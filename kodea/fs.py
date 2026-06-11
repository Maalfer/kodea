"""Abstracción de sistema de ficheros: local o remoto por SFTP.

El explorador y el editor trabajan contra esta interfaz, de modo que abrir
una carpeta local o una carpeta en un VPS es indistinto para la UI.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass


@dataclass
class FSEntry:
    name: str
    path: str
    is_dir: bool


class FileSystem:
    """Interfaz común. Las rutas son siempre absolutas estilo POSIX."""

    #: etiqueta para mostrar en la UI ("Local" o "user@host")
    label = "Local"
    is_remote = False

    def listdir(self, path: str) -> list[FSEntry]:
        raise NotImplementedError

    def read_text(self, path: str) -> str:
        raise NotImplementedError

    def write_text(self, path: str, content: str) -> None:
        raise NotImplementedError

    def mtime(self, path: str) -> float:
        raise NotImplementedError

    def close(self):
        pass


def _sorted_entries(entries: list[FSEntry]) -> list[FSEntry]:
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))


class LocalFS(FileSystem):
    label = "Local"
    is_remote = False

    def listdir(self, path: str) -> list[FSEntry]:
        out = []
        for name in os.listdir(path):
            full = os.path.join(path, name)
            try:
                is_dir = os.path.isdir(full)
            except OSError:
                continue
            out.append(FSEntry(name, full, is_dir))
        return _sorted_entries(out)

    def read_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def write_text(self, path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def mtime(self, path: str) -> float:
        return os.path.getmtime(path)


class RemoteFS(FileSystem):
    """Sistema de ficheros sobre SFTP (paramiko)."""

    is_remote = True

    def __init__(self, connection):
        """`connection` es un kodea.connections.Connection ya configurado."""
        import paramiko

        self.connection = connection
        self.label = f"{connection.user}@{connection.host}"
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(
            hostname=connection.host,
            port=connection.port,
            username=connection.user,
            timeout=15,
        )
        if connection.key_path:
            kwargs["key_filename"] = os.path.expanduser(connection.key_path)
        if connection.password:
            kwargs["password"] = connection.password
        # permite también agente ssh y claves por defecto (~/.ssh/id_*)
        kwargs["allow_agent"] = True
        kwargs["look_for_keys"] = True
        self.client.connect(**kwargs)
        self.sftp = self.client.open_sftp()

    def listdir(self, path: str) -> list[FSEntry]:
        out = []
        for attr in self.sftp.listdir_attr(path):
            full = path.rstrip("/") + "/" + attr.filename
            is_dir = stat.S_ISDIR(attr.st_mode)
            out.append(FSEntry(attr.filename, full, is_dir))
        return _sorted_entries(out)

    def read_text(self, path: str) -> str:
        with self.sftp.open(path, "r") as f:
            return f.read().decode("utf-8", errors="replace")

    def write_text(self, path: str, content: str) -> None:
        with self.sftp.open(path, "w") as f:
            f.write(content.encode("utf-8"))

    def mtime(self, path: str) -> float:
        return self.sftp.stat(path).st_mtime or 0.0

    def home_dir(self) -> str:
        return self.sftp.normalize(".")

    def close(self):
        try:
            self.sftp.close()
            self.client.close()
        except Exception:
            pass
