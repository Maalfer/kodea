<p align="center">
  <img src="kodea/assets/logo.png" alt="Kodea" width="140">
</p>

<h1 align="center">Kodea</h1>

<p align="center">
  Editor de código de escritorio (PySide6) estilo VS Code con <b>tu terminal del sistema embebida ejecutando Claude Code</b> y soporte de <b>conexiones SSH a VPS</b> para trabajar sobre código en producción.
</p>

<p align="center">
  <a href="../../releases"><img alt="Releases" src="https://img.shields.io/github/v/release/Maalfer/kodea?display_name=tag"></a>
  <img alt="Plataformas" src="https://img.shields.io/badge/macOS%20·%20Windows%20·%20Linux-supported-2ea44f">
</p>

---

## ✨ Características

- **Editor**: pestañas, números de línea, resaltado de sintaxis (Python, JS/TS, PHP, Go, Ruby, shell…), tema oscuro Dark+, autoindentado, guardado con ⌘S. Si Claude (o cualquier proceso) modifica un fichero abierto, la pestaña se recarga sola.
- **Follow mode**: mientras Claude trabaja, Kodea detecta el archivo que edita o crea, lo abre como pestaña activa, lo selecciona en el explorador y salta a la línea del cambio — sin robarte el foco del terminal. Se activa/desactiva en `Ver → Seguir archivos que Claude edita` (⌘⇧F) y funciona tanto en local como por SSH.
- **Terminal integrada al 100%**: el panel derecho es un terminal real (xterm.js + pseudo-terminal) con tu shell de login — zsh/bash en macOS y Linux, PowerShell en Windows, con tu prompt y tu PATH. Al abrir un proyecto, Kodea ejecuta `claude` dentro de esa shell y tienes la TUI completa de Claude Code: permisos interactivos, `/comandos`, `Shift+Tab`, colores… Al salir de claude sigues en tu terminal y puedes ejecutar lo que quieras.
- **SSH a VPS**: define conexiones (host, usuario, clave, directorio). El explorador y el editor funcionan por SFTP. Claude es siempre **tu Claude Code local** (tu sesión de este equipo): con una conexión activa recibe el comando ssh de esa conexión y opera sobre el servidor a través de él (leer, editar y ejecutar en remoto). No hace falta instalar `claude` en el VPS.
- **Multiplataforma**: una sola base de código que abre la shell adecuada en macOS, Windows y Linux.
- **Barra de menús completa** (Archivo, Editar, Selección, Ver, Ir, Terminal, Remoto, Ayuda) con lo típico de un editor profesional: buscar/reemplazar (Ctrl+F / Ctrl+H), comentar línea (Ctrl+/), mover/duplicar/eliminar líneas, ir a línea (Ctrl+G), alternar explorador/terminal (Ctrl+B / Ctrl+J)… y **zoom del editor con Ctrl + / Ctrl - / Ctrl 0** (o Ctrl + rueda del ratón). Los atajos que coinciden con teclas de control del terminal (Ctrl+C, Ctrl+W…) solo actúan con el editor enfocado, así que tu terminal no se ve afectada.

## 📦 Instalación

Descarga el instalador de tu sistema desde la página de [**Releases**](../../releases):

| Sistema | Archivo | Instalación |
| --- | --- | --- |
| **Windows** | `Kodea-Setup-<versión>.exe` | Instalador con asistente (Inno Setup), accesos directos y desinstalador. |
| **macOS** | `Kodea-<versión>.dmg` | Arrastra `Kodea.app` a Aplicaciones. Al no estar firmado, la primera vez ábrelo con clic derecho → *Abrir*. |
| **Linux** | `kodea_<versión>_amd64.deb` | `sudo apt install ./kodea_<versión>_amd64.deb` |

### Linux: repositorio APT (recomendado)

Para instalar y recibir actualizaciones con `apt`:

```bash
echo "deb [trusted=yes] https://maalfer.github.io/kodea stable main" | sudo tee /etc/apt/sources.list.d/kodea.list
sudo apt update
sudo apt install kodea
```

> El repositorio APT se publica automáticamente en GitHub Pages en cada release.

## 🔧 Requisitos

- macOS, Linux o Windows.
- [**Claude Code CLI**](https://claude.com/claude-code) instalado y autenticado en local (`claude` en el PATH).
- Para los VPS: acceso SSH por clave (recomendado) o contraseña (requiere `sshpass` en local: `brew install sshpass`). No hace falta nada de Claude en el servidor.

## 🚀 Uso

1. Al arrancar ya tienes una terminal local viva en el panel derecho.
2. **Local**: `Archivo → Abrir carpeta…` (⌘O). Se abre una shell en esa carpeta y se ejecuta `claude` automáticamente.
3. **Remoto**: `Remoto → Conectar a VPS…` (⌘⇧P) → `Nueva…` → rellena host, usuario, clave y directorio del proyecto → `Conectar`. El árbol muestra el código del servidor y claude se lanza con un lanzador generado con el ssh de la conexión (`~/.kodea/claude-vps.sh` en macOS/Linux, `claude-vps.ps1` en Windows) para trabajar sobre el VPS.
4. El selector de permisos fija el modo con que se lanza claude («Lanzar claude» abre shell nueva con el modo elegido); dentro de la TUI puedes cambiarlo con `Shift+Tab` como siempre.
5. Si sales de claude (Ctrl+C / `exit`), te quedas en tu shell; con `exit` de la shell se reabre una limpia.

## 🧑‍💻 Ejecutar desde el código

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh                       # o: .venv/bin/python main.py
```

En Windows:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## 🏗️ Generar los instaladores

Los tres instaladores se compilan automáticamente en GitHub Actions
(`.github/workflows/build.yml`): en cada push se suben como *artifacts* y al
empujar un tag `vX.Y.Z` se publica una *Release* con ellos y se actualiza el
repositorio APT.

```bash
git tag v1.0.0 && git push origin v1.0.0   # dispara la Release + repo APT
```

Para compilar en local (necesitas `pyinstaller` y `pillow`):

```bash
python build/make_icons.py            # genera build/icon.ico|icns y los PNG desde logo.png
pyinstaller --noconfirm kodea.spec    # → dist/kodea/ (y dist/Kodea.app en mac)
# Windows: ISCC.exe /DAppVersion=1.0.0 installer\kodea.iss   → instalador .exe
# Linux:   VERSION=1.0.0 bash packaging/build_deb.sh         → dist/kodea_*.deb
# macOS:   hdiutil create -volname Kodea -srcfolder dist/Kodea.app -ov -format UDZO Kodea.dmg
```

> **Nota macOS/Windows:** los ejecutables van sin firmar. En macOS, la primera
> apertura requiere clic derecho → *Abrir*. Para firmar/notarizar habría que
> añadir certificados como *secrets* del repositorio.

## 📝 Notas

- Las conexiones se guardan en `~/.kodea/connections.json` (permisos 0600). Evita guardar contraseñas; usa claves SSH o el agente.
- Los comandos ssh/scp de Claude hacia el VPS quedan pre-autorizados en la sesión (`--allowedTools`); el resto de permisos sigue el modo elegido.
- La navegación de ficheros del explorador usa SFTP (paramiko); claude usa el binario `ssh` del sistema (respeta `~/.ssh/config` y el agente).
- Log de diagnóstico en `~/.kodea/kodea.log`.

## 🗂️ Estructura del proyecto

```
kodea/
  main_window.py   ventana, layout, follow mode, menús
  editor.py        editor de código (números de línea, sintaxis)
  terminal.py      panel de terminal (xterm.js + WebEngine)
  pty_backend.py   pseudo-terminal por SO (ConPTY en Windows, pty.fork en Unix)
  claude_cmd.py    construcción del comando de Claude (local y ssh)
  connections.py   conexiones SSH + diálogo
  fs.py            sistema de ficheros local / remoto (SFTP)
  file_tree.py     explorador de archivos
  icons.py         logo e iconos
  theme.py         tema oscuro (QSS)
  assets/          logo.png, term.html, xterm.js, iconos SVG
build/             generador de iconos para los instaladores
installer/         script de Inno Setup (Windows)
packaging/         scripts de .deb y del repositorio APT
.github/workflows/ CI: build de los 3 instaladores + repo APT
```
