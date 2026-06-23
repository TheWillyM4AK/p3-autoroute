"""Persistent application settings (JSON in the data folder).

Used to remember things between launches, e.g. the last opened AutoRoute folder.
"""
from __future__ import annotations

import json
import os

from .paths import data_dir

_FILENAME = "settings.json"


def _path() -> str:
    return os.path.join(data_dir(), _FILENAME)


def load() -> dict:
    path = _path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def save(settings: dict) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def get(key: str, default=None):
    return load().get(key, default)


def set(key: str, value) -> None:
    settings = load()
    settings[key] = value
    save(settings)
