"""Editor de código: números de línea, resaltado de línea actual y sintaxis."""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import (
    QAction,
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
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QToolButton,
    QWidget,
)

from . import theme


# ---------------------------------------------------------------- sintaxis
#
# Resaltado por *tokenizador con contexto* (no solo regex sueltas): distingue
# definiciones de función de llamadas, clases/tipos, constantes, decoradores,
# números, y maneja comentarios y cadenas (incluidas las multilínea) con estado
# por bloque. Pensado para que Python, JavaScript/TS, Java, PHP, Go, Ruby, C/C++
# y shell se lean como en VS Code.

def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


# Colores VS Code Dark+
C_KEYWORD = "#569cd6"    # palabras clave (def, class, var, public…)
C_CONTROL = "#c586c0"    # control de flujo (if, for, return…)
C_STRING = "#ce9178"     # cadenas
C_COMMENT = "#6a9955"    # comentarios
C_NUMBER = "#b5cea8"     # números
C_FUNC = "#dcdcaa"       # funciones (definición y llamada)
C_TYPE = "#4ec9b0"       # clases / tipos
C_CONST = "#569cd6"      # constantes (True/False/None/null…)
C_DECOR = "#dcdcaa"      # decoradores / anotaciones
C_VAR = "#9cdcfe"        # variables ($var, etc.)

_WORD_RE = re.compile(r"[@$]?[A-Za-z_][A-Za-z0-9_]*")
_NUM_RE = re.compile(
    r"0[xXbBoO][0-9a-fA-F_]+|\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?")


def _spec(*, keywords="", control="", constants="", types="",
          line_comments=(), multiline=(), quotes="'\"",
          func_def="", class_kw="", decorator=False, dollar_vars=False):
    return {
        "keywords": set(keywords.split()),
        "control": set(control.split()),
        "constants": set(constants.split()),
        "types": set(types.split()),
        "line_comments": list(line_comments),
        "multiline": list(multiline),   # (open, close, "comment"|"string")
        "quotes": set(quotes),
        "func_def": set(func_def.split()),
        "class_kw": set(class_kw.split()),
        "decorator": decorator,
        "dollar_vars": dollar_vars,
    }


_BLOCK_C = ("/*", "*/", "comment")
_TICK = ("`", "`", "string")

LANGS = {
    "python": _spec(
        keywords="def lambda class global nonlocal del import from as with async await and or not in is self cls",
        control="if elif else for while break continue return yield try except finally raise assert match case pass",
        constants="True False None Ellipsis NotImplemented",
        types="int float str bool list dict set tuple bytes object complex frozenset bytearray range",
        line_comments=["#"],
        multiline=[('"""', '"""', "string"), ("'''", "'''", "string")],
        func_def="def", class_kw="class", decorator=True),
    "javascript": _spec(
        keywords="function var let const class extends implements new this super typeof instanceof in of delete "
                 "void import export from default as async static get set public private protected readonly enum "
                 "interface namespace type abstract declare",
        control="if else for while do break continue return switch case try catch finally throw yield await",
        constants="true false null undefined NaN Infinity",
        types="string number boolean object symbol bigint any unknown never Array Object String Number Boolean "
              "Promise Map Set Date RegExp Error JSON Math",
        line_comments=["//"], multiline=[_BLOCK_C, _TICK],
        func_def="function", class_kw="class extends implements new instanceof interface", decorator=True),
    "java": _spec(
        keywords="class interface enum extends implements new this super import package public private protected "
                 "static final abstract synchronized volatile transient native instanceof var record sealed permits "
                 "throws default assert",
        control="if else for while do break continue return switch case try catch finally throw yield",
        constants="true false null",
        types="int long short byte char boolean float double void String Integer Long Double Float Boolean Object "
              "List Map Set Optional Stream Exception",
        line_comments=["//"], multiline=[_BLOCK_C],
        class_kw="class interface enum extends implements new instanceof", decorator=True),
    "php": _spec(
        keywords="function fn class interface trait extends implements new clone instanceof public private protected "
                 "static abstract final const var namespace use global echo print isset unset empty list array as "
                 "enum readonly and or xor require require_once include include_once",
        control="if elseif else for foreach while do break continue return switch case try catch finally throw yield match",
        constants="true false null TRUE FALSE NULL",
        types="int float string bool array object void mixed callable iterable self parent static",
        line_comments=["//", "#"], multiline=[_BLOCK_C],
        func_def="function fn", class_kw="class interface trait extends implements new instanceof",
        dollar_vars=True),
    "go": _spec(
        keywords="func var const type struct interface map chan package import",
        control="if else for range switch case break continue return select fallthrough goto defer go",
        constants="true false nil iota",
        types="int int8 int16 int32 int64 uint uint8 uint16 uint32 uint64 float32 float64 string bool byte rune "
              "error complex64 complex128 uintptr any",
        line_comments=["//"], multiline=[_BLOCK_C, _TICK],
        func_def="func", class_kw="type struct interface"),
    "ruby": _spec(
        keywords="def class module require require_relative include extend attr_accessor attr_reader attr_writer "
                 "self super new lambda proc then and or not",
        control="if elsif else unless end for while until do break next return begin rescue ensure raise case when yield",
        constants="true false nil",
        line_comments=["#"], func_def="def", class_kw="class module"),
    "c": _spec(
        keywords="int long short char float double void unsigned signed const static extern struct union enum "
                 "typedef sizeof volatile register inline class public private protected virtual template typename "
                 "namespace using new delete this operator friend explicit auto",
        control="if else for while do break continue return switch case goto",
        constants="true false NULL nullptr",
        types="int char float double void bool size_t int8_t int16_t int32_t int64_t uint8_t uint32_t uint64_t wchar_t",
        line_comments=["//"], multiline=[_BLOCK_C],
        class_kw="class struct union enum new"),
    "shell": _spec(
        keywords="export local readonly declare function alias source set unset eval exec trap let",
        control="if then elif else fi for while until do done case esac break continue return exit in",
        constants="true false",
        line_comments=["#"], func_def="function", dollar_vars=True),
}
LANGS["cpp"] = LANGS["c"]

EXT_TO_LANG = {
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "javascript", ".tsx": "javascript", ".json": "javascript", ".vue": "javascript",
    ".java": "java",
    ".php": "php", ".phtml": "php",
    ".go": "go",
    ".rb": "ruby",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".env": "shell",
}


def lang_for_path(path: str) -> str | None:
    path = path.lower()
    for ext, lang in EXT_TO_LANG.items():
        if path.endswith(ext):
            return lang
    return None


class Highlighter(QSyntaxHighlighter):
    """Tokenizador con contexto y estado por bloque (para multilínea)."""

    def __init__(self, document, lang: str | None):
        super().__init__(document)
        self.lang = lang
        self.spec = LANGS.get(lang or "")
        self.fmt = {
            "keyword": _fmt(C_KEYWORD),
            "control": _fmt(C_CONTROL),
            "string": _fmt(C_STRING),
            "comment": _fmt(C_COMMENT, italic=True),
            "number": _fmt(C_NUMBER),
            "function": _fmt(C_FUNC),
            "type": _fmt(C_TYPE),
            "constant": _fmt(C_CONST),
            "decorator": _fmt(C_DECOR),
            "variable": _fmt(C_VAR),
        }
        lc = self.spec["line_comments"] if self.spec else []
        self.comment_token = lc[0] if lc else None

    def highlightBlock(self, text: str):
        if not self.spec:
            return
        self.setCurrentBlockState(0)
        ml = self.spec["multiline"]
        start = 0
        prev = self.previousBlockState()
        if 0 < prev <= len(ml):
            op, cl, kind = ml[prev - 1]
            end = text.find(cl)
            if end == -1:
                self.setFormat(0, len(text), self.fmt[kind])
                self.setCurrentBlockState(prev)
                return
            self.setFormat(0, end + len(cl), self.fmt[kind])
            start = end + len(cl)
        self._scan(text, start)

    def _scan(self, text: str, i: int):
        spec, fmt, n = self.spec, self.fmt, len(text)
        quotes = spec["quotes"]
        line_comments = spec["line_comments"]
        multiline = spec["multiline"]
        while i < n:
            c = text[i]
            # comentario de línea
            if any(text.startswith(lc, i) for lc in line_comments):
                self.setFormat(i, n - i, fmt["comment"])
                return
            # apertura de bloque multilínea (comentario o cadena)
            ml_done = False
            for idx, (op, cl, kind) in enumerate(multiline):
                if text.startswith(op, i):
                    close_at = text.find(cl, i + len(op))
                    if close_at == -1:
                        self.setFormat(i, n - i, fmt[kind])
                        self.setCurrentBlockState(idx + 1)
                        return
                    self.setFormat(i, close_at + len(cl) - i, fmt[kind])
                    i = close_at + len(cl)
                    ml_done = True
                    break
            if ml_done:
                continue
            # cadena de una línea
            if c in quotes:
                i = self._scan_string(text, i, c, allow_interp=False)
                continue
            # número
            if c.isdigit() and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                m = _NUM_RE.match(text, i)
                if m:
                    self.setFormat(i, m.end() - i, fmt["number"])
                    i = m.end()
                    continue
            # palabra (identificador, palabra clave, decorador, variable…)
            if c.isalpha() or c == "_" or c == "@" or (c == "$" and spec["dollar_vars"]):
                m = _WORD_RE.match(text, i)
                if m:
                    end = m.end()
                    word = m.group()
                    nxt = text[end:end + 1]
                    # prefijo de cadena de Python: f"…", r'…', rb"…", f-string…
                    if (self.lang == "python" and nxt in quotes
                            and text[end:end + 3] != nxt * 3
                            and self._is_string_prefix(word)):
                        self.setFormat(i, end - i, fmt["string"])
                        i = self._scan_string(text, end, nxt,
                                              allow_interp="f" in word.lower())
                        continue
                    self._classify(text, i, end, word)
                    i = end
                    continue
            i += 1

    @staticmethod
    def _is_string_prefix(word: str) -> bool:
        return len(word) <= 2 and all(ch in "frbuFRBU" for ch in word)

    def _scan_string(self, text: str, i: int, quote: str, allow_interp: bool) -> int:
        """Colorea una cadena de una línea desde la comilla en `i`. Si
        `allow_interp`, los tramos {…} (f-strings) se tokenizan como código."""
        n = len(text)
        seg = i           # inicio del tramo de cadena sin pintar
        j = i + 1
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == quote:
                j += 1
                self.setFormat(seg, j - seg, self.fmt["string"])
                return j
            if allow_interp and ch == "{":
                if text[j + 1:j + 2] == "{":     # '{{' literal
                    j += 2
                    continue
                self.setFormat(seg, j - seg, self.fmt["string"])
                close = self._brace_end(text, j)
                self._scan_code_range(text, j + 1, close)
                j = close + 1
                seg = j
                continue
            j += 1
        self.setFormat(seg, n - seg, self.fmt["string"])
        return n

    @staticmethod
    def _brace_end(text: str, j: int) -> int:
        depth, n = 0, len(text)
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        return n - 1

    def _scan_code_range(self, text: str, i: int, end: int):
        """Tokeniza el interior de una interpolación como código."""
        quotes = self.spec["quotes"]
        while i < end:
            c = text[i]
            if c in quotes:
                i = self._scan_string(text, i, c, allow_interp=False)
                continue
            if c.isdigit() and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                m = _NUM_RE.match(text, i)
                if m and m.end() <= end:
                    self.setFormat(i, m.end() - i, self.fmt["number"])
                    i = m.end()
                    continue
            if c.isalpha() or c == "_" or (c == "$" and self.spec["dollar_vars"]):
                m = _WORD_RE.match(text, i)
                if m:
                    self._classify(text, i, m.end(), m.group())
                    i = m.end()
                    continue
            i += 1

    def _classify(self, text: str, i: int, end: int, word: str):
        spec, fmt = self.spec, self.fmt
        if word[0] == "@":
            if spec["decorator"]:
                self.setFormat(i, end - i, fmt["decorator"])
            return
        if word[0] == "$":
            self.setFormat(i, end - i, fmt["variable"])
            return
        if word in spec["control"]:
            self.setFormat(i, end - i, fmt["control"])
            return
        if word in spec["keywords"]:
            self.setFormat(i, end - i, fmt["keyword"])
            return
        if word in spec["constants"]:
            self.setFormat(i, end - i, fmt["constant"])
            return
        if word in spec["types"]:
            self.setFormat(i, end - i, fmt["type"])
            return
        prev = self._prev_word(text, i)
        if prev in spec["func_def"]:
            self.setFormat(i, end - i, fmt["function"])
            return
        if prev in spec["class_kw"]:
            self.setFormat(i, end - i, fmt["type"])
            return
        if self._next_nonspace(text, end) == "(":
            self.setFormat(i, end - i, fmt["function"])
            return
        if word[0].isupper() and any(ch.islower() for ch in word):
            self.setFormat(i, end - i, fmt["type"])   # PascalCase → clase/tipo
            return
        # resto: variable / parámetro / propiedad / constante → celeste
        self.setFormat(i, end - i, fmt["variable"])

    @staticmethod
    def _prev_word(text: str, i: int) -> str:
        j = i - 1
        while j >= 0 and text[j].isspace():
            j -= 1
        end = j + 1
        while j >= 0 and (text[j].isalnum() or text[j] == "_"):
            j -= 1
        return text[j + 1:end]

    @staticmethod
    def _next_nonspace(text: str, end: int) -> str:
        j = end
        while j < len(text) and text[j].isspace():
            j += 1
        return text[j] if j < len(text) else ""


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


# Acciones de IA sobre la selección (clave interna, etiqueta visible)
AI_ACTIONS = [
    ("explain", "Explica esto"),
    ("refactor", "Refactoriza"),
    ("tests", "Escribe tests"),
    ("document", "Documenta"),
    ("bugs", "Busca bugs"),
    ("ask", "Preguntar a Claude…"),
]


class ReviewBar(QFrame):
    """Tarjeta flotante que avisa de los cambios de Claude (ya aplicados) y
    permite navegarlos o deshacerlos."""

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.setObjectName("reviewBar")
        self.editor = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 8, 6)
        lay.setSpacing(8)

        self.label = QLabel("Claude editó este archivo")
        self.label.setObjectName("reviewLabel")
        lay.addWidget(self.label)

        for text, tip, slot in (("‹", "Cambio anterior", lambda: editor.goto_change(-1)),
                                ("›", "Cambio siguiente", lambda: editor.goto_change(1))):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            lay.addWidget(b)

        self.btn_undo = QPushButton("Deshacer")
        self.btn_undo.setObjectName("reviewUndo")
        self.btn_undo.setToolTip("Revertir estos cambios de Claude")
        self.btn_undo.clicked.connect(editor.change_undo)
        lay.addWidget(self.btn_undo)

        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("Ocultar resaltado (mantener cambios)")
        self.btn_close.clicked.connect(editor.clear_review)
        lay.addWidget(self.btn_close)
        self.hide()

    def set_count(self, hunks: int):
        n = f"{hunks} bloque" + ("" if hunks == 1 else "s")
        self.label.setText(f"✦ Claude cambió {n}")


class CodeEditor(QPlainTextEdit):
    modified_changed = Signal(bool)
    zoom_requested = Signal(int)  # +1 / -1 con Ctrl + rueda del ratón
    change_undo = Signal()        # deshacer el último lote de cambios de Claude
    ai_action = Signal(str)       # acción de IA sobre la selección (clave)

    def __init__(self, path: str = "", parent=None, font_size: int = DEFAULT_FONT_SIZE):
        super().__init__(parent)
        self.path = path
        self._font_pt = font_size
        # estado de revisión de cambios de Claude (antes de cualquier resaltado)
        self._review_bar: ReviewBar | None = None
        self._in_review = False
        self._review_baseline: str | None = None
        self._review_added: list[tuple[int, int]] = []
        self._review_deleted: list[int] = []
        self._applying = False
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

        # si el usuario escribe durante la revisión, se quita el resaltado
        self.document().contentsChanged.connect(self._on_contents_changed)

    @staticmethod
    def _build_lang_words(lang: str | None) -> set[str]:
        spec = LANGS.get(lang or "")
        if not spec:
            return set()
        words: set[str] = set()
        for key in ("keywords", "control", "constants", "types"):
            words.update(spec[key])
        return words

    # --- revisión de cambios de Claude ---
    def enter_review(self, baseline: str, added, deleted, hunks: int):
        """Entra en modo revisión: el buffer ya tiene el contenido nuevo;
        `added` son rangos [j1,j2) de líneas nuevas y `deleted` posiciones
        (línea nueva) donde se borraron líneas."""
        self._review_baseline = baseline
        self._review_added = list(added)
        self._review_deleted = list(deleted)
        self._in_review = True
        if self._review_bar is None:
            self._review_bar = ReviewBar(self)
        self._review_bar.set_count(hunks)
        self._review_bar.show()
        self._review_bar.raise_()
        self._position_review_bar()
        self._highlight_current_line()
        self.viewport().update()

    def clear_review(self):
        self._in_review = False
        self._review_baseline = None
        self._review_added = []
        self._review_deleted = []
        if self._review_bar is not None:
            self._review_bar.hide()
        self._highlight_current_line()
        self.viewport().update()

    @property
    def in_review(self) -> bool:
        return self._in_review

    @property
    def review_baseline(self) -> str | None:
        return self._review_baseline

    def set_text_silently(self, text: str):
        """Cambia el contenido sin que se interprete como edición del usuario."""
        self._applying = True
        self.setPlainText(text)
        self._applying = False

    def _on_contents_changed(self):
        # si el usuario escribe durante la revisión, asumimos que acepta y
        # quitamos los resaltados (sus cambios se conservan)
        if self._in_review and not self._applying:
            self.clear_review()

    def _review_selections(self) -> list:
        if not self._in_review:
            return []
        sels = []
        doc = self.document()
        for j1, j2 in self._review_added:
            for ln in range(j1, j2):
                blk = doc.findBlockByNumber(ln)
                if not blk.isValid():
                    continue
                es = QTextEdit.ExtraSelection()
                es.format.setBackground(QColor("#16351f"))
                es.format.setProperty(QTextFormat.FullWidthSelection, True)
                es.cursor = QTextCursor(blk)
                sels.append(es)
        return sels

    def _change_anchors(self) -> list[int]:
        return sorted(set([a for a, _ in self._review_added] + self._review_deleted))

    def goto_change(self, direction: int):
        anchors = self._change_anchors()
        if not anchors:
            return
        cur = self.textCursor().blockNumber()
        if direction == 0:
            target = anchors[0]
        elif direction > 0:
            target = next((a for a in anchors if a > cur), anchors[0])
        else:
            target = next((a for a in reversed(anchors) if a < cur), anchors[-1])
        blk = self.document().findBlockByNumber(target)
        c = self.textCursor()
        c.setPosition(blk.position())
        self.setTextCursor(c)
        self.centerCursor()

    def _position_review_bar(self):
        bar = self._review_bar
        if bar is None:
            return
        sz = bar.sizeHint()
        avail = self.width() - self.line_number_width() - 16
        w = min(sz.width(), max(avail, 120))
        x = max(self.line_number_width() + 8, self.width() - w - 18)
        bar.setGeometry(x, 8, w, sz.height())

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

    # --- menú contextual con acciones de IA ---
    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        first = menu.actions()[0] if menu.actions() else None
        header = QAction("✦ Claude", menu)
        header.setEnabled(False)
        menu.insertAction(first, header)
        for key, label in AI_ACTIONS:
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, k=key: self.ai_action.emit(k))
            menu.insertAction(first, act)
        menu.insertSeparator(first)
        menu.exec(event.globalPos())

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
        if self._review_bar is not None and self._review_bar.isVisible():
            self._position_review_bar()

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
        self.setExtraSelections([line] + self._review_selections()
                                + self._occurrence_selections()
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

    # --- guías de indentación + marcas de borrado en revisión ---
    def paintEvent(self, event):
        super().paintEvent(event)
        sw = self.fontMetrics().horizontalAdvance(" ")
        if sw <= 0:
            return
        painter = QPainter(self.viewport())
        base = self.contentOffset().x() + self.document().documentMargin()
        deleted = set(self._review_deleted) if self._in_review else set()
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
                painter.setPen(QColor("#34373b"))
                for lvl in range(1, level + 1):
                    x = int(base + lvl * 4 * sw)
                    painter.drawLine(x, top, x, bottom)
                if block.blockNumber() in deleted:
                    # líneas borradas por Claude justo encima de esta
                    painter.setPen(QColor("#f14c4c"))
                    painter.drawLine(0, top, self.viewport().width(), top)
            block = block.next()
        painter.end()
