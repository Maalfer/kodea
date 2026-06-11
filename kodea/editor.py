"""Editor de código: números de línea, resaltado de línea actual y sintaxis."""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from . import theme


# ---------------------------------------------------------------- sintaxis

def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


# Colores VS Code Dark+
C_KEYWORD = "#569cd6"
C_CONTROL = "#c586c0"
C_STRING = "#ce9178"
C_COMMENT = "#6a9955"
C_NUMBER = "#b5cea8"
C_FUNC = "#dcdcaa"
C_TYPE = "#4ec9b0"
C_DECOR = "#dcdcaa"

LANG_KEYWORDS = {
    "python": {
        "keywords": "def lambda class global nonlocal del pass import from as with async await "
                    "True False None and or not in is",
        "control": "if elif else for while break continue return yield try except finally raise assert match case",
        "comment": "#",
        "decorator": r"@\w+",
    },
    "javascript": {
        "keywords": "function var let const class extends new this typeof instanceof in of "
                    "true false null undefined async await import export from default delete void",
        "control": "if else for while do break continue return switch case try catch finally throw yield",
        "comment": "//",
    },
    "php": {
        "keywords": "function class extends implements new echo print var const public private protected "
                    "static abstract final namespace use true false null and or xor instanceof",
        "control": "if elseif else for foreach while do break continue return switch case try catch finally throw",
        "comment": "//",
    },
    "shell": {
        "keywords": "export local readonly declare function alias source",
        "control": "if then elif else fi for while until do done case esac break continue return exit",
        "comment": "#",
    },
    "ruby": {
        "keywords": "def class module require include attr_accessor true false nil self new lambda proc",
        "control": "if elsif else unless end for while until do break next return begin rescue ensure raise case when",
        "comment": "#",
    },
    "go": {
        "keywords": "func var const type struct interface map chan package import go defer "
                    "true false nil make new len cap append",
        "control": "if else for range switch case break continue return select fallthrough goto",
        "comment": "//",
    },
}

EXT_TO_LANG = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".ts": "javascript", ".tsx": "javascript",
    ".mjs": "javascript", ".json": "javascript", ".vue": "javascript",
    ".php": "php",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".env": "shell",
    ".yml": "shell", ".yaml": "shell", ".conf": "shell", ".ini": "shell", ".toml": "shell",
    ".rb": "ruby",
    ".go": "go",
    ".html": "javascript", ".css": "javascript", ".sql": "javascript",
}


def lang_for_path(path: str) -> str | None:
    path = path.lower()
    for ext, lang in EXT_TO_LANG.items():
        if path.endswith(ext):
            return lang
    return None


class Highlighter(QSyntaxHighlighter):
    def __init__(self, document, lang: str | None):
        super().__init__(document)
        self.rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self.comment_token = None
        if not lang or lang not in LANG_KEYWORDS:
            return
        spec = LANG_KEYWORDS[lang]
        kw = spec["keywords"].split()
        ctrl = spec["control"].split()
        self.rules.append((re.compile(r"\b(" + "|".join(kw) + r")\b"), _fmt(C_KEYWORD)))
        self.rules.append((re.compile(r"\b(" + "|".join(ctrl) + r")\b"), _fmt(C_CONTROL)))
        self.rules.append((re.compile(r"\b[A-Z][A-Za-z0-9_]*\b"), _fmt(C_TYPE)))
        self.rules.append((re.compile(r"\b\w+(?=\s*\()"), _fmt(C_FUNC)))
        self.rules.append((re.compile(r"\b\d+(\.\d+)?\b"), _fmt(C_NUMBER)))
        if "decorator" in spec:
            self.rules.append((re.compile(spec["decorator"]), _fmt(C_DECOR)))
        # cadenas (después, para que pisen a lo anterior)
        self.rules.append((re.compile(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`\n]*`"), _fmt(C_STRING)))
        self.comment_token = spec.get("comment")
        self.comment_fmt = _fmt(C_COMMENT, italic=True)

    def highlightBlock(self, text: str):
        for pattern, fmt in self.rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        if self.comment_token:
            idx = text.find(self.comment_token)
            if idx >= 0:
                self.setFormat(idx, len(text) - idx, self.comment_fmt)


# ---------------------------------------------------------------- editor

class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    modified_changed = Signal(bool)

    def __init__(self, path: str = "", parent=None):
        super().__init__(parent)
        self.path = path
        font = QFont(theme.EDITOR_FONT)
        font.setPointSize(13)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        self._line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_line_area_width()
        self._highlight_current_line()

        self.highlighter = Highlighter(self.document(), lang_for_path(path))
        self.document().modificationChanged.connect(self.modified_changed)

    # --- números de línea ---
    def line_number_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_line_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(theme.BG))
        sep_x = self._line_area.width() - 1
        painter.setPen(QColor("#2a2a2a"))
        painter.drawLine(sep_x, event.rect().top(), sep_x, event.rect().bottom())
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                color = QColor("#c6c6c6") if num == current else QColor("#6e7681")
                painter.setPen(color)
                painter.drawText(0, top, self._line_area.width() - 8,
                                 self.fontMetrics().height(), Qt.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def _highlight_current_line(self):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor("#282828"))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel] + self._bracket_selections())
        self._line_area.update()

    # --- emparejado de paréntesis/corchetes/llaves ---
    _OPEN = "([{"
    _CLOSE = ")]}"
    _MATCH = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}

    def _bracket_selections(self) -> list:
        cursor = self.textCursor()
        if cursor.hasSelection() or self.document().characterCount() > 300_000:
            return []
        text = self.toPlainText()
        pos = cursor.position()
        for p in (pos - 1, pos):
            if 0 <= p < len(text) and text[p] in self._MATCH:
                match = self._find_match(text, p)
                sels = [self._bracket_sel(p, match is not None)]
                if match is not None:
                    sels.append(self._bracket_sel(match, True))
                return sels
        return []

    def _find_match(self, text: str, p: int) -> int | None:
        ch = text[p]
        target = self._MATCH[ch]
        depth = 1
        if ch in self._OPEN:
            rng = range(p + 1, len(text))
        else:
            rng = range(p - 1, -1, -1)
        for i in rng:
            c = text[i]
            if c == ch:
                depth += 1
            elif c == target:
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _bracket_sel(self, pos: int, matched: bool):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor("#46515c" if matched else "#7a3333"))
        sel.format.setForeground(QColor("#ffd700" if matched else "#ff8888"))
        sel.cursor = self.textCursor()
        sel.cursor.setPosition(pos)
        sel.cursor.setPosition(pos + 1, QTextCursor.KeepAnchor)
        return sel

    # --- indentación básica ---
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            line = cursor.block().text()
            indent = line[: len(line) - len(line.lstrip())]
            if line.rstrip().endswith((":", "{", "(", "[")):
                indent += "    "
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        if event.key() == Qt.Key_Tab and not self.textCursor().hasSelection():
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)
