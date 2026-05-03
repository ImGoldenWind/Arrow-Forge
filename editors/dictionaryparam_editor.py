"""editors/dictionaryparam_editor.py  –  Full editor for DictionaryParam.bin.xfbin."""

import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QCheckBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_file_label, ss_check,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.dictionaryparam_parser import (
    parse_dictionaryparam_xfbin, save_dictionaryparam_xfbin, make_default_entry,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


_FLAG_NAMES = {
    "flag1":  ui_text("ui_charviewer_part_1"),
    "flag2":  ui_text("ui_charviewer_part_2"),
    "flag3":  ui_text("ui_charviewer_part_3"),
    "flag4":  ui_text("ui_charviewer_part_4"),
    "flag5":  ui_text("ui_charviewer_part_5"),
    "flag6":  ui_text("ui_charviewer_part_6"),
    "flag7":  ui_text("ui_charviewer_part_7"),
    "flag8":  ui_text("ui_charviewer_part_8"),
    "flag13": ui_text("ui_dictionaryparam_flag_a"),
    "flag14": ui_text("ui_dictionaryparam_flag_b"),
    "flag15": ui_text("ui_dictionaryparam_flag_c"),
    "flag19": ui_text("ui_dictionaryparam_flag_d"),
}

_DLC_NAMES = {
    0:     ui_text("ui_charviewer_base_game"),
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


class DictionaryParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t        = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath: str | None = None
        self._original_data: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._current_entry: dict | None = None
        self._entry_buttons: list[tuple] = []
        self._fields: dict[str, QWidget] = {}
        self._dirty = False

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        open_btn = QPushButton(self._t("btn_open_file"))
        open_btn.setFixedHeight(TOOLBAR_BTN_H)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._on_open)
        tl.addWidget(open_btn)

        self._save_btn = QPushButton(self._t("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._on_save)
        tl.addWidget(self._save_btn)

        self._file_lbl = QLabel(self._t("no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        # Separator
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
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self._t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        self._search_entry.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search_entry)

        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(self._t("btn_new"))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_new_entry)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self._t("btn_duplicate"))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_entry)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self._t("btn_delete"))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_entry)
        actions_layout.addWidget(self._del_btn, 1)

        list_vlayout.addWidget(actions_frame)

        self._entry_scroll = QScrollArea()
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setStyleSheet("background-color: transparent;")
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(1)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        list_vlayout.addWidget(self._entry_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Editor panel
        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {P['bg_dark']}; border: none; }}"
        )
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)

        self._placeholder = QLabel(ui_text("ui_dictionaryparam_open_a_dictionaryparam_xfbin_file_to_begin_editing"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # Helpers

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()

    def _clear_editor(self):
        _clear_layout(self._editor_layout)

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)

    # File I/O

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_dictionaryparam_open_dictionaryparam_xfbin"), game_files_dialog_dir(target_patterns=("DictionaryParam.xfbin", "DictionaryParam.bin.xfbin")),
            "XFBIN Files (*.xfbin);;All Files (*.*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, filepath: str):
        create_backup_on_open(filepath)
        try:
            data, version, entries = parse_dictionaryparam_xfbin(filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=exc))
            return

        self._filepath      = filepath
        self._original_data = data
        self._version       = version
        self._entries       = entries
        self._current_entry = None
        self._fields        = {}

        self._dirty = False
        set_file_label(self._file_lbl, filepath)
        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)

        self._populate_list()

    def _on_save(self):
        if not self._filepath or self._original_data is None:
            return
        self._apply_fields()
        path = self._filepath
        try:
            save_dictionaryparam_xfbin(path, self._original_data, self._version, self._entries)
            with open(path, "rb") as fh:
                self._original_data = bytearray(fh.read())
            self._dirty = False
            set_file_label(self._file_lbl, path)
            QMessageBox.information(self, ui_text("ui_assist_saved"), ui_text("ui_dictionaryparam_saved_to_value", p0=os.path.basename(path)))
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=exc))

    # Entry list

    def _populate_list(self):
        self._clear_entry_list()
        self._entry_buttons = []
        for entry in self._entries:
            btn = self._make_entry_button(entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, entry))
        if self._entries:
            self._select_entry(self._entries[0])

    def _make_entry_button(self, entry):
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; border-radius: 6px; "
            f"text-align: left; padding: 0px; border: none; }} "
            f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
        )

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        name_lbl = QLabel(entry['char_id'])
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(name_lbl)

        sub_lbl = QLabel(entry.get('title', '') or f"#{entry.get('index', 0)}")
        sub_lbl.setFont(QFont("Consolas", 11))
        sub_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(sub_lbl)

        btn.clicked.connect(lambda checked=False, e=entry: self._select_entry(e))
        return btn

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, entry in self._entry_buttons:
            match = (
                query in entry['char_id'].lower() or
                query in (entry.get('title') or '').lower() or
                query in str(entry.get('index', ''))
            )
            btn.setVisible(match)

    def _select_entry(self, entry):
        self._apply_fields()
        self._current_entry = entry
        for btn, e in self._entry_buttons:
            try:
                if e is entry:
                    btn.setStyleSheet(
                        f"QPushButton {{ background-color: {P['bg_card']}; border-radius: 6px; "
                        f"text-align: left; padding: 0px; border: none; }} "
                        f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                    )
                else:
                    btn.setStyleSheet(
                        f"QPushButton {{ background-color: transparent; border-radius: 6px; "
                        f"text-align: left; padding: 0px; border: none; }} "
                        f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                    )
            except Exception:
                pass
        self._build_editor(entry)

    def _apply_fields(self):
        if not self._current_entry or not self._fields:
            return
        e = self._current_entry
        for key, widget in self._fields.items():
            try:
                if isinstance(widget, QCheckBox):
                    e[key] = 4 if (key == 'no_panel' and widget.isChecked()) else (1 if widget.isChecked() else 0)
                else:
                    val = widget.text().strip()
                    if key in ('char_id', 'panel', 'title', 'header', 'dmy'):
                        e[key] = val
                    elif key == 'padding':
                        e[key] = int(val or 'FFFFFFFF', 16) & 0xFFFFFFFF
                    else:
                        e[key] = int(val) if val else 0
            except (ValueError, KeyError):
                pass
        for btn, entry in self._entry_buttons:
            if entry is self._current_entry:
                labels = btn.findChildren(QLabel)
                if labels:
                    labels[0].setText(entry['char_id'])
                if len(labels) >= 2:
                    labels[1].setText(entry.get('title', '') or f"#{entry.get('index', 0)}")
                break

    # Editor

    def _build_editor(self, entry):
        self._clear_editor()
        self._fields = {}

        # Identity header
        hdr = QFrame()
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_inner = QWidget(hdr)
        hdr_inner.setStyleSheet("background: transparent;")
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(16, 12, 16, 12)
        hdr_grid.setHorizontalSpacing(16)

        hdr_main = QVBoxLayout(hdr)
        hdr_main.setContentsMargins(0, 0, 0, 0)
        hdr_main.addWidget(hdr_inner)

        ci_frame = QWidget()
        ci_frame.setStyleSheet("background: transparent;")
        ci_layout = QVBoxLayout(ci_frame)
        ci_layout.setContentsMargins(0, 0, 0, 0)
        ci_layout.setSpacing(2)
        lbl = QLabel(ui_text("ui_assist_char_id"))
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(f"color: {P['text_dim']};")
        ci_layout.addWidget(lbl)
        e_ci = QLineEdit()
        e_ci.setFixedHeight(36)
        e_ci.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        e_ci.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['accent']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e_ci.setText(entry['char_id'])
        ci_layout.addWidget(e_ci)
        self._fields['char_id'] = e_ci
        hdr_grid.addWidget(ci_frame, 0, 0)
        hdr_grid.setColumnStretch(0, 2)

        idx_frame = QWidget()
        idx_frame.setStyleSheet("background: transparent;")
        idx_layout = QVBoxLayout(idx_frame)
        idx_layout.setContentsMargins(0, 0, 0, 0)
        idx_layout.setSpacing(2)
        lbl2 = QLabel(ui_text("ui_dictionaryparam_index"))
        lbl2.setFont(QFont("Segoe UI", 12))
        lbl2.setStyleSheet(f"color: {P['text_dim']};")
        idx_layout.addWidget(lbl2)
        e_idx = QLineEdit()
        e_idx.setFixedHeight(36)
        e_idx.setFont(QFont("Consolas", 16))
        e_idx.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e_idx.setText(str(entry['index']))
        idx_layout.addWidget(e_idx)
        self._fields['index'] = e_idx
        hdr_grid.addWidget(idx_frame, 0, 1)
        hdr_grid.setColumnStretch(1, 1)

        self._editor_layout.addWidget(hdr)

        # Strings
        self._add_section(ui_text("ui_customcardparam_strings"))
        str_frame = QFrame()
        str_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        str_inner = QWidget(str_frame)
        str_inner.setStyleSheet("background: transparent;")
        str_grid = QGridLayout(str_inner)
        str_grid.setContentsMargins(12, 12, 12, 12)
        str_grid.setHorizontalSpacing(16)
        str_grid.setVerticalSpacing(8)
        str_main = QVBoxLayout(str_frame)
        str_main.setContentsMargins(0, 0, 0, 0)
        str_main.addWidget(str_inner)

        str_fields = [
            ("panel",  ui_text("ui_dictionaryparam_panel"),       entry['panel']),
            ("title",  ui_text("ui_dictionaryparam_title_key"),   entry['title']),
            ("header", ui_text("ui_dictionaryparam_header_key"),  entry['header']),
            ("dmy",    "DMY",         entry['dmy']),
        ]
        for fi, (key, label, val) in enumerate(str_fields):
            row, col = divmod(fi, 2)
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            fl.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(str(val))
            fl.addWidget(e)
            str_grid.addWidget(f, row, col)
            str_grid.setColumnStretch(col, 1)
            self._fields[key] = e

        self._editor_layout.addWidget(str_frame)

        # Identifiers
        self._add_section(ui_text("ui_dictionaryparam_identifiers"))
        ids_frame = QFrame()
        ids_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        ids_inner = QWidget(ids_frame)
        ids_inner.setStyleSheet("background: transparent;")
        ids_grid = QGridLayout(ids_inner)
        ids_grid.setContentsMargins(12, 12, 12, 12)
        ids_grid.setHorizontalSpacing(16)
        ids_grid.setVerticalSpacing(8)
        ids_main = QVBoxLayout(ids_frame)
        ids_main.setContentsMargins(0, 0, 0, 0)
        ids_main.addWidget(ids_inner)

        dlc_hint = _DLC_NAMES.get(entry['dlc_id'], f"ID {entry['dlc_id']}")
        ids_list = [
            ("dlc_id", f"DLC ID  ({dlc_hint})", entry['dlc_id']),
            ("patch",  ui_text("ui_dictionaryparam_patch_version"),          entry['patch']),
        ]
        for ci, (key, label, val) in enumerate(ids_list):
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            fl.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(str(val))
            fl.addWidget(e)
            ids_grid.addWidget(f, 0, ci)
            ids_grid.setColumnStretch(ci, 1)
            self._fields[key] = e

        self._editor_layout.addWidget(ids_frame)

        # Part Flags
        self._add_section(ui_text("ui_dictionaryparam_part_flags"))
        flags_frame = QFrame()
        flags_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        flags_inner = QWidget(flags_frame)
        flags_inner.setStyleSheet("background: transparent;")
        flags_grid = QGridLayout(flags_inner)
        flags_grid.setContentsMargins(12, 12, 12, 12)
        flags_grid.setHorizontalSpacing(16)
        flags_grid.setVerticalSpacing(8)
        flags_main = QVBoxLayout(flags_frame)
        flags_main.setContentsMargins(0, 0, 0, 0)
        flags_main.addWidget(flags_inner)

        for fi, (key, name) in enumerate(_FLAG_NAMES.items()):
            row, col = divmod(fi, 4)
            cb = QCheckBox(name)
            cb.setChecked(bool(entry.get(key, 0)))
            cb.setFont(QFont("Segoe UI", 12))
            cb.setStyleSheet(ss_check())
            flags_grid.addWidget(cb, row, col)
            self._fields[key] = cb

        self._editor_layout.addWidget(flags_frame)

        # Panel Settings
        self._add_section(ui_text("ui_dictionaryparam_panel_settings"))
        panel_frame = QFrame()
        panel_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        panel_inner = QWidget(panel_frame)
        panel_inner.setStyleSheet("background: transparent;")
        panel_vl = QVBoxLayout(panel_inner)
        panel_vl.setContentsMargins(12, 12, 12, 12)
        panel_vl.setSpacing(8)
        panel_main = QVBoxLayout(panel_frame)
        panel_main.setContentsMargins(0, 0, 0, 0)
        panel_main.addWidget(panel_inner)

        no_panel_cb = QCheckBox(ui_text("ui_dictionaryparam_no_panel_entry_is_not_unlockable_via_a_panel"))
        no_panel_cb.setChecked(entry.get('no_panel', 0) == 4)
        no_panel_cb.setFont(QFont("Segoe UI", 12))
        no_panel_cb.setStyleSheet(ss_check())
        panel_vl.addWidget(no_panel_cb)
        self._fields['no_panel'] = no_panel_cb

        self._editor_layout.addWidget(panel_frame)

        # Advanced
        self._add_section(ui_text("ui_charviewer_advanced"))
        adv_frame = QFrame()
        adv_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        adv_inner = QWidget(adv_frame)
        adv_inner.setStyleSheet("background: transparent;")
        adv_grid = QGridLayout(adv_inner)
        adv_grid.setContentsMargins(12, 12, 12, 12)
        adv_grid.setHorizontalSpacing(16)
        adv_grid.setVerticalSpacing(8)
        adv_main = QVBoxLayout(adv_frame)
        adv_main.setContentsMargins(0, 0, 0, 0)
        adv_main.addWidget(adv_inner)

        adv_fields = [
            ("const1",  ui_text("ui_dictionaryparam_const1_always_1"),         entry.get('const1', 1)),
            ("padding", ui_text("ui_dictionaryparam_padding_hex_ffffffff"),    f"{entry.get('padding', 0xFFFFFFFF) & 0xFFFFFFFF:08X}"),
            ("pad1",    ui_text("ui_dictionaryparam_pad_1"),                      entry.get('pad1', 0)),
            ("pad2",    ui_text("ui_dictionaryparam_pad_2"),                      entry.get('pad2', 0)),
            ("pad3",    ui_text("ui_dictionaryparam_pad_3"),                      entry.get('pad3', 0)),
            ("pad4",    ui_text("ui_dictionaryparam_pad_4"),                      entry.get('pad4', 0)),
            ("pad5",    ui_text("ui_dictionaryparam_pad_5"),                      entry.get('pad5', 0)),
            ("pad6",    ui_text("ui_dictionaryparam_pad_6"),                      entry.get('pad6', 0)),
            ("pad7",    ui_text("ui_dictionaryparam_pad_7"),                      entry.get('pad7', 0)),
            ("pad8",    ui_text("ui_dictionaryparam_pad_8"),                      entry.get('pad8', 0)),
            ("res1",    ui_text("ui_dictionaryparam_res_1"),                      entry.get('res1', 0)),
            ("res2",    ui_text("ui_dictionaryparam_res_2"),                      entry.get('res2', 0)),
            ("res3",    ui_text("ui_dictionaryparam_res_3"),                      entry.get('res3', 0)),
            ("res4",    ui_text("ui_dictionaryparam_res_4"),                      entry.get('res4', 0)),
            ("res5",    ui_text("ui_dictionaryparam_res_5"),                      entry.get('res5', 0)),
        ]
        for fi, (key, label, val) in enumerate(adv_fields):
            row, col = divmod(fi, 3)
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            fl.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(str(val))
            fl.addWidget(e)
            adv_grid.addWidget(f, row, col)
            adv_grid.setColumnStretch(col, 1)
            self._fields[key] = e

        self._editor_layout.addWidget(adv_frame)

        for widget in self._fields.values():
            if isinstance(widget, QLineEdit):
                widget.textEdited.connect(self._mark_dirty)
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self._mark_dirty)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    def _mark_dirty(self, *_):
        if self._dirty:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    # Add / Duplicate / Delete

    def _add_new_entry(self):
        if self._original_data is None:
            return
        self._apply_fields()
        new_entry = make_default_entry(len(self._entries))
        self._entries.append(new_entry)
        self._populate_list()
        self._select_entry(new_entry)
        self._mark_dirty()

    def _duplicate_entry(self):
        if not self._current_entry:
            return
        self._apply_fields()
        new_entry = copy.deepcopy(self._current_entry)
        new_entry['index'] = len(self._entries)
        new_entry['char_id'] = new_entry['char_id'] + '_copy'
        self._entries.append(new_entry)
        self._populate_list()
        self._select_entry(new_entry)
        self._mark_dirty()

    def _delete_entry(self):
        if not self._current_entry:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("msg_cannot_delete_last_entry"))
            return
        name = self._current_entry['char_id']
        result = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"),
            ui_text("ui_dictionaryparam_delete_entry_value_this_cannot_be_undone", p0=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._fields = {}
        self._entries.remove(self._current_entry)
        self._current_entry = None
        self._populate_list()
        self._mark_dirty()
