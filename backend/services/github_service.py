"""GitHub REST API から対象日のコミット履歴を取得する。

- author はサーバサイド絞り込みせず、client 側で `commit.author.login` を照合する
  （ローカル git config の author.name が違っても GitHub 側で本人アカウントに紐付いていれば拾える）
- merge commit (parents >= 2) は除外
- タイムゾーンは JST (UTC+9) 固定
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from services.secrets_service import get_github_auth


logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
GITHUB_API = "https://api.github.com"
UA = "daily-report-generator/1.0"
DEFAULT_TIMEOUT = 10

# デフォルト対象リポジトリ（2026-07 の活動実績ベース）
DEFAULT_REPOS: list[str] = [
    "msg-network/msg-native-app",
    "msg-network/msg-app",
    "msg-network/msg-app-terms",
    "msg-network/daily-report-generator",
    "msg-network/attendance-monitor",
    "msg-network-org/notion-automation",
    "msg-network-org/internal-tools",
    "msg-network-org/summer-planning-form",
    "msg-network-org/executive-app",
    "msg-network-org/ss-application-extractor",
    "msg-network-org/kodama",
    "msg-network-org/internal-ai-agent",
    "msg-network-org/t-msg",
]


def _headers() -> dict[str, str]:
    auth = get_github_auth()
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {auth['personal_token']}",
        "User-Agent": UA,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_logins() -> set[str]:
    """許可する author login の集合。カンマ区切りで複数指定可 (例: "shockbox-dev,msg-network")。"""
    raw = get_github_auth()["login"]
    return {s.strip() for s in raw.split(",") if s.strip()}


def _http_get(url: str) -> tuple[int, dict, list | dict]:
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, dict(resp.headers), data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("GitHub API %s -> %s: %s", url, e.code, body[:200])
        return e.code, dict(e.headers), []


def fetch_commits_for_repo(repo: str, date_iso: str, logins: set[str]) -> list[dict]:
    """1 リポジトリ・1 日ぶんのコミット (author in logins, no merges) を返す。"""
    day = datetime.fromisoformat(date_iso).date()
    since = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=JST).isoformat()
    until = (
        datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=JST) + timedelta(seconds=1)
    ).isoformat()

    qs = urllib.parse.urlencode({"since": since, "until": until, "per_page": 100})
    url = f"{GITHUB_API}/repos/{repo}/commits?{qs}"
    status, _headers_, data = _http_get(url)
    if status == 404 or status == 409:  # empty repo / no access
        return []
    if status >= 400 or not isinstance(data, list):
        return []

    out: list[dict] = []
    for c in data:
        if len(c.get("parents", [])) >= 2:
            continue  # merge commit
        author = c.get("author") or {}
        if author.get("login") not in logins:
            continue
        commit_meta = c.get("commit", {})
        out.append(
            {
                "sha": c.get("sha", "")[:7],
                "repo": repo,
                "message": commit_meta.get("message", "").split("\n", 1)[0],
                "date_iso": commit_meta.get("author", {}).get("date"),
            }
        )
    return out


def fetch_all_commits(date_iso: str, repos: list[str] | None = None) -> list[dict]:
    """対象日ぶんのコミットを全リポ横断で返す（時刻昇順）。

    リポジトリごとの GitHub API 呼び出しはスレッドプールで並列化する。
    """
    logins = _get_logins()
    repos = repos or DEFAULT_REPOS
    all_commits: list[dict] = []

    def _one(repo: str) -> list[dict]:
        try:
            return fetch_commits_for_repo(repo, date_iso, logins)
        except Exception as e:
            logger.warning("skip repo %s: %s", repo, e)
            return []

    max_workers = min(16, len(repos)) or 1
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for result in ex.map(_one, repos):
            all_commits.extend(result)

    all_commits.sort(key=lambda c: c.get("date_iso") or "")
    return all_commits


_ISSUE_PATTERN = re.compile(r"#(\d+)")


def group_by_issue(commits: list[dict]) -> list[dict]:
    """コミットを (repo, 先頭issue番号) でグルーピングして返す。

    Returns: [{"repo": ..., "issue": "#NNN" | None, "commits": [...], "messages": [str]}]
    """
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for c in commits:
        m = _ISSUE_PATTERN.search(c["message"])
        issue = m.group(0) if m else ""
        key = (c["repo"], issue)
        if key not in buckets:
            order.append(key)
        buckets[key].append(c)

    result = []
    for repo, issue in order:
        cs = buckets[(repo, issue)]
        messages = [c["message"] for c in cs]
        result.append(
            {
                "repo": repo,
                "issue": issue or None,
                "commits": cs,
                "messages": messages,
            }
        )
    return result


def format_commits_for_prompt(date_iso: str, commits: list[dict]) -> str:
    """Bedrock プロンプトに投げる用にコミット群を整形する。"""
    if not commits:
        return f"日付: {date_iso}\n本日のコミット: なし"

    grouped = group_by_issue(commits)
    lines = [f"日付: {date_iso}", "本日のコミット履歴 (issue/PR ごとにまとめ):"]
    for g in grouped:
        head = f"[{g['repo']}]"
        if g["issue"]:
            head += f" {g['issue']}"
        head += f" ({len(g['commits'])} commits)"
        lines.append(head)
        for m in g["messages"]:
            lines.append(f"  - {m}")
    return "\n".join(lines)
