"""Editor de código: números de línea, resaltado de línea actual y sintaxis."""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QTextEdit, QWidget

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


DEFAULT_FONT_SIZE = 13


class CodeEditor(QPlainTextEdit):
    modified_changed = Signal(bool)
    zoom_requested = Signal(int)  # +1 / -1 con Ctrl + rueda del ratón

    def __init__(self, path: str = "", parent=None, font_size: int = DEFAULT_FONT_SIZE):
        super().__init__(parent)
        self.path = path
        self._font_pt = font_size
        font = QFont(theme.EDITOR_FONT)
        font.setPointSize(font_size)
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
        self.comment_token = self.highlighter.comment_token
        self.document().modificationChanged.connect(self.modified_changed)

        # apariencia más cómoda (cursor marcado, margen para respirar)
        self.setCursorWidth(2)
        self.document().setDocumentMargin(6)
        self.setCenterOnScroll(True)

        # autocompletado: palabras clave del lenguaje + palabras del documento
        self._lang_words = self._build_lang_words(lang_for_path(path))
        self._completer = QCompleter(self)
        self._completer_model = QStringListModel(self._completer)
        self._completer.setModel(self._completer_model)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.popup().setObjectName("completer")
        self._completer.activated.connect(self._insert_completion)

        # resalta otras apariciones de la palabra seleccionada
        self.selectionChanged.connect(self._highlight_current_line)

    @staticmethod
    def _build_lang_words(lang: str | None) -> set[str]:
        spec = LANG_KEYWORDS.get(lang or "", {})
        words: set[str] = set()
        for key in ("keywords", "control"):
            words.update(spec.get(key, "").split())
        return words

    # --- zoom / tamaño de fuente ---
    def set_font_size(self, pt: int):
        pt = max(6, min(40, pt))
        self._font_pt = pt
        font = self.font()
        font.setPointSize(pt)
        self.setFont(font)
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * 4)
        self._update_line_area_width()
        self._line_area.update()

    def font_size(self) -> int:
        return self._font_pt

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_requested.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    # --- operaciones de línea (estilo VS Code) ---
    def _line_span(self) -> tuple[int, int]:
        """(primera, última) línea 0-based cubierta por la selección/cursor."""
        c = self.textCursor()
        first = self.document().findBlock(c.selectionStart()).blockNumber()
        last = self.document().findBlock(c.selectionEnd()).blockNumber()
        return first, last

    def _apply_lines(self, lines: list[str], cursor_line: int, cursor_col: int = 0):
        """Reescribe el documento en una sola operación (conserva el undo) y
        recoloca el cursor."""
        cur = self.textCursor()
        cur.beginEditBlock()
        cur.select(QTextCursor.Document)
        cur.insertText("\n".join(lines))
        cur.endEditBlock()
        line = max(0, min(cursor_line, self.blockCount() - 1))
        blk = self.document().findBlockByNumber(line)
        nc = self.textCursor()
        nc.setPosition(blk.position() + min(cursor_col, len(blk.text())))
        self.setTextCursor(nc)

    def move_lines(self, down: bool):
        first, last = self._line_span()
        lines = self.toPlainText().split("\n")
        if down and last >= len(lines) - 1:
            return
        if not down and first <= 0:
            return
        col = self.textCursor().columnNumber()
        block = lines[first:last + 1]
        del lines[first:last + 1]
        dest = first + 1 if down else first - 1
        lines[dest:dest] = block
        self._apply_lines(lines, dest, col)

    def duplicate_lines(self):
        first, last = self._line_span()
        col = self.textCursor().columnNumber()
        lines = self.toPlainText().split("\n")
        block = lines[first:last + 1]
        lines[last + 1:last + 1] = block
        self._apply_lines(lines, last + 1, col)

    def delete_lines(self):
        first, last = self._line_span()
        lines = self.toPlainText().split("\n")
        del lines[first:last + 1]
        if not lines:
            lines = [""]
        self._apply_lines(lines, min(first, len(lines) - 1), 0)

    def toggle_comment(self):
        token = self.comment_token
        if not token:
            return
        first, last = self._line_span()
        col = self.textCursor().columnNumber()
        lines = self.toPlainText().split("\n")
        seg = [lines[i] for i in range(first, last + 1) if lines[i].strip()]
        commented = bool(seg) and all(l.lstrip().startswith(token) for l in seg)
        for i in range(first, last + 1):
            if not lines[i].strip():
                continue
            if commented:
                idx = lines[i].find(token)
                after = idx + len(token)
                if lines[i][after:after + 1] == " ":
                    after += 1
                lines[i] = lines[i][:idx] + lines[i][after:]
            else:
                indent_len = len(lines[i]) - len(lines[i].lstrip())
                lines[i] = lines[i][:indent_len] + token + " " + lines[i][indent_len:]
        self._apply_lines(lines, last, col)

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
        line = QTextEdit.ExtraSelection()
        line.format.setBackground(QColor("#282828"))
        line.format.setProperty(QTextFormat.FullWidthSelection, True)
        line.cursor = self.textCursor()
        line.cursor.clearSelection()
        self.setExtraSelections([line] + self._occurrence_selections()
                                + self._bracket_selections())
        self._line_area.update()

    def _occurrence_selections(self) -> list:
        """Resalta las demás apariciones de la palabra seleccionada (como VS Code)."""
        c = self.textCursor()
        if not c.hasSelection() or self.document().characterCount() > 200_000:
            return []
        word = c.selectedText()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", word):
            return []
        sels = []
        doc = self.document()
        found = QTextCursor(doc)
        flags = QTextDocument.FindCaseSensitively | QTextDocument.FindWholeWords
        while True:
            found = doc.find(word, found, flags)
            if found.isNull():
                break
            if found.selectionStart() == c.selectionStart():
                continue  # la propia selección ya se ve resaltada
            es = QTextEdit.ExtraSelection()
            es.format.setBackground(QColor("#3a3d41"))
            es.cursor = found
            sels.append(es)
            if len(sels) > 500:
                break
        return sels

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

    # --- autocompletado ---
    def _completion_prefix(self) -> str:
        c = self.textCursor()
        text = c.block().text()
        col = c.positionInBlock()
        i = col
        while i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_"):
            i -= 1
        return text[i:col]

    def _refresh_completions(self, prefix: str):
        words = set(self._lang_words)
        content = self.toPlainText()
        if len(content) < 200_000:
            words.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", content))
        words.discard(prefix)
        self._completer_model.setStringList(sorted(words, key=str.lower))

    def _show_completion(self, force: bool = False):
        prefix = self._completion_prefix()
        if not force and len(prefix) < 2:
            self._completer.popup().hide()
            return
        self._refresh_completions(prefix)
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        cr = self.cursorRect()
        cr.moveTopLeft(self.viewport().mapTo(self, cr.topLeft()))
        cr.setWidth(popup.sizeHintForColumn(0)
                    + popup.verticalScrollBar().sizeHint().width() + 16)
        self._completer.complete(cr)

    def _insert_completion(self, text: str):
        if self._completer.widget() is not self:
            return
        prefix = self._completer.completionPrefix()
        cursor = self.textCursor()
        cursor.insertText(text[len(prefix):])
        self.setTextCursor(cursor)

    def _maybe_complete(self, event):
        ch = event.text()[-1:] if event.text() else ""
        if ch and (ch.isalnum() or ch == "_"):
            self._show_completion(False)
        else:
            self._completer.popup().hide()

    # --- auto-cierre de pares, Enter inteligente e indentación ---
    _PAIRS = {"(": ")", "[": "]", "{": "}"}
    _QUOTES = {'"', "'", "`"}

    def _char_after(self) -> str:
        c = self.textCursor()
        col = c.positionInBlock()
        return c.block().text()[col:col + 1]

    def _char_before(self) -> str:
        c = self.textCursor()
        col = c.positionInBlock()
        return c.block().text()[col - 1:col] if col > 0 else ""

    def keyPressEvent(self, event):
        comp = self._completer
        # con el popup abierto, deja que gestione navegación/aceptación
        if comp.popup().isVisible() and event.key() in (
                Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
            event.ignore()
            return
        # Ctrl+Espacio fuerza el autocompletado
        if (event.modifiers() & Qt.ControlModifier) and event.key() == Qt.Key_Space:
            self._show_completion(force=True)
            return
        if self._handle_pairs_and_indent(event):
            return
        super().keyPressEvent(event)
        self._maybe_complete(event)

    def _handle_pairs_and_indent(self, event) -> bool:
        key = event.key()
        text = event.text()
        cursor = self.textCursor()

        if key in (Qt.Key_Return, Qt.Key_Enter):
            return self._handle_return()

        if key == Qt.Key_Tab:
            if cursor.hasSelection():
                self._indent_selection(1)
                return True
            self.insertPlainText("    ")
            return True
        if key == Qt.Key_Backtab:
            self._indent_selection(-1)
            return True

        if key == Qt.Key_Backspace and not cursor.hasSelection():
            before, after = self._char_before(), self._char_after()
            if (before in self._PAIRS and after == self._PAIRS[before]) or \
               (before in self._QUOTES and after == before):
                c = self.textCursor()
                c.beginEditBlock()
                c.deletePreviousChar()
                c.deleteChar()
                c.endEditBlock()
                return True
            return False

        if text in self._PAIRS:
            close = self._PAIRS[text]
            if cursor.hasSelection():
                cursor.insertText(text + cursor.selectedText() + close)
                return True
            cursor.insertText(text + close)
            cursor.movePosition(QTextCursor.Left)
            self.setTextCursor(cursor)
            return True

        if text and text in self._PAIRS.values():
            if self._char_after() == text:  # salta por encima del cierre ya puesto
                cursor.movePosition(QTextCursor.Right)
                self.setTextCursor(cursor)
                return True
            return False

        if text in self._QUOTES:
            if cursor.hasSelection():
                cursor.insertText(text + cursor.selectedText() + text)
                return True
            if self._char_after() == text:
                cursor.movePosition(QTextCursor.Right)
                self.setTextCursor(cursor)
                return True
            before = self._char_before()
            if before.isalnum() or before == text:  # apóstrofo dentro de palabra
                return False
            cursor.insertText(text + text)
            cursor.movePosition(QTextCursor.Left)
            self.setTextCursor(cursor)
            return True

        return False

    def _handle_return(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        line = cursor.block().text()
        indent = line[: len(line) - len(line.lstrip())]
        before, after = self._char_before(), self._char_after()
        # cursor entre un par {|} () [] → abre bloque indentado
        if before in self._PAIRS and after == self._PAIRS[before]:
            c = self.textCursor()
            c.beginEditBlock()
            c.insertText("\n" + indent + "    \n" + indent)
            c.movePosition(QTextCursor.Up)
            c.movePosition(QTextCursor.EndOfLine)
            c.endEditBlock()
            self.setTextCursor(c)
            return True
        extra = "    " if line.rstrip().endswith((":", "{", "(", "[")) else ""
        cursor.beginEditBlock()
        cursor.insertText("\n" + indent + extra)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True

    def _indent_selection(self, direction: int):
        doc = self.document()
        cursor = self.textCursor()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        edit = self.textCursor()
        edit.beginEditBlock()
        for n in range(first, last + 1):
            blk = doc.findBlockByNumber(n)
            bc = QTextCursor(blk)
            bc.movePosition(QTextCursor.StartOfBlock)
            if direction > 0:
                bc.insertText("    ")
            else:
                btext = blk.text()
                remove = 0
                while remove < 4 and remove < len(btext) and btext[remove] == " ":
                    remove += 1
                if remove == 0 and btext[:1] == "\t":
                    remove = 1
                for _ in range(remove):
                    bc.deleteChar()
        edit.endEditBlock()

    # --- guías de indentación ---
    def paintEvent(self, event):
        super().paintEvent(event)
        sw = self.fontMetrics().horizontalAdvance(" ")
        if sw <= 0:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#34373b"))
        base = self.contentOffset().x() + self.document().documentMargin()
        block = self.firstVisibleBlock()
        offset = self.contentOffset()
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(offset)
            if geo.top() > event.rect().bottom():
                break
            if block.isVisible():
                text = block.text()
                level = (len(text) - len(text.lstrip(" "))) // 4
                top, bottom = int(geo.top()), int(geo.bottom())
                for lvl in range(1, level + 1):
                    x = int(base + lvl * 4 * sw)
                    painter.drawLine(x, top, x, bottom)
            block = block.next()
        painter.end()
