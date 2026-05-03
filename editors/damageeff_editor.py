"""editors/damageeff_editor.py  –  Editor for damageeff.bin.xfbin (Hit Reactions).

Each entry maps a damage-effect slot index to five effectprm slot IDs.
Load effectprm.bin.xfbin to resolve slot IDs to human-readable effect names.
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QFileDialog, QMessageBox, QLineEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_input, ss_search, ss_scrollarea,
    ss_scrollarea_transparent, ss_field_label, ss_sidebar_btn,
    ss_file_label, TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.damageeff_parser import parse_damageeff_xfbin, save_damageeff_xfbin, _NONE_VAL
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir

# Field definitions

_FIELDS = [
    # (field_key, display_name, nullable, tooltip)
    ("eff_a", ui_text("ui_damageeff_offset_effect"), True,
     ui_text("ui_damageeff_positional_offset_vfx_on_hit_ecmn_offset_throw00_rush_r")),
    ("eff_b", ui_text("ui_damageeff_hit_vfx"),       False,
     ui_text("ui_damageeff_main_impact_particle_on_target_ecmn_common_hit_slash_ri")),
    ("eff_c", ui_text("ui_damageeff_symbol_vfx"),    True,
     ui_text("ui_damageeff_ui_indicator_cancel_counter_stylish_move_guard_break_bg")),
    ("eff_d", ui_text("ui_damageeff_guard_vector"),  False,
     ui_text("ui_damageeff_guard_direction_indicator_ecmn_common_guard_vector_00_0")),
    ("eff_e", ui_text("ui_damageeff_stand_effect"),  True,
     ui_text("ui_damageeff_stand_activation_vfx_ecmn_stand_end00_ecmn_stand_rush00")),
]

_NONE_STR = "NONE"


# Value helpers

def _fmt(val, nullable):
    if nullable and val == _NONE_VAL:
        return _NONE_STR
    return str(val)


def _parse(text, nullable):
    t = text.strip()
    if nullable and t.upper() in (_NONE_STR, "-1", ""):
        return _NONE_VAL
    v = int(t, 0)
    if v < 0 or v > 0xFFFFFFFE:
        raise ValueError(f"Value {v} out of range 0–4294967294")
    return v


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


# Main editor widget

class DamageEffEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t           = t or (lambda k, **kw: k)
        self._embedded    = embedded
        self._filepath    = None
        self._raw         = None
        self._result      = None
        self._dirty       = False
        self._effprm_map  = {}
        self._current_idx = -1
        self._entry_buttons = []
        self._field_widgets = {}  # key → (QLineEdit, name_label)

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        self._build_toolbar_content(top)
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        body_w = QWidget()
        body = QHBoxLayout(body_w)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        self._build_sidebar(sidebar)
        body.addWidget(sidebar)

        div1 = QFrame()
        div1.setFixedWidth(1)
        div1.setStyleSheet(ss_sep())
        body.addWidget(div1)

        self._main_scroll = QScrollArea()
        self._main_scroll.setWidgetResizable(True)
        self._main_scroll.setStyleSheet(ss_scrollarea())
        self._main_inner = QWidget()
        self._main_inner.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._main_layout = QVBoxLayout(self._main_inner)
        self._main_layout.setContentsMargins(20, 16, 20, 20)
        self._main_layout.setSpacing(12)
        self._main_scroll.setWidget(self._main_inner)
        body.addWidget(self._main_scroll, 1)

        root.addWidget(body_w, 1)

        self._show_placeholder()

    def _build_toolbar_content(self, bar):
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(12, 8, 12, 8)
        lo.setSpacing(4)

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        lo.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        lo.addWidget(self._btn_save)

        lo.addSpacing(8)

        self._btn_effprm = QPushButton(ui_text("ui_damageeff_load_effectprm"))
        self._btn_effprm.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_effprm.setStyleSheet(ss_btn())
        self._btn_effprm.setToolTip(ui_text("ui_damageeff_load_effectprm_bin_xfbin_to_resolve_slot_ids_to_"))
        self._btn_effprm.clicked.connect(self._on_load_effectprm)
        lo.addWidget(self._btn_effprm)

        self._effprm_lbl = QLabel(ui_text("ui_damageeff_not_loaded"))
        self._effprm_lbl.setFont(QFont("Consolas", 10))
        self._effprm_lbl.setStyleSheet(ss_file_label())
        lo.addWidget(self._effprm_lbl)

        lo.addStretch(1)

        self._file_lbl = QLabel(ui_text("xfa_no_file"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        self._file_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lo.addWidget(self._file_lbl)

    def _build_sidebar(self, frame):
        lo = QVBoxLayout(frame)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("ui_damageeff_search"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._on_search)
        lo.addWidget(self._search)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 4)
        btn_row.setSpacing(4)

        self._btn_new = QPushButton(ui_text("btn_new"))
        self._btn_new.setFixedHeight(28)
        self._btn_new.setFont(QFont("Segoe UI", 10))
        self._btn_new.setStyleSheet(ss_btn())
        self._btn_new.setEnabled(False)
        self._btn_new.clicked.connect(self._on_add_entry)
        btn_row.addWidget(self._btn_new)

        self._btn_dup = QPushButton(ui_text("btn_dup_short"))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(QFont("Segoe UI", 10))
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.setEnabled(False)
        self._btn_dup.clicked.connect(self._on_dup_entry)
        btn_row.addWidget(self._btn_dup)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(QFont("Segoe UI", 10))
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._on_delete_entry)
        btn_row.addWidget(self._btn_del)

        lo.addLayout(btn_row)

        self._sidebar_scroll = QScrollArea()
        self._sidebar_scroll.setWidgetResizable(True)
        self._sidebar_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._sidebar_inner = QWidget()
        self._sidebar_inner.setStyleSheet("background: transparent;")
        self._sidebar_list = QVBoxLayout(self._sidebar_inner)
        self._sidebar_list.setContentsMargins(0, 0, 0, 0)
        self._sidebar_list.setSpacing(2)
        self._sidebar_list.addStretch()

        self._sidebar_scroll.setWidget(self._sidebar_inner)
        lo.addWidget(self._sidebar_scroll, 1)

    # Sidebar

    def _make_entry_button(self, entry, idx):
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))

        inner = QWidget()
        inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(inner)
        vl.setContentsMargins(10, 4, 10, 4)
        vl.setSpacing(1)

        name_lbl = QLabel(ui_text("ui_damageeff_entry_value", p0=entry['entry_id']))
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        vl.addWidget(name_lbl)

        id_lbl = QLabel(ui_text("ui_damageeff_slot_value", p0=entry['entry_id']))
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        vl.addWidget(id_lbl)

        ol = QHBoxLayout(btn)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(inner)

        btn.clicked.connect(lambda checked, i=idx: self._select_entry(i))
        return btn

    def _populate_sidebar(self, filter_text=""):
        ft = filter_text.strip().lower()
        while self._sidebar_list.count() > 1:
            item = self._sidebar_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._entry_buttons = []
        if self._result is None:
            return

        for idx, entry in enumerate(self._result['entries']):
            if ft and ft not in str(entry['entry_id']):
                continue
            btn = self._make_entry_button(entry, idx)
            self._sidebar_list.insertWidget(self._sidebar_list.count() - 1, btn)
            self._entry_buttons.append((idx, btn))

    def _refresh_sidebar_styles(self):
        for idx, btn in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))

    # Right panel

    def _show_placeholder(self):
        _clear_layout(self._main_layout)
        self._field_widgets = {}
        lbl = QLabel(ui_text("ui_damageeff_open_a_damageeff_bin_xfbin_file_to_begin_editing"))
        lbl.setFont(QFont("Segoe UI", 14))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._main_layout.addStretch(1)
        self._main_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        self._main_layout.addStretch(1)

    def _show_empty_selection(self):
        _clear_layout(self._main_layout)
        self._field_widgets = {}
        lbl = QLabel(ui_text("ui_damageeff_select_an_entry_from_the_sidebar"))
        lbl.setFont(QFont("Segoe UI", 14))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._main_layout.addStretch(1)
        self._main_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        self._main_layout.addStretch(1)

    def _build_editor(self, entry):
        _clear_layout(self._main_layout)
        self._field_widgets = {}

        hdr = QLabel(ui_text("ui_damageeff_damage_effect_slot_value", p0=entry['entry_id']))
        hdr.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        self._main_layout.addWidget(hdr)

        if not self._effprm_map:
            notice = QLabel(ui_text("ui_damageeff_load_effectprm_bin_xfbin_to_see_effect_names"))
            notice.setFont(QFont("Segoe UI", 10))
            notice.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            self._main_layout.addWidget(notice)

        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        card_inner = QWidget()
        card_inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(card_inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(4)

        for i, (fkey, fname, nullable, tip) in enumerate(_FIELDS):
            col  = i % 2
            vrow = i // 2
            gr   = vrow * 3

            lbl_text = fname + (ui_text("ui_damageeff_nullable") if nullable else "")
            lbl = QLabel(lbl_text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(ss_field_label())
            lbl.setToolTip(tip)
            grid.addWidget(lbl, gr, col)

            val = entry[fkey]
            inp = QLineEdit(_fmt(val, nullable))
            inp.setFixedHeight(30)
            inp.setFont(QFont("Consolas", 13))
            inp.setStyleSheet(ss_input())
            inp.setToolTip(tip)
            inp.textEdited.connect(lambda _, fk=fkey: self._mark_dirty())
            grid.addWidget(inp, gr + 1, col)

            resolved = self._eff_name(val, nullable)
            name_lbl = QLabel(resolved or "")
            name_lbl.setFont(QFont("Consolas", 10))
            name_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            grid.addWidget(name_lbl, gr + 2, col)

            self._field_widgets[fkey] = (inp, name_lbl)

        card_lo = QVBoxLayout(card)
        card_lo.setContentsMargins(0, 0, 0, 0)
        card_lo.addWidget(card_inner)
        self._main_layout.addWidget(card)
        self._main_layout.addStretch(1)

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(True)
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _apply_fields(self):
        if self._current_idx < 0 or self._result is None:
            return
        entries = self._result['entries']
        if not (0 <= self._current_idx < len(entries)):
            return
        entry = entries[self._current_idx]
        changed = False
        for fkey, fname, nullable, _ in _FIELDS:
            if fkey not in self._field_widgets:
                continue
            inp, name_lbl = self._field_widgets[fkey]
            try:
                value = _parse(inp.text(), nullable)
            except (ValueError, TypeError):
                inp.setText(_fmt(entry[fkey], nullable))
                continue
            if entry[fkey] != value:
                entry[fkey] = value
                changed = True
            name_lbl.setText(self._eff_name(value, nullable) or "")
        if changed:
            self._dirty = True
            self._btn_save.setEnabled(True)

    def _select_entry(self, idx):
        self._apply_fields()
        self._current_idx = idx
        self._refresh_sidebar_styles()

        if self._result is None or not (0 <= idx < len(self._result['entries'])):
            self._show_empty_selection()
            return

        entry = self._result['entries'][idx]
        self._build_editor(entry)
        self._btn_del.setEnabled(True)
        self._btn_dup.setEnabled(True)

    # effectprm

    def _on_load_effectprm(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_damageeff_load_effectprm_bin_xfbin"), game_files_dialog_dir(target_patterns="effectprm.bin.xfbin"),
            "XFBIN Files (effectprm.bin.xfbin);;All Files (*.*)"
        )
        if not path:
            return
        create_backup_on_open(path)
        try:
            from parsers.effectprm_parser import parse_effectprm_xfbin
            _, eff = parse_effectprm_xfbin(path)
            self._effprm_map = {
                e['slot_id']: e['effect_name']
                for e in eff['entries']
                if e['effect_name']
            }
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_damageeff_failed_to_load_effectprm_value", p0=e))
            return

        count = len(self._effprm_map)
        self._effprm_lbl.setText(ui_text("ui_damageeff_value_effects_loaded", p0=count))
        self._effprm_lbl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        self._btn_effprm.setText(ui_text("ui_damageeff_reload_effectprm"))

        if self._result and 0 <= self._current_idx < len(self._result['entries']):
            self._build_editor(self._result['entries'][self._current_idx])

    def _eff_name(self, val, nullable):
        if nullable and val == _NONE_VAL:
            return ""
        return self._effprm_map.get(val, "")

    # Data loading

    def _load_file(self, filepath):
        create_backup_on_open(filepath)
        try:
            raw, result = parse_damageeff_xfbin(filepath)
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=e))
            return

        self._filepath    = filepath
        self._raw         = raw
        self._result      = result
        self._dirty       = False
        self._current_idx = -1
        self._field_widgets = {}

        self._populate_sidebar()
        self._show_empty_selection()

        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._btn_new.setEnabled(True)

    # Search

    def _on_search(self, text):
        self._populate_sidebar(filter_text=text)

    # File I/O

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_damageeff_open_damageeff_bin_xfbin"), game_files_dialog_dir(target_patterns="damageeff.bin.xfbin"),
            "XFBIN Files (damageeff.bin.xfbin);;All Files (*.*)"
        )
        if path:
            self._load_file(path)

    def _on_save(self):
        if not self._filepath or self._raw is None:
            return
        self._apply_fields()
        self._save_to(self._filepath)

    def _save_to(self, filepath):
        try:
            save_damageeff_xfbin(filepath, self._raw, self._result)
            self._dirty = False
            set_file_label(self._file_lbl, filepath)
            QMessageBox.information(self, ui_text("ui_assist_saved"), ui_text("ui_assist_file_saved_value", p0=os.path.basename(filepath)))
        except Exception as e:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=e))

    # Add / Dup / Delete

    def _on_add_entry(self):
        if self._result is None:
            return
        self._apply_fields()
        entries = self._result['entries']
        new_idx = len(entries)
        entries.append({
            'idx':      new_idx,
            'entry_id': new_idx,
            'eff_a':    _NONE_VAL,
            'eff_b':    0,
            'eff_c':    _NONE_VAL,
            'eff_d':    0,
            'eff_e':    _NONE_VAL,
        })
        self._result['entry_count'] = len(entries)
        self._dirty = True
        self._populate_sidebar(self._search.text())
        self._select_entry(new_idx)
        self._sidebar_scroll.verticalScrollBar().setValue(
            self._sidebar_scroll.verticalScrollBar().maximum()
        )

    def _on_dup_entry(self):
        if self._result is None or self._current_idx < 0:
            return
        self._apply_fields()
        entries = self._result['entries']
        src     = entries[self._current_idx]
        new_idx = len(entries)
        entries.append({
            'idx':      new_idx,
            'entry_id': new_idx,
            'eff_a':    src['eff_a'],
            'eff_b':    src['eff_b'],
            'eff_c':    src['eff_c'],
            'eff_d':    src['eff_d'],
            'eff_e':    src['eff_e'],
        })
        self._result['entry_count'] = len(entries)
        self._dirty = True
        self._populate_sidebar(self._search.text())
        self._select_entry(new_idx)
        self._sidebar_scroll.verticalScrollBar().setValue(
            self._sidebar_scroll.verticalScrollBar().maximum()
        )

    def _on_delete_entry(self):
        if self._result is None or self._current_idx < 0:
            return
        entries = self._result['entries']
        idx = self._current_idx
        if not (0 <= idx < len(entries)):
            return

        reply = QMessageBox.question(
            self, ui_text("ui_damageeff_delete_entry"),
            ui_text("ui_damageeff_delete_entry_value", p0=entries[idx]['entry_id']),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del entries[idx]
        for i, e in enumerate(entries):
            e['idx']      = i
            e['entry_id'] = i
        self._result['entry_count'] = len(entries)
        self._dirty = True

        self._current_idx = -1
        self._populate_sidebar(self._search.text())

        new_idx = min(idx, len(entries) - 1)
        if new_idx >= 0:
            self._select_entry(new_idx)
        else:
            self._show_empty_selection()
            self._btn_del.setEnabled(False)
            self._btn_dup.setEnabled(False)
