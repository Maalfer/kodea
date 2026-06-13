# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller compartido para Windows, macOS y Linux.

Genera una build *onedir* (carpeta `dist/kodea`) con el ejecutable `kodea` y
todas las dependencias, incluido el QtWebEngine que usa el terminal. Cada SO
empaqueta luego esa carpeta a su formato (instalador Inno Setup, .dmg, .deb).
"""
import sys

block_cipher = None

# assets web del terminal (term.html + xterm) → kodea/assets dentro del bundle
datas = [("kodea/assets", "kodea/assets")]

# icono específico del SO (generado por build/make_icons.py)
icon = None
if sys.platform.startswith("win"):
    icon = "build/icon.ico"
elif sys.platform == "darwin":
    icon = "build/icon.icns"

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["paramiko"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kodea",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # app GUI: sin consola en Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="kodea",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Kodea.app",
        icon=icon,
        bundle_identifier="com.kodea.app",
        info_plist={
            "CFBundleName": "Kodea",
            "CFBundleDisplayName": "Kodea",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
