"""Генерує файл версії Windows для PyInstaller (``--version-file``).

Використання: ``python version_info.py build\\version_info.txt``
(викликається з ``build.ps1``). Номер береться з ``version.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from version import __version__

TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tuple},
    prodvers={tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'LMPilot'),
        StringStruct('FileDescription', 'YouTube Downloader'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'yt-downloader'),
        StringStruct('OriginalFilename', 'yt-downloader.exe'),
        StringStruct('ProductName', 'YouTube Downloader'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def render(version: str = __version__) -> str:
    parts = [int(p) for p in version.split(".")]
    numbers = tuple((parts + [0, 0, 0, 0])[:4])
    return TEMPLATE.format(tuple=numbers, version=version)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "build/version_info.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8")
    print(target)
