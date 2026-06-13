# Kodea

Editor de código de escritorio (PySide6) estilo VS Code con **tu terminal del sistema embebida ejecutando Claude Code** y soporte de **conexiones SSH a VPS** para trabajar sobre código en producción.

## Características

- **Editor**: pestañas, números de línea, resaltado de sintaxis (Python, JS/TS, PHP, Go, Ruby, shell…), tema oscuro Dark+, autoindentado, guardado con ⌘S. Si Claude (o cualquier proceso) modifica un fichero abierto, la pestaña se recarga sola.
- **Follow mode**: mientras Claude trabaja, Kodea detecta el archivo que edita o crea, lo abre como pestaña activa, lo selecciona en el explorador y salta a la línea del cambio — sin robarte el foco del terminal. Se activa/desactiva en `Ver → Seguir archivos que Claude edita` (⌘⇧F) y funciona tanto en local como por SSH.
- **Terminal integrada al 100%**: el panel derecho es un terminal real (xterm.js + pty) con tu shell de login — tu zsh, tu prompt, tu PATH. Al abrir un proyecto, Kodea ejecuta `claude` dentro de esa shell y tienes la TUI completa de Claude Code: permisos interactivos, `/comandos`, `Shift+Tab`, colores… Al salir de claude sigues en tu terminal y puedes ejecutar lo que quieras.
- **SSH a VPS**: define conexiones (host, usuario, clave, directorio). El explorador y el editor funcionan por SFTP. Claude es siempre **tu Claude Code local** (tu sesión de este equipo): con una conexión activa recibe el comando ssh de esa conexión y opera sobre el servidor a través de él (leer, editar y ejecutar en remoto). No hace falta instalar `claude` en el VPS.

## Requisitos

- macOS / Linux con Python 3.10+
- [Claude Code CLI](https://claude.com/claude-code) instalado y autenticado en local (`claude` en el PATH).
- Para los VPS: acceso SSH por clave (recomendado) o contraseña (requiere `sshpass` en local: `brew install sshpass`). No hace falta nada de Claude en el servidor.

## Instalación y arranque

```bash
python3 -m venv .venv          # ya creado si usaste el setup inicial
.venv/bin/pip install -r requirements.txt
./run.sh                       # o: .venv/bin/python main.py
```

## Uso

1. Al arrancar ya tienes una terminal local viva en el panel derecho.
2. **Local**: `Archivo → Abrir carpeta…` (⌘O). Se abre una shell en esa carpeta y se ejecuta `claude` automáticamente.
3. **Remoto**: `Remoto → Conectar a VPS…` (⌘⇧P) → `Nueva…` → rellena host, usuario, clave y directorio del proyecto → `Conectar`. El árbol muestra el código del servidor y claude se lanza con `~/.kodea/claude-vps.sh` (script generado con el ssh de la conexión) para trabajar sobre el VPS.
4. El selector de permisos fija el modo con que se lanza claude («Lanzar claude» abre shell nueva con el modo elegido); dentro de la TUI puedes cambiarlo con `Shift+Tab` como siempre.
5. Si sales de claude (Ctrl+C / `exit`), te quedas en tu shell; con `exit` de la shell se reabre una limpia.

## Notas

- Las conexiones se guardan en `~/.kodea/connections.json` (permisos 0600). Evita guardar contraseñas; usa claves SSH o el agente.
- Los comandos ssh/scp de Claude hacia el VPS quedan pre-autorizados en la sesión (`--allowedTools`); el resto de permisos sigue el modo elegido.
- La navegación de ficheros del explorador usa SFTP (paramiko); claude usa el binario `ssh` del sistema (respeta `~/.ssh/config` y el agente).
- Log de diagnóstico en `~/.kodea/kodea.log`.
