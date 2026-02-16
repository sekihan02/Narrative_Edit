from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .models import ChapterMemo, CharacterProfile, NovelMetadata, ProgressGoals


class NovelInfoPanel(QWidget):
    metadataChanged = Signal(object)
    sectionStateChanged = Signal(str, bool)
    panelExpandedChanged = Signal(bool)

    def __init__(self, language: str = "ja", theme: str = "soft_light", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("plot_panel")
        self._language = "en" if language == "en" else "ja"
        self._theme = "soft_dark" if theme == "soft_dark" else "soft_light"
        self._updating = False
        self._current_chars = 0
        self._panel_expanded = True
        self._sections: dict[str, tuple[QPushButton, QGroupBox, str, str]] = {}

        self._build_ui()
        self._apply_language()
        self._apply_theme()

    def _t(self, ja: str, en: str) -> str:
        return ja if self._language == "ja" else en

    def _add_section(self, key: str, group: QGroupBox, title_ja: str, title_en: str, expanded: bool = True) -> None:
        toggle = QPushButton(self.container)
        toggle.setObjectName("section_toggle")
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.clicked.connect(lambda checked, k=key: self._on_section_toggled(k, checked))
        self._sections[key] = (toggle, group, title_ja, title_en)
        self.body.addWidget(toggle)
        self.body.addWidget(group)
        group.setVisible(expanded)

    def _on_section_toggled(self, key: str, checked: bool) -> None:
        section = self._sections.get(key)
        if not section:
            return
        _button, group, _ja, _en = section
        group.setVisible(bool(checked))
        self._refresh_section_toggle_texts()
        self.sectionStateChanged.emit(key, bool(checked))

    def _refresh_section_toggle_texts(self) -> None:
        for _key, (button, _group, title_ja, title_en) in self._sections.items():
            marker = "▼" if button.isChecked() else "▶"
            button.setText(f"{marker} {self._t(title_ja, title_en)}")

    def _refresh_panel_toggle_text(self) -> None:
        # Keep toggle as arrow-only so it reads as a clear side drawer control.
        self.panel_toggle.setText("")
        self.panel_toggle.setArrowType(Qt.RightArrow if self._panel_expanded else Qt.LeftArrow)
        self.panel_toggle.setToolTip(
            self._t("プロット情報を折りたたむ", "Collapse Plot Panel")
            if self._panel_expanded
            else self._t("プロット情報を開く", "Expand Plot Panel")
        )

    def _on_panel_toggled(self, checked: bool) -> None:
        self._panel_expanded = bool(checked)
        self.scroll.setVisible(self._panel_expanded)
        self._refresh_panel_toggle_text()
        self.panelExpandedChanged.emit(self._panel_expanded)

    def panel_expanded(self) -> bool:
        return bool(self._panel_expanded)

    def set_panel_expanded(self, expanded: bool) -> None:
        self._panel_expanded = bool(expanded)
        self.panel_toggle.setChecked(self._panel_expanded)
        self.scroll.setVisible(self._panel_expanded)
        self._refresh_panel_toggle_text()

    def section_states(self) -> dict[str, bool]:
        states: dict[str, bool] = {}
        for key, (button, _group, _ja, _en) in self._sections.items():
            states[key] = bool(button.isChecked())
        return states

    def set_section_states(self, states: dict[str, bool]) -> None:
        if not isinstance(states, dict):
            return
        for key, state in states.items():
            section = self._sections.get(key)
            if not section:
                continue
            button, group, _ja, _en = section
            checked = bool(state)
            button.setChecked(checked)
            group.setVisible(checked)
        self._refresh_section_toggle_texts()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.panel_toggle = QToolButton(self)
        self.panel_toggle.setObjectName("panel_toggle")
        self.panel_toggle.setCheckable(True)
        self.panel_toggle.setChecked(True)
        self.panel_toggle.clicked.connect(self._on_panel_toggled)
        self.panel_toggle.setFixedWidth(30)
        self.panel_toggle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        root.addWidget(self.panel_toggle, 0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.container = QWidget(self.scroll)
        self.container.setObjectName("plot_panel_body")
        self.scroll.setWidget(self.container)

        self.body = QVBoxLayout(self.container)
        self.body.setContentsMargins(8, 8, 8, 8)
        self.body.setSpacing(10)

        self.overview_group = QGroupBox(self.container)
        overview_form = QFormLayout(self.overview_group)
        overview_form.setLabelAlignment(Qt.AlignLeft)

        self.title_edit = QLineEdit(self.overview_group)
        self.genre_edit = QLineEdit(self.overview_group)
        self.pov_edit = QLineEdit(self.overview_group)
        self.setting_edit = QLineEdit(self.overview_group)
        self.logline_edit = QTextEdit(self.overview_group)
        self.main_plot_edit = QTextEdit(self.overview_group)
        self.sub_plot_edit = QTextEdit(self.overview_group)

        for w in (self.logline_edit, self.main_plot_edit, self.sub_plot_edit):
            w.setFixedHeight(66)

        self._label_title = QLabel(self.overview_group)
        self._label_genre = QLabel(self.overview_group)
        self._label_pov = QLabel(self.overview_group)
        self._label_setting = QLabel(self.overview_group)
        self._label_logline = QLabel(self.overview_group)
        self._label_main_plot = QLabel(self.overview_group)
        self._label_sub_plot = QLabel(self.overview_group)

        overview_form.addRow(self._label_title, self.title_edit)
        overview_form.addRow(self._label_genre, self.genre_edit)
        overview_form.addRow(self._label_pov, self.pov_edit)
        overview_form.addRow(self._label_setting, self.setting_edit)
        overview_form.addRow(self._label_logline, self.logline_edit)
        overview_form.addRow(self._label_main_plot, self.main_plot_edit)
        overview_form.addRow(self._label_sub_plot, self.sub_plot_edit)

        self.characters_group = QGroupBox(self.container)
        characters_layout = QVBoxLayout(self.characters_group)
        characters_buttons = QHBoxLayout()
        self.add_character_btn = QPushButton(self.characters_group)
        self.remove_character_btn = QPushButton(self.characters_group)
        characters_buttons.addWidget(self.add_character_btn)
        characters_buttons.addWidget(self.remove_character_btn)
        characters_buttons.addStretch(1)
        self.characters_table = QTableWidget(self.characters_group)
        self.characters_table.setColumnCount(5)
        self.characters_table.verticalHeader().setVisible(False)
        self.characters_table.horizontalHeader().setStretchLastSection(True)
        characters_layout.addLayout(characters_buttons)
        characters_layout.addWidget(self.characters_table)

        self.chapters_group = QGroupBox(self.container)
        chapters_layout = QVBoxLayout(self.chapters_group)
        chapters_buttons = QHBoxLayout()
        self.add_chapter_btn = QPushButton(self.chapters_group)
        self.remove_chapter_btn = QPushButton(self.chapters_group)
        chapters_buttons.addWidget(self.add_chapter_btn)
        chapters_buttons.addWidget(self.remove_chapter_btn)
        chapters_buttons.addStretch(1)
        self.chapters_table = QTableWidget(self.chapters_group)
        self.chapters_table.setColumnCount(5)
        self.chapters_table.verticalHeader().setVisible(False)
        self.chapters_table.horizontalHeader().setStretchLastSection(True)
        chapters_layout.addLayout(chapters_buttons)
        chapters_layout.addWidget(self.chapters_table)

        self.setting_group = QGroupBox(self.container)
        setting_form = QFormLayout(self.setting_group)
        self.world_notes_edit = QTextEdit(self.setting_group)
        self.glossary_notes_edit = QTextEdit(self.setting_group)
        self.reference_notes_edit = QTextEdit(self.setting_group)
        self._label_world = QLabel(self.setting_group)
        self._label_glossary = QLabel(self.setting_group)
        self._label_reference = QLabel(self.setting_group)
        for w in (self.world_notes_edit, self.glossary_notes_edit, self.reference_notes_edit):
            w.setFixedHeight(64)
        setting_form.addRow(self._label_world, self.world_notes_edit)
        setting_form.addRow(self._label_glossary, self.glossary_notes_edit)
        setting_form.addRow(self._label_reference, self.reference_notes_edit)

        self.progress_group = QGroupBox(self.container)
        progress_grid = QGridLayout(self.progress_group)
        self._label_daily_target = QLabel(self.progress_group)
        self.daily_target_spin = QSpinBox(self.progress_group)
        self.daily_target_spin.setRange(0, 1_000_000)
        self.current_chars_label = QLabel(self.progress_group)
        self.achieve_rate_label = QLabel(self.progress_group)
        self.remaining_label = QLabel(self.progress_group)
        self.pages_estimate_label = QLabel(self.progress_group)
        self._label_current_chars = QLabel(self.progress_group)
        self._label_achieve_rate = QLabel(self.progress_group)
        self._label_remaining = QLabel(self.progress_group)
        self._label_pages = QLabel(self.progress_group)

        progress_grid.addWidget(self._label_daily_target, 0, 0)
        progress_grid.addWidget(self.daily_target_spin, 0, 1)
        progress_grid.addWidget(self._label_current_chars, 1, 0)
        progress_grid.addWidget(self.current_chars_label, 1, 1)
        progress_grid.addWidget(self._label_achieve_rate, 2, 0)
        progress_grid.addWidget(self.achieve_rate_label, 2, 1)
        progress_grid.addWidget(self._label_remaining, 3, 0)
        progress_grid.addWidget(self.remaining_label, 3, 1)
        progress_grid.addWidget(self._label_pages, 4, 0)
        progress_grid.addWidget(self.pages_estimate_label, 4, 1)

        self._add_section("progress", self.progress_group, "進捗分析", "Progress", expanded=True)
        self._add_section("overview", self.overview_group, "概要", "Overview", expanded=True)
        self._add_section("characters", self.characters_group, "登場人物", "Characters", expanded=True)
        self._add_section("chapters", self.chapters_group, "章メモ", "Chapters", expanded=True)
        self._add_section("setting", self.setting_group, "設定資料", "References", expanded=True)

        self.body.addStretch(1)
        root.addWidget(self.scroll, 1)

        self.add_character_btn.clicked.connect(self._add_character_row)
        self.remove_character_btn.clicked.connect(self._remove_character_row)
        self.add_chapter_btn.clicked.connect(self._add_chapter_row)
        self.remove_chapter_btn.clicked.connect(self._remove_chapter_row)
        self.characters_table.itemChanged.connect(self._on_any_changed)
        self.chapters_table.itemChanged.connect(self._on_any_changed)

        for widget in (
            self.title_edit,
            self.genre_edit,
            self.pov_edit,
            self.setting_edit,
            self.logline_edit,
            self.main_plot_edit,
            self.sub_plot_edit,
            self.world_notes_edit,
            self.glossary_notes_edit,
            self.reference_notes_edit,
        ):
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._on_any_changed)
            else:
                widget.textChanged.connect(self._on_any_changed)

        self.daily_target_spin.valueChanged.connect(self._on_any_changed)

    def set_language(self, language: str) -> None:
        self._language = "en" if language == "en" else "ja"
        self._apply_language()

    def set_theme(self, theme_name: str) -> None:
        self._theme = "soft_dark" if theme_name == "soft_dark" else "soft_light"
        self._apply_theme()

    def _apply_language(self) -> None:
        self._refresh_panel_toggle_text()

        self.overview_group.setTitle("")
        self._label_title.setText(self._t("作品タイトル", "Title"))
        self._label_genre.setText(self._t("ジャンル", "Genre"))
        self._label_pov.setText(self._t("視点", "Point of View"))
        self._label_setting.setText(self._t("舞台/時代", "Setting"))
        self._label_logline.setText(self._t("ログライン", "Logline"))
        self._label_main_plot.setText(self._t("主プロット", "Main Plot"))
        self._label_sub_plot.setText(self._t("サブプロット", "Sub Plot"))

        self.characters_group.setTitle("")
        self.add_character_btn.setText(self._t("追加", "Add"))
        self.remove_character_btn.setText(self._t("削除", "Remove"))
        self.characters_table.setHorizontalHeaderLabels(
            [
                self._t("名前", "Name"),
                self._t("役割", "Role"),
                self._t("目的", "Goal"),
                self._t("葛藤", "Conflict"),
                self._t("メモ", "Notes"),
            ]
        )

        self.chapters_group.setTitle("")
        self.add_chapter_btn.setText(self._t("追加", "Add"))
        self.remove_chapter_btn.setText(self._t("削除", "Remove"))
        self.chapters_table.setHorizontalHeaderLabels(
            [
                self._t("章", "No"),
                self._t("タイトル", "Title"),
                self._t("目的", "Purpose"),
                self._t("要約", "Summary"),
                self._t("目標文字数", "Target Chars"),
            ]
        )

        self.setting_group.setTitle("")
        self._label_world.setText(self._t("世界観", "World Notes"))
        self._label_glossary.setText(self._t("用語メモ", "Glossary"))
        self._label_reference.setText(self._t("参考メモ", "Reference"))

        self.progress_group.setTitle("")
        self._label_daily_target.setText(self._t("日次目標文字数", "Daily Target"))
        self._label_current_chars.setText(self._t("現在文字数", "Current Chars"))
        self._label_achieve_rate.setText(self._t("達成率", "Achievement"))
        self._label_remaining.setText(self._t("残文字数", "Remaining"))
        self._label_pages.setText(self._t("推定原稿枚数", "Estimated Pages"))

        self._refresh_section_toggle_texts()
        self._update_progress_labels()

    def _apply_theme(self) -> None:
        if self._theme == "soft_dark":
            self.setStyleSheet(
                """
                QWidget#plot_panel, QWidget#plot_panel_body {
                    background: #232a33;
                    color: #dce3ec;
                }
                QWidget#plot_panel QLabel,
                QWidget#plot_panel QGroupBox::title {
                    color: #dce3ec;
                }
                QWidget#plot_panel QGroupBox {
                    border: 1px solid #485466;
                    border-radius: 6px;
                    margin-top: 4px;
                    padding-top: 8px;
                    background: #2a313b;
                }
                QWidget#plot_panel QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 8px;
                    padding: 0 3px;
                }
                QWidget#plot_panel QLineEdit,
                QWidget#plot_panel QTextEdit,
                QWidget#plot_panel QTableWidget,
                QWidget#plot_panel QSpinBox,
                QWidget#plot_panel QAbstractItemView {
                    background: #36404d;
                    color: #dce3ec;
                    border: 1px solid #556172;
                    selection-background-color: #4d6ea1;
                    selection-color: #f4f8ff;
                }
                QWidget#plot_panel QTableWidget::item {
                    color: #dce3ec;
                }
                QWidget#plot_panel QTableCornerButton::section {
                    background: #2a313b;
                    border: 1px solid #556172;
                }
                QWidget#plot_panel QHeaderView::section {
                    background: #2a313b;
                    color: #dce3ec;
                    border: 1px solid #556172;
                }
                QWidget#plot_panel QPushButton {
                    background: #3a4657;
                    color: #dce3ec;
                    border: 1px solid #5a687d;
                    padding: 4px 8px;
                }
                QWidget#plot_panel QPushButton:hover { background: #47556b; }
                QWidget#plot_panel QToolButton#panel_toggle {
                    background: #1f2630;
                    border: none;
                    border-left: 1px solid #556172;
                    color: #dce3ec;
                }
                QWidget#plot_panel QToolButton#panel_toggle:hover { background: #2a3340; }
                QWidget#plot_panel QPushButton#section_toggle {
                    text-align: left;
                    font-weight: 600;
                    background: #2f3845;
                    border: 1px solid #556172;
                    padding: 5px 8px;
                }
                QWidget#plot_panel QPushButton#section_toggle:hover { background: #3a4657; }
                QWidget#plot_panel QLabel#panel_header {
                    font-size: 15px;
                    font-weight: 600;
                    padding: 2px 0 6px 2px;
                }
                """
            )
            return

        self.setStyleSheet(
            """
            QWidget#plot_panel, QWidget#plot_panel_body {
                background: #f2e9df;
                color: #3a2d24;
            }
            QWidget#plot_panel QLabel,
            QWidget#plot_panel QGroupBox::title {
                color: #3a2d24;
            }
            QWidget#plot_panel QGroupBox {
                border: 1px solid #d7c7b6;
                border-radius: 6px;
                margin-top: 4px;
                padding-top: 8px;
                background: #f8efe5;
            }
            QWidget#plot_panel QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px;
            }
            QWidget#plot_panel QLineEdit,
            QWidget#plot_panel QTextEdit,
            QWidget#plot_panel QTableWidget,
            QWidget#plot_panel QSpinBox,
            QWidget#plot_panel QAbstractItemView {
                background: #fffaf4;
                color: #3a2d24;
                border: 1px solid #d7c7b6;
                selection-background-color: #d7e3f5;
                selection-color: #2a1f18;
            }
            QWidget#plot_panel QTableWidget::item {
                color: #3a2d24;
            }
            QWidget#plot_panel QTableCornerButton::section {
                background: #f1e5d8;
                border: 1px solid #d7c7b6;
            }
            QWidget#plot_panel QHeaderView::section {
                background: #f1e5d8;
                color: #3a2d24;
                border: 1px solid #d7c7b6;
            }
                QWidget#plot_panel QPushButton {
                    background: #efe2d4;
                    color: #3a2d24;
                    border: 1px solid #d7c7b6;
                    padding: 4px 8px;
                }
                QWidget#plot_panel QPushButton:hover { background: #e6d8c9; }
                QWidget#plot_panel QToolButton#panel_toggle {
                    background: #e9ddcf;
                    border: none;
                    border-left: 1px solid #d7c7b6;
                    color: #5a4332;
                }
                QWidget#plot_panel QToolButton#panel_toggle:hover { background: #e2d3c3; }
                QWidget#plot_panel QPushButton#section_toggle {
                    text-align: left;
                    font-weight: 600;
                    background: #efe2d4;
                    border: 1px solid #d7c7b6;
                padding: 5px 8px;
            }
            QWidget#plot_panel QPushButton#section_toggle:hover { background: #e6d8c9; }
            QWidget#plot_panel QLabel#panel_header {
                font-size: 15px;
                font-weight: 600;
                padding: 2px 0 6px 2px;
            }
            """
        )

    def set_character_count(self, count: int) -> None:
        self._current_chars = max(0, int(count))
        self._update_progress_labels()

    def _add_character_row(self) -> None:
        row = self.characters_table.rowCount()
        self.characters_table.insertRow(row)
        for col in range(self.characters_table.columnCount()):
            self.characters_table.setItem(row, col, QTableWidgetItem(""))
        self._on_any_changed()

    def _remove_character_row(self) -> None:
        row = self.characters_table.currentRow()
        if row >= 0:
            self.characters_table.removeRow(row)
            self._on_any_changed()

    def _add_chapter_row(self) -> None:
        row = self.chapters_table.rowCount()
        self.chapters_table.insertRow(row)
        defaults = [str(row + 1), "", "", "", "0"]
        for col, value in enumerate(defaults):
            self.chapters_table.setItem(row, col, QTableWidgetItem(value))
        self._on_any_changed()

    def _remove_chapter_row(self) -> None:
        row = self.chapters_table.currentRow()
        if row >= 0:
            self.chapters_table.removeRow(row)
            self._on_any_changed()

    def _safe_int(self, text: str, default: int = 0) -> int:
        try:
            return int(text)
        except Exception:
            return default

    def metadata(self) -> NovelMetadata:
        characters: list[CharacterProfile] = []
        for row in range(self.characters_table.rowCount()):
            values = []
            for col in range(self.characters_table.columnCount()):
                item = self.characters_table.item(row, col)
                values.append(item.text().strip() if item else "")
            if any(values):
                characters.append(
                    CharacterProfile(
                        name=values[0],
                        role=values[1],
                        goal=values[2],
                        conflict=values[3],
                        notes=values[4],
                    )
                )

        chapters: list[ChapterMemo] = []
        for row in range(self.chapters_table.rowCount()):
            values = []
            for col in range(self.chapters_table.columnCount()):
                item = self.chapters_table.item(row, col)
                values.append(item.text().strip() if item else "")
            if any(values):
                chapters.append(
                    ChapterMemo(
                        number=max(1, self._safe_int(values[0], row + 1)),
                        title=values[1],
                        purpose=values[2],
                        summary=values[3],
                        target_chars=max(0, self._safe_int(values[4], 0)),
                    )
                )

        return NovelMetadata(
            work_title=self.title_edit.text().strip(),
            genre=self.genre_edit.text().strip(),
            point_of_view=self.pov_edit.text().strip(),
            era_setting=self.setting_edit.text().strip(),
            logline=self.logline_edit.toPlainText().strip(),
            main_plot=self.main_plot_edit.toPlainText().strip(),
            sub_plot=self.sub_plot_edit.toPlainText().strip(),
            world_notes=self.world_notes_edit.toPlainText().strip(),
            glossary_notes=self.glossary_notes_edit.toPlainText().strip(),
            reference_notes=self.reference_notes_edit.toPlainText().strip(),
            characters=characters,
            chapters=chapters,
            progress_goals=ProgressGoals(daily_target_chars=self.daily_target_spin.value()),
        )

    def set_metadata(self, metadata: NovelMetadata, current_chars: int = 0) -> None:
        self._updating = True
        self._current_chars = max(0, int(current_chars))

        self.title_edit.setText(metadata.work_title)
        self.genre_edit.setText(metadata.genre)
        self.pov_edit.setText(metadata.point_of_view)
        self.setting_edit.setText(metadata.era_setting)
        self.logline_edit.setPlainText(metadata.logline)
        self.main_plot_edit.setPlainText(metadata.main_plot)
        self.sub_plot_edit.setPlainText(metadata.sub_plot)
        self.world_notes_edit.setPlainText(metadata.world_notes)
        self.glossary_notes_edit.setPlainText(metadata.glossary_notes)
        self.reference_notes_edit.setPlainText(metadata.reference_notes)
        self.daily_target_spin.setValue(metadata.progress_goals.daily_target_chars)

        self.characters_table.setRowCount(0)
        for row, item in enumerate(metadata.characters):
            self.characters_table.insertRow(row)
            values = [item.name, item.role, item.goal, item.conflict, item.notes]
            for col, value in enumerate(values):
                self.characters_table.setItem(row, col, QTableWidgetItem(value))

        self.chapters_table.setRowCount(0)
        for row, item in enumerate(metadata.chapters):
            self.chapters_table.insertRow(row)
            values = [str(item.number), item.title, item.purpose, item.summary, str(item.target_chars)]
            for col, value in enumerate(values):
                self.chapters_table.setItem(row, col, QTableWidgetItem(value))

        self._updating = False
        self._update_progress_labels()

    def _update_progress_labels(self) -> None:
        target = self.daily_target_spin.value()
        current = self._current_chars
        rate = (current / target * 100.0) if target > 0 else 0.0
        remaining = max(0, target - current)
        pages = current / 400.0

        self.current_chars_label.setText(f"{current}")
        self.achieve_rate_label.setText(f"{rate:.1f}%" if target > 0 else self._t("目標未設定", "No target"))
        self.remaining_label.setText(f"{remaining}" if target > 0 else "-")
        self.pages_estimate_label.setText(f"{pages:.2f}")

    def _on_any_changed(self, *_args) -> None:
        if self._updating:
            return
        self._update_progress_labels()
        self.metadataChanged.emit(self.metadata())
