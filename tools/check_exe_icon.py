"""Перевіряє, що в exe вшита саме наша іконка (а не стандартна PyInstaller).

Використання (у CI після збірки):
    python tools/check_exe_icon.py dist\\yt-downloader.exe assets\\icon.ico
"""

from __future__ import annotations

import struct
import sys

import pefile  # встановлюється разом із PyInstaller у Windows


def ico_images(path: str) -> list[bytes]:
    data = open(path, "rb").read()
    _, _, count = struct.unpack_from("<HHH", data, 0)
    images = []
    for i in range(count):
        size, offset = struct.unpack_from("<II", data, 6 + 16 * i + 8)
        images.append(data[offset:offset + size])
    return images


def exe_icons(path: str) -> list[bytes]:
    pe = pefile.PE(path)
    icons = []
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id != pefile.RESOURCE_TYPE["RT_ICON"]:
            continue
        for item in entry.directory.entries:
            for lang in item.directory.entries:
                rva, size = lang.data.struct.OffsetToData, lang.data.struct.Size
                icons.append(pe.get_data(rva, size))
    return icons


def main(exe: str, ico: str) -> int:
    expected = ico_images(ico)
    embedded = exe_icons(exe)
    missing = [i for i, image in enumerate(expected) if image not in embedded]
    print(f"{ico}: {len(expected)} images, {exe}: {len(embedded)} icon resources")
    if missing:
        print(f"Images not embedded in exe: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
