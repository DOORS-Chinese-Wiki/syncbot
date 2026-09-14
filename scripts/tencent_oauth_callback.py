# -*- coding: utf-8 -*-
"""Receive the Tencent Docs OAuth callback and persist the token pair."""
from __future__ import annotations

import argparse
import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import achievements_sync  # noqa: E402


class CallbackHandler(BaseHTTPRequestHandler):
    redirect_uri = ""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/oauth/callback":
            self.send_error(404)
            return

        query = parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        error = (query.get("error_description") or query.get("error") or [""])[0]
        if error:
            self._respond(400, f"授权失败：{html.escape(error)}")
            return
        if not code:
            self._respond(400, "回调中没有 code")
            return

        try:
            client = achievements_sync.TencentDocsClient()
            client.exchange_code(code, self.redirect_uri)
        except Exception as exc:  # pragma: no cover - network/service failure
            self._respond(500, f"换取 Token 失败：{html.escape(str(exc))}")
            return
        self._respond(
            200,
            "授权完成，Access Token 和 Refresh Token 已保存到服务器的 "
            f"{achievements_sync.TOKEN_FILE}。可以关闭此页面。",
        )

    def _respond(self, status: int, message: str) -> None:
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<title>DOORS Wiki OAuth</title>"
            "<style>body{font:16px sans-serif;max-width:720px;margin:80px auto;"
            "padding:0 20px;line-height:1.6}</style>"
            f"<p>{message}</p>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--redirect-uri", required=True)
    args = parser.parse_args()

    CallbackHandler.redirect_uri = args.redirect_uri
    server = ThreadingHTTPServer((args.host, args.port), CallbackHandler)
    print(f"OAuth callback listening on http://{args.host}:{args.port}/oauth/callback")
    print(f"External redirect URI: {args.redirect_uri}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
