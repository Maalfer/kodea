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
    mtime: float = 0.0


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

    def scan_tree(self, root: str, skip, is_watchable) -> dict[str, float]:
        """Recorre el árbol bajo `root` y devuelve {ruta: mtime} de los
        archivos de texto. Pensado para ejecutarse en un hilo de trabajo
        (no toca la UI). `skip` es un set de nombres a ignorar y
        `is_watchable(name)` filtra por extensión."""
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
        with os.scandir(path) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                out.append(FSEntry(entry.name, entry.path, is_dir, mtime))
        return _sorted_entries(out)

    def read_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def write_text(self, path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def mtime(self, path: str) -> float:
        return os.path.getmtime(path)

    def scan_tree(self, root: str, skip, is_watchable) -> dict[str, float]:
        out: dict[str, float] = {}
        stack = [root]
        count = 0
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for entry in it:
                        if entry.name in skip:
                            continue
                        try:
                            if entry.is_dir():
                                stack.append(entry.path)
                            elif is_watchable(entry.name):
                                out[entry.path] = entry.stat().st_mtime
                                count += 1
                        except OSError:
                            continue
                        if count >= 8000:
                            return out
            except OSError:
                continue
        return out


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
        # canal SFTP independiente para el escaneo en segundo plano, de modo
        # que no colisione con el SFTP que usa la UI (paramiko permite varios
        # canales sobre el mismo transporte)
        self._scan_sftp = None

    def listdir(self, path: str) -> list[FSEntry]:
        out = []
        for attr in self.sftp.listdir_attr(path):
            full = path.rstrip("/") + "/" + attr.filename
            is_dir = stat.S_ISDIR(attr.st_mode)
            out.append(FSEntry(attr.filename, full, is_dir, attr.st_mtime or 0.0))
        return _sorted_entries(out)

    def read_text(self, path: str) -> str:
        with self.sftp.open(path, "r") as f:
            return f.read().decode("utf-8", errors="replace")

    def write_text(self, path: str, content: str) -> None:
        with self.sftp.open(path, "w") as f:
            f.write(content.encode("utf-8"))

    def mtime(self, path: str) -> float:
        return self.sftp.stat(path).st_mtime or 0.0

    def scan_tree(self, root: str, skip, is_watchable) -> dict[str, float]:
        if self._scan_sftp is None:
            self._scan_sftp = self.client.open_sftp()
        sftp = self._scan_sftp
        out: dict[str, float] = {}
        stack = [root]
        count = 0
        while stack:
            d = stack.pop()
            try:
                attrs = sftp.listdir_attr(d)
            except Exception:
                continue
            for a in attrs:
                if a.filename in skip:
                    continue
                full = d.rstrip("/") + "/" + a.filename
                if stat.S_ISDIR(a.st_mode):
                    stack.append(full)
                elif is_watchable(a.filename):
                    out[full] = a.st_mtime or 0.0
                    count += 1
                    if count >= 8000:
                        return out
        return out

    def home_dir(self) -> str:
        return self.sftp.normalize(".")

    def close(self):
        for ch in (getattr(self, "_scan_sftp", None), self.sftp):
            try:
                if ch is not None:
                    ch.close()
            except Exception:
                pass
        try:
            self.client.close()
        except Exception:
            pass
