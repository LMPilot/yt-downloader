"""Перевірка та встановлення оновлень із GitHub Releases (без GUI).

Як це працює:

1. ``check_for_update`` читає ``releases/latest`` через GitHub API і повертає
   ``ReleaseInfo``, якщо там є новіша версія з файлом ``yt-downloader.exe``.
2. ``download_update`` завантажує новий exe у тимчасовий файл поруч із поточним
   і звіряє розмір та SHA256 з файлом ``yt-downloader.exe.sha256`` з релізу.
3. ``launch_update_helper`` записує невеликий ``.cmd``-скрипт і запускає його у
   фоні. Запущений exe на Windows не можна перезаписати, тож скрипт чекає, поки
   програма закриється, замінює exe (стара версія лишається як ``.old``, при
   помилці повертається назад), запускає нову версію і видаляє себе.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = "LMPilot/yt-downloader"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET_NAME = "yt-downloader.exe"
CHECKSUM_SUFFIX = ".sha256"
HELPER_NAME = "yt-downloader-update.cmd"
USER_AGENT = "yt-downloader-updater"
CHECK_TIMEOUT = 5
DOWNLOAD_TIMEOUT = 30
CHUNK_SIZE = 256 * 1024

_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?\s*$", re.IGNORECASE)
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


class UpdateError(Exception):
    """Помилка оновлення з повідомленням для користувача."""


class UpdateCancelled(UpdateError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    asset_url: str
    asset_size: int
    checksum_url: str | None


# ------------------------------------------------------------- версії --

def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """``"v1.2.3"`` → ``(1, 2, 3)``; ``"1.2"`` → ``(1, 2, 0)``.

    Передрелізні версії (``1.2.3-rc1``) та сміття → ``None``.
    """
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text)
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def format_version(parsed: tuple[int, int, int]) -> str:
    return ".".join(str(p) for p in parsed)


def is_newer(remote: str | None, current: str | None) -> bool:
    """Чи ``remote`` новіша за ``current``. Непарсабельна ``remote`` — ні."""
    remote_v = parse_version(remote)
    if remote_v is None:
        return False
    current_v = parse_version(current)
    return current_v is None or remote_v > current_v


# ------------------------------------------------------------ реліз ----

def parse_release(data: object, asset_name: str = ASSET_NAME) -> ReleaseInfo | None:
    """Розбирає JSON релізу з GitHub API.

    Повертає ``None`` для чернеток, передрелізів, тегів не у форматі версії та
    релізів без потрібного файлу.
    """
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name") or ""
    parsed = parse_version(tag)
    if parsed is None:
        return None
    assets = [a for a in data.get("assets") or [] if isinstance(a, dict)]
    by_name = {a.get("name"): a for a in assets}
    exe = by_name.get(asset_name)
    if not exe or not exe.get("browser_download_url"):
        return None
    checksum = by_name.get(asset_name + CHECKSUM_SUFFIX) or {}
    return ReleaseInfo(
        version=format_version(parsed),
        tag=tag,
        notes=(data.get("body") or "").strip(),
        page_url=data.get("html_url") or RELEASES_PAGE,
        asset_url=exe["browser_download_url"],
        asset_size=int(exe.get("size") or 0),
        checksum_url=checksum.get("browser_download_url"),
    )


def _open(url: str, timeout: float, accept: str = "*/*"):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — лише https


def fetch_latest_release(timeout: float = CHECK_TIMEOUT) -> ReleaseInfo | None:
    """Останній реліз або ``None``. Мережеві помилки — ``OSError``/``ValueError``."""
    with _open(LATEST_RELEASE_API, timeout, "application/vnd.github+json") as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_release(data)


def check_for_update(current: str, timeout: float = CHECK_TIMEOUT) -> ReleaseInfo | None:
    """Повертає новіший реліз або ``None``, якщо оновлень немає."""
    release = fetch_latest_release(timeout)
    if release and is_newer(release.version, current):
        return release
    return None


# -------------------------------------------------------- завантаження --

def is_frozen() -> bool:
    """Чи запущено зібраний PyInstaller-ом exe (а не ``python app.py``)."""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    """Шлях до exe. У one-file збірці код працює з тимчасової папки ``_MEI…``,
    але ``sys.executable`` вказує саме на exe, який запустив користувач."""
    return Path(sys.executable).resolve()


def update_paths(exe: Path) -> tuple[Path, Path, Path]:
    """(новий файл, резервна копія, скрипт) — усе поруч із exe."""
    return (exe.with_name(exe.name + ".new"),
            exe.with_name(exe.name + ".old"),
            exe.with_name(HELPER_NAME))


def parse_checksum(text: str) -> str:
    """Дістає SHA256 з вмісту ``.sha256`` (``<hash>  <файл>`` або просто hash)."""
    match = _SHA256_RE.search(text or "")
    if not match:
        raise UpdateError("Файл контрольної суми релізу пошкоджений.")
    return match.group(1).lower()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_size: int, expected_sha256: str) -> None:
    size = path.stat().st_size
    if expected_size and size != expected_size:
        raise UpdateError(f"Розмір завантаженого файлу не збігається "
                          f"({size} замість {expected_size} байт).")
    actual = sha256_of(path)
    if actual != expected_sha256.lower():
        raise UpdateError("Контрольна сума SHA256 не збігається — файл пошкоджений.")


def download_update(release: ReleaseInfo, dest: Path,
                    on_progress: Callable[[int, int], None] | None = None,
                    is_cancelled: Callable[[], bool] | None = None,
                    timeout: float = DOWNLOAD_TIMEOUT) -> Path:
    """Завантажує exe з релізу в ``dest`` і перевіряє його.

    При будь-якій помилці ``dest`` видаляється і кидається ``UpdateError``.
    """
    if not release.checksum_url:
        raise UpdateError("У релізі немає файлу контрольної суми "
                          f"{ASSET_NAME}{CHECKSUM_SUFFIX} — оновлення скасовано.")
    try:
        with _open(release.checksum_url, timeout) as resp:
            expected = parse_checksum(resp.read(4096).decode("utf-8", "replace"))
        with _open(release.asset_url, timeout, "application/octet-stream") as resp, \
                open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or release.asset_size or 0)
            done = 0
            while True:
                if is_cancelled and is_cancelled():
                    raise UpdateCancelled("Оновлення скасовано.")
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        verify_file(dest, release.asset_size, expected)
    except UpdateError:
        _remove_quietly(dest)
        raise
    except (OSError, ValueError) as exc:
        _remove_quietly(dest)
        raise UpdateError(f"Не вдалося завантажити оновлення: {exc}") from exc
    return dest


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# ------------------------------------------------- заміна exe (Windows) --

# Шляхи передаються через змінні середовища, а не вписуються в скрипт: так
# кирилиця, пробіли та символи на кшталт «&» у шляхах не ламають cmd.exe
# (він читає .cmd у кодуванні OEM, а середовище — у Unicode).
ENV_TARGET = "YTD_UPDATE_TARGET"
ENV_NEW = "YTD_UPDATE_NEW"
ENV_BACKUP = "YTD_UPDATE_BACKUP"


def build_update_script(pid: int, wait_seconds: int = 60, retries: int = 30) -> str:
    """Вміст ``.cmd``, що замінює exe після завершення процесу ``pid``."""
    pid = int(pid)
    lines = [
        "@echo off",
        "setlocal EnableExtensions DisableDelayedExpansion",
        "rem Generated by yt-downloader: replaces the exe after the app exits.",
        "rem System tools by full path: PATH may contain e.g. Git's Unix find.exe.",
        'set "SYS=%SystemRoot%\\System32"',
        "set /a WAITED=0",
        ":wait",
        f'"%SYS%\\tasklist.exe" /NH /FI "PID eq {pid}" 2>nul | "%SYS%\\find.exe" " {pid} " >nul',
        "if errorlevel 1 goto replace",
        "set /a WAITED+=1",
        f"if %WAITED% geq {int(wait_seconds)} goto replace",
        '"%SYS%\\ping.exe" -n 2 127.0.0.1 >nul',
        "goto wait",
        ":replace",
        "set /a TRIES=0",
        ":backup",
        f'if exist "%{ENV_BACKUP}%" del /f /q "%{ENV_BACKUP}%" >nul 2>&1',
        f'move /y "%{ENV_TARGET}%" "%{ENV_BACKUP}%" >nul 2>&1',
        "if not errorlevel 1 goto install",
        "set /a TRIES+=1",
        f"if %TRIES% geq {int(retries)} goto failed",
        '"%SYS%\\ping.exe" -n 2 127.0.0.1 >nul',
        "goto backup",
        ":install",
        f'move /y "%{ENV_NEW}%" "%{ENV_TARGET}%" >nul 2>&1',
        "if not errorlevel 1 goto launch",
        "rem Rollback: restore the previous version.",
        f'move /y "%{ENV_BACKUP}%" "%{ENV_TARGET}%" >nul 2>&1',
        ":failed",
        f'del /f /q "%{ENV_NEW}%" >nul 2>&1',
        ":launch",
        f'start "" "%{ENV_TARGET}%"',
        '(goto) 2>nul & del /f /q "%~f0"',
    ]
    return "\r\n".join(lines) + "\r\n"


def clean_environment(env: dict[str, str], meipass: str | None) -> dict[str, str]:
    """Середовище для нового exe без слідів поточного запуску PyInstaller.

    Інакше новий exe може успадкувати шляхи до папки ``_MEI…`` старого процесу,
    яку буде видалено.
    """
    result = {}
    prefix = os.path.normcase(os.path.normpath(meipass)) if meipass else None

    def inside(value: str) -> bool:
        return bool(prefix) and os.path.normcase(os.path.normpath(value)).startswith(prefix)

    for key, value in env.items():
        upper = key.upper()
        if upper.startswith("_PYI_") or upper.startswith("_MEIPASS"):
            continue
        if upper == "PATH" and prefix:
            value = os.pathsep.join(p for p in value.split(os.pathsep) if p and not inside(p))
        elif value and inside(value):
            continue
        result[key] = value
    result["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return result


def launch_update_helper(new_exe: Path, exe: Path | None = None) -> Path:
    """Записує скрипт заміни поруч із exe і запускає його у фоні.

    Після виклику програму потрібно одразу закрити.
    """
    exe = exe or current_exe()
    _, backup, script = update_paths(exe)
    script.write_bytes(build_update_script(os.getpid()).encode("ascii"))
    env = clean_environment(dict(os.environ), getattr(sys, "_MEIPASS", None))
    env.update({ENV_TARGET: str(exe), ENV_NEW: str(new_exe), ENV_BACKUP: str(backup)})
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen(  # noqa: S603
        ["cmd.exe", "/d", "/c", str(script)], cwd=str(exe.parent), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, creationflags=flags)
    return script
