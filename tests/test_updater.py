import hashlib
import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater as u  # noqa: E402
import version_info  # noqa: E402
from version import __version__  # noqa: E402


def make_release(**overrides):
    data = {
        "tag_name": "v1.2.3",
        "draft": False,
        "prerelease": False,
        "body": "Що нового\r\n- щось",
        "html_url": "https://github.com/LMPilot/yt-downloader/releases/tag/v1.2.3",
        "assets": [
            {"name": "yt-downloader-windows-with-ffmpeg.zip", "size": 1,
             "browser_download_url": "https://example.com/zip"},
            {"name": "yt-downloader.exe", "size": 1234,
             "browser_download_url": "https://example.com/yt-downloader.exe"},
            {"name": "yt-downloader.exe.sha256", "size": 85,
             "browser_download_url": "https://example.com/yt-downloader.exe.sha256"},
        ],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------- версії --

@pytest.mark.parametrize("text, expected", [
    ("1.2.3", (1, 2, 3)),
    ("v1.2.3", (1, 2, 3)),
    ("V10.0.1", (10, 0, 1)),
    ("1.2", (1, 2, 0)),
    (" v2.0.0 ", (2, 0, 0)),
    ("1.2.3-rc1", None),
    ("1.2.3.4", None),
    ("latest", None),
    ("", None),
    (None, None),
])
def test_parse_version(text, expected):
    assert u.parse_version(text) == expected


@pytest.mark.parametrize("remote, current, expected", [
    ("1.0.1", "1.0.0", True),
    ("v1.10.0", "1.9.9", True),   # числове, а не рядкове порівняння
    ("2.0.0", "1.99.99", True),
    ("1.0.0", "1.0.0", False),
    ("v1.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False),
    ("garbage", "1.0.0", False),
    ("1.0.0", "dev", True),
])
def test_is_newer(remote, current, expected):
    assert u.is_newer(remote, current) is expected


def test_version_constant_is_valid():
    assert u.parse_version(__version__) is not None
    assert u.format_version(u.parse_version(__version__)) == __version__


# ------------------------------------------------------------- реліз ----

def test_parse_release_picks_exe_and_checksum():
    info = u.parse_release(make_release())
    assert info.version == "1.2.3"
    assert info.tag == "v1.2.3"
    assert info.asset_url == "https://example.com/yt-downloader.exe"
    assert info.asset_size == 1234
    assert info.checksum_url == "https://example.com/yt-downloader.exe.sha256"
    assert info.notes == "Що нового\r\n- щось"
    assert info.page_url.endswith("/v1.2.3")


@pytest.mark.parametrize("overrides", [
    {"draft": True},
    {"prerelease": True},
    {"tag_name": "nightly"},
    {"tag_name": "v1.3.0-beta"},
    {"assets": []},
    {"assets": [{"name": "yt-downloader.zip", "browser_download_url": "x"}]},
])
def test_parse_release_rejects(overrides):
    assert u.parse_release(make_release(**overrides)) is None


def test_parse_release_rejects_non_dict():
    assert u.parse_release(None) is None
    assert u.parse_release(["x"]) is None
    assert u.parse_release({"message": "Not Found"}) is None


def test_parse_release_without_checksum():
    data = make_release()
    data["assets"] = [a for a in data["assets"] if not a["name"].endswith(".sha256")]
    info = u.parse_release(data)
    assert info is not None and info.checksum_url is None


def test_check_for_update(monkeypatch):
    release = u.parse_release(make_release())
    monkeypatch.setattr(u, "fetch_latest_release", lambda timeout: release)
    assert u.check_for_update("1.0.0") is release
    assert u.check_for_update("1.2.3") is None
    assert u.check_for_update("2.0.0") is None


def test_fetch_latest_release_parses_json(monkeypatch):
    import json

    seen = {}

    def fake_open(url, timeout, accept="*/*"):
        seen.update(url=url, timeout=timeout)
        return io.BytesIO(json.dumps(make_release()).encode())

    monkeypatch.setattr(u, "_open", fake_open)
    info = u.fetch_latest_release(timeout=3)
    assert info.version == "1.2.3"
    assert seen == {"url": u.LATEST_RELEASE_API, "timeout": 3}


# ----------------------------------------------------- контрольна сума --

def test_parse_checksum():
    h = "AB" * 32
    assert u.parse_checksum(f"{h}  yt-downloader.exe\n") == h.lower()
    assert u.parse_checksum(h) == h.lower()
    with pytest.raises(u.UpdateError):
        u.parse_checksum("not a hash")


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, length: int | None = None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


def _serve(monkeypatch, exe_bytes: bytes, checksum_text: str):
    def fake_open(url, timeout, accept="*/*"):
        if url.endswith(".sha256"):
            return FakeResponse(checksum_text.encode())
        return FakeResponse(exe_bytes)

    monkeypatch.setattr(u, "_open", fake_open)


def _release_for(data: bytes):
    rel = u.parse_release(make_release())
    rel.asset_size = len(data)
    return rel


def test_download_update_ok(monkeypatch, tmp_path):
    data = os.urandom(u.CHUNK_SIZE * 2 + 17)
    _serve(monkeypatch, data, hashlib.sha256(data).hexdigest() + "  yt-downloader.exe\n")
    progress = []
    dest = tmp_path / "yt-downloader.exe.new"
    u.download_update(_release_for(data), dest, on_progress=lambda d, t: progress.append((d, t)))
    assert dest.read_bytes() == data
    assert progress[-1] == (len(data), len(data))
    assert len(progress) == 3


def test_download_update_bad_hash_removes_file(monkeypatch, tmp_path):
    data = b"new exe"
    _serve(monkeypatch, data, "0" * 64)
    dest = tmp_path / "new.exe"
    with pytest.raises(u.UpdateError, match="SHA256"):
        u.download_update(_release_for(data), dest)
    assert not dest.exists()


def test_download_update_bad_size(monkeypatch, tmp_path):
    data = b"new exe"
    _serve(monkeypatch, data, hashlib.sha256(data).hexdigest())
    rel = _release_for(data)
    rel.asset_size = 999
    dest = tmp_path / "new.exe"
    with pytest.raises(u.UpdateError, match="Розмір"):
        u.download_update(rel, dest)
    assert not dest.exists()


def test_download_update_requires_checksum(tmp_path):
    rel = _release_for(b"x")
    rel.checksum_url = None
    with pytest.raises(u.UpdateError):
        u.download_update(rel, tmp_path / "new.exe")


def test_download_update_cancel(monkeypatch, tmp_path):
    data = b"x" * 10
    _serve(monkeypatch, data, hashlib.sha256(data).hexdigest())
    dest = tmp_path / "new.exe"
    with pytest.raises(u.UpdateCancelled):
        u.download_update(_release_for(data), dest, is_cancelled=lambda: True)
    assert not dest.exists()


def test_download_update_network_error(monkeypatch, tmp_path):
    def fail(url, timeout, accept="*/*"):
        raise OSError("timed out")

    monkeypatch.setattr(u, "_open", fail)
    with pytest.raises(u.UpdateError, match="timed out"):
        u.download_update(_release_for(b"x"), tmp_path / "new.exe")


# -------------------------------------------------------- шляхи і скрипт --

def test_current_exe_uses_sys_executable(monkeypatch, tmp_path):
    exe = tmp_path / "Програми" / "yt-downloader.exe"
    monkeypatch.setattr(sys, "executable", str(exe))
    assert u.current_exe() == exe.resolve()


def test_update_paths_next_to_exe(tmp_path):
    exe = tmp_path / "yt-downloader.exe"
    new, backup, script = u.update_paths(exe)
    assert new == tmp_path / "yt-downloader.exe.new"
    assert backup == tmp_path / "yt-downloader.exe.old"
    assert script == tmp_path / u.HELPER_NAME
    assert all(p.parent == exe.parent for p in (new, backup, script))


def test_update_script_contents():
    script = u.build_update_script(4321)
    script.encode("ascii")  # cmd.exe читає .cmd в OEM-кодуванні — лише ASCII
    assert script.endswith("\r\n") and "\n" not in script.replace("\r\n", "")
    lines = script.split("\r\n")
    assert lines[0] == "@echo off"
    # чекає саме на наш PID
    assert ('"%SYS%\\tasklist.exe" /NH /FI "PID eq 4321" 2>nul '
            '| "%SYS%\\find.exe" " 4321 " >nul') in lines
    # резервна копія → встановлення → відкат → запуск → самовидалення
    order = [
        'move /y "%YTD_UPDATE_TARGET%" "%YTD_UPDATE_BACKUP%" >nul 2>&1',
        'move /y "%YTD_UPDATE_NEW%" "%YTD_UPDATE_TARGET%" >nul 2>&1',
        'move /y "%YTD_UPDATE_BACKUP%" "%YTD_UPDATE_TARGET%" >nul 2>&1',
        'start "" "%YTD_UPDATE_TARGET%"',
        '(goto) 2>nul & del /f /q "%~f0"',
    ]
    positions = [lines.index(line) for line in order]
    assert positions == sorted(positions)
    # усі goto ведуть на існуючі мітки
    labels = {line[1:] for line in lines if line.startswith(":")}
    targets = {line.split("goto ")[1] for line in lines
               if "goto " in line and not line.startswith("(goto)")}
    assert targets <= labels


def test_update_script_rejects_non_int_pid():
    with pytest.raises(ValueError):
        u.build_update_script("1 & del C:\\")


def test_clean_environment():
    mei = os.path.join(os.sep, "tmp", "_MEI12345")
    env = {
        "PATH": os.pathsep.join([os.path.join(mei, "bin"), "/usr/bin", ""]),
        "TCL_LIBRARY": os.path.join(mei, "tcl"),
        "_PYI_APPLICATION_HOME_DIR": mei,
        "_MEIPASS2": mei,
        "HOME": "/home/user",
        "EMPTY": "",
    }
    clean = u.clean_environment(env, mei)
    assert clean == {"PATH": "/usr/bin", "HOME": "/home/user", "EMPTY": "",
                     "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    assert u.clean_environment({"PATH": "/usr/bin"}, None)["PATH"] == "/usr/bin"


def test_launch_update_helper(monkeypatch, tmp_path):
    calls = {}

    def fake_popen(args, **kwargs):
        calls.update(args=args, **kwargs)

    monkeypatch.setattr(u.subprocess, "Popen", fake_popen)
    exe = tmp_path / "yt-downloader.exe"
    new = tmp_path / "yt-downloader.exe.new"
    script = u.launch_update_helper(new, exe)
    assert script == tmp_path / u.HELPER_NAME
    assert f"PID eq {os.getpid()}" in script.read_text(encoding="ascii")
    assert calls["args"] == u.helper_command(script)
    env = calls["env"]
    assert env[u.ENV_TARGET] == str(exe)
    assert env[u.ENV_NEW] == str(new)
    assert env[u.ENV_BACKUP] == str(tmp_path / "yt-downloader.exe.old")
    assert calls["cwd"] == str(tmp_path)


# --------------------------------------------------------- version info --

def test_version_info_render():
    text = version_info.render("1.2.3")
    assert "filevers=(1, 2, 3, 0)" in text
    assert "StringStruct('ProductVersion', '1.2.3')" in text
    assert f"'{__version__}'" in version_info.render()


@pytest.mark.skipif(sys.platform != "win32", reason="парсер PyInstaller працює лише на Windows")
def test_version_info_is_valid_for_pyinstaller(tmp_path):
    pytest.importorskip("PyInstaller")
    from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file

    path = tmp_path / "version_info.txt"
    path.write_text(version_info.render("1.2.3"), encoding="utf-8")
    info = load_version_info_from_text_file(str(path))
    assert info.ffi.fileVersionMS == (1 << 16) | 2


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe є лише на Windows")
def test_update_script_runs_in_cmd(tmp_path):
    """Справжній запуск скрипта: чекає на процес, замінює exe, лишає .old."""
    import shutil
    import subprocess
    import time

    folder = tmp_path / "Мої програми & ще"
    folder.mkdir()
    exe = folder / "yt-downloader.exe"
    new, backup, script = u.update_paths(exe)
    system_exe = Path(os.environ["SystemRoot"]) / "System32" / "hostname.exe"
    shutil.copyfile(system_exe, exe)
    old_bytes = exe.read_bytes()
    new_bytes = old_bytes + b"NEW"  # дописані байти не заважають запуску exe
    new.write_bytes(new_bytes)

    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    script.write_bytes(u.build_update_script(sleeper.pid).encode("ascii"))
    env = dict(os.environ, **{u.ENV_TARGET: str(exe), u.ENV_NEW: str(new),
                              u.ENV_BACKUP: str(backup)})
    started = time.monotonic()
    log = tmp_path / "cmd.log"
    with open(log, "wb") as out:
        subprocess.run(u.helper_command(script), env=env, cwd=str(folder),
                       timeout=120, check=False, stdout=out, stderr=subprocess.STDOUT)
    output = log.read_bytes().decode("oem", "replace")
    assert sleeper.poll() is not None, output
    assert time.monotonic() - started >= 2  # справді чекав на процес
    assert exe.read_bytes() == new_bytes
    assert backup.read_bytes() == old_bytes
    assert not new.exists()
    for _ in range(50):
        if not script.exists():
            break
        time.sleep(0.1)
    assert not script.exists()


def test_helper_command_quotes_special_paths(monkeypatch):
    monkeypatch.setenv("ComSpec", r"C:\Windows\system32\cmd.exe")
    script = Path(r"C:\Program Files (x86)\A & B\yt-downloader-update.cmd")
    assert u.helper_command(script) == (
        r'"C:\Windows\system32\cmd.exe" /d /s /c ""C:\Program Files (x86)\A & B'
        r'\yt-downloader-update.cmd""')


def test_fetch_latest_release_no_releases(monkeypatch):
    import urllib.error

    def not_found(url, timeout, accept="*/*"):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(u, "_open", not_found)
    assert u.fetch_latest_release() is None


def test_fetch_latest_release_other_http_error(monkeypatch):
    import urllib.error

    def forbidden(url, timeout, accept="*/*"):
        raise urllib.error.HTTPError(url, 403, "rate limit", {}, None)

    monkeypatch.setattr(u, "_open", forbidden)
    with pytest.raises(OSError):
        u.fetch_latest_release()
