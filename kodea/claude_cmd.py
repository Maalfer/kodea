"""Construcción del comando de Claude Code (local o apuntando a un VPS por ssh)."""
from __future__ import annotations

import os
import shlex
import shutil
from datetime import datetime

from .connections import Connection

LOG_FILE = os.path.expanduser("~/.kodea/kodea.log")


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
    for cand in (
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
        os.path.expanduser("~/.claude/local/claude"),
        os.path.expanduser("~/.local/bin/claude"),
    ):
        if os.path.exists(cand):
            return cand
    return "claude"


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
