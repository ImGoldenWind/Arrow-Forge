import copy
import os
import threading

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QTabWidget, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_input, ss_search, ss_sidebar_btn,
    ss_section_label, ss_field_label, ss_file_label, ss_scrollarea, ss_sep,
    ss_scrollarea_transparent, ss_tab_widget, ss_tab_bar,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label, set_file_label_empty
from parsers.skill_parser import (
    parse_prm_xfbin, save_prm_xfbin,
    parse_prmload_xfbin, save_prmload_xfbin,
    write_mot_entry, write_mot_subentry,
    make_default_mot_entry, make_default_mot_subentry, write_mot,
    DATA_TYPE_MAP, FUNC_MAP_1B, PRMLOAD_TYPE_NAMES, ANM_SPEED_FUNC_NAMES,
    FWD_VELOCITY_FUNC_NAMES, GION_FUNC_NAMES, ATKHIT_FUNC_NAMES,
    MOT_SUB_SIZE,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir

FUNC_PARAM_FIELD_NAMES = {
    'ME_CANCEL_OP_ADD', 'ME_CANCEL_OP_SUB', 'ME_CANCEL_OP_SET',
    'ME_BODHIT_ON', 'ME_BODHIT_OFF',
    'ME_INVINCIBLE_ON', 'ME_INVINCIBLE_OFF',
}


# Shared helpers

def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _make_field(label_text, value_text):
    """Returns (container_widget, QLineEdit)."""
    f = QWidget()
    f.setStyleSheet("background: transparent;")
    fl = QVBoxLayout(f)
    fl.setContentsMargins(0, 0, 0, 0)
    fl.setSpacing(2)
    lbl = QLabel(str(label_text))
    lbl.setFont(QFont("Segoe UI", 12))
    lbl.setStyleSheet(ss_field_label())
    fl.addWidget(lbl)
    e = QLineEdit(str(value_text))
    e.setFixedHeight(30)
    e.setFont(QFont("Consolas", 13))
    e.setStyleSheet(ss_input())
    fl.addWidget(e)
    return f, e


def _make_combo_field(label_text, items, current):
    """Returns (container_widget, QComboBox)."""
    f = QWidget()
    f.setStyleSheet("background: transparent;")
    fl = QVBoxLayout(f)
    fl.setContentsMargins(0, 0, 0, 0)
    fl.setSpacing(2)
    lbl = QLabel(str(label_text))
    lbl.setFont(QFont("Segoe UI", 12))
    lbl.setStyleSheet(ss_field_label())
    fl.addWidget(lbl)
    cb = QComboBox()
    cb.addItems(items)
    cb.setFixedHeight(30)
    cb.setFont(QFont("Consolas", 13))
    cb.setStyleSheet(ss_input())
    cb.blockSignals(True)
    cb.setCurrentText(str(current))
    cb.blockSignals(False)
    fl.addWidget(cb)
    return f, cb


def _section_label(text):
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
    lbl.setStyleSheet(ss_section_label())
    lbl.setContentsMargins(20, 10, 0, 2)
    return lbl


def _card_frame():
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
    return f


def _sidebar_search(placeholder):
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setFixedHeight(32)
    e.setFont(QFont("Segoe UI", 13))
    e.setStyleSheet(ss_search())
    return e


def _sidebar_scroll():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(ss_scrollarea_transparent())
    inner = QWidget()
    inner.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(1)
    layout.addStretch()
    scroll.setWidget(inner)
    return scroll, inner, layout


def _entry_btn(title, subtitle, selected, on_click):
    btn = QPushButton()
    btn.setFixedHeight(44)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(ss_sidebar_btn(selected=selected))
    bl = QVBoxLayout(btn)
    bl.setContentsMargins(10, 3, 10, 3)
    bl.setSpacing(0)
    name_lbl = QLabel(title)
    name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
    name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    bl.addWidget(name_lbl)
    if subtitle:
        sub_lbl = QLabel(subtitle)
        sub_lbl.setFont(QFont("Segoe UI", 11))
        sub_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(sub_lbl)
    btn.clicked.connect(on_click)
    return btn


def _right_scroll():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(ss_scrollarea())
    inner = QWidget()
    inner.setStyleSheet(f"background-color: {P['bg_dark']};")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    scroll.setWidget(inner)
    return scroll, layout


def _placeholder_label(text):
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 15))
    lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setContentsMargins(0, 60, 0, 60)
    return lbl


_LOAD_TYPE_NAMES = {
    0: 'NULL', 3: 'GHH', 6: 'PRM_BIN', 9: 'ACCESSORY',
    10: 'EFFECT', 11: 'MOTION', 12: 'MODEL', 13: 'SKILL', 14: 'SPECIAL',
}


# Skill Slots Tab
class _SklslotTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._selected = -1
        self._slot_btns = []  # list of (btn, idx)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 8, 8, 4)
        sl.setSpacing(4)

        self._search = _sidebar_search(ui_text("ui_skill_search_slots"))
        self._search.textChanged.connect(self._filter_list)
        sl.addWidget(self._search)

        abf = QWidget()
        abf.setStyleSheet("background: transparent;")
        abl = QHBoxLayout(abf)
        abl.setContentsMargins(0, 2, 0, 4)
        abl.setSpacing(4)
        bf = QFont("Segoe UI", 10)

        self._new_btn = QPushButton(ui_text("btn_new"))
        self._new_btn.setFixedHeight(28)
        self._new_btn.setFont(bf)
        self._new_btn.setStyleSheet(ss_btn())
        self._new_btn.setEnabled(False)
        self._new_btn.setToolTip(ui_text("ui_skill_add_slot_tooltip"))
        self._new_btn.clicked.connect(self._add_slot)
        abl.addWidget(self._new_btn, 1)

        self._dup_btn = QPushButton(ui_text("btn_duplicate"))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(bf)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.setEnabled(False)
        self._dup_btn.setToolTip(ui_text("ui_skill_duplicate_slot_tooltip"))
        self._dup_btn.clicked.connect(self._dup_slot)
        abl.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(ui_text("btn_delete"))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(bf)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.setEnabled(False)
        self._del_btn.setToolTip(ui_text("ui_skill_delete_slot_tooltip"))
        self._del_btn.clicked.connect(self._del_slot)
        abl.addWidget(self._del_btn, 1)
        sl.addWidget(abf)

        self._list_scroll, self._list_widget, self._list_layout = _sidebar_scroll()
        sl.addWidget(self._list_scroll)
        root.addWidget(sidebar)

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        root.addWidget(div)

        self._editor_scroll, self._editor_layout = _right_scroll()
        self._editor_layout.addWidget(_placeholder_label(ui_text("ui_skill_select_a_slot")))
        self._editor_layout.addStretch()
        root.addWidget(self._editor_scroll, 1)

    def _set_action_state(self, loaded, has_selection=False):
        self._new_btn.setEnabled(loaded)
        self._dup_btn.setEnabled(loaded and has_selection)
        self._del_btn.setEnabled(loaded and has_selection)

    def set_placeholder(self, text, loaded=False):
        self._entries = []
        self._selected = -1
        self._rebuild_list()
        self._set_action_state(loaded, False)
        _clear_layout(self._editor_layout)
        self._editor_layout.addWidget(_placeholder_label(text))
        self._editor_layout.addStretch()

    def load(self, entries):
        self._entries = [dict(e) for e in entries]
        self._selected = -1
        self._rebuild_list()
        self._set_action_state(True, False)
        _clear_layout(self._editor_layout)
        self._editor_layout.addWidget(_placeholder_label(ui_text("ui_skill_select_a_slot_2")))
        self._editor_layout.addStretch()

    def get_entries(self):
        return [dict(e) for e in self._entries]

    @staticmethod
    def _is_end_entry(entry):
        return entry.get('xfbin', '').strip().upper() == 'END'

    def _non_end_entries(self):
        return [e for e in self._entries if not self._is_end_entry(e)]

    def _insert_index(self):
        if self._entries and self._is_end_entry(self._entries[-1]):
            return len(self._entries) - 1
        return len(self._entries)

    def _make_default_slot(self):
        usable = self._non_end_entries()
        prefix = 'NEW'
        max_num = len(usable)
        xfbin = 'char_x.xfbin'

        for entry in usable:
            name = entry.get('slot_name', '')
            if '_SLOT_' in name:
                candidate_prefix, candidate_num = name.rsplit('_SLOT_', 1)
                if candidate_prefix:
                    prefix = candidate_prefix
                if candidate_num.isdigit():
                    max_num = max(max_num, int(candidate_num))
            if entry.get('xfbin'):
                xfbin = entry['xfbin']

        next_num = max_num + 1
        slot_name = f"{prefix}_SLOT_{next_num:02d}"
        skill_prefix = prefix.lower()
        return {
            'slot_name': slot_name,
            'xfbin': xfbin,
            'skill_id': f"{skill_prefix}_skl_new_{next_num:02d}",
        }

    def _rebuild_list(self):
        _clear_layout(self._list_layout)
        self._slot_btns = []
        for i, e in enumerate(self._entries):
            btn = _entry_btn(
                e['slot_name'], e['skill_id'],
                selected=(i == self._selected),
                on_click=lambda _, idx=i: self._select_slot(idx),
            )
            self._list_layout.insertWidget(self._list_layout.count(), btn)
            self._slot_btns.append((btn, i))
        self._list_layout.addStretch()

    def _filter_list(self):
        q = self._search.text().lower()
        for btn, i in self._slot_btns:
            if i >= len(self._entries):
                continue
            e = self._entries[i]
            btn.setVisible(q in e['slot_name'].lower() or q in e['skill_id'].lower())

    def _select_slot(self, idx):
        self._selected = idx
        for btn, i in self._slot_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))
        can_edit = 0 <= idx < len(self._entries) and not self._is_end_entry(self._entries[idx])
        self._set_action_state(True, can_edit)
        self._build_editor(idx)

    def _build_editor(self, idx):
        _clear_layout(self._editor_layout)
        e = self._entries[idx]
        is_end = self._is_end_entry(e)

        card = _card_frame()
        inner = QWidget(card)
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        card_main = QVBoxLayout(card)
        card_main.setContentsMargins(0, 0, 0, 0)
        card_main.addWidget(inner)

        for ci, (key, label) in enumerate([
            ('slot_name', ui_text("skill_field_slot_name")),
            ('xfbin',     ui_text("ui_skill_xfbin_file")),
            ('skill_id',  ui_text("ui_projectile_skill_id")),
        ]):
            fw, field = _make_field(label, e[key])
            field.setReadOnly(is_end)
            grid.addWidget(fw, 0, ci)
            grid.setColumnStretch(ci, 1)
            if not is_end:
                field.editingFinished.connect(
                    lambda k=key, f=field, i=idx: self._commit(i, k, f)
                )

        self._editor_layout.addWidget(card)
        self._editor_layout.addStretch()

    def _commit(self, idx, key, field):
        if idx >= len(self._entries):
            return
        self._entries[idx][key] = field.text()
        if key in ('slot_name', 'skill_id') and idx < len(self._slot_btns):
            btn = self._slot_btns[idx][0]
            lbls = btn.findChildren(QLabel)
            if key == 'slot_name' and lbls:
                lbls[0].setText(field.text())
            elif key == 'skill_id' and len(lbls) > 1:
                lbls[1].setText(field.text())
        self._set_action_state(True, not self._is_end_entry(self._entries[idx]))
        self.changed.emit()

    def _add_slot(self):
        insert_at = self._insert_index()
        self._entries.insert(insert_at, self._make_default_slot())
        self._rebuild_list()
        self._select_slot(insert_at)
        self.changed.emit()

    def _dup_slot(self):
        if self._selected < 0 or self._selected >= len(self._entries):
            return
        if self._is_end_entry(self._entries[self._selected]):
            QMessageBox.warning(
                self,
                ui_text("dlg_title_warning"),
                ui_text("ui_skill_cannot_modify_end_slot"),
            )
            return
        new_e = dict(self._entries[self._selected])
        new_e['slot_name'] += '_copy'
        insert_at = self._insert_index()
        self._entries.insert(insert_at, new_e)
        self._rebuild_list()
        self._select_slot(insert_at)
        self.changed.emit()

    def _del_slot(self):
        if self._selected < 0 or self._selected >= len(self._entries):
            return
        if self._is_end_entry(self._entries[self._selected]):
            QMessageBox.warning(
                self,
                ui_text("dlg_title_warning"),
                ui_text("ui_skill_cannot_modify_end_slot"),
            )
            return
        if len(self._non_end_entries()) <= 1:
            QMessageBox.warning(
                self,
                ui_text("dlg_title_warning"),
                ui_text("msg_cannot_delete_last_entry"),
            )
            return
        self._entries.pop(self._selected)
        self._selected = -1
        self._rebuild_list()
        self._set_action_state(True, False)
        _clear_layout(self._editor_layout)
        self._editor_layout.addWidget(_placeholder_label(ui_text("ui_skill_select_a_slot")))
        self._editor_layout.addStretch()
        self.changed.emit()


# Load Config Tab
class _LoadTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._editor_scroll, self._editor_layout = _right_scroll()
        self._editor_layout.addStretch()
        root.addWidget(self._editor_scroll, 1)

    def load(self, entries):
        self._entries = [dict(e) for e in entries]
        self._rebuild()

    def get_entries(self):
        return [dict(e) for e in self._entries]

    def _rebuild(self):
        _clear_layout(self._editor_layout)
        for i, e in enumerate(self._entries):
            self._editor_layout.addWidget(self._make_card(i, e))
        self._editor_layout.addStretch()

    def _make_card(self, i, e):
        tname = _LOAD_TYPE_NAMES.get(e['type'], str(e['type']))
        card = _card_frame()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        hdr = QLabel(ui_text("ui_mainmodeparam_value_value", p0=i, p1=tname))
        hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        cl.addWidget(hdr)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        fw0, f_type = _make_field(ui_text("ui_dlcinfoparam_type"), e['type'])
        grid.addWidget(fw0, 0, 0)
        grid.setColumnStretch(0, 1)
        f_type.editingFinished.connect(lambda fe=f_type, idx=i: self._commit_type(idx, fe))

        flag_val = str(e['flag']) if e['flag'] is not None else ''
        fw1, f_flag = _make_field(ui_text("skill_field_flag"), flag_val)
        grid.addWidget(fw1, 0, 1)
        grid.setColumnStretch(1, 1)
        f_flag.editingFinished.connect(lambda fe=f_flag, idx=i: self._commit_flag(idx, fe))

        fw2, f_cat = _make_field(ui_text("skill_field_category"), e['category'])
        grid.addWidget(fw2, 1, 0)
        f_cat.editingFinished.connect(lambda fe=f_cat, idx=i: self._commit_str(idx, 'category', fe))

        fw3, f_code = _make_field(ui_text("ui_dlcinfoparam_code"), e['code'])
        grid.addWidget(fw3, 1, 1)
        f_code.editingFinished.connect(lambda fe=f_code, idx=i: self._commit_str(idx, 'code', fe))

        cl.addLayout(grid)
        return card

    def _commit_type(self, idx, field):
        try:
            self._entries[idx]['type'] = int(field.text().split()[0])
            self.changed.emit()
        except Exception:
            pass

    def _commit_flag(self, idx, field):
        txt = field.text().strip()
        try:
            self._entries[idx]['flag'] = None if txt in ('', '-', '—') else int(txt)
            self.changed.emit()
        except Exception:
            pass

    def _commit_str(self, idx, key, field):
        self._entries[idx][key] = field.text()
        self.changed.emit()


# Standalone prm_load Tab
class _PrmLoadStandaloneTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._editor_scroll, self._editor_layout = _right_scroll()
        self._editor_layout.addStretch()
        root.addWidget(self._editor_scroll, 1)

    def load(self, entries):
        self._entries = [dict(e) for e in entries]
        self._rebuild()

    def get_entries(self):
        return [dict(e) for e in self._entries]

    def _rebuild(self):
        _clear_layout(self._editor_layout)
        for i, e in enumerate(self._entries):
            self._editor_layout.addWidget(self._make_card(i, e))
        self._editor_layout.addStretch()

    def _make_card(self, i, e):
        tname = PRMLOAD_TYPE_NAMES.get(e['type'], str(e['type']))
        card = _card_frame()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        hdr = QLabel(ui_text("ui_mainmodeparam_value_value", p0=i, p1=tname))
        hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        cl.addWidget(hdr)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        fw0, f_type = _make_field(ui_text("ui_dlcinfoparam_type"), e['type'])
        grid.addWidget(fw0, 0, 0)
        grid.setColumnStretch(0, 1)
        f_type.editingFinished.connect(lambda fe=f_type, idx=i: self._commit_type(idx, fe))

        fw1, f_folder = _make_field(ui_text("ui_skill_folder"), e['folder'])
        grid.addWidget(fw1, 0, 1)
        grid.setColumnStretch(1, 1)
        f_folder.editingFinished.connect(lambda fe=f_folder, idx=i: self._commit_str(idx, 'folder', fe))

        fw2, f_xfbin = _make_field(ui_text("ui_skill_xfbin_file"), e['xfbin'])
        grid.addWidget(fw2, 1, 0)
        f_xfbin.editingFinished.connect(lambda fe=f_xfbin, idx=i: self._commit_str(idx, 'xfbin', fe))

        fw3, f_unk2 = _make_field("unk2", e['unk2'])
        grid.addWidget(fw3, 1, 1)
        f_unk2.editingFinished.connect(lambda fe=f_unk2, idx=i: self._commit_int(idx, 'unk2', fe))

        cl.addLayout(grid)
        return card

    def _commit_type(self, idx, field):
        try:
            self._entries[idx]['type'] = int(field.text().split()[0])
            self.changed.emit()
        except Exception:
            pass

    def _commit_str(self, idx, key, field):
        self._entries[idx][key] = field.text()
        self.changed.emit()

    def _commit_int(self, idx, key, field):
        try:
            self._entries[idx][key] = int(field.text())
            self.changed.emit()
        except Exception:
            pass


# Motion Data Tab
class _MotTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._mot_raw = None
        self._cur_entry = None
        self._entry_btns = []  # list of (btn, entry)
        self._structural_dirty = False
        self._entry_add_btn = None
        self._entry_dup_btn = None
        self._entry_del_btn = None
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 8, 8, 4)
        sl.setSpacing(4)

        self._search = _sidebar_search(ui_text("ui_messageinfo_search_entries"))
        self._search.textChanged.connect(self._filter_entries)
        sl.addWidget(self._search)

        abf = QWidget()
        abf.setStyleSheet("background: transparent;")
        abl = QHBoxLayout(abf)
        abl.setContentsMargins(0, 2, 0, 4)
        abl.setSpacing(4)
        bf = QFont("Segoe UI", 10)

        self._entry_add_btn = QPushButton(ui_text("btn_new"))
        self._entry_add_btn.setFixedHeight(28)
        self._entry_add_btn.setFont(bf)
        self._entry_add_btn.setStyleSheet(ss_btn())
        self._entry_add_btn.setEnabled(False)
        self._entry_add_btn.setToolTip(ui_text("ui_skill_add_motion_entry_tooltip"))
        self._entry_add_btn.clicked.connect(self._add_entry)
        abl.addWidget(self._entry_add_btn, 1)

        self._entry_dup_btn = QPushButton(ui_text("btn_duplicate"))
        self._entry_dup_btn.setFixedHeight(28)
        self._entry_dup_btn.setFont(bf)
        self._entry_dup_btn.setStyleSheet(ss_btn())
        self._entry_dup_btn.setEnabled(False)
        self._entry_dup_btn.setToolTip(ui_text("ui_skill_duplicate_motion_entry_tooltip"))
        self._entry_dup_btn.clicked.connect(self._dup_entry)
        abl.addWidget(self._entry_dup_btn, 1)

        self._entry_del_btn = QPushButton(ui_text("btn_delete"))
        self._entry_del_btn.setFixedHeight(28)
        self._entry_del_btn.setFont(bf)
        self._entry_del_btn.setStyleSheet(ss_btn(danger=True))
        self._entry_del_btn.setEnabled(False)
        self._entry_del_btn.setToolTip(ui_text("ui_skill_delete_motion_entry_tooltip"))
        self._entry_del_btn.clicked.connect(self._del_entry)
        abl.addWidget(self._entry_del_btn, 1)
        sl.addWidget(abf)

        self._list_scroll, self._list_widget, self._list_layout = _sidebar_scroll()
        sl.addWidget(self._list_scroll)
        root.addWidget(sidebar)

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        root.addWidget(div)

        self._editor_scroll, self._editor_layout = _right_scroll()
        self._editor_layout.addWidget(_placeholder_label(ui_text("ui_skill_select_an_animation_entry")))
        self._editor_layout.addStretch()
        root.addWidget(self._editor_scroll, 1)

    def _set_action_state(self):
        loaded = self._mot_raw is not None
        selected = self._cur_entry is not None
        self._entry_add_btn.setEnabled(loaded)
        self._entry_dup_btn.setEnabled(loaded and selected)
        self._entry_del_btn.setEnabled(loaded and selected and len(self._entries) > 1)

    def load(self, entries, mot_raw):
        self._entries = entries
        self._mot_raw = mot_raw
        self._cur_entry = None
        self._structural_dirty = False
        self._populate_list(entries)
        self._set_action_state()

    def _populate_list(self, entries):
        _clear_layout(self._list_layout)
        self._entry_btns = []
        for e in entries:
            n = e.get('n_subs', len(e.get('subentries', [])))
            subtitle = f"{n} subs" if n > 0 else None
            btn = _entry_btn(
                e['event_id'], subtitle,
                selected=(e is self._cur_entry),
                on_click=lambda _, entry=e: self._on_entry_click(entry),
            )
            self._list_layout.insertWidget(self._list_layout.count(), btn)
            self._entry_btns.append((btn, e))
        self._list_layout.addStretch()

    def _filter_entries(self, text):
        text = text.lower()
        filtered = [
            e for e in self._entries
            if (
                text in e['event_id'].lower()
                or text in e.get('anim_id', '').lower()
                or any(
                    text in sub.get('bone', '').lower()
                    or text in sub.get('dmg_label', '').lower()
                    or text in sub.get('func_name', '').lower()
                    for sub in e.get('subentries', [])
                )
            )
        ]
        self._populate_list(filtered)

    def _on_entry_click(self, entry):
        self._cur_entry = entry
        for btn, e in self._entry_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(e is entry)))
        self._set_action_state()
        self._show_entry(entry)

    def get_entries(self):
        return self._entries

    def get_raw(self):
        if self._mot_raw is None:
            return None
        if self._structural_dirty:
            self._mot_raw = write_mot(self._entries, self._mot_raw)
            self._structural_dirty = False
        return self._mot_raw

    def _refresh_list(self):
        self._filter_entries(self._search.text())
        self._set_action_state()

    def _clear_editor_placeholder(self):
        _clear_layout(self._editor_layout)
        self._editor_layout.addWidget(_placeholder_label(ui_text("ui_skill_select_an_animation_entry")))
        self._editor_layout.addStretch()

    def _add_entry(self):
        new_entry = make_default_mot_entry(len(self._entries) + 1)
        self._entries.append(new_entry)
        self._cur_entry = new_entry
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(new_entry)
        self.changed.emit()

    def _dup_entry(self):
        if self._cur_entry is None:
            return
        new_entry = copy.deepcopy(self._cur_entry)
        new_entry['offset'] = None
        new_entry['event_id'] = f"{new_entry.get('event_id', 'PL_ANM')}_copy"
        for sub in new_entry.get('subentries', []):
            sub['sub_off'] = None
        self._entries.append(new_entry)
        self._cur_entry = new_entry
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(new_entry)
        self.changed.emit()

    def _del_entry(self):
        if self._cur_entry is None:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(
                self,
                ui_text("dlg_title_warning"),
                ui_text("msg_cannot_delete_last_entry"),
            )
            return
        self._entries = [e for e in self._entries if e is not self._cur_entry]
        self._cur_entry = None
        self._structural_dirty = True
        self._refresh_list()
        self._clear_editor_placeholder()
        self.changed.emit()

    def _show_entry(self, entry):
        _clear_layout(self._editor_layout)

        # Header card
        card = _card_frame()
        inner = QWidget(card)
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        cm = QVBoxLayout(card)
        cm.setContentsMargins(0, 0, 0, 0)
        cm.addWidget(inner)

        fw_ev, f_ev = _make_field(ui_text("ui_guidecharparam_event_id"), entry['event_id'])
        grid.addWidget(fw_ev, 0, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        f_ev.textEdited.connect(lambda t, e=entry: self._on_ev_edited(t, e))

        fw_an, f_an = _make_field(ui_text("ui_playertitleparam_anim_id"), entry['anim_id'])
        grid.addWidget(fw_an, 0, 2, 1, 2)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        f_an.textEdited.connect(lambda t, e=entry: self._on_an_edited(t, e))

        flag_defs = [
            ('enable_face_animation', ui_text("ui_skill_faceanim")),
            ('no_frame_skip',         ui_text("ui_skill_nofrmskip")),
            ('fix_position',          ui_text("ui_skill_fixpos")),
            ('frame_skip',            ui_text("ui_skill_frmskip")),
            ('file_id',               ui_text("ui_skill_fileid")),
        ]
        for col, (key, label) in enumerate(flag_defs):
            fw, fe = _make_field(label, entry.get(key, 0))
            grid.addWidget(fw, 1, col)
            grid.setColumnStretch(col, 1)
            fe.editingFinished.connect(
                lambda k=key, f=fe, e=entry: self._on_flag_edited(k, f, e)
            )

        self._editor_layout.addWidget(card)

        action_row = QWidget()
        action_row.setStyleSheet("background: transparent;")
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(20, 0, 20, 0)
        action_layout.setSpacing(6)
        bf = QFont("Segoe UI", 10)

        add_sub_btn = QPushButton(ui_text("ui_skill_add_subentry"))
        add_sub_btn.setFixedHeight(28)
        add_sub_btn.setFont(bf)
        add_sub_btn.setStyleSheet(ss_btn())
        add_sub_btn.clicked.connect(lambda _, e=entry: self._add_subentry(e))
        action_layout.addWidget(add_sub_btn)

        dup_sub_btn = QPushButton(ui_text("ui_skill_duplicate_last_subentry"))
        dup_sub_btn.setFixedHeight(28)
        dup_sub_btn.setFont(bf)
        dup_sub_btn.setStyleSheet(ss_btn())
        dup_sub_btn.setEnabled(bool(entry.get('subentries')))
        dup_sub_btn.clicked.connect(lambda _, e=entry: self._dup_last_subentry(e))
        action_layout.addWidget(dup_sub_btn)

        del_sub_btn = QPushButton(ui_text("ui_skill_delete_last_subentry"))
        del_sub_btn.setFixedHeight(28)
        del_sub_btn.setFont(bf)
        del_sub_btn.setStyleSheet(ss_btn(danger=True))
        del_sub_btn.setEnabled(bool(entry.get('subentries')))
        del_sub_btn.clicked.connect(lambda _, e=entry: self._del_last_subentry(e))
        action_layout.addWidget(del_sub_btn)

        action_layout.addStretch()
        self._editor_layout.addWidget(action_row)

        # Subentry cards
        subs = entry.get('subentries', [])
        if subs:
            self._editor_layout.addWidget(_section_label(ui_text("ui_skill_subentries")))
            for r, s in enumerate(subs):
                self._editor_layout.addWidget(self._make_sub_card(entry, r, s))

        self._editor_layout.addStretch()

    def _add_subentry(self, entry):
        subs = entry.setdefault('subentries', [])
        self._insert_subentry(entry, len(subs))

    def _dup_last_subentry(self, entry):
        subs = entry.setdefault('subentries', [])
        if not subs:
            return
        self._duplicate_subentry(entry, len(subs) - 1)

    def _del_last_subentry(self, entry):
        subs = entry.setdefault('subentries', [])
        if not subs:
            return
        self._delete_subentry(entry, len(subs) - 1)

    def _insert_subentry(self, entry, index, template=None):
        subs = entry.setdefault('subentries', [])
        index = max(0, min(index, len(subs)))
        new_sub = copy.deepcopy(template) if template is not None else make_default_mot_subentry(index + 1)
        new_sub['sub_off'] = None
        subs.insert(index, new_sub)
        entry['n_subs'] = len(subs)
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(entry)
        self.changed.emit()

    def _duplicate_subentry(self, entry, index):
        subs = entry.setdefault('subentries', [])
        if not (0 <= index < len(subs)):
            return
        self._insert_subentry(entry, index + 1, subs[index])

    def _delete_subentry(self, entry, index):
        subs = entry.setdefault('subentries', [])
        if not (0 <= index < len(subs)):
            return
        subs.pop(index)
        entry['n_subs'] = len(subs)
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(entry)
        self.changed.emit()

    def _make_sub_card(self, entry, r, s):
        card = _card_frame()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        hdr_lbl = QLabel(ui_text("ui_skill_value_value_value", p0=r, p1=s.get('bone', ''), p2=s.get('func_name', '')))
        hdr_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        hdr_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        cl.addWidget(hdr_lbl)

        sub_action_row = QWidget()
        sub_action_row.setStyleSheet("background: transparent;")
        sub_action_layout = QHBoxLayout(sub_action_row)
        sub_action_layout.setContentsMargins(0, 0, 0, 0)
        sub_action_layout.setSpacing(6)
        sf = QFont("Segoe UI", 9)

        insert_above_btn = QPushButton(ui_text("ui_skill_insert_subentry_above"))
        insert_above_btn.setFixedHeight(26)
        insert_above_btn.setFont(sf)
        insert_above_btn.setStyleSheet(ss_btn())
        insert_above_btn.clicked.connect(lambda _, e=entry, idx=r: self._insert_subentry(e, idx))
        sub_action_layout.addWidget(insert_above_btn)

        insert_below_btn = QPushButton(ui_text("ui_skill_insert_subentry_below"))
        insert_below_btn.setFixedHeight(26)
        insert_below_btn.setFont(sf)
        insert_below_btn.setStyleSheet(ss_btn())
        insert_below_btn.clicked.connect(lambda _, e=entry, idx=r: self._insert_subentry(e, idx + 1))
        sub_action_layout.addWidget(insert_below_btn)

        duplicate_here_btn = QPushButton(ui_text("ui_skill_duplicate_subentry_here"))
        duplicate_here_btn.setFixedHeight(26)
        duplicate_here_btn.setFont(sf)
        duplicate_here_btn.setStyleSheet(ss_btn())
        duplicate_here_btn.clicked.connect(lambda _, e=entry, idx=r: self._duplicate_subentry(e, idx))
        sub_action_layout.addWidget(duplicate_here_btn)

        delete_here_btn = QPushButton(ui_text("ui_skill_delete_subentry_here"))
        delete_here_btn.setFixedHeight(26)
        delete_here_btn.setFont(sf)
        delete_here_btn.setStyleSheet(ss_btn(danger=True))
        delete_here_btn.clicked.connect(lambda _, e=entry, idx=r: self._delete_subentry(e, idx))
        sub_action_layout.addWidget(delete_here_btn)

        sub_action_layout.addStretch()
        cl.addWidget(sub_action_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        # Row 0: Bone | Type | Frame | Attack
        fw0, f_bone  = _make_field(ui_text("bone_col_bone"),  s.get('bone', ''))
        fw1, f_type  = _make_field(ui_text("ui_dlcinfoparam_type"),  s.get('dtype', 0))
        fw2, f_frame = _make_field(ui_text("skill_field_frame_num"), s.get('frame_str', ''))
        fw3, f_attack = _make_combo_field(
            ui_text("ui_skill_attack"),
            ['', 'high', 'middle', 'low', 'unblockable'],
            s.get('attack', ''),
        )
        grid.addWidget(fw0, 0, 0); grid.setColumnStretch(0, 1)
        grid.addWidget(fw1, 0, 1); grid.setColumnStretch(1, 1)
        grid.addWidget(fw2, 0, 2); grid.setColumnStretch(2, 1)
        grid.addWidget(fw3, 0, 3); grid.setColumnStretch(3, 1)

        # Row 1: Dmg | Grd | X | Y
        fw4, f_dmg = _make_field(ui_text("ui_skill_dmg"), s.get('dmg', 0) or 0)
        fw5, f_grd = _make_field(ui_text("ui_skill_grd"), s.get('grd', 0) or 0)
        fw6, f_x   = _make_field("X",   f"{s['x']:.6g}" if s.get('x') else '0')
        fw7, f_y   = _make_field("Y",   f"{s['y']:.6g}" if s.get('y') else '0')
        grid.addWidget(fw4, 1, 0)
        grid.addWidget(fw5, 1, 1)
        grid.addWidget(fw6, 1, 2)
        grid.addWidget(fw7, 1, 3)

        # Row 2: Push | Speed/FWD params | Function (spans 2 cols)
        fw8, f_push = _make_field(ui_text("ui_skill_push"), s.get('push', 0))
        grid.addWidget(fw8, 2, 0)

        fw_speed, f_speed = _make_field(
            ui_text("skill_field_speed"),
            f"{s.get('speed_multiplier', 1.0):.6g}",
        )
        grid.addWidget(fw_speed, 2, 1)

        fw_fwd_vel, f_fwd_vel = _make_field(
            ui_text("skill_field_fwd_velocity"),
            s.get('fwd_velocity', 0),
        )
        grid.addWidget(fw_fwd_vel, 3, 0)

        fw_fwd_dur, f_fwd_dur = _make_field(
            ui_text("skill_field_duration_frames"),
            s.get('fwd_velocity_duration', 0),
        )
        grid.addWidget(fw_fwd_dur, 3, 1)

        fw_gion_id, f_gion_id = _make_field(
            ui_text("skill_field_gion_id"),
            s.get('gion_id', ''),
        )
        grid.addWidget(fw_gion_id, 3, 2)

        fw_gion_scale, f_gion_scale = _make_field(
            ui_text("skill_field_gion_scale"),
            f"{s.get('gion_scale', 1.0):.6g}",
        )
        grid.addWidget(fw_gion_scale, 3, 3)

        atkhit_values = list(s.get('atkhit_params', [0, 0, 0, 0, 0]))
        atkhit_values.extend([0] * (5 - len(atkhit_values)))
        atkhit_fields = []
        for i in range(5):
            fw_param, f_param = _make_field(
                ui_text("skill_field_atkhit_param_n", n=i + 1),
                atkhit_values[i],
            )
            row = 4 + (i // 4)
            col = i % 4
            grid.addWidget(fw_param, row, col)
            atkhit_fields.append((fw_param, f_param))

        func_param_values = list(s.get('func_param_bytes', [0, 0, 0]))
        func_param_values.extend([0] * (3 - len(func_param_values)))
        func_param_fields = []
        for i in range(3):
            fw_param, f_param = _make_field(
                ui_text("skill_field_func_byte_n", n=i + 1),
                func_param_values[i],
            )
            grid.addWidget(fw_param, 6, i)
            func_param_fields.append((fw_param, f_param))

        fw_func_w, f_func = _make_combo_field(ui_text("skill_field_function"), [], s.get('func_name', ''))
        f_func.setEditable(True)
        f_func.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        f_func.blockSignals(True)
        for name in sorted({v for v in FUNC_MAP_1B.values() if v}):
            f_func.addItem(name)
        f_func.setCurrentText(s.get('func_name', ''))
        f_func.blockSignals(False)
        grid.addWidget(fw_func_w, 2, 2, 1, 2)

        def update_func_param_visibility():
            is_speed_func = f_func.currentText().strip() in ANM_SPEED_FUNC_NAMES
            is_fwd_velocity_func = f_func.currentText().strip() in FWD_VELOCITY_FUNC_NAMES
            is_gion_func = f_func.currentText().strip() in GION_FUNC_NAMES
            is_atkhit_func = f_func.currentText().strip() in ATKHIT_FUNC_NAMES
            func_params = list(s.get('func_param_bytes', [0, 0, 0]))
            show_func_params = (
                f_func.currentText().strip() in FUNC_PARAM_FIELD_NAMES
                or any(int(v or 0) for v in func_params)
            )
            fw_speed.setVisible(is_speed_func)
            f_speed.setEnabled(is_speed_func)
            fw_fwd_vel.setVisible(is_fwd_velocity_func)
            f_fwd_vel.setEnabled(is_fwd_velocity_func)
            fw_fwd_dur.setVisible(is_fwd_velocity_func)
            f_fwd_dur.setEnabled(is_fwd_velocity_func)
            fw_gion_id.setVisible(is_gion_func)
            f_gion_id.setEnabled(is_gion_func)
            fw_gion_scale.setVisible(is_gion_func)
            f_gion_scale.setEnabled(is_gion_func)
            for fw_param, f_param in atkhit_fields:
                fw_param.setVisible(is_atkhit_func)
                f_param.setEnabled(is_atkhit_func)
            for fw_param, f_param in func_param_fields:
                fw_param.setVisible(show_func_params)
                f_param.setEnabled(show_func_params)

        update_func_param_visibility()

        cl.addLayout(grid)

        def commit():
            s['bone'] = f_bone.text()
            try:
                s['dtype'] = int(f_type.text())
            except Exception:
                pass
            fw_v = f_frame.text()
            if fw_v == ui_text("ui_skill_start"):
                s['frame_w'] = 0x270E; s['frame_str'] = ui_text("ui_skill_start")
            elif fw_v == ui_text("ui_skill_end"):
                s['frame_w'] = 0x270F; s['frame_str'] = ui_text("ui_skill_end")
            else:
                try:
                    fv = int(fw_v); s['frame_w'] = fv; s['frame_str'] = str(fv)
                except Exception:
                    pass
            s['attack'] = f_attack.currentText()
            try:
                s['dmg'] = max(0, min(255, int(f_dmg.text())))
            except Exception:
                pass
            try:
                s['grd'] = max(0, min(255, int(f_grd.text())))
            except Exception:
                pass
            try:
                s['x'] = float(f_x.text())
            except Exception:
                pass
            try:
                s['y'] = float(f_y.text())
            except Exception:
                pass
            try:
                s['push'] = int(f_push.text())
            except Exception:
                pass
            try:
                s['speed_multiplier'] = float(f_speed.text())
            except Exception:
                pass
            try:
                s['fwd_velocity'] = int(f_fwd_vel.text())
            except Exception:
                pass
            try:
                s['fwd_velocity_duration'] = int(f_fwd_dur.text())
            except Exception:
                pass
            s['gion_id'] = f_gion_id.text()
            try:
                s['gion_scale'] = float(f_gion_scale.text())
            except Exception:
                pass
            atkhit_params = list(s.get('atkhit_params', [0, 0, 0, 0, 0]))
            atkhit_params.extend([0] * (5 - len(atkhit_params)))
            for i, (_, f_param) in enumerate(atkhit_fields):
                try:
                    atkhit_params[i] = int(f_param.text())
                except Exception:
                    pass
            s['atkhit_params'] = atkhit_params[:5]
            func_param_bytes = list(s.get('func_param_bytes', [0, 0, 0]))
            func_param_bytes.extend([0] * (3 - len(func_param_bytes)))
            for i, (_, f_param) in enumerate(func_param_fields):
                try:
                    func_param_bytes[i] = max(0, min(255, int(f_param.text())))
                except Exception:
                    pass
            s['func_param_bytes'] = func_param_bytes[:3]
            func_txt = f_func.currentText().strip()
            _func_rev = {v: k for k, v in FUNC_MAP_1B.items()}
            if func_txt in _func_rev:
                s['dtype'] = (
                    _func_rev[func_txt]
                    | (s['func_param_bytes'][0] << 8)
                    | (s['func_param_bytes'][1] << 16)
                    | (s['func_param_bytes'][2] << 24)
                )
                s['func_name'] = func_txt
            else:
                s['func_name'] = FUNC_MAP_1B.get(s['dtype'], s.get('func_name', ''))
            if s.get('func_name') in ANM_SPEED_FUNC_NAMES and 'speed_multiplier' not in s:
                s['speed_multiplier'] = 1.0
                f_speed.setText("1")
            if s.get('func_name') in FWD_VELOCITY_FUNC_NAMES:
                if 'fwd_velocity' not in s:
                    s['fwd_velocity'] = 0
                    f_fwd_vel.setText("0")
                if 'fwd_velocity_duration' not in s:
                    s['fwd_velocity_duration'] = 0
                    f_fwd_dur.setText("0")
            if s.get('func_name') in GION_FUNC_NAMES:
                if 'gion_scale' not in s:
                    s['gion_scale'] = 1.0
                    f_gion_scale.setText("1")
                if 'gion_id' not in s:
                    s['gion_id'] = ''
                    f_gion_id.setText("")
            if s.get('func_name') in ATKHIT_FUNC_NAMES and 'atkhit_params' not in s:
                s['atkhit_params'] = [0, 0, 0, 0, 0]
                for _, f_param in atkhit_fields:
                    f_param.setText("0")
            s['dname'] = DATA_TYPE_MAP.get(s['dtype'], str(s['dtype']))
            f_type.setText(str(s['dtype']))
            hdr_lbl.setText(ui_text("ui_skill_value_value_value", p0=r, p1=s['bone'], p2=s.get('func_name', '')))
            update_func_param_visibility()
            if self._mot_raw is not None and s.get('sub_off') is not None and not self._structural_dirty:
                write_mot_subentry(self._mot_raw, s)
                sub_off = s.get('sub_off')
                if 0 <= sub_off and sub_off+MOT_SUB_SIZE <= len(self._mot_raw):
                    s['raw_bytes'] = bytes(self._mot_raw[sub_off:sub_off+MOT_SUB_SIZE])
            self.changed.emit()

        f_bone.editingFinished.connect(commit)
        f_type.editingFinished.connect(commit)
        f_frame.editingFinished.connect(commit)
        f_attack.currentTextChanged.connect(lambda _: commit())
        f_dmg.editingFinished.connect(commit)
        f_grd.editingFinished.connect(commit)
        f_x.editingFinished.connect(commit)
        f_y.editingFinished.connect(commit)
        f_push.editingFinished.connect(commit)
        f_speed.editingFinished.connect(commit)
        f_fwd_vel.editingFinished.connect(commit)
        f_fwd_dur.editingFinished.connect(commit)
        f_gion_id.editingFinished.connect(commit)
        f_gion_scale.editingFinished.connect(commit)
        for _, f_param in atkhit_fields:
            f_param.editingFinished.connect(commit)
        for _, f_param in func_param_fields:
            f_param.editingFinished.connect(commit)
        f_func.currentTextChanged.connect(lambda _: commit())

        return card

    def _on_ev_edited(self, text, entry):
        entry['event_id'] = text
        for btn, e in self._entry_btns:
            if e is entry:
                lbls = btn.findChildren(QLabel)
                if lbls:
                    lbls[0].setText(text)
                break
        if self._mot_raw is not None and entry.get('offset') is not None:
            write_mot_entry(self._mot_raw, entry)
        self.changed.emit()

    def _on_an_edited(self, text, entry):
        entry['anim_id'] = text
        if self._mot_raw is not None and entry.get('offset') is not None:
            write_mot_entry(self._mot_raw, entry)
        self.changed.emit()

    def _on_flag_edited(self, key, field, entry):
        try:
            entry[key] = int(field.text())
            if self._mot_raw is not None and entry.get('offset') is not None:
                write_mot_entry(self._mot_raw, entry)
            self.changed.emit()
        except Exception:
            pass


# Main Editor
class SkillEditor(QWidget):
    _load_done_signal  = pyqtSignal(str, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):  # noqa: ARG002
        super().__init__(parent)
        self.t = lang_func or (lambda k, **_: k)

        self._filepath  = None
        self._file_type = 'prm'
        self._raw       = None
        self._result    = None
        self._dirty     = False

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar — matches CharacterStats style
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        self._open_btn = QPushButton(ui_text("btn_open_file"))
        self._open_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._open_btn.setFont(QFont("Segoe UI", 10))
        self._open_btn.setStyleSheet(ss_btn(accent=True))
        self._open_btn.clicked.connect(self._load_file)
        tl.addWidget(self._open_btn)

        self._save_btn = QPushButton(ui_text("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)

        self._file_lbl = QLabel(ui_text("no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        # Content area
        self._tabs = QTabWidget(self)
        self._tabs.setFont(QFont("Segoe UI", 11))
        self._tabs.setStyleSheet(ss_tab_widget())
        self._tabs.setDocumentMode(True)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.tabBar().setExpanding(False)
        self._tabs.tabBar().setDrawBase(False)
        self._tabs.tabBar().setStyleSheet(ss_tab_bar())

        self._sklslot_tab = _SklslotTab()
        self._sklslot_tab.changed.connect(self._mark_dirty)

        self._load_tab = _LoadTab()
        self._load_tab.changed.connect(self._mark_dirty)

        self._mot_tab = _MotTab()
        self._mot_tab.changed.connect(self._mark_dirty)

        self._gha_tab = _MotTab()
        self._gha_tab.changed.connect(self._mark_dirty)

        self._prmload_tab = _PrmLoadStandaloneTab()
        self._prmload_tab.changed.connect(self._mark_dirty)

        root.addWidget(self._tabs, 1)
        self._show_empty_state()

    def _show_empty_state(self, text=None):
        self._tabs.clear()
        self._sklslot_tab.set_placeholder(
            text or ui_text("ui_skill_open_a_prm_bin_xfbin_file_to_begin_editing"),
            loaded=False,
        )
        self._tabs.addTab(self._sklslot_tab, ui_text("ui_skill_skill_slots"))
        self._tabs.setVisible(True)

    # File I/O

    @staticmethod
    def _detect_file_type(path):
        fname = os.path.basename(path).lower()
        if 'prm_load' in fname:
            return 'prm_load_standalone'
        return 'prm'

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_skill_open_prm_xfbin"), game_files_dialog_dir(target_patterns="*prm*.bin.xfbin"),
            "PRM XFBIN files (*prm*.bin.xfbin *.xfbin);;All files (*.*)"
        )
        if not path:
            return
        create_backup_on_open(path)
        self._filepath = path
        self._file_type = self._detect_file_type(path)
        name = os.path.basename(path)
        self._file_lbl.setText(ui_text("ui_effect_loading_value", p0=name))
        self._file_lbl.setStyleSheet(ss_file_label())
        self._show_empty_state(ui_text("ui_effect_loading"))

        file_type = self._file_type

        def _worker():
            try:
                if file_type == 'prm_load_standalone':
                    raw, result = parse_prmload_xfbin(path)
                else:
                    raw, result = parse_prm_xfbin(path)
                self._load_done_signal.emit(path, raw, result)
            except Exception as e:
                self._load_error_signal.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, path, raw, result):
        self._raw    = raw
        self._result = result
        self._dirty  = False
        set_file_label(self._file_lbl, path)

        self._tabs.clear()
        errors = []

        # Tab order: Motion Data → GHA Motion Data → Load Config → Skill Slots
        for mot_key, mot_label in [('mot', ui_text("ui_skill_motion_data")), ('gha', ui_text("ui_skill_gha_motion_data"))]:
            if mot_key in result:
                try:
                    n = len(result[mot_key]['entries'])
                    tab = self._mot_tab if mot_key == 'mot' else self._gha_tab
                    tab.load(result[mot_key]['entries'], result[mot_key]['raw'])
                    self._tabs.addTab(tab, f"{mot_label}  ({n})")
                except Exception as e:
                    errors.append(f"{mot_label}: {e}")

        if 'load' in result:
            try:
                self._load_tab.load(result['load']['entries'])
                self._tabs.addTab(self._load_tab, ui_text("ui_skill_load_config"))
            except Exception as e:
                errors.append(f"Load Config: {e}")

        if 'sklslot' in result:
            try:
                self._sklslot_tab.load(result['sklslot']['entries'])
                self._tabs.addTab(self._sklslot_tab, ui_text("ui_skill_skill_slots"))
            except Exception as e:
                errors.append(f"Skill Slots: {e}")

        if 'prmload_standalone' in result:
            try:
                self._prmload_tab.load(result['prmload_standalone']['entries'])
                n = len(result['prmload_standalone']['entries'])
                self._tabs.addTab(self._prmload_tab, f"Load Assets  ({n})")
            except Exception as e:
                errors.append(f"Load Assets: {e}")

        if errors:
            QMessageBox.warning(self, ui_text("ui_skill_parse_warnings"), "\n".join(errors))

        self._tabs.setVisible(True)
        self._save_btn.setEnabled(True)

    def _on_load_error(self, msg):
        self._filepath = None
        self._raw = None
        self._result = None
        self._dirty = False
        self._save_btn.setEnabled(False)
        set_file_label_empty(self._file_lbl, ui_text("no_file_loaded"))
        self._show_empty_state(ui_text("ui_effect_error_loading_file"))
        QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), msg)

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _save_file(self):
        if self._filepath is None:
            return
        self._do_save(self._filepath)

    def _do_save(self, path):
        try:
            if 'prmload_standalone' in self._result:
                self._result['prmload_standalone']['entries'] = self._prmload_tab.get_entries()
                save_prmload_xfbin(path, self._raw, self._result)
            else:
                if 'sklslot' in self._result:
                    self._result['sklslot']['entries'] = self._sklslot_tab.get_entries()
                if 'load' in self._result:
                    self._result['load']['entries'] = self._load_tab.get_entries()
                if 'mot' in self._result:
                    self._result['mot']['entries'] = self._mot_tab.get_entries()
                    self._result['mot']['raw'] = self._mot_tab.get_raw()
                if 'gha' in self._result:
                    self._result['gha']['entries'] = self._gha_tab.get_entries()
                    self._result['gha']['raw'] = self._gha_tab.get_raw()
                save_prm_xfbin(path, self._raw, self._result)

            self._dirty = False
            set_file_label(self._file_lbl, path)
        except Exception as e:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(e))
