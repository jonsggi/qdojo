#!/usr/bin/env python3
"""Serve apps/web locally the way the production nginx does (Dockerfile).

  uv run qdojo combat api --db rm.sqlite --export DIR --port 8795 &
  python3 scripts/dev-site.py --api http://127.0.0.1:8795 --port 8080

- /data/combat/v1/X  -> {api}/X, falling back to apps/web/data/combat/v1/X (the baked copy)
- /api/v1/...        -> {api}/api/v1/..., or a 503 JSON error when the API is down
- anything else      -> apps/web

Development only: GET/HEAD, stdlib, binds 127.0.0.1 by default.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

WEB = Path(__file__).resolve().parents[1] / "apps" / "web"


class Handler(BaseHTTPRequestHandler):
    api = ""

    def log_message(self, fmt, *args):
        pass

    def _reply(self, status, body: bytes, ctype: str, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _proxy(self, url: str):
        req = urllib.request.Request(url, headers={k: v for k, v in self.headers.items()
                                                   if k.lower() in ("accept", "if-none-match")})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                keep = [(k, v) for k, v in r.headers.items() if k.lower() in ("cache-control", "etag", "last-modified")]
                return r.status, r.read(), r.headers.get("Content-Type", "application/json"), keep
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "application/json"), []
        except OSError:
            return None

    def _file(self, rel: str):
        target = (WEB / rel.lstrip("/")).resolve()
        if target.is_dir():
            target = target / "index.html"
        if WEB not in target.parents or not target.is_file():
            return self._reply(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._reply(200, target.read_bytes(), ctype, [("Cache-Control", "no-cache")])

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        query = ("?" + urlsplit(self.path).query) if urlsplit(self.path).query else ""
        if path.startswith("/api/v1/"):
            got = self._proxy(self.api + path + query)
            if got is None or got[0] in (502, 503, 504):
                body = json.dumps({"error": {"status": 503, "code": "api_down", "message": "read API unreachable"}})
                return self._reply(503, body.encode(), "application/json")
            return self._reply(got[0], got[1], got[2], got[3])
        if path.startswith("/data/combat/v1/"):
            got = self._proxy(self.api + "/" + path[len("/data/combat/v1/"):] + query)
            if got is not None and got[0] < 400:
                return self._reply(got[0], got[1], got[2], got[3])
            return self._file(path)                          # the baked copy
        return self._file(path)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", required=True, help="base URL of `qdojo combat api`")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args()
    Handler.api = a.api.rstrip("/")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"site on http://{a.host}:{a.port}/ (API {Handler.api})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
