"""Conexiones SSH: modelo, persistencia en ~/.kodea/connections.json y diálogo."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

CONFIG_DIR = os.path.expanduser("~/.kodea")
CONFIG_FILE = os.path.join(CONFIG_DIR, "connections.json")


@dataclass
class Connection:
    name: str = ""
    host: str = ""
    port: int = 22
    user: str = "root"
    key_path: str = ""          # ruta a clave privada (opcional)
    password: str = ""          # opcional; se guarda en claro, mejor usar claves
    remote_dir: str = ""        # directorio de trabajo inicial en el VPS
    extra: dict = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.name or f"{self.user}@{self.host}"

    def ssh_args(self) -> list[str]:
        """Argumentos para el binario `ssh` del sistema (usa ~/.ssh/config y agente)."""
        args = ["-p", str(self.port), "-o", "BatchMode=no", "-o", "StrictHostKeyChecking=accept-new"]
        if self.key_path:
            args += ["-i", os.path.expanduser(self.key_path)]
        args.append(f"{self.user}@{self.host}")
        return args


class ConnectionStore:
    def __init__(self):
        self.connections: list[Connection] = []
        self.load()

    def load(self):
        self.connections = []
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                self.connections = [Connection(**c) for c in data]
            except Exception:
                pass

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump([asdict(c) for c in self.connections], f, indent=2)
        os.chmod(CONFIG_FILE, 0o600)

    def add(self, conn: Connection):
        self.connections.append(conn)
        self.save()

    def remove(self, conn: Connection):
        self.connections = [c for c in self.connections if c is not conn]
        self.save()


class ConnectionDialog(QDialog):
    """Alta/edición de una conexión SSH."""

    def __init__(self, parent=None, conn: Connection | None = None):
        super().__init__(parent)
        self.setWindowTitle("Conexión SSH")
        self.setMinimumWidth(420)
        self.conn = conn or Connection()

        form = QFormLayout(self)
        self.name = QLineEdit(self.conn.name)
        self.name.setPlaceholderText("Mi VPS de producción")
        self.host = QLineEdit(self.conn.host)
        self.host.setPlaceholderText("203.0.113.10 o vps.midominio.com")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(self.conn.port)
        self.user = QLineEdit(self.conn.user)
        self.key = QLineEdit(self.conn.key_path)
        self.key.setPlaceholderText("~/.ssh/id_ed25519 (vacío = agente/claves por defecto)")
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key)
        key_row.addWidget(browse)
        self.password = QLineEdit(self.conn.password)
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Solo si no usas clave (no recomendado)")
        self.remote_dir = QLineEdit(self.conn.remote_dir)
        self.remote_dir.setPlaceholderText("/var/www/miapp (vacío = home)")

        form.addRow("Nombre:", self.name)
        form.addRow("Host:", self.host)
        form.addRow("Puerto:", self.port)
        form.addRow("Usuario:", self.user)
        form.addRow("Clave privada:", key_row)
        form.addRow("Contraseña:", self.password)
        form.addRow("Directorio:", self.remote_dir)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Clave privada", os.path.expanduser("~/.ssh"))
        if path:
            self.key.setText(path)

    def result_connection(self) -> Connection:
        self.conn.name = self.name.text().strip()
        self.conn.host = self.host.text().strip()
        self.conn.port = self.port.value()
        self.conn.user = self.user.text().strip() or "root"
        self.conn.key_path = self.key.text().strip()
        self.conn.password = self.password.text()
        self.conn.remote_dir = self.remote_dir.text().strip()
        return self.conn
