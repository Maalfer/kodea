#!/usr/bin/env python3
"""Genera los iconos de la app a partir de `kodea.icons.app_pixmap`.

Renderiza el logo de Kodea (el mismo que usa la ventana) a varios PNG con Qt en
modo *offscreen* y los ensambla en los formatos que piden los instaladores:

- ``build/icon.ico``  (Windows / Inno Setup)   — vía Pillow
- ``build/icon.icns`` (macOS / .app)           — vía `iconutil` (solo macOS)
- ``build/icon_256.png`` y demás PNG           — Linux / .desktop

Pillow es opcional: si no está, se omite el .ico (la build sigue, sin icono).
"""
from __future__ import annotations

import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build")
SIZES = [16, 32, 48, 64, 128, 256, 512, 1024]


def main() -> int:
    sys.path.insert(0, ROOT)
    app = QApplication([])  # necesario para QPixmap/QPainter
    from kodea.icons import app_pixmap

    os.makedirs(OUT, exist_ok=True)
    png_paths: dict[int, str] = {}
    for size in SIZES:
        path = os.path.join(OUT, f"icon_{size}.png")
        app_pixmap(size).save(path, "PNG")
        png_paths[size] = path
    print(f"PNG generados: {', '.join(map(str, SIZES))}")

    _make_ico(png_paths)
    if sys.platform == "darwin":
        _make_icns(png_paths)
    del app
    return 0


def _make_ico(png_paths: dict[int, str]):
    try:
        from PIL import Image
    except ImportError:
        print("Pillow no instalado: se omite icon.ico")
        return
    ico_sizes = [16, 32, 48, 64, 128, 256]
    base = Image.open(png_paths[256]).convert("RGBA")
    out = os.path.join(OUT, "icon.ico")
    base.save(out, format="ICO", sizes=[(s, s) for s in ico_sizes])
    print(f"icon.ico generado ({out})")


def _make_icns(png_paths: dict[int, str]):
    """Construye un .iconset y lo convierte con `iconutil` (macOS)."""
    iconset = os.path.join(OUT, "Kodea.iconset")
    os.makedirs(iconset, exist_ok=True)
    # nombres que espera iconutil: icon_<size>x<size>[@2x].png
    mapping = [
        (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
    ]
    from PySide6.QtGui import QPixmap
    for size, name in mapping:
        QPixmap(png_paths[size]).save(os.path.join(iconset, name), "PNG")
    out = os.path.join(OUT, "icon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
    print(f"icon.icns generado ({out})")


if __name__ == "__main__":
    raise SystemExit(main())
