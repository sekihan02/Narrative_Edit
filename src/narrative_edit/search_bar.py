from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPushButton, QWidget


class SearchBar(QWidget):
    findRequested = Signal(bool)  # forward=True/False
    hideRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._language = "ja"
        self._build_ui()

    def _build_ui(self) -> None:
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self.query_edit = QLineEdit(self)
        self.query_edit.installEventFilter(self)

        self.regex_checkbox = QCheckBox(self)
        self.case_checkbox = QCheckBox(self)
        self.prev_button = QPushButton(self)
        self.next_button = QPushButton(self)
        self.close_button = QPushButton("x", self)
        self.close_button.setFixedWidth(28)

        self.prev_button.clicked.connect(lambda: self.findRequested.emit(False))
        self.next_button.clicked.connect(lambda: self.findRequested.emit(True))
        self.close_button.clicked.connect(self.hideRequested.emit)

        layout.addWidget(self.query_edit, 1)
        layout.addWidget(self.regex_checkbox)
        layout.addWidget(self.case_checkbox)
        layout.addWidget(self.prev_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.close_button)

        self._apply_labels()

    def set_language(self, language: str) -> None:
        self._language = "en" if language == "en" else "ja"
        self._apply_labels()

    def _apply_labels(self) -> None:
        if self._language == "en":
            self.query_edit.setPlaceholderText("Search...")
            self.regex_checkbox.setText("Regex")
            self.case_checkbox.setText("Case")
            self.prev_button.setText("Prev")
            self.next_button.setText("Next")
            self.close_button.setToolTip("Close search bar")
            return

        self.query_edit.setPlaceholderText("検索...")
        self.regex_checkbox.setText("正規表現")
        self.case_checkbox.setText("大/小文字")
        self.prev_button.setText("前へ")
        self.next_button.setText("次へ")
        self.close_button.setToolTip("検索バーを閉じる")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.query_edit and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                backward = bool(event.modifiers() & Qt.ShiftModifier)
                self.findRequested.emit(not backward)
                return True
            if event.key() == Qt.Key_Escape:
                self.hideRequested.emit()
                return True
        return super().eventFilter(obj, event)

    def query(self) -> str:
        return self.query_edit.text()

    def is_regex(self) -> bool:
        return self.regex_checkbox.isChecked()

    def is_case_sensitive(self) -> bool:
        return self.case_checkbox.isChecked()

    def open(self, initial_text: str = "") -> None:
        self.setVisible(True)
        if initial_text:
            self.query_edit.setText(initial_text)
        self.query_edit.selectAll()
        self.query_edit.setFocus()
