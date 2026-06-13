"""Ventana principal: explorador + editor con pestañas + chat de Claude Code."""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .terminal import ClaudeTerminalPanel
from .connections import Connection, ConnectionDialog, ConnectionStore
from .editor import CodeEditor, lang_for_path
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
        logo.setPixmap(icons.app_pixmap(88))
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

        # --- layout: [explorador | editor | chat] ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        sidebar = QWidget()
        sidebar.setMinimumWidth(180)
        sl = QVBoxLayout(sidebar)
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
        splitter.addWidget(sidebar)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(320)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda _: self._update_cursor_status())
        welcome = WelcomeWidget(self.open_local_folder, self.show_connections)
        self.tabs.addTab(welcome, "Bienvenida")
        splitter.addWidget(self.tabs)

        self.chat = ClaudeTerminalPanel()
        self.chat.setMinimumWidth(360)
        splitter.addWidget(self.chat)

        splitter.setSizes([240, 700, 540])
        splitter.setStretchFactor(0, 0)  # explorador: ancho fijo
        splitter.setStretchFactor(1, 1)  # editor: absorbe el espacio extra
        splitter.setStretchFactor(2, 0)  # terminal: ancho fijo

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

    def _build_menu(self):
        m_file = self.menuBar().addMenu("Archivo")
        act_open = QAction("Abrir carpeta…", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self.open_local_folder)
        m_file.addAction(act_open)
        act_save = QAction("Guardar", self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self.save_current)
        m_file.addAction(act_save)
        act_refresh = QAction("Recargar explorador", self)
        act_refresh.setShortcut(QKeySequence("Ctrl+R"))
        act_refresh.triggered.connect(self.tree.refresh)
        m_file.addAction(act_refresh)

        m_remote = self.menuBar().addMenu("Remoto")
        act_connect = QAction("Conectar a VPS…", self)
        act_connect.setShortcut(QKeySequence("Ctrl+Shift+P"))
        act_connect.triggered.connect(self.show_connections)
        m_remote.addAction(act_connect)
        act_disconnect = QAction("Desconectar (volver a local)", self)
        act_disconnect.triggered.connect(self.disconnect_remote)
        m_remote.addAction(act_disconnect)

        m_view = self.menuBar().addMenu("Ver")
        self.act_follow = QAction("Seguir archivos que Claude edita", self)
        self.act_follow.setCheckable(True)
        self.act_follow.setChecked(self.follow_enabled)
        self.act_follow.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_follow.toggled.connect(self._set_follow)
        m_view.addAction(self.act_follow)

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

        editor = CodeEditor(path)
        editor.fs = self.fs
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
        newest = max(changed, key=lambda p: snapshot[p]) if self.follow_enabled else None
        for p in changed:
            self._reload_if_open(p, jump=(p == newest))
        if newest is not None:
            self._reveal_file(newest)

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
