"""Entry point.

  python -m p3autoroute            -> native window (PyWebView, primary mode)
  python -m p3autoroute --web      -> fallback web server (browser)
"""
import argparse


def main() -> None:
    ap = argparse.ArgumentParser(description="Patrician III .rou route editor")
    ap.add_argument("--web", action="store_true",
                    help="use the fallback web server instead of the native window")
    ap.add_argument("--host", default="127.0.0.1", help="(--web mode)")
    ap.add_argument("--port", type=int, default=8765, help="(--web mode)")
    ap.add_argument("--no-browser", action="store_true", help="(--web mode) do not open the browser")
    args = ap.parse_args()

    if args.web:
        from .server import serve
        serve(args.host, args.port, open_browser=not args.no_browser)
    else:
        from .app import run
        run()


if __name__ == "__main__":
    main()
