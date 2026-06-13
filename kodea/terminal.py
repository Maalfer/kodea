"""Terminal del sistema embebida (xterm.js + pty).

El panel es una terminal completa al 100%: tu shell de login (zsh con tu
prompt, tu PATH y tu configuración) corriendo en un pseudo-terminal. Al abrir
un proyecto o conectar a un VPS, Kodea teclea y ejecuta el comando `claude`
dentro de esa shell; cuando claude termina (o pulsas Ctrl+C) sigues en tu
terminal normal y puedes ejecutar lo que quieras.
"""
from __future__ import annotations

import base64
import fcntl
import os
import pty
import shlex
import signal
import struct
import termios
import time

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .claude_cmd import claude_command, log
from .connections import Connection

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
SCRIPT_PATH = os.path.expanduser("~/.kodea/claude-vps.sh")

PERMISSION_MODES = [
    ("Aceptar ediciones", "acceptEdits"),
    ("Preguntar (default)", "default"),
    ("Solo planificar", "plan"),
    ("Sin permisos (⚠ peligroso)", "bypassPermissions"),
]


class TermBridge(QObject):
    """Puente Qt ↔ JS (xterm.js)."""

    output = Signal(str)   # bytes del pty → terminal (base64)
    cleared = Signal()     # resetea la pantalla del terminal

    def __init__(self, terminal: "TerminalWidget"):
        super().__init__(terminal)
        self.terminal = terminal

    @Slot(str)
    def send_input(self, data: str):
        self.terminal.write_pty(data)

    @Slot(int, int)
    def resized(self, cols: int, rows: int):
        self.terminal.resize_pty(cols, rows)


class TerminalWidget(QWebEngineView):
    """Emulador de terminal (xterm.js) conectado a un pty con tu shell."""

    process_finished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pid: int | None = None
        self.fd: int | None = None
        self._notifier: QSocketNotifier | None = None
        self._cols, self._rows = 80, 24
        self._page_ready = False
        self._pending_start: tuple | None = None
        self._started_at = 0.0

        self.bridge = TermBridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.page().setBackgroundColor("#1e1e1e")
        self.loadFinished.connect(self._on_page_ready)
        self.load(QUrl.fromLocalFile(os.path.join(ASSETS_DIR, "term.html")))

    # ------------------------------------------------ ciclo de vida

    def _on_page_ready(self, ok: bool):
        self._page_ready = ok
        if ok and self._pending_start:
            args = self._pending_start
            self._pending_start = None
            self.start_shell(*args)

    def start_shell(self, cwd: str, initial_cmd: str | None = None):
        """Abre el shell de login del usuario en un pty. Si se indica
        `initial_cmd`, se teclea y ejecuta dentro de esa shell."""
        if not self._page_ready:
            self._pending_start = (cwd, initial_cmd)
            return
        self.stop_process()
        self.bridge.cleared.emit()

        shell = os.environ.get("SHELL", "/bin/zsh")
        argv = [shell, "-l"]
        log(f"terminal: shell {argv} (cwd={cwd}) cmd inicial: {initial_cmd or '-'}")

        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env.setdefault("LANG", "en_US.UTF-8")

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
        self._started_at = time.time()
        self.resize_pty(self._cols, self._rows)
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._read_pty)
        if initial_cmd:
            # deja que el shell pinte su prompt antes de teclear el comando
            QTimer.singleShot(700, lambda: self.write_pty(initial_cmd + "\n"))

    def seconds_alive(self) -> float:
        return time.time() - self._started_at

    def stop_process(self):
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
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
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    # ------------------------------------------------ E/S del pty

    def _read_pty(self):
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._on_child_exit()
            return
        self.bridge.output.emit(base64.b64encode(data).decode("ascii"))

    def _on_child_exit(self):
        code = -1
        if self.pid:
            try:
                _, status = os.waitpid(self.pid, os.WNOHANG)
                code = os.waitstatus_to_exitcode(status) if status else 0
            except ChildProcessError:
                pass
        log(f"terminal: shell terminada (código {code})")
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.pid = self.fd = None
        self.process_finished.emit(code)

    def write_pty(self, data: str):
        if self.fd is not None:
            try:
                os.write(self.fd, data.encode("utf-8"))
            except OSError:
                pass

    def resize_pty(self, cols: int, rows: int):
        self._cols, self._rows = max(cols, 2), max(rows, 2)
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                            struct.pack("HHHH", self._rows, self._cols, 0, 0))
            except OSError:
                pass


class ClaudeTerminalPanel(QWidget):
    """Panel lateral: tu terminal del sistema, con claude lanzado dentro."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.workdir = ""
        self.connection: Connection | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("TERMINAL · CLAUDE CODE")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.context_label = QLabel("Terminal local — abre una carpeta o conéctate a un VPS")
        self.context_label.setObjectName("contextLabel")
        self.context_label.setWordWrap(True)
        layout.addWidget(self.context_label)

        self.term = TerminalWidget()
        self.term.process_finished.connect(self._on_finished)
        layout.addWidget(self.term, 1)

        bottom = QWidget()
        bottom.setObjectName("panelBar")
        row = QHBoxLayout(bottom)
        row.setContentsMargins(8, 7, 8, 8)
        self.mode_combo = QComboBox()
        for label, value in PERMISSION_MODES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.setToolTip(
            "Modo de permisos de claude. Al cambiarlo se cierra la sesión actual "
            "y se relanza claude con ese modo.")
        # cambiar el modo relanza claude con esa configuración (se conecta
        # después de poblar el combo para que la carga inicial no lo dispare)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        row.addWidget(self.mode_combo, 1)
        self.claude_btn = QPushButton("Lanzar claude")
        self.claude_btn.setToolTip("Abre una shell nueva y ejecuta claude en el contexto actual")
        self.claude_btn.clicked.connect(self.restart)
        row.addWidget(self.claude_btn)
        layout.addWidget(bottom)

        # terminal disponible desde el arranque, sin necesidad de proyecto
        self.term.start_shell(os.path.expanduser("~"))

    # ------------------------------------------------ contexto

    def set_context(self, workdir: str, connection: Connection | None):
        self.workdir = workdir
        self.connection = connection
        where = (f"🌐 {connection.display} (claude local → ssh)"
                 if connection else "💻 Local")
        self.context_label.setText(f"{where} — {workdir}")
        self.restart()

    def _claude_invocation(self) -> tuple[str, str]:
        """(línea de comando a teclear en la shell, cwd de la shell)."""
        cmd, cwd = claude_command(self.workdir, self.mode_combo.currentData(),
                                  self.connection)
        if self.connection is None:
            return shlex.join(cmd), cwd
        # remoto: el system prompt es multilínea; se envuelve en un script
        # para teclear algo corto y legible en la shell
        os.makedirs(os.path.dirname(SCRIPT_PATH), exist_ok=True)
        with open(SCRIPT_PATH, "w") as f:
            f.write("#!/bin/sh\n# Generado por Kodea: claude apuntando a "
                    f"{self.connection.display}\nexec {shlex.join(cmd)}\n")
        os.chmod(SCRIPT_PATH, 0o700)
        return SCRIPT_PATH, cwd

    def _on_mode_changed(self, _index: int):
        """Al elegir otro modo de permisos, cierra la sesión de claude actual
        y la relanza con ese modo. Solo si hay un proyecto/VPS abierto (es
        cuando claude está corriendo); si no, el modo se aplicará al lanzarlo."""
        if self.workdir:
            self.restart()

    def restart(self):
        """Shell nueva en el contexto actual con claude ejecutándose dentro."""
        if not self.workdir:
            self.term.start_shell(os.path.expanduser("~"))
            self.term.setFocus()
            return
        invocation, cwd = self._claude_invocation()
        self.term.start_shell(cwd, invocation)
        self.term.setFocus()

    def _on_finished(self, code: int):
        # la shell se cerró (exit/crash): reabre una limpia para que el panel
        # siga siendo una terminal viva, salvo que muera nada más arrancar
        if self.term.seconds_alive() < 3:
            self.bridge_message("\r\n\x1b[91m[no se pudo abrir el shell — revisa "
                                "~/.kodea/kodea.log]\x1b[0m\r\n")
            return
        cwd = self.workdir if (self.workdir and not self.connection) else os.path.expanduser("~")
        self.term.start_shell(cwd)

    def bridge_message(self, text: str):
        self.term.bridge.output.emit(base64.b64encode(text.encode()).decode("ascii"))

    def shutdown(self):
        self.term.stop_process()
