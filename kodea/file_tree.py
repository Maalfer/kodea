"""Árbol de archivos con carga perezosa, válido para FS local y remoto."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from . import icons
from .fs import FileSystem

ROLE_PATH = Qt.UserRole
ROLE_IS_DIR = Qt.UserRole + 1
ROLE_LOADED = Qt.UserRole + 2

SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".DS_Store"}


class FileTree(QTreeWidget):
    file_activated = Signal(str)  # ruta del archivo a abrir

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fs: FileSystem | None = None
        self.root_path = ""
        self.setHeaderHidden(True)
        self.setIndentation(12)
        self.setAnimated(True)
        self.setUniformRowHeights(True)
        self.itemExpanded.connect(self._load_children)
        self.itemExpanded.connect(lambda it: it.data(0, ROLE_IS_DIR) and it.setIcon(0, icons.folder_icon(True)))
        self.itemCollapsed.connect(lambda it: it.data(0, ROLE_IS_DIR) and it.setIcon(0, icons.folder_icon(False)))
        self.itemActivated.connect(self._on_activated)
        self.itemClicked.connect(self._on_activated)

    def set_root(self, fs: FileSystem, path: str):
        self.fs = fs
        self.root_path = path
        self.refresh()

    def refresh(self):
        # conserva qué rutas estaban expandidas para restaurarlas tras recargar
        expanded = set()
        def collect(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.isExpanded():
                    expanded.add(child.data(0, ROLE_PATH))
                    collect(child)
        collect(self.invisibleRootItem())

        self.clear()
        if not self.fs:
            return
        self._populate(self.invisibleRootItem(), self.root_path)
        self._restore(self.invisibleRootItem(), expanded)

    def _restore(self, item, expanded):
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, ROLE_PATH) in expanded:
                child.setExpanded(True)  # dispara la carga de hijos
                self._restore(child, expanded)

    def _populate(self, parent_item, path: str):
        try:
            entries = self.fs.listdir(path)
        except Exception as e:
            err = QTreeWidgetItem(parent_item, [f"⚠ {e}"])
            err.setDisabled(True)
            return
        for entry in entries:
            if entry.name in SKIP:
                continue
            item = QTreeWidgetItem(parent_item)
            item.setText(0, entry.name)
            item.setIcon(0, icons.folder_icon() if entry.is_dir else icons.file_icon(entry.name))
            item.setToolTip(0, entry.path)
            item.setData(0, ROLE_PATH, entry.path)
            item.setData(0, ROLE_IS_DIR, entry.is_dir)
            item.setData(0, ROLE_LOADED, False)
            if entry.is_dir:
                item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)

    def _load_children(self, item: QTreeWidgetItem):
        if item.data(0, ROLE_LOADED) or not item.data(0, ROLE_IS_DIR):
            return
        item.setData(0, ROLE_LOADED, True)
        self._populate(item, item.data(0, ROLE_PATH))

    def _on_activated(self, item: QTreeWidgetItem, _col: int = 0):
        path = item.data(0, ROLE_PATH)
        if path and not item.data(0, ROLE_IS_DIR):
            self.file_activated.emit(path)
