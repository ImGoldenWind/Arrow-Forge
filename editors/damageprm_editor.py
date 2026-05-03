"""editors/damageprm_editor.py  –  Editor for damageprm.bin.xfbin (Hit Reactions)."""

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
    ss_file_label, ss_section_label,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.damageprm_parser import parse_damageprm_xfbin, save_damageprm_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir

# Reaction type names (for hint display)

_REACTION_NAMES = {
    0:  ui_text("gaps_none"),          1:  ui_text("ui_damageprm_small_uc"),       2:  ui_text("ui_damageprm_collapse"),
    3:  ui_text("ui_damageprm_tumble"),        4:  ui_text("ui_damageprm_smash"),          5:  ui_text("ui_damageprm_smash_roll"),
    6:  ui_text("ui_damageprm_smash_up"),      7:  ui_text("ui_damageprm_throw_begin"),    8:  ui_text("ui_damageprm_rush"),
    9:  ui_text("ui_damageprm_bind"),          10: ui_text("ui_damageprm_unknown_10"),   11: ui_text("ui_damageprm_unknown_11"),
    12: ui_text("ui_damageprm_unknown_12"),  13: ui_text("ui_damageprm_unknown_13"),   14: ui_text("ui_damageprm_crash_ground"),
    15: ui_text("ui_damageprm_wall_crash"),    16: ui_text("ui_damageprm_rise"),           17: ui_text("ui_damageprm_throw_blow"),
    18: ui_text("ui_damageprm_smash_down"),    19: ui_text("ui_damageprm_throw_command"),  20: ui_text("ui_damageprm_smash_gimmick"),
    21: ui_text("ui_damageprm_rush_speed_lose"), 22: ui_text("ui_damageprm_freeze"),       23: ui_text("ui_damageprm_raise"),
    24: ui_text("ui_damageprm_dummy_lock_release"), 25: ui_text("ui_damageprm_3mra_strap_bind"),
    26: ui_text("ui_damageprm_5prs_string_bind"),   27: ui_text("ui_damageprm_pull_ground"),
}

# Editable field definitions

_FIELDS = [
    # (key, label, type, tooltip)
    ("launch_x",  ui_text("ui_damageprm_launch_x"),   "float", ui_text("ui_damageprm_horizontal_launch_force_scale_float")),
    ("launch_y",  ui_text("ui_damageprm_launch_y"),   "float", ui_text("ui_damageprm_vertical_launch_force_scale_float")),
    ("flag",      ui_text("skill_field_flag"),       "uint",  ui_text("ui_damageprm_misc_flag_integer")),
    ("reaction",  ui_text("ui_damageprm_reaction"),   "uint",  ui_text("ui_damageprm_hit_reaction_animation_type_id_see_legend_below")),
    ("hitstun",   ui_text("ui_damageprm_hitstun"),    "uint",  ui_text("ui_damageprm_hitstun_duration_integer")),
    ("recovery",  ui_text("ui_damageprm_recovery"),   "uint",  ui_text("ui_damageprm_recovery_duration_integer")),
    ("sub_react", ui_text("ui_damageprm_sub_reaction"),"uint", ui_text("ui_damageprm_sub_reaction_type_used_by_bind_variants_integer")),
]


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class DamagePrmEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t           = t or (lambda k, **kw: k)
        self._embedded    = embedded
        self._filepath    = None
        self._raw         = None
        self._result      = None
        self._dirty       = False
        self._current_idx = -1
        self._entry_buttons = []
        self._field_widgets = {}  # key → (QLineEdit, hint_label | None)

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

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        body.addWidget(div)

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

        name_lbl = QLabel(entry['name'])
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        vl.addWidget(name_lbl)

        id_lbl = QLabel(ui_text("ui_damageeff_slot_value", p0=entry['idx']))
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
            if ft and ft not in entry['name'].lower():
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
        lbl = QLabel(ui_text("ui_damageprm_open_a_damageprm_bin_xfbin_file_to_begin_editing"))
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

        hdr = QLabel(entry['name'])
        hdr.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        self._main_layout.addWidget(hdr)

        # Fields card
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        card_inner = QWidget()
        card_inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(card_inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(4)

        for i, (fkey, fname, ftype, tip) in enumerate(_FIELDS):
            col  = i % 2
            vrow = i // 2
            gr   = vrow * 3

            lbl = QLabel(fname)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(ss_field_label())
            lbl.setToolTip(tip)
            grid.addWidget(lbl, gr, col)

            val = entry[fkey]
            text = f"{val:.4g}" if ftype == 'float' else str(val)
            inp = QLineEdit(text)
            inp.setFixedHeight(30)
            inp.setFont(QFont("Consolas", 13))
            inp.setStyleSheet(ss_input())
            inp.setToolTip(tip)
            inp.textEdited.connect(lambda _, fk=fkey: self._mark_dirty())
            grid.addWidget(inp, gr + 1, col)

            hint_lbl = None
            if fkey == 'reaction':
                hint_lbl = QLabel(_REACTION_NAMES.get(val, f"Unknown ({val})"))
                hint_lbl.setFont(QFont("Consolas", 10))
                hint_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
                grid.addWidget(hint_lbl, gr + 2, col)

            self._field_widgets[fkey] = (inp, hint_lbl)

        card_lo = QVBoxLayout(card)
        card_lo.setContentsMargins(0, 0, 0, 0)
        card_lo.addWidget(card_inner)
        self._main_layout.addWidget(card)

        # Reaction type legend
        self._main_layout.addWidget(self._build_reaction_legend())
        self._main_layout.addStretch(1)

    def _build_reaction_legend(self):
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        lo = QVBoxLayout(frame)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(6)

        title = QLabel(ui_text("ui_damageprm_reaction_type_ids"))
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(ss_section_label())
        lo.addWidget(title)

        row_w = QWidget()
        row_w.setStyleSheet("background: transparent;")
        row_lo = QHBoxLayout(row_w)
        row_lo.setContentsMargins(0, 0, 0, 0)
        row_lo.setSpacing(24)

        items = sorted(_REACTION_NAMES.items())
        half = (len(items) + 1) // 2
        for col_items in [items[:half], items[half:]]:
            col_w = QWidget()
            col_w.setStyleSheet("background: transparent;")
            col_l = QVBoxLayout(col_w)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(1)
            for rid, rname in col_items:
                lbl = QLabel(ui_text("ui_damageprm_value_value", p0=rid, p1=rname))
                lbl.setFont(QFont("Consolas", 9))
                lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
                col_l.addWidget(lbl)
            row_lo.addWidget(col_w)

        row_lo.addStretch()
        lo.addWidget(row_w)
        return frame

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
        for fkey, fname, ftype, _ in _FIELDS:
            if fkey not in self._field_widgets:
                continue
            inp, hint_lbl = self._field_widgets[fkey]
            try:
                value = float(inp.text()) if ftype == 'float' else int(inp.text(), 0)
            except (ValueError, TypeError):
                inp.setText(f"{entry[fkey]:.4g}" if ftype == 'float' else str(entry[fkey]))
                continue
            if entry[fkey] != value:
                entry[fkey] = value
                changed = True
            if fkey == 'reaction' and hint_lbl:
                iv = int(value)
                hint_lbl.setText(_REACTION_NAMES.get(iv, f"Unknown ({iv})"))
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

        self._build_editor(self._result['entries'][idx])

    # Search

    def _on_search(self, text):
        self._populate_sidebar(filter_text=text)

    # Data loading

    def _load_file(self, filepath):
        create_backup_on_open(filepath)
        try:
            raw, result = parse_damageprm_xfbin(filepath)
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

    # File I/O

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_damageprm_open_damageprm_bin_xfbin"), game_files_dialog_dir(target_patterns="damageprm.bin.xfbin"),
            "XFBIN Files (damageprm.bin.xfbin);;All Files (*.*)"
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
            save_damageprm_xfbin(filepath, self._raw, self._result)
            self._dirty = False
            set_file_label(self._file_lbl, filepath)
            QMessageBox.information(self, ui_text("ui_assist_saved"), ui_text("ui_assist_file_saved_value", p0=os.path.basename(filepath)))
        except Exception as e:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=e))
