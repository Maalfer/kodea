#!/usr/bin/env bash
# Construye/actualiza un repositorio APT estático (servible por GitHub Pages).
#
# Entrada:
#   incoming/*.deb   los .deb nuevos a publicar
#   apt-repo/        (opcional) repo existente — si se hace checkout de la rama
#                    gh-pages aquí, se conservan las versiones anteriores
# Salida:
#   apt-repo/        repo listo para publicar (pool + dists + index.html)
#
# Requiere: dpkg-dev (dpkg-scanpackages) y apt-utils (apt-ftparchive).
set -euo pipefail

REPO="apt-repo"
SUITE="stable"
COMP="main"
ARCH="amd64"
PAGES_URL="${PAGES_URL:-https://maalfer.github.io/kodea}"

mkdir -p "$REPO/pool/$COMP" "$REPO/dists/$SUITE/$COMP/binary-$ARCH"

# añade los .deb nuevos al pool (conserva los que ya hubiera)
if compgen -G "incoming/*.deb" > /dev/null; then
  cp -f incoming/*.deb "$REPO/pool/$COMP/"
else
  echo "AVISO: no hay .deb en incoming/ — solo se regenera el índice" >&2
fi

cd "$REPO"

# índice de paquetes (todas las versiones presentes en el pool)
dpkg-scanpackages --multiversion "pool/$COMP" > "dists/$SUITE/$COMP/binary-$ARCH/Packages"
gzip -kf "dists/$SUITE/$COMP/binary-$ARCH/Packages"

# fichero Release del suite (con sumas de comprobación)
apt-ftparchive \
  -o "APT::FTPArchive::Release::Origin=Kodea" \
  -o "APT::FTPArchive::Release::Label=Kodea" \
  -o "APT::FTPArchive::Release::Suite=$SUITE" \
  -o "APT::FTPArchive::Release::Codename=$SUITE" \
  -o "APT::FTPArchive::Release::Components=$COMP" \
  -o "APT::FTPArchive::Release::Architectures=$ARCH" \
  release "dists/$SUITE" > "dists/$SUITE/Release"

# página de ayuda en la raíz del repo
cat > index.html <<EOF
<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Repositorio APT de Kodea</title>
<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;background:#1e1e1e;color:#d4d4d4}
code,pre{background:#2d2d30;border-radius:6px}pre{padding:14px;overflow:auto}code{padding:2px 6px}a{color:#4fc1ff}</style></head>
<body>
<h1>Repositorio APT de Kodea</h1>
<p>Instala Kodea en Debian/Ubuntu y recibe actualizaciones con <code>apt</code>:</p>
<pre>echo "deb [trusted=yes] $PAGES_URL $SUITE $COMP" | sudo tee /etc/apt/sources.list.d/kodea.list
sudo apt update
sudo apt install kodea</pre>
<p>Para actualizar: <code>sudo apt update &amp;&amp; sudo apt install --only-upgrade kodea</code></p>
</body></html>
EOF

# evita que Pages procese el repo con Jekyll (oculta dists/ por el _)
touch .nojekyll

echo "Repositorio APT generado en $REPO/ (pool: $(ls pool/$COMP | wc -l) .deb)"
