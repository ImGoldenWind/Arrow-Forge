from __future__ import annotations

import copy
import os
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    ss_accent_sep,
    ss_bg_panel,
    ss_btn,
    ss_dim_label,
    ss_editor_card,
    ss_error_label,
    ss_field_label,
    ss_file_label,
    ss_input,
    ss_main_label,
    ss_placeholder,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_search,
    ss_sep,
    ss_sidebar_btn,
    ss_table,
    ss_transparent,
)
from parsers.anmofs_parser import (
    AnmofsEntry,
    append_chunk_page,
    duplicate_anmofs_chunk,
    load_anmofs_xfbin,
    make_default_chunk,
    save_anmofs_xfbin,
)


ENTRY_FIELDS = ("frame", "value_1", "value_2", "value_3", "value_4", "value_5", "value_6")


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
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
        self._chunk_snapshots = {}
        self._current_chunk = None
        self._chunk_buttons = []
        self._fields = {}
        self._dirty = False
        self._rebuilding = False
        self._selected_entry_idx = -1

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._build_ui(root)

    def _build_ui(self, root):
        top = QFrame(self)
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(6)

        open_btn = QPushButton(self.t("btn_open_file"), top)
        open_btn.setFixedHeight(TOOLBAR_BTN_H)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._load_file)
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"), top)
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"), top)
        self._file_label.setFont(QFont("Consolas", 11))
        self._file_label.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_label, 1)
        root.addWidget(top)

        sep = QFrame(self)
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        main = QWidget(self)
        main.setStyleSheet(ss_transparent())
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_sidebar(main, main_layout)

        vsep = QFrame(main)
        vsep.setFixedWidth(1)
        vsep.setStyleSheet(ss_sep())
        main_layout.addWidget(vsep)

        self._editor_scroll = QScrollArea(main)
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_transparent())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(10)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder()
        root.addWidget(main, 1)

    def _build_sidebar(self, parent, main_layout):
        side = QFrame(parent)
        side.setFixedWidth(260)
        side.setStyleSheet(ss_bg_panel())
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 8, 8, 4)
        side_layout.setSpacing(4)

        self._search = QLineEdit(side)
        self._search.setPlaceholderText(self.t("search_placeholder"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_chunks)
        side_layout.addWidget(self._search)

        actions = QWidget(side)
        actions.setStyleSheet("QWidget { background: transparent; border: none; }")
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        self._add_chunk_btn = QPushButton(self.t("btn_new"), actions)
        self._dup_chunk_btn = QPushButton(self.t("btn_duplicate"), actions)
        self._del_chunk_btn = QPushButton(self.t("btn_delete"), actions)
        for btn in (self._add_chunk_btn, self._dup_chunk_btn, self._del_chunk_btn):
            btn.setFixedHeight(28)
            btn.setEnabled(False)
            btn.setFont(QFont("Segoe UI", 10))
            actions_layout.addWidget(btn, 1)
        self._add_chunk_btn.setStyleSheet(ss_btn())
        self._dup_chunk_btn.setStyleSheet(ss_btn())
        self._del_chunk_btn.setStyleSheet(ss_btn(danger=True))
        self._add_chunk_btn.clicked.connect(self._add_chunk)
        self._dup_chunk_btn.clicked.connect(self._duplicate_chunk)
        self._del_chunk_btn.clicked.connect(self._delete_chunk)
        side_layout.addWidget(actions)

        self._chunk_scroll = QScrollArea(side)
        self._chunk_scroll.setWidgetResizable(True)
        self._chunk_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chunk_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._chunk_list_widget = QWidget()
        self._chunk_list_widget.setStyleSheet(ss_transparent())
        self._chunk_list_layout = QVBoxLayout(self._chunk_list_widget)
        self._chunk_list_layout.setContentsMargins(0, 0, 0, 0)
        self._chunk_list_layout.setSpacing(0)
        self._chunk_list_layout.addStretch()
        self._chunk_scroll.setWidget(self._chunk_list_widget)
        side_layout.addWidget(self._chunk_scroll, 1)
        main_layout.addWidget(side)

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        label = QLabel(self.t("ui_anmofs_open_file_to_begin_editing"), self._editor_widget)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(QFont("Segoe UI", 16))
        label.setStyleSheet(ss_placeholder())
        self._editor_layout.addWidget(label, 1)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("ui_anmofs_open_title"),
            game_files_dialog_dir(target_patterns="*_anmofs.xfbin"),
            self.t("ui_anmofs_file_filter"),
        )
        if not path:
            return
        create_backup_on_open(path)
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
        self._chunk_snapshots = {}
        self._current_chunk = None
        self._dirty = False
        self._set_controls_enabled(False)
        self._rebuild_chunk_list()
        self._show_placeholder()
        set_file_label_empty(self._file_label, self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, xfbin, chunks):
        self._filepath = path
        self._xfbin = xfbin
        self._chunks = list(chunks)
        self._chunk_snapshots = {id(item.chunk): copy.deepcopy(item) for item in self._chunks}
        self._current_chunk = None
        self._dirty = False
        set_file_label(self._file_label, path)
        self._set_controls_enabled(True)
        self._rebuild_chunk_list()
        if self._chunks:
            self._select_chunk(self._chunks[0])

    def _save_file(self):
        if self._xfbin is None or not self._filepath:
            return
        self._apply_meta_fields()
        try:
            save_anmofs_xfbin(self._xfbin, self._filepath, self._chunks)
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_save_error", error=exc))
            return
        self._dirty = False
        self._chunk_snapshots = {id(item.chunk): copy.deepcopy(item) for item in self._chunks}
        set_file_label(self._file_label, self._filepath)
        self._refresh_selected_ui()
        QMessageBox.information(
            self,
            self.t("dlg_title_success"),
            self.t("msg_save_success", path=os.path.basename(self._filepath)),
        )

    def _set_controls_enabled(self, enabled):
        self._save_btn.setEnabled(bool(enabled and self._filepath))
        for btn in (self._add_chunk_btn, self._dup_chunk_btn, self._del_chunk_btn):
            btn.setEnabled(bool(enabled))

    def _rebuild_chunk_list(self):
        _clear_layout(self._chunk_list_layout)
        self._chunk_buttons = []
        for item in self._chunks:
            btn = QPushButton(self._chunk_list_widget)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(ss_sidebar_btn(item is self._current_chunk))
            btn.clicked.connect(lambda checked=False, chunk=item: self._select_chunk(chunk))

            layout = QVBoxLayout(btn)
            layout.setContentsMargins(10, 3, 10, 3)
            layout.setSpacing(0)
            title = QLabel(item.chunk_name or self.t("ui_anmofs_unnamed_chunk"), btn)
            title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            title.setStyleSheet(ss_main_label())
            title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            subtitle = QLabel(item.characode, btn)
            subtitle.setFont(QFont("Consolas", 11))
            subtitle.setStyleSheet(ss_dim_label())
            subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(title)
            layout.addWidget(subtitle)

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
            )).lower()
            btn.setVisible(query in haystack)

    def _select_chunk(self, item):
        if item is self._current_chunk:
            return
        self._apply_meta_fields()
        self._current_chunk = item
        self._selected_entry_idx = 0 if item.entries else -1
        self._build_editor(item)
        self._refresh_chunk_buttons()

    def _refresh_chunk_buttons(self):
        for btn, item, title, subtitle in self._chunk_buttons:
            btn.setStyleSheet(ss_sidebar_btn(item is self._current_chunk))
            title.setText(item.chunk_name or self.t("ui_anmofs_unnamed_chunk"))
            subtitle.setText(item.characode)

    def _build_editor(self, item):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._editor_layout.setContentsMargins(10, 8, 10, 0)
        self._editor_layout.setSpacing(12)

        self._build_metadata_panel(item)
        self._build_entries_panel(item)
        self._editor_layout.addStretch()
        self._sync_name_warning()

    def _make_editor_card(self, margins=(16, 14, 16, 14), spacing=10):
        card = QFrame(self._editor_widget)
        card.setObjectName("EditorCard")
        card.setStyleSheet(ss_editor_card())
        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(inner)
        return card, layout

    def _make_editor_field(self, label_text, value, key, *, value_font=None, height=30, width=None):
        wrap = QWidget(self._editor_widget)
        wrap.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(label_text, wrap)
        label.setFont(QFont("Segoe UI", 12))
        label.setStyleSheet(ss_field_label())
        edit = QLineEdit(wrap)
        edit.setText(str(value))
        edit.setFixedHeight(height)
        if width:
            edit.setFixedWidth(width)
        edit.setFont(value_font or QFont("Consolas", 13))
        edit.setStyleSheet(ss_input())
        edit.textEdited.connect(self._on_meta_changed)
        layout.addWidget(label)
        layout.addWidget(edit)
        self._fields[key] = edit
        return wrap, edit

    def _build_metadata_panel(self, item):
        panel, layout = self._make_editor_card(margins=(16, 14, 16, 14), spacing=10)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        layout.addLayout(grid)

        self._add_line_field(grid, 0, 0, "chunk_name", self.t("ui_anmofs_chunk_name"), item.chunk_name)
        self._add_line_field(grid, 0, 1, "file_path", self.t("ui_anmofs_file_path"), item.file_path)
        self._add_line_field(grid, 1, 0, "anm_name", self.t("ui_anmofs_animation_name"), item.anm_name)
        self._add_line_field(grid, 1, 1, "characode", self.t("ui_anmofs_characode"), item.characode)
        self._add_line_field(grid, 1, 2, "reserved", self.t("ui_anmofs_reserved"), str(item.reserved), width=120)

        self._name_warning = QLabel("", panel)
        self._name_warning.setWordWrap(True)
        self._name_warning.setFont(QFont("Segoe UI", 10))
        self._name_warning.setStyleSheet(ss_error_label())
        layout.addWidget(self._name_warning)

        self._editor_layout.addWidget(panel)

    def _build_entries_panel(self, item):
        panel, layout = self._make_editor_card(margins=(16, 14, 16, 14), spacing=10)

        header = QWidget(panel)
        header.setStyleSheet(ss_transparent())
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addStretch()

        self._add_entry_btn = QPushButton(self.t("btn_new"), header)
        self._dup_entry_btn = QPushButton(self.t("btn_duplicate"), header)
        self._del_entry_btn = QPushButton(self.t("btn_delete"), header)
        self._sort_entry_btn = QPushButton(self.t("ui_anmofs_sort_entries"), header)
        self._reset_chunk_btn = QPushButton(self.t("ui_anmofs_reset_chunk"), header)
        for btn in (self._add_entry_btn, self._dup_entry_btn, self._sort_entry_btn, self._reset_chunk_btn):
            btn.setFixedHeight(28)
            btn.setStyleSheet(ss_btn())
            header_layout.addWidget(btn)
        self._del_entry_btn.setFixedHeight(28)
        self._del_entry_btn.setStyleSheet(ss_btn(danger=True))
        header_layout.addWidget(self._del_entry_btn)
        self._add_entry_btn.clicked.connect(self._add_entry)
        self._dup_entry_btn.clicked.connect(self._duplicate_entry)
        self._del_entry_btn.clicked.connect(self._delete_entry)
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
        self._table.setStyleSheet(ss_table())
        self._table.setShowGrid(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setMinimumHeight(260)
        self._table.itemChanged.connect(self._on_table_item_changed)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self._table)

        self._editor_layout.addWidget(panel)
        self._rebuild_table(item)

    def _add_line_field(self, grid, row, col, key, label_text, value, width=None):
        wrap, _edit = self._make_editor_field(label_text, value, key, width=width)
        grid.addWidget(wrap, row, col)
        grid.setColumnStretch(col, 1)

    def _rebuild_table(self, item):
        self._rebuilding = True
        self._table.setRowCount(len(item.entries))
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
                if col == 0:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, cell)
        if 0 <= self._selected_entry_idx < len(item.entries):
            self._table.selectRow(self._selected_entry_idx)
        self._rebuilding = False
        self._sync_entry_buttons()

    @staticmethod
    def _fmt_float(value):
        return f"{float(value):.6g}"

    def _on_meta_changed(self):
        self._apply_meta_fields()
        self._sync_name_warning()
        self._refresh_chunk_buttons()
        self._filter_chunks()
        self._mark_dirty()

    def _apply_meta_fields(self):
        item = self._current_chunk
        if item is None or not self._fields:
            return
        item.chunk_name = self._fields["chunk_name"].text().strip()
        item.file_path = self._fields["file_path"].text().strip()
        item.anm_name = self._fields["anm_name"].text().strip()
        item.characode = self._fields["characode"].text().strip()
        try:
            reserved = int(self._fields["reserved"].text().strip() or "0", 0)
            if 0 <= reserved <= 0xFFFFFFFF:
                item.reserved = reserved
        except ValueError:
            pass

    def _sync_name_warning(self):
        item = self._current_chunk
        if item is None or not hasattr(self, "_name_warning"):
            return
        expected = item.expected_chunk_name
        if expected and item.chunk_name != expected:
            self._name_warning.setText(self.t("ui_anmofs_name_mismatch", expected=expected))
            self._name_warning.setVisible(True)
        else:
            self._name_warning.setText("")
            self._name_warning.setVisible(False)

    def _on_table_selection_changed(self):
        if self._rebuilding or self._current_chunk is None:
            return
        rows = self._table.selectionModel().selectedRows()
        self._selected_entry_idx = rows[0].row() if rows else -1
        self._sync_entry_buttons()

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
                if not (0 <= value <= 0xFFFFFFFF):
                    raise ValueError
                entry.frame = value
            else:
                setattr(entry, ENTRY_FIELDS[col - 1], float(text or "0"))
        except ValueError:
            self._rebuilding = True
            old_value = entry.frame if col == 1 else getattr(entry, ENTRY_FIELDS[col - 1])
            item.setText(str(old_value) if col == 1 else self._fmt_float(old_value))
            self._rebuilding = False
            return
        self._mark_dirty()

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
