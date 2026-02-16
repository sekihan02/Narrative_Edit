from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

from .models import DocumentState
from .vertical_editor import VerticalManuscriptEditor


class EditorTab(QWidget):
    cursorPositionChanged = Signal(int, int, int)
    dirtyChanged = Signal(bool)
    characterCountChanged = Signal(int)

    def __init__(self, state: DocumentState, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.state = state
        self.editor = VerticalManuscriptEditor(self)
        self.editor.setPlainText(text)
        self.editor.setModified(state.is_dirty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor)

        self.editor.cursorPositionChanged.connect(self.cursorPositionChanged.emit)
        self.editor.modificationChanged.connect(self._on_modified_changed)
        self.editor.characterCountChanged.connect(self.characterCountChanged.emit)
        self.characterCountChanged.emit(self.editor.character_count())

    def _on_modified_changed(self, modified: bool) -> None:
        self.state.is_dirty = modified
        self.dirtyChanged.emit(modified)

    def set_font_size(self, size: int) -> None:
        self.editor.set_font_size(size)

    def set_theme(self, theme_name: str) -> None:
        self.editor.set_theme(theme_name)

    def set_grid(self, rows: int, cols: int) -> None:
        self.editor.set_grid(rows, cols)

    def set_show_grid(self, show_grid: bool) -> None:
        self.editor.set_show_grid(show_grid)

    def undo(self) -> None:
        self.editor.undo()

    def redo(self) -> None:
        self.editor.redo()

    def current_page_column_cell(self) -> tuple[int, int, int]:
        return self.editor.current_page_column_cell()

    def character_count(self) -> int:
        return self.editor.character_count()
