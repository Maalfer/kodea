"""Pseudo-terminal multiplataforma para el panel de terminal embebido.

Kodea abre una shell de login real dentro de un pseudo-terminal y la conecta a
xterm.js. La forma de crear ese pty depende del SO:

- **macOS / Linux**: ``pty.fork`` + un descriptor de fichero vigilado con
  ``QSocketNotifier`` (sin hilos: el bucle de eventos de Qt lee del fd).
- **Windows**: ConPTY a través de ``pywinpty``; como su lectura es bloqueante,
  un hilo lector (``QThread``) reenvía los datos al hilo de UI por señal.

`TerminalWidget` usa la interfaz común (`make_backend` → objeto con
``spawn/write/resize/terminate``) sin saber en qué SO corre.
"""
from __future__ import annotations

import os
import shutil
import sys

from PySide6.QtCore import QObject, QSocketNotifier, QThread, Signal

IS_WINDOWS = sys.platform.startswith("win")

if not IS_WINDOWS:
    import fcntl
    import pty
    import signal
    import struct
    import termios


def default_shell() -> list[str]:
    """argv de la shell de login del usuario para este SO."""
    if IS_WINDOWS:
        for cand in ("pwsh.exe", "powershell.exe"):
            exe = shutil.which(cand)
            if exe:
                return [exe, "-NoLogo"]
        return [os.environ.get("COMSPEC", "cmd.exe")]
    shell = os.environ.get("SHELL") or shutil.which("zsh") or shutil.which("bash") or "/bin/sh"
    return [shell, "-l"]


def submit_key() -> str:
    """Carácter que «pulsa Enter» al teclear un comando en la shell."""
    return "\r" if IS_WINDOWS else "\n"


# --------------------------------------------------------------------------- Unix


class _UnixPty(QObject):
    """pty.fork con el fd vigilado por el bucle de eventos de Qt."""

    def __init__(self, on_data, on_exit, parent=None):
        super().__init__(parent)
        self._on_data = on_data
        self._on_exit = on_exit
        self.pid: int | None = None
        self.fd: int | None = None
        self._notifier: QSocketNotifier | None = None

    @property
    def alive(self) -> bool:
        return self.pid is not None

    def spawn(self, argv, cwd, env, cols, rows):
        pid, fd = pty.fork()
        if pid == 0:  # hijo: solo chdir + exec, nada de Qt
            try:
                os.chdir(cwd)
            except OSError:
                pass
            try:
                os.execvpe(argv[0], argv, env)
            except OSError:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.resize(cols, rows)
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._read)

    def _read(self):
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._finish()
            return
        self._on_data(data)

    def _finish(self):
        code = -1
        if self.pid:
            try:
                _, status = os.waitpid(self.pid, os.WNOHANG)
                code = os.waitstatus_to_exitcode(status) if status else 0
            except ChildProcessError:
                pass
        self._drop_notifier()
        self._close_fd()
        self.pid = None
        self._on_exit(code)

    def write(self, data: str):
        if self.fd is not None:
            try:
                os.write(self.fd, data.encode("utf-8"))
            except OSError:
                pass

    def resize(self, cols, rows):
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                            struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass

    def terminate(self):
        # silencioso: desactivamos el notifier para no emitir on_exit
        self._drop_notifier()
        if self.pid:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGHUP)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                pass
            self.pid = None
        self._close_fd()

    def _drop_notifier(self):
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None

    def _close_fd(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


# ------------------------------------------------------------------------- Windows


class _WinReader(QThread):
    """Lee del ConPTY en un hilo y reenvía al hilo de UI por señal."""

    data = Signal(bytes)
    exited = Signal(int)

    def __init__(self, proc):
        super().__init__()
        self._proc = proc

    def run(self):
        proc = self._proc
        try:
            while True:
                try:
                    chunk = proc.read(65536)
                except EOFError:
                    break
                except OSError:
                    break
                if chunk:
                    self.data.emit(chunk.encode("utf-8", "replace"))
                elif not proc.isalive():
                    break
        finally:
            code = 0
            try:
                if proc.exitstatus is not None:
                    code = int(proc.exitstatus)
            except Exception:
                pass
            self.exited.emit(code)


class _WinPty(QObject):
    """ConPTY vía pywinpty."""

    def __init__(self, on_data, on_exit, parent=None):
        super().__init__(parent)
        self._on_data = on_data
        self._on_exit = on_exit
        self.proc = None
        self._reader: _WinReader | None = None

    @property
    def alive(self) -> bool:
        return self.proc is not None

    def spawn(self, argv, cwd, env, cols, rows):
        from winpty import PtyProcess

        self.proc = PtyProcess.spawn(
            argv, cwd=cwd, env=env, dimensions=(rows, cols))
        self._reader = _WinReader(self.proc)
        self._reader.data.connect(self._on_data)
        self._reader.exited.connect(self._on_exit)
        self._reader.start()

    def write(self, data: str):
        if self.proc is not None:
            try:
                self.proc.write(data)
            except (OSError, EOFError):
                pass

    def resize(self, cols, rows):
        if self.proc is not None:
            try:
                self.proc.setwinsize(rows, cols)
            except (OSError, ValueError):
                pass

    def terminate(self):
        # desconecta antes de matar para no propagar el on_exit del cierre
        if self._reader is not None:
            try:
                self._reader.data.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                self._reader.exited.disconnect()
            except (RuntimeError, TypeError):
                pass
        if self.proc is not None:
            try:
                self.proc.terminate(force=True)
            except Exception:
                pass
            self.proc = None
        if self._reader is not None:
            self._reader.wait(2000)
            self._reader = None


def make_backend(on_data, on_exit, parent=None):
    """Crea el backend de pty adecuado al SO.

    `on_data(bytes)` recibe la salida cruda del pty; `on_exit(int)` se llama
    cuando el proceso termina por sí mismo (no al llamar a `terminate`)."""
    cls = _WinPty if IS_WINDOWS else _UnixPty
    return cls(on_data, on_exit, parent)
