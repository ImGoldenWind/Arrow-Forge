from __future__ import annotations

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_bg_dark,
    ss_dim_label,
    ss_error_label,
    ss_sidebar_btn,
    ss_splitter,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorListRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_card,
    configure_field,
    configure_file_label,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
    configure_table,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy
import math
import os
import threading

from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.editor_diff import ChangeItem
from core.editor_host import confirm_editor_change_summary, notify_editor_file_loaded
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.undo_redo import EditorHistory
from parsers.anmofs_tools import key_states, key_tick, receiver_code, receiver_model_code, active_offset, is_situation_finish_offsets
from parsers.anmofs_parser import (
    AnmofsEntry,
    append_chunk_page,
    duplicate_anmofs_chunk,
    load_anmofs_xfbin,
    make_default_chunk,
    save_anmofs_xfbin,
)


ENTRY_FIELDS = ("frame", "value_1", "value_2", "value_3", "value_4", "value_5", "value_6")


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 3)] + "..."


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


class AnmofsEditor(QWidget):
    """Editor for ASBR *_anmofs.xfbin animation offset tables."""

    _load_done_signal = pyqtSignal(str, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.t = lang_func
        self.setStyleSheet(ss_transparent())

        self._filepath = None
        self._xfbin = None
        self._chunks = []
        self._saved_chunks = []
        self._chunk_snapshots = {}
        self._current_chunk = None
        self._chunk_buttons = []
        self._fields = {}
        self._dirty = False
        self._rebuilding = False
        self._selected_entry_idx = -1
        self._history = EditorHistory()
        self._restoring_history = False
        self._last_meta_columns = None

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self._build_ui(root)
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self, root):
        top = EditorToolbar(self)


        top_layout = top.content_layout


        open_btn = QPushButton(self.t("btn_open_file"), top)
        configure_button(open_btn, accent=True)
        open_btn.clicked.connect(lambda _checked=False: self._load_file())
        open_btn.setProperty("designAction", 'open')
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"), top)
        self._save_btn.setEnabled(False)
        configure_button(self._save_btn, accent=True)
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)


        self._file_label = QLabel(self.t("no_file_loaded"), top)

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label, 1)
        root.addWidget(top)

        sep = EditorSeparator(self, accent=True)


        root.addWidget(sep)

        main = QWidget(self)
        main.setStyleSheet(ss_transparent())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        self._build_sidebar(main, main_layout)

        vsep = EditorSeparator(main, orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(vsep)

        self._editor_scroll = QScrollArea(main)


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        self._workspace_splitter = QSplitter(Qt.Orientation.Horizontal, main)
        self._workspace_splitter.setStyleSheet(ss_splitter())
        self._workspace_splitter.setChildrenCollapsible(False)
        self._workspace_splitter.addWidget(self._editor_scroll)
        from editors.anmofs_preview import AnmofsPreviewPanel
        self._preview = AnmofsPreviewPanel()
        self._preview.key_selected.connect(self._preview_key_selected)
        self._preview_scroll = QScrollArea()
        configure_scrollarea(self._preview_scroll)
        self._preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_scroll.setMinimumWidth(self._preview.minimumWidth())
        self._preview_scroll.setWidget(self._preview)
        from core.ui.editor_chrome import EditorSidebarPane
        self._preview_pane = EditorSidebarPane(self._preview_scroll, self, edge="right", resizable=True, label="preview")
        self._preview_pane.collapsedChanged.connect(lambda hidden: self._preview._stop() if hidden else None)
        self._workspace_splitter.addWidget(self._preview_pane)
        self._workspace_splitter.setSizes([640, 520])
        main_layout.addWidget(self._workspace_splitter, 1)

        self._show_placeholder()
        root.addWidget(main, 1)

    def _preview_key_selected(self, row):
        if self._current_chunk and 0 <= row < len(self._current_chunk.entries):
            self._table.blockSignals(True)
            self._table.selectRow(row)
            self._table.blockSignals(False)
            self._selected_entry_idx = row
            self._sync_entry_buttons()
            self._sync_key_hint()

    def _build_sidebar(self, parent, main_layout):
        side = EditorSidebar(parent, width=276)


        side_layout = side.content_layout


        self._search = QLineEdit(side)
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_chunks)
        side_layout.addWidget(self._search)

        actions = EditorActionRow(side)

        actions_layout = actions.content_layout


        self._add_chunk_btn = QPushButton(self.t("btn_new"), actions)
        self._dup_chunk_btn = QPushButton(self.t("btn_duplicate"), actions)
        self._del_chunk_btn = QPushButton(self.t("btn_delete"), actions)
        for btn in (self._add_chunk_btn, self._dup_chunk_btn, self._del_chunk_btn):
            btn.setFixedHeight(Size.COMPACT_CONTROL)
            btn.setEnabled(False)
            btn.setFont(ui_font(TypeSize.BODY))
            actions_layout.addWidget(btn, 1)
        configure_button(self._add_chunk_btn)
        configure_button(self._dup_chunk_btn)
        configure_button(self._del_chunk_btn, danger=True)
        self._add_chunk_btn.clicked.connect(self._add_chunk)
        self._add_chunk_btn.setProperty("designAction", 'new')
        self._dup_chunk_btn.clicked.connect(self._duplicate_chunk)
        self._dup_chunk_btn.setProperty("designAction", 'duplicate')
        self._del_chunk_btn.clicked.connect(self._delete_chunk)
        self._del_chunk_btn.setProperty("designAction", 'delete')
        side_layout.addWidget(actions)

        self._chunk_scroll = QScrollArea(side)


        configure_scrollarea(self._chunk_scroll, transparent=True)
        self._chunk_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chunk_list_widget = QWidget()
        self._chunk_list_widget.setMinimumWidth(0)
        self._chunk_list_widget.setStyleSheet(ss_transparent())
        self._chunk_list_layout = QVBoxLayout(self._chunk_list_widget)
        configure_layout(self._chunk_list_layout, LayoutRole.ROOT)
        self._chunk_list_layout.addStretch()
        self._chunk_scroll.setWidget(self._chunk_list_widget)
        side_layout.addWidget(self._chunk_scroll, 1)
        main_layout.addWidget(side)

    def _show_placeholder(self):
        if hasattr(self, "_preview"):
            self._preview.set_chunk('', None)
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._key_fields = {}
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        card = make_empty_state(
            self._editor_widget,
            title=self.t("no_file_loaded"),
            text=self.t("ui_anmofs_open_file_to_begin_editing"),
            icon_name="fa6s.film",
        )
        self._editor_layout.addStretch(1)
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch(1)

    def _load_file(self, path=None):
        if path is not None and not isinstance(path, (str, os.PathLike)):
            path = None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                self.t("ui_anmofs_open_title"),
                game_files_dialog_dir(target_patterns="*_anmofs.xfbin"),
                self.t("ui_anmofs_file_filter"),
            )
            if not path:
                return
        create_backup_on_open(path, tool_id=getattr(self, "_tool_id", None))
        set_file_label_empty(self._file_label, self.t("loading"))
        self._set_controls_enabled(False)
        self._show_placeholder()

        def worker():
            try:
                xfbin, chunks = load_anmofs_xfbin(path)
            except Exception as exc:
                self._load_error_signal.emit(str(exc))
                return
            self._load_done_signal.emit(path, xfbin, chunks)

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_error(self, msg):
        self._filepath = None
        self._xfbin = None
        self._chunks = []
        self._saved_chunks = []
        self._chunk_snapshots = {}
        self._current_chunk = None
        self._dirty = False
        self._history.clear()
        self._set_controls_enabled(False)
        self._rebuild_chunk_list()
        self._show_placeholder()
        set_file_label_empty(self._file_label, self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, xfbin, chunks):
        self._filepath = path
        self._xfbin = xfbin
        self._chunks = list(chunks)
        self._saved_chunks = copy.deepcopy(self._chunks)
        self._chunk_snapshots = {id(item.chunk): copy.deepcopy(item) for item in self._chunks}
        self._current_chunk = None
        self._dirty = False
        self._history.clear()
        set_file_label(self._file_label, path)
        notify_editor_file_loaded(self, path)
        self._set_controls_enabled(True)
        self._rebuild_chunk_list()
        if self._chunks:
            self._select_chunk(self._chunks[0])

    def _save_file(self, target_path=None):
        save_path = target_path or editor_path(self)
        if self._xfbin is None or not save_path:
            return
        self._apply_meta_fields()
        if not confirm_editor_change_summary(self):
            return
        try:
            save_anmofs_xfbin(self._xfbin, save_path, self._chunks)
        except Exception as exc:
            QMessageBox.critical(self, self.t('dlg_title_error'), self.t('msg_save_error', error=exc))
            return
        commit_save_path(self, save_path)
        self._dirty = False
        self._saved_chunks = copy.deepcopy(self._chunks)
        self._chunk_snapshots = {id(item.chunk): copy.deepcopy(item) for item in self._chunks}
        set_file_label(self._file_label, save_path)
        self._refresh_selected_ui()
        QMessageBox.information(self, self.t('dlg_title_success'), self.t('msg_save_success', path=os.path.basename(save_path)))

    def _set_controls_enabled(self, enabled):
        self._save_btn.setEnabled(bool(enabled and self._filepath))
        for btn in (self._add_chunk_btn, self._dup_chunk_btn, self._del_chunk_btn):
            btn.setEnabled(bool(enabled))

    def _rebuild_chunk_list(self):
        _clear_layout(self._chunk_list_layout)
        self._chunk_buttons = []
        for item in self._chunks:
            btn = EditorListRow(self._chunk_list_widget, height=50)

            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


            btn.clicked.connect(lambda checked=False, chunk=item: self._select_chunk(chunk))

            layout = btn.content_layout


            title_text = self._receiver_title(item)
            title = btn.add_title(_truncate(title_text, 24))


            title.setToolTip(item.chunk_name)

            subtitle_text = item.anm_name
            subtitle = btn.add_subtitle(_truncate(subtitle_text, 30))


            subtitle.setToolTip(subtitle_text)


            self._chunk_list_layout.addWidget(btn)
            self._chunk_buttons.append((btn, item, title, subtitle))
        self._chunk_list_layout.addStretch()
        self._filter_chunks()

    def _filter_chunks(self):
        query = self._search.text().strip().lower() if hasattr(self, "_search") else ""
        for btn, item, _title, _subtitle in self._chunk_buttons:
            haystack = " ".join((
                item.chunk_name,
                item.file_path,
                item.anm_name,
                item.characode,
                self._receiver_title(item),
            )).lower()
            btn.setVisible(query in haystack)

    def _select_chunk(self, item):
        if item is self._current_chunk:
            return
        self.apply_pending_edits()
        self._current_chunk = item
        self._selected_entry_idx = 0 if item.entries else -1
        self._build_editor(item)
        self._refresh_chunk_buttons()

    def _refresh_chunk_buttons(self):
        for btn, item, title, subtitle in self._chunk_buttons:
            btn.setStyleSheet(ss_sidebar_btn(item is self._current_chunk))
            title_text = self._receiver_title(item)
            subtitle_text = item.anm_name
            title.setText(_truncate(title_text, 24))
            title.setToolTip(item.chunk_name)
            subtitle.setText(_truncate(subtitle_text, 30))
            subtitle.setToolTip(subtitle_text)

    def _receiver_title(self, item):
        name = self._preview._character_name(receiver_model_code(item))
        return name + (' · d' if receiver_code(item) != receiver_model_code(item) else '')

    def _build_editor(self, item):
        _clear_layout(self._editor_layout)
        self._fields = {}
        configure_layout(self._editor_layout, LayoutRole.PAGE)

        intro, body = self._make_editor_card()
        attacker = self._preview._character_name(os.path.basename(self._filepath).removesuffix('_anmofs.xfbin'))
        receiver = self._preview._character_name(receiver_model_code(item))
        _, self._intro_title, _ = add_editor_card_title(body, self.t('anmofs_edit_pair', attacker=attacker, receiver=receiver), 'fa6s.people-arrows')
        self._editor_layout.addWidget(intro)
        self._build_entries_panel(item)
        self._build_metadata_panel(item)
        reference, body = self._make_editor_card()
        add_editor_card_title(body, self.t('ui_anmofs_layout_title'), 'fa6s.magnifying-glass')
        hint = QLabel(self.t('ui_anmofs_layout_hint'), reference)
        hint.setWordWrap(True)
        hint.setStyleSheet(ss_dim_label())
        body.addWidget(hint)
        self._editor_layout.addWidget(reference)
        self._editor_layout.addStretch()
        self._sync_name_warning()
        self._preview.set_chunk(self._filepath, item)
        for label in self._editor_widget.findChildren(QLabel):
            if label.wordWrap():
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
                label.installEventFilter(self)
        QTimer.singleShot(0, self._fit_wrapped_labels)

    def _fit_wrapped_labels(self):
        for label in self._editor_widget.findChildren(QLabel):
            if label.wordWrap():
                label.setMinimumHeight(max(0, label.heightForWidth(max(1, label.width()))))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and isinstance(watched, QLabel) and watched.wordWrap():
            watched.setMinimumHeight(max(0, watched.heightForWidth(max(1, watched.width()))))
        return super().eventFilter(watched, event)

    def _make_editor_card(self, margins=Insets.CARD, spacing=Size.CARD_GAP):
        card, layout = make_editor_card(self._editor_widget, margins=margins, spacing=spacing)
        self._prep_card(card)
        return card, layout

    def _grid_columns(self, max_columns=3):
        width = self._editor_scroll.viewport().width() if hasattr(self, "_editor_scroll") else self.width()
        if width < 760:
            return 1
        if width < 980:
            return min(2, max_columns)
        return max_columns

    def _entry_action_columns(self):
        return max(1, min(5, (self._editor_scroll.viewport().width() - 24) // 140))

    def _prep_card(self, card):
        configure_card(card, maximum_width=16777215)
        return card

    def _prep_field(self, wrap, edit):
        configure_field(wrap, edit)

    def _make_editor_field(self, label_text, value, key, *, value_font=None, height=30, width=None):
        wrap, layout, _label, _hint = make_editor_field_shell(label_text)
        wrap.setParent(self._editor_widget)
        if key in ('anm_name', 'characode'):
            edit = QComboBox(wrap)
            edit.setEditable(True)
            edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            edit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            edit.addItems(sorted({str(getattr(chunk, key)) for chunk in self._chunks} | {str(value)}))
            edit.setCurrentText(str(value))
            edit.lineEdit().textEdited.connect(self._on_meta_changed)
            edit.activated.connect(self._on_meta_changed)
        else:
            edit = QLineEdit(wrap)
            edit.setText(str(value))
            edit.textEdited.connect(self._on_meta_changed)
        if width:
            edit.setFixedWidth(width)
        configure_input(edit, height=height, monospace=True, font=value_font)
        edit.setMinimumWidth(0)
        (edit.lineEdit() if isinstance(edit, QComboBox) else edit).setCursorPosition(0)
        if key in ('anm_name', 'characode', 'chunk_name', 'reserved'):
            edit.setToolTip(self.t('anmofs_help_' + key))
        self._prep_field(wrap, edit)
        layout.addWidget(edit)
        self._fields[key] = edit
        return wrap, edit

    def _build_metadata_panel(self, item):
        panel, grid = make_editor_grid_card(self._editor_widget, title=item.chunk_name or self.t('ui_anmofs_unnamed_chunk'), icon_name='fa6s.film', subtitle=' / '.join((part for part in (item.anm_name, item.characode) if part)))
        self._prep_card(panel)

        fields = [
            ("chunk_name", self.t("ui_anmofs_chunk_name"), item.chunk_name, None),
            ("file_path", self.t("ui_anmofs_file_path"), item.file_path, None),
            ("anm_name", self.t("ui_anmofs_animation_name"), item.anm_name, None),
            ("characode", self.t("ui_anmofs_characode"), item.characode, None),
        ]
        columns = self._grid_columns(2)
        self._last_meta_columns = columns
        if columns == 1:
            for row, (key, label, value, width) in enumerate(fields):
                self._add_line_field(grid, row, 0, key, label, value, width=width)
            warning_row = len(fields)
        else:
            for idx, (key, label, value, width) in enumerate(fields):
                row, col = divmod(idx, columns)
                self._add_line_field(grid, row, col, key, label, value, width=width)
            warning_row = (len(fields) + columns - 1) // columns

        self._name_warning = QLabel("", panel)
        self._name_warning.setWordWrap(True)
        self._name_warning.setFont(ui_font(TypeSize.BODY))
        self._name_warning.setStyleSheet(ss_dim_label())
        grid.addWidget(self._name_warning, warning_row, 0, 1, columns)

        self._editor_layout.addWidget(panel)
        self._metadata_panel = panel

    def _build_entries_panel(self, item):
        panel, layout = self._make_editor_card(margins=Insets.CARD, spacing=Size.CARD_GAP)
        add_editor_card_title(layout, self.t("ui_anmofs_entries"), "fa6s.table")

        self._key_fields = {}
        selected = QWidget(panel)
        selected.setStyleSheet(ss_transparent())
        values = QGridLayout(selected)
        values.setContentsMargins(*Insets.NONE)
        values.setHorizontalSpacing(6)
        values.setVerticalSpacing(Size.GAP_SM)
        field_names = ('frame', 'value_1', 'value_2', 'value_3', 'value_4', 'value_5', 'value_6')
        for i, field in enumerate(field_names):
            if i == 0:
                row, col, span = 0, 0, 3
                label = self.t('ui_anmofs_col_frame')
            else:
                row, col, span = 2 + (i - 1) // 3 * 2, (i - 1) % 3, 1
                label = self.t('anmofs_position_axis' if i <= 3 else 'anmofs_rotation_axis', axis='XYZ'[(i - 1) % 3])
            title = QLabel(label, selected)
            title.setStyleSheet(ss_dim_label())
            title.setWordWrap(True)
            if field == 'frame':
                self._selected_key_title = title
            values.addWidget(title, row, col, 1, span)
            edit = QLineEdit(selected)
            edit.setMinimumWidth(0)
            edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            configure_input(edit)
            edit.setToolTip(self.t('anmofs_edit_value_hint'))
            edit.editingFinished.connect(lambda key=field: self._apply_key_field(key))
            values.addWidget(edit, row + 1, col, 1, span)
            self._key_fields[field] = edit
        layout.addWidget(selected)
        self._value_feedback = QLabel('', panel)
        self._value_feedback.setStyleSheet(ss_error_label())
        self._value_feedback.setWordWrap(True)
        self._value_feedback.hide()
        layout.addWidget(self._value_feedback)

        header = QWidget(panel)
        header.setStyleSheet(ss_transparent())
        header_layout = QGridLayout(header)
        configure_layout(header_layout, LayoutRole.TITLE)

        self._add_entry_btn = QPushButton(self.t("btn_new"), header)
        self._active_key_btn = QPushButton(self.t('anmofs_select_active_key'), header)
        self._active_key_btn.setToolTip(self.t('anmofs_select_active_key_hint'))
        self._active_key_btn.clicked.connect(self._select_active_key)
        self._dup_entry_btn = QPushButton(self.t("btn_duplicate"), header)
        self._del_entry_btn = QPushButton(self.t("btn_delete"), header)
        self._sort_entry_btn = QPushButton(self.t("ui_anmofs_sort_entries"), header)
        self._reset_chunk_btn = QPushButton(self.t("ui_anmofs_reset_chunk"), header)
        self._reset_chunk_btn.hide()
        for btn in (self._active_key_btn, self._add_entry_btn, self._dup_entry_btn, self._sort_entry_btn, self._reset_chunk_btn):
            configure_button(btn, height=Size.COMPACT_CONTROL)
        configure_button(self._del_entry_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._last_action_columns = self._entry_action_columns()
        for i, btn in enumerate((self._active_key_btn, self._add_entry_btn, self._dup_entry_btn, self._sort_entry_btn,
                                 self._del_entry_btn)):
            row, col = divmod(i, self._last_action_columns)
            header_layout.addWidget(btn, row, col)
        self._add_entry_btn.clicked.connect(self._add_entry)
        self._add_entry_btn.setProperty("designAction", 'new')
        self._dup_entry_btn.clicked.connect(self._duplicate_entry)
        self._dup_entry_btn.setProperty("designAction", 'duplicate')
        self._del_entry_btn.clicked.connect(self._delete_entry)
        self._del_entry_btn.setProperty("designAction", 'delete')
        self._sort_entry_btn.clicked.connect(self._sort_entries)
        self._reset_chunk_btn.clicked.connect(self._reset_chunk)
        layout.addWidget(header)

        self._table = QTableWidget(panel)
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            self.t("ui_anmofs_col_index"),
            self.t("ui_anmofs_col_frame"),
            self.t("ui_anmofs_col_value_1"),
            self.t("ui_anmofs_col_value_2"),
            self.t("ui_anmofs_col_value_3"),
            self.t("ui_anmofs_col_value_4"),
            self.t("ui_anmofs_col_value_5"),
            self.t("ui_anmofs_col_value_6"),
        ])
        configure_table(self._table)
        self._table.setShowGrid(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        if self._grid_columns(2) == 1:
            self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self._table.horizontalHeader().setMinimumSectionSize(72)
            self._table.horizontalHeader().setDefaultSectionSize(92)
            self._table.setColumnWidth(0, 38)
        else:
            self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setMinimumHeight(260)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._table.itemChanged.connect(self._on_table_item_changed)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self._table)

        self._key_hint = QLabel(panel)
        self._key_hint.setWordWrap(True)
        self._key_hint.setStyleSheet(ss_dim_label())
        layout.addWidget(self._key_hint)

        self._editor_layout.addWidget(panel)
        self._rebuild_table(item)

    def _apply_key_field(self, field):
        row = self._selected_entry_idx
        if self._rebuilding or self._current_chunk is None or not 0 <= row < len(self._current_chunk.entries):
            return
        edit = self._key_fields[field]
        previous = getattr(self._current_chunk.entries[row], field)
        try:
            text = edit.text().strip()
            base = 0 if text.lower().lstrip('+-').startswith(('0x', '0b', '0o')) else 10
            value = int(text, base) if field == 'frame' else float(text)
            valid = -0x80000000 <= value <= 0x7fffffff if field == 'frame' else math.isfinite(value) and abs(value) <= 3.4028234663852886e38
            if not valid:
                raise ValueError
        except ValueError:
            edit.setText(str(previous) if field == 'frame' else self._fmt_float(previous))
            self._value_feedback.setText(self.t('anmofs_invalid_value'))
            self._value_feedback.show()
            return
        self._value_feedback.hide()
        if value != previous:
            self._table.item(row, ENTRY_FIELDS.index(field) + 1).setText(str(value) if field == 'frame' else text)
        self._sync_key_fields()

    def _sync_key_fields(self):
        row = self._selected_entry_idx
        entries = self._current_chunk.entries if self._current_chunk else []
        if hasattr(self, '_selected_key_title'):
            self._selected_key_title.setText(self.t('anmofs_selected_key', index=row) if 0 <= row < len(entries)
                                             else self.t('ui_anmofs_no_entry_selected'))
        for field, edit in getattr(self, '_key_fields', {}).items():
            edit.setEnabled(0 <= row < len(entries))
            if 0 <= row < len(entries):
                value = getattr(entries[row], field)
                text = str(value) if field == 'frame' else self._fmt_float(value)
                edit.setText(text)
                edit.setToolTip(self.t('anmofs_edit_value_hint') + '\n' + text)
            else:
                edit.clear()

    def _select_active_key(self):
        if self._current_chunk is None:
            return
        row = active_offset(self._current_chunk.entries, self._preview._frame, self._preview.view_rate)
        if row is not None:
            self._preview_key_selected(row)
            self._value_feedback.hide()
        else:
            self._value_feedback.setText(self.t('anmofs_no_active_key'))
            self._value_feedback.show()

    def _add_line_field(self, grid, row, col, key, label_text, value, width=None):
        wrap, _edit = self._make_editor_field(label_text, value, key, width=width)
        grid.addWidget(wrap, row, col)
        grid.setColumnStretch(col, 1)

    def _rebuild_table(self, item):
        self._rebuilding = True
        self._table.setRowCount(len(item.entries))
        states = key_states(item.entries)
        for row, entry in enumerate(item.entries):
            values = [
                str(row),
                str(entry.frame),
                self._fmt_float(entry.value_1),
                self._fmt_float(entry.value_2),
                self._fmt_float(entry.value_3),
                self._fmt_float(entry.value_4),
                self._fmt_float(entry.value_5),
                self._fmt_float(entry.value_6),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(self.t('anmofs_key_' + states[row]))
                if col == 0:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, cell)
        if 0 <= self._selected_entry_idx < len(item.entries):
            self._table.selectRow(self._selected_entry_idx)
        self._rebuilding = False
        self._sync_entry_buttons()
        self._sync_key_hint()
        if hasattr(self, "_preview") and self._current_chunk:
            self._preview.set_chunk(self._filepath, self._current_chunk)

    @staticmethod
    def _fmt_float(value):
        return f"{float(value):.9g}"

    def _on_meta_changed(self, *_args):
        self._push_undo_state()
        self._apply_meta_fields()
        self._sync_name_warning()
        self._refresh_chunk_buttons()
        self._filter_chunks()
        self._mark_dirty()
        self._preview.set_chunk(self._filepath, self._current_chunk)

    def _apply_meta_fields(self):
        item = self._current_chunk
        if item is None or not self._fields:
            return
        item.chunk_name = self._fields["chunk_name"].text()
        item.file_path = self._fields["file_path"].text()
        item.anm_name = self._fields["anm_name"].currentText()
        item.characode = self._fields["characode"].currentText()

    def _sync_name_warning(self):
        item = self._current_chunk
        if item is None or not hasattr(self, "_name_warning"):
            return
        if hasattr(self, '_intro_title'):
            attacker = self._preview._character_name(os.path.basename(self._filepath).removesuffix('_anmofs.xfbin'))
            if is_situation_finish_offsets(self._filepath):
                attacker = self.t('anmofs_situation_finish')
            receiver = self._preview._character_name(receiver_model_code(item))
            self._intro_title.setText(self.t('anmofs_edit_pair', attacker=attacker, receiver=receiver))
        code = receiver_code(item)
        text = self.t('anmofs_receiver_route', receiver=code, header=item.characode)
        if item.expected_chunk_name and item.chunk_name != item.expected_chunk_name:
            text += '\n' + self.t('ui_anmofs_name_mismatch', expected=item.expected_chunk_name)
        self._name_warning.setText(text)
        self._name_warning.setVisible(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_chunk is None or self._last_meta_columns is None:
            return
        columns = self._grid_columns(2)
        if columns == self._last_meta_columns and self._entry_action_columns() == getattr(self, '_last_action_columns', None):
            return
        self._apply_meta_fields()
        QTimer.singleShot(0, self._rebuild_current_chunk_for_width)

    def _rebuild_current_chunk_for_width(self):
        if self._current_chunk is not None:
            from core.ui.editor_chrome import capture_pending_fields
            restore = capture_pending_fields(self)
            self._build_editor(self._current_chunk)
            restore()

    def _on_table_selection_changed(self):
        if self._rebuilding or self._current_chunk is None:
            return
        rows = self._table.selectionModel().selectedRows()
        self._selected_entry_idx = rows[0].row() if rows else -1
        self._sync_entry_buttons()
        if self._selected_entry_idx >= 0:
            self._preview.seek_key(self._selected_entry_idx)
        self._sync_key_hint()

    def _sync_key_hint(self):
        self._sync_key_fields()
        if not hasattr(self, '_key_hint'):
            return
        row = self._selected_entry_idx
        entries = self._current_chunk.entries if self._current_chunk else []
        if not 0 <= row < len(entries):
            self._key_hint.setText(self.t('ui_anmofs_no_entry_selected'))
            return
        entry = entries[row]
        self._key_hint.setText(self.t('anmofs_key_detail', index=row, frame=entry.frame,
                                     ticks=key_tick(entry.frame, 60), seconds=entry.frame / 30)
                               + '\n' + self.t('anmofs_key_' + key_states(entries)[row]))

    def _on_table_item_changed(self, item):
        if self._rebuilding or self._current_chunk is None:
            return
        row = item.row()
        col = item.column()
        if row < 0 or row >= len(self._current_chunk.entries) or col <= 0:
            return
        entry = self._current_chunk.entries[row]
        text = item.text().strip()
        try:
            if col == 1:
                value = int(text or "0", 0)
                if not (-0x80000000 <= value <= 0x7FFFFFFF):
                    raise ValueError
                old_value = entry.frame
                if old_value != value:
                    self._push_undo_state()
                    entry.frame = value
            else:
                value = float(text or "0")
                if not math.isfinite(value) or abs(value) > 3.4028234663852886e38:
                    raise ValueError
                old_value = getattr(entry, ENTRY_FIELDS[col - 1])
                if old_value != value:
                    self._push_undo_state()
                    setattr(entry, ENTRY_FIELDS[col - 1], value)
        except ValueError:
            self._rebuilding = True
            old_value = entry.frame if col == 1 else getattr(entry, ENTRY_FIELDS[col - 1])
            item.setText(str(old_value) if col == 1 else self._fmt_float(old_value))
            self._rebuilding = False
            return
        self._mark_dirty()
        self._preview.set_chunk(self._filepath, self._current_chunk)
        states = key_states(self._current_chunk.entries)
        for r, state in enumerate(states):
            for c in range(self._table.columnCount()):
                self._table.item(r, c).setToolTip(self.t('anmofs_key_' + state))
        self._sync_key_hint()

    def _sync_entry_buttons(self):
        has_chunk = self._current_chunk is not None
        has_entry = has_chunk and bool(self._current_chunk.entries) and self._selected_entry_idx >= 0
        for btn in (getattr(self, "_add_entry_btn", None), getattr(self, "_sort_entry_btn", None), getattr(self, "_reset_chunk_btn", None)):
            if btn is not None:
                btn.setEnabled(has_chunk)
        for btn in (getattr(self, "_dup_entry_btn", None), getattr(self, "_del_entry_btn", None)):
            if btn is not None:
                btn.setEnabled(has_entry)

    def _add_chunk(self):
        if self._xfbin is None:
            return
        self._push_undo_state()
        name = self._unique_chunk_name("anmofs_entry")
        item = make_default_chunk(name)
        append_chunk_page(self._xfbin, item)
        self._chunks.append(item)
        self._chunk_snapshots[id(item.chunk)] = copy.deepcopy(item)
        self._selected_entry_idx = 0
        self._rebuild_chunk_list()
        self._current_chunk = None
        self._select_chunk(item)
        self._mark_dirty()

    def _duplicate_chunk(self):
        if self._xfbin is None or self._current_chunk is None:
            return
        self._push_undo_state()
        name = self._unique_chunk_name(f"{self._current_chunk.chunk_name}_copy")
        item = duplicate_anmofs_chunk(self._current_chunk, name)
        append_chunk_page(self._xfbin, item)
        self._chunks.append(item)
        self._chunk_snapshots[id(item.chunk)] = copy.deepcopy(item)
        self._selected_entry_idx = 0 if item.entries else -1
        self._rebuild_chunk_list()
        self._current_chunk = None
        self._select_chunk(item)
        self._mark_dirty()

    def _delete_chunk(self):
        if self._xfbin is None or self._current_chunk is None:
            return
        if len(self._chunks) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("ui_anmofs_cannot_delete_last_chunk"))
            return
        item = self._current_chunk
        reply = QMessageBox.question(
            self,
            self.t("dlg_title_confirm_delete"),
            self.t("ui_anmofs_delete_chunk_confirm", name=item.chunk_name),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._push_undo_state()
        for page in list(self._xfbin.pages):
            if item.chunk in page.chunks:
                page.chunks.remove(item.chunk)
                if not any(hasattr(chunk, "binary_data") for chunk in page.chunks):
                    try:
                        self._xfbin.pages.remove(page)
                    except ValueError:
                        pass
                break
        idx = self._chunks.index(item)
        self._chunks.remove(item)
        self._chunk_snapshots.pop(id(item.chunk), None)
        self._current_chunk = None
        self._rebuild_chunk_list()
        self._select_chunk(self._chunks[min(idx, len(self._chunks) - 1)])
        self._mark_dirty()

    def _add_entry(self):
        item = self._current_chunk
        if item is None:
            return
        self._push_undo_state()
        source = item.entries[self._selected_entry_idx] if 0 <= self._selected_entry_idx < len(item.entries) else AnmofsEntry()
        new_entry = copy.deepcopy(source)
        new_entry.frame = int(new_entry.frame) + 1
        insert_at = self._selected_entry_idx + 1 if self._selected_entry_idx >= 0 else len(item.entries)
        item.entries.insert(insert_at, new_entry)
        self._selected_entry_idx = insert_at
        self._rebuild_table(item)
        self._refresh_chunk_buttons()
        self._mark_dirty()

    def _duplicate_entry(self):
        item = self._current_chunk
        if item is None or not item.entries:
            return
        self._push_undo_state()
        idx = self._selected_entry_idx if 0 <= self._selected_entry_idx < len(item.entries) else 0
        item.entries.insert(idx + 1, copy.deepcopy(item.entries[idx]))
        self._selected_entry_idx = idx + 1
        self._rebuild_table(item)
        self._refresh_chunk_buttons()
        self._mark_dirty()

    def _delete_entry(self):
        item = self._current_chunk
        if item is None or not item.entries:
            return
        self._push_undo_state()
        idx = self._selected_entry_idx if 0 <= self._selected_entry_idx < len(item.entries) else len(item.entries) - 1
        item.entries.pop(idx)
        self._selected_entry_idx = min(idx, len(item.entries) - 1)
        self._rebuild_table(item)
        self._refresh_chunk_buttons()
        self._mark_dirty()

    def _sort_entries(self):
        item = self._current_chunk
        if item is None:
            return
        self._push_undo_state()
        selected = item.entries[self._selected_entry_idx] if 0 <= self._selected_entry_idx < len(item.entries) else None
        item.entries.sort(key=lambda entry: entry.frame)
        self._selected_entry_idx = item.entries.index(selected) if selected in item.entries else (0 if item.entries else -1)
        self._rebuild_table(item)
        self._mark_dirty()

    def _reset_chunk(self):
        item = self._current_chunk
        if item is None:
            return
        snapshot = self._chunk_snapshots.get(id(item.chunk))
        if snapshot is None:
            return
        self._push_undo_state()
        item.chunk_name = snapshot.chunk_name
        item.file_path = snapshot.file_path
        item.anm_name = snapshot.anm_name
        item.characode = snapshot.characode
        item.reserved = snapshot.reserved
        item.entries = copy.deepcopy(snapshot.entries)
        self._selected_entry_idx = 0 if item.entries else -1
        self._build_editor(item)
        self._refresh_chunk_buttons()
        self._filter_chunks()
        self._mark_dirty()

    def _unique_chunk_name(self, base):
        existing = {item.chunk_name.lower() for item in self._chunks}
        candidate = base
        suffix = 1
        while candidate.lower() in existing:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _refresh_selected_ui(self):
        if self._current_chunk is not None:
            self._build_editor(self._current_chunk)
            self._refresh_chunk_buttons()
            self._filter_chunks()

    def _mark_dirty(self, *_args):
        if self._filepath:
            self._dirty = True
            self._save_btn.setEnabled(True)
            set_file_label(self._file_label, self._filepath, dirty=True)

    def _push_undo_state(self):
        if self._restoring_history:
            return
        state = self.get_undo_state()
        if state is not None:
            self._history.push(state)

    def get_undo_state(self):
        if self._xfbin is None:
            return None
        current_index = -1
        if self._current_chunk in self._chunks:
            current_index = self._chunks.index(self._current_chunk)
        return copy.deepcopy({
            "xfbin": self._xfbin,
            "chunks": self._chunks,
            "chunk_snapshots": self._chunk_snapshots,
            "current_index": current_index,
            "selected_entry_idx": self._selected_entry_idx,
        })

    def restore_undo_state(self, state):
        if not state:
            return False
        self._restoring_history = True
        try:
            self._xfbin = state["xfbin"]
            self._chunks = state["chunks"]
            self._chunk_snapshots = state.get("chunk_snapshots", {})
            self._selected_entry_idx = int(state.get("selected_entry_idx", -1))
            current_index = int(state.get("current_index", -1))
            self._current_chunk = None
            self._rebuild_chunk_list()
            if 0 <= current_index < len(self._chunks):
                self._select_chunk(self._chunks[current_index])
            else:
                self._show_placeholder()
            self._mark_dirty()
        finally:
            self._restoring_history = False
        return True

    def apply_pending_edits(self):
        pending = {field: edit.text() for field, edit in getattr(self, '_key_fields', {}).items()}
        for field, text in pending.items():
            self._key_fields[field].setText(text)
            self._apply_key_field(field)
        self._apply_meta_fields()

    def get_saved_state(self):
        return copy.deepcopy(self._saved_chunks)

    def get_current_state(self):
        self.apply_pending_edits()
        return copy.deepcopy(self._chunks)

    def get_change_summary(self):
        return self.describe_state_diff(self.get_saved_state(), self.get_current_state())

    def load_comparison_state(self, path):
        _xfbin, chunks = load_anmofs_xfbin(path)
        return copy.deepcopy(chunks)

    def describe_state_diff(self, before, after):
        before_map = {item.chunk_name: item for item in before or []}
        after_map = {item.chunk_name: item for item in after or []}
        changes = []
        for name, after_item in after_map.items():
            before_item = before_map.get(name)
            if before_item is None:
                changes.append(ChangeItem(f"chunk:{name}", "added", self.t("qol_diff_added", item=name), "", "", True))
                continue
            for field in ("file_path", "anm_name", "characode", "reserved"):
                before_value = getattr(before_item, field)
                after_value = getattr(after_item, field)
                if before_value != after_value:
                    changes.append(ChangeItem(
                        f"meta:{name}:{field}",
                        "changed",
                        f"{name} / {field}",
                        str(before_value),
                        str(after_value),
                        True,
                    ))
            max_entries = max(len(before_item.entries), len(after_item.entries))
            for idx in range(max_entries):
                if idx >= len(before_item.entries):
                    changes.append(ChangeItem(
                        f"entryadd:{name}:{idx}",
                        "added",
                        self.t("qol_diff_added", item=f"{name} entry {idx}"),
                        "",
                        "",
                        True,
                    ))
                    continue
                if idx >= len(after_item.entries):
                    changes.append(ChangeItem(
                        f"entry:{name}:{idx}",
                        "removed",
                        self.t("qol_diff_removed", item=f"{name} entry {idx}"),
                        "",
                        "",
                        False,
                    ))
                    continue
                before_entry = before_item.entries[idx]
                after_entry = after_item.entries[idx]
                for field in ENTRY_FIELDS:
                    before_value = getattr(before_entry, field)
                    after_value = getattr(after_entry, field)
                    if before_value != after_value:
                        changes.append(ChangeItem(
                            f"entry:{name}:{idx}:{field}",
                            "changed",
                            f"{name} / entry {idx} / {field}",
                            str(before_value),
                            str(after_value),
                            True,
                        ))
        for name in before_map:
            if name not in after_map:
                changes.append(ChangeItem(f"chunk:{name}", "removed", self.t("qol_diff_removed", item=name), "", "", False))
        return changes

    def copy_from_state(self, external_state, item_ids):
        if not item_ids:
            return
        self.apply_pending_edits()
        self._push_undo_state()
        external_map = {item.chunk_name: item for item in external_state or []}
        current_map = {item.chunk_name: item for item in self._chunks}
        selected = None
        for item_id in item_ids:
            parts = item_id.split(":")
            if len(parts) < 2:
                continue
            kind, name = parts[0], parts[1]
            source = external_map.get(name)
            if source is None:
                continue
            target = current_map.get(name)
            if kind == "chunk" and target is None:
                copied = duplicate_anmofs_chunk(source, source.chunk_name)
                append_chunk_page(self._xfbin, copied)
                self._chunks.append(copied)
                self._chunk_snapshots[id(copied.chunk)] = copy.deepcopy(copied)
                current_map[copied.chunk_name] = copied
                selected = copied
            elif kind == "meta" and len(parts) == 3 and target is not None:
                setattr(target, parts[2], copy.deepcopy(getattr(source, parts[2])))
                selected = target
            elif kind == "entryadd" and len(parts) == 3 and target is not None:
                idx = int(parts[2])
                if 0 <= idx < len(source.entries):
                    target.entries.insert(min(idx, len(target.entries)), copy.deepcopy(source.entries[idx]))
                    selected = target
            elif kind == "entry" and len(parts) == 4 and target is not None:
                idx = int(parts[2])
                field = parts[3]
                if 0 <= idx < len(source.entries):
                    while len(target.entries) <= idx:
                        target.entries.append(AnmofsEntry())
                    setattr(target.entries[idx], field, copy.deepcopy(getattr(source.entries[idx], field)))
                    selected = target
        self._rebuild_chunk_list()
        if selected in self._chunks:
            self._current_chunk = None
            self._select_chunk(selected)
        self._mark_dirty()

    def shortcut_action(self, action_id: str) -> bool:
        if action_id == "editor.undo":
            self.apply_pending_edits()
            state = self._history.undo(self.get_undo_state())
            return self.restore_undo_state(state)
        if action_id == "editor.redo":
            state = self._history.redo(self.get_undo_state())
            return self.restore_undo_state(state)
        if action_id == "editor.new":
            self._add_entry() if self._table_has_focus() else self._add_chunk()
            return True
        if action_id == "editor.duplicate":
            self._duplicate_entry() if self._table_has_focus() else self._duplicate_chunk()
            return True
        if action_id == "editor.delete":
            self._delete_entry() if self._table_has_focus() else self._delete_chunk()
            return True
        return False

    def _table_has_focus(self) -> bool:
        table = getattr(self, "_table", None)
        if table is None:
            return False
        focus = QApplication.focusWidget()
        return focus is table or (focus is not None and table.isAncestorOf(focus))
