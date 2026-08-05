"""AWS Secrets Manager から機密情報を取得する。

ローカル開発時は環境変数 (.env) フォールバックを持つ。

- daily-report/github-auth  → { "login": "...", "personal_token": "..." }
- daily-report/google-oauth → { "client_id": "...", "client_secret": "...", "refresh_token": "..." }
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

import boto3


AWS_REGION = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "ap-northeast-1"))
AWS_PROFILE = os.environ.get("AWS_PROFILE")

GITHUB_SECRET_NAME = os.environ.get("GITHUB_SECRET_NAME", "daily-report/github-auth")
GOOGLE_SECRET_NAME = os.environ.get("GOOGLE_SECRET_NAME", "daily-report/google-oauth")


def _session_kwargs() -> dict:
    kw: dict = {"region_name": AWS_REGION}
    if AWS_PROFILE:
        kw["profile_name"] = AWS_PROFILE
    return kw


@lru_cache(maxsize=8)
def _fetch_secret(name: str) -> dict:
    session = boto3.Session(**_session_kwargs())
    client = session.client("secretsmanager")
    resp = client.get_secret_value(SecretId=name)
    body = resp.get("SecretString")
    if not body:
        raise RuntimeError(f"Secret {name} has no SecretString")
    return json.loads(body)


def get_github_auth() -> dict:
    """{'login': str, 'personal_token': str} を返す。

    ローカルは .env の GITHUB_LOGIN / GITHUB_PERSONAL_TOKEN 優先。
    """
    login_env = os.environ.get("GITHUB_LOGIN")
    tok_env = os.environ.get("GITHUB_PERSONAL_TOKEN")
    if login_env and tok_env:
        return {"login": login_env, "personal_token": tok_env}
    return _fetch_secret(GITHUB_SECRET_NAME)


def get_google_oauth() -> dict:
    """{'client_id','client_secret','refresh_token'} を返す。

    ローカルは .env の GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN 優先。
    """
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    cs = os.environ.get("GOOGLE_CLIENT_SECRET")
    rt = os.environ.get("GOOGLE_REFRESH_TOKEN")
    if cid and cs and rt:
        return {"client_id": cid, "client_secret": cs, "refresh_token": rt}
    return _fetch_secret(GOOGLE_SECRET_NAME)
