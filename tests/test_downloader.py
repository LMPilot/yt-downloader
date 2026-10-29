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

@pytest.mark.parametrize("char", list('<>:"/\\|?*'))
def test_sanitize_replaces_forbidden_chars(char):
    result = d.sanitize_folder_name(f"a{char}b")
    assert result == "a_b"


def test_sanitize_control_chars():
    assert d.sanitize_folder_name("a\x00b\x07c") == "a_b_c"


def test_sanitize_collapses_whitespace():
    assert d.sanitize_folder_name("  a \t\n  b  ") == "a b"


@pytest.mark.parametrize("name, expected", [
    ("Title.", "Title"),
    ("Title...", "Title"),
    ("Title . . ", "Title"),
    ("Title   ", "Title"),
    ("...Title", "Title"),
])
def test_sanitize_strips_dots_and_spaces(name, expected):
    assert d.sanitize_folder_name(name) == expected


def test_sanitize_length_limit():
    result = d.sanitize_folder_name("x" * 500)
    assert len(result) == d.MAX_NAME_LENGTH


def test_sanitize_length_limit_no_trailing_dot_after_cut():
    name = "a" * 79 + ". tail"
    result = d.sanitize_folder_name(name)
    assert len(result) <= d.MAX_NAME_LENGTH
    assert not result.endswith((".", " "))


def test_sanitize_custom_length():
    assert d.sanitize_folder_name("abcdef", max_length=3) == "abc"


@pytest.mark.parametrize("name", ["", None, "   ", "...", " . . "])
def test_sanitize_empty(name):
    assert d.sanitize_folder_name(name) == "video"


@pytest.mark.parametrize("name", ["CON", "con", "NUL", "COM1", "LPT9", "aux.txt"])
def test_sanitize_reserved_names(name):
    result = d.sanitize_folder_name(name)
    assert result.split(".")[0].upper() not in {"CON", "NUL", "COM1", "LPT9", "AUX"}


def test_sanitize_keeps_unicode():
    assert d.sanitize_folder_name("Відео: частина 1 🎬") == "Відео_ частина 1 🎬"


def test_unique_folder_names_for_duplicate_titles():
    dl = d.Downloader(d.DownloadOptions(url="x"))
    assert dl.folder_name_for("Same", "id1") == "Same"
    assert dl.folder_name_for("Same", "id1") == "Same"
    assert dl.folder_name_for("Same", "id2") == "Same [id2]"


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


def test_format_options_invalid():
    with pytest.raises(ValueError):
        d.build_format_options("999")
    with pytest.raises(ValueError):
        d.build_format_options("audio", "64")


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


def test_params_accepted_by_yt_dlp(tmp_path):
    import yt_dlp
    dl = d.Downloader(d.DownloadOptions(url="x", output_dir=str(tmp_path), mode=d.MODE_COUNT, count=3))
    with yt_dlp.YoutubeDL(dl.build_ydl_params()) as ydl:
        ydl.add_post_processor(d._FolderNamePP(dl), when="pre_process")
        ydl.add_post_processor(d._FinishPP(dl), when="after_move")
