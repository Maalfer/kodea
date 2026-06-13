"""Ventana principal: explorador + editor con pestañas + chat de Claude Code."""
from __future__ import annotations

import difflib
import os
import re

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QKeySequence,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, icons
from .terminal import ClaudeTerminalPanel
from .connections import Connection, ConnectionDialog, ConnectionStore
from .editor import AI_ACTIONS, CodeEditor, lang_for_path
from .file_tree import FileTree, SKIP
from .fs import FileSystem, LocalFS, RemoteFS

# Extensiones que no tiene sentido seguir/abrir como texto.
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".class", ".jar", ".o", ".a",
    ".bin", ".exe", ".wasm", ".db", ".sqlite", ".sqlite3", ".lock",
}


def _is_watchable(name: str) -> bool:
    """¿Es un archivo de texto/código que tiene sentido seguir y abrir?"""
    return os.path.splitext(name)[1].lower() not in _BINARY_EXT


def _first_diff_line(old: str, new: str) -> int:
    """Primera línea (0-based) que difiere entre dos textos."""
    a, b = old.split("\n"), new.split("\n")
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return max(0, min(len(a), len(b)) - 1)


def diff_regions(old: str, new: str):
    """Compara `old` vs `new` por líneas y devuelve:
    - added:   lista de rangos [j1, j2) de líneas NUEVAS (resaltar en verde)
    - deleted: lista de índices (línea nueva) donde se borraron líneas (marca roja)
    - hunks:   nº de bloques de cambio."""
    a, b = old.split("\n"), new.split("\n")
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    added, deleted, hunks = [], [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        hunks += 1
        if tag in ("replace", "insert"):
            added.append((j1, j2))
        if tag in ("replace", "delete"):
            deleted.append(j1)
    return added, deleted, hunks


# --------------------------------------------------------------- tareas en 2º plano
# Toda la E/S que puede bloquear (conectar por SSH, recorrer el árbol remoto por
# SFTP) se ejecuta en el QThreadPool para que la ventana no se congele.

class _ConnectSignals(QObject):
    ok = Signal(object, str)   # (FileSystem, workdir)
    err = Signal(str)


class _ConnectTask(QRunnable):
    """Abre la conexión SSH/SFTP fuera del hilo de la GUI."""

    def __init__(self, conn: Connection):
        super().__init__()
        self.setAutoDelete(False)  # el ciclo de vida lo gestiona MainWindow._tasks
        self.conn = conn
        self.signals = _ConnectSignals()

    def run(self):
        try:
            fs = RemoteFS(self.conn)
            workdir = self.conn.remote_dir or fs.home_dir()
        except Exception as e:  # noqa: BLE001 — se reporta tal cual en la UI
            self.signals.err.emit(str(e))
            return
        self.signals.ok.emit(fs, workdir)


class _ScanSignals(QObject):
    done = Signal(object, dict)  # (fs que se escaneó, {ruta: mtime})
    failed = Signal()


class _ScanTask(QRunnable):
    """Recorre el árbol del proyecto (local o remoto) fuera del hilo de la GUI."""

    def __init__(self, fs: FileSystem, root: str):
        super().__init__()
        self.setAutoDelete(False)  # el ciclo de vida lo gestiona MainWindow._tasks
        self.fs = fs
        self.root = root
        self.signals = _ScanSignals()

    def run(self):
        try:
            snapshot = self.fs.scan_tree(self.root, SKIP, _is_watchable)
        except Exception:  # noqa: BLE001 — un fallo de red no debe tumbar nada
            self.signals.failed.emit()
            return
        self.signals.done.emit(self.fs, snapshot)


class WelcomeWidget(QWidget):
    """Pantalla de bienvenida con accesos rápidos."""

    def __init__(self, open_folder_cb, connect_cb, parent=None):
        super().__init__(parent)
        # El fondo se pinta solo en este widget (no en las QLabel hijas, que
        # de lo contrario aparecerían como bandas más claras).
        self.setObjectName("welcome")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#welcome { background: #1e1e1e; }")
        outer = QVBoxLayout(self)
        outer.addStretch(2)

        logo = QLabel()
        logo.setPixmap(icons.app_pixmap_round(96))
        logo.setAlignment(Qt.AlignCenter)
        outer.addWidget(logo)

        title = QLabel("Kodea")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 38px; font-weight: 600; color: #e8e8e8; padding-top: 8px;")
        outer.addWidget(title)

        sub = QLabel("Editor con Claude Code y acceso SSH a tus servidores")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("font-size: 14px; color: #8a8a8a; padding-bottom: 18px;")
        outer.addWidget(sub)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        b_open = QPushButton("  Abrir carpeta")
        b_open.setIcon(icons.folder_icon())
        b_open.setMinimumWidth(170)
        b_open.clicked.connect(open_folder_cb)
        btn_row.addWidget(b_open)
        btn_row.addSpacing(12)
        b_conn = QPushButton("  Conectar a VPS")
        b_conn.setIcon(icons.server_icon())
        b_conn.setMinimumWidth(170)
        b_conn.clicked.connect(connect_cb)
        btn_row.addWidget(b_conn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        keys = QLabel(
            "⌘O  Abrir carpeta     ·     "
            "⌘⇧P  Conectar a VPS     ·     "
            "⌘S  Guardar     ·     "
            "⌘R  Recargar explorador"
        )
        keys.setAlignment(Qt.AlignCenter)
        keys.setWordWrap(True)
        keys.setStyleSheet("font-size: 12px; color: #6e7681; padding-top: 26px;")
        outer.addWidget(keys)
        outer.addStretch(3)


class FindBar(QWidget):
    """Barra de búsqueda y reemplazo sobre el editor activo (estilo VS Code)."""

    def __init__(self, editor_getter, parent=None):
        super().__init__(parent)
        self.get_editor = editor_getter
        self.setObjectName("findBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar")
        self.search.returnPressed.connect(self.find_next)
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search, 1)

        self.case = QCheckBox("Aa")
        self.case.setToolTip("Distinguir mayúsculas/minúsculas")
        lay.addWidget(self.case)

        for text, tip, cb in (
            ("‹", "Anterior (⇧Intro)", self.find_prev),
            ("›", "Siguiente (Intro)", self.find_next),
        ):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(cb)
            lay.addWidget(b)

        self.replace = QLineEdit()
        self.replace.setPlaceholderText("Reemplazar")
        self.replace.returnPressed.connect(self.replace_one)
        lay.addWidget(self.replace, 1)

        self.btn_rep = QToolButton()
        self.btn_rep.setText("Reemplazar")
        self.btn_rep.clicked.connect(self.replace_one)
        lay.addWidget(self.btn_rep)
        self.btn_rep_all = QToolButton()
        self.btn_rep_all.setText("Todo")
        self.btn_rep_all.clicked.connect(self.replace_all)
        lay.addWidget(self.btn_rep_all)

        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Cerrar (Esc)")
        close.clicked.connect(self.hide_bar)
        lay.addWidget(close)

        self.hide()

    def show_for(self, replace: bool):
        ed = self.get_editor()
        if ed is not None:
            sel = ed.textCursor().selectedText()
            if sel and " " not in sel:
                self.search.setText(sel)
        for w in (self.replace, self.btn_rep, self.btn_rep_all):
            w.setVisible(replace)
        self.show()
        self.search.setFocus()
        self.search.selectAll()

    def hide_bar(self):
        self.hide()
        ed = self.get_editor()
        if ed is not None:
            ed.setFocus()

    def _flags(self, backward: bool = False):
        flags = QTextDocument.FindFlags()
        if self.case.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if backward:
            flags |= QTextDocument.FindBackward
        return flags

    def _find(self, backward: bool = False):
        ed = self.get_editor()
        text = self.search.text()
        if ed is None or not text:
            return
        if not ed.find(text, self._flags(backward)):
            # no hay más: vuelve al principio/final y reintenta (búsqueda cíclica)
            cur = ed.textCursor()
            cur.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            ed.setTextCursor(cur)
            ed.find(text, self._flags(backward))

    def find_next(self):
        self._find(backward=False)

    def find_prev(self):
        self._find(backward=True)

    def replace_one(self):
        ed = self.get_editor()
        if ed is None or not self.search.text():
            return
        cur = ed.textCursor()
        sel = cur.selectedText()
        target = self.search.text()
        match = sel == target if self.case.isChecked() else sel.lower() == target.lower()
        if sel and match:
            cur.insertText(self.replace.text())
        self.find_next()

    def replace_all(self):
        ed = self.get_editor()
        text = self.search.text()
        if ed is None or not text:
            return
        flags = 0 if self.case.isChecked() else re.IGNORECASE
        content = ed.toPlainText()
        new, n = re.subn(re.escape(text), lambda _m: self.replace.text(), content, flags=flags)
        if n:
            cur = ed.textCursor()
            cur.beginEditBlock()
            cur.select(QTextCursor.Document)
            cur.insertText(new)
            cur.endEditBlock()
        if self.window():
            self.window().statusBar().showMessage(f"{n} reemplazo(s)", 3000)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide_bar()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kodea")
        self.setWindowIcon(icons.app_icon())
        self.resize(1480, 920)

        self.store = ConnectionStore()
        self.fs: FileSystem = LocalFS()
        self.connection: Connection | None = None
        self.workdir = ""

        # «follow mode»: seguir los archivos que Claude edita
        self.follow_enabled = True
        self._fs_snapshot: dict[str, float] = {}
        self._primed = False
        self._scanning = False  # hay un escaneo en curso (evita solaparlos)
        # referencias vivas a las tareas en segundo plano: sin esto Python
        # recolecta el QRunnable y su objeto de señales, y emitir desde el
        # hilo de trabajo accede a un QObject destruido (crash)
        self._tasks: set = set()

        # tamaño de fuente del editor (zoom); se aplica a todas las pestañas
        from .editor import DEFAULT_FONT_SIZE
        self.editor_font_pt = DEFAULT_FONT_SIZE

        # --- layout: [explorador | editor | chat] ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)

        self.sidebar = QWidget()
        self.sidebar.setMinimumWidth(180)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        explorer_title = QLabel("EXPLORADOR")
        explorer_title.setObjectName("panelTitle")
        sl.addWidget(explorer_title)
        self.context_label = QLabel("Abre una carpeta o conéctate a un VPS")
        self.context_label.setObjectName("contextLabel")
        self.context_label.setWordWrap(True)
        sl.addWidget(self.context_label)
        self.tree = FileTree()
        self.tree.file_activated.connect(self.open_file)
        sl.addWidget(self.tree, 1)
        self.splitter.addWidget(self.sidebar)

        # columna del editor: barra de búsqueda (oculta) + pestañas
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda _: self._update_cursor_status())
        welcome = WelcomeWidget(self.open_local_folder, self.show_connections)
        self.tabs.addTab(welcome, "Bienvenida")

        self.editor_col = QWidget()
        self.editor_col.setMinimumWidth(320)
        ec = QVBoxLayout(self.editor_col)
        ec.setContentsMargins(0, 0, 0, 0)
        ec.setSpacing(0)
        self.find_bar = FindBar(self._current_editor)
        ec.addWidget(self.find_bar)
        ec.addWidget(self.tabs, 1)
        self.splitter.addWidget(self.editor_col)

        self.chat = ClaudeTerminalPanel()
        self.chat.setMinimumWidth(360)
        self.splitter.addWidget(self.chat)

        self.splitter.setSizes([240, 700, 540])
        self.splitter.setStretchFactor(0, 0)  # explorador: ancho fijo
        self.splitter.setStretchFactor(1, 1)  # editor: absorbe el espacio extra
        self.splitter.setStretchFactor(2, 0)  # terminal: ancho fijo

        # barra de estado: conexión a la izquierda, cursor/lenguaje a la derecha
        self.conn_status = QLabel("⬤ Local")
        self.statusBar().addWidget(self.conn_status)
        self.lang_status = QLabel("")
        self.statusBar().addPermanentWidget(self.lang_status)
        self.cursor_status = QLabel("")
        self.statusBar().addPermanentWidget(self.cursor_status)
        self._build_menu()

        # vigila el proyecto: recarga las pestañas abiertas que Claude modifique
        # y revela el archivo recién editado (follow mode)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(1500)
        self.watch_timer.timeout.connect(self._scan_changes)
        self.watch_timer.start()

    # ------------------------------------------------------------- menú

    def _act(self, menu, text, slot, shortcut=None):
        """Acción a nivel de ventana (atajo global mientras Kodea está activa)."""
        a = QAction(text, self)
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, (list, tuple)) else [shortcut])])
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _act_ed(self, menu, text, slot, shortcut=None):
        """Acción acotada al editor: el atajo solo actúa cuando el foco está en
        el editor, para no pisar las teclas de control del terminal."""
        a = QAction(text, self.editor_col)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a.triggered.connect(slot)
        self.editor_col.addAction(a)
        menu.addAction(a)
        return a

    def _build_menu(self):
        bar = self.menuBar()

        # --- Archivo ---
        m_file = bar.addMenu("&Archivo")
        self._act(m_file, "Abrir carpeta…", self.open_local_folder, "Ctrl+O")
        self._act(m_file, "Abrir archivo…", self.open_file_dialog, "Ctrl+Shift+O")
        self._act(m_file, "Recargar explorador", self.tree.refresh, "Ctrl+R")
        m_file.addSeparator()
        self._act(m_file, "Guardar", self.save_current, "Ctrl+S")
        self._act_ed(m_file, "Guardar como…", self.save_as, "Ctrl+Shift+S")
        self._act(m_file, "Guardar todo", self.save_all, "Ctrl+Alt+S")
        m_file.addSeparator()
        self._act_ed(m_file, "Cerrar pestaña", self.close_current_tab, "Ctrl+W")
        self._act(m_file, "Cerrar todas las pestañas", self.close_all_tabs)
        m_file.addSeparator()
        self._act(m_file, "Salir", self.close, "Ctrl+Q")

        # --- Editar ---
        m_edit = bar.addMenu("&Editar")
        self._act_ed(m_edit, "Deshacer", lambda: self._ed_call("undo"), "Ctrl+Z")
        self._act_ed(m_edit, "Rehacer", lambda: self._ed_call("redo"), "Ctrl+Shift+Z")
        m_edit.addSeparator()
        self._act_ed(m_edit, "Cortar", lambda: self._ed_call("cut"), "Ctrl+X")
        self._act_ed(m_edit, "Copiar", lambda: self._ed_call("copy"), "Ctrl+C")
        self._act_ed(m_edit, "Pegar", lambda: self._ed_call("paste"), "Ctrl+V")
        m_edit.addSeparator()
        self._act_ed(m_edit, "Buscar", lambda: self.find_bar.show_for(False), "Ctrl+F")
        self._act_ed(m_edit, "Buscar siguiente", self.find_bar.find_next, "F3")
        self._act_ed(m_edit, "Reemplazar", lambda: self.find_bar.show_for(True), "Ctrl+H")
        m_edit.addSeparator()
        self._act_ed(m_edit, "Comentar/descomentar línea", lambda: self._ed_call("toggle_comment"), "Ctrl+/")

        # --- Selección ---
        m_sel = bar.addMenu("&Selección")
        self._act_ed(m_sel, "Seleccionar todo", lambda: self._ed_call("selectAll"), "Ctrl+A")
        m_sel.addSeparator()
        self._act_ed(m_sel, "Mover línea arriba", lambda: self._ed_call("move_lines", False), "Alt+Up")
        self._act_ed(m_sel, "Mover línea abajo", lambda: self._ed_call("move_lines", True), "Alt+Down")
        self._act_ed(m_sel, "Duplicar línea", lambda: self._ed_call("duplicate_lines"), "Shift+Alt+Down")
        self._act_ed(m_sel, "Eliminar línea", lambda: self._ed_call("delete_lines"), "Ctrl+Shift+K")

        # --- IA (Claude) ---
        m_ai = bar.addMenu("&IA")
        self._act_ed(m_ai, "Explica la selección", lambda: self._run_ai_action("explain"), "Ctrl+I")
        self._act_ed(m_ai, "Refactoriza la selección", lambda: self._run_ai_action("refactor"))
        self._act_ed(m_ai, "Escribe tests", lambda: self._run_ai_action("tests"))
        self._act_ed(m_ai, "Documenta", lambda: self._run_ai_action("document"))
        self._act_ed(m_ai, "Busca bugs", lambda: self._run_ai_action("bugs"))
        m_ai.addSeparator()
        self._act_ed(m_ai, "Preguntar a Claude…", lambda: self._run_ai_action("ask"), "Ctrl+Shift+I")

        # --- Ver ---
        m_view = bar.addMenu("&Ver")
        self._act(m_view, "Acercar (zoom +)", self.zoom_in, ["Ctrl+=", "Ctrl++"])
        self._act(m_view, "Alejar (zoom -)", self.zoom_out, "Ctrl+-")
        self._act(m_view, "Restablecer zoom", self.zoom_reset, "Ctrl+0")
        m_view.addSeparator()
        self._act_ed(m_view, "Alternar explorador", self.toggle_sidebar, "Ctrl+B")
        self._act_ed(m_view, "Alternar terminal", self.toggle_terminal, "Ctrl+J")
        self.act_wrap = self._act_ed(m_view, "Ajuste de línea", self.toggle_wrap, "Alt+Z")
        self.act_wrap.setCheckable(True)
        m_view.addSeparator()
        self.act_follow = QAction("Seguir archivos que Claude edita", self)
        self.act_follow.setCheckable(True)
        self.act_follow.setChecked(self.follow_enabled)
        self.act_follow.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_follow.toggled.connect(self._set_follow)
        m_view.addAction(self.act_follow)

        # --- Ir ---
        m_go = bar.addMenu("&Ir")
        self._act_ed(m_go, "Ir a línea…", self.go_to_line, "Ctrl+G")
        m_go.addSeparator()
        self._act(m_go, "Pestaña siguiente", lambda: self._cycle_tab(1), "Ctrl+PgDown")
        self._act(m_go, "Pestaña anterior", lambda: self._cycle_tab(-1), "Ctrl+PgUp")

        # --- Terminal ---
        m_term = bar.addMenu("&Terminal")
        self._act(m_term, "Lanzar claude / reiniciar", self.chat.restart)
        self._act(m_term, "Mostrar/ocultar terminal", self.toggle_terminal)

        # --- Remoto ---
        m_remote = bar.addMenu("&Remoto")
        self._act(m_remote, "Conectar a VPS…", self.show_connections, "Ctrl+Shift+P")
        self._act(m_remote, "Desconectar (volver a local)", self.disconnect_remote)

        # --- Ayuda ---
        m_help = bar.addMenu("A&yuda")
        self._act(m_help, "Documentación de Claude Code",
                  lambda: QDesktopServices.openUrl(QUrl("https://docs.claude.com/claude-code")))
        self._act(m_help, "Repositorio de Kodea",
                  lambda: QDesktopServices.openUrl(QUrl("https://github.com/Maalfer/kodea")))
        self._act(m_help, "Atajos de teclado", self.show_shortcuts)
        m_help.addSeparator()
        self._act(m_help, "Acerca de Kodea", self.show_about)

    # ----------------------------------------------------- helpers de editor

    def _current_editor(self) -> CodeEditor | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, CodeEditor) else None

    def _ed(self) -> CodeEditor | None:
        w = QApplication.focusWidget()
        if isinstance(w, CodeEditor):
            return w
        return self._current_editor()

    def _ed_call(self, method: str, *args):
        ed = self._ed()
        if ed is not None:
            getattr(ed, method)(*args)

    # ----------------------------------------------------- acciones de IA

    def _claude_path_ref(self, path: str) -> str:
        """Referencia al archivo para el prompt (ruta relativa si es local)."""
        if self.connection is not None:
            return f"`{path}` (en el servidor)"
        try:
            rel = os.path.relpath(path, self.workdir) if self.workdir else path
        except ValueError:
            rel = path
        return f"`{path if rel.startswith('..') else rel}`"

    @staticmethod
    def _ai_prompt(key: str, ref: str, rng: str) -> str:
        return {
            "explain": f"Explica qué hace el código de {ref} en {rng}. No cambies nada, "
                       f"solo explícamelo.",
            "refactor": f"Refactoriza el código de {ref} en {rng} para que sea más limpio y "
                        f"legible manteniendo el comportamiento, y aplica los cambios.",
            "tests": f"Escribe tests para el código de {ref} en {rng}.",
            "document": f"Añade comentarios y documentación al código de {ref} en {rng} "
                        f"y aplica los cambios.",
            "bugs": f"Revisa el código de {ref} en {rng} en busca de bugs, errores o "
                    f"problemas y dime qué encuentras.",
        }[key]

    def _run_ai_action(self, key: str, ed: CodeEditor | None = None):
        ed = ed or self._ed()
        if ed is None:
            return
        if not self.workdir:
            QMessageBox.information(
                self, "Claude",
                "Abre una carpeta o conéctate a un VPS para usar las acciones de IA "
                "(Claude debe estar en marcha en el terminal).")
            return
        cur = ed.textCursor()
        doc = ed.document()
        a = doc.findBlock(cur.selectionStart()).blockNumber() + 1
        b = doc.findBlock(cur.selectionEnd()).blockNumber() + 1
        rng = f"la línea {a}" if a == b else f"las líneas {a}-{b}"
        ref = self._claude_path_ref(ed.path)
        if key == "ask":
            text, ok = QInputDialog.getMultiLineText(
                self, "Preguntar a Claude", f"Tu pregunta sobre {ref} ({rng}):", "")
            if not ok or not text.strip():
                return
            prompt = f"Sobre {ref} en {rng}: {text.strip()}"
        else:
            prompt = self._ai_prompt(key, ref, rng)
        self.chat.setVisible(True)
        self.chat.send_to_claude(prompt)
        self.statusBar().showMessage("✦ Enviado a Claude", 3000)

    # --------------------------------------------------------------- zoom

    def _apply_zoom(self):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CodeEditor):
                w.set_font_size(self.editor_font_pt)
        self.statusBar().showMessage(f"Zoom: {self.editor_font_pt} pt", 1500)

    def zoom_step(self, delta: int):
        self.editor_font_pt = max(6, min(40, self.editor_font_pt + delta))
        self._apply_zoom()

    def zoom_in(self):
        self.zoom_step(1)

    def zoom_out(self):
        self.zoom_step(-1)

    def zoom_reset(self):
        from .editor import DEFAULT_FONT_SIZE
        self.editor_font_pt = DEFAULT_FONT_SIZE
        self._apply_zoom()

    # ------------------------------------------------------ vista / paneles

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def toggle_terminal(self):
        self.chat.setVisible(not self.chat.isVisible())

    def toggle_wrap(self, checked: bool):
        from .editor import CodeEditor as _CE
        from PySide6.QtWidgets import QPlainTextEdit
        mode = QPlainTextEdit.WidgetWidth if checked else QPlainTextEdit.NoWrap
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, _CE):
                w.setLineWrapMode(mode)

    # ------------------------------------------------------ navegación / tabs

    def _cycle_tab(self, step: int):
        n = self.tabs.count()
        if n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % n)

    def close_current_tab(self):
        if self.tabs.count():
            self.close_tab(self.tabs.currentIndex())

    def close_all_tabs(self):
        for i in range(self.tabs.count() - 1, -1, -1):
            self.close_tab(i)

    def go_to_line(self):
        ed = self._ed()
        if ed is None:
            return
        total = ed.blockCount()
        line, ok = QInputDialog.getInt(self, "Ir a línea", f"Línea (1–{total}):",
                                       ed.textCursor().blockNumber() + 1, 1, total)
        if ok:
            block = ed.document().findBlockByNumber(line - 1)
            cur = ed.textCursor()
            cur.setPosition(block.position())
            ed.setTextCursor(cur)
            ed.centerCursor()
            ed.setFocus()

    # ------------------------------------------------------------- ayuda

    def show_shortcuts(self):
        rows = [
            ("Abrir carpeta", "Ctrl+O"), ("Abrir archivo", "Ctrl+Shift+O"),
            ("Guardar / Guardar todo", "Ctrl+S / Ctrl+Alt+S"),
            ("Cerrar pestaña", "Ctrl+W"), ("Buscar / Reemplazar", "Ctrl+F / Ctrl+H"),
            ("Comentar línea", "Ctrl+/"), ("Mover línea", "Alt+↑ / Alt+↓"),
            ("Duplicar / Eliminar línea", "Shift+Alt+↓ / Ctrl+Shift+K"),
            ("Zoom", "Ctrl+ + / Ctrl+ - / Ctrl+0"),
            ("Explorador / Terminal", "Ctrl+B / Ctrl+J"),
            ("Ir a línea", "Ctrl+G"), ("Cambiar pestaña", "Ctrl+PgUp / Ctrl+PgDown"),
            ("Conectar a VPS", "Ctrl+Shift+P"), ("Seguir a Claude", "Ctrl+Shift+F"),
        ]
        body = "\n".join(f"{name:<32}{keys}" for name, keys in rows)
        box = QMessageBox(self)
        box.setWindowTitle("Atajos de teclado")
        box.setText("Atajos de Kodea")
        box.setInformativeText(f"<pre>{body}</pre>")
        box.exec()

    def show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle("Acerca de Kodea")
        box.setIconPixmap(icons.app_pixmap_round(72))
        box.setText(f"<b>Kodea</b> {__version__}")
        box.setInformativeText(
            "Editor de código con Claude Code y SSH integrados.<br><br>"
            "<a href='https://github.com/Maalfer/kodea'>github.com/Maalfer/kodea</a>")
        box.exec()

    # ------------------------------------------------------------- contexto

    def open_local_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Abrir carpeta", os.path.expanduser("~"))
        if path:
            self._set_context(LocalFS(), path, None)

    def show_connections(self):
        dlg = ConnectionsManager(self, self.store)
        if dlg.exec() == QDialog.Accepted and dlg.selected:
            self.connect_remote(dlg.selected)

    def connect_remote(self, conn: Connection):
        # la conexión SSH puede tardar; se hace en segundo plano para no
        # congelar la ventana
        self.statusBar().showMessage(f"Conectando a {conn.display}…")
        self.conn_status.setText(f"⬤ Conectando a {conn.display}…")
        task = _ConnectTask(conn)
        self._tasks.add(task)
        task.signals.ok.connect(lambda fs, wd, t=task, c=conn: self._on_connected(fs, wd, c, t))
        task.signals.err.connect(lambda msg, t=task, c=conn: self._on_connect_error(msg, c, t))
        QThreadPool.globalInstance().start(task)

    def _on_connected(self, fs: FileSystem, workdir: str, conn: Connection, task=None):
        self._tasks.discard(task)
        self._set_context(fs, workdir, conn)
        self.statusBar().showMessage(f"Conectado a {conn.display}")

    def _on_connect_error(self, msg: str, conn: Connection, task=None):
        self._tasks.discard(task)
        QMessageBox.critical(self, "Error de conexión",
                             f"No se pudo conectar a {conn.display}:\n{msg}")
        self.statusBar().showMessage("Error de conexión")
        self.conn_status.setText("⬤ Local")

    def disconnect_remote(self):
        if self.connection:
            self.fs.close()
            self.connection = None
            self.fs = LocalFS()
            self.workdir = ""
            self._fs_snapshot = {}
            self._primed = False
            self._scanning = False
            self.tree.clear()
            self.context_label.setText("Abre una carpeta o conéctate a un VPS")
            self.statusBar().showMessage("Desconectado")

    def _set_follow(self, enabled: bool):
        self.follow_enabled = enabled
        self.statusBar().showMessage(
            "Follow mode activado — sigo los archivos que edita Claude" if enabled
            else "Follow mode desactivado", 3000)

    def _set_context(self, fs: FileSystem, workdir: str, conn: Connection | None):
        if self.connection and fs is not self.fs:
            self.fs.close()
        self.fs = fs
        self.workdir = workdir
        self.connection = conn
        # nueva base de referencia para el escaneo (no revelar todo de golpe)
        self._fs_snapshot = {}
        self._primed = False
        self._scanning = False
        # el escaneo recursivo por SFTP es más caro: hazlo algo más espaciado
        self.watch_timer.setInterval(2500 if fs.is_remote else 1500)
        where = f"🌐 {conn.display}" if conn else "💻 Local"
        self.context_label.setText(f"{where}\n{workdir}")
        self.tree.set_root(fs, workdir)
        self.chat.set_context(workdir, conn)
        self.setWindowTitle(f"Kodea — {conn.display if conn else os.path.basename(workdir)}")
        if conn:
            self.conn_status.setText(f"⬤ SSH: {conn.display}")
        else:
            self.conn_status.setText(f"⬤ Local: {os.path.basename(workdir)}")

    # ------------------------------------------------------------- pestañas

    def _tab_for_path(self, path: str) -> int | None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CodeEditor) and w.path == path and w.fs is self.fs:
                return i
        return None

    def open_file(self, path: str, focus: bool = True):
        # ¿ya está abierta?
        existing = self._tab_for_path(path)
        if existing is not None:
            self.tabs.setCurrentIndex(existing)
            return
        try:
            content = self.fs.read_text(path)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo abrir {path}:\n{e}")
            return
        # cierra la pestaña de bienvenida si sigue ahí
        if self.tabs.count() == 1 and not isinstance(self.tabs.widget(0), CodeEditor):
            self.tabs.removeTab(0)

        editor = CodeEditor(path, font_size=self.editor_font_pt)
        editor.fs = self.fs
        editor.zoom_requested.connect(self.zoom_step)
        editor.change_undo.connect(lambda ed=editor: self._undo_change(ed))
        editor.ai_action.connect(lambda key, ed=editor: self._run_ai_action(key, ed))
        if getattr(self, "act_wrap", None) and self.act_wrap.isChecked():
            from PySide6.QtWidgets import QPlainTextEdit
            editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        try:
            editor._mtime = self.fs.mtime(path)
        except Exception:
            editor._mtime = None
        editor.setPlainText(content)
        editor.document().setModified(False)
        name = os.path.basename(path)
        idx = self.tabs.addTab(editor, icons.file_icon(name), name)
        self.tabs.setTabToolTip(idx, f"{self.fs.label}: {path}")
        self.tabs.setCurrentIndex(idx)
        editor.modified_changed.connect(lambda mod, ed=editor: self._mark_modified(ed, mod))
        editor.cursorPositionChanged.connect(self._update_cursor_status)
        self._update_cursor_status()
        if focus:
            editor.setFocus()

    def _update_cursor_status(self):
        if not hasattr(self, "cursor_status"):
            return  # aún construyendo la ventana
        w = self.tabs.currentWidget()
        if isinstance(w, CodeEditor):
            c = w.textCursor()
            self.cursor_status.setText(f"Ln {c.blockNumber() + 1}, Col {c.positionInBlock() + 1}")
            lang = lang_for_path(w.path)
            self.lang_status.setText(lang.capitalize() if lang else "Texto")
        else:
            self.cursor_status.setText("")
            self.lang_status.setText("")

    def _mark_modified(self, editor: CodeEditor, modified: bool):
        idx = self.tabs.indexOf(editor)
        if idx < 0:
            return
        name = os.path.basename(editor.path)
        self.tabs.setTabText(idx, f"● {name}" if modified else name)

    def close_tab(self, index: int):
        w = self.tabs.widget(index)
        if isinstance(w, CodeEditor) and w.document().isModified():
            resp = QMessageBox.question(
                self, "Cambios sin guardar",
                f"¿Guardar los cambios de {os.path.basename(w.path)}?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if resp == QMessageBox.Cancel:
                return
            if resp == QMessageBox.Save:
                self._save_editor(w)
        self.tabs.removeTab(index)

    def save_current(self):
        w = self.tabs.currentWidget()
        if isinstance(w, CodeEditor):
            self._save_editor(w)

    def _save_editor(self, editor: CodeEditor):
        try:
            editor.fs.write_text(editor.path, editor.toPlainText())
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar:\n{e}")
            return
        editor.document().setModified(False)
        try:
            editor._mtime = editor.fs.mtime(editor.path)
            # registra el mtime para que el guardado propio no se interprete
            # como una edición externa de Claude
            self._fs_snapshot[editor.path] = editor._mtime
        except Exception:
            editor._mtime = None
        self.statusBar().showMessage(f"Guardado {editor.path}", 3000)

    def open_file_dialog(self):
        if self.fs.is_remote:
            QMessageBox.information(
                self, "Abrir archivo",
                "Con un VPS conectado, abre los archivos desde el explorador.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir archivo", self.workdir or os.path.expanduser("~"))
        if path:
            self.open_file(path)

    def save_as(self):
        ed = self._ed()
        if ed is None:
            return
        if ed.fs.is_remote:
            new_path, ok = QInputDialog.getText(
                self, "Guardar como", "Ruta en el servidor:", text=ed.path)
            if not ok or not new_path:
                return
        else:
            new_path, _ = QFileDialog.getSaveFileName(
                self, "Guardar como", ed.path or os.path.expanduser("~"))
            if not new_path:
                return
        try:
            ed.fs.write_text(new_path, ed.toPlainText())
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar:\n{e}")
            return
        ed.path = new_path
        idx = self.tabs.indexOf(ed)
        if idx >= 0:
            name = os.path.basename(new_path)
            self.tabs.setTabText(idx, name)
            self.tabs.setTabIcon(idx, icons.file_icon(name))
            self.tabs.setTabToolTip(idx, f"{ed.fs.label}: {new_path}")
        ed.document().setModified(False)
        self.statusBar().showMessage(f"Guardado {new_path}", 3000)

    def save_all(self):
        saved = 0
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CodeEditor) and w.document().isModified():
                self._save_editor(w)
                saved += 1
        self.statusBar().showMessage(f"{saved} archivo(s) guardado(s)", 3000)

    # ------------------------------------------------------------- claude

    def _scan_changes(self):
        """Lanza un escaneo del proyecto en segundo plano (no bloquea la UI).
        Si ya hay uno en curso, se salta este tick para no encolar trabajo."""
        if not self.workdir or self._scanning:
            return
        self._scanning = True
        task = _ScanTask(self.fs, self.workdir)
        self._tasks.add(task)
        task.signals.done.connect(lambda fs, snap, t=task: self._on_scan_done(fs, snap, t))
        task.signals.failed.connect(lambda t=task: self._on_scan_failed(t))
        QThreadPool.globalInstance().start(task)

    def _on_scan_failed(self, task=None):
        self._tasks.discard(task)
        self._scanning = False

    def _on_scan_done(self, scanned_fs: FileSystem, snapshot: dict, task=None):
        self._tasks.discard(task)
        """Procesa (en el hilo de la GUI) el resultado del escaneo: recarga las
        pestañas abiertas que cambiaron y revela el archivo recién editado."""
        self._scanning = False
        # si cambiamos de carpeta/conexión mientras escaneaba, descarta
        if scanned_fs is not self.fs:
            return
        prev = self._fs_snapshot
        if not self._primed:
            # primer escaneo tras abrir/conectar: solo fija la línea base
            self._fs_snapshot = snapshot
            self._primed = True
            return
        changed = [p for p, m in snapshot.items() if m > prev.get(p, 0.0)]
        self._fs_snapshot = snapshot
        if not changed:
            return
        if not self.follow_enabled:
            # follow desactivado: recarga silenciosa, sin resaltar
            for p in changed:
                self._reload_if_open(p, jump=False)
            return
        newest = max(changed, key=lambda p: snapshot[p])
        for p in changed:
            if self._tab_for_path(p) is not None:
                # archivo abierto: aplica el cambio y resáltalo (con Deshacer)
                self._show_change_diff(p, jump=(p == newest))
        # trae al frente / abre el archivo recién tocado
        if self._tab_for_path(newest) is None:
            self._reveal_file(newest)
        else:
            self.tabs.setCurrentIndex(self._tab_for_path(newest))
            self.tree.reveal(newest)

    def _reload_if_open(self, path: str, jump: bool = False):
        """Recarga la pestaña de `path` si está abierta y sin cambios propios.
        Con `jump`, salta a la primera línea modificada; si no, conserva la
        posición y el scroll actuales."""
        idx = self._tab_for_path(path)
        if idx is None:
            return
        w = self.tabs.widget(idx)
        if w.document().isModified():
            return
        try:
            m = w.fs.mtime(path)
        except Exception:
            return
        if m == getattr(w, "_mtime", None):
            return
        try:
            fresh = w.fs.read_text(path)
        except Exception:
            return
        w._mtime = m
        self._fs_snapshot[path] = m
        if fresh == w.toPlainText():
            return
        if jump:
            line = _first_diff_line(w.toPlainText(), fresh)
            w.setPlainText(fresh)
            block = w.document().findBlockByNumber(line)
            cursor = w.textCursor()
            cursor.setPosition(block.position() if block.isValid() else 0)
            w.setTextCursor(cursor)
            w.centerCursor()
        else:
            pos = w.textCursor().position()
            scroll = w.verticalScrollBar().value()
            w.setPlainText(fresh)
            cursor = w.textCursor()
            cursor.setPosition(min(pos, len(fresh)))
            w.setTextCursor(cursor)
            w.verticalScrollBar().setValue(scroll)
        w.document().setModified(False)
        self.statusBar().showMessage(
            f"♻ {os.path.basename(path)} actualizado por Claude", 4000)

    def _show_change_diff(self, path: str, jump: bool = False):
        """Aplica el cambio de Claude (auto-aceptado) en la pestaña abierta y lo
        resalta (verde lo añadido, rojo lo borrado) con opción de Deshacer."""
        idx = self._tab_for_path(path)
        if idx is None:
            return
        ed = self.tabs.widget(idx)
        if ed.document().isModified():
            self.statusBar().showMessage(
                f"⚠ {os.path.basename(path)}: Claude lo cambió, pero tienes "
                f"ediciones sin guardar (no se toca)", 6000)
            return
        try:
            m = ed.fs.mtime(path)
        except Exception:
            return
        if m == getattr(ed, "_mtime", None):
            return
        try:
            fresh = ed.fs.read_text(path)
        except Exception:
            return
        # baseline = estado previo (si ya estaba en revisión, conserva el original
        # para que «Deshacer» revierta todo el lote de cambios de Claude)
        baseline = ed.review_baseline if ed.in_review else ed.toPlainText()
        ed._mtime = m
        self._fs_snapshot[path] = m
        if fresh == baseline:
            ed.clear_review()
            return
        added, deleted, hunks = diff_regions(baseline, fresh)
        pos = ed.textCursor().position()
        scroll = ed.verticalScrollBar().value()
        ed.set_text_silently(fresh)
        ed.document().setModified(False)
        ed.enter_review(baseline, added, deleted, hunks)
        if jump:
            ed.goto_change(0)
        else:
            cursor = ed.textCursor()
            cursor.setPosition(min(pos, len(fresh)))
            ed.setTextCursor(cursor)
            ed.verticalScrollBar().setValue(scroll)
        self.statusBar().showMessage(
            f"✦ {os.path.basename(path)}: {hunks} cambio(s) de Claude — "
            f"Deshacer si no te convencen", 5000)

    def _undo_change(self, ed: CodeEditor):
        """Revierte el archivo al estado previo a los cambios de Claude (también
        en disco / VPS) y quita el resaltado."""
        baseline = ed.review_baseline
        if baseline is None:
            ed.clear_review()
            return
        ed.set_text_silently(baseline)
        try:
            ed.fs.write_text(ed.path, baseline)
            ed._mtime = ed.fs.mtime(ed.path)
            self._fs_snapshot[ed.path] = ed._mtime
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo deshacer:\n{e}")
            return
        ed.document().setModified(False)
        ed.clear_review()
        self.statusBar().showMessage(
            f"↩ {os.path.basename(ed.path)} restaurado (cambios de Claude deshechos)", 4000)

    def _reveal_file(self, path: str):
        """Trae al frente (y abre si hace falta) el archivo editado por Claude,
        sin robar el foco del terminal, y lo selecciona en el explorador."""
        idx = self._tab_for_path(path)
        if idx is None:
            if not _is_watchable(os.path.basename(path)):
                return
            self.open_file(path, focus=False)
            idx = self._tab_for_path(path)
            if idx is None:
                return  # no se pudo abrir (binario, error de lectura…)
        self.tabs.setCurrentIndex(idx)
        self.tree.reveal(path)
        self.statusBar().showMessage(
            f"➜ {os.path.basename(path)} (editado por Claude)", 4000)

    # ------------------------------------------------------------- cierre

    def closeEvent(self, event):
        modified = [
            self.tabs.widget(i) for i in range(self.tabs.count())
            if isinstance(self.tabs.widget(i), CodeEditor) and self.tabs.widget(i).document().isModified()
        ]
        if modified:
            resp = QMessageBox.question(
                self, "Cambios sin guardar",
                f"Hay {len(modified)} archivo(s) con cambios sin guardar. ¿Salir igualmente?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp == QMessageBox.No:
                event.ignore()
                return
        self.chat.shutdown()
        self.fs.close()
        event.accept()


class ConnectionsManager(QDialog):
    """Lista de conexiones guardadas: conectar, crear, editar, eliminar."""

    def __init__(self, parent, store: ConnectionStore):
        super().__init__(parent)
        self.setWindowTitle("Conexiones SSH")
        self.setMinimumSize(440, 320)
        self.store = store
        self.selected: Connection | None = None

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._connect())
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        btn_new = QPushButton("Nueva…")
        btn_new.setProperty("flat", True)
        btn_new.clicked.connect(self._new)
        btn_edit = QPushButton("Editar…")
        btn_edit.setProperty("flat", True)
        btn_edit.clicked.connect(self._edit)
        btn_del = QPushButton("Eliminar")
        btn_del.setProperty("flat", True)
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_new)
        row.addWidget(btn_edit)
        row.addWidget(btn_del)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox()
        connect_btn = buttons.addButton("Conectar", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        connect_btn.clicked.connect(self._connect)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._reload()

    def _reload(self):
        self.list.clear()
        for conn in self.store.connections:
            item = QListWidgetItem(f"🌐 {conn.display}   ({conn.user}@{conn.host}:{conn.port})")
            item.setData(Qt.UserRole, conn)
            self.list.addItem(item)

    def _current(self) -> Connection | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _new(self):
        dlg = ConnectionDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.store.add(dlg.result_connection())
            self._reload()

    def _edit(self):
        conn = self._current()
        if conn:
            dlg = ConnectionDialog(self, conn)
            if dlg.exec() == QDialog.Accepted:
                self.store.save()
                self._reload()

    def _delete(self):
        conn = self._current()
        if conn:
            self.store.remove(conn)
            self._reload()

    def _connect(self):
        self.selected = self._current()
        if self.selected:
            self.accept()
