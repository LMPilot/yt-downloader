import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import settings as s  # noqa: E402


def test_roundtrip(tmp_path):
    path = tmp_path / "cfg" / "settings.json"
    data = {"output_dir": "D:\\Відео\\YT", "quality": "720", "mode": "count", "count": 5}
    assert s.save_settings(data, path) is True
    assert s.load_settings(path) == data


def test_missing_file(tmp_path):
    assert s.load_settings(tmp_path / "none.json") == {}


def test_corrupted_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{не json", encoding="utf-8")
    assert s.load_settings(path) == {}
    path.write_text("[1, 2]", encoding="utf-8")
    assert s.load_settings(path) == {}


def test_save_failure_is_not_fatal(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert s.save_settings({"a": 1}, blocker / "settings.json") is False


def test_config_dir_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(s, "_IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert s.config_dir() == tmp_path / "yt-downloader"


def test_config_dir_fallback(monkeypatch):
    monkeypatch.setattr(s, "_IS_WINDOWS", False)
    assert s.config_dir() == s.Path.home() / ".config" / "yt-downloader"


def test_defaults_on_first_launch(tmp_path):
    data = s.with_defaults(s.load_settings(tmp_path / "none.json"))
    assert data["theme"] == "dark"
    assert data["media"] == "video"
    assert data["audio_format"] == "mp3"


def test_defaults_replace_unknown_values():
    data = s.with_defaults({"theme": "pink", "media": 1, "audio_format": "flac"})
    assert data == s.DEFAULTS


def test_with_defaults_keeps_valid_values_and_input():
    saved = {"theme": "light", "media": "audio", "audio_format": "opus", "count": 3}
    assert s.with_defaults(saved) == saved
    original = {"quality": "audio"}
    s.with_defaults(original)
    assert original == {"quality": "audio"}  # вхідний словник не змінюється


def test_migrates_audio_quality_from_0_1_0():
    data = s.with_defaults({"quality": "audio", "audio_bitrate": "320"})
    assert data["media"] == "audio"
    assert data["audio_bitrate"] == "320"
    assert "quality" not in data
    assert s.with_defaults({"quality": "720"})["media"] == "video"


@pytest.mark.parametrize("theme", s.THEMES)
def test_theme_and_audio_persist(tmp_path, theme):
    path = tmp_path / "settings.json"
    s.save_settings({"theme": theme, "media": "audio", "audio_format": "m4a",
                     "audio_bitrate": "128"}, path)
    data = s.with_defaults(s.load_settings(path))
    assert data["theme"] == theme
    assert data["media"] == "audio"
    assert data["audio_format"] == "m4a"
    assert data["audio_bitrate"] == "128"


def test_audio_formats_match_downloader():
    import downloader
    assert s.AUDIO_FORMATS == downloader.AUDIO_FORMATS
