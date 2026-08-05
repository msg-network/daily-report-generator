"""コミット履歴から業務日報スロットを自動生成するエンドポイント。

個人の GitHub / Google Calendar 認証情報で動くため、共有トークン
(X-Api-Token ヘッダー) による簡易認証を掛けている。
期待値は環境変数 FROM_COMMITS_TOKEN、無ければ Secrets Manager の
daily-report/api-token (プレーン文字列) から取得する。
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import date as date_type
from datetime import datetime, time, timedelta

import boto3
from fastapi import APIRouter, Header, HTTPException

from schemas.nippou import FromCommitsRequest, FromCommitsResponse
from services.bedrock_service import parse_from_commits
from services.calendar_service import JST, fetch_day_events
from services.github_service import fetch_all_commits, format_commits_for_prompt


logger = logging.getLogger(__name__)

router = APIRouter()

API_TOKEN_SECRET_ID = "daily-report/api-token"

SHIFT_HOURS = {"normal": range(9, 18), "late": range(13, 22)}
SLOT_MAX_CHARS = 20


def _events_to_slots(date_iso: str, events: list[dict], shift_pattern: str) -> dict[str, str]:
    """カレンダー予定を勤務時間内の1時間スロットに割り当てる。

    スロット h は [h:00, h+1:00) をカバーし、重なる予定のタイトルを入れる。
    同一スロットに複数の予定が重なる場合は「・」で連結して20文字に切り詰める。
    """
    day = date_type.fromisoformat(date_iso)
    occupied: dict[str, str] = {}
    for hour in SHIFT_HOURS[shift_pattern]:
        slot_start = datetime.combine(day, time(hour), tzinfo=JST)
        slot_end = slot_start + timedelta(hours=1)
        titles = [
            ev["title"]
            for ev in events
            if datetime.fromisoformat(ev["start"]) < slot_end
            and datetime.fromisoformat(ev["end"]) > slot_start
        ]
        if titles:
            occupied[str(hour)] = "・".join(titles)[:SLOT_MAX_CHARS]
    return occupied


# 取得成功時のみキャッシュする（None を lru_cache すると、後からシークレットを
# 作成しても Lambda 再起動まで 503 が続いてしまうため）
_cached_token: str | None = None


def _expected_token() -> str | None:
    global _cached_token
    if _cached_token:
        return _cached_token

    env_token = os.environ.get("FROM_COMMITS_TOKEN")
    if env_token:
        _cached_token = env_token.strip()
        return _cached_token

    try:
        region = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "ap-northeast-1"))
        session_kwargs = {"region_name": region}
        if os.environ.get("AWS_PROFILE"):
            session_kwargs["profile_name"] = os.environ["AWS_PROFILE"]
        sm = boto3.Session(**session_kwargs).client("secretsmanager")
        _cached_token = sm.get_secret_value(SecretId=API_TOKEN_SECRET_ID)["SecretString"].strip()
        return _cached_token
    except Exception as e:
        logger.warning("api token の取得に失敗: %s", e)
        return None


def _verify_token(provided: str | None) -> None:
    expected = _expected_token()
    if expected is None:
        raise HTTPException(status_code=503, detail="アクセストークンがサーバーに未設定です")
    if not provided or not secrets.compare_digest(provided.strip(), expected):
        raise HTTPException(status_code=401, detail="アクセストークンが正しくありません")


@router.post("/from-commits", response_model=FromCommitsResponse)
async def from_commits(
    request: FromCommitsRequest,
    x_api_token: str | None = Header(default=None, alias="X-Api-Token"),
):
    _verify_token(x_api_token)

    if request.shift_pattern not in ("normal", "late"):
        raise HTTPException(status_code=400, detail="shift_pattern は 'normal' または 'late' を指定してください")

    try:
        commits = fetch_all_commits(request.date, request.repos)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GitHub からのコミット取得に失敗: {e}")

    commits_text = format_commits_for_prompt(request.date, commits)

    events = fetch_day_events(request.date)
    occupied = _events_to_slots(request.date, events, request.shift_pattern)

    try:
        result = parse_from_commits(
            date=request.date,
            shift_pattern=request.shift_pattern,
            commits_text=commits_text,
            occupied_slots=occupied,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI解析に失敗しました: {e}")

    # カレンダー由来のスロットはコード側で確定させる（モデル出力に依存しない）
    slots = result["slots"]
    slots.update(occupied)

    return FromCommitsResponse(
        shift_pattern=request.shift_pattern,
        slots=slots,
        commits_summary=commits_text,
        calendar_events=events,
    )
