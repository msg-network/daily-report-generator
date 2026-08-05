"""Google OAuth2 の一発設定スクリプト (Loopback flow)。

前提:
  1. Google Cloud Console で OAuth 2.0 クライアント ID (Desktop app) を作成
  2. Calendar API を有効化
  3. OAuth 同意画面 User type = Internal (Workspace 配下推奨)

使い方:
  poetry run python scripts/setup_google_oauth.py
  # 非対話環境 (stdin が無い場合) は引数で渡す:
  poetry run python scripts/setup_google_oauth.py --client-id XXX --client-secret YYY

対話フローで URL が表示される → ブラウザで承認 →
  ローカル HTTP サーバがコールバックを受信 → refresh info が標準出力に出る。

出力を Secrets Manager (daily-report/google-oauth) に手動投入する:
  # NOTE: このコマンドは shell から直接実行してください（Claude 経由の自動実行は auto guard に弾かれます）
  aws secretsmanager create-secret \\
    --name daily-report/google-oauth \\
    --secret-string '{"client_id":"...","client_secret":"...","refresh_token":"..."}' \\
    --profile itop --region ap-northeast-1

なぜ Loopback フローか:
  Google が 2022 年に OOB (urn:ietf:wg:oauth:2.0:oob) フローを廃止したため、
  新規 Desktop app OAuth クライアントは http://localhost:PORT にリダイレクトする必要がある。
  https://developers.google.com/identity/protocols/oauth2/native-app#redirect-uri_loopback

依存ライブラリ不要（stdlib のみで完結）。
"""

from __future__ import annotations

import argparse
import getpass
import json
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer


AUTHZ_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/calendar.readonly"


class _CallbackHandler(BaseHTTPRequestHandler):
    received_code: str | None = None
    received_error: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _CallbackHandler.received_code = params["code"][0]
            body = "<h2>認可完了</h2><p>このタブは閉じて構いません。ターミナルに戻ってください。</p>"
        else:
            _CallbackHandler.received_error = params.get("error", ["unknown"])[0]
            body = f"<h2>認可失敗</h2><p>{_CallbackHandler.received_error}</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # suppress default access log


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_code(port: int, timeout: int = 300) -> str:
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    server.server_close()
    if _CallbackHandler.received_error:
        raise RuntimeError(f"OAuth denied: {_CallbackHandler.received_error}")
    if not _CallbackHandler.received_code:
        raise RuntimeError("認可コード取得タイムアウト")
    return _CallbackHandler.received_code


def main() -> int:
    print("Google OAuth 初回セットアップ (Calendar readonly, Loopback flow)")
    print("-" * 60)

    parser = argparse.ArgumentParser(description="Google OAuth 初回セットアップ")
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--client-secret", default=None)
    args = parser.parse_args()

    client_id = (args.client_id or input("client_id: ")).strip()
    client_secret = (args.client_secret or getpass.getpass("client_secret: ")).strip()
    if not client_id or not client_secret:
        print("client_id / client_secret は必須です", file=sys.stderr)
        return 1

    port = _free_port()
    redirect_uri = f"http://localhost:{port}"

    qs = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",  # 毎回 refresh_token を返させる
        }
    )
    authz = f"{AUTHZ_URL}?{qs}"

    print(f"\nブラウザを開きます（開かない場合は下記 URL を手動で開いてください）:\n\n  {authz}\n")
    try:
        webbrowser.open(authz)
    except Exception:
        pass

    print(f"localhost:{port} でコールバック待機中... (5 分でタイムアウト)")
    code = _wait_for_code(port)
    print("認可コード取得 OK。access/refresh を交換します...")

    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    refresh = data.get("refresh_token")
    if not refresh:
        print(
            "refresh_token が返ってこなかった。"
            "https://myaccount.google.com/permissions で対象アプリの権限を revoke してから再実行してみて:",
            file=sys.stderr,
        )
        print(json.dumps(data, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
    }
    print("\n[OK] 以下を Secrets Manager (daily-report/google-oauth) に登録してください:\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("\nローカルで試す場合は backend/.env に:")
    print(f"  GOOGLE_CLIENT_ID={client_id}")
    print("  GOOGLE_CLIENT_SECRET=***")
    print(f"  GOOGLE_REFRESH_TOKEN={refresh}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
