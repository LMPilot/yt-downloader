"""YouTube Downloader — графічний інтерфейс на CustomTkinter."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

import downloader as dl
import settings
import updater
from version import __version__

MODE_LABELS = {
    "Одне відео": dl.MODE_SINGLE,
    "N відео з каналу": dl.MODE_COUNT,
    "Усі відео з каналу": dl.MODE_ALL,
}
QUALITY_LABELS = {
    "Найкраща": dl.QUALITY_BEST,
    **{f"{h}p": h for h in dl.VIDEO_HEIGHTS},
}
MEDIA_LABELS = {
    "🎬 Відео": "video",
    "🎵 Лише аудіо": "audio",
}
AUDIO_FORMAT_LABELS = {f.upper(): f for f in dl.AUDIO_FORMATS}
THEME_LABELS = {
    "Темна": "dark",
    "Світла": "light",
    "Системна": "system",
}
LOG_PREFIX = {"warning": "⚠ ", "error": "✖ "}
APP_NAME = "YouTube Downloader"


def resource_path(name: str) -> Path:
    """Шлях до файлу з assets/: поруч із app.py або в розпакованому .exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


ICON_ICO = resource_path("icon.ico")
ICON_PNG = resource_path("icon.png")


def _label_for(labels: dict, value, default: str) -> str:
    """Підпис у списку для збереженого значення (або ``default``)."""
    for label, val in labels.items():
        if val == value:
            return label
    return default


def format_speed(speed: float | None) -> str:
    if not speed:
        return ""
    for unit in ("Б/с", "КБ/с", "МБ/с", "ГБ/с"):
        if speed < 1024:
            return f"{speed:.1f} {unit}"
        speed /= 1024
    return f"{speed:.1f} ТБ/с"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        self._icon_photo = None
        self._set_window_icon(self)
        self.geometry("780x760")
        self.minsize(660, 680)

        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._downloader: dl.Downloader | None = None
        self._release: updater.ReleaseInfo | None = None
        self._checking_update = False
        self._updating = False
        self._update_cancel = threading.Event()
        saved = settings.with_defaults(settings.load_settings())
        ctk.set_appearance_mode(saved["theme"])

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)
        pad = {"padx": 16, "pady": (12, 0)}

        # --- заголовок і тема ------------------------------------------------
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(8, 0))
        top.grid_columnconfigure(0, weight=1)
        header_icon = None
        if ICON_PNG.is_file():
            # Той самий файл, що й іконка вікна/exe (tools/make_icon.py).
            header_icon = ctk.CTkImage(Image.open(ICON_PNG), size=(28, 28))
        ctk.CTkLabel(top, text=f"  {APP_NAME}", image=header_icon, compound="left",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0,
                                                                   sticky="w")
        ctk.CTkLabel(top, text="Тема:", text_color=("gray35", "gray65")).grid(
            row=0, column=1, padx=(0, 6))
        self.theme_var = ctk.StringVar(value=_label_for(THEME_LABELS, saved["theme"], "Темна"))
        ctk.CTkOptionMenu(top, values=list(THEME_LABELS), variable=self.theme_var,
                          width=110, height=26, command=self._change_theme,
                          ).grid(row=0, column=2)

        # --- папка -----------------------------------------------------------
        folder_frame = ctk.CTkFrame(self, border_width=2,
                                    border_color=("#3b8ed0", "#1f6aa5"))
        folder_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 0))
        folder_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(folder_frame, text="📁 Папка для завантаження",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 0))
        self.folder_entry = ctk.CTkEntry(folder_frame, height=34)
        self.folder_entry.insert(0, saved.get("output_dir") or dl.DEFAULT_OUTPUT_DIR)
        self.folder_entry.grid(row=1, column=0, sticky="ew", padx=(12, 0), pady=(6, 0))
        ctk.CTkButton(folder_frame, text="Обрати…", width=100, height=34,
                      command=self._choose_folder).grid(row=1, column=1, padx=(8, 0),
                                                        pady=(6, 0))
        ctk.CTkButton(folder_frame, text="Відкрити", width=100, height=34,
                      fg_color="gray40", hover_color="gray30",
                      command=self._open_folder).grid(row=1, column=2, padx=(8, 12),
                                                      pady=(6, 0))
        ctk.CTkLabel(folder_frame, text="Кожне відео зберігається в окрему підпапку "
                                        "всередині цієї папки.",
                     text_color=("gray35", "gray65")).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=12, pady=(2, 8))

        # --- посилання -------------------------------------------------------
        url_frame = ctk.CTkFrame(self, fg_color="transparent")
        url_frame.grid(row=2, column=0, sticky="ew", **pad)
        url_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(url_frame, text="Посилання на відео, плейлист або канал:").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.url_entry = ctk.CTkEntry(
            url_frame, placeholder_text="https://www.youtube.com/@назва_каналу")
        self.url_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ctk.CTkButton(url_frame, text="Вставити", width=90,
                      command=self._paste_url).grid(row=1, column=1, padx=(8, 0), pady=(4, 0))

        # --- режим -----------------------------------------------------------
        mode_frame = ctk.CTkFrame(self)
        mode_frame.grid(row=3, column=0, sticky="ew", **pad)
        ctk.CTkLabel(mode_frame, text="Режим:").grid(row=0, column=0, padx=12, pady=10)
        self.mode_var = ctk.StringVar(
            value=_label_for(MODE_LABELS, saved.get("mode"), "Одне відео"))
        ctk.CTkSegmentedButton(
            mode_frame, values=list(MODE_LABELS), variable=self.mode_var,
            command=lambda _: self._update_controls(),
        ).grid(row=0, column=1, pady=10)
        ctk.CTkLabel(mode_frame, text="N =").grid(row=0, column=2, padx=(16, 4))
        self.count_entry = ctk.CTkEntry(mode_frame, width=70)
        self.count_entry.insert(0, str(saved.get("count") or 10))
        self.count_entry.grid(row=0, column=3, padx=(0, 12))

        # --- відео / аудіо ---------------------------------------------------
        quality_frame = ctk.CTkFrame(self)
        quality_frame.grid(row=4, column=0, sticky="ew", **pad)
        media_row = ctk.CTkFrame(quality_frame, fg_color="transparent")
        media_row.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(media_row, text="Завантажити:").grid(row=0, column=0, padx=(12, 8),
                                                         pady=10)
        self.media_var = ctk.StringVar(value=_label_for(MEDIA_LABELS, saved["media"],
                                                        "🎬 Відео"))
        ctk.CTkSegmentedButton(
            media_row, values=list(MEDIA_LABELS), variable=self.media_var,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda _: self._update_controls(),
        ).grid(row=0, column=1, pady=10)

        # Налаштування відео: якість.
        self.video_options = ctk.CTkFrame(quality_frame, fg_color="transparent")
        ctk.CTkLabel(self.video_options, text="Якість відео:").grid(row=0, column=0,
                                                                    padx=(12, 8))
        self.quality_var = ctk.StringVar(
            value=_label_for(QUALITY_LABELS, saved.get("quality"), "Найкраща"))
        self.quality_menu = ctk.CTkOptionMenu(self.video_options, values=list(QUALITY_LABELS),
                                              variable=self.quality_var)
        self.quality_menu.grid(row=0, column=1)

        # Налаштування аудіо: формат і бітрейт MP3.
        self.audio_options = ctk.CTkFrame(quality_frame, fg_color="transparent")
        ctk.CTkLabel(self.audio_options, text="Формат:").grid(row=0, column=0, padx=(12, 8))
        self.audio_format_var = ctk.StringVar(
            value=_label_for(AUDIO_FORMAT_LABELS, saved["audio_format"], "MP3"))
        self.audio_format_menu = ctk.CTkOptionMenu(
            self.audio_options, values=list(AUDIO_FORMAT_LABELS),
            variable=self.audio_format_var, width=90,
            command=lambda _: self._update_controls())
        self.audio_format_menu.grid(row=0, column=1)
        ctk.CTkLabel(self.audio_options, text="Бітрейт MP3:").grid(row=0, column=2,
                                                                   padx=(16, 4))
        bitrate = saved.get("audio_bitrate")
        self.bitrate_var = ctk.StringVar(
            value=bitrate if bitrate in dl.AUDIO_BITRATES else "192")
        self.bitrate_menu = ctk.CTkOptionMenu(
            self.audio_options, values=[f"{b}" for b in dl.AUDIO_BITRATES],
            variable=self.bitrate_var, width=80)
        self.bitrate_menu.grid(row=0, column=3)
        ctk.CTkLabel(self.audio_options, text="кбіт/с").grid(row=0, column=4, padx=(4, 0))

        self.save_info_var = ctk.BooleanVar(value=saved.get("save_info", True) is not False)
        ctk.CTkCheckBox(quality_frame, text="Зберігати назву та опис (info.txt)",
                        variable=self.save_info_var).grid(row=2, column=0,
                                                          sticky="w", padx=12, pady=(0, 6))
        self.save_thumbnail_var = ctk.BooleanVar(
            value=saved.get("save_thumbnail", True) is not False)
        ctk.CTkCheckBox(quality_frame, text="Зберігати прев'ю (preview.jpg)",
                        variable=self.save_thumbnail_var).grid(row=3, column=0,
                                                               sticky="w", padx=12, pady=(0, 10))

        # --- прогрес ---------------------------------------------------------
        progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        progress_frame.grid(row=5, column=0, sticky="ew", **pad)
        progress_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(progress_frame, text="Готово до завантаження",
                                         anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.progress = ctk.CTkProgressBar(progress_frame)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # --- журнал ----------------------------------------------------------
        self.log_box = ctk.CTkTextbox(self, wrap="word")
        self.log_box.grid(row=6, column=0, sticky="nsew", padx=16, pady=(12, 0))
        self.log_box.configure(state="disabled")

        # --- оновлення (показується, коли є нова версія) ----------------------
        self.update_frame = ctk.CTkFrame(self, fg_color=("#d4edda", "#1e4620"))
        self.update_frame.grid_columnconfigure(0, weight=1)
        self.update_label = ctk.CTkLabel(self.update_frame, text="", anchor="w")
        self.update_label.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        ctk.CTkButton(self.update_frame, text="Що нового", width=100,
                      fg_color="gray40", hover_color="gray30",
                      command=self._show_release_notes).grid(row=0, column=1, padx=(8, 0))
        self.update_button = ctk.CTkButton(self.update_frame, text="", fg_color="#2e7d32",
                                           hover_color="#1b5e20",
                                           command=self._install_update)
        self.update_button.grid(row=0, column=2, padx=(8, 12), pady=8)

        # --- кнопки ----------------------------------------------------------
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=8, column=0, sticky="ew", padx=16, pady=12)
        bottom.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(bottom, text=f"Версія {__version__}",
                     text_color=("gray35", "gray65")).grid(row=0, column=0, sticky="w")
        self.check_button = ctk.CTkButton(
            bottom, text="Перевірити оновлення", width=170, fg_color="transparent",
            border_width=1, text_color=("gray20", "gray80"),
            command=lambda: self._check_updates(manual=True))
        self.check_button.grid(row=0, column=1, sticky="w", padx=(12, 0))
        buttons = ctk.CTkFrame(bottom, fg_color="transparent")
        buttons.grid(row=0, column=3, sticky="e")
        self.start_button = ctk.CTkButton(buttons, text="Завантажити", command=self._start)
        self.start_button.grid(row=0, column=0)
        self.cancel_button = ctk.CTkButton(buttons, text="Скасувати", fg_color="#b03a2e",
                                           hover_color="#8e2f25", command=self._cancel,
                                           state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=(8, 0))

        self.url_entry.bind("<Return>", lambda _: self._start())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_controls()
        self.after(100, self._poll_events)
        self.after(300, self._check_ffmpeg_on_startup)
        self.after(1500, self._check_updates)

    # ------------------------------------------------------------------ UI --

    def _update_controls(self) -> None:
        downloading = self._worker is not None and self._worker.is_alive()
        running = downloading or self._updating
        count_on = MODE_LABELS[self.mode_var.get()] == dl.MODE_COUNT and not running
        self.count_entry.configure(state="normal" if count_on else "disabled")
        if self._audio_mode():
            self.video_options.grid_remove()
            self.audio_options.grid(row=1, column=0, sticky="w", pady=(0, 10))
        else:
            self.audio_options.grid_remove()
            self.video_options.grid(row=1, column=0, sticky="w", pady=(0, 10))
        mp3 = AUDIO_FORMAT_LABELS[self.audio_format_var.get()] == "mp3"
        self.bitrate_menu.configure(state="normal" if mp3 and not running else "disabled")
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if downloading else "disabled",
                                     fg_color="#b03a2e" if downloading else "gray50")
        self.update_button.configure(state="disabled" if running else "normal")
        self.check_button.configure(
            state="disabled" if self._updating or self._checking_update else "normal")

    def _set_window_icon(self, win) -> None:
        """Іконка вікна й панелі задач: .ico у Windows, інакше PNG."""
        try:
            if sys.platform == "win32" and ICON_ICO.is_file():
                win.iconbitmap(str(ICON_ICO))
                if win is not self:
                    # CTkToplevel через 200 мс ставить свою іконку — повертаємо нашу.
                    win.after(250, lambda: win.iconbitmap(str(ICON_ICO)))
            elif ICON_PNG.is_file():
                if self._icon_photo is None:
                    self._icon_photo = tkinter.PhotoImage(master=self, file=str(ICON_PNG))
                win.iconphoto(False, self._icon_photo)
        except tkinter.TclError:
            pass  # без іконки програма все одно працює

    def _audio_mode(self) -> bool:
        return MEDIA_LABELS[self.media_var.get()] == "audio"

    def _change_theme(self, label: str) -> None:
        ctk.set_appearance_mode(THEME_LABELS[label])
        self._save_settings()

    def _log(self, message: str, level: str = "info") -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", LOG_PREFIX.get(level, "") + message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)

    def _choose_folder(self) -> None:
        current = os.path.expanduser(self.folder_entry.get().strip())
        folder = filedialog.askdirectory(
            parent=self, title="Оберіть папку для завантаження",
            initialdir=current if os.path.isdir(current) else str(Path.home()))
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, os.path.normpath(folder))
            self._save_settings()

    def _prepare_folder(self) -> str | None:
        """Створює/перевіряє папку; при помилці показує повідомлення."""
        try:
            folder = dl.prepare_output_dir(self.folder_entry.get())
        except OSError as exc:
            self._show_message("Папка для завантаження", str(exc))
            return None
        self.folder_entry.delete(0, "end")
        self.folder_entry.insert(0, folder)
        return folder

    def _open_folder(self) -> None:
        folder = self._prepare_folder()
        if folder is None:
            return
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def _show_message(self, title: str, text: str) -> None:
        win = ctk.CTkToplevel(self)
        win.title(title)
        self._set_window_icon(win)
        win.resizable(False, False)
        win.transient(self)
        ctk.CTkLabel(win, text=text, justify="left", wraplength=460).pack(padx=20, pady=(20, 10))
        ctk.CTkButton(win, text="OK", width=100, command=win.destroy).pack(pady=(0, 20))
        win.after(50, win.grab_set)

    def _check_ffmpeg_on_startup(self) -> None:
        if not dl.find_ffmpeg():
            self._log(dl.FFMPEG_INSTALL_HINT, "warning")
            self._show_message("Потрібен FFmpeg", dl.FFMPEG_INSTALL_HINT)
        elif not dl.has_js_runtime():
            self._log(dl.JS_RUNTIME_HINT, "warning")

    # ------------------------------------------------------------ download --

    def _collect_options(self) -> dl.DownloadOptions | None:
        url = self.url_entry.get().strip()
        if not url:
            self._show_message("Помилка", "Вставте посилання на відео або канал.")
            return None
        mode = MODE_LABELS[self.mode_var.get()]
        count = 0
        if mode == dl.MODE_COUNT:
            try:
                count = int(self.count_entry.get().strip())
                if count < 1:
                    raise ValueError
            except ValueError:
                self._show_message("Помилка", "N має бути цілим числом більшим за 0.")
                return None
        folder = self._prepare_folder()
        if folder is None:
            return None
        return dl.DownloadOptions(
            url=url, mode=mode, count=count,
            quality=(dl.QUALITY_AUDIO if self._audio_mode()
                     else QUALITY_LABELS[self.quality_var.get()]),
            audio_bitrate=self.bitrate_var.get(),
            audio_format=AUDIO_FORMAT_LABELS[self.audio_format_var.get()],
            save_info=self.save_info_var.get(),
            save_thumbnail=self.save_thumbnail_var.get(),
            output_dir=folder,
        )

    def _start(self) -> None:
        if self._updating or (self._worker is not None and self._worker.is_alive()):
            return
        if not dl.find_ffmpeg():
            self._show_message("Потрібен FFmpeg", dl.FFMPEG_INSTALL_HINT)
            return
        options = self._collect_options()
        if options is None:
            return
        self._save_settings()
        self._log(f"Папка: {options.output_dir}")

        self.progress.set(0)
        self.status_label.configure(text="Отримання інформації…")
        self._downloader = dl.Downloader(options, on_event=self._on_event)
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self._update_controls()

    def _run_worker(self) -> None:
        try:
            result = self._downloader.run()
            self._events.put(("finished", {"result": result}))
        except Exception as exc:  # noqa: BLE001 — показуємо будь-яку помилку
            self._events.put(("failed", {"message": str(exc)}))

    def _cancel(self) -> None:
        if self._downloader:
            self._downloader.cancel()
            self.status_label.configure(text="Скасування…")
            self.cancel_button.configure(state="disabled")

    def _on_event(self, kind: str, data: dict) -> None:
        # Викликається з фонового потоку — лише кладемо подію в чергу.
        self._events.put((kind, data))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, data = self._events.get_nowait()
                self._handle_event(kind, data)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _handle_event(self, kind: str, data: dict) -> None:
        if kind == "update_check":
            self._on_update_check(data)
        elif kind == "update_progress":
            total, done = data["total"], data["done"]
            if total:
                self.progress.set(min(done / total, 1))
                self.status_label.configure(
                    text=f"Завантаження оновлення… {done * 100 // total}% "
                         f"({done / 1048576:.1f} з {total / 1048576:.1f} МБ)")
        elif kind == "update_ready":
            self._on_update_ready(data["path"])
        elif kind == "update_failed":
            self._on_update_failed(data["message"])
        elif kind == "log":
            self._log(data["message"], data.get("level", "info"))
        elif kind == "progress":
            total = data.get("total")
            pos = f"Відео {data['index']}/{total}" if total else f"Відео {data['index']}"
            parts = [pos]
            if data.get("percent") is not None:
                parts.append(f"{data['percent']:.1f}%")
                self.progress.set(data["percent"] / 100)
            if speed := format_speed(data.get("speed")):
                parts.append(speed)
            title = data.get("title") or ""
            if len(title) > 50:
                title = title[:49] + "…"
            self.status_label.configure(text=" · ".join(parts) + (f" — {title}" if title else ""))
        elif kind == "done":
            self._log(f"✔ Готово: {data['folder']}")
        elif kind == "finished":
            result: dl.DownloadResult = data["result"]
            if result.cancelled:
                summary = f"Скасовано. Завантажено: {result.downloaded}"
            else:
                summary = f"Завершено. Завантажено: {result.downloaded}"
                self.progress.set(1)
            if result.errors:
                summary += f", помилок: {len(result.errors)}"
            self.status_label.configure(text=summary)
            self._log("— " + summary)
            self._worker = None
            self._update_controls()
        elif kind == "failed":
            self.status_label.configure(text="Помилка")
            self._log(data["message"], "error")
            self._show_message("Помилка", data["message"])
            self._worker = None
            self._update_controls()

    # ------------------------------------------------------------- update --

    def _check_updates(self, manual: bool = False) -> None:
        if self._checking_update or self._updating:
            return
        self._checking_update = True
        self._update_controls()

        def work() -> None:
            try:
                release = updater.check_for_update(__version__)
                self._events.put(("update_check", {"release": release, "manual": manual}))
            except Exception as exc:  # noqa: BLE001 — мережа недоступна тощо
                self._events.put(("update_check", {"error": str(exc), "manual": manual}))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_check(self, data: dict) -> None:
        self._checking_update = False
        self._update_controls()
        manual = data.get("manual")
        if "error" in data:
            self._log(f"Не вдалося перевірити оновлення: {data['error']}")
            if manual:
                self._show_message("Оновлення", "Не вдалося перевірити оновлення. "
                                                "Перевірте підключення до інтернету.")
            return
        release: updater.ReleaseInfo | None = data["release"]
        if release is None:
            if manual:
                self._show_message("Оновлення",
                                   f"У вас остання версія ({__version__}).")
            return
        self._release = release
        self.update_label.configure(
            text=f"Доступна нова версія {release.version} (у вас {__version__})")
        self.update_button.configure(text=f"Оновити до версії {release.version}")
        self.update_frame.grid(row=7, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._update_controls()
        self._log(f"Доступна нова версія {release.version}.")

    def _show_release_notes(self) -> None:
        if not self._release:
            return
        win = ctk.CTkToplevel(self)
        win.title(f"Що нового у версії {self._release.version}")
        self._set_window_icon(win)
        win.geometry("560x420")
        win.transient(self)
        box = ctk.CTkTextbox(win, wrap="word")
        box.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        box.insert("end", self._release.notes or "Опис змін відсутній.")
        box.insert("end", f"\n\n{self._release.page_url}")
        box.configure(state="disabled")
        ctk.CTkButton(win, text="OK", width=100, command=win.destroy).pack(pady=(0, 16))
        win.after(50, win.grab_set)

    def _install_update(self) -> None:
        release = self._release
        if release is None or self._updating:
            return
        if self._worker is not None and self._worker.is_alive():
            self._show_message("Оновлення", "Зараз іде завантаження відео. Дочекайтеся "
                                            "його завершення або скасуйте, а потім "
                                            "оновіть програму.")
            return
        if not updater.is_frozen():
            self._show_message(
                "Оновлення",
                f"Доступна версія {release.version}, але програма запущена з вихідного "
                "коду. Оновіть її командою\n\n    git pull\n    pip install -r "
                "requirements.txt\n\nабо завантажте exe зі сторінки релізів:\n"
                f"{release.page_url}")
            return
        exe = updater.current_exe()
        new_exe, _, _ = updater.update_paths(exe)
        self._updating = True
        self._update_cancel.clear()
        self._update_controls()
        self.progress.set(0)
        self.status_label.configure(text=f"Завантаження оновлення {release.version}…")
        self._log(f"Завантаження версії {release.version}…")

        def progress(done: int, total: int) -> None:
            self._events.put(("update_progress", {"done": done, "total": total}))

        def work() -> None:
            try:
                updater.download_update(release, new_exe, on_progress=progress,
                                        is_cancelled=self._update_cancel.is_set)
                self._events.put(("update_ready", {"path": new_exe}))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("update_failed", {"message": str(exc)}))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_ready(self, path: Path) -> None:
        try:
            updater.launch_update_helper(path)
        except OSError as exc:
            path.unlink(missing_ok=True)
            self._on_update_failed(f"Не вдалося запустити оновлення: {exc}")
            return
        self._log("Оновлення завантажено. Програма перезапуститься…")
        self.update()
        self._save_settings()
        self.destroy()

    def _on_update_failed(self, message: str) -> None:
        self._updating = False
        self._update_controls()
        self.status_label.configure(text="Оновлення не вдалося")
        self._log(message, "error")
        page = self._release.page_url if self._release else updater.RELEASES_PAGE
        self._show_message("Оновлення", f"{message}\n\nНову версію можна завантажити "
                                        f"вручну:\n{page}")

    def _save_settings(self) -> None:
        data = {
            "output_dir": self.folder_entry.get().strip(),
            "mode": MODE_LABELS[self.mode_var.get()],
            "media": MEDIA_LABELS[self.media_var.get()],
            "quality": QUALITY_LABELS[self.quality_var.get()],
            "audio_format": AUDIO_FORMAT_LABELS[self.audio_format_var.get()],
            "audio_bitrate": self.bitrate_var.get(),
            "theme": THEME_LABELS[self.theme_var.get()],
            "save_info": bool(self.save_info_var.get()),
            "save_thumbnail": bool(self.save_thumbnail_var.get()),
        }
        count = self.count_entry.get().strip()
        if count.isdigit() and int(count) > 0:
            data["count"] = int(count)
        settings.save_settings(data)

    def _on_close(self) -> None:
        self._save_settings()
        self._update_cancel.set()
        if self._downloader:
            self._downloader.cancel()
        self.destroy()


def self_test(report_path: str) -> int:
    """Перевірка зібраного .exe у CI: вікно створюється, залежності на місці.
    Результат пишеться в JSON-файл (у --windowed-збірці немає консолі)."""
    import json
    import traceback

    report: dict = {}
    try:
        import yt_dlp
        import yt_dlp_ejs  # noqa: F401 — потрібен yt-dlp для YouTube

        report["yt_dlp"] = yt_dlp.version.__version__
        report["ejs_files"] = len(list(Path(yt_dlp_ejs.__file__).parent.rglob("*.js")))
        report["ffmpeg"] = dl.find_ffmpeg()
        report["icon"] = ICON_ICO.is_file() and ICON_PNG.is_file()
        app = App()
        app.update()
        report["window"] = app.title()
        report["version"] = __version__
        app.destroy()
        report["ok"] = report["ejs_files"] > 0 and report["icon"]
    except Exception:  # noqa: BLE001
        report["ok"] = False
        report["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    return 0 if report["ok"] else 1


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        sys.exit(self_test(sys.argv[2]))
    ctk.set_default_color_theme("blue")
    App().mainloop()


if __name__ == "__main__":
    main()
