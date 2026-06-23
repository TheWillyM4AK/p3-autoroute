"""Resource and data path resolution (PyInstaller/frozen compatible)."""
import os
import sys


def web_dir() -> str:
    """Frontend folder (web/), both in development and when packaged."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "p3autoroute", "web")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def data_dir() -> str:
    """Folder for persisted user data (presets, settings).

    Defaults to ~/.p3autoroute, overridable with the P3AUTOROUTE_DATA env var.
    """
    override = os.environ.get("P3AUTOROUTE_DATA")
    base = override or os.path.join(os.path.expanduser("~"), ".p3autoroute")
    os.makedirs(base, exist_ok=True)
    return base
