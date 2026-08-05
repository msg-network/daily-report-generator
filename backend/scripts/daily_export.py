"""日次の業務日報を自動生成して指定フォルダに保存するスクリプト。

launchd から毎日 23:30 に起動される想定（スリープ中だった場合は次回起床時に実行）。

- コミットが1件も無い日は何も生成しない
- 出力ファイルが既に存在する日はスキップ（二重生成防止）
- 午前中の実行はスリープからのリカバリーとみなし、前日ぶんを生成する

設定は ~/.config/nippou/config.json から読む:
  {
    "api_base": "https://nippou.msg-network.app",
    "api_token": "...",
    "shift_pattern": "normal",
    "department": "...",
    "name": "...",
    "output_dir": "~/Documents/Work/報告関連/09_業務日報"
  }

出力先は output_dir 直下の月フォルダ（例: 8月/業務日報_2026_08_05.docx）。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path("~/.config/nippou/config.json").expanduser()
JST = timezone(timedelta(hours=9))
TIMEOUT = 120


def log(msg: str) -> None:
    print(f"[{datetime.now(JST).isoformat(timespec='seconds')}] {msg}")


def target_date() -> str:
    """正午前の実行は前日ぶんのリカバリー実行とみなす。"""
    now = datetime.now(JST)
    day = now.date() - timedelta(days=1) if now.hour < 12 else now.date()
    return day.isoformat()


def post_json(url: str, payload: dict, headers: dict) -> tuple[int, bytes]:
    body = json.dumps(payload).encode()
    h = {"Content-Type": "application/json"}
    h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text())
    date = target_date()

    month = int(date.split("-")[1])
    out_dir = Path(config["output_dir"]).expanduser() / f"{month}月"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"業務日報_{date.replace('-', '_')}.docx"
    if out_path.exists():
        log(f"{out_path.name} は既に存在するためスキップ")
        return 0

    auth = {"X-Api-Token": config["api_token"]}

    # 1. コミット履歴＋カレンダーからスロット生成
    code, body = post_json(
        f"{config['api_base']}/api/from-commits",
        {"date": date, "shift_pattern": config["shift_pattern"]},
        auth,
    )
    if code != 200:
        log(f"from-commits 失敗 ({code}): {body.decode(errors='replace')[:300]}")
        return 1
    result = json.loads(body)

    if "本日のコミット: なし" in result["commits_summary"]:
        log(f"{date} はコミットなしのため生成スキップ")
        return 0

    # 2. Word 生成
    code, body = post_json(
        f"{config['api_base']}/api/generate",
        {
            "date": date,
            "shift_pattern": config["shift_pattern"],
            "slots": result["slots"],
            "department": config["department"],
            "name": config["name"],
            "notes": "",
        },
        auth,
    )
    if code != 200:
        log(f"generate 失敗 ({code}): {body.decode(errors='replace')[:300]}")
        return 1

    out_path.write_bytes(body)
    filled = sum(1 for v in result["slots"].values() if v)
    log(f"{out_path} を生成した（スロット {filled} 個 / 予定 {len(result.get('calendar_events', []))} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
