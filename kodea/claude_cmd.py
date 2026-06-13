"""Construcción del comando de Claude Code (local o apuntando a un VPS por ssh)."""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from datetime import datetime

from .connections import Connection

IS_WINDOWS = sys.platform.startswith("win")
KODEA_DIR = os.path.expanduser("~/.kodea")
LOG_FILE = os.path.join(KODEA_DIR, "kodea.log")


def log(message: str):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def find_claude() -> str:
    """Localiza el binario `claude` aunque la app no herede el PATH del shell."""
    found = shutil.which("claude")
    if found:
        return found
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA", "")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(appdata, "npm", "claude.cmd"),
            os.path.join(appdata, "npm", "claude.exe"),
            os.path.join(local, "Programs", "claude", "claude.exe"),
            os.path.expanduser(r"~\.local\bin\claude.exe"),
        ]
    else:
        candidates = [
            "/opt/homebrew/bin/claude",
            "/usr/local/bin/claude",
            os.path.expanduser("~/.claude/local/claude"),
            os.path.expanduser("~/.local/bin/claude"),
        ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return "claude"


def _ps_quote(arg: str) -> str:
    """Cita un argumento para PowerShell (comillas dobles, escape con backtick)."""
    return '"' + arg.replace("`", "``").replace('"', '`"') + '"'


def format_local_command(cmd: list[str]) -> str:
    """Línea de comando lista para teclear en la shell local del SO.

    En Windows la shell es PowerShell, que necesita el operador de llamada `&`
    para ejecutar una ruta entre comillas; en Unix basta con shlex.join."""
    if IS_WINDOWS:
        return "& " + " ".join(_ps_quote(c) for c in cmd)
    return shlex.join(cmd)


def _powershell_launcher(cmd: list[str]) -> str:
    """Script .ps1 que ejecuta `cmd`. Los argumentos multilínea (el system
    prompt) se vuelcan como here-string literal para no romper el quoting."""
    exe, args = cmd[0], cmd[1:]
    lines = ["# Generado por Kodea: claude apuntando al VPS"]
    parts = []
    for i, arg in enumerate(args):
        if "\n" in arg:
            var = f"$arg{i}"
            lines.append(f"{var} = @'\n{arg}\n'@")
            parts.append(var)
        else:
            parts.append("'" + arg.replace("'", "''") + "'")
    lines.append("& '" + exe.replace("'", "''") + "' " + " ".join(parts))
    return "\n".join(lines) + "\n"


def write_remote_launcher(cmd: list[str], conn: Connection) -> str:
    """Escribe un lanzador para el `cmd` de claude→ssh y devuelve lo que hay
    que teclear en la shell para ejecutarlo. Multiplataforma."""
    os.makedirs(KODEA_DIR, exist_ok=True)
    if IS_WINDOWS:
        path = os.path.join(KODEA_DIR, "claude-vps.ps1")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_powershell_launcher(cmd))
        return f'powershell -ExecutionPolicy Bypass -File {_ps_quote(path)}'
    path = os.path.join(KODEA_DIR, "claude-vps.sh")
    with open(path, "w") as f:
        f.write("#!/bin/sh\n# Generado por Kodea: claude apuntando a "
                f"{conn.display}\nexec {shlex.join(cmd)}\n")
    os.chmod(path, 0o700)
    return path


def build_ssh_command(conn: Connection) -> str:
    """Comando ssh (como cadena) que Claude usará para operar en el VPS."""
    parts = ["ssh"] + conn.ssh_args()
    if conn.password and not conn.key_path and shutil.which("sshpass"):
        parts = ["sshpass", "-p", conn.password] + parts
    return " ".join(shlex.quote(p) for p in parts)


def remote_system_prompt(ssh_cmd: str, workdir: str, conn: Connection) -> str:
    return (
        f"Trabajas sobre un servidor remoto ({conn.display}) accesible por SSH, "
        f"NO sobre la máquina local.\n"
        f"Comando de conexión: {ssh_cmd}\n"
        f"Directorio del proyecto en el servidor: {workdir}\n"
        f"Reglas:\n"
        f"- Todo el código del proyecto vive en el servidor. Para leer, buscar o "
        f"ejecutar usa Bash con ese comando, p. ej.: {ssh_cmd} 'cd {workdir} && cat app.py'.\n"
        f"- Para editar ficheros remotos usa ssh con heredoc, sed/python remotos, "
        f"o scp desde un fichero temporal local.\n"
        f"- No uses las herramientas Read/Edit/Write sobre rutas locales para ficheros "
        f"del proyecto: no existen en local.\n"
        f"- Antes de sobrescribir un fichero remoto, léelo primero."
    )


def claude_command(workdir: str, permission_mode: str,
                   connection: Connection | None = None) -> tuple[list[str], str]:
    """Devuelve (comando claude interactivo, cwd local) para el terminal."""
    cmd = [find_claude(), "--permission-mode", permission_mode]
    if connection is None:
        return cmd, workdir
    ssh_cmd = build_ssh_command(connection)
    cmd += [
        "--append-system-prompt", remote_system_prompt(ssh_cmd, workdir, connection),
        "--allowedTools", "Bash(ssh:*),Bash(scp:*),Bash(sshpass:*)",
    ]
    # cwd local neutro; el trabajo real va por ssh al VPS
    return cmd, os.path.expanduser("~")
