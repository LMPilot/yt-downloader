import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import downloader as d  # noqa: E402


# ---------------------------------------------------------------- info.txt ---

def test_info_text_format():
    text = d.format_info_text("Назва відео", "Опис\nдругий рядок")
    lines = text.split("\n")
    assert lines[0] == "Назва відео"
    assert lines[1:4] == ["", "", ""]
    assert lines[4] == "Опис"
    assert lines[5] == "другий рядок"
    assert text == "Назва відео\n\n\n\nОпис\nдругий рядок"


def test_info_text_empty_description():
    assert d.format_info_text("Title", None) == "Title\n\n\n\n"
    assert d.format_info_text("Title", "") == "Title\n\n\n\n"


def test_info_text_normalizes_windows_newlines():
    assert d.format_info_text("T", "a\r\nb\rc") == "T\n\n\n\na\nb\nc"


def test_info_text_title_is_single_line():
    assert d.format_info_text("Line\none", "x").split("\n")[0] == "Line one"


def test_write_info_file_utf8(tmp_path):
    path = d.write_info_file(tmp_path / "sub", "Привіт 🎬", "Опис ✓")
    assert path.name == "info.txt"
    raw = path.read_bytes()
    assert raw.decode("utf-8") == "Привіт 🎬\n\n\n\nОпис ✓"
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0] == "Привіт 🎬"
    assert lines[4] == "Опис ✓"


# ---------------------------------------------------------- folder names ---

@pytest.mark.parametrize("char, lookalike", [
    (":", "："), ("?", "？"), ("/", "⧸"), ("\\", "⧹"), ("*", "＊"),
    ('"', "＂"), ("<", "＜"), (">", "＞"), ("|", "｜"),
])
def test_sanitize_replaces_forbidden_chars_with_lookalikes(char, lookalike):
    assert d.sanitize_folder_name(f"a{char}b") == f"a{lookalike}b"


def test_sanitize_matches_youtube_title():
    assert d.sanitize_folder_name("Відео: огляд?") == "Відео： огляд？"


@pytest.mark.parametrize("title", [
    "Відео частина 1 🎬",
    "Rock'n'roll #1 & co (live) [4K] — 100%",
    "__init__ та -флаги ~ $HOME %(title)s",
    "a  b",
])
def test_sanitize_keeps_other_chars(title):
    assert d.sanitize_folder_name(title) == title


def test_sanitize_control_chars_and_newlines():
    assert d.sanitize_folder_name("a\x00b\x07c") == "a b c"
    assert d.sanitize_folder_name("a\r\nb\tc") == "a b c"


@pytest.mark.parametrize("name, expected", [
    ("Title.", "Title"),
    ("Title...", "Title"),
    ("Title . . ", "Title"),
    ("Title   ", "Title"),
    ("...Title", "Title"),
    ("Що?.", "Що？"),
])
def test_sanitize_strips_dots_and_spaces(name, expected):
    assert d.sanitize_folder_name(name) == expected


def test_sanitize_length_limit():
    result = d.sanitize_folder_name("x" * 500)
    assert len(result) == d.MAX_NAME_LENGTH == 150


def test_sanitize_length_limit_no_trailing_dot_after_cut():
    name = "a" * 149 + ". tail"
    result = d.sanitize_folder_name(name)
    assert len(result) <= d.MAX_NAME_LENGTH
    assert not result.endswith((".", " "))


def test_sanitize_custom_length():
    assert d.sanitize_folder_name("abcdef", max_length=3) == "abc"


@pytest.mark.parametrize("name", ["", None, "   ", "...", " . . ", "\n\t"])
def test_sanitize_empty(name):
    assert d.sanitize_folder_name(name) == "video"


@pytest.mark.parametrize("name", ["CON", "con", "NUL", "COM1", "LPT9", "aux.txt", "PRN. "])
def test_sanitize_reserved_names(name):
    result = d.sanitize_folder_name(name)
    assert result.split(".")[0].upper() not in {"CON", "NUL", "COM1", "LPT9", "AUX", "PRN"}


def test_sanitize_reserved_name_only_whole_stem():
    assert d.sanitize_folder_name("Console: огляд") == "Console： огляд"


def test_max_name_length_short_dir():
    # Назва трапляється у шляху двічі (папка й файл), тож навіть для «C:\\YT»
    # межа MAX_PATH менша за MAX_NAME_LENGTH.
    limit = d.max_name_length("C:\\YT")
    assert limit == (259 - 5 - 2 - 24) // 2 > 80


def test_max_name_length_counts_utf16():
    assert d.max_name_length("C:\\🎬🎬") == d.max_name_length("C:\\abcd")


def test_max_name_length_fits_windows_path():
    folder = "C:\\Users\\Користувач\\Downloads\\YT"
    limit = d.max_name_length(folder)
    assert d.MIN_NAME_LENGTH <= limit < d.MAX_NAME_LENGTH
    name = "x" * limit
    path = f"{folder}\\{name}\\{name}.f137.mp4.part"
    assert len(path) < 260


def test_max_name_length_very_long_dir():
    assert d.max_name_length("C:\\" + "a" * 300) == d.MIN_NAME_LENGTH


def test_folder_name_uses_output_dir_limit():
    folder = "C:\\" + "d" * 150
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=folder))
    name = dl.folder_name_for("я" * 300, "id1")
    assert len(name) == d.max_name_length(os.path.abspath(folder))


def test_unique_folder_names_for_duplicate_titles():
    dl = d.Downloader(d.DownloadOptions(url="x"))
    assert dl.folder_name_for("Same", "id1") == "Same"
    assert dl.folder_name_for("Same", "id1") == "Same"
    assert dl.folder_name_for("Same", "id2") == "Same [id2]"


def test_duplicate_long_title_keeps_id_within_limit(tmp_path):
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path)))
    limit = d.max_name_length(str(tmp_path))
    title = "Довга назва: " + "x" * 300
    assert len(dl.folder_name_for(title, "aaaaaaaaaaa")) == limit
    second = dl.folder_name_for(title, "bbbbbbbbbbb")
    assert second.endswith(" [bbbbbbbbbbb]")
    assert second.startswith("Довга назва： ")
    assert len(second) <= limit


# ---------------------------------------------------------------- URLs ---

@pytest.mark.parametrize("url, expected", [
    ("https://www.youtube.com/@name", "https://www.youtube.com/@name/videos"),
    ("https://www.youtube.com/@name/", "https://www.youtube.com/@name/videos"),
    ("https://www.youtube.com/@name/featured", "https://www.youtube.com/@name/videos"),
    ("youtube.com/@name", "https://youtube.com/@name/videos"),
    ("https://www.youtube.com/channel/UC123", "https://www.youtube.com/channel/UC123/videos"),
    ("https://www.youtube.com/c/Name", "https://www.youtube.com/c/Name/videos"),
    ("https://m.youtube.com/user/Name", "https://m.youtube.com/user/Name/videos"),
    ("https://www.youtube.com/@name/videos", "https://www.youtube.com/@name/videos"),
    ("https://www.youtube.com/@name/shorts", "https://www.youtube.com/@name/shorts"),
    ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
    ("https://youtu.be/abc", "https://youtu.be/abc"),
    ("https://www.youtube.com/playlist?list=PL1", "https://www.youtube.com/playlist?list=PL1"),
    ("  https://www.youtube.com/@name  ", "https://www.youtube.com/@name/videos"),
])
def test_normalize_url(url, expected):
    assert d.normalize_url(url) == expected


# ---------------------------------------------------------- yt-dlp params ---

def test_format_options_video():
    opts = d.build_format_options("1080")
    assert opts["merge_output_format"] == "mp4"
    assert opts["format_sort"][0] == "res:1080"


def test_format_options_audio():
    opts = d.build_format_options("audio", "320")
    pp = opts["postprocessors"][0]
    assert pp["key"] == "FFmpegExtractAudio"
    assert pp["preferredcodec"] == "mp3"
    assert pp["preferredquality"] == "320"


@pytest.mark.parametrize("fmt, source", [
    ("mp3", "bestaudio/best"),
    ("m4a", "bestaudio[ext=m4a]/bestaudio/best"),
    ("opus", "bestaudio[acodec=opus]/bestaudio/best"),
])
def test_format_options_audio_formats(fmt, source):
    opts = d.build_format_options(d.QUALITY_AUDIO, "128", fmt)
    assert opts["format"] == source
    assert "merge_output_format" not in opts
    [pp] = opts["postprocessors"]
    assert pp["key"] == "FFmpegExtractAudio"
    assert pp["preferredcodec"] == fmt
    # Бітрейт задається лише для MP3; M4A/OPUS без перекодування, якщо можна.
    assert pp.get("preferredquality") == ("128" if fmt == "mp3" else None)


def test_format_options_audio_default_is_mp3():
    pp = d.build_format_options(d.QUALITY_AUDIO)["postprocessors"][0]
    assert pp["preferredcodec"] == "mp3"
    assert pp["preferredquality"] == "192"
    assert d.DownloadOptions(url="x").audio_format == "mp3"


def test_format_options_bitrate_ignored_for_other_formats():
    # Бітрейт MP3 не має значення для M4A/OPUS — навіть невідомий не є помилкою.
    assert d.build_format_options(d.QUALITY_AUDIO, "64", "opus")


def test_format_options_invalid():
    with pytest.raises(ValueError):
        d.build_format_options("999")
    with pytest.raises(ValueError):
        d.build_format_options("audio", "64")
    with pytest.raises(ValueError):
        d.build_format_options("audio", "192", "flac")


def test_ydl_params_modes(tmp_path):
    def params(**kw):
        return d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path), **kw)).build_ydl_params()

    single = params(mode=d.MODE_SINGLE)
    assert single["noplaylist"] is True and single["playlistend"] == 1
    assert params(mode=d.MODE_COUNT, count=5)["playlistend"] == 5
    assert "playlistend" not in params(mode=d.MODE_ALL)
    assert params()["ignoreerrors"] is True
    with pytest.raises(ValueError):
        params(mode=d.MODE_COUNT, count=0)


@pytest.mark.parametrize("mode", [d.MODE_SINGLE, d.MODE_COUNT, d.MODE_ALL])
@pytest.mark.parametrize("fmt", d.AUDIO_FORMATS)
def test_ydl_params_audio_every_mode(tmp_path, mode, fmt):
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path), mode=mode, count=3,
                                        quality=d.QUALITY_AUDIO, audio_format=fmt,
                                        audio_bitrate="320"))
    params = dl.build_ydl_params()
    # Кожен файл — у власній підпапці, як і для відео.
    assert params["outtmpl"]["default"] == "%(yt_folder)s/%(yt_folder)s.%(ext)s"
    assert params["postprocessors"][0]["preferredcodec"] == fmt
    assert "format_sort" not in params


@pytest.mark.parametrize("fmt", d.AUDIO_FORMATS)
def test_audio_params_accepted_by_yt_dlp(tmp_path, fmt):
    import yt_dlp
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path),
                                        quality=d.QUALITY_AUDIO, audio_format=fmt))
    with yt_dlp.YoutubeDL(dl.build_ydl_params()) as ydl:
        [pp] = ydl._pps["post_process"]
        assert type(pp).__name__ == "FFmpegExtractAudioPP"
        assert pp.mapping == fmt


@pytest.mark.parametrize("quality", [d.QUALITY_BEST, d.QUALITY_AUDIO])
def test_ydl_params_thumbnail(tmp_path, quality):
    def params(**kw):
        return d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path),
                                              quality=quality, **kw)).build_ydl_params()

    on = params()  # типово прев'ю зберігається
    assert on["writethumbnail"] is True
    assert on["outtmpl"]["thumbnail"] == "%(yt_folder)s/preview.%(ext)s"
    assert {"key": "FFmpegThumbnailsConvertor", "format": "jpg",
            "when": "before_dl"} in on["postprocessors"]

    off = params(save_thumbnail=False)
    assert "writethumbnail" not in off
    assert "thumbnail" not in off["outtmpl"]
    assert all(pp["key"] != "FFmpegThumbnailsConvertor"
               for pp in off.get("postprocessors", []))


def test_thumbnail_params_accepted_by_yt_dlp(tmp_path):
    import yt_dlp
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path),
                                        quality=d.QUALITY_AUDIO))
    with yt_dlp.YoutubeDL(dl.build_ydl_params()) as ydl:
        [pp] = ydl._pps["before_dl"]
        assert type(pp).__name__ == "FFmpegThumbnailsConvertorPP"
        # Аудіо-постпроцесор і далі єдиний після завантаження.
        [audio_pp] = ydl._pps["post_process"]
        assert type(audio_pp).__name__ == "FFmpegExtractAudioPP"


def test_finish_pp_writes_info_next_to_audio(tmp_path):
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path),
                                        quality=d.QUALITY_AUDIO))
    folder = tmp_path / "Пісня"
    folder.mkdir()
    info = {"filepath": str(folder / "Пісня.mp3"), "title": "Пісня", "description": "Опис"}
    d._FinishPP(dl).run(info)
    assert (folder / "info.txt").read_text(encoding="utf-8") == "Пісня\n\n\n\nОпис"
    assert dl.result.downloaded == 1


def test_params_accepted_by_yt_dlp(tmp_path):
    import yt_dlp
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path), mode=d.MODE_COUNT, count=3))
    with yt_dlp.YoutubeDL(dl.build_ydl_params()) as ydl:
        ydl.add_post_processor(d._FolderNamePP(dl), when="pre_process")
        ydl.add_post_processor(d._FinishPP(dl), when="after_move")


@pytest.mark.parametrize("title", [
    "Відео: огляд?", '__init__ — <b>|*/\\"', "-5% $HOME ~ #1 & 'ok' 🎬", "a\nb\x07", "12:30",
])
def test_yt_dlp_keeps_sanitized_name(title):
    from yt_dlp.utils import sanitize_filename
    name = d.sanitize_folder_name(title)
    assert sanitize_filename(name) == name


def _download_local(tmp_path, titles, save_thumbnail=False):
    """Справжній прогін yt-dlp на локальному файлі замість YouTube."""
    import yt_dlp
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\0" * 1024)
    out = tmp_path / "out"
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(out),
                                        save_thumbnail=save_thumbnail))
    params = dl.build_ydl_params()
    params["enable_file_urls"] = True
    with yt_dlp.YoutubeDL(params) as ydl:
        ydl.add_post_processor(d._FolderNamePP(dl), when="pre_process")
        ydl.add_post_processor(d._FinishPP(dl), when="after_move")
        for i, title in enumerate(titles):
            ydl.process_ie_result({
                "id": f"vid{i}", "title": title, "description": "Опис",
                "extractor": "test", "extractor_key": "Test", "webpage_url": "http://x",
                "formats": [{"url": src.as_uri(), "ext": "mp4", "format_id": "18",
                             "vcodec": "avc1", "acodec": "mp4a"}],
            }, download=True)
    return dl, out


@pytest.mark.parametrize("title, name", [
    ("Відео: огляд?", "Відео： огляд？"),
    ('__init__ — <b>|*/\\"', "__init__ — ＜b＞｜＊⧸⧹＂"),
    ("-5% знижка $HOME %(title)s ~ #1 & 'ok' 🎬", "-5% знижка $HOME %(title)s ~ #1 & 'ok' 🎬"),
])
def test_file_on_disk_named_like_title(tmp_path, title, name):
    dl, out = _download_local(tmp_path, [title])
    assert dl.result.downloaded == 1, dl.result.errors
    assert (out / name / f"{name}.mp4").is_file()
    assert (out / name / "info.txt").read_text(encoding="utf-8").startswith(title)


def test_file_on_disk_duplicate_titles(tmp_path):
    dl, out = _download_local(tmp_path, ["Те саме?", "Те саме?"])
    assert dl.result.downloaded == 2, dl.result.errors
    assert (out / "Те саме？" / "Те саме？.mp4").is_file()
    assert (out / "Те саме？ [vid1]" / "Те саме？ [vid1].mp4").is_file()


def test_thumbnail_path_uses_same_folder(tmp_path):
    import yt_dlp
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path)))
    with yt_dlp.YoutubeDL(dl.build_ydl_params()) as ydl:
        info = {"id": "a", "title": "x", "ext": "webp", "yt_folder": "__Що？__"}
        path = ydl.prepare_filename(info, "thumbnail")
    assert path == os.path.join(str(tmp_path), "__Що？__", "preview.webp")


# ------------------------------------------------------- папка завантаження ---

def test_prepare_output_dir_creates_missing(tmp_path):
    target = tmp_path / "a" / "b"
    result = d.prepare_output_dir(str(target))
    assert target.is_dir()
    assert result == str(target.resolve())
    assert list(target.iterdir()) == []  # тестовий файл прибрано


def test_prepare_output_dir_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert d.prepare_output_dir("~/YT") == str((tmp_path / "YT").resolve())


def test_prepare_output_dir_rejects_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(OSError, match="не папка"):
        d.prepare_output_dir(str(f))


def test_prepare_output_dir_rejects_empty():
    with pytest.raises(OSError):
        d.prepare_output_dir("  ")


def test_prepare_output_dir_not_writable(tmp_path, monkeypatch):
    def deny(self, data):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(d.Path, "write_bytes", deny)
    with pytest.raises(OSError, match="Немає дозволу на запис"):
        d.prepare_output_dir(str(tmp_path / "x"))
