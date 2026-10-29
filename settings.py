"""Збереження налаштувань між запусками (невеликий JSON-файл).

Windows: ``%APPDATA%\\yt-downloader\\settings.json``;
інші системи: ``~/.config/yt-downloader/settings.json``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR_NAME = "yt-downloader"
SETTINGS_FILENAME = "settings.json"
_IS_WINDOWS = os.name == "nt"


def config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if _IS_WINDOWS and appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


def settings_path() -> Path:
    return config_dir() / SETTINGS_FILENAME


def load_settings(path: str | os.PathLike | None = None) -> dict:
    """Повертає збережені налаштування або ``{}``, якщо файлу немає чи він пошкоджений."""
    path = Path(path) if path else settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data: dict, path: str | os.PathLike | None = None) -> bool:
    """Записує налаштування. Помилки запису не критичні — повертає ``False``."""
    path = Path(path) if path else settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError:
        return False
    return True
