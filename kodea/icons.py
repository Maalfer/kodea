"""Iconos de la app: logo (logo.png) e iconos generados por código (archivos,
carpetas, servidor)."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)


def _assets_dir() -> str:
    """Carpeta de assets, también cuando la app va empaquetada (PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "kodea", "assets")  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(__file__), "assets")


LOGO_PATH = os.path.join(_assets_dir(), "logo.png")

# color por extensión (paleta tipo GitHub/Seti)
EXT_COLORS = {
    "py": ("#3572A5", "Py"),
    "js": ("#e8d44d", "JS"),
    "jsx": ("#e8d44d", "JS"),
    "ts": ("#3178c6", "TS"),
    "tsx": ("#3178c6", "TS"),
    "mjs": ("#e8d44d", "JS"),
    "json": ("#b8a038", "{}"),
    "html": ("#e34c26", "<>"),
    "htm": ("#e34c26", "<>"),
    "css": ("#9376bd", "#"),
    "scss": ("#c6538c", "#"),
    "md": ("#519aba", "M"),
    "sh": ("#6aa84f", "$"),
    "bash": ("#6aa84f", "$"),
    "zsh": ("#6aa84f", "$"),
    "php": ("#7377ad", "P"),
    "rb": ("#9c3328", "Rb"),
    "go": ("#00ADD8", "Go"),
    "rs": ("#c77b4f", "Rs"),
    "sql": ("#d08770", "Q"),
    "yml": ("#a8334b", "Y"),
    "yaml": ("#a8334b", "Y"),
    "toml": ("#9c4221", "T"),
    "ini": ("#8a8a8a", "≡"),
    "conf": ("#8a8a8a", "≡"),
    "env": ("#c2a633", "$"),
    "txt": ("#9a9a9a", "≡"),
    "log": ("#9a9a9a", "≡"),
    "lock": ("#8a8a8a", "🔒"),
    "vue": ("#41b883", "V"),
    "svg": ("#b8893a", "S"),
    "png": ("#b07db8", "▣"),
    "jpg": ("#b07db8", "▣"),
    "jpeg": ("#b07db8", "▣"),
    "gif": ("#b07db8", "▣"),
    "ico": ("#b07db8", "▣"),
    "pdf": ("#c44536", "▤"),
    "zip": ("#8a8a8a", "▦"),
    "gz": ("#8a8a8a", "▦"),
    "dockerfile": ("#2496ed", "D"),
}

_cache: dict[str, QIcon] = {}


def file_icon(filename: str) -> QIcon:
    name = filename.lower()
    if name in ("dockerfile",):
        ext = "dockerfile"
    elif name.startswith(".env"):
        ext = "env"
    else:
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
    color, label = EXT_COLORS.get(ext, ("#6e7681", "·"))
    key = f"file:{ext}"
    if key not in _cache:
        _cache[key] = _make_file_icon(color, label)
    return _cache[key]


def _make_file_icon(color: str, label: str) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # hoja de papel con esquina doblada
    path = QPainterPath()
    path.moveTo(7, 3)
    path.lineTo(20, 3)
    path.lineTo(26, 9)
    path.lineTo(26, 29)
    path.lineTo(7, 29)
    path.closeSubpath()
    p.setPen(QColor("#454545"))
    p.setBrush(QColor("#2b2b2b"))
    p.drawPath(path)
    p.setPen(QColor("#454545"))
    p.drawLine(20, 3, 20, 9)
    p.drawLine(20, 9, 26, 9)
    # etiqueta de tipo
    f = QFont("Helvetica Neue")
    f.setPixelSize(11)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(5, 12, 23, 16), Qt.AlignCenter, label)
    p.end()
    return QIcon(pm)


def folder_icon(open_: bool = False) -> QIcon:
    key = f"folder:{open_}"
    if key not in _cache:
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        body = QColor("#dcb67a")
        p.setPen(QColor("#b3935e"))
        p.setBrush(body)
        path = QPainterPath()
        path.moveTo(4, 8)
        path.lineTo(13, 8)
        path.lineTo(16, 11)
        path.lineTo(28, 11)
        path.lineTo(28, 26)
        path.lineTo(4, 26)
        path.closeSubpath()
        p.drawPath(path)
        if open_:
            p.setBrush(QColor("#e8c98f"))
            p.drawRect(QRectF(6, 14, 22, 12))
        p.end()
        _cache[key] = QIcon(pm)
    return _cache[key]


def server_icon() -> QIcon:
    """Icono de servidor/VPS para el botón de conexión remota."""
    if "server" not in _cache:
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#cfe3f2"))
        p.setBrush(QColor("#3a5a72"))
        for y in (6, 17):  # dos «racks» apilados
            p.drawRoundedRect(QRectF(5, y, 22, 9), 2, 2)
            p.setBrush(QColor("#5fd38d"))  # led de estado
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(8, y + 3, 3, 3))
            p.setPen(QColor("#cfe3f2"))
            p.setBrush(QColor("#3a5a72"))
        p.end()
        _cache["server"] = QIcon(pm)
    return _cache["server"]


def _drawn_app_pixmap(size: int) -> QPixmap:
    """Logo de respaldo dibujado por código (si falta logo.png)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#0e639c"))
    grad.setColorAt(1, QColor("#4fc1ff"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    radius = size * 0.22
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    f = QFont("Helvetica Neue")
    f.setPixelSize(int(size * 0.62))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, -size * 0.03, size, size), Qt.AlignCenter, "K")
    p.end()
    return pm


def app_pixmap(size: int = 256) -> QPixmap:
    """Logo de la app (logo.png) escalado a `size`; si no existe, el dibujado."""
    pm = QPixmap(LOGO_PATH)
    if pm.isNull():
        return _drawn_app_pixmap(size)
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def app_pixmap_round(size: int = 88) -> QPixmap:
    """Logo recortado en círculo, para mostrarlo sobre paneles oscuros sin que
    se vean las esquinas del PNG."""
    src = app_pixmap(size)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    p.setClipPath(path)
    x = (size - src.width()) // 2
    y = (size - src.height()) // 2
    p.drawPixmap(x, y, src)
    p.end()
    return out


def app_icon() -> QIcon:
    if "app" not in _cache:
        pm = QPixmap(LOGO_PATH)
        _cache["app"] = QIcon(pm) if not pm.isNull() else QIcon(_drawn_app_pixmap(256))
    return _cache["app"]
