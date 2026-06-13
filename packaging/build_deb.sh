#!/usr/bin/env bash
# Construye un paquete .deb a partir de la build onedir de PyInstaller.
#
# Espera:
#   - dist/kodea/        (carpeta generada por: pyinstaller kodea.spec)
#   - build/icon_256.png (generado por: python build/make_icons.py)
#
# Uso:  VERSION=1.2.3 packaging/build_deb.sh
# Salida: dist/kodea_<version>_amd64.deb
set -euo pipefail

VERSION="${VERSION:-0.0.0}"
ARCH="${ARCH:-amd64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="kodea"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [[ ! -d "$ROOT/dist/kodea" ]]; then
  echo "ERROR: no existe dist/kodea — ejecuta primero pyinstaller kodea.spec" >&2
  exit 1
fi

# --- layout del paquete -----------------------------------------------------
install -d "$STAGE/DEBIAN"
install -d "$STAGE/opt/kodea"
install -d "$STAGE/usr/bin"
install -d "$STAGE/usr/share/applications"
install -d "$STAGE/usr/share/icons/hicolor/256x256/apps"

cp -a "$ROOT/dist/kodea/." "$STAGE/opt/kodea/"

# lanzador en el PATH
cat > "$STAGE/usr/bin/kodea" <<'EOF'
#!/bin/sh
exec /opt/kodea/kodea "$@"
EOF
chmod 755 "$STAGE/usr/bin/kodea"

# icono y acceso de escritorio
if [[ -f "$ROOT/build/icon_256.png" ]]; then
  cp "$ROOT/build/icon_256.png" "$STAGE/usr/share/icons/hicolor/256x256/apps/kodea.png"
fi

cat > "$STAGE/usr/share/applications/kodea.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Kodea
Comment=Editor de código con Claude Code y SSH integrados
Exec=/opt/kodea/kodea %F
Icon=kodea
Terminal=false
Categories=Development;IDE;TextEditor;
StartupWMClass=Kodea
EOF

# --- metadatos del paquete --------------------------------------------------
SIZE_KB="$(du -sk "$STAGE/opt" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: devel
Priority: optional
Architecture: $ARCH
Maintainer: Kodea <maalfer59@gmail.com>
Installed-Size: $SIZE_KB
Depends: libnss3, libnspr4, libxcomposite1, libxdamage1, libxrandr2, libxtst6, libxkbcommon0, libgbm1, libasound2 | libasound2t64, libglib2.0-0, libgl1, libegl1, libpulse0, libxcb-cursor0, fonts-dejavu-core
Description: Editor de código con Claude Code y SSH integrados
 Kodea es un editor de escritorio (PySide6) estilo VS Code con un terminal
 real embebido ejecutando Claude Code y soporte de conexiones SSH a VPS para
 trabajar sobre código en producción.
EOF

# --- empaquetado ------------------------------------------------------------
OUT="$ROOT/dist/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
echo "Generado: $OUT"
