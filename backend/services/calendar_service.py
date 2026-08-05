"""Google Calendar REST API を使い、対象日の予定一覧を取得する。

- OAuth2 refresh token で access token を発行 (google-auth 依存なし、REST 直叩き)
- primary カレンダーを対象とする
- 終日予定は無視 (dateTime のみ考慮)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from services.secrets_service import get_google_oauth


logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL_API = "https://www.googleapis.com/calendar/v3"
DEFAULT_TIMEOUT = 10


def _get_access_token() -> str:
    creds = get_google_oauth()
    body = urllib.parse.urlencode(
        {
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["access_token"]


def _fetch_events(date_iso: str, access_token: str) -> list[dict]:
    day = datetime.fromisoformat(date_iso).date()
    time_min = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=JST).isoformat()
    time_max = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=JST).isoformat()
    qs = urllib.parse.urlencode(
        {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 100,
        }
    )
    url = f"{CAL_API}/calendars/primary/events?{qs}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("Calendar API %s: %s", e.code, body[:200])
        return []
    return data.get("items", [])


def _event_time(event: dict, key: str) -> datetime | None:
    v = event.get(key, {}).get("dateTime")
    if not v:
        return None
    return datetime.fromisoformat(v).astimezone(JST)


def fetch_day_events(date_iso: str) -> list[dict]:
    """対象日の予定 (dateTime を持つもののみ・終日は除外) を JST 時刻つきで返す。

    認証失敗などで取得できない場合は空リストを返す（フェイルセーフ）。
    Returns: [{"title": str, "start": iso8601, "end": iso8601}]
    """
    try:
        token = _get_access_token()
    except Exception as e:
        logger.warning("google oauth failed: %s", e)
        return []

    events = _fetch_events(date_iso, token)

    out: list[dict] = []
    for ev in events:
        start = _event_time(ev, "start")
        end = _event_time(ev, "end")
        if not start or not end:
            continue
        out.append(
            {
                "title": ev.get("summary") or "(無題)",
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )
    return out
