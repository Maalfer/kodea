"""Terminal del sistema embebida (xterm.js + pseudo-terminal).

El panel es una terminal completa al 100%: tu shell de login (zsh/bash en
macOS y Linux, PowerShell en Windows, con tu prompt, tu PATH y tu
configuración) corriendo en un pseudo-terminal. Al abrir un proyecto o
conectar a un VPS, Kodea teclea y ejecuta el comando `claude` dentro de esa
shell; cuando claude termina (o pulsas Ctrl+C) sigues en tu terminal normal y
puedes ejecutar lo que quieras.

El pty concreto (ConPTY en Windows, ``pty.fork`` en Unix) lo resuelve
``kodea.pty_backend``; aquí solo orquestamos la vista web y el contexto.
"""
from __future__ import annotations

import base64
import os
import sys
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
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

from .claude_cmd import claude_command, format_local_command, log, write_remote_launcher
from .connections import Connection
from .pty_backend import default_shell, make_backend, submit_key


def _assets_dir() -> str:
    """Carpeta de assets web, también cuando la app va empaquetada (PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "kodea", "assets")  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(__file__), "assets")


ASSETS_DIR = _assets_dir()

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
    """Emulador de terminal (xterm.js) conectado a la shell del sistema."""

    process_finished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
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
        """Abre la shell de login del usuario en un pty. Si se indica
        `initial_cmd`, se teclea y ejecuta dentro de esa shell."""
        if not self._page_ready:
            self._pending_start = (cwd, initial_cmd)
            return
        self.stop_process()
        self.bridge.cleared.emit()

        argv = default_shell()
        log(f"terminal: shell {argv} (cwd={cwd}) cmd inicial: {initial_cmd or '-'}")

        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env.setdefault("LANG", "en_US.UTF-8")

        self._backend = make_backend(self._on_data, self._on_child_exit, self)
        self._started_at = time.time()
        try:
            self._backend.spawn(argv, cwd, env, self._cols, self._rows)
        except Exception as exc:  # pty/ConPTY no disponible o shell inválida
            log(f"terminal: no se pudo abrir la shell: {exc!r}")
            self._backend = None
            self.process_finished.emit(-1)
            return
        if initial_cmd:
            # deja que la shell pinte su prompt antes de teclear el comando
            QTimer.singleShot(700, lambda: self.write_pty(initial_cmd + submit_key()))

    def seconds_alive(self) -> float:
        return time.time() - self._started_at

    def stop_process(self):
        if self._backend is not None:
            self._backend.terminate()
            self._backend.deleteLater()
            self._backend = None

    # ------------------------------------------------ E/S del pty

    def _on_data(self, data: bytes):
        self.bridge.output.emit(base64.b64encode(data).decode("ascii"))

    def _on_child_exit(self, code: int):
        log(f"terminal: shell terminada (código {code})")
        if self._backend is not None:
            self._backend.deleteLater()
            self._backend = None
        self.process_finished.emit(code)

    def write_pty(self, data: str):
        if self._backend is not None:
            self._backend.write(data)

    def resize_pty(self, cols: int, rows: int):
        self._cols, self._rows = max(cols, 2), max(rows, 2)
        if self._backend is not None:
            self._backend.resize(self._cols, self._rows)


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
            return format_local_command(cmd), cwd
        # remoto: el system prompt es multilínea; se envuelve en un lanzador
        # (.sh en Unix, .ps1 en Windows) para teclear algo corto en la shell
        return write_remote_launcher(cmd, self.connection), cwd

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

    def send_to_claude(self, text: str, submit: bool = True):
        """Teclea `text` en la sesión de Claude del terminal y lo envía.
        El Enter se manda con un pequeño retardo para que la TUI registre
        primero todo el texto."""
        self.term.write_pty(text)
        self.term.setFocus()
        if submit:
            QTimer.singleShot(80, lambda: self.term.write_pty("\r"))

    def bridge_message(self, text: str):
        self.term.bridge.output.emit(base64.b64encode(text.encode()).decode("ascii"))

    def shutdown(self):
        self.term.stop_process()
