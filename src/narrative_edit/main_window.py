from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Optional

from PySide6.QtCore import QMarginsF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCloseEvent, QDragEnterEvent, QDropEvent, QFont, QIcon, QKeySequence, QPageLayout, QPageSize, QPainter, QPdfWriter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSplitter,
    QStatusBar,
    QStyle,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config_store import LEGACY_APP_NAME, clear_sessions, load_config, load_sessions, remove_session, save_config, save_session
from .editor import EditorTab
from .models import DocumentState, NewlineMode, NovelMetadata
from .novel_info_panel import NovelInfoPanel
from .search_bar import SearchBar
from .vertical_editor import LINE_END_PROHIBITED, LINE_HEAD_PROHIBITED, VERTICAL_GLYPH_MAP


@dataclass
class _SubmissionUnit:
    gcol: int
    row: int
    text: str
    kind: str


class _WorkspaceFileTree(QTreeWidget):
    directoryDropped = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setHeaderHidden(True)
        self.setColumnCount(1)

    def _extract_directory_from_event(self, event) -> Optional[str]:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir():
                return str(path)
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        directory = self._extract_directory_from_event(event)
        if directory:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        directory = self._extract_directory_from_event(event)
        if directory:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        directory = self._extract_directory_from_event(event)
        if directory:
            self.directoryDropped.emit(directory)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, restore_sessions: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("Narrative_Edit")
        self.resize(1320, 820)

        self.config = load_config()
        self.ui_language = self._normalize_language(self.config.get("ui_language", "ja"))
        self.ui_theme = self._normalize_theme(self.config.get("ui_theme", "soft_light"))
        self.config["ui_language"] = self.ui_language
        self.config["ui_theme"] = self.ui_theme

        self._untitled_counter = 1
        self._editor_by_tab_id: dict[str, EditorTab] = {}
        self._info_panel_last_expanded_width = 360
        self._child_windows: list["MainWindow"] = []
        self._workspace_dir: Optional[Path] = None
        self._workspace_text_files: list[Path] = []
        self._workspace_search_result_limit = 200
        self._workspace_panel_last_expanded_width = max(220, min(620, int(self.config.get("workspace_sidebar_width", 300))))
        self._workspace_sidebar_expanded = bool(self.config.get("workspace_sidebar_expanded", True))
        self._workspace_active_panel = self._normalize_workspace_panel(self.config.get("workspace_active_panel", "explorer"))

        self._file_menu: Optional[QMenu] = None
        self._recent_menu: Optional[QMenu] = None
        self._edit_menu: Optional[QMenu] = None
        self._view_menu: Optional[QMenu] = None
        self._settings_menu: Optional[QMenu] = None
        self._language_menu: Optional[QMenu] = None
        self._theme_menu: Optional[QMenu] = None

        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._apply_ui_texts()
        self._apply_theme()
        self._bind_shortcuts()
        self._setup_autosave()
        self._restore_workspace_if_available()
        if restore_sessions:
            self._restore_sessions_if_available()

        if self.tab_widget.count() == 0:
            self.new_tab()

    def _build_ui(self) -> None:
        self.tab_widget = QTabWidget(self)
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab_at)
        self.tab_widget.currentChanged.connect(self._on_current_tab_changed)
        self.tab_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_widget.customContextMenuRequested.connect(self._open_tab_context_menu)
        self.new_window_tab_button = QPushButton(self.tab_widget)
        self.new_window_tab_button.setProperty("tabCornerButton", True)
        self.new_window_tab_button.setFocusPolicy(Qt.NoFocus)
        self.new_window_tab_button.clicked.connect(self.open_new_window)
        self.tab_widget.setCornerWidget(self.new_window_tab_button, Qt.TopRightCorner)

        self.search_bar = SearchBar(self)
        self.search_bar.set_language(self.ui_language)
        self.search_bar.findRequested.connect(self.find_in_current_editor)
        self.search_bar.hideRequested.connect(self.hide_search_bar)

        left_container = QWidget(self)
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.tab_widget, 1)
        left_layout.addWidget(self.search_bar, 0)

        self.activity_bar = QWidget(self)
        self.activity_bar.setObjectName("activity_bar")
        activity_layout = QVBoxLayout(self.activity_bar)
        activity_layout.setContentsMargins(4, 8, 4, 8)
        activity_layout.setSpacing(8)

        self.activity_explorer_button = QPushButton(self.activity_bar)
        self.activity_explorer_button.setProperty("activityButton", True)
        self.activity_search_button = QPushButton(self.activity_bar)
        self.activity_search_button.setProperty("activityButton", True)
        for button in (self.activity_explorer_button, self.activity_search_button):
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setFixedSize(34, 34)
            activity_layout.addWidget(button, 0, Qt.AlignTop)
        activity_layout.addStretch(1)

        activity_group = QButtonGroup(self)
        activity_group.setExclusive(True)
        activity_group.addButton(self.activity_explorer_button)
        activity_group.addButton(self.activity_search_button)
        self.activity_explorer_button.clicked.connect(lambda checked=False: self._on_workspace_activity_clicked("explorer"))
        self.activity_search_button.clicked.connect(lambda checked=False: self._on_workspace_activity_clicked("search"))

        explorer_page = QWidget(self)
        explorer_layout = QVBoxLayout(explorer_page)
        explorer_layout.setContentsMargins(12, 12, 12, 12)
        explorer_layout.setSpacing(8)

        self.explorer_title_label = QLabel(explorer_page)
        self.explorer_title_label.setObjectName("workspace_header")
        self.workspace_path_label = QLabel(explorer_page)
        self.workspace_path_label.setObjectName("workspace_path_label")
        self.workspace_path_label.setWordWrap(True)

        explorer_button_row = QWidget(explorer_page)
        explorer_button_row_layout = QHBoxLayout(explorer_button_row)
        explorer_button_row_layout.setContentsMargins(0, 0, 0, 0)
        explorer_button_row_layout.setSpacing(6)
        self.workspace_open_button = QPushButton(explorer_button_row)
        self.workspace_open_button.clicked.connect(self.open_workspace_directory_dialog)
        self.workspace_create_text_button = QPushButton(explorer_button_row)
        self.workspace_create_text_button.clicked.connect(self.create_workspace_text_file)
        explorer_button_row_layout.addWidget(self.workspace_open_button, 1)
        explorer_button_row_layout.addWidget(self.workspace_create_text_button, 1)

        self.workspace_export_pdf_button = QPushButton(explorer_page)
        self.workspace_export_pdf_button.clicked.connect(self.export_workspace_submission_pdf)

        self.workspace_drop_hint_label = QLabel(explorer_page)
        self.workspace_drop_hint_label.setObjectName("workspace_hint_label")
        self.workspace_drop_hint_label.setWordWrap(True)

        self.workspace_file_list = _WorkspaceFileTree(explorer_page)
        self.workspace_file_list.setObjectName("workspace_file_list")
        self.workspace_file_list.directoryDropped.connect(self._on_workspace_directory_dropped)
        self.workspace_file_list.itemActivated.connect(self._on_workspace_tree_item_activated)
        self.workspace_file_list.itemClicked.connect(self._on_workspace_tree_item_clicked)

        self.workspace_file_count_label = QLabel(explorer_page)
        self.workspace_file_count_label.setObjectName("workspace_hint_label")

        explorer_layout.addWidget(self.explorer_title_label, 0)
        explorer_layout.addWidget(self.workspace_path_label, 0)
        explorer_layout.addWidget(explorer_button_row, 0)
        explorer_layout.addWidget(self.workspace_export_pdf_button, 0)
        explorer_layout.addWidget(self.workspace_drop_hint_label, 0)
        explorer_layout.addWidget(self.workspace_file_list, 1)
        explorer_layout.addWidget(self.workspace_file_count_label, 0)

        search_page = QWidget(self)
        search_layout = QVBoxLayout(search_page)
        search_layout.setContentsMargins(12, 12, 12, 12)
        search_layout.setSpacing(8)

        self.workspace_search_title_label = QLabel(search_page)
        self.workspace_search_title_label.setObjectName("workspace_header")

        search_input_row = QWidget(search_page)
        search_input_row_layout = QHBoxLayout(search_input_row)
        search_input_row_layout.setContentsMargins(0, 0, 0, 0)
        search_input_row_layout.setSpacing(6)
        self.workspace_search_input = QLineEdit(search_input_row)
        self.workspace_search_input.returnPressed.connect(self.search_workspace_files)
        self.workspace_search_button = QPushButton(search_input_row)
        self.workspace_search_button.clicked.connect(self.search_workspace_files)
        search_input_row_layout.addWidget(self.workspace_search_input, 1)
        search_input_row_layout.addWidget(self.workspace_search_button, 0)

        self.workspace_search_results = QListWidget(search_page)
        self.workspace_search_results.setObjectName("workspace_search_results")
        self.workspace_search_results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.workspace_search_results.itemActivated.connect(self._open_workspace_search_item)
        self.workspace_search_results.itemClicked.connect(self._open_workspace_search_item)

        self.workspace_search_result_label = QLabel(search_page)
        self.workspace_search_result_label.setObjectName("workspace_hint_label")
        self.workspace_search_result_label.setWordWrap(True)

        search_layout.addWidget(self.workspace_search_title_label, 0)
        search_layout.addWidget(search_input_row, 0)
        search_layout.addWidget(self.workspace_search_results, 1)
        search_layout.addWidget(self.workspace_search_result_label, 0)

        self.workspace_stack = QStackedWidget(self)
        self.workspace_stack.setObjectName("workspace_stack")
        self.workspace_stack.addWidget(explorer_page)
        self.workspace_stack.addWidget(search_page)

        self.workspace_sidebar = QWidget(self)
        self.workspace_sidebar.setObjectName("workspace_sidebar")
        workspace_sidebar_layout = QHBoxLayout(self.workspace_sidebar)
        workspace_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        workspace_sidebar_layout.setSpacing(0)
        workspace_sidebar_layout.addWidget(self.activity_bar, 0)
        workspace_sidebar_layout.addWidget(self.workspace_stack, 1)
        self.workspace_sidebar.setMinimumWidth(44)
        self.workspace_sidebar.setMaximumWidth(380)

        self.info_panel = NovelInfoPanel(language=self.ui_language, theme=self.ui_theme, parent=self)
        self.info_panel.setMinimumWidth(320)
        self.info_panel.setMaximumWidth(420)
        self.info_panel.metadataChanged.connect(self._on_info_metadata_changed)
        self.info_panel.sectionStateChanged.connect(self._on_info_section_state_changed)
        self.info_panel.panelExpandedChanged.connect(self._on_info_panel_expanded_changed)
        self.info_panel.set_panel_expanded(bool(self.config.get("plot_panel_expanded", True)))
        self.info_panel.set_section_states(self.config.get("plot_panel_sections", {}))
        self.config["plot_panel_expanded"] = self.info_panel.panel_expanded()
        self.config["plot_panel_sections"] = self.info_panel.section_states()

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.addWidget(left_container)
        self.splitter.addWidget(self.info_panel)
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([940, 360])
        self._apply_info_panel_expanded_layout(self.info_panel.panel_expanded())

        self.root_splitter = QSplitter(Qt.Horizontal, self)
        self.root_splitter.setObjectName("workspace_root_splitter")
        self.root_splitter.setCollapsible(0, False)
        self.root_splitter.setCollapsible(1, False)
        self.root_splitter.addWidget(self.workspace_sidebar)
        self.root_splitter.addWidget(self.splitter)
        self.root_splitter.setStretchFactor(0, 0)
        self.root_splitter.setStretchFactor(1, 1)
        self.root_splitter.splitterMoved.connect(self._on_root_splitter_moved)
        self.setCentralWidget(self.root_splitter)

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.statusBar().showMessage("")

        self._apply_workspace_activity_icons()
        self._switch_workspace_panel(self._workspace_active_panel)
        self._apply_workspace_sidebar_expanded_layout(self._workspace_sidebar_expanded, persist=False)

    def _build_actions(self) -> None:
        self.action_new = QAction("", self)
        self.action_new.setShortcut(QKeySequence("Ctrl+T"))
        self.action_new.triggered.connect(self.new_tab)

        self.action_new_window = QAction("", self)
        self.action_new_window.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.action_new_window.triggered.connect(self.open_new_window)

        self.action_open = QAction("", self)
        self.action_open.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open.triggered.connect(self.open_file_dialog)

        self.action_open_workspace = QAction("", self)
        self.action_open_workspace.triggered.connect(self.open_workspace_directory_dialog)

        self.action_save = QAction("", self)
        self.action_save.setShortcut(QKeySequence("Ctrl+S"))
        self.action_save.triggered.connect(self.save_current_tab)

        self.action_save_as = QAction("", self)
        self.action_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.action_save_as.triggered.connect(self.save_current_tab_as)

        self.action_export_submission_pdf = QAction("", self)
        self.action_export_submission_pdf.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.action_export_submission_pdf.triggered.connect(self.export_submission_pdf_current_tab)

        self.action_export_workspace_pdf = QAction("", self)
        self.action_export_workspace_pdf.triggered.connect(self.export_workspace_submission_pdf)
        self.action_export_workspace_pdf.setEnabled(False)

        self.action_save_plot = QAction("", self)
        self.action_save_plot.triggered.connect(self.save_plot_for_current_tab)

        self.action_load_plot = QAction("", self)
        self.action_load_plot.triggered.connect(self.load_plot_for_current_tab)

        self.action_close_tab = QAction("", self)
        self.action_close_tab.setShortcut(QKeySequence("Ctrl+W"))
        self.action_close_tab.triggered.connect(self.close_current_tab)

        self.action_exit = QAction("", self)
        self.action_exit.triggered.connect(self.close)

        self.action_undo = QAction("", self)
        self.action_undo.setShortcut(QKeySequence.Undo)
        self.action_undo.triggered.connect(self.undo_current)

        self.action_redo = QAction("", self)
        self.action_redo.setShortcut(QKeySequence.Redo)
        self.action_redo.triggered.connect(self.redo_current)

        self.action_find = QAction("", self)
        self.action_find.setShortcut(QKeySequence.Find)
        self.action_find.triggered.connect(self.open_search_bar)

        self.action_font_size = QAction("", self)
        self.action_font_size.triggered.connect(self.change_font_size)

        self.action_grid_rows = QAction("", self)
        self.action_grid_rows.triggered.connect(self.change_grid_rows)

        self.action_grid_cols = QAction("", self)
        self.action_grid_cols.triggered.connect(self.change_grid_cols)

        self.action_show_grid = QAction("", self, checkable=True)
        self.action_show_grid.setChecked(bool(self.config.get("show_manuscript_grid", True)))
        self.action_show_grid.triggered.connect(self.toggle_show_grid)

        self.action_autosave = QAction("", self, checkable=True)
        self.action_autosave.setChecked(bool(self.config.get("autosave_enabled", True)))
        self.action_autosave.triggered.connect(self.toggle_autosave)

        self.action_autosave_interval = QAction("", self)
        self.action_autosave_interval.triggered.connect(self.change_autosave_interval)

        self.action_lang_ja = QAction("日本語", self, checkable=True)
        self.action_lang_en = QAction("English", self, checkable=True)
        self.action_theme_light = QAction("", self, checkable=True)
        self.action_theme_dark = QAction("", self, checkable=True)

        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        language_group.addAction(self.action_lang_ja)
        language_group.addAction(self.action_lang_en)
        self.action_lang_ja.setChecked(self.ui_language == "ja")
        self.action_lang_en.setChecked(self.ui_language == "en")
        self.action_lang_ja.triggered.connect(lambda checked: self._set_language("ja") if checked else None)
        self.action_lang_en.triggered.connect(lambda checked: self._set_language("en") if checked else None)

        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        theme_group.addAction(self.action_theme_light)
        theme_group.addAction(self.action_theme_dark)
        self.action_theme_light.setChecked(self.ui_theme == "soft_light")
        self.action_theme_dark.setChecked(self.ui_theme == "soft_dark")
        self.action_theme_light.triggered.connect(lambda checked: self._set_theme("soft_light") if checked else None)
        self.action_theme_dark.triggered.connect(lambda checked: self._set_theme("soft_dark") if checked else None)

    def _build_menus(self) -> None:
        self._file_menu = self.menuBar().addMenu("")
        self._file_menu.addAction(self.action_new)
        self._file_menu.addAction(self.action_new_window)
        self._file_menu.addAction(self.action_open)
        self._file_menu.addAction(self.action_open_workspace)
        self._file_menu.addSeparator()
        self._file_menu.addAction(self.action_save)
        self._file_menu.addAction(self.action_save_as)
        self._file_menu.addAction(self.action_export_submission_pdf)
        self._file_menu.addAction(self.action_export_workspace_pdf)
        self._file_menu.addSeparator()
        self._file_menu.addAction(self.action_save_plot)
        self._file_menu.addAction(self.action_load_plot)
        self._file_menu.addSeparator()

        self._recent_menu = self._file_menu.addMenu("")
        self._rebuild_recent_files_menu()

        self._file_menu.addSeparator()
        self._file_menu.addAction(self.action_close_tab)
        self._file_menu.addSeparator()
        self._file_menu.addAction(self.action_exit)

        self._edit_menu = self.menuBar().addMenu("")
        self._edit_menu.addAction(self.action_undo)
        self._edit_menu.addAction(self.action_redo)
        self._edit_menu.addSeparator()
        self._edit_menu.addAction(self.action_find)

        self._view_menu = self.menuBar().addMenu("")
        self._view_menu.addAction(self.action_font_size)
        self._view_menu.addAction(self.action_grid_rows)
        self._view_menu.addAction(self.action_grid_cols)
        self._view_menu.addAction(self.action_show_grid)

        self._settings_menu = self.menuBar().addMenu("")
        self._settings_menu.addAction(self.action_autosave)
        self._settings_menu.addAction(self.action_autosave_interval)
        self._settings_menu.addSeparator()
        self._language_menu = self._settings_menu.addMenu("")
        self._language_menu.addAction(self.action_lang_ja)
        self._language_menu.addAction(self.action_lang_en)
        self._theme_menu = self._settings_menu.addMenu("")
        self._theme_menu.addAction(self.action_theme_light)
        self._theme_menu.addAction(self.action_theme_dark)

    def _normalize_language(self, language: object) -> str:
        return "en" if language == "en" else "ja"

    def _normalize_theme(self, theme: object) -> str:
        return "soft_dark" if theme == "soft_dark" else "soft_light"

    def _normalize_workspace_panel(self, panel: object) -> str:
        return "search" if panel == "search" else "explorer"

    def _t(self, ja: str, en: str) -> str:
        return ja if self.ui_language == "ja" else en

    def _set_language(self, language: str) -> None:
        normalized = self._normalize_language(language)
        if normalized == self.ui_language:
            return
        self.ui_language = normalized
        self.config["ui_language"] = normalized
        self._apply_ui_texts()
        self.info_panel.set_language(self.ui_language)
        save_config(self.config)

    def _set_theme(self, theme_name: str) -> None:
        normalized = self._normalize_theme(theme_name)
        if normalized == self.ui_theme:
            return
        self.ui_theme = normalized
        self.config["ui_theme"] = normalized
        self._apply_theme()
        save_config(self.config)

    def _apply_ui_texts(self) -> None:
        self.search_bar.set_language(self.ui_language)
        self.info_panel.set_language(self.ui_language)

        self.action_new.setText(self._t("新しいタブ", "New Tab"))
        self.action_new_window.setText(self._t("新しいウィンドウ", "New Window"))
        self.action_open.setText(self._t("開く...", "Open..."))
        self.action_open_workspace.setText(self._t("作業フォルダを開く...", "Open Workspace Folder..."))
        self.action_save.setText(self._t("保存", "Save"))
        self.action_save_as.setText(self._t("名前を付けて保存...", "Save As..."))
        self.action_export_submission_pdf.setText(self._t("PDFを書き出し...", "Export PDF..."))
        self.action_export_workspace_pdf.setText(
            self._t("作業フォルダのテキストを結合してPDFを書き出し...", "Export Workspace Texts to PDF...")
        )
        self.action_save_plot.setText(self._t("プロットを保存...", "Save Plot..."))
        self.action_load_plot.setText(self._t("プロットを読み込み...", "Load Plot..."))
        self.action_close_tab.setText(self._t("タブを閉じる", "Close Tab"))
        self.action_exit.setText(self._t("終了", "Exit"))
        self.action_undo.setText(self._t("元に戻す", "Undo"))
        self.action_redo.setText(self._t("やり直し", "Redo"))
        self.action_find.setText(self._t("検索", "Find"))
        self.action_font_size.setText(self._t("フォントサイズ...", "Font Size..."))
        self.action_grid_rows.setText(self._t("原稿用紙の行数...", "Grid Rows..."))
        self.action_grid_cols.setText(self._t("原稿用紙の列数...", "Grid Columns..."))
        self.action_show_grid.setText(self._t("マス目を表示", "Show Grid"))
        self.action_autosave.setText(self._t("自動保存", "Autosave"))
        self.action_autosave_interval.setText(self._t("自動保存間隔...", "Autosave Interval..."))
        self.action_theme_light.setText(self._t("ウォームライト", "Warm Light"))
        self.action_theme_dark.setText(self._t("ダークグレー", "Soft Dark"))

        self.new_window_tab_button.setText(self._t("新しいウィンドウ", "New Window"))
        self.new_window_tab_button.setToolTip(self.action_new_window.text())
        self.activity_explorer_button.setToolTip(self._t("エクスプローラ", "Explorer"))
        self.activity_search_button.setToolTip(self._t("検索", "Search"))
        self._apply_workspace_activity_icons()
        self.activity_explorer_button.setAccessibleName(self._t("エクスプローラ", "Explorer"))
        self.activity_search_button.setAccessibleName(self._t("検索", "Search"))
        self.explorer_title_label.setText(self._t("エクスプローラ", "Explorer"))
        self.workspace_search_title_label.setText(self._t("検索", "Search"))
        self.workspace_open_button.setText(self._t("フォルダを開く", "Open Folder"))
        self.workspace_create_text_button.setText(self._t("新規テキスト", "New Text"))
        self.workspace_export_pdf_button.setText(self._t("結合PDFを書き出し", "Export Combined PDF"))
        self.workspace_drop_hint_label.setText(
            self._t("フォルダをドラッグ&ドロップして作業フォルダにできます。", "Drop a folder here to set workspace.")
        )
        self.workspace_search_input.setPlaceholderText(self._t("ファイル名または本文を検索", "Search file name or content"))
        self.workspace_search_button.setText(self._t("検索", "Search"))

        if self._file_menu is not None:
            self._file_menu.setTitle(self._t("ファイル", "File"))
        if self._recent_menu is not None:
            self._recent_menu.setTitle(self._t("最近開いたファイル", "Recent Files"))
        if self._edit_menu is not None:
            self._edit_menu.setTitle(self._t("編集", "Edit"))
        if self._view_menu is not None:
            self._view_menu.setTitle(self._t("表示", "View"))
        if self._settings_menu is not None:
            self._settings_menu.setTitle(self._t("設定", "Settings"))
        if self._language_menu is not None:
            self._language_menu.setTitle(self._t("言語", "Language"))
        if self._theme_menu is not None:
            self._theme_menu.setTitle(self._t("テーマ", "Theme"))

        self._update_workspace_labels()
        self._update_workspace_action_state()
        self._refresh_status()

    def _apply_theme(self) -> None:
        if self.ui_theme == "soft_dark":
            palette = {
                "window_bg": "#20262e",
                "surface_bg": "#2a313b",
                "tab_bg": "#323b47",
                "tab_hover": "#3a4553",
                "border": "#404b5a",
                "text": "#dce3ec",
                "input_bg": "#37404c",
                "input_border": "#4b5869",
                "input_text": "#dce3ec",
                "scroll_track": "#2a313b",
                "scroll_handle": "#556172",
                "scroll_handle_hover": "#647184",
            }
        else:
            palette = {
                "window_bg": "#f3e9de",
                "surface_bg": "#f7eee4",
                "tab_bg": "#eedfce",
                "tab_hover": "#e4d2bf",
                "border": "#d8c5b2",
                "text": "#3a2d24",
                "input_bg": "#f8efe6",
                "input_border": "#d8c5b2",
                "input_text": "#3a2d24",
                "scroll_track": "#f1e4d6",
                "scroll_handle": "#cfb8a2",
                "scroll_handle_hover": "#c3a88f",
            }

        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {palette["window_bg"]};
                color: {palette["text"]};
            }}
            QStatusBar, QMenuBar {{
                background: {palette["surface_bg"]};
                color: {palette["text"]};
                border-top: 1px solid {palette["border"]};
            }}
            QMenuBar::item:selected {{
                background: {palette["tab_hover"]};
            }}
            QMenu {{
                background: {palette["surface_bg"]};
                color: {palette["text"]};
                border: 1px solid {palette["border"]};
            }}
            QMenu::item:selected {{
                background: {palette["tab_hover"]};
            }}
            QTabWidget::pane {{
                background: {palette["surface_bg"]};
                border: 1px solid {palette["border"]};
            }}
            QTabBar::tab {{
                background: {palette["tab_bg"]};
                color: {palette["text"]};
                border: 1px solid {palette["border"]};
                border-bottom: none;
                padding: 6px 10px;
            }}
            QTabBar::tab:selected {{
                background: {palette["surface_bg"]};
            }}
            QTabBar::tab:hover {{
                background: {palette["tab_hover"]};
            }}
            QPushButton[tabCornerButton="true"] {{
                min-height: 22px;
                padding: 3px 8px;
                margin: 1px;
            }}
            QWidget#workspace_sidebar {{
                background: {palette["surface_bg"]};
                border-right: 1px solid {palette["border"]};
            }}
            QWidget#activity_bar {{
                background: {palette["tab_bg"]};
                border-right: 1px solid {palette["border"]};
            }}
            QPushButton[activityButton="true"] {{
                background: transparent;
                border: 1px solid transparent;
                font-weight: bold;
                padding: 0;
            }}
            QPushButton[activityButton="true"]:hover {{
                background: {palette["tab_hover"]};
                border: 1px solid {palette["border"]};
            }}
            QPushButton[activityButton="true"]:checked {{
                background: {palette["surface_bg"]};
                border: 1px solid {palette["border"]};
            }}
            QLabel#workspace_header {{
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                color: {palette["text"]};
            }}
            QLabel#workspace_path_label, QLabel#workspace_hint_label {{
                color: {palette["text"]};
            }}
            QTreeWidget#workspace_file_list, QListWidget#workspace_search_results {{
                background: {palette["input_bg"]};
                color: {palette["input_text"]};
                border: 1px solid {palette["input_border"]};
            }}
            QTreeWidget#workspace_file_list::item:selected, QListWidget#workspace_search_results::item:selected {{
                background: {palette["tab_hover"]};
                color: {palette["text"]};
            }}
            QLineEdit, QPushButton, QSpinBox {{
                background: {palette["input_bg"]};
                color: {palette["input_text"]};
                border: 1px solid {palette["input_border"]};
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background: {palette["tab_hover"]};
            }}
            QCheckBox {{
                color: {palette["text"]};
            }}
            QSplitter::handle {{
                background: {palette["border"]};
                width: 1px;
            }}
            QSplitter#workspace_root_splitter::handle {{
                width: 6px;
            }}
            QScrollBar:vertical {{
                background: {palette["scroll_track"]};
                width: 12px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {palette["scroll_handle"]};
                min-height: 28px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {palette["scroll_handle_hover"]};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                background: {palette["scroll_track"]};
                height: 12px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {palette["scroll_handle"]};
                min-width: 28px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {palette["scroll_handle_hover"]};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
            """
        )

        for editor_tab in self._iter_editor_tabs():
            editor_tab.set_theme(self.ui_theme)
        self.info_panel.set_theme(self.ui_theme)
        self._apply_workspace_activity_icons()

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=self.switch_to_next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=self.switch_to_previous_tab)

    def _setup_autosave(self) -> None:
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave_dirty_tabs)
        self._apply_autosave_timer_settings()

    def _apply_autosave_timer_settings(self) -> None:
        enabled = bool(self.config.get("autosave_enabled", True))
        interval = int(self.config.get("autosave_interval_sec", 5))
        interval = max(2, interval)
        self.config["autosave_interval_sec"] = interval

        if enabled:
            self.autosave_timer.start(interval * 1000)
        else:
            self.autosave_timer.stop()
        save_config(self.config)

    def open_new_window(self) -> None:
        child = MainWindow(restore_sessions=False)
        self._child_windows.append(child)
        child.destroyed.connect(lambda _obj=None, w=child: self._on_child_window_destroyed(w))
        child.show()

    def _on_child_window_destroyed(self, child: "MainWindow") -> None:
        self._child_windows = [window for window in self._child_windows if window is not child]

    def _theme_icon(self, theme_name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        icon = QIcon.fromTheme(theme_name)
        if icon.isNull():
            icon = self.style().standardIcon(fallback)
        return icon

    def _apply_workspace_activity_icons(self) -> None:
        icon_size = QSize(18, 18)
        self.activity_explorer_button.setIcon(self._theme_icon("folder-open", QStyle.SP_DirOpenIcon))
        self.activity_search_button.setIcon(self._theme_icon("edit-find", QStyle.SP_FileDialogContentsView))
        self.activity_explorer_button.setIconSize(icon_size)
        self.activity_search_button.setIconSize(icon_size)
        self.activity_explorer_button.setText("")
        self.activity_search_button.setText("")

    def _on_workspace_activity_clicked(self, panel: str) -> None:
        normalized = self._normalize_workspace_panel(panel)
        if normalized == self._workspace_active_panel:
            self._apply_workspace_sidebar_expanded_layout(not self._workspace_sidebar_expanded)
            return

        self._workspace_active_panel = normalized
        self._switch_workspace_panel(normalized, focus_search=True)
        self._apply_workspace_sidebar_expanded_layout(True)

    def _on_root_splitter_moved(self, _pos: int, _index: int) -> None:
        if not self._workspace_sidebar_expanded:
            return
        sizes = self.root_splitter.sizes()
        if len(sizes) != 2:
            return
        width = int(sizes[0])
        if width < 220:
            return
        self._workspace_panel_last_expanded_width = max(220, min(620, width))
        self.config["workspace_sidebar_width"] = int(self._workspace_panel_last_expanded_width)

    def _switch_workspace_panel(self, panel: str, focus_search: bool = False) -> None:
        normalized = self._normalize_workspace_panel(panel)
        self._workspace_active_panel = normalized
        if normalized == "search":
            self.workspace_stack.setCurrentIndex(1)
            self.activity_search_button.setChecked(True)
            self.activity_explorer_button.setChecked(False)
            if focus_search and self._workspace_sidebar_expanded:
                self.workspace_search_input.setFocus()
            return

        self.workspace_stack.setCurrentIndex(0)
        self.activity_explorer_button.setChecked(True)
        self.activity_search_button.setChecked(False)

    def _apply_workspace_sidebar_expanded_layout(self, expanded: bool, persist: bool = True) -> None:
        expanded = bool(expanded)
        if not expanded:
            sizes = self.root_splitter.sizes()
            if len(sizes) == 2 and sizes[0] >= 220:
                self._workspace_panel_last_expanded_width = sizes[0]

        if expanded:
            width = max(220, min(620, int(self._workspace_panel_last_expanded_width)))
            self.workspace_stack.setVisible(True)
            self.workspace_sidebar.setMinimumWidth(220)
            self.workspace_sidebar.setMaximumWidth(620)
            self.workspace_sidebar.updateGeometry()
            self._switch_workspace_panel(
                self._workspace_active_panel,
                focus_search=(self._workspace_active_panel == "search"),
            )
            sizes = self.root_splitter.sizes()
            total = max(1, sum(sizes)) if len(sizes) == 2 else max(1, self.width())
            self.root_splitter.setSizes([width, max(1, total - width)])
        else:
            self.workspace_stack.setVisible(False)
            collapsed_width = max(44, self.activity_bar.sizeHint().width() + 2)
            self.workspace_sidebar.setMinimumWidth(collapsed_width)
            self.workspace_sidebar.setMaximumWidth(collapsed_width)
            self.workspace_sidebar.updateGeometry()
            sizes = self.root_splitter.sizes()
            total = max(1, sum(sizes)) if len(sizes) == 2 else max(1, self.width())
            self.root_splitter.setSizes([collapsed_width, max(1, total - collapsed_width)])

        self._workspace_sidebar_expanded = expanded
        if persist:
            self.config["workspace_sidebar_expanded"] = expanded
            self.config["workspace_sidebar_width"] = int(self._workspace_panel_last_expanded_width)
            self.config["workspace_active_panel"] = self._workspace_active_panel
            save_config(self.config)

    def _restore_workspace_if_available(self) -> None:
        self._workspace_active_panel = self._normalize_workspace_panel(self.config.get("workspace_active_panel", self._workspace_active_panel))
        self._workspace_sidebar_expanded = bool(self.config.get("workspace_sidebar_expanded", self._workspace_sidebar_expanded))
        self._workspace_panel_last_expanded_width = max(
            220,
            min(620, int(self.config.get("workspace_sidebar_width", self._workspace_panel_last_expanded_width))),
        )
        self._switch_workspace_panel(self._workspace_active_panel)
        self._apply_workspace_sidebar_expanded_layout(self._workspace_sidebar_expanded, persist=False)

        raw_path = self.config.get("workspace_directory")
        if isinstance(raw_path, str) and raw_path.strip():
            restored = self.set_workspace_directory(raw_path.strip(), show_feedback=False)
            if restored:
                return
            self.config["workspace_directory"] = ""
            save_config(self.config)
        self._workspace_dir = None
        self._refresh_workspace_file_list()

    def open_workspace_directory_dialog(self) -> None:
        start_path = str(self._workspace_dir or Path.cwd())
        directory = QFileDialog.getExistingDirectory(
            self,
            self._t("作業フォルダを選択", "Select Workspace Folder"),
            start_path,
        )
        if not directory:
            return
        self.set_workspace_directory(directory)

    def _on_workspace_directory_dropped(self, directory: str) -> None:
        self.set_workspace_directory(directory)

    def set_workspace_directory(self, directory: str, show_feedback: bool = True) -> bool:
        candidate = Path(directory).expanduser()
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate

        if not resolved.exists() or not resolved.is_dir():
            if show_feedback:
                QMessageBox.warning(
                    self,
                    self._t("フォルダエラー", "Directory Error"),
                    self._t("指定されたフォルダを利用できません。", "The selected directory is not available."),
                )
            return False

        self._workspace_dir = resolved
        self.config["workspace_directory"] = str(resolved)
        save_config(self.config)
        self._refresh_workspace_file_list()
        self.workspace_search_results.clear()
        self.workspace_search_result_label.setText(
            self._t("検索語を入力して実行してください。", "Enter query and run search.")
        )

        if show_feedback:
            self.statusBar().showMessage(
                self._t(f"作業フォルダを設定しました: {resolved}", f"Workspace set: {resolved}"),
                3000,
            )
        return True

    def _workspace_contains_path(self, path: Path) -> bool:
        if self._workspace_dir is None:
            return False
        try:
            path.resolve().relative_to(self._workspace_dir.resolve())
            return True
        except Exception:
            return False

    def _is_workspace_text_file(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".text", ".md"}

    def _is_workspace_hidden_dir(self, path: Path) -> bool:
        name = path.name
        return name.startswith(".") or name in {"__pycache__", ".git"}

    def _populate_workspace_tree(self, parent_item: QTreeWidgetItem, directory: Path) -> None:
        entries: list[Path] = []
        try:
            entries = list(directory.iterdir())
        except Exception:
            return
        entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

        for entry in entries:
            if entry.is_dir():
                if self._is_workspace_hidden_dir(entry):
                    continue
                dir_item = QTreeWidgetItem([entry.name])
                dir_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                dir_item.setData(0, Qt.UserRole, str(entry))
                dir_item.setData(0, Qt.UserRole + 1, "dir")
                parent_item.addChild(dir_item)
                self._populate_workspace_tree(dir_item, entry)
                continue

            if not entry.is_file() or not self._is_workspace_text_file(entry):
                continue
            file_item = QTreeWidgetItem([entry.name])
            file_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
            file_item.setData(0, Qt.UserRole, str(entry))
            file_item.setData(0, Qt.UserRole + 1, "file")
            file_item.setToolTip(0, str(entry))
            parent_item.addChild(file_item)
            self._workspace_text_files.append(entry)

    def _refresh_workspace_file_list(self) -> None:
        self.workspace_file_list.clear()
        self._workspace_text_files = []

        if self._workspace_dir and self._workspace_dir.exists():
            try:
                root_name = self._workspace_dir.name or str(self._workspace_dir)
                root_item = QTreeWidgetItem([root_name])
                root_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirOpenIcon))
                root_item.setData(0, Qt.UserRole, str(self._workspace_dir))
                root_item.setData(0, Qt.UserRole + 1, "dir")
                root_item.setToolTip(0, str(self._workspace_dir))
                self.workspace_file_list.addTopLevelItem(root_item)
                self._populate_workspace_tree(root_item, self._workspace_dir)
                root_item.setExpanded(True)
                self._workspace_text_files.sort(key=lambda p: p.relative_to(self._workspace_dir).as_posix().lower())
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    self._t("フォルダ読み込みエラー", "Workspace Error"),
                    self._t(
                        f"作業フォルダの読み込みに失敗しました:\n{exc}",
                        f"Failed to read workspace folder:\n{exc}",
                    ),
                )
                self._workspace_text_files = []

        self._update_workspace_labels()
        self._update_workspace_action_state()

    def _open_workspace_file_path(self, path: str) -> None:
        if not path:
            return
        self.open_file(path)

    def _on_workspace_tree_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        self._on_workspace_tree_item_clicked(item, 0)

    def _on_workspace_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        kind = item.data(0, Qt.UserRole + 1)
        path = item.data(0, Qt.UserRole)
        if kind == "dir":
            item.setExpanded(not item.isExpanded())
            return
        if kind == "file" and isinstance(path, str):
            self._open_workspace_file_path(path)

    def _open_workspace_search_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if not isinstance(path, str) or not path:
            return
        self._open_workspace_file_path(path)

    def create_workspace_text_file(self) -> None:
        if self._workspace_dir is None:
            QMessageBox.information(
                self,
                self._t("作業フォルダ未設定", "Workspace Not Set"),
                self._t("先に作業フォルダを設定してください。", "Set workspace folder first."),
            )
            return

        name, ok = QInputDialog.getText(
            self,
            self._t("テキストファイルを作成", "Create Text File"),
            self._t("ファイル名（相対パス可）:", "File name (relative path):"),
            text="new_file.txt",
        )
        if not ok:
            return

        relative = name.strip()
        if not relative:
            return

        relative_path = Path(relative)
        if relative_path.is_absolute():
            QMessageBox.warning(
                self,
                self._t("作成エラー", "Create Error"),
                self._t("絶対パスは指定できません。", "Absolute paths are not allowed."),
            )
            return

        if relative_path.suffix == "":
            relative_path = relative_path.with_suffix(".txt")

        target = (self._workspace_dir / relative_path).resolve()
        if not self._workspace_contains_path(target):
            QMessageBox.warning(
                self,
                self._t("作成エラー", "Create Error"),
                self._t("作業フォルダの外には作成できません。", "Cannot create files outside workspace."),
            )
            return

        if target.exists():
            QMessageBox.warning(
                self,
                self._t("作成エラー", "Create Error"),
                self._t("同名ファイルがすでに存在します。", "A file with the same name already exists."),
            )
            return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("作成エラー", "Create Error"),
                self._t(f"ファイル作成に失敗しました:\n{exc}", f"Failed to create file:\n{exc}"),
            )
            return

        self._refresh_workspace_file_list()
        self.open_file(str(target))
        self.statusBar().showMessage(
            self._t(f"テキストファイルを作成しました: {target.name}", f"Text file created: {target.name}"),
            2500,
        )

    def _update_workspace_labels(self) -> None:
        if self._workspace_dir is None:
            self.workspace_path_label.setText(self._t("作業フォルダ: 未設定", "Workspace: not set"))
            self.workspace_path_label.setToolTip("")
            self.workspace_file_count_label.setText(self._t("テキストファイル: 0件", "Text files: 0"))
        else:
            workspace_name = self._workspace_dir.name or str(self._workspace_dir)
            self.workspace_path_label.setText(self._t(f"作業フォルダ: {workspace_name}", f"Workspace: {workspace_name}"))
            self.workspace_path_label.setToolTip(str(self._workspace_dir))
            self.workspace_file_count_label.setText(
                self._t(
                    f"テキストファイル: {len(self._workspace_text_files)}件",
                    f"Text files: {len(self._workspace_text_files)}",
                )
            )

        if self.workspace_search_results.count() == 0:
            if self._workspace_dir is None:
                self.workspace_search_result_label.setText(self._t("先に作業フォルダを設定してください。", "Set workspace folder first."))
            else:
                self.workspace_search_result_label.setText(self._t("検索語を入力して実行してください。", "Enter query and run search."))

    def _update_workspace_action_state(self) -> None:
        has_workspace = self._workspace_dir is not None
        self.workspace_create_text_button.setEnabled(has_workspace)
        self.workspace_search_input.setEnabled(has_workspace)
        self.workspace_search_button.setEnabled(has_workspace)
        can_export_combined = has_workspace and len(self._workspace_text_files) >= 2
        self.workspace_export_pdf_button.setEnabled(can_export_combined)
        self.action_export_workspace_pdf.setEnabled(can_export_combined)

    def search_workspace_files(self) -> None:
        self.workspace_search_results.clear()
        if self._workspace_dir is None:
            self.workspace_search_result_label.setText(self._t("先に作業フォルダを設定してください。", "Set workspace folder first."))
            return

        query = self.workspace_search_input.text().strip()
        if not query:
            self.workspace_search_result_label.setText(self._t("検索語を入力してください。", "Enter a search query."))
            return

        query_lower = query.lower()
        matches = 0
        for text_file in self._workspace_text_files:
            rel = text_file.relative_to(self._workspace_dir).as_posix()
            source = ""
            if query_lower in rel.lower():
                source = self._t("ファイル名", "name")
            else:
                try:
                    if text_file.stat().st_size > 2_000_000:
                        continue
                    raw = text_file.read_bytes()
                    body, _encoding = self._decode_with_fallback(raw)
                    if body and query_lower in body.lower():
                        source = self._t("本文", "content")
                except Exception:
                    continue

            if not source:
                continue

            parent_rel = text_file.relative_to(self._workspace_dir).parent.as_posix()
            if parent_rel in {".", ""}:
                display = f"{text_file.name} [{source}]"
            else:
                display = f"{text_file.name} ({parent_rel}) [{source}]"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, str(text_file))
            self.workspace_search_results.addItem(item)
            matches += 1
            if matches >= self._workspace_search_result_limit:
                break

        if matches == 0:
            self.workspace_search_result_label.setText(self._t("一致するテキストファイルはありません。", "No matching text files found."))
        elif matches >= self._workspace_search_result_limit:
            self.workspace_search_result_label.setText(
                self._t(
                    f"上限 {self._workspace_search_result_limit} 件まで表示しています。",
                    f"Showing first {self._workspace_search_result_limit} results.",
                )
            )
        else:
            self.workspace_search_result_label.setText(
                self._t(f"{matches} 件見つかりました。", f"{matches} result(s) found.")
            )

    def _restore_sessions_if_available(self) -> None:
        raw_sessions = load_sessions()
        sessions: list[dict] = []
        invalid_session_files: list[str] = []
        for payload in raw_sessions:
            if self._is_supported_session_payload(payload):
                sessions.append(payload)
            else:
                session_file = payload.get("_session_file")
                if isinstance(session_file, str):
                    invalid_session_files.append(session_file)

        for file_path in invalid_session_files:
            try:
                Path(file_path).unlink(missing_ok=True)
            except Exception:
                pass

        if not sessions:
            return

        result = QMessageBox.question(
            self,
            self._t("復元", "Restore Session"),
            self._t(
                f"自動保存データが {len(sessions)} 件あります。復元しますか？",
                f"{len(sessions)} autosave session(s) found. Restore them?",
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if result == QMessageBox.No:
            clear_sessions()
            return

        for payload in sessions:
            path = payload.get("path")
            display_name = payload.get("display_name")
            encoding = payload.get("encoding", "utf-8")
            newline_value = payload.get("newline", NewlineMode.LF.value)
            text = payload.get("text", "")
            is_dirty = bool(payload.get("is_dirty", True))
            session_id = payload.get("session_id")
            metadata_payload = payload.get("metadata", {})
            try:
                newline_mode = NewlineMode(newline_value)
            except Exception:
                newline_mode = NewlineMode.LF

            metadata = NovelMetadata.from_dict(metadata_payload)
            metadata_path = payload.get("metadata_path")
            plot_path = payload.get("plot_path")

            editor_tab = self._create_editor_tab(
                text=text,
                path=path,
                encoding=encoding,
                newline_mode=newline_mode,
                display_name=display_name,
                session_id=session_id,
                metadata=metadata,
                metadata_path=metadata_path,
                plot_path=plot_path,
            )
            editor_tab.editor.setModified(is_dirty)

        self.statusBar().showMessage(self._t("復元しました。", "Session restored."), 2500)

    def _is_supported_session_payload(self, payload: dict) -> bool:
        if not isinstance(payload, dict):
            return False
        if not isinstance(payload.get("text"), str):
            return False

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            return False

        app = meta.get("app")
        schema = int(meta.get("schema", 0))
        if app not in {LEGACY_APP_NAME, "Narrative_Edit"}:
            return False
        if schema not in {1, 2}:
            return False
        return True

    def new_tab(self) -> None:
        self._create_editor_tab()

    def _create_editor_tab(
        self,
        text: str = "",
        path: Optional[str] = None,
        encoding: str = "utf-8",
        newline_mode: NewlineMode = NewlineMode.LF,
        display_name: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[NovelMetadata] = None,
        metadata_path: Optional[str] = None,
        plot_path: Optional[str] = None,
    ) -> EditorTab:
        if display_name is None and not path:
            display_name = f"{self._t('無題', 'Untitled')}-{self._untitled_counter}"
            self._untitled_counter += 1

        state = DocumentState(
            path=path,
            encoding=encoding,
            newline=newline_mode,
            display_name=display_name,
            metadata=metadata or NovelMetadata(),
            metadata_path=metadata_path,
            plot_path=plot_path,
        )
        if session_id:
            state.session_id = session_id

        editor_tab = EditorTab(state=state, text=text, parent=self)
        self._apply_editor_preferences(editor_tab)

        editor_tab.cursorPositionChanged.connect(lambda _p, _c, _m: self._refresh_status())
        editor_tab.dirtyChanged.connect(lambda _dirty: self._on_editor_dirty_changed(editor_tab))
        editor_tab.characterCountChanged.connect(lambda _count: self._on_editor_character_count_changed(editor_tab))

        self._editor_by_tab_id[state.tab_id] = editor_tab
        index = self.tab_widget.addTab(editor_tab, self._tab_title_for_editor(editor_tab))
        self.tab_widget.setCurrentIndex(index)
        self._refresh_status()
        return editor_tab

    def _apply_editor_preferences(self, editor_tab: EditorTab) -> None:
        editor_tab.set_font_size(int(self.config.get("font_size", 16)))
        editor_tab.set_grid(
            int(self.config.get("manuscript_grid_rows", 40)),
            int(self.config.get("manuscript_grid_cols", 40)),
        )
        editor_tab.set_show_grid(bool(self.config.get("show_manuscript_grid", True)))
        editor_tab.set_theme(self.ui_theme)

    def _iter_editor_tabs(self) -> list[EditorTab]:
        items: list[EditorTab] = []
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if isinstance(w, EditorTab):
                items.append(w)
        return items

    def current_editor_tab(self) -> Optional[EditorTab]:
        widget = self.tab_widget.currentWidget()
        return widget if isinstance(widget, EditorTab) else None

    def _tab_title_for_editor(self, editor_tab: EditorTab) -> str:
        state = editor_tab.state
        base = state.display_name or (Path(state.path).name if state.path else self._t("無題", "Untitled"))
        if editor_tab.editor.isModified():
            base += " *"
        return base

    def _on_editor_dirty_changed(self, editor_tab: EditorTab) -> None:
        idx = self.tab_widget.indexOf(editor_tab)
        if idx >= 0:
            self.tab_widget.setTabText(idx, self._tab_title_for_editor(editor_tab))
        self._refresh_status()

    def _on_editor_character_count_changed(self, editor_tab: EditorTab) -> None:
        if editor_tab is self.current_editor_tab():
            self.info_panel.set_character_count(editor_tab.character_count())
            self._refresh_status()

    def _on_info_metadata_changed(self, metadata: NovelMetadata) -> None:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return
        editor_tab.state.metadata = metadata
        if not editor_tab.editor.isModified():
            editor_tab.editor.setModified(True)
        self._refresh_status()

    def _on_info_section_state_changed(self, key: str, expanded: bool) -> None:
        current = self.config.get("plot_panel_sections", {})
        if not isinstance(current, dict):
            current = {}
        current[str(key)] = bool(expanded)
        self.config["plot_panel_sections"] = current
        save_config(self.config)

    def _on_info_panel_expanded_changed(self, expanded: bool) -> None:
        self._apply_info_panel_expanded_layout(expanded)
        self.config["plot_panel_expanded"] = bool(expanded)
        save_config(self.config)

    def _apply_info_panel_expanded_layout(self, expanded: bool) -> None:
        if expanded:
            self.info_panel.setMinimumWidth(320)
            self.info_panel.setMaximumWidth(420)
            total = max(1, self.width())
            desired = max(320, min(420, int(self._info_panel_last_expanded_width)))
            self.splitter.setSizes([max(1, total - desired), desired])
            return

        sizes = self.splitter.sizes()
        if len(sizes) == 2 and sizes[1] >= 200:
            self._info_panel_last_expanded_width = sizes[1]
        collapsed_width = 36
        self.info_panel.setMinimumWidth(collapsed_width)
        self.info_panel.setMaximumWidth(collapsed_width)
        total = max(1, self.width())
        self.splitter.setSizes([max(1, total - collapsed_width), collapsed_width])

    def _sync_info_panel(self) -> None:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            self.info_panel.setDisabled(True)
            return
        self.info_panel.setDisabled(False)
        self.info_panel.set_metadata(editor_tab.state.metadata, editor_tab.character_count())

    def _refresh_status(self) -> None:
        current = self.current_editor_tab()
        if not current:
            self.statusBar().showMessage("-")
            return

        page, col, cell = current.current_page_column_cell()
        chars = current.character_count()
        goal = current.state.metadata.progress_goals.daily_target_chars
        rate_text = "-"
        if goal > 0:
            rate = chars / goal * 100.0
            rate_text = f"{rate:.1f}%"

        dirty = self._t("未保存", "Modified") if current.editor.isModified() else self._t("保存済み", "Saved")

        message = self._t(
            f"ページ {page} / 列 {col} / マス {cell} | {chars} 文字 | 目標達成率 {rate_text} | {dirty}",
            f"Page {page} / Col {col} / Cell {cell} | {chars} chars | Goal {rate_text} | {dirty}",
        )
        self.statusBar().showMessage(message)

    def _on_current_tab_changed(self, _index: int) -> None:
        self._sync_info_panel()
        self._refresh_status()

    def switch_to_next_tab(self) -> None:
        if self.tab_widget.count() <= 1:
            return
        idx = (self.tab_widget.currentIndex() + 1) % self.tab_widget.count()
        self.tab_widget.setCurrentIndex(idx)

    def switch_to_previous_tab(self) -> None:
        if self.tab_widget.count() <= 1:
            return
        idx = (self.tab_widget.currentIndex() - 1) % self.tab_widget.count()
        self.tab_widget.setCurrentIndex(idx)

    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._t("ファイルを開く", "Open File"),
            str(self._working_directory()),
        )
        if not path:
            return
        self.open_file(path)

    def _sidecar_path_for(self, path: str) -> str:
        return f"{path}.narrative.json"

    def _plot_path_for_text(self, path: str) -> str:
        return f"{path}.plot.json"

    def _title_seed_for_filename(self, editor_tab: EditorTab) -> str:
        seed = editor_tab.state.metadata.work_title.strip()
        if not seed:
            for line in editor_tab.editor.toPlainText().splitlines():
                if line.strip():
                    seed = line.strip()
                    break
        if not seed:
            seed = self._t("無題", "untitled")
        seed = re.sub(r'[\\\\/:*?"<>|\\s]+', "", seed)
        seed = seed[:5]
        return seed or "story"

    def _working_directory(self) -> Path:
        if self._workspace_dir and self._workspace_dir.exists():
            return self._workspace_dir
        return Path.cwd()

    def _default_text_path_for_tab(self, editor_tab: EditorTab) -> str:
        if editor_tab.state.path:
            return editor_tab.state.path
        parent = self._working_directory()
        filename = f"{self._title_seed_for_filename(editor_tab)}.txt"
        return str(parent / filename)

    def _default_plot_path_for_tab(self, editor_tab: EditorTab) -> str:
        if editor_tab.state.plot_path:
            return editor_tab.state.plot_path
        if editor_tab.state.path:
            return self._plot_path_for_text(editor_tab.state.path)
        parent = self._working_directory()
        filename = f"{self._title_seed_for_filename(editor_tab)}.plot.json"
        return str(parent / filename)

    def _default_pdf_path_for_tab(self, editor_tab: EditorTab) -> str:
        if editor_tab.state.path:
            return str(Path(editor_tab.state.path).with_suffix(".pdf"))
        parent = self._working_directory()
        filename = f"{self._title_seed_for_filename(editor_tab)}.pdf"
        return str(parent / filename)

    def _load_sidecar_metadata(self, path: str) -> tuple[NovelMetadata, str]:
        sidecar_path = self._sidecar_path_for(path)
        metadata = NovelMetadata()
        if not Path(sidecar_path).exists():
            return metadata, sidecar_path

        try:
            payload = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
            metadata = NovelMetadata.from_dict(payload.get("metadata", {}))
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("メタデータ警告", "Metadata Warning"),
                self._t(
                    f"メタデータを読み込めませんでした。本文のみ開きます。\n{exc}",
                    f"Failed to read metadata sidecar. Opening text only.\n{exc}",
                ),
            )
        return metadata, sidecar_path

    def open_file(self, path: str) -> None:
        normalized = self._normalize_path(path)
        for editor_tab in self._iter_editor_tabs():
            if editor_tab.state.path and self._normalize_path(editor_tab.state.path) == normalized:
                self.tab_widget.setCurrentWidget(editor_tab)
                return

        try:
            raw = Path(path).read_bytes()
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("読み込みエラー", "Open Error"),
                self._t(f"ファイルを読み込めませんでした:\n{exc}", f"Failed to read file:\n{exc}"),
            )
            return

        text, encoding = self._decode_with_fallback(raw)
        if text is None:
            QMessageBox.warning(
                self,
                self._t("文字コードエラー", "Encoding Error"),
                self._t("設定された文字コードでデコードできませんでした。", "Could not decode file with configured encodings."),
            )
            return

        metadata, metadata_path = self._load_sidecar_metadata(path)
        plot_path = self._plot_path_for_text(path)

        editor_tab = self._create_editor_tab(
            text=text,
            path=path,
            encoding=encoding,
            newline_mode=self._detect_newline(raw),
            display_name=None,
            metadata=metadata,
            metadata_path=metadata_path,
            plot_path=plot_path,
        )
        editor_tab.editor.setModified(False)
        self._add_recent_file(path)

    def _decode_with_fallback(self, raw: bytes) -> tuple[Optional[str], str]:
        encodings = list(self.config.get("fallback_encodings", ["utf-8", "utf-8-sig", "cp932"]))
        defaults = ["utf-8", "utf-8-sig", "cp932"]
        for enc in defaults:
            if enc not in encodings:
                encodings.append(enc)

        for encoding in encodings:
            try:
                return raw.decode(encoding), encoding
            except Exception:
                continue
        return None, "utf-8"

    def _detect_newline(self, raw: bytes) -> NewlineMode:
        if b"\r\n" in raw:
            return NewlineMode.CRLF
        if b"\r" in raw and b"\n" not in raw:
            return NewlineMode.CR
        return NewlineMode.LF

    def save_current_tab(self) -> bool:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return False
        return self._save_editor_tab(editor_tab)

    def save_current_tab_as(self) -> bool:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return False
        return self._save_editor_tab_as(editor_tab)

    def _save_editor_tab(self, editor_tab: EditorTab) -> bool:
        if not editor_tab.state.path:
            return self._save_editor_tab_as(editor_tab)
        return self._write_editor_to_path(editor_tab, editor_tab.state.path)

    def _save_editor_tab_as(self, editor_tab: EditorTab) -> bool:
        default_path = self._default_text_path_for_tab(editor_tab)
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("名前を付けて保存", "Save File As"),
            default_path,
            self._t("テキスト (*.txt);;すべてのファイル (*)", "Text Files (*.txt);;All Files (*)"),
        )
        if not path:
            return False
        if Path(path).suffix == "":
            path = f"{path}.txt"
        return self._write_editor_to_path(editor_tab, path)

    def _tokenize_for_submission(self, text: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        i = 0
        length = len(text)
        while i < length:
            ch = text[i]
            if ch == "\n":
                tokens.append(("newline", ch))
                i += 1
                continue
            if (
                ch.isdigit()
                and i + 1 < length
                and text[i + 1].isdigit()
                and (i == 0 or not text[i - 1].isdigit())
                and (i + 2 == length or not text[i + 2].isdigit())
            ):
                tokens.append(("tcy", text[i : i + 2]))
                i += 2
                continue
            tokens.append(("char", ch))
            i += 1
        return tokens

    def _layout_submission_units(self, text: str, rows: int = 40, cols: int = 40) -> tuple[list[list[_SubmissionUnit]], int]:
        units: list[_SubmissionUnit] = []
        row = 0
        gcol = 0
        for kind, token_text in self._tokenize_for_submission(text):
            if kind == "newline":
                gcol += 1
                row = 0
                continue

            if row == rows - 1 and token_text in LINE_END_PROHIBITED:
                gcol += 1
                row = 0

            if row == 0 and token_text in LINE_HEAD_PROHIBITED and units:
                prev = units[-1]
                if prev.gcol == gcol - 1 and prev.row == rows - 1:
                    prev.gcol = gcol
                    prev.row = 0
                    row = 1

            units.append(_SubmissionUnit(gcol=gcol, row=row, text=token_text, kind=kind))
            row += 1
            if row >= rows:
                row = 0
                gcol += 1

        max_col = 0
        for unit in units:
            max_col = max(max_col, unit.gcol)
        total_pages = max(1, (max_col // cols) + 1)

        page_units: list[list[_SubmissionUnit]] = [[] for _ in range(total_pages)]
        for unit in units:
            page_index = max(0, min(total_pages - 1, unit.gcol // cols))
            page_units[page_index].append(unit)
        return page_units, total_pages

    def _draw_submission_page(
        self,
        painter: QPainter,
        page_units: list[_SubmissionUnit],
        content_left: float,
        content_top: float,
        cell_width: float,
        cell_height: float,
        rows: int,
        cols: int,
        draw_grid: bool = True,
    ) -> None:
        base_font = QFont(painter.font())
        tcy_font = QFont(base_font)
        if base_font.pixelSize() > 0:
            tcy_font.setPixelSize(max(8, int(base_font.pixelSize() * 0.80)))
        elif base_font.pointSizeF() > 0:
            tcy_font.setPointSizeF(max(8.0, base_font.pointSizeF() * 0.80))

        if draw_grid:
            painter.save()
            painter.setPen(QColor("#c7ced8"))
            for r in range(rows + 1):
                y = content_top + r * cell_height
                painter.drawLine(int(content_left), int(y), int(content_left + cols * cell_width), int(y))
            for c in range(cols + 1):
                x = content_left + c * cell_width
                painter.drawLine(int(x), int(content_top), int(x), int(content_top + rows * cell_height))
            painter.restore()

        for unit in page_units:
            col_in_page = unit.gcol % cols
            x = content_left + (cols - 1 - col_in_page) * cell_width
            y = content_top + unit.row * cell_height
            rect = QRectF(x, y, cell_width, cell_height)

            draw_text = VERTICAL_GLYPH_MAP.get(unit.text, unit.text)
            if unit.kind == "tcy":
                painter.setFont(tcy_font)
                painter.drawText(rect, Qt.AlignCenter, unit.text)
                painter.setFont(base_font)
                continue

            if len(draw_text) == 1 and draw_text.isascii() and draw_text.isalnum():
                center = rect.center()
                painter.save()
                painter.translate(center)
                painter.rotate(90)
                rotated = QRectF(-rect.width() * 0.46, -rect.height() * 0.46, rect.width() * 0.92, rect.height() * 0.92)
                painter.drawText(rotated, Qt.AlignCenter, draw_text)
                painter.restore()
                continue

            painter.drawText(rect, Qt.AlignCenter, draw_text)

    def _export_text_to_pdf(self, text: str, path: str, title: str, base_font: Optional[QFont] = None) -> tuple[bool, int, int]:
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        page_units, total_pages = self._layout_submission_units(normalized_text, rows=40, cols=40)
        char_count = sum(1 for ch in normalized_text if ch not in {"\n", "\r"})

        writer = QPdfWriter(path)
        writer.setResolution(300)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setPageOrientation(QPageLayout.Landscape)
        try:
            writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        except Exception:
            pass
        writer.setTitle(title or Path(path).stem)

        painter = QPainter(writer)
        if not painter.isActive():
            QMessageBox.warning(
                self,
                self._t("書き出しエラー", "Export Error"),
                self._t("PDFの書き出しを開始できませんでした。", "Failed to start PDF export."),
            )
            return False, 0, 0

        try:
            page_rect = writer.pageLayout().fullRectPixels(writer.resolution())
            rows = 40
            cols = 40
            content_left = float(page_rect.left())
            content_top = float(page_rect.top())
            content_width = float(page_rect.width())
            content_height = float(page_rect.height())
            cell_width = content_width / cols
            cell_height = content_height / rows

            font = QFont(base_font or self.font())
            font.setPixelSize(max(16, int(min(cell_width, cell_height) * 0.88)))
            painter.setFont(font)
            painter.setPen(QColor("#111111"))

            for page_index, units in enumerate(page_units):
                if page_index > 0:
                    writer.newPage()
                    painter.setFont(font)
                    painter.setPen(QColor("#111111"))
                painter.fillRect(
                    QRectF(
                        float(page_rect.left()),
                        float(page_rect.top()),
                        float(page_rect.width()),
                        float(page_rect.height()),
                    ),
                    QColor("#ffffff"),
                )
                self._draw_submission_page(
                    painter,
                    units,
                    content_left,
                    content_top,
                    cell_width,
                    cell_height,
                    rows,
                    cols,
                    draw_grid=True,
                )
        finally:
            painter.end()

        return True, char_count, total_pages

    def export_submission_pdf_current_tab(self) -> bool:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return False

        default_path = self._default_pdf_path_for_tab(editor_tab)
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("PDFを書き出し", "Export PDF"),
            default_path,
            "PDF (*.pdf)",
        )
        if not path:
            return False
        if Path(path).suffix.lower() != ".pdf":
            path = f"{path}.pdf"

        text = editor_tab.editor.toPlainText()
        ok, char_count, total_pages = self._export_text_to_pdf(
            text=text,
            path=path,
            title=editor_tab.state.metadata.work_title or Path(path).stem,
            base_font=editor_tab.editor.font(),
        )
        if not ok:
            return False

        self.statusBar().showMessage(
            self._t(
                f"PDFを書き出しました（A4横・40x40・方眼あり・{char_count}文字・{total_pages}枚）。",
                f"PDF exported (A4 landscape, 40x40, with grid, {char_count} chars, {total_pages} pages).",
            ),
            3500,
        )
        return True

    def _default_workspace_pdf_path(self) -> str:
        parent = self._working_directory()
        workspace_name = self._workspace_dir.name if self._workspace_dir else "workspace"
        safe_name = re.sub(r'[\\\\/:*?"<>|\\s]+', "_", workspace_name).strip("_") or "workspace"
        return str(parent / f"{safe_name}_combined.pdf")

    def export_workspace_submission_pdf(self) -> bool:
        if self._workspace_dir is None:
            QMessageBox.information(
                self,
                self._t("作業フォルダ未設定", "Workspace Not Set"),
                self._t("先に作業フォルダを設定してください。", "Set workspace folder first."),
            )
            return False
        if len(self._workspace_text_files) < 2:
            QMessageBox.information(
                self,
                self._t("PDF書き出し", "Export PDF"),
                self._t("結合PDFは2件以上のテキストファイルが必要です。", "Combined PDF needs at least 2 text files."),
            )
            return False

        default_path = self._default_workspace_pdf_path()
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("結合PDFを書き出し", "Export Combined PDF"),
            default_path,
            "PDF (*.pdf)",
        )
        if not path:
            return False
        if Path(path).suffix.lower() != ".pdf":
            path = f"{path}.pdf"

        chunks: list[str] = []
        skipped = 0
        for text_file in self._workspace_text_files:
            try:
                raw = text_file.read_bytes()
            except Exception:
                skipped += 1
                continue
            body, _encoding = self._decode_with_fallback(raw)
            if body is None:
                skipped += 1
                continue

            chunks.append(body)

        if not chunks:
            QMessageBox.warning(
                self,
                self._t("PDF書き出し", "Export PDF"),
                self._t("結合できるテキストファイルがありませんでした。", "No readable text file was found."),
            )
            return False

        merged_text = ""
        for index, chunk in enumerate(chunks):
            if index == 0:
                merged_text = chunk
                continue
            if merged_text.endswith(("\n", "\r")) or chunk.startswith(("\n", "\r")):
                merged_text += chunk
            else:
                merged_text += "\n" + chunk
        ok, char_count, total_pages = self._export_text_to_pdf(
            text=merged_text,
            path=path,
            title=self._workspace_dir.name,
        )
        if not ok:
            return False

        exported_count = len(chunks)
        if skipped > 0:
            self.statusBar().showMessage(
                self._t(
                    f"{exported_count}件を結合してPDFを書き出し（{skipped}件スキップ）: {char_count}文字・{total_pages}枚。",
                    f"Combined {exported_count} files ({skipped} skipped): {char_count} chars, {total_pages} pages.",
                ),
                4500,
            )
        else:
            self.statusBar().showMessage(
                self._t(
                    f"{exported_count}件を結合してPDFを書き出しました: {char_count}文字・{total_pages}枚。",
                    f"Combined {exported_count} files into PDF: {char_count} chars, {total_pages} pages.",
                ),
                4500,
            )
        return True

    def _write_editor_to_path(self, editor_tab: EditorTab, path: str) -> bool:
        body = editor_tab.editor.toPlainText()
        body = self._normalize_text_newline(body, editor_tab.state.newline)

        try:
            raw = body.encode(editor_tab.state.encoding)
        except UnicodeEncodeError:
            result = QMessageBox.question(
                self,
                self._t("文字コード警告", "Encoding Warning"),
                self._t(
                    f"{editor_tab.state.encoding} では保存できない文字があります。UTF-8 で保存しますか？",
                    f"Text cannot be encoded with {editor_tab.state.encoding}. Save as UTF-8 instead?",
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if result != QMessageBox.Yes:
                return False
            editor_tab.state.encoding = "utf-8"
            raw = body.encode("utf-8")
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("保存エラー", "Save Error"),
                self._t(f"保存に失敗しました:\n{exc}", f"Failed to save file:\n{exc}"),
            )
            return False

        sidecar_path = self._sidecar_path_for(path)
        sidecar_payload = {
            "meta": {"app": "Narrative_Edit", "schema": 1, "saved_at": int(time())},
            "metadata": editor_tab.state.metadata.to_dict(),
        }

        try:
            Path(path).write_bytes(raw)
            Path(sidecar_path).write_text(json.dumps(sidecar_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("保存エラー", "Save Error"),
                self._t(
                    f"本文またはメタデータの保存に失敗しました:\n{exc}",
                    f"Failed to save text or metadata:\n{exc}",
                ),
            )
            return False

        editor_tab.state.path = path
        editor_tab.state.metadata_path = sidecar_path
        editor_tab.state.plot_path = self._plot_path_for_text(path)
        editor_tab.state.display_name = None
        editor_tab.editor.setModified(False)
        remove_session(editor_tab.state.session_id)
        self._add_recent_file(path)
        if self._workspace_contains_path(Path(path)):
            self._refresh_workspace_file_list()

        idx = self.tab_widget.indexOf(editor_tab)
        if idx >= 0:
            self.tab_widget.setTabText(idx, self._tab_title_for_editor(editor_tab))
        self._refresh_status()
        return True

    def save_plot_for_current_tab(self) -> bool:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return False

        default_path = self._default_plot_path_for_tab(editor_tab)
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("プロットを保存", "Save Plot"),
            default_path,
            self._t("プロット (*.plot.json *.json);;すべてのファイル (*)", "Plot Files (*.plot.json *.json);;All Files (*)"),
        )
        if not path:
            return False
        suffix = Path(path).suffix.lower()
        if suffix not in {".json"} and not path.lower().endswith(".plot.json"):
            path = f"{path}.plot.json"

        payload = {
            "meta": {"app": "Narrative_Edit", "type": "plot", "schema": 1, "saved_at": int(time())},
            "metadata": editor_tab.state.metadata.to_dict(),
        }
        try:
            Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("保存エラー", "Save Error"),
                self._t(f"プロット保存に失敗しました:\n{exc}", f"Failed to save plot:\n{exc}"),
            )
            return False

        editor_tab.state.plot_path = path
        self.statusBar().showMessage(self._t("プロットを保存しました。", "Plot saved."), 2000)
        return True

    def load_plot_for_current_tab(self) -> bool:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return False

        default_path = self._default_plot_path_for_tab(editor_tab)
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._t("プロットを読み込み", "Load Plot"),
            default_path,
            self._t("プロット (*.plot.json *.json);;すべてのファイル (*)", "Plot Files (*.plot.json *.json);;All Files (*)"),
        )
        if not path:
            return False

        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "metadata" in payload:
                metadata = NovelMetadata.from_dict(payload.get("metadata", {}))
            else:
                metadata = NovelMetadata.from_dict(payload if isinstance(payload, dict) else {})
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("読み込みエラー", "Load Error"),
                self._t(f"プロット読み込みに失敗しました:\n{exc}", f"Failed to load plot:\n{exc}"),
            )
            return False

        editor_tab.state.metadata = metadata
        editor_tab.state.plot_path = path
        self.info_panel.set_metadata(metadata, editor_tab.character_count())
        if not editor_tab.editor.isModified():
            editor_tab.editor.setModified(True)
        self._refresh_status()
        self.statusBar().showMessage(self._t("プロットを読み込みました。", "Plot loaded."), 2000)
        return True

    def _normalize_text_newline(self, text: str, mode: NewlineMode) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if mode == NewlineMode.CRLF:
            return normalized.replace("\n", "\r\n")
        if mode == NewlineMode.CR:
            return normalized.replace("\n", "\r")
        return normalized

    def close_current_tab(self) -> None:
        idx = self.tab_widget.currentIndex()
        if idx >= 0:
            self._close_tab_at(idx)

    def _close_tab_at(self, index: int) -> None:
        widget = self.tab_widget.widget(index)
        if widget is None:
            return

        if isinstance(widget, EditorTab):
            if not self._confirm_close_editor(widget):
                return
            self._editor_by_tab_id.pop(widget.state.tab_id, None)
            remove_session(widget.state.session_id)

        self.tab_widget.removeTab(index)
        widget.deleteLater()
        if self.tab_widget.count() == 0:
            self.new_tab()

    def _confirm_close_editor(self, editor_tab: EditorTab) -> bool:
        if not editor_tab.editor.isModified():
            return True

        title = editor_tab.state.path or editor_tab.state.display_name or self._t("無題", "Untitled")
        result = QMessageBox.question(
            self,
            self._t("未保存の変更", "Unsaved Changes"),
            self._t(f"次の変更を保存しますか？\n{title}", f"Save changes to:\n{title}?"),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if result == QMessageBox.Cancel:
            return False
        if result == QMessageBox.Yes:
            return self._save_editor_tab(editor_tab)

        editor_tab.editor.setModified(False)
        return True

    def _open_tab_context_menu(self, pos) -> None:
        index = self.tab_widget.tabBar().tabAt(pos)
        if index < 0:
            return
        widget = self.tab_widget.widget(index)
        if not isinstance(widget, EditorTab):
            return

        menu = QMenu(self)
        rename_action = menu.addAction(self._t("タブ名を変更", "Rename Tab"))
        selected = menu.exec(self.tab_widget.tabBar().mapToGlobal(pos))
        if selected is rename_action:
            current_name = widget.state.display_name or (Path(widget.state.path).name if widget.state.path else "")
            name, ok = QInputDialog.getText(
                self,
                self._t("タブ名変更", "Rename Tab"),
                self._t("タブ名:", "Tab name:"),
                text=current_name,
            )
            if ok and name.strip():
                widget.state.display_name = name.strip()
                tab_index = self.tab_widget.indexOf(widget)
                if tab_index >= 0:
                    self.tab_widget.setTabText(tab_index, self._tab_title_for_editor(widget))

    def undo_current(self) -> None:
        editor_tab = self.current_editor_tab()
        if editor_tab:
            editor_tab.undo()

    def redo_current(self) -> None:
        editor_tab = self.current_editor_tab()
        if editor_tab:
            editor_tab.redo()

    def open_search_bar(self) -> None:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return
        selected = editor_tab.editor.selectedText()
        self.search_bar.open(selected)

    def hide_search_bar(self) -> None:
        self.search_bar.setVisible(False)
        editor_tab = self.current_editor_tab()
        if editor_tab:
            editor_tab.editor.setFocus()

    def find_in_current_editor(self, forward: bool = True) -> None:
        editor_tab = self.current_editor_tab()
        if not editor_tab:
            return

        pattern = self.search_bar.query()
        if not pattern:
            return

        try:
            found = editor_tab.editor.find(
                pattern,
                forward=forward,
                is_regex=self.search_bar.is_regex(),
                case_sensitive=self.search_bar.is_case_sensitive(),
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._t("検索エラー", "Find Error"),
                self._t(f"検索に失敗しました:\n{exc}", f"Search failed:\n{exc}"),
            )
            return

        if not found:
            self.statusBar().showMessage(self._t("一致する結果がありません。", "No matches found."), 1500)

    def change_font_size(self) -> None:
        current = int(self.config.get("font_size", 16))
        value, ok = QInputDialog.getInt(
            self,
            self._t("フォントサイズ", "Font Size"),
            self._t("ポイントサイズ:", "Point size:"),
            value=current,
            minValue=8,
            maxValue=64,
        )
        if not ok:
            return
        self.config["font_size"] = value
        for editor_tab in self._iter_editor_tabs():
            editor_tab.set_font_size(value)
        save_config(self.config)

    def change_grid_rows(self) -> None:
        current = int(self.config.get("manuscript_grid_rows", 40))
        value, ok = QInputDialog.getInt(
            self,
            self._t("原稿用紙の行数", "Grid Rows"),
            self._t("行数:", "Rows:"),
            value=current,
            minValue=8,
            maxValue=80,
        )
        if not ok:
            return
        self.config["manuscript_grid_rows"] = value
        for editor_tab in self._iter_editor_tabs():
            editor_tab.set_grid(value, int(self.config.get("manuscript_grid_cols", 40)))
        save_config(self.config)

    def change_grid_cols(self) -> None:
        current = int(self.config.get("manuscript_grid_cols", 40))
        value, ok = QInputDialog.getInt(
            self,
            self._t("原稿用紙の列数", "Grid Columns"),
            self._t("列数:", "Columns:"),
            value=current,
            minValue=8,
            maxValue=80,
        )
        if not ok:
            return
        self.config["manuscript_grid_cols"] = value
        for editor_tab in self._iter_editor_tabs():
            editor_tab.set_grid(int(self.config.get("manuscript_grid_rows", 40)), value)
        save_config(self.config)

    def toggle_show_grid(self, checked: bool) -> None:
        self.config["show_manuscript_grid"] = bool(checked)
        for editor_tab in self._iter_editor_tabs():
            editor_tab.set_show_grid(bool(checked))
        save_config(self.config)

    def toggle_autosave(self, checked: bool) -> None:
        self.config["autosave_enabled"] = checked
        self._apply_autosave_timer_settings()

    def change_autosave_interval(self) -> None:
        current = int(self.config.get("autosave_interval_sec", 5))
        value, ok = QInputDialog.getInt(
            self,
            self._t("自動保存間隔", "Autosave Interval"),
            self._t("秒:", "Seconds:"),
            value=current,
            minValue=2,
            maxValue=600,
        )
        if not ok:
            return
        self.config["autosave_interval_sec"] = value
        self._apply_autosave_timer_settings()

    def _add_recent_file(self, path: str) -> None:
        files = list(self.config.get("recent_files", []))
        normalized = self._normalize_path(path)
        filtered = [p for p in files if self._normalize_path(p) != normalized]
        filtered.insert(0, path)
        limit = max(1, int(self.config.get("recent_files_limit", 10)))
        self.config["recent_files"] = filtered[:limit]
        save_config(self.config)
        self._rebuild_recent_files_menu()

    def _rebuild_recent_files_menu(self) -> None:
        if self._recent_menu is None:
            return
        self._recent_menu.clear()
        self._recent_menu.setTitle(self._t("最近開いたファイル", "Recent Files"))
        files = list(self.config.get("recent_files", []))
        if not files:
            empty = self._recent_menu.addAction(self._t("(空)", "(empty)"))
            empty.setEnabled(False)
            return

        for path in files:
            action = self._recent_menu.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: self.open_file(p))

    def _normalize_path(self, path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def autosave_dirty_tabs(self) -> None:
        if not bool(self.config.get("autosave_enabled", True)):
            return

        for editor_tab in self._iter_editor_tabs():
            if editor_tab.editor.isModified():
                payload = {
                    "session_id": editor_tab.state.session_id,
                    "path": editor_tab.state.path,
                    "display_name": editor_tab.state.display_name,
                    "encoding": editor_tab.state.encoding,
                    "newline": editor_tab.state.newline.value,
                    "is_dirty": True,
                    "text": editor_tab.editor.toPlainText(),
                    "metadata": editor_tab.state.metadata.to_dict(),
                    "metadata_path": editor_tab.state.metadata_path,
                    "plot_path": editor_tab.state.plot_path,
                    "meta": {
                        "app": "Narrative_Edit",
                        "schema": 2,
                        "saved_at": int(time()),
                    },
                }
                save_session(editor_tab.state.session_id, payload)
            else:
                remove_session(editor_tab.state.session_id)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for editor_tab in list(self._iter_editor_tabs()):
            self.tab_widget.setCurrentWidget(editor_tab)
            if not self._confirm_close_editor(editor_tab):
                event.ignore()
                return

        app = QApplication.instance()
        other_windows_open = False
        if app is not None:
            for widget in app.topLevelWidgets():
                if widget is self:
                    continue
                if isinstance(widget, MainWindow) and widget.isVisible():
                    other_windows_open = True
                    break

        if not other_windows_open:
            clear_sessions()
        save_config(self.config)
        event.accept()
