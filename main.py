#!/usr/bin/env python3
"""Kodea — editor de código con chat de Claude Code integrado y soporte SSH."""
import sys

from PySide6.QtWidgets import QApplication

from kodea.theme import apply_theme
from kodea.main_window import MainWindow
from kodea import icons


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Kodea")
    app.setOrganizationName("Kodea")
    app.setWindowIcon(icons.app_icon())
    apply_theme(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
