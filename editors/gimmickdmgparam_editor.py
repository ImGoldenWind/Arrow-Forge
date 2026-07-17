from __future__ import annotations

import copy
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
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
    ss_transparent,
)
from parsers.gimmickdmgparam_parser import (
    FIELD_SPECS,
    float_to_word,
    load_gimmickdmgparam_xfbin,
    make_default_entry,
    save_gimmickdmgparam_xfbin,
    word_to_float,
)


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


class GimmickDmgParamEditor(QWidget):
    _load_done_signal = pyqtSignal(str, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self.t = t or (lambda key, **kwargs: key)
        self.setStyleSheet(ss_transparent())

        self._filepath = None
        self._xfbin = None
        self._item = None
        self._snapshots = []
        self._current_idx = -1
        self._entry_buttons = []
        self._header_fields = {}
        self._record_fields = {}
        self._dirty = False

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
        self._search.textChanged.connect(self._filter_entries)
        side_layout.addWidget(self._search)

        actions = QWidget(side)
        actions.setStyleSheet(ss_transparent())
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        self._add_btn = QPushButton(self.t("btn_new"), actions)
        self._dup_btn = QPushButton(self.t("btn_duplicate"), actions)
        self._del_btn = QPushButton(self.t("btn_delete"), actions)
        for btn in (self._add_btn, self._dup_btn, self._del_btn):
            btn.setFixedHeight(28)
            btn.setEnabled(False)
            btn.setFont(QFont("Segoe UI", 10))
            actions_layout.addWidget(btn, 1)
        self._add_btn.setStyleSheet(ss_btn())
        self._dup_btn.setStyleSheet(ss_btn())
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._add_btn.clicked.connect(self._add_entry)
        self._dup_btn.clicked.connect(self._duplicate_entry)
        self._del_btn.clicked.connect(self._delete_entry)
        side_layout.addWidget(actions)

        self._entry_scroll = QScrollArea(side)
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(0)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        side_layout.addWidget(self._entry_scroll, 1)
        main_layout.addWidget(side)

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        self._header_fields = {}
        self._record_fields = {}
        label = QLabel(self.t("ui_gimmickdmg_open_file_to_begin_editing"), self._editor_widget)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(QFont("Segoe UI", 16))
        label.setStyleSheet(ss_placeholder())
        self._editor_layout.addWidget(label, 1)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("ui_gimmickdmg_open_title"),
            game_files_dialog_dir(target_patterns="gimmickDmgParam.bin.xfbin"),
            self.t("ui_gimmickdmg_file_filter"),
        )
        if not path:
            return
        create_backup_on_open(path)
        set_file_label_empty(self._file_label, self.t("loading"))
        self._set_controls_enabled(False)
        self._show_placeholder()

        def worker():
            try:
                xfbin, item = load_gimmickdmgparam_xfbin(path)
            except Exception as exc:
                self._load_error_signal.emit(str(exc))
                return
            self._load_done_signal.emit(path, xfbin, item)

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_error(self, msg):
        self._filepath = None
        self._xfbin = None
        self._item = None
        self._current_idx = -1
        self._snapshots = []
        self._rebuild_entry_list()
        self._show_placeholder()
        self._set_controls_enabled(False)
        set_file_label_empty(self._file_label, self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), msg)

    def _on_load_done(self, path, xfbin, item):
        self._filepath = path
        self._xfbin = xfbin
        self._item = item
        self._snapshots = [copy.deepcopy(entry) for entry in item.entries]
        self._current_idx = 0 if item.entries else -1
        self._dirty = False
        self._save_btn.setEnabled(False)
        set_file_label(self._file_label, path, dirty=False)
        self._set_controls_enabled(True)
        self._rebuild_entry_list()
        if self._current_idx >= 0:
            self._build_editor()
        else:
            self._show_placeholder()

    def _set_controls_enabled(self, enabled):
        for btn in (self._add_btn, self._dup_btn, self._del_btn):
            btn.setEnabled(enabled and self._item is not None)

    def _save_file(self):
        if self._xfbin is None or self._item is None or not self._filepath:
            return
        self._apply_editor_fields()
        try:
            save_gimmickdmgparam_xfbin(self._xfbin, self._filepath, self._item)
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_save_error", error=exc))
            return
        self._snapshots = [copy.deepcopy(entry) for entry in self._item.entries]
        self._dirty = False
        self._save_btn.setEnabled(False)
        set_file_label(self._file_label, self._filepath, dirty=False)

    def _make_entry_button(self, idx, entry):
        btn = QPushButton(self._entry_list_widget)
        btn.setFixedHeight(48)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))

        inner = QWidget(btn)
        inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(1)

        title = entry.stage_id or self.t("ui_gimmickdmg_blank_stage")
        title_label = QLabel(title, inner)
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_label.setStyleSheet(ss_main_label())
        layout.addWidget(title_label)

        subtitle = entry.damage_id or self.t("ui_gimmickdmg_blank_damage")
        sub_label = QLabel(self.t("ui_gimmickdmg_entry_subtitle", index=idx, damage=subtitle), inner)
        sub_label.setFont(QFont("Consolas", 10))
        sub_label.setStyleSheet(ss_dim_label())
        layout.addWidget(sub_label)

        outer = QHBoxLayout(btn)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(inner)
        btn.clicked.connect(lambda _checked=False, i=idx: self._select_entry(i))
        return btn

    def _rebuild_entry_list(self, filter_text=""):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []
        if self._item is None:
            return
        needle = filter_text.strip().lower()
        for idx, entry in enumerate(self._item.entries):
            hay = f"{entry.stage_id} {entry.damage_id} {idx}".lower()
            if needle and needle not in hay:
                continue
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((idx, btn))

    def _filter_entries(self):
        self._rebuild_entry_list(self._search.text())

    def _select_entry(self, idx):
        if self._item is None or idx < 0 or idx >= len(self._item.entries):
            return
        self._apply_editor_fields()
        self._current_idx = idx
        self._build_editor()
        self._filter_entries()

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

    def _add_title(self, layout, title_key, hint_key=None):
        title = QLabel(self.t(title_key), self._editor_widget)
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        layout.addWidget(title)
        if hint_key:
            hint = QLabel(self.t(hint_key), self._editor_widget)
            hint.setWordWrap(True)
            hint.setFont(QFont("Segoe UI", 10))
            hint.setStyleSheet(ss_dim_label())
            layout.addWidget(hint)

    def _make_field(self, label_text, value_text, on_change, *, width=None):
        wrap = QWidget(self._editor_widget)
        wrap.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(label_text, wrap)
        label.setFont(QFont("Segoe UI", 11))
        label.setStyleSheet(ss_field_label())
        edit = QLineEdit(str(value_text), wrap)
        edit.setFixedHeight(30)
        if width:
            edit.setFixedWidth(width)
        edit.setFont(QFont("Consolas", 12))
        edit.setStyleSheet(ss_input())
        edit.textEdited.connect(on_change)
        layout.addWidget(label)
        layout.addWidget(edit)
        return wrap, edit

    def _build_editor(self):
        if self._item is None:
            self._show_placeholder()
            return
        _clear_layout(self._editor_layout)
        self._header_fields = {}
        self._record_fields = {}

        self._build_layout_panel()
        self._build_header_panel()
        if 0 <= self._current_idx < len(self._item.entries):
            self._build_record_panel(self._item.entries[self._current_idx])
        self._editor_layout.addStretch()

    def _build_layout_panel(self):
        panel, layout = self._make_editor_card()
        self._add_title(layout, "ui_gimmickdmg_layout_title", "ui_gimmickdmg_layout_hint")
        self._editor_layout.addWidget(panel)

    def _build_header_panel(self):
        panel, layout = self._make_editor_card()
        self._add_title(layout, "ui_gimmickdmg_header_title")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        layout.addLayout(grid)

        fields = [
            ("chunk_name", self.t("ui_gimmickdmg_chunk_name"), self._item.chunk_name),
            ("file_path", self.t("ui_gimmickdmg_file_path"), self._item.file_path),
            ("magic", self.t("ui_gimmickdmg_header_magic"), self._item.magic),
            ("count", self.t("ui_gimmickdmg_header_count"), len(self._item.entries)),
            ("unknown_08", self.t("ui_gimmickdmg_header_unknown_08"), self._item.unknown_08),
            ("reserved_0c", self.t("ui_gimmickdmg_header_reserved_0c"), self._item.reserved_0c),
        ]
        for idx, (key, label, value) in enumerate(fields):
            wrap, edit = self._make_field(label, value, self._on_header_changed)
            if key == "count":
                edit.setReadOnly(True)
            self._header_fields[key] = edit
            grid.addWidget(wrap, idx // 3, idx % 3)
            grid.setColumnStretch(idx % 3, 1)
        self._editor_layout.addWidget(panel)

    def _build_record_panel(self, entry):
        panel, layout = self._make_editor_card()
        self._add_title(layout, "ui_gimmickdmg_record_title", "ui_gimmickdmg_record_hint")

        strings_grid = QGridLayout()
        strings_grid.setContentsMargins(0, 0, 0, 0)
        strings_grid.setHorizontalSpacing(16)
        strings_grid.setVerticalSpacing(10)
        layout.addLayout(strings_grid)

        stage_wrap, stage_edit = self._make_field(
            self.t("ui_gimmickdmg_stage_id"),
            entry.stage_id,
            self._on_record_changed,
        )
        damage_wrap, damage_edit = self._make_field(
            self.t("ui_gimmickdmg_damage_id"),
            entry.damage_id,
            self._on_record_changed,
        )
        self._record_fields["stage_id"] = stage_edit
        self._record_fields["damage_id"] = damage_edit
        strings_grid.addWidget(stage_wrap, 0, 0)
        strings_grid.addWidget(damage_wrap, 0, 1)

        warn = QLabel(self.t("ui_gimmickdmg_string_pointer_note"), panel)
        warn.setWordWrap(True)
        warn.setFont(QFont("Segoe UI", 10))
        warn.setStyleSheet(ss_error_label())
        layout.addWidget(warn)

        raw_grid = QGridLayout()
        raw_grid.setContentsMargins(0, 0, 0, 0)
        raw_grid.setHorizontalSpacing(14)
        raw_grid.setVerticalSpacing(10)
        layout.addLayout(raw_grid)

        for idx, (key, offset, kind) in enumerate(FIELD_SPECS):
            word_idx = offset // 4
            raw = entry.words[word_idx]
            value_text = self._format_field(raw, kind)
            label = self.t(f"ui_gimmickdmg_field_{key}")
            wrap, edit = self._make_field(label, value_text, self._on_record_changed)
            self._record_fields[key] = edit
            raw_grid.addWidget(wrap, idx // 3, idx % 3)
            raw_grid.setColumnStretch(idx % 3, 1)

        self._editor_layout.addWidget(panel)

    @staticmethod
    def _format_field(raw, kind):
        if kind == "f32":
            return f"{word_to_float(raw):.6g}"
        if raw == 0xFFFFFFFF:
            return "-1"
        return str(raw)

    def _parse_u32_text(self, text):
        text = text.strip() or "0"
        value = int(text, 0)
        if value == -1:
            return 0xFFFFFFFF
        if not (0 <= value <= 0xFFFFFFFF):
            raise ValueError
        return value

    def _on_header_changed(self):
        self._apply_header_fields()
        self._mark_dirty()

    def _on_record_changed(self):
        self._apply_record_fields()
        self._filter_entries()
        self._mark_dirty()

    def _apply_editor_fields(self):
        self._apply_header_fields()
        self._apply_record_fields()

    def _apply_header_fields(self):
        if self._item is None or not self._header_fields:
            return
        self._item.chunk_name = self._header_fields["chunk_name"].text().strip()
        self._item.file_path = self._header_fields["file_path"].text().strip()
        for key in ("magic", "unknown_08", "reserved_0c"):
            try:
                setattr(self._item, key, self._parse_u32_text(self._header_fields[key].text()))
            except ValueError:
                pass

    def _apply_record_fields(self):
        if self._item is None or not (0 <= self._current_idx < len(self._item.entries)) or not self._record_fields:
            return
        entry = self._item.entries[self._current_idx]
        entry.stage_id = self._record_fields["stage_id"].text().strip()
        entry.damage_id = self._record_fields["damage_id"].text().strip()
        for key, offset, kind in FIELD_SPECS:
            edit = self._record_fields.get(key)
            if edit is None:
                continue
            word_idx = offset // 4
            try:
                if kind == "f32":
                    entry.words[word_idx] = float_to_word(float(edit.text().strip() or "0"))
                else:
                    entry.words[word_idx] = self._parse_u32_text(edit.text())
            except ValueError:
                edit.setText(self._format_field(entry.words[word_idx], kind))
        if "count" in self._header_fields:
            self._header_fields["count"].setText(str(len(self._item.entries)))

    def _add_entry(self):
        if self._item is None:
            return
        self._apply_editor_fields()
        entry = make_default_entry()
        insert_at = self._current_idx + 1 if self._current_idx >= 0 else len(self._item.entries)
        self._item.entries.insert(insert_at, entry)
        self._snapshots.insert(insert_at, copy.deepcopy(entry))
        self._current_idx = insert_at
        self._rebuild_entry_list()
        self._build_editor()
        self._mark_dirty()

    def _duplicate_entry(self):
        if self._item is None:
            return
        self._apply_editor_fields()
        source = self._item.entries[self._current_idx] if 0 <= self._current_idx < len(self._item.entries) else None
        entry = make_default_entry(source)
        insert_at = self._current_idx + 1 if self._current_idx >= 0 else len(self._item.entries)
        self._item.entries.insert(insert_at, entry)
        self._snapshots.insert(insert_at, copy.deepcopy(entry))
        self._current_idx = insert_at
        self._rebuild_entry_list()
        self._build_editor()
        self._mark_dirty()

    def _delete_entry(self):
        if self._item is None or not self._item.entries:
            return
        if len(self._item.entries) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("ui_gimmickdmg_cannot_delete_last_entry"))
            return
        idx = self._current_idx if 0 <= self._current_idx < len(self._item.entries) else len(self._item.entries) - 1
        entry = self._item.entries[idx]
        reply = QMessageBox.question(
            self,
            self.t("dlg_title_confirm_delete"),
            self.t("ui_gimmickdmg_delete_entry_confirm", stage=entry.stage_id or str(idx)),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._item.entries.pop(idx)
        if idx < len(self._snapshots):
            self._snapshots.pop(idx)
        self._current_idx = min(idx, len(self._item.entries) - 1)
        self._rebuild_entry_list()
        self._build_editor()
        self._mark_dirty()

    def _mark_dirty(self):
        if self._filepath:
            self._dirty = True
            self._save_btn.setEnabled(True)
            set_file_label(self._file_label, self._filepath, dirty=True)
