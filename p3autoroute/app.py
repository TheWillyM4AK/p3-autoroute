"""Desktop application (primary mode): native window with PyWebView.

The Python backend is exposed as the SINGLE bridge via `js_api`: the frontend
calls `window.pywebview.api.<method>(params)` and receives a promise with the
result. No port or HTTP server is opened.

Run:  python -m p3autoroute
"""
from __future__ import annotations

import os

import webview

from .api import Api
from .paths import web_dir


def run(width: int = 1240, height: int = 820) -> None:
    api = Api()
    index = os.path.join(web_dir(), "index.html")
    window = webview.create_window(
        "p3-autoroute — route editor",
        url=index,
        js_api=api,
        width=width,
        height=height,
        min_size=(900, 600),
    )
    api.window = window  # enables the native folder picker
    webview.start()
