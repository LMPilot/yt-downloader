"""Логіка завантаження з YouTube через yt-dlp (без GUI).

Кожне відео зберігається у власну підпапку, названу за назвою відео.
Поруч із медіафайлом за бажанням створюється ``info.txt``:
рядок 1 — назва, рядки 2–4 — порожні, з рядка 5 — повний опис.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse, urlunparse

import yt_dlp
from yt_dlp.postprocessor.common import PostProcessor

# --------------------------------------------------------------------------- #
# Константи
# --------------------------------------------------------------------------- #

DEFAULT_OUTPUT_DIR = str(Path.home() / "Downloads" / "YT")
INFO_FILENAME = "info.txt"
THUMBNAIL_BASENAME = "preview"  # → preview.jpg у папці відео

MODE_SINGLE = "single"  # одне відео
MODE_COUNT = "count"    # N відео з каналу
MODE_ALL = "all"        # усі відео з каналу

QUALITY_BEST = "best"
QUALITY_AUDIO = "audio"
VIDEO_HEIGHTS = ("2160", "1440", "1080", "720", "480", "360")
AUDIO_BITRATES = ("320", "192", "128")
AUDIO_FORMATS = ("mp3", "m4a", "opus")
DEFAULT_AUDIO_FORMAT = "mp3"
# Для M4A/OPUS спершу беремо доріжку в тому ж кодеку — тоді FFmpeg лише
# переносить її в контейнер без перекодування й втрати якості.
_AUDIO_SOURCE = {
    "mp3": "bestaudio/best",
    "m4a": "bestaudio[ext=m4a]/bestaudio/best",
    "opus": "bestaudio[acodec=opus]/bestaudio/best",
}

# Максимальна довжина назви папки/файлу. Windows обмежує повний шлях
# 260 символами (MAX_PATH), тож для довгої папки завантаження межа менша —
# див. ``max_name_length``.
MAX_NAME_LENGTH = 150
MIN_NAME_LENGTH = 40
WINDOWS_MAX_PATH = 259  # 260 разом із завершальним нулем
# Запас на суфікси yt-dlp / FFmpeg у назві файлу: ".f137.mp4.part", ".temp.mp4"…
_SUFFIX_RESERVE = 24

FFMPEG_INSTALL_HINT = (
    "FFmpeg не знайдено. Він потрібен, щоб зʼєднати відео й аудіо в MP4 "
    "та зберегти аудіо в MP3 / M4A / OPUS.\n\n"
    "Windows: відкрийте PowerShell і виконайте\n"
    "    winget install Gyan.FFmpeg\n"
    "після чого перезапустіть програму.\n\n"
    "Або покладіть ffmpeg.exe поруч із програмою."
)

JS_RUNTIME_HINT = (
    "Не знайдено JavaScript-рушій (Deno або Node.js). Без нього YouTube може "
    "віддавати не всі формати (наприклад, без високої якості). "
    "Рекомендовано встановити: winget install DenoLand.Deno"
)

# Заборонені у Windows символи → їхні повноширинні двійники (так само робить
# yt-dlp без ``windowsfilenames``), тож назва виглядає як на YouTube.
_LOOKALIKES = str.maketrans({
    ":": "\uff1a", "?": "\uff1f", "/": "\u29f8", "\\": "\u29f9", "*": "\uff0a",
    '"': "\uff02", "<": "\uff1c", ">": "\uff1e", "|": "\uff5c",
})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_CHANNEL_PATH = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(/[^/]*)?/?$")


# --------------------------------------------------------------------------- #
# Чисті функції (покриті тестами)
# --------------------------------------------------------------------------- #

def sanitize_folder_name(name: str | None, max_length: int = MAX_NAME_LENGTH) -> str:
    """Перетворює назву відео на назву папки/файлу для Windows, що виглядає
    так само, як на YouTube.

    - заборонені символи ``<>:"/\\|?*`` → повноширинні двійники
      (``：？⧸⧹＊＂＜＞｜``); решта (емодзі, кирилиця, ``'#&`` …) не змінюється;
    - керувальні символи й переноси рядків → пробіл;
    - без пробілів і крапок на початку й у кінці (Windows не допускає їх у кінці);
    - зарезервовані імена (CON, NUL, COM1, ...) отримують суфікс ``_``;
    - довжина не більша за ``max_length``;
    - порожній результат → ``video``.

    Результат не містить символів, які yt-dlp змінює в полях шаблону
    ``outtmpl``, тож ``%(yt_folder)s`` потрапляє в назву файлу без змін.
    """
    text = _CONTROL_CHARS.sub(" ", name or "").translate(_LOOKALIKES)
    text = text.strip(" .")
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .")
    if not text:
        return "video"
    stem, dot, rest = text.partition(".")
    if stem.upper() in _WINDOWS_RESERVED:
        text = f"{stem}_{dot}{rest}"
    return text


def max_name_length(output_dir: str | os.PathLike) -> int:
    """Найбільша довжина назви, за якої повний шлях
    ``<папка>\\<назва>\\<назва>.f137.mp4.part`` вкладається в 260 символів
    Windows. Не більше ``MAX_NAME_LENGTH`` і не менше ``MIN_NAME_LENGTH``."""
    # Windows рахує шлях у UTF-16: емодзі в назві папки займає 2 символи.
    used = len(os.fspath(output_dir).encode("utf-16-le")) // 2
    available = (WINDOWS_MAX_PATH - used - 2 - _SUFFIX_RESERVE) // 2
    return max(MIN_NAME_LENGTH, min(MAX_NAME_LENGTH, available))


def format_info_text(title: str | None, description: str | None) -> str:
    """Вміст info.txt: назва, три порожні рядки, далі повний опис."""
    title = " ".join((title or "").split())
    description = (description or "").replace("\r\n", "\n").replace("\r", "\n")
    return f"{title}\n\n\n\n{description}"


def write_info_file(folder: str | os.PathLike, title: str | None,
                    description: str | None) -> Path:
    """Записує info.txt (UTF-8) у вказану папку й повертає шлях до нього."""
    path = Path(folder) / INFO_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_info_text(title, description), encoding="utf-8", newline="\n")
    return path


def prepare_output_dir(folder: str | os.PathLike | None) -> str:
    """Створює папку для завантаження (якщо її немає) і перевіряє, що в неї
    можна писати. Повертає абсолютний шлях або кидає ``OSError`` з
    зрозумілим українським повідомленням."""
    text = str(folder or "").strip()
    if not text:
        raise OSError("Не вказано папку для завантаження.")
    path = Path(os.path.expandvars(os.path.expanduser(text))).resolve()
    if path.exists() and not path.is_dir():
        raise OSError(f"Шлях існує, але це не папка:\n{path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Не вдалося створити папку:\n{path}\n\n{exc.strerror or exc}") from exc
    probe = path / f".yt-downloader-write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise OSError(f"Немає дозволу на запис у папку:\n{path}\n\n"
                      "Оберіть іншу папку.") from exc
    return str(path)


def normalize_url(url: str) -> str:
    """Для посилання на канал без вкладки (або з /featured) додає ``/videos``.

    ``https://www.youtube.com/@name`` → ``https://www.youtube.com/@name/videos``.
    Інші посилання (відео, плейлисти, вкладки shorts/streams) не змінюються.
    """
    url = url.strip()
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not (host == "youtube.com" or host.endswith(".youtube.com")):
        return url
    match = _CHANNEL_PATH.match(parsed.path)
    if not match:
        return url
    tab = (match.group(2) or "").strip("/").lower()
    if tab in ("", "featured", "home"):
        return urlunparse(parsed._replace(path=f"/{match.group(1)}/videos"))
    return url


def build_format_options(quality: str, audio_bitrate: str = "192",
                         audio_format: str = DEFAULT_AUDIO_FORMAT) -> dict:
    """Параметри yt-dlp для вибраної якості.

    ``quality == QUALITY_AUDIO`` — лише аудіо у форматі ``audio_format``
    (MP3, M4A або OPUS); ``audio_bitrate`` застосовується лише до MP3.
    """
    if quality == QUALITY_AUDIO:
        if audio_format not in AUDIO_FORMATS:
            raise ValueError(f"Невідомий аудіоформат: {audio_format}")
        postprocessor = {"key": "FFmpegExtractAudio", "preferredcodec": audio_format}
        if audio_format == "mp3":
            if audio_bitrate not in AUDIO_BITRATES:
                raise ValueError(f"Невідомий бітрейт: {audio_bitrate}")
            postprocessor["preferredquality"] = audio_bitrate
        return {
            "format": _AUDIO_SOURCE[audio_format],
            "postprocessors": [postprocessor],
        }
    if quality == QUALITY_BEST:
        sort = ["res", "ext:mp4:m4a"]
    elif quality in VIDEO_HEIGHTS:
        # Найбільша роздільність ≤ вибраної; якщо такої немає — найближча більша.
        sort = [f"res:{quality}", "ext:mp4:m4a"]
    else:
        raise ValueError(f"Невідома якість: {quality}")
    return {
        "format": "bv*+ba/b",
        "format_sort": sort,
        "merge_output_format": "mp4",
    }


def find_ffmpeg() -> str | None:
    """Шлях до ffmpeg: поруч із програмою (.exe) або в PATH."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    base = Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent
    local = base / exe
    if local.is_file():
        return str(local)
    return shutil.which("ffmpeg")


def has_js_runtime() -> bool:
    return any(shutil.which(name) for name in ("deno", "node"))


# --------------------------------------------------------------------------- #
# Завантаження
# --------------------------------------------------------------------------- #

@dataclass
class DownloadOptions:
    url: str
    mode: str = MODE_SINGLE
    count: int = 10
    quality: str = QUALITY_BEST
    audio_bitrate: str = "192"
    audio_format: str = DEFAULT_AUDIO_FORMAT
    save_info: bool = True
    save_thumbnail: bool = True
    output_dir: str = DEFAULT_OUTPUT_DIR


@dataclass
class DownloadResult:
    downloaded: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


# Тип колбеку подій: on_event(kind, data)
#   "log"      — {"message": str, "level": "info" | "warning" | "error"}
#   "progress" — {"index": int, "total": int | None, "percent": float | None,
#                 "speed": float | None, "title": str}
#   "done"     — {"title": str, "folder": str}
EventCallback = Callable[[str, dict], None]


class _Logger:
    _NOISY = re.compile(r"^(\[(youtube|youtube:tab|generic|info|debug)\]|Deleting original file)")

    def __init__(self, emit: EventCallback, result: DownloadResult):
        self._emit = emit
        self._result = result

    def debug(self, msg: str) -> None:
        if not self._NOISY.match(msg):
            self._emit("log", {"message": msg, "level": "info"})

    def info(self, msg: str) -> None:
        self.debug(msg)

    def warning(self, msg: str) -> None:
        self._emit("log", {"message": msg, "level": "warning"})

    def error(self, msg: str) -> None:
        self._result.errors.append(msg)
        self._emit("log", {"message": msg, "level": "error"})


class Downloader:
    """Запускає yt-dlp з потрібними налаштуваннями. Викликайте ``run()``
    у фоновому потоці; ``cancel()`` можна викликати з будь-якого потоку."""

    def __init__(self, options: DownloadOptions, on_event: EventCallback | None = None):
        self.options = options
        self._emit = on_event or (lambda kind, data: None)
        self._cancel = threading.Event()
        self._used_names: dict[str, str] = {}  # назва папки → id відео
        self.result = DownloadResult()

    def cancel(self) -> None:
        self._cancel.set()

    # -- налаштування yt-dlp ------------------------------------------------ #

    def build_ydl_params(self, ffmpeg_path: str | None = None) -> dict:
        opts = self.options
        output_dir = os.path.abspath(os.path.expanduser(opts.output_dir))
        params: dict = {
            "paths": {"home": output_dir},
            "outtmpl": {"default": "%(yt_folder)s/%(yt_folder)s.%(ext)s"},
            "ignoreerrors": True,
            "noprogress": True,
            "windowsfilenames": True,
            "js_runtimes": {"deno": {}, "node": {}},
            "logger": _Logger(self._emit, self.result),
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
        }
        params.update(build_format_options(opts.quality, opts.audio_bitrate, opts.audio_format))
        if opts.save_thumbnail:
            # Найкраще прев'ю відео → preview.jpg у папці відео (WebP від
            # YouTube конвертується в JPG, щоб відкривався будь-де).
            params["writethumbnail"] = True
            params["outtmpl"]["thumbnail"] = f"%(yt_folder)s/{THUMBNAIL_BASENAME}.%(ext)s"
            params["postprocessors"] = [
                *params.get("postprocessors", []),
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg",
                 "when": "before_dl"},
            ]
        if ffmpeg_path:
            params["ffmpeg_location"] = ffmpeg_path

        if opts.mode == MODE_SINGLE:
            params["noplaylist"] = True  # watch?v=...&list=... → лише це відео
            params["playlistend"] = 1    # посилання на канал → останнє відео
        elif opts.mode == MODE_COUNT:
            if opts.count < 1:
                raise ValueError("Кількість відео має бути більшою за 0")
            params["playlistend"] = int(opts.count)
        elif opts.mode != MODE_ALL:
            raise ValueError(f"Невідомий режим: {opts.mode}")
        return params

    # -- запуск ------------------------------------------------------------- #

    def run(self) -> DownloadResult:
        url = normalize_url(self.options.url)
        if not url:
            raise ValueError("Вкажіть посилання")

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError(FFMPEG_INSTALL_HINT)
        if not has_js_runtime():
            self._emit("log", {"message": JS_RUNTIME_HINT, "level": "warning"})

        self.options.output_dir = prepare_output_dir(self.options.output_dir)
        params = self.build_ydl_params(ffmpeg)
        self._emit("log", {"message": f"Посилання: {url}", "level": "info"})

        try:
            with yt_dlp.YoutubeDL(params) as ydl:
                ydl.add_post_processor(_FolderNamePP(self), when="pre_process")
                ydl.add_post_processor(_FinishPP(self), when="after_move")
                ydl.download([url])
        except yt_dlp.utils.DownloadCancelled:
            self.result.cancelled = True
        return self.result

    # -- допоміжне ---------------------------------------------------------- #

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise yt_dlp.utils.DownloadCancelled("Скасовано користувачем")

    def folder_name_for(self, title: str | None, video_id: str | None) -> str:
        """Унікальна в межах сесії назва папки (однакові назви → додається id)."""
        limit = max_name_length(os.path.abspath(os.path.expanduser(self.options.output_dir)))
        name = sanitize_folder_name(title, limit)
        owner = self._used_names.get(name)
        if owner is not None and owner != video_id and video_id:
            suffix = f" [{video_id}]"
            name = sanitize_folder_name(title, limit - len(suffix)) + suffix
        self._used_names.setdefault(name, video_id or "")
        return name

    @staticmethod
    def _position(info: dict) -> tuple[int, int | None]:
        index = info.get("playlist_autonumber") or info.get("playlist_index") or 1
        total = info.get("n_entries") or (None if info.get("playlist_id") else 1)
        return int(index), total

    def _progress_hook(self, d: dict) -> None:
        self._check_cancel()
        info = d.get("info_dict") or {}
        index, total = self._position(info)
        percent = None
        if d.get("status") == "downloading":
            done = d.get("downloaded_bytes") or 0
            whole = d.get("total_bytes") or d.get("total_bytes_estimate")
            if whole:
                percent = min(100.0, done * 100.0 / whole)
        elif d.get("status") == "finished":
            percent = 100.0
        self._emit("progress", {
            "index": index,
            "total": total,
            "percent": percent,
            "speed": d.get("speed"),
            "title": info.get("title") or "",
        })

    def _postprocessor_hook(self, d: dict) -> None:
        self._check_cancel()


class _FolderNamePP(PostProcessor):
    """Перед завантаженням визначає назву папки для відео."""

    def __init__(self, downloader: Downloader):
        super().__init__()
        self.dl = downloader

    def run(self, info):
        self.dl._check_cancel()
        info["yt_folder"] = self.dl.folder_name_for(info.get("title"), info.get("id"))
        index, total = self.dl._position(info)
        pos = f"{index}/{total}" if total else str(index)
        self.dl._emit("log", {"message": f"▶ [{pos}] {info.get('title', '')}",
                              "level": "info"})
        return [], info


class _FinishPP(PostProcessor):
    """Після переміщення готового файлу записує info.txt."""

    def __init__(self, downloader: Downloader):
        super().__init__()
        self.dl = downloader

    def run(self, info):
        filepath = info.get("filepath") or ""
        folder = os.path.dirname(filepath) if filepath else ""
        if folder and self.dl.options.save_info:
            write_info_file(folder, info.get("title"), info.get("description"))
        self.dl.result.downloaded += 1
        self.dl._emit("done", {"title": info.get("title") or "", "folder": folder})
        return [], info
