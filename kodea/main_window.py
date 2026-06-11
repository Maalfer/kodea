"""Ventana principal: explorador + editor con pestañas + chat de Claude Code."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
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
from .file_tree import FileTree
from .fs import FileSystem, LocalFS, RemoteFS


class WelcomeWidget(QWidget):
    """Pantalla de bienvenida con accesos rápidos."""

    def __init__(self, open_folder_cb, connect_cb, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: #1e1e1e;")
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
            "⌘O&nbsp;&nbsp;Abrir carpeta&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;"
            "⌘⇧P&nbsp;&nbsp;Conectar a VPS&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;"
            "⌘S&nbsp;&nbsp;Guardar&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;"
            "⌘R&nbsp;&nbsp;Recargar explorador"
        )
        keys.setAlignment(Qt.AlignCenter)
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

        # --- layout: [explorador | editor | chat] ---
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        sidebar = QWidget()
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
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda _: self._update_cursor_status())
        welcome = WelcomeWidget(self.open_local_folder, self.show_connections)
        self.tabs.addTab(welcome, "Bienvenida")
        splitter.addWidget(self.tabs)

        self.chat = ClaudeTerminalPanel()
        splitter.addWidget(self.chat)

        splitter.setSizes([240, 700, 540])
        splitter.setStretchFactor(1, 1)

        # barra de estado: conexión a la izquierda, cursor/lenguaje a la derecha
        self.conn_status = QLabel("⬤ Local")
        self.statusBar().addWidget(self.conn_status)
        self.lang_status = QLabel("")
        self.statusBar().addPermanentWidget(self.lang_status)
        self.cursor_status = QLabel("")
        self.statusBar().addPermanentWidget(self.cursor_status)
        self._build_menu()

        # vigila cambios externos (p. ej. ediciones de Claude) en los ficheros abiertos
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(3000)
        self.watch_timer.timeout.connect(self._check_external_changes)
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
        self.statusBar().showMessage(f"Conectando a {conn.display}…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            fs = RemoteFS(conn)
        except Exception as e:
            QMessageBox.critical(self, "Error de conexión", f"No se pudo conectar a {conn.display}:\n{e}")
            self.statusBar().showMessage("Error de conexión")
            return
        finally:
            QApplication.restoreOverrideCursor()
        workdir = conn.remote_dir or fs.home_dir()
        self._set_context(fs, workdir, conn)
        self.statusBar().showMessage(f"Conectado a {conn.display}")

    def disconnect_remote(self):
        if self.connection:
            self.fs.close()
            self.connection = None
            self.fs = LocalFS()
            self.workdir = ""
            self.tree.clear()
            self.context_label.setText("Abre una carpeta o conéctate a un VPS")
            self.statusBar().showMessage("Desconectado")

    def _set_context(self, fs: FileSystem, workdir: str, conn: Connection | None):
        if self.connection and fs is not self.fs:
            self.fs.close()
        self.fs = fs
        self.workdir = workdir
        self.connection = conn
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

    def open_file(self, path: str):
        # ¿ya está abierta?
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CodeEditor) and w.path == path and w.fs is self.fs:
                self.tabs.setCurrentIndex(i)
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
        except Exception:
            editor._mtime = None
        self.statusBar().showMessage(f"Guardado {editor.path}", 3000)

    # ------------------------------------------------------------- claude

    def _check_external_changes(self):
        """Recarga los ficheros abiertos sin cambios propios si alguien
        (normalmente Claude) los ha modificado por debajo."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if not isinstance(w, CodeEditor) or w.document().isModified():
                continue
            try:
                m = w.fs.mtime(w.path)
            except Exception:
                continue
            if m == getattr(w, "_mtime", None):
                continue
            try:
                fresh = w.fs.read_text(w.path)
            except Exception:
                continue
            w._mtime = m
            if fresh != w.toPlainText():
                pos = w.textCursor().position()
                scroll = w.verticalScrollBar().value()
                w.setPlainText(fresh)
                cursor = w.textCursor()
                cursor.setPosition(min(pos, len(fresh)))
                w.setTextCursor(cursor)
                w.verticalScrollBar().setValue(scroll)
                w.document().setModified(False)
                self.statusBar().showMessage(
                    f"♻ Recargado {os.path.basename(w.path)} (modificado externamente)", 4000)

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
