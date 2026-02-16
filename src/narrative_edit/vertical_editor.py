from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QInputMethodEvent, QKeyEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractScrollArea, QApplication


LINE_HEAD_PROHIBITED = set("、。，．！？)]｝〕〉》」』】")
LINE_END_PROHIBITED = set("([｛〔〈《「『【")
VERTICAL_GLYPH_MAP = {
    "、": "︑",
    "。": "︒",
    "「": "﹁",
    "」": "﹂",
    "『": "﹃",
    "』": "﹄",
    "（": "︵",
    "）": "︶",
    "［": "﹇",
    "］": "﹈",
    "｛": "︷",
    "｝": "︸",
    "〈": "︿",
    "〉": "﹀",
    "《": "︽",
    "》": "︾",
    "【": "︻",
    "】": "︼",
    "ー": "｜",
}


@dataclass
class _LayoutUnit:
    start: int
    end: int
    text: str
    kind: str
    gcol: int
    row: int


class VerticalManuscriptEditor(QAbstractScrollArea):
    cursorPositionChanged = Signal(int, int, int)
    modificationChanged = Signal(bool)
    characterCountChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)

        self._text = ""
        self._cursor_index = 0
        self._anchor_index = 0
        self._modified = False
        self._saved_snapshot = ""
        self._read_only = False
        self._preedit_text = ""

        self._grid_rows = 40
        self._grid_cols = 40
        self._show_grid = True
        self._cell_size = 36
        self._page_gap = 12
        self._outer_margin = 6
        self._page_left = 20

        self._units: list[_LayoutUnit] = []
        self._cursor_slots: list[tuple[int, int]] = [(0, 0)]
        self._total_pages = 1

        self._history: list[tuple[str, int, int]] = [("", 0, 0)]
        self._history_index = 0

        self._theme_name = "soft_light"
        self._bg = QColor("#eef1f4")
        self._page_bg = QColor("#fbfbfd")
        self._grid = QColor("#ccd3dc")
        self._text_color = QColor("#1f2328")
        self._selection = QColor("#96b5e8")
        self._cursor_color = QColor("#2d6ad8")

        self._cursor_visible = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(520)
        self._cursor_timer.timeout.connect(self._blink_cursor)
        self._cursor_timer.start()

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._set_default_font()
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        self._rebuild_layout()

    def _set_default_font(self) -> None:
        font = QFont("Yu Mincho")
        if not font.exactMatch():
            font = QFont("MS Mincho")
        if not font.exactMatch():
            font = QFont("Serif")
        font.setPointSize(16)
        self.setFont(font)
        self._update_cell_size()

    def _update_cell_size(self) -> None:
        fm = self.fontMetrics()
        # Respect configured font size as the primary source of manuscript cell size.
        self._cell_size = max(16, fm.height() + 8)

    def set_font_size(self, size: int) -> None:
        font = QFont(self.font())
        font.setPointSize(max(8, min(64, int(size))))
        self.setFont(font)
        self._update_cell_size()
        self._rebuild_layout()

    def _render_font(self, ratio: float = 0.72) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(max(8, int(self._cell_size * ratio)))
        return font

    def set_grid(self, rows: int, cols: int) -> None:
        self._grid_rows = max(8, min(80, int(rows)))
        self._grid_cols = max(8, min(80, int(cols)))
        self._update_cell_size()
        self._rebuild_layout()

    def set_show_grid(self, show_grid: bool) -> None:
        self._show_grid = bool(show_grid)
        self.viewport().update()

    def set_theme(self, theme_name: str) -> None:
        self._theme_name = "soft_dark" if theme_name == "soft_dark" else "soft_light"
        if self._theme_name == "soft_dark":
            self._bg = QColor("#20262e")
            self._page_bg = QColor("#2a313b")
            self._grid = QColor("#46515f")
            self._text_color = QColor("#dce3ec")
            self._selection = QColor("#4d6ea1")
            self._cursor_color = QColor("#8bb7ff")
        else:
            self._bg = QColor("#f3e9de")
            self._page_bg = QColor("#fffaf4")
            self._grid = QColor("#d8c6b2")
            self._text_color = QColor("#3a2d24")
            self._selection = QColor("#d7e3f5")
            self._cursor_color = QColor("#7c4f2f")
        self.viewport().update()

    def setReadOnly(self, value: bool) -> None:  # noqa: N802
        self._read_only = bool(value)

    def isReadOnly(self) -> bool:  # noqa: N802
        return self._read_only

    def toPlainText(self) -> str:
        return self._text

    def setPlainText(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self._text = normalized
        self._cursor_index = min(self._cursor_index, len(self._text))
        self._anchor_index = self._cursor_index
        self._modified = False
        self._saved_snapshot = self._text
        self._history = [(self._text, self._cursor_index, self._anchor_index)]
        self._history_index = 0
        self._preedit_text = ""
        self._rebuild_layout()
        self.modificationChanged.emit(False)
        self.characterCountChanged.emit(self.character_count())

    def isModified(self) -> bool:  # noqa: N802
        return self._modified

    def setModified(self, modified: bool) -> None:  # noqa: N802
        self._modified = bool(modified)
        if not self._modified:
            self._saved_snapshot = self._text
        self.modificationChanged.emit(self._modified)

    def character_count(self) -> int:
        return sum(1 for ch in self._text if ch not in {"\n", "\r"})

    def selectedText(self) -> str:  # noqa: N802
        if self._cursor_index == self._anchor_index:
            return ""
        lo = min(self._cursor_index, self._anchor_index)
        hi = max(self._cursor_index, self._anchor_index)
        return self._text[lo:hi]

    def clearSelection(self) -> None:  # noqa: N802
        self._anchor_index = self._cursor_index
        self.viewport().update()

    def undo(self) -> None:
        if self._history_index <= 0:
            return
        self._history_index -= 1
        text, cursor, anchor = self._history[self._history_index]
        self._apply_history_state(text, cursor, anchor)

    def redo(self) -> None:
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        text, cursor, anchor = self._history[self._history_index]
        self._apply_history_state(text, cursor, anchor)

    def _apply_history_state(self, text: str, cursor: int, anchor: int) -> None:
        self._text = text
        self._cursor_index = max(0, min(cursor, len(self._text)))
        self._anchor_index = max(0, min(anchor, len(self._text)))
        self._modified = self._text != self._saved_snapshot
        self._rebuild_layout()
        self.modificationChanged.emit(self._modified)
        self.characterCountChanged.emit(self.character_count())

    def _push_history(self) -> None:
        snapshot = (self._text, self._cursor_index, self._anchor_index)
        if self._history and self._history[self._history_index] == snapshot:
            return
        self._history = self._history[: self._history_index + 1]
        self._history.append(snapshot)
        self._history_index = len(self._history) - 1

    def _apply_edit(self, new_text: str, new_cursor: int, new_anchor: Optional[int] = None) -> None:
        if new_anchor is None:
            new_anchor = new_cursor

        old_count = self.character_count()
        self._preedit_text = ""
        self._text = new_text
        self._cursor_index = max(0, min(new_cursor, len(self._text)))
        self._anchor_index = max(0, min(new_anchor, len(self._text)))
        self._modified = self._text != self._saved_snapshot

        self._push_history()
        self._rebuild_layout()
        self.modificationChanged.emit(self._modified)

        new_count = self.character_count()
        if new_count != old_count:
            self.characterCountChanged.emit(new_count)

    def _selection_range(self) -> tuple[int, int]:
        return (min(self._cursor_index, self._anchor_index), max(self._cursor_index, self._anchor_index))

    def _replace_selection(self, insert_text: str) -> None:
        lo, hi = self._selection_range()
        insert_text = insert_text.replace("\r\n", "\n").replace("\r", "\n")
        new_text = self._text[:lo] + insert_text + self._text[hi:]
        cursor = lo + len(insert_text)
        self._apply_edit(new_text, cursor, cursor)

    def _delete_backward(self) -> None:
        if self._cursor_index != self._anchor_index:
            self._replace_selection("")
            return
        if self._cursor_index <= 0:
            return
        idx = self._cursor_index
        new_text = self._text[: idx - 1] + self._text[idx:]
        self._apply_edit(new_text, idx - 1, idx - 1)

    def _delete_forward(self) -> None:
        if self._cursor_index != self._anchor_index:
            self._replace_selection("")
            return
        if self._cursor_index >= len(self._text):
            return
        idx = self._cursor_index
        new_text = self._text[:idx] + self._text[idx + 1 :]
        self._apply_edit(new_text, idx, idx)

    def _insert_text(self, text: str) -> None:
        if not text:
            return
        self._replace_selection(text)

    def find(self, pattern: str, forward: bool = True, is_regex: bool = False, case_sensitive: bool = False) -> bool:
        if not pattern:
            return False

        text = self._text
        if not text:
            return False

        start = max(self._cursor_index, self._anchor_index) if forward else min(self._cursor_index, self._anchor_index)
        span: Optional[tuple[int, int]] = None

        if is_regex:
            flags = re.MULTILINE
            if not case_sensitive:
                flags |= re.IGNORECASE
            regex = re.compile(pattern, flags)
            if forward:
                match = regex.search(text, start)
                if match is None:
                    match = regex.search(text, 0, start)
                if match is not None:
                    span = match.span()
            else:
                last = None
                for match in regex.finditer(text, 0, start):
                    last = match
                if last is None:
                    for match in regex.finditer(text, start):
                        last = match
                if last is not None:
                    span = last.span()
        else:
            source = text if case_sensitive else text.lower()
            needle = pattern if case_sensitive else pattern.lower()
            if forward:
                idx = source.find(needle, start)
                if idx < 0:
                    idx = source.find(needle, 0, start)
            else:
                idx = source.rfind(needle, 0, start)
                if idx < 0:
                    idx = source.rfind(needle, start)
            if idx >= 0:
                span = (idx, idx + len(pattern))

        if span is None:
            return False

        lo, hi = span
        self._anchor_index = lo
        self._cursor_index = hi
        self._ensure_cursor_visible()
        self.cursorPositionChanged.emit(*self.current_page_column_cell())
        self.viewport().update()
        return True

    def current_page_column_cell(self) -> tuple[int, int, int]:
        if not self._cursor_slots:
            return (1, 1, 1)
        gcol, row = self._cursor_slots[min(self._cursor_index, len(self._cursor_slots) - 1)]
        page = gcol // self._grid_cols + 1
        column = gcol % self._grid_cols + 1
        cell = row + 1
        return (page, column, cell)

    def _tokenize(self) -> list[tuple[int, int, str, str]]:
        tokens: list[tuple[int, int, str, str]] = []
        i = 0
        text = self._text
        length = len(text)
        while i < length:
            ch = text[i]
            if ch == "\n":
                tokens.append((i, i + 1, ch, "newline"))
                i += 1
                continue
            if (
                ch.isdigit()
                and i + 1 < length
                and text[i + 1].isdigit()
                and (i == 0 or not text[i - 1].isdigit())
                and (i + 2 == length or not text[i + 2].isdigit())
            ):
                tokens.append((i, i + 2, text[i : i + 2], "tcy"))
                i += 2
                continue
            tokens.append((i, i + 1, ch, "char"))
            i += 1
        return tokens

    def _rebuild_layout(self) -> None:
        length = len(self._text)
        self._cursor_slots = [(0, 0) for _ in range(length + 1)]
        self._units = []

        row = 0
        gcol = 0
        for start, end, token_text, kind in self._tokenize():
            self._cursor_slots[start] = (gcol, row)

            if kind == "newline":
                gcol += 1
                row = 0
                self._cursor_slots[end] = (gcol, row)
                continue

            if row == self._grid_rows - 1 and token_text in LINE_END_PROHIBITED:
                gcol += 1
                row = 0

            if row == 0 and token_text in LINE_HEAD_PROHIBITED and self._units:
                prev = self._units[-1]
                if prev.gcol == gcol - 1 and prev.row == self._grid_rows - 1:
                    prev.gcol = gcol
                    prev.row = 0
                    row = 1

            for mid in range(start + 1, end):
                self._cursor_slots[mid] = (gcol, row)

            self._units.append(_LayoutUnit(start=start, end=end, text=token_text, kind=kind, gcol=gcol, row=row))
            row += 1
            if row >= self._grid_rows:
                row = 0
                gcol += 1

            self._cursor_slots[end] = (gcol, row)

        max_col = 0
        for unit in self._units:
            max_col = max(max_col, unit.gcol)
        for col, _r in self._cursor_slots:
            max_col = max(max_col, col)

        self._total_pages = max(1, (max_col // self._grid_cols) + 1)
        self._update_geometry_cache()
        self._ensure_cursor_visible()
        self.cursorPositionChanged.emit(*self.current_page_column_cell())
        self.viewport().update()

    def _update_geometry_cache(self) -> None:
        page_width = self._grid_cols * self._cell_size
        page_height = self._grid_rows * self._cell_size
        viewport_width = max(1, self.viewport().width())
        viewport_height = max(1, self.viewport().height())

        total_width = self._outer_margin * 2 + self._total_pages * page_width + max(0, self._total_pages - 1) * self._page_gap
        self._page_left = self._outer_margin

        total_height = self._outer_margin * 2 + page_height
        vbar = self.verticalScrollBar()
        vbar.setPageStep(viewport_height)
        vbar.setSingleStep(max(6, self._cell_size // 3))
        vbar.setRange(0, max(0, total_height - viewport_height))

        hbar = self.horizontalScrollBar()
        hbar.setPageStep(viewport_width)
        hbar.setSingleStep(max(6, self._cell_size // 3))
        hbar.setRange(0, max(0, total_width - viewport_width))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_cell_size()
        self._update_geometry_cache()
        self._ensure_cursor_visible()
        self.viewport().update()

    def _page_origin_x(self, page: int) -> float:
        page_width = self._grid_cols * self._cell_size
        # Page 0 is shown on the right; subsequent pages continue to the left.
        return float(self._page_left + (self._total_pages - 1 - page) * (page_width + self._page_gap))

    def _cell_rect(self, gcol: int, row: int) -> QRectF:
        page = gcol // self._grid_cols
        col_in_page = gcol % self._grid_cols
        page_x = self._page_origin_x(page)
        x = page_x + (self._grid_cols - 1 - col_in_page) * self._cell_size
        y = self._outer_margin + row * self._cell_size
        return QRectF(float(x), float(y), float(self._cell_size), float(self._cell_size))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), self._bg)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        page_w = self._grid_cols * self._cell_size
        page_h = self._grid_rows * self._cell_size

        base_font = self._render_font(0.72)
        tcy_font = self._render_font(0.58)
        painter.setFont(base_font)

        for page in range(self._total_pages):
            left = self._page_origin_x(page) - scroll_x
            top = self._outer_margin - scroll_y
            right = left + page_w
            bottom = top + page_h
            if right < 0 or left > self.viewport().width() or bottom < 0 or top > self.viewport().height():
                continue

            rect = QRectF(float(left), float(top), float(page_w), float(page_h))
            painter.fillRect(rect, self._page_bg)
            if self._show_grid:
                painter.setPen(self._grid)
                for r in range(self._grid_rows + 1):
                    y = top + r * self._cell_size
                    painter.drawLine(int(left), int(y), int(left + page_w), int(y))
                for c in range(self._grid_cols + 1):
                    x = left + c * self._cell_size
                    painter.drawLine(int(x), int(top), int(x), int(top + page_h))

        sel_lo, sel_hi = self._selection_range()
        has_selection = sel_lo != sel_hi

        for unit in self._units:
            rect = self._cell_rect(unit.gcol, unit.row)
            rect.translate(float(-scroll_x), float(-scroll_y))
            if rect.bottom() < 0 or rect.top() > self.viewport().height():
                continue

            if has_selection and unit.start < sel_hi and unit.end > sel_lo:
                painter.fillRect(rect, self._selection)

            text = VERTICAL_GLYPH_MAP.get(unit.text, unit.text)
            painter.setPen(self._text_color)

            if unit.kind == "tcy":
                painter.setFont(tcy_font)
                painter.drawText(rect, Qt.AlignCenter, unit.text)
                painter.setFont(base_font)
                continue

            if len(text) == 1 and text.isascii() and text.isalnum():
                center = rect.center()
                painter.save()
                painter.translate(center)
                painter.rotate(90)
                rotated = QRectF(-rect.width() * 0.46, -rect.height() * 0.46, rect.width() * 0.92, rect.height() * 0.92)
                painter.drawText(rotated, Qt.AlignCenter, text)
                painter.restore()
                continue

            painter.drawText(rect, Qt.AlignCenter, text)

        if self._preedit_text and self._cursor_slots:
            preedit_color = QColor(self._text_color)
            preedit_color.setAlpha(190)
            preedit_bg = QColor(self._selection)
            preedit_bg.setAlpha(90)
            gcol, row = self._cursor_slots[min(self._cursor_index, len(self._cursor_slots) - 1)]

            for ch in self._preedit_text:
                rect = self._cell_rect(gcol, row)
                rect.translate(float(-scroll_x), float(-scroll_y))
                if rect.bottom() >= 0 and rect.top() <= self.viewport().height():
                    painter.fillRect(rect, preedit_bg)
                    painter.setPen(preedit_color)
                    draw_ch = VERTICAL_GLYPH_MAP.get(ch, ch)
                    if len(draw_ch) == 1 and draw_ch.isascii() and draw_ch.isalnum():
                        center = rect.center()
                        painter.save()
                        painter.translate(center)
                        painter.rotate(90)
                        rotated = QRectF(-rect.width() * 0.46, -rect.height() * 0.46, rect.width() * 0.92, rect.height() * 0.92)
                        painter.drawText(rotated, Qt.AlignCenter, draw_ch)
                        painter.restore()
                    else:
                        painter.drawText(rect, Qt.AlignCenter, draw_ch)
                    painter.setPen(preedit_color.darker(130))
                    painter.drawLine(int(rect.left()) + 4, int(rect.bottom()) - 3, int(rect.right()) - 4, int(rect.bottom()) - 3)

                row += 1
                if row >= self._grid_rows:
                    row = 0
                    gcol += 1

        if self.hasFocus() and self._cursor_visible and self._cursor_slots:
            ccol, crow = self._cursor_slots[min(self._cursor_index, len(self._cursor_slots) - 1)]
            rect = self._cell_rect(ccol, crow)
            rect.translate(float(-scroll_x), float(-scroll_y))
            if rect.bottom() >= 0 and rect.top() <= self.viewport().height():
                painter.setPen(self._cursor_color)
                x = int(rect.right()) - 3
                painter.drawLine(x, int(rect.top()) + 3, x, int(rect.bottom()) - 3)

    def _blink_cursor(self) -> None:
        self._cursor_visible = not self._cursor_visible
        self.viewport().update()

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._cursor_visible = True
        self.viewport().update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._cursor_visible = False
        self.viewport().update()

    def _nearest_cursor_index(self, gcol_target: int, row_target: int) -> int:
        best_idx = 0
        best_dist = 10**9
        for idx, (gcol, row) in enumerate(self._cursor_slots):
            dist = abs(gcol - gcol_target) * self._grid_rows + abs(row - row_target)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def _point_to_grid(self, point: QPointF) -> tuple[int, int]:
        page_w = self._grid_cols * self._cell_size
        page_h = self._grid_rows * self._cell_size
        world_y = point.y() + self.verticalScrollBar().value() - self._outer_margin
        world_x = point.x() + self.horizontalScrollBar().value()

        row = int(max(0.0, min(page_h - 1, world_y)) // self._cell_size) if world_y >= 0 else 0

        best_page = 0
        best_dist = float("inf")
        for page in range(self._total_pages):
            left = self._page_origin_x(page)
            right = left + page_w
            if world_x < left:
                dist = left - world_x
            elif world_x > right:
                dist = world_x - right
            else:
                dist = 0.0
            if dist < best_dist:
                best_dist = dist
                best_page = page

        within_x = max(0.0, min(page_w - 1, world_x - self._page_origin_x(best_page)))
        col_from_left = int(within_x // self._cell_size)
        col_in_page = max(0, min(self._grid_cols - 1, self._grid_cols - 1 - col_from_left))
        gcol = best_page * self._grid_cols + col_in_page
        return gcol, row

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        self.setFocus()
        gcol, row = self._point_to_grid(event.position())
        idx = self._nearest_cursor_index(gcol, row)

        if event.modifiers() & Qt.ShiftModifier:
            self._cursor_index = idx
        else:
            self._cursor_index = idx
            self._anchor_index = idx

        self._ensure_cursor_visible()
        self.cursorPositionChanged.emit(*self.current_page_column_cell())
        self._cursor_visible = True
        self.viewport().update()

    def _ensure_cursor_visible(self) -> None:
        if not self._cursor_slots:
            return
        gcol, row = self._cursor_slots[min(self._cursor_index, len(self._cursor_slots) - 1)]
        rect = self._cell_rect(gcol, row)
        left = rect.left()
        right = rect.right()
        top = rect.top()
        bottom = rect.bottom()

        hbar = self.horizontalScrollBar()
        hvalue = hbar.value()
        view_left = hvalue + 4
        view_right = hvalue + self.viewport().width() - 4
        if left < view_left:
            hbar.setValue(max(0, int(left) - 8))
        elif right > view_right:
            hbar.setValue(min(hbar.maximum(), int(right - self.viewport().width() + 12)))

        vbar = self.verticalScrollBar()
        value = vbar.value()
        view_top = value + 4
        view_bottom = value + self.viewport().height() - 4

        if top < view_top:
            vbar.setValue(max(0, int(top) - 8))
        elif bottom > view_bottom:
            vbar.setValue(min(vbar.maximum(), int(bottom - self.viewport().height() + 12)))

    def _move_cursor_visual(self, delta_col: int, delta_row: int, keep_anchor: bool) -> None:
        if not self._cursor_slots:
            return
        gcol, row = self._cursor_slots[min(self._cursor_index, len(self._cursor_slots) - 1)]
        target_col = max(0, gcol + delta_col)
        target_row = max(0, min(self._grid_rows - 1, row + delta_row))
        idx = self._nearest_cursor_index(target_col, target_row)
        self._cursor_index = idx
        if not keep_anchor:
            self._anchor_index = idx
        self._ensure_cursor_visible()
        self.cursorPositionChanged.emit(*self.current_page_column_cell())
        self.viewport().update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        keep_anchor = bool(mods & Qt.ShiftModifier)

        if mods & Qt.ControlModifier:
            if key == Qt.Key_Z:
                self.undo()
                return
            if key == Qt.Key_Y:
                self.redo()
                return
            if key == Qt.Key_A:
                self._anchor_index = 0
                self._cursor_index = len(self._text)
                self.viewport().update()
                return
            if key == Qt.Key_C:
                text = self.selectedText()
                if text:
                    QApplication.clipboard().setText(text)
                return
            if key == Qt.Key_X and not self._read_only:
                text = self.selectedText()
                if text:
                    QApplication.clipboard().setText(text)
                    self._replace_selection("")
                return
            if key == Qt.Key_V and not self._read_only:
                clip = QApplication.clipboard().text()
                if clip:
                    self._insert_text(clip)
                return

        if key == Qt.Key_Left:
            self._move_cursor_visual(+1, 0, keep_anchor)
            return
        if key == Qt.Key_Right:
            self._move_cursor_visual(-1, 0, keep_anchor)
            return
        if key == Qt.Key_Up:
            self._move_cursor_visual(0, -1, keep_anchor)
            return
        if key == Qt.Key_Down:
            self._move_cursor_visual(0, +1, keep_anchor)
            return
        if key == Qt.Key_Home:
            self._cursor_index = 0
            if not keep_anchor:
                self._anchor_index = 0
            self._ensure_cursor_visible()
            self.cursorPositionChanged.emit(*self.current_page_column_cell())
            self.viewport().update()
            return
        if key == Qt.Key_End:
            self._cursor_index = len(self._text)
            if not keep_anchor:
                self._anchor_index = self._cursor_index
            self._ensure_cursor_visible()
            self.cursorPositionChanged.emit(*self.current_page_column_cell())
            self.viewport().update()
            return

        if self._read_only:
            return super().keyPressEvent(event)

        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._insert_text("\n")
            return
        if key == Qt.Key_Backspace:
            self._delete_backward()
            return
        if key == Qt.Key_Delete:
            self._delete_forward()
            return
        if key == Qt.Key_Tab:
            self._insert_text("　")
            return

        text = event.text()
        if text and not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            self._insert_text(text)
            return

        super().keyPressEvent(event)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:  # noqa: N802
        if self._read_only:
            return

        self._preedit_text = event.preeditString()
        commit = event.commitString()
        if commit:
            self._insert_text(commit)
        self.viewport().update()
        event.accept()

    def inputMethodQuery(self, query):  # noqa: N802
        if query == Qt.ImCursorRectangle:
            if not self._cursor_slots:
                return QRectF()
            gcol, row = self._cursor_slots[min(self._cursor_index, len(self._cursor_slots) - 1)]
            rect = self._cell_rect(gcol, row)
            rect.translate(float(-self.horizontalScrollBar().value()), float(-self.verticalScrollBar().value()))
            return rect
        return super().inputMethodQuery(query)
