import os
import sys

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
