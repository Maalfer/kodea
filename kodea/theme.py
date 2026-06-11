"""Tema oscuro estilo VS Code (Dark+), pulido."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Paleta base
BG = "#1e1e1e"            # fondo del editor
BG_SIDE = "#252526"       # paneles laterales
BG_PANEL = "#2d2d30"      # cabeceras / barras
BG_INPUT = "#3c3c3c"
BORDER = "#3c3c3c"
FG = "#cccccc"
FG_DIM = "#858585"
ACCENT = "#0e639c"
ACCENT_HOVER = "#1177bb"
ACCENT_LINE = "#007fd4"
SELECTION = "#264f78"

EDITOR_FONT = "Menlo"

STYLESHEET = f"""
* {{
    outline: none;
}}
QMainWindow, QDialog {{
    background: {BG_SIDE};
}}
QWidget {{
    color: {FG};
    font-size: 13px;
}}

/* ---------- splitter ---------- */
QSplitter::handle {{
    background: #1b1b1c;
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background: {ACCENT_LINE}; }}

/* ---------- editor / texto ---------- */
QPlainTextEdit, QTextEdit, QTextBrowser {{
    background: {BG};
    color: #d4d4d4;
    border: none;
    selection-background-color: {SELECTION};
    selection-color: #ffffff;
}}

/* ---------- árboles y listas ---------- */
QTreeView, QTreeWidget, QListWidget {{
    background: {BG_SIDE};
    border: none;
    show-decoration-selected: 1;
}}
QTreeView::item, QTreeWidget::item {{
    padding: 4px 2px;
    border: none;
}}
QTreeView::item:selected, QTreeWidget::item:selected {{
    background: #04395e;
    color: #ffffff;
}}
QTreeView::item:hover:!selected, QTreeWidget::item:hover:!selected {{
    background: #2a2d2e;
}}
QTreeView::branch {{
    background: transparent;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 4px;
    margin: 1px 4px;
}}
QListWidget::item:selected {{
    background: #04395e;
    color: white;
}}
QListWidget::item:hover:!selected {{
    background: #2a2d2e;
}}

/* ---------- pestañas ---------- */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid #1b1b1c;
}}
QTabBar {{
    background: {BG_SIDE};
}}
QTabBar::tab {{
    background: {BG_PANEL};
    color: #969696;
    padding: 7px 12px 7px 14px;
    border: none;
    border-right: 1px solid #1b1b1c;
    min-width: 60px;
}}
QTabBar::tab:selected {{
    background: {BG};
    color: #ffffff;
    border-top: 1px solid {ACCENT_LINE};
    padding-top: 6px;
}}
QTabBar::tab:hover:!selected {{
    background: #2e2e31;
    color: #cccccc;
}}
QTabBar::close-button {{
    subcontrol-position: right;
    margin: 2px;
    border-radius: 3px;
}}
QTabBar::close-button:hover {{
    background: #5a5a5a;
}}

/* ---------- botones ---------- */
QPushButton {{
    background: {ACCENT};
    color: white;
    border: none;
    padding: 6px 16px;
    border-radius: 3px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {ACCENT_HOVER}; }}
QPushButton:pressed {{ background: #0d5689; }}
QPushButton:disabled {{
    background: {BG_INPUT};
    color: {FG_DIM};
}}
QPushButton[flat="true"] {{
    background: transparent;
    color: {FG};
    padding: 5px 10px;
    border: 1px solid transparent;
}}
QPushButton[flat="true"]:hover {{
    background: {BG_INPUT};
    border: 1px solid #4a4a4a;
}}

/* ---------- entradas ---------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {BG_INPUT};
    border: 1px solid transparent;
    padding: 6px 8px;
    border-radius: 3px;
    color: {FG};
    selection-background-color: {SELECTION};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {ACCENT_LINE};
}}
QLineEdit:hover, QComboBox:hover {{
    background: #424242;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #9a9a9a;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {BG_PANEL};
    border: 1px solid #454545;
    selection-background-color: #04395e;
    padding: 4px;
}}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
}}
QScrollBar::handle:vertical {{
    background: rgba(121, 121, 121, 0.4);
    min-height: 24px;
    border-radius: 4px;
    margin: 2px 2px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(160, 160, 160, 0.6); }}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(121, 121, 121, 0.4);
    min-width: 24px;
    border-radius: 4px;
    margin: 2px 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: rgba(160, 160, 160, 0.6); }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- barra de estado ---------- */
QStatusBar {{
    background: #007acc;
    color: white;
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{
    color: white;
    font-size: 12px;
    padding: 2px 8px;
}}

/* ---------- menús ---------- */
QMenuBar {{
    background: {BG_PANEL};
    color: {FG};
    border-bottom: 1px solid #1b1b1c;
}}
QMenuBar::item {{
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{ background: {BG_INPUT}; }}
QMenu {{
    background: {BG_PANEL};
    border: 1px solid #454545;
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 16px;
    border-radius: 4px;
}}
QMenu::item:selected {{ background: #04395e; }}
QMenu::separator {{
    height: 1px;
    background: #454545;
    margin: 4px 8px;
}}

/* ---------- varios ---------- */
QToolTip {{
    background: {BG_PANEL};
    color: {FG};
    border: 1px solid #454545;
    padding: 4px 8px;
}}
QLabel#panelTitle {{
    color: #bbbbbb;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
    padding: 10px 14px 4px 14px;
}}
QLabel#contextLabel {{
    color: {FG_DIM};
    padding: 0 14px 8px 14px;
    font-size: 11px;
}}
QWidget#panelBar {{
    background: {BG_SIDE};
    border-top: 1px solid #1b1b1c;
}}
QDialogButtonBox QPushButton {{
    min-width: 70px;
}}
"""


def apply_theme(app: QApplication):
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(BG_SIDE))
    pal.setColor(QPalette.WindowText, QColor(FG))
    pal.setColor(QPalette.Base, QColor(BG))
    pal.setColor(QPalette.AlternateBase, QColor(BG_PANEL))
    pal.setColor(QPalette.Text, QColor("#d4d4d4"))
    pal.setColor(QPalette.Button, QColor(BG_PANEL))
    pal.setColor(QPalette.ButtonText, QColor(FG))
    pal.setColor(QPalette.Highlight, QColor(SELECTION))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor(BG_PANEL))
    pal.setColor(QPalette.ToolTipText, QColor(FG))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
