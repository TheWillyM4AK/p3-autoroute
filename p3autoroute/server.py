"""FALLBACK web server (standard library only).

The primary mode is the native window (`app.py`, PyWebView + js_api). This
server exists to debug in a real browser: the frontend detects there is no
js_api bridge and uses fetch against this API. It dispatches to the same `Api`
class.

Run:  python -m p3autoroute --web
"""
from __future__ import annotations

import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .api import Api, PUBLIC_METHODS
from .paths import web_dir

WEB_DIR = web_dir()
_CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript",
                  ".css": "text/css", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    server_version = "p3autoroute"
    api = Api()

    def _send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def log_message(self, *args):
        pass

    def _dispatch(self, name, params):
        if name not in PUBLIC_METHODS:
            return self._json({"ok": False, "error": "unknown endpoint"}, 404)
        try:
            return self._json(getattr(self.api, name)(params))
        except Exception as exc:  # noqa: BLE001
            return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/api/"):
            return self._dispatch(path[len("/api/"):].replace("/", "_"), {})
        return self._static(path.lstrip("/"))

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._json({"ok": False, "error": "unknown endpoint"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        params = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        return self._dispatch(path[len("/api/"):].replace("/", "_"), params)

    def _static(self, rel):
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain")
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            self._send(200, f.read(), _CONTENT_TYPES.get(ext, "application/octet-stream"))


def serve(host="127.0.0.1", port=8765, open_browser=True):
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"p3-autoroute (web mode)  ->  {url}   (Ctrl+C to quit)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")
        httpd.shutdown()
