"""editors/assist_editor.py  –  Editor for SupportCharaParam.bin.xfbin."""

import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_input, ss_search, ss_scrollarea, ss_scrollarea_transparent,
    ss_field_label, ss_section_label, ss_sidebar_btn, ss_file_label,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.assist_parser import (
    parse_assist_xfbin, save_assist_xfbin, make_default_entry,
    FIELD_NAMES, FIELD_TOOLTIPS,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


# Character display names (fallback when translation key not found)

_CHAR_NAMES = {
    "1jnt01": ui_text("char_1jnt01"),
    "1zpl01": ui_text("char_1zpl01"),
    "1dio01": ui_text("char_1dio01"),
    "1sdw01": ui_text("char_1sdw01"),
    "2jsp01": ui_text("char_2jsp01"),
    "2csr01": ui_text("char_2csr01"),
    "2esd01": ui_text("char_2esd01"),
    "2wmu01": ui_text("char_2wmu01"),
    "2krs01": ui_text("char_2krs01"),
    "2lsa01": ui_text("char_2lsa01"),
    "2shm01": ui_text("char_2shm01"),
    "3jtr01": ui_text("char_3jtr01"),
    "3kki01": ui_text("char_3kki01"),
    "3jsp01": ui_text("char_3jsp01"),
    "3pln01": ui_text("char_3pln01"),
    "3abd01": ui_text("char_3abd01"),
    "3igy01": ui_text("char_3igy01"),
    "3hhs01": ui_text("char_3hhs01"),
    "3vni01": ui_text("char_3vni01"),
    "3dio01": "DIO",
    "3mra01": ui_text("char_3mra01"),
    "3psp01": ui_text("char_3psp01"),
    "4jsk01": ui_text("char_4jsk01"),
    "4koi01": ui_text("char_4koi01"),
    "4oky01": ui_text("char_4oky01"),
    "4kch01": ui_text("char_4kch01"),
    "4rhn01": ui_text("char_4rhn01"),
    "4sgc01": ui_text("char_4sgc01"),
    "4fgm01": ui_text("char_4fgm01"),
    "4oti01": ui_text("char_4oti01"),
    "4kir01": ui_text("char_4kir01"),
    "4kwk01": ui_text("char_4kwk01"),
    "4jtr01": ui_text("char_4jtr01"),
    "4ykk01": ui_text("char_4ykk01"),
    "5grn01": ui_text("char_5grn01"),
    "5mst01": ui_text("char_5mst01"),
    "5fgo01": ui_text("char_5fgo01"),
    "5nrc01": ui_text("char_5nrc01"),
    "5bct01": ui_text("char_5bct01"),
    "5abc01": ui_text("char_5abc01"),
    "5dvl01": ui_text("char_5dvl01"),
    "5gac01": ui_text("char_5gac01"),
    "5prs01": ui_text("char_5prs01"),
    "5trs01": ui_text("char_5trs01"),
    "5ris01": ui_text("char_5ris01"),
    "6jln01": ui_text("char_6jln01"),
    "6elm01": ui_text("char_6elm01"),
    "6ans01": ui_text("char_6ans01"),
    "6pci01": ui_text("char_6pci01"),
    "6pci02": ui_text("char_6pci02"),
    "6fit01": ui_text("char_6fit01"),
    "6wet01": ui_text("char_6wet01"),
    "7jny01": ui_text("char_7jny01"),
    "7jir01": ui_text("char_7jir01"),
    "7vtn01": ui_text("char_7vtn01"),
    "7dio01": ui_text("char_7dio01"),
    "7dio02": ui_text("char_7dio02"),
    "8jsk01": ui_text("char_8jsk01"),
    "8wou01": ui_text("char_8wou01"),
    "0bao01": ui_text("char_0bao01"),
}


# Field grouping for card layout

_FIELD_GROUPS = [
    (ui_text("ui_assist_stocks"),            [2, 3]),
    (ui_text("ui_assist_assault_entrance"),  [4, 5, 6]),
    (ui_text("ui_assist_reversal_entrance"), [7, 8, 9]),
    (ui_text("ui_assist_assault_info"),      [10, 11, 12, 13, 14, 15]),
    (ui_text("ui_assist_reversal_info"),     [16, 17, 18, 19, 20, 21]),
    (ui_text("ui_assist_cooldowns"),         [22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33]),
    (ui_text("ui_assist_special"),           [35]),
]


# Helpers

def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


# Editor

class AssistEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath = None
        self._original_data = None
        self._entries = []
        self._dirty = False
        self._current_idx = -1
        self._current_entry = None
        self._entry_buttons = []
        self._fields = {}
        self._display_name_lbl = None

        self._build_ui()

    # Name resolution

    def _get_display_name(self, char_id):
        key = f"char_{char_id}"
        translated = self._t(key)
        if translated != key:
            return translated
        return _CHAR_NAMES.get(char_id, char_id)

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        self._btn_open = QPushButton(self._t("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._t("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        tl.addWidget(self._btn_save)

        self._file_lbl = QLabel(self._t("no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 8, 8, 4)
        sl.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self._t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(self._filter_list)
        sl.addWidget(self._search_entry)

        abf = QWidget()
        abf.setStyleSheet("background: transparent;")
        abl = QHBoxLayout(abf)
        abl.setContentsMargins(0, 2, 0, 4)
        abl.setSpacing(4)
        bf = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(self._t("btn_new"))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(bf)
        self._btn_add.setEnabled(False)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.clicked.connect(self._on_add)
        abl.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._t("btn_duplicate"))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(bf)
        self._btn_dup.setEnabled(False)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.clicked.connect(self._on_dup)
        abl.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._t("btn_delete"))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(bf)
        self._btn_del.setEnabled(False)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.clicked.connect(self._on_delete)
        abl.addWidget(self._btn_del, 1)

        sl.addWidget(abf)

        self._entry_scroll = QScrollArea()
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setStyleSheet("background: transparent;")
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(1)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        sl.addWidget(self._entry_scroll)

        main_layout.addWidget(sidebar)

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        main_layout.addWidget(div)

        # Right panel
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

        self._set_editor_placeholder(ui_text("ui_assist_open_a_supportcharaparam_bin_xfbin_file_to_begin"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # Helpers

    def _set_editor_placeholder(self, text):
        _clear_layout(self._editor_layout)
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 15))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)

    def _build_field_card(self, field_indices, entry, cols=3):
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        card_inner = QWidget(card)
        card_inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(card_inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        card_main = QVBoxLayout(card)
        card_main.setContentsMargins(0, 0, 0, 0)
        card_main.addWidget(card_inner)

        for i, fi in enumerate(field_indices):
            row, col = divmod(i, cols)
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)

            lbl = QLabel(FIELD_NAMES[fi])
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(ss_field_label())
            lbl.setToolTip(FIELD_TOOLTIPS.get(fi, ''))
            fl.addWidget(lbl)

            e = QLineEdit(str(entry[f'f{fi}']))
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(ss_input())
            e.setToolTip(FIELD_TOOLTIPS.get(fi, ''))
            e.textEdited.connect(self._mark_dirty)
            fl.addWidget(e)

            grid.addWidget(f, row, col)
            grid.setColumnStretch(col, 1)
            self._fields[f'f{fi}'] = e

        return card

    # Data

    def _load_file(self, filepath):
        create_backup_on_open(filepath)
        try:
            data, entries = parse_assist_xfbin(filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=exc))
            return

        self._filepath = filepath
        self._original_data = data
        self._entries = entries
        self._dirty = False
        self._current_idx = -1
        self._current_entry = None
        self._fields = {}

        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)

        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._set_editor_placeholder(ui_text("ui_assist_no_entries_found"))

    def _populate_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []
        for i, entry in enumerate(self._entries):
            btn = self._make_entry_button(entry, i)
            self._entry_list_layout.addWidget(btn)
            self._entry_buttons.append((btn, i))
        self._entry_list_layout.addStretch()

    def _make_entry_button(self, entry, idx):
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))
        bl = QVBoxLayout(btn)
        bl.setContentsMargins(10, 3, 10, 3)
        bl.setSpacing(0)

        char_id = entry['char_id']
        name_lbl = QLabel(self._get_display_name(char_id))
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(name_lbl)

        id_lbl = QLabel(char_id)
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(id_lbl)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, i in self._entry_buttons:
            if i >= len(self._entries):
                continue
            entry = self._entries[i]
            char_id = entry['char_id']
            name = self._get_display_name(char_id)
            btn.setVisible(query in char_id.lower() or query in name.lower())

    def _select_entry(self, idx):
        self._apply_fields()
        self._current_idx = idx
        self._current_entry = self._entries[idx] if 0 <= idx < len(self._entries) else None
        for btn, i in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))
        if self._current_entry is not None:
            self._build_editor(self._current_entry)
        else:
            self._set_editor_placeholder(ui_text("ui_assist_select_an_entry"))

    def _apply_fields(self):
        if not self._current_entry or not self._fields:
            return
        entry = self._current_entry
        for key, field in self._fields.items():
            text = field.text().strip()
            try:
                if key == 'char_id':
                    old = entry['char_id']
                    entry['char_id'] = text
                    if old != text:
                        for btn, i in self._entry_buttons:
                            if i == self._current_idx:
                                lbls = btn.findChildren(QLabel)
                                if len(lbls) >= 2:
                                    lbls[0].setText(self._get_display_name(text))
                                    lbls[1].setText(text)
                                break
                else:
                    entry[key] = int(text)
            except (ValueError, Exception):
                pass

    def _build_editor(self, entry):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._display_name_lbl = None

        # Header card
        hdr = QFrame()
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_inner = QWidget(hdr)
        hdr_inner.setStyleSheet("background: transparent;")
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(16, 12, 16, 12)
        hdr_grid.setHorizontalSpacing(16)
        hdr_grid.setVerticalSpacing(4)
        hdr_main = QVBoxLayout(hdr)
        hdr_main.setContentsMargins(0, 0, 0, 0)
        hdr_main.addWidget(hdr_inner)

        # Column 0: display name (cosmetic, non-editable)
        name_frame = QWidget()
        name_frame.setStyleSheet("background: transparent;")
        name_layout = QVBoxLayout(name_frame)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(2)

        lbl_char = QLabel(ui_text("ui_assist_character"))
        lbl_char.setFont(QFont("Segoe UI", 12))
        lbl_char.setStyleSheet(ss_field_label())
        name_layout.addWidget(lbl_char)

        self._display_name_lbl = QLabel(self._get_display_name(entry['char_id']))
        self._display_name_lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self._display_name_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        self._display_name_lbl.setFixedHeight(36)
        name_layout.addWidget(self._display_name_lbl)

        hdr_grid.addWidget(name_frame, 0, 0)
        hdr_grid.setColumnStretch(0, 2)

        # Column 1: char_id (editable)
        id_frame = QWidget()
        id_frame.setStyleSheet("background: transparent;")
        id_layout = QVBoxLayout(id_frame)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.setSpacing(2)

        lbl_id = QLabel(ui_text("ui_assist_char_id"))
        lbl_id.setFont(QFont("Segoe UI", 12))
        lbl_id.setStyleSheet(ss_field_label())
        id_layout.addWidget(lbl_id)

        e_id = QLineEdit(entry['char_id'])
        e_id.setFixedHeight(36)
        e_id.setFont(QFont("Consolas", 16))
        e_id.setStyleSheet(ss_input())
        e_id.textEdited.connect(self._on_char_id_edited)
        id_layout.addWidget(e_id)
        self._fields['char_id'] = e_id

        hdr_grid.addWidget(id_frame, 0, 1)
        hdr_grid.setColumnStretch(1, 1)

        self._editor_layout.addWidget(hdr)

        # Field group cards
        for section_title, field_indices in _FIELD_GROUPS:
            self._add_section(section_title)
            card = self._build_field_card(field_indices, entry, cols=3)
            self._editor_layout.addWidget(card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    def _on_char_id_edited(self, new_id):
        if self._display_name_lbl is not None:
            self._display_name_lbl.setText(self._get_display_name(new_id))
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(True)
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    # File I/O

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_assist_open_supportcharaparam_bin_xfbin"), game_files_dialog_dir(target_patterns="SupportCharaParam.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if path:
            self._load_file(path)

    def _on_save(self):
        if not self._filepath or self._original_data is None:
            return
        self._apply_fields()
        try:
            save_assist_xfbin(self._filepath, self._original_data, self._entries)
            self._dirty = False
            name = os.path.basename(self._filepath)
            set_file_label(self._file_lbl, self._filepath)
            QMessageBox.information(self, ui_text("ui_assist_saved"), ui_text("ui_assist_file_saved_value", p0=name))
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=exc))

    # Add / Dup / Delete

    def _on_add(self):
        self._apply_fields()
        new_entry = make_default_entry('new_assist')
        self._entries.append(new_entry)
        self._current_idx = len(self._entries) - 1
        self._populate_list()
        self._mark_dirty()
        self._select_entry(self._current_idx)

    def _on_dup(self):
        if self._current_idx < 0 or self._current_idx >= len(self._entries):
            return
        self._apply_fields()
        new_entry = copy.deepcopy(self._entries[self._current_idx])
        new_idx = self._current_idx + 1
        self._entries.insert(new_idx, new_entry)
        self._current_idx = new_idx
        self._populate_list()
        self._mark_dirty()
        self._select_entry(new_idx)

    def _on_delete(self):
        if self._current_idx < 0 or self._current_idx >= len(self._entries):
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("msg_cannot_delete_last_entry"))
            return
        name = self._get_display_name(self._entries[self._current_idx]['char_id'])
        result = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"), ui_text("ui_assist_delete_entry_for_value", p0=name)
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        del self._entries[self._current_idx]
        new_idx = min(self._current_idx, len(self._entries) - 1)
        self._current_idx = -1
        self._current_entry = None
        self._fields = {}
        self._populate_list()
        self._mark_dirty()
        self._select_entry(new_idx)
