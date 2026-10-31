"""Генерує іконку програми: assets/icon.ico (16–256 px) та assets/icon.png (256 px).

Іконка — синій квадрат із заокругленими кутами й градієнтом (кольори теми
CustomTkinter «blue», як у рамці папки в app.py) та білою стрілкою «завантажити».
Той самий icon.png показується в заголовку вікна, тож вони не розходяться.

Запуск (у папці репозиторію):
    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

GRADIENT_TOP = (0x3B, 0x8E, 0xD0)     # світлий синій угорі зліва
GRADIENT_BOTTOM = (0x1F, 0x6A, 0xA5)  # темний синій унизу справа
GLYPH = (255, 255, 255)
CORNER_RADIUS = 0.22  # частка від сторони
_SCALE = 4  # малюємо більшим і зменшуємо — згладжені краї


def draw_icon(size: int) -> Image.Image:
    """Іконка ``size``×``size`` (RGBA)."""
    big = size * _SCALE
    # Діагональний градієнт: зліва вгорі → справа внизу.
    ramp = Image.linear_gradient("L").resize((big, big))  # 0 угорі → 255 унизу
    mask = ImageChops.add(ramp, ramp.transpose(Image.Transpose.TRANSPOSE), scale=2)
    gradient = Image.composite(Image.new("RGB", (big, big), GRADIENT_BOTTOM),
                               Image.new("RGB", (big, big), GRADIENT_TOP), mask)

    shape = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shape).rounded_rectangle((0, 0, big - 1, big - 1),
                                            radius=round(big * CORNER_RADIUS), fill=255)
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    icon.paste(gradient, (0, 0), shape)

    # Стрілка вниз над «лотком» — знак завантаження.
    draw = ImageDraw.Draw(icon)
    u = big / 64
    shaft = round(7 * u)
    draw.rectangle((32 * u - shaft / 2, 13 * u, 32 * u + shaft / 2, 34 * u), fill=GLYPH)
    draw.polygon([(18 * u, 30 * u), (46 * u, 30 * u), (32 * u, 45 * u)], fill=GLYPH)
    draw.rounded_rectangle((15 * u, 47 * u, 49 * u, 53 * u), radius=round(3 * u), fill=GLYPH)
    return icon.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    draw_icon(256).save(ASSETS / "icon.png", optimize=True)
    images = [draw_icon(size) for size in ICO_SIZES]
    images[-1].save(ASSETS / "icon.ico", format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    print(f"Збережено {ASSETS / 'icon.png'} та {ASSETS / 'icon.ico'}")


if __name__ == "__main__":
    main()
