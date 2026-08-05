"""日次の業務日報を自動生成して指定フォルダに保存するスクリプト。

launchd から毎朝 05:30 に起動される想定（スリープ中だった場合は次回起床時に実行）。
「1日」は朝5時区切り（前日5:00〜当日5:00）なので、深夜3〜4時の作業も前日ぶんに含めて
朝の実行で前日の日報を確定生成する。
引数で日付を渡せば過去日の一括生成にも使える:

  python3 daily_export.py                          # 当日ぶん（launchd用）
  python3 daily_export.py 2026-07-15               # 指定日
  python3 daily_export.py 2026-07-01..2026-07-31   # 範囲指定（複数指定・混在も可）

- コミットが1件も無い日は何も生成しない
- 出力ファイルが既に存在する日はスキップ（二重生成防止）
- 引数なしのときは「直近に完了した作業日」（朝5時区切りの前日）を対象にする

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
import time
import urllib.error
import urllib.request
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path("~/.config/nippou/config.json").expanduser()
JST = timezone(timedelta(hours=9))
TIMEOUT = 120


def log(msg: str) -> None:
    print(f"[{datetime.now(JST).isoformat(timespec='seconds')}] {msg}")


def target_date() -> str:
    """直近に完了した作業日を返す。

    作業日は朝5時区切り（D 05:00〜D+1 05:00）。現在進行中の作業日の
    1日前が「確定済みの直近作業日」になる。
    例: 8/6 05:30 実行 → 8/5 ぶん / 8/6 14:00 実行（起床リカバリー）→ 8/5 ぶん
    """
    now = datetime.now(JST)
    current_workday = (now - timedelta(hours=5)).date()
    return (current_workday - timedelta(days=1)).isoformat()


def post_json(url: str, payload: dict, headers: dict) -> tuple[int, bytes]:
    body = json.dumps(payload).encode()
    h = {"Content-Type": "application/json"}
    h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    # スリープ解除直後などネットワーク未復帰のことがあるため、接続系エラーはリトライする
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except urllib.error.URLError as e:
            if attempt == 3:
                raise
            log(f"接続エラー（{e.reason}）。30秒後にリトライ ({attempt + 1}/3)")
            time.sleep(30)
    raise RuntimeError("unreachable")


def parse_date_args(args: list[str]) -> list[str]:
    """引数の日付・範囲指定を日付リストに展開する。"""
    dates: list[str] = []
    for arg in args:
        if ".." in arg:
            start_s, end_s = arg.split("..", 1)
            start, end = date_type.fromisoformat(start_s), date_type.fromisoformat(end_s)
            if end < start:
                raise ValueError(f"範囲の終了日が開始日より前: {arg}")
            d = start
            while d <= end:
                dates.append(d.isoformat())
                d += timedelta(days=1)
        else:
            dates.append(date_type.fromisoformat(arg).isoformat())
    return dates


def generate_for_date(config: dict, date: str) -> int:
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


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text())
    dates = parse_date_args(sys.argv[1:]) if len(sys.argv) > 1 else [target_date()]

    exit_code = 0
    for i, date in enumerate(dates):
        if i > 0:
            time.sleep(10)  # 一括生成時は GitHub API レートリミット対策で間隔を空ける
        try:
            if generate_for_date(config, date) != 0:
                exit_code = 1
        except Exception as e:
            log(f"{date} の生成でエラー: {e}")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
