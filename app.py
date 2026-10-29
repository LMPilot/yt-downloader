"""YouTube Downloader — графічний інтерфейс на CustomTkinter."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from tkinter import filedialog

import customtkinter as ctk

import downloader as dl

MODE_LABELS = {
    "Одне відео": dl.MODE_SINGLE,
    "N відео з каналу": dl.MODE_COUNT,
    "Усі відео з каналу": dl.MODE_ALL,
}
QUALITY_LABELS = {
    "Найкраща": dl.QUALITY_BEST,
    **{f"{h}p": h for h in dl.VIDEO_HEIGHTS},
    "Лише аудіо (MP3)": dl.QUALITY_AUDIO,
}
LOG_PREFIX = {"warning": "⚠ ", "error": "✖ "}


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
        self.title("YouTube Downloader")
        self.geometry("760x640")
        self.minsize(640, 560)

        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._downloader: dl.Downloader | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)
        pad = {"padx": 16, "pady": (12, 0)}

        # --- посилання -------------------------------------------------------
        url_frame = ctk.CTkFrame(self, fg_color="transparent")
        url_frame.grid(row=0, column=0, sticky="ew", **pad)
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
        mode_frame.grid(row=1, column=0, sticky="ew", **pad)
        ctk.CTkLabel(mode_frame, text="Режим:").grid(row=0, column=0, padx=12, pady=10)
        self.mode_var = ctk.StringVar(value="Одне відео")
        ctk.CTkSegmentedButton(
            mode_frame, values=list(MODE_LABELS), variable=self.mode_var,
            command=lambda _: self._update_controls(),
        ).grid(row=0, column=1, pady=10)
        ctk.CTkLabel(mode_frame, text="N =").grid(row=0, column=2, padx=(16, 4))
        self.count_entry = ctk.CTkEntry(mode_frame, width=70)
        self.count_entry.insert(0, "10")
        self.count_entry.grid(row=0, column=3, padx=(0, 12))

        # --- якість ----------------------------------------------------------
        quality_frame = ctk.CTkFrame(self)
        quality_frame.grid(row=2, column=0, sticky="ew", **pad)
        ctk.CTkLabel(quality_frame, text="Якість:").grid(row=0, column=0, padx=12, pady=10)
        self.quality_var = ctk.StringVar(value="Найкраща")
        ctk.CTkOptionMenu(quality_frame, values=list(QUALITY_LABELS),
                          variable=self.quality_var,
                          command=lambda _: self._update_controls(),
                          ).grid(row=0, column=1, pady=10)
        ctk.CTkLabel(quality_frame, text="Бітрейт MP3:").grid(row=0, column=2, padx=(16, 4))
        self.bitrate_var = ctk.StringVar(value="192")
        self.bitrate_menu = ctk.CTkOptionMenu(
            quality_frame, values=[f"{b}" for b in dl.AUDIO_BITRATES],
            variable=self.bitrate_var, width=80)
        self.bitrate_menu.grid(row=0, column=3)
        ctk.CTkLabel(quality_frame, text="кбіт/с").grid(row=0, column=4, padx=(4, 12))
        self.save_info_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(quality_frame, text="Зберігати назву та опис",
                        variable=self.save_info_var).grid(row=1, column=0, columnspan=5,
                                                          sticky="w", padx=12, pady=(0, 10))

        # --- папка -----------------------------------------------------------
        folder_frame = ctk.CTkFrame(self, fg_color="transparent")
        folder_frame.grid(row=3, column=0, sticky="ew", **pad)
        folder_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(folder_frame, text="Папка:").grid(row=0, column=0, padx=(0, 8))
        self.folder_entry = ctk.CTkEntry(folder_frame)
        self.folder_entry.insert(0, dl.DEFAULT_OUTPUT_DIR)
        self.folder_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(folder_frame, text="Обрати…", width=90,
                      command=self._choose_folder).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkButton(folder_frame, text="Відкрити", width=90, fg_color="gray40",
                      hover_color="gray30",
                      command=self._open_folder).grid(row=0, column=3, padx=(8, 0))

        # --- прогрес ---------------------------------------------------------
        progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", **pad)
        progress_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(progress_frame, text="Готово до завантаження",
                                         anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.progress = ctk.CTkProgressBar(progress_frame)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # --- журнал ----------------------------------------------------------
        self.log_box = ctk.CTkTextbox(self, wrap="word")
        self.log_box.grid(row=5, column=0, sticky="nsew", padx=16, pady=(12, 0))
        self.log_box.configure(state="disabled")

        # --- кнопки ----------------------------------------------------------
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="e", padx=16, pady=12)
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

    # ------------------------------------------------------------------ UI --

    def _update_controls(self) -> None:
        running = self._worker is not None and self._worker.is_alive()
        count_on = MODE_LABELS[self.mode_var.get()] == dl.MODE_COUNT and not running
        self.count_entry.configure(state="normal" if count_on else "disabled")
        audio = QUALITY_LABELS[self.quality_var.get()] == dl.QUALITY_AUDIO
        self.bitrate_menu.configure(state="normal" if audio and not running else "disabled")
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled",
                                     fg_color="#b03a2e" if running else "gray50")

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
        folder = filedialog.askdirectory(initialdir=self.folder_entry.get() or None)
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, os.path.normpath(folder))

    def _open_folder(self) -> None:
        folder = os.path.expanduser(self.folder_entry.get().strip())
        os.makedirs(folder, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def _show_message(self, title: str, text: str) -> None:
        win = ctk.CTkToplevel(self)
        win.title(title)
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
        folder = self.folder_entry.get().strip() or dl.DEFAULT_OUTPUT_DIR
        return dl.DownloadOptions(
            url=url, mode=mode, count=count,
            quality=QUALITY_LABELS[self.quality_var.get()],
            audio_bitrate=self.bitrate_var.get(),
            save_info=self.save_info_var.get(),
            output_dir=folder,
        )

    def _start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        if not dl.find_ffmpeg():
            self._show_message("Потрібен FFmpeg", dl.FFMPEG_INSTALL_HINT)
            return
        options = self._collect_options()
        if options is None:
            return

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
        if kind == "log":
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

    def _on_close(self) -> None:
        if self._downloader:
            self._downloader.cancel()
        self.destroy()


def main() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    App().mainloop()


if __name__ == "__main__":
    main()
