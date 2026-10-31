import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import make_icon  # noqa: E402


def test_ico_has_all_sizes():
    with Image.open(ROOT / "assets" / "icon.ico") as ico:
        assert ico.info["sizes"] == {(s, s) for s in make_icon.ICO_SIZES}


def test_png_is_256_with_transparent_corners():
    with Image.open(ROOT / "assets" / "icon.png") as png:
        assert png.size == (256, 256)
        assert png.convert("RGBA").getpixel((0, 0))[3] == 0


def test_committed_icon_matches_generator():
    # Якщо змінили tools/make_icon.py — перегенеруйте assets (python tools/make_icon.py).
    with Image.open(ROOT / "assets" / "icon.png") as png:
        diff = ImageChops.difference(png.convert("RGBA"), make_icon.draw_icon(256))
    assert max(ImageStat.Stat(diff).mean) < 1


def test_gradient_uses_theme_blues():
    icon = make_icon.draw_icon(256)
    top_left = icon.getpixel((40, 40))[:3]
    bottom_right = icon.getpixel((215, 215))[:3]
    assert top_left[2] > bottom_right[2]  # світліший угорі зліва
    assert all(abs(a - b) < 20 for a, b in zip(top_left, make_icon.GRADIENT_TOP))


def test_app_resolves_icon_from_meipass(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT))
    try:
        import app
    except ImportError:  # немає tkinter
        return
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert app.resource_path("icon.ico") == tmp_path / "assets" / "icon.ico"
    monkeypatch.delattr(sys, "_MEIPASS")
    assert app.resource_path("icon.png") == ROOT / "assets" / "icon.png"
    assert os.path.isfile(app.ICON_ICO)
