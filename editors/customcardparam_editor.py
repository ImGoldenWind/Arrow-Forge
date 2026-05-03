import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFileDialog, QMessageBox, QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_input, ss_search, ss_file_label, ss_sidebar_btn,
    ss_scrollarea, ss_scrollarea_transparent, ss_panel, ss_section_label,
    ss_field_label, ss_dim_label, ss_placeholder, TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.customcardparam_parser import (
    parse_customcardparam_xfbin,
    save_customcardparam_xfbin,
    make_default_entry,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


_PART_NAMES = {
    0: ui_text("ui_charviewer_all_none"),
    1: ui_text("ui_charviewer_part_1"),
    2: ui_text("ui_charviewer_part_2"),
    3: ui_text("ui_charviewer_part_3"),
    4: ui_text("ui_charviewer_part_4"),
    5: ui_text("ui_charviewer_part_5"),
    6: ui_text("ui_charviewer_part_6"),
    7: ui_text("ui_charviewer_part_7"),
    8: ui_text("ui_charviewer_part_8"),
}

_DLC_NAMES = {
    0: ui_text("ui_charviewer_base_game"),
    10000: ui_text("ui_charviewer_dlc_0"),
    10001: ui_text("ui_charviewer_dlc_1"),
    10002: ui_text("ui_charviewer_dlc_2"),
    10003: ui_text("ui_charviewer_dlc_3"),
    10004: ui_text("ui_charviewer_dlc_4"),
    10005: ui_text("ui_charviewer_dlc_5"),
    10006: ui_text("ui_charviewer_dlc_6"),
    10007: ui_text("ui_charviewer_dlc_7"),
    10008: ui_text("ui_charviewer_dlc_8"),
    10009: ui_text("ui_charviewer_dlc_9"),
    10010: ui_text("ui_charviewer_dlc_10"),
    10011: ui_text("ui_charviewer_dlc_11"),
}

_MEDAL_NAMES = {
    1: ui_text("ui_customcardparam_bronze"),
    2: ui_text("ui_customcardparam_silver"),
    3: ui_text("ui_customcardparam_gold"),
    4: ui_text("ui_customcardparam_platinum"),
    5: ui_text("ui_customcardparam_diamond"),
    7: ui_text("ui_assist_special"),
    10: ui_text("ui_customcardparam_event"),
}

_INTER_NAMES = {
    0: ui_text("gaps_none"),
    1: ui_text("ui_customcardparam_type_1"),
    2: ui_text("ui_customcardparam_type_2"),
    3: ui_text("ui_customcardparam_type_3"),
    4: ui_text("ui_customcardparam_type_4"),
}

_UNLOCK_NAMES = {
    0: ui_text("ui_customcardparam_default_free"),
    2: ui_text("ui_customcardparam_shop_purchase"),
    3: ui_text("ui_customcardparam_dlc_unlock"),
    5: ui_text("ui_customcardparam_special_condition"),
    6: ui_text("ui_customcardparam_shop_alt"),
}


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class CustomCardParamEditor(QWidget):
    """Embedded editor for CustomCardParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._dirty = False
        self._filter_text = ""
        self._current_index: int | None = None
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._fields: dict[str, QLineEdit] = {}
        self._loading_detail = False

        self._build_ui()

    def _tr(self, key, fallback):
        value = self._t(key)
        return fallback if value == key else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._on_save)
        tl.addWidget(self._btn_save)

        self._lbl_file = QLabel(self._tr("no_file_loaded", ui_text("cpk_no_file")))
        self._lbl_file.setFont(QFont("Consolas", 12))
        self._lbl_file.setStyleSheet(ss_file_label())
        tl.addWidget(self._lbl_file)
        tl.addStretch()
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        main = QWidget()
        main_l = QHBoxLayout(main)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 8, 8, 4)
        sl.setSpacing(4)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(self._tr("search_placeholder", ui_text("search_placeholder")))
        self._search_box.setFixedHeight(32)
        self._search_box.setFont(QFont("Segoe UI", 13))
        self._search_box.setStyleSheet(ss_search())
        self._search_box.textChanged.connect(self._on_filter_changed)
        sl.addWidget(self._search_box)

        actions = QWidget()
        actions.setStyleSheet("background: transparent;")
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 2, 0, 4)
        al.setSpacing(4)
        btn_font = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(btn_font)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._on_add)
        al.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(btn_font)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.setEnabled(False)
        self._btn_dup.clicked.connect(self._on_duplicate)
        al.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(btn_font)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._on_delete)
        al.addWidget(self._btn_del, 1)

        sl.addWidget(actions)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        sl.addWidget(self._list_scroll, 1)

        main_l.addWidget(sidebar)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_l.addWidget(divider)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)
        main_l.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_customcardparam_open_a_customcardparam_bin_xfbin_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet(ss_placeholder())
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    def _clear_entry_list(self):
        _clear_layout(self._list_layout)
        self._list_layout.addStretch()

    def _visible_indices(self):
        text = self._filter_text.lower().strip()
        result = []
        for i, e in enumerate(self._entries):
            haystack = " ".join((
                e.get("card_id", ""),
                e.get("char_id", ""),
                e.get("letter", ""),
                e.get("medal_name", ""),
                e.get("card_detail", ""),
            )).lower()
            if not text or text in haystack:
                result.append(i)
        return result

    def _populate_list(self, preserve_selection: int | None = None):
        self._clear_entry_list()
        self._entry_buttons = []
        visible = self._visible_indices()
        for i in visible:
            btn = self._make_entry_button(i)
            self._list_layout.insertWidget(self._list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, i))

        if preserve_selection is not None and preserve_selection in visible:
            self._select_entry(preserve_selection)
        elif self._current_index in visible:
            self._select_entry(self._current_index)
        elif visible:
            self._select_entry(visible[0])
        else:
            self._current_index = None
            self._set_detail_buttons(False)
            self._show_placeholder(ui_text("ui_customcardparam_select_a_card_to_edit"))

    def _make_entry_button(self, idx):
        e = self._entries[idx]
        title = f"Entry #{idx:04d}"
        subtitle = f"{e.get('card_id', '')}  {e.get('char_id', '')}"

        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_index)))

        bl = QVBoxLayout(btn)
        bl.setContentsMargins(10, 3, 10, 3)
        bl.setSpacing(0)

        name_lbl = QLabel(title)
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(name_lbl)

        id_lbl = QLabel(subtitle)
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(ss_dim_label())
        id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(id_lbl)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _set_detail_buttons(self, has_selection):
        self._btn_dup.setEnabled(has_selection)
        self._btn_del.setEnabled(has_selection)

    def _select_entry(self, idx):
        if idx < 0 or idx >= len(self._entries):
            return
        self._current_index = idx
        self._set_detail_buttons(True)
        for btn, i in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))
        self._build_editor(idx)

    def _build_editor(self, idx):
        self._loading_detail = True
        _clear_layout(self._editor_layout)
        self._fields = {}
        e = self._entries[idx]

        hdr = QFrame()
        hdr.setStyleSheet(ss_panel())
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(8)

        title = QLabel(ui_text("ui_customcardparam_entry_value", p0=idx))
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        hl.addWidget(title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self._add_field(grid, 0, 0, "card_id", ui_text("ui_customcardparam_card_id"), e["card_id"], wide=True)
        self._add_field(grid, 0, 1, "char_id", ui_text("tool_char_id"), e["char_id"])
        self._add_field(grid, 0, 2, "index", ui_text("ui_dictionaryparam_index"), e["index"])
        hl.addLayout(grid)
        self._editor_layout.addWidget(hdr)

        self._add_section(ui_text("ui_customcardparam_strings"))
        self._add_card_grid([
            ("letter", ui_text("ui_customcardparam_letter"), e["letter"]),
            ("medal_name", ui_text("ui_customcardparam_medal_name"), e["medal_name"]),
            ("card_detail", ui_text("ui_customcardparam_card_detail"), e["card_detail"]),
            ("sfx1", ui_text("ui_customcardparam_sfx_1"), e["sfx1"]),
            ("sfx2", ui_text("ui_customcardparam_sfx_2"), e["sfx2"]),
            ("sfx3", ui_text("ui_customcardparam_sfx_3"), e["sfx3"]),
            ("sfx4", ui_text("ui_customcardparam_sfx_4"), e["sfx4"]),
        ], columns=3)

        self._add_section(ui_text("ui_customcardparam_gameplay"))
        self._add_card_grid([
            ("part", self._label_with_hint(ui_text("ui_customcardparam_part"), _PART_NAMES, e["part"]), e["part"]),
            ("interaction_type", self._label_with_hint(ui_text("ui_customcardparam_interaction_type"), _INTER_NAMES, e["interaction_type"]), e["interaction_type"]),
            ("medal_type", self._label_with_hint(ui_text("ui_customcardparam_medal_type"), _MEDAL_NAMES, e["medal_type"]), e["medal_type"]),
            ("unlock_condition", self._label_with_hint(ui_text("ui_charviewer_unlock_condition"), _UNLOCK_NAMES, e["unlock_condition"]), e["unlock_condition"]),
            ("dlc_id", self._label_with_hint(ui_text("ui_charviewer_dlc_id"), _DLC_NAMES, e["dlc_id"]), e["dlc_id"]),
            ("patch", ui_text("ui_customcardparam_patch"), e["patch"]),
            ("price", ui_text("ui_customcardparam_price"), e["price"]),
        ], columns=3)

        self._add_section(ui_text("ui_customcardparam_unknown_fields"))
        self._add_card_grid([
            ("unk7_0", "unk7_0", e["unk7_0"]),
            ("unk7_1", "unk7_1", e["unk7_1"]),
            ("unk7_2", "unk7_2", e["unk7_2"]),
            ("unk7_3", "unk7_3", e["unk7_3"]),
            ("unk18", "unk18", e["unk18"]),
            ("unk19", "unk19", e["unk19"]),
            ("unk", "unk", e["unk"]),
        ], columns=4)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _label_with_hint(self, label, names, value):
        hint = names.get(value)
        return f"{label} ({hint})" if hint else label

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)

    def _add_card_grid(self, fields, columns=3):
        card = QFrame()
        card.setStyleSheet(ss_panel())
        inner = QWidget(card)
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        for i, (key, label, value) in enumerate(fields):
            row, col = divmod(i, columns)
            self._add_field(grid, row, col, key, label, value)

        main = QVBoxLayout(card)
        main.setContentsMargins(0, 0, 0, 0)
        main.addWidget(inner)
        self._editor_layout.addWidget(card)

    def _add_field(self, grid, row, col, key, label, value, wide=False):
        f = QWidget()
        f.setStyleSheet("background: transparent;")
        fl = QVBoxLayout(f)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(2)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        fl.addWidget(lbl)

        le = QLineEdit()
        le.setText(str(value))
        le.setFixedHeight(30 if not wide else 36)
        le.setFont(QFont("Consolas", 13 if not wide else 16))
        le.setStyleSheet(ss_input())
        le.textChanged.connect(lambda text, k=key: self._on_field_changed(k, text))
        fl.addWidget(le)

        grid.addWidget(f, row, col)
        grid.setColumnStretch(col, 1)
        self._fields[key] = le

    def _on_field_changed(self, key, text):
        if self._loading_detail or self._current_index is None:
            return
        e = self._entries[self._current_index]
        try:
            if key in {
                "part", "interaction_type", "medal_type", "unk7_0", "unk7_1",
                "unk7_2", "unk7_3", "unk18", "unk19", "dlc_id", "patch",
                "unlock_condition", "unk", "price", "index",
            }:
                e[key] = int(text.strip() or "0")
            else:
                e[key] = text.strip()
        except ValueError:
            return

        self._mark_dirty()
        if key in {"card_id", "char_id"}:
            self._refresh_current_button()

    def _refresh_current_button(self):
        if self._current_index is None:
            return
        e = self._entries[self._current_index]
        for btn, i in self._entry_buttons:
            if i == self._current_index:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(ui_text("ui_customcardparam_entry_value_2", p0=i))
                    labels[1].setText(ui_text("ui_customcardparam_value_value", p0=e.get('card_id', ''), p1=e.get('char_id', '')))
                break

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(self._filepath is not None)
        set_file_label(self._lbl_file, self._filepath, dirty=True)

    def _on_filter_changed(self):
        self._filter_text = self._search_box.text()
        self._populate_list(preserve_selection=self._current_index)

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_customcardparam_open_customcardparam_bin_xfbin"), game_files_dialog_dir(target_patterns="CustomCardParam.bin.xfbin"),
            "XFBIN files (*.xfbin);;All files (*.*)"
        )
        if not path:
            return
        create_backup_on_open(path)
        try:
            raw, version, entries = parse_customcardparam_xfbin(path)
        except Exception as ex:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=ex))
            return

        self._filepath = path
        self._raw = raw
        self._version = version
        self._entries = entries
        self._dirty = False
        self._current_index = None
        self._btn_add.setEnabled(True)
        self._btn_save.setEnabled(False)
        set_file_label(self._lbl_file, path)
        self._search_box.setText("")
        self._filter_text = ""
        self._populate_list()

    def _on_save(self):
        if not self._filepath or not self._raw:
            return
        try:
            save_customcardparam_xfbin(self._filepath, self._raw, self._version, self._entries)
            with open(self._filepath, "rb") as fh:
                self._raw = bytearray(fh.read())
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._lbl_file, self._filepath)
        except Exception as ex:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_customcardparam_failed_to_save_file_value", p0=ex))

    def _on_add(self):
        if self._raw is None:
            return
        new_e = make_default_entry(len(self._entries))
        self._entries.append(new_e)
        self._mark_dirty()
        self._populate_list(preserve_selection=len(self._entries) - 1)

    def _on_duplicate(self):
        if self._current_index is None:
            return
        dup = copy.deepcopy(self._entries[self._current_index])
        dup["card_id"] = dup["card_id"] + "_COPY"
        self._entries.insert(self._current_index + 1, dup)
        self._mark_dirty()
        self._populate_list(preserve_selection=self._current_index + 1)

    def _on_delete(self):
        if self._current_index is None:
            return
        e = self._entries[self._current_index]
        reply = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"),
            ui_text("ui_customcardparam_delete_entry_value_value_this_cannot_be_undone", p0=self._current_index, p1=e['card_id']),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        old_idx = self._current_index
        self._entries.pop(old_idx)
        self._mark_dirty()
        new_sel = min(old_idx, len(self._entries) - 1) if self._entries else None
        self._current_index = None
        self._populate_list(preserve_selection=new_sel)
