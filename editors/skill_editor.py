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
    make_editor_card_frame,
    make_editor_field_shell,
    make_empty_state,
    ss_bg_dark,
    ss_dialog,
    ss_input_validation,
    ss_main_label,
    ss_sidebar_btn,
    ss_tab_bar,
    ss_tab_widget,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorListRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_file_label,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
    configure_table,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import install_file_actions
import copy
import os
import math
import struct

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QTabWidget, QComboBox, QInputDialog, QDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMenu, QTextEdit, QSplitter, QLayout,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

from core.themes import P
from core.editor_file_state import set_file_label, set_file_label_empty
from parsers.skill_parser import (
    parse_prm_xfbin, save_prm_xfbin,
    parse_prmload_xfbin, save_prmload_xfbin,
    write_mot_entry, write_mot_subentry,
    make_default_mot_entry, make_default_mot_subentry, write_mot,
    DATA_TYPE_MAP, FUNC_MAP_1B, FUNC_MAP_2B, PRMLOAD_TYPE_NAMES, ANM_SPEED_FUNC_NAMES,
    FWD_VELOCITY_FUNC_NAMES, GION_FUNC_NAMES, ATKHIT_FUNC_NAMES,
    MOT_HDR_SIZE, MOT_SUB_SIZE, function_name, function_opcode, motion_subentry_size,
    parse_motion_subentry,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from parsers.skill_tools import (validate_skills, related_resources, shift_frames,
                                export_move, import_move, frame_label)

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
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _make_field(label_text, value_text):
    """Returns (container_widget, QLineEdit)."""
    f, fl, _label, _hint = make_editor_field_shell(label_text)
    e = QLineEdit(str(value_text))
    e.setMinimumWidth(0)
    configure_input(e, monospace=True)
    e.setCursorPosition(0)
    fl.addWidget(e)
    return f, e


def _make_combo_field(label_text, items, current):
    """Returns (container_widget, QComboBox)."""
    f, fl, _label, _hint = make_editor_field_shell(label_text)
    cb = QComboBox()
    cb.addItems(items)
    cb.setMinimumWidth(0)
    cb.setMinimumContentsLength(1)
    cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    configure_input(cb, monospace=True)
    cb.blockSignals(True)
    cb.setCurrentText(str(current))
    cb.blockSignals(False)
    cb.lineEdit().setCursorPosition(0) if cb.isEditable() and cb.lineEdit() else None
    fl.addWidget(cb)
    return f, cb


def _section_label(text):
    lbl = QLabel(text)
    lbl.setFont(ui_font(TypeSize.SECTION, QFont.Weight.Bold))
    lbl.setStyleSheet(ss_main_label())
    lbl.setContentsMargins(20, 10, 0, 2)
    return lbl


def _card_frame():
    return make_editor_card_frame()


def _card_with_layout(parent=None, *, margins=Insets.CARD, spacing=Size.CARD_GAP):
    return make_editor_card(parent, margins=margins, spacing=spacing)


def _make_sidebar(width=260):
    sidebar = EditorSidebar(width=width)


    layout = sidebar.content_layout


    return sidebar, layout


def _sidebar_actions_row(*buttons):
    frame = EditorActionRow()

    layout = frame.content_layout


    for button in buttons:
        button.setMinimumWidth(0)
        layout.addWidget(button, 1)
    return frame


def _sidebar_search(placeholder):
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    configure_search(e)
    return e


def _sidebar_scroll():
    scroll = QScrollArea()


    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    configure_scrollarea(scroll, transparent=True)
    inner = QWidget()
    inner.setMinimumWidth(0)
    inner.setStyleSheet(ss_transparent())
    layout = QVBoxLayout(inner)
    configure_layout(layout, LayoutRole.LIST)
    layout.addStretch()
    scroll.setWidget(inner)
    return scroll, inner, layout


def _entry_btn(title, subtitle, selected, on_click):
    btn = EditorListRow()


    bl = btn.content_layout


    name_lbl = btn.add_title(title)


    if subtitle:
        sub_lbl = btn.add_subtitle(subtitle, value_font=ui_font(TypeSize.CODE))


    btn.clicked.connect(on_click)
    return btn


def _right_scroll():
    scroll = QScrollArea()


    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    configure_scrollarea(scroll)
    inner = QWidget()
    inner.setMinimumWidth(0)
    inner.setStyleSheet(ss_bg_dark())
    layout = QVBoxLayout(inner)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    configure_layout(layout, LayoutRole.PAGE)
    scroll.setWidget(inner)
    return scroll, layout


def _placeholder_label(text, *, loaded=True, icon_name="fa6s.list"):
    if loaded:
        return make_empty_state(
            title=ui_text("select_entry"),
            text="",
            icon_name=None,
        )
    title = ui_text("no_file_loaded")
    return make_empty_state(
        title=title,
        text=text,
        icon_name=icon_name or "fa6s.folder-open",
    )


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
        configure_layout(root, LayoutRole.ROOT)

        # Sidebar
        sidebar, sl = _make_sidebar(260)

        self._search = _sidebar_search(ui_text("ui_skill_search_slots"))
        self._search.textChanged.connect(self._filter_list)
        sl.addWidget(self._search)

        bf = ui_font(TypeSize.BODY)

        self._new_btn = QPushButton(ui_text("btn_new"))
        configure_button(self._new_btn, height=Size.COMPACT_CONTROL)
        self._new_btn.setEnabled(False)
        self._new_btn.setToolTip(ui_text("ui_skill_add_slot_tooltip"))
        self._new_btn.clicked.connect(self._add_slot)
        self._new_btn.setProperty("designAction", 'new')

        self._dup_btn = QPushButton(ui_text("btn_duplicate"))
        configure_button(self._dup_btn, height=Size.COMPACT_CONTROL)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setToolTip(ui_text("ui_skill_duplicate_slot_tooltip"))
        self._dup_btn.clicked.connect(self._dup_slot)
        self._dup_btn.setProperty("designAction", 'duplicate')

        self._del_btn = QPushButton(ui_text("btn_delete"))
        configure_button(self._del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_btn.setEnabled(False)
        self._del_btn.setToolTip(ui_text("ui_skill_delete_slot_tooltip"))
        self._del_btn.clicked.connect(self._del_slot)
        self._del_btn.setProperty("designAction", 'delete')
        sl.addWidget(_sidebar_actions_row(self._new_btn, self._dup_btn, self._del_btn))

        self._list_scroll, self._list_widget, self._list_layout = _sidebar_scroll()
        sl.addWidget(self._list_scroll)
        root.addWidget(sidebar)

        div = EditorSeparator(orientation=Qt.Orientation.Vertical)


        root.addWidget(div)

        self._editor_scroll, self._editor_layout = _right_scroll()
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(
            _placeholder_label(ui_text("ui_skill_select_a_slot")),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
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
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(
            _placeholder_label(text, loaded=loaded, icon_name="fa6s.person-running" if loaded else "fa6s.folder-open"),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        self._editor_layout.addStretch()

    def load(self, entries):
        self._entries = [dict(e) for e in entries]
        self._selected = -1
        self._rebuild_list()
        self._set_action_state(True, False)
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(
            _placeholder_label(ui_text("ui_skill_select_a_slot_2")),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
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

        card, card_main = _card_with_layout()
        add_editor_card_title(card_main, e.get('slot_name', ui_text("ui_skill_skill_slots")), "fa6s.person-running")
        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        grid = QGridLayout(inner)
        configure_layout(grid, LayoutRole.GRID)
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
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(
            _placeholder_label(ui_text("ui_skill_select_a_slot")),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
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
        configure_layout(root, LayoutRole.ROOT)
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
        card, cl = make_editor_card()

        hdr = QLabel(ui_text("ui_mainmodeparam_value_value", p0=i, p1=tname))
        hdr.setFont(ui_font(TypeSize.TITLE, QFont.Weight.Bold))
        hdr.setStyleSheet(ss_main_label())
        cl.addWidget(hdr)

        grid = QGridLayout()
        configure_layout(grid, LayoutRole.GRID)

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
        configure_layout(root, LayoutRole.ROOT)
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
        card, cl = make_editor_card()

        hdr = QLabel(ui_text("ui_mainmodeparam_value_value", p0=i, p1=tname))
        hdr.setFont(ui_font(TypeSize.TITLE, QFont.Weight.Bold))
        hdr.setStyleSheet(ss_main_label())
        cl.addWidget(hdr)

        grid = QGridLayout()
        configure_layout(grid, LayoutRole.GRID)

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
    selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._mot_raw = None
        self._cur_entry = None
        self._entry_btns = []  # list of (btn, entry)
        self._subentry_templates = {}
        self._structural_dirty = False
        self._entry_add_btn = None
        self._entry_dup_btn = None
        self._entry_del_btn = None
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        # Sidebar
        sidebar, sl = _make_sidebar(260)

        self._search = _sidebar_search(ui_text("ui_messageinfo_search_entries"))
        self._search.textChanged.connect(self._filter_entries)
        sl.addWidget(self._search)

        bf = ui_font(TypeSize.BODY)

        self._entry_add_btn = QPushButton(ui_text("btn_new"))
        configure_button(self._entry_add_btn, height=Size.COMPACT_CONTROL)
        self._entry_add_btn.setEnabled(False)
        self._entry_add_btn.setToolTip(ui_text("ui_skill_add_motion_entry_tooltip"))
        self._entry_add_btn.clicked.connect(self._add_entry)
        self._entry_add_btn.setProperty("designAction", 'new')

        self._entry_dup_btn = QPushButton(ui_text("btn_duplicate"))
        configure_button(self._entry_dup_btn, height=Size.COMPACT_CONTROL)
        self._entry_dup_btn.setEnabled(False)
        self._entry_dup_btn.setToolTip(ui_text("ui_skill_duplicate_motion_entry_tooltip"))
        self._entry_dup_btn.clicked.connect(self._dup_entry)
        self._entry_dup_btn.setProperty("designAction", 'duplicate')

        self._entry_del_btn = QPushButton(ui_text("btn_delete"))
        configure_button(self._entry_del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._entry_del_btn.setEnabled(False)
        self._entry_del_btn.setToolTip(ui_text("ui_skill_delete_motion_entry_tooltip"))
        self._entry_del_btn.clicked.connect(self._del_entry)
        self._entry_del_btn.setProperty("designAction", 'delete')
        sl.addWidget(_sidebar_actions_row(self._entry_add_btn, self._entry_dup_btn, self._entry_del_btn))

        self._list_scroll, self._list_widget, self._list_layout = _sidebar_scroll()
        sl.addWidget(self._list_scroll)
        root.addWidget(sidebar)

        div = EditorSeparator(orientation=Qt.Orientation.Vertical)


        root.addWidget(div)

        self._editor_scroll, self._editor_layout = _right_scroll()
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(
            _placeholder_label(ui_text("ui_skill_select_an_animation_entry"), icon_name="fa6s.film"),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        self._editor_layout.addStretch()
        root.addWidget(self._editor_scroll, 1)

    def _set_action_state(self):
        loaded = self._mot_raw is not None
        selected = self._cur_entry is not None
        self._entry_add_btn.setEnabled(loaded)
        self._entry_dup_btn.setEnabled(loaded and selected)
        self._entry_del_btn.setEnabled(loaded and selected and len(self._entries) > 1)

    def load(self, entries, mot_raw):
        self._command_flushers = []
        self._operand_suggestions = {}
        self._entries = entries
        self._mot_raw = mot_raw
        self._cur_entry = None
        self._rebuild_subentry_templates()
        self._structural_dirty = False
        self._populate_list(entries)
        self._set_action_state()

    def _rebuild_subentry_templates(self):
        self._subentry_templates = {}
        for entry in self._entries:
            for sub in entry.get('subentries', []):
                func_name = sub.get('func_name')
                raw_bytes = sub.get('raw_bytes', b'')
                if (
                    func_name
                    and func_name not in self._subentry_templates
                    and len(raw_bytes) >= MOT_SUB_SIZE
                ):
                    self._subentry_templates[func_name] = bytes(raw_bytes)

    def _apply_subentry_template(self, sub, func_name):
        raw_template = self._subentry_templates.get(func_name)
        sub['raw_bytes'] = (
            bytes(raw_template)
            if raw_template is not None
            else bytes(motion_subentry_size(function_opcode(func_name)))
        )
        sub['raw_func_name'] = func_name

    def _populate_list(self, entries):
        _clear_layout(self._list_layout)
        self._entry_btns = []
        for e in entries:
            n = e.get('n_subs', len(e.get('subentries', [])))
            subtitle = None
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
        if not self._flush_command_edits():
            return
        self._cur_entry = entry
        for btn, e in self._entry_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(e is entry)))
        self._set_action_state()
        self._show_entry(entry)
        self.selected.emit(entry)

    def get_entries(self):
        return self._entries

    def _flush_command_edits(self):
        return all([commit() for commit in getattr(self, '_command_flushers', [])])

    def get_raw(self):
        if not self._flush_command_edits():
            raise ValueError(ui_text('skill_invalid_fields'))
        if self._mot_raw is None:
            return None
        if self._structural_dirty:
            self._mot_raw = write_mot(self._entries, self._mot_raw)
            self._rebuild_subentry_templates()
            self._structural_dirty = False
        return self._mot_raw

    def _refresh_list(self):
        self._filter_entries(self._search.text())
        self._set_action_state()

    def _clear_editor_placeholder(self):
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(
            _placeholder_label(ui_text("ui_skill_select_an_animation_entry"), icon_name="fa6s.film"),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        self._editor_layout.addStretch()

    @staticmethod
    def _subentry_capacity(entry):
        raw_size = int(entry.get('raw_size') or 0)
        if raw_size < MOT_HDR_SIZE:
            return len(entry.get('subentries', []))
        return len(entry.get('subentries', []))

    def _unique_entry_id(self, candidate):
        existing = {e.get('event_id', '') for e in self._entries}
        candidate = (candidate or 'PL_ANM_NEW').strip() or 'PL_ANM_NEW'
        candidate = candidate[:32]
        if candidate not in existing:
            return candidate
        for n in range(1, 10000):
            suffix = f"_{n:03d}"
            stem = candidate[:32 - len(suffix)]
            value = f"{stem}{suffix}"
            if value not in existing:
                return value
        return candidate[:32]

    def _add_entry(self):
        if not self._flush_command_edits():
            return
        new_entry = make_default_mot_entry(len(self._entries))
        new_entry['event_id'] = self._unique_entry_id(new_entry.get('event_id'))
        self._entries.append(new_entry)
        self._cur_entry = new_entry
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(new_entry)
        self.changed.emit()

    def _dup_entry(self):
        if not self._flush_command_edits():
            return
        if self._cur_entry is None:
            return
        try:
            idx = self._entries.index(self._cur_entry)
        except ValueError:
            idx = len(self._entries) - 1
        new_entry = copy.deepcopy(self._cur_entry)
        template_offset = self._cur_entry.get('offset', self._cur_entry.get('template_offset'))
        new_entry['offset'] = None
        if template_offset is not None:
            new_entry['template_offset'] = template_offset
        new_entry['event_id'] = self._unique_entry_id(f"{new_entry.get('event_id', 'PL_ANM')}_copy")
        for sub in new_entry.get('subentries', []):
            sub['sub_off'] = None
        self._entries.insert(idx + 1, new_entry)
        self._cur_entry = new_entry
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(new_entry)
        self.changed.emit()

    def _del_entry(self):
        if not self._flush_command_edits():
            return
        if self._cur_entry is None:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(
                self,
                ui_text("dlg_title_warning"),
                ui_text("msg_cannot_delete_last_entry"),
            )
            return
        try:
            idx = self._entries.index(self._cur_entry)
        except ValueError:
            return
        self._entries.pop(idx)
        self._cur_entry = self._entries[min(idx, len(self._entries) - 1)] if self._entries else None
        self._structural_dirty = True
        self._refresh_list()
        if self._cur_entry is not None:
            self._show_entry(self._cur_entry)
        else:
            self._clear_editor_placeholder()
        self.changed.emit()

    def _show_entry(self, entry):
        if not self._flush_command_edits():
            return
        self._command_flushers = []
        _clear_layout(self._editor_layout)
        compact = self._editor_scroll.viewport().width() < 760

        # Header card
        card, cm = _card_with_layout()
        add_editor_card_title(cm, entry.get('event_id', ui_text("ui_skill_motion_data")), "fa6s.film", entry.get('anim_id', ''))
        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        grid = QGridLayout(inner)
        configure_layout(grid, LayoutRole.GRID)
        cm.addWidget(inner)

        fw_ev, f_ev = _make_field(ui_text("ui_guidecharparam_event_id"), entry['event_id'])
        grid.addWidget(fw_ev, 0, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        f_ev.textEdited.connect(lambda t, e=entry: self._on_ev_edited(t, e))

        fw_an, f_an = _make_field(ui_text("ui_playertitleparam_anim_id"), entry['anim_id'])
        grid.addWidget(fw_an, 1 if compact else 0, 0 if compact else 2, 1, 2)
        if not compact:
            grid.setColumnStretch(2, 1)
            grid.setColumnStretch(3, 1)
        f_an.textEdited.connect(lambda t, e=entry: self._on_an_edited(t, e))

        flag_defs = [
            ('enable_face_animation', ui_text("ui_skill_faceanim")),
            ('no_frame_skip',         ui_text("ui_skill_nofrmskip")),
            ('fix_position',          ui_text("ui_skill_fixpos")),
            ('frame_skip',            ui_text("ui_skill_frmskip")),

        ]
        flag_panel = QWidget()
        flag_panel.setStyleSheet(ss_transparent())
        flag_grid = QGridLayout(flag_panel)
        configure_layout(flag_grid, LayoutRole.GRID)
        cm.addWidget(flag_panel)
        flag_start_row = 0
        flag_cols = 2 if compact else len(flag_defs)
        for col, (key, label) in enumerate(flag_defs):
            fw, fe = _make_field(label, entry.get(key, 0))
            fe.setObjectName('skill_motion_' + key)
            flag_grid.addWidget(fw, flag_start_row + (col // flag_cols), col % flag_cols)
            flag_grid.setColumnStretch(col % flag_cols, 1)
            fe.editingFinished.connect(
                lambda k=key, f=fe, e=entry: self._on_flag_edited(k, f, e)
            )
            self._command_flushers.append(
                lambda k=key, f=fe, e=entry: self._on_flag_edited(k, f, e)
            )

        self._editor_layout.addWidget(card)

        action_row = QWidget()
        action_row.setStyleSheet(ss_transparent())
        action_layout = QVBoxLayout(action_row) if compact else QHBoxLayout(action_row)
        configure_layout(action_layout, LayoutRole.ACTIONS)
        bf = ui_font(TypeSize.BODY)

        add_sub_btn = QPushButton(ui_text("ui_skill_add_subentry"))
        configure_button(add_sub_btn, height=Size.COMPACT_CONTROL)
        add_sub_btn.clicked.connect(lambda _, e=entry: self._add_subentry(e))
        add_sub_btn.setProperty("designAction", 'new')
        action_layout.addWidget(add_sub_btn)

        tools_btn = QPushButton(ui_text('skill_move_tools'))
        configure_button(tools_btn)
        tools_btn.clicked.connect(lambda: self._move_tools(entry))
        action_layout.addWidget(tools_btn)

        dup_sub_btn = QPushButton(ui_text("ui_skill_duplicate_last_subentry"))
        configure_button(dup_sub_btn, height=Size.COMPACT_CONTROL)
        dup_sub_btn.setEnabled(bool(entry.get('subentries')))
        dup_sub_btn.clicked.connect(lambda _, e=entry: self._dup_last_subentry(e))
        dup_sub_btn.setProperty("designAction", 'duplicate')
        action_layout.addWidget(dup_sub_btn)

        del_sub_btn = QPushButton(ui_text("ui_skill_delete_last_subentry"))
        configure_button(del_sub_btn, danger=True, height=Size.COMPACT_CONTROL)
        del_sub_btn.setEnabled(bool(entry.get('subentries')))
        del_sub_btn.clicked.connect(lambda _, e=entry: self._del_last_subentry(e))
        del_sub_btn.setProperty("designAction", 'delete')
        action_layout.addWidget(del_sub_btn)

        if not compact:
            action_layout.addStretch()
        self._editor_layout.addWidget(action_row)

        self._sub_cards = []
        # Subentry cards
        subs = entry.get('subentries', [])
        if subs:
            for r, s in enumerate(subs):
                title = ui_text("ui_skill_subentries") if r == 0 else None
                sub_card = self._make_sub_card(entry, r, s, title)
                self._sub_cards.append(sub_card)
                self._editor_layout.addWidget(sub_card)

        self._editor_layout.addStretch()

    def _add_subentry(self, entry):
        if not self._flush_command_edits():
            return
        subs = entry.setdefault('subentries', [])
        self._insert_subentry(entry, len(subs))

    def _dup_last_subentry(self, entry):
        if not self._flush_command_edits():
            return
        subs = entry.setdefault('subentries', [])
        if not subs:
            return
        self._duplicate_subentry(entry, len(subs) - 1)

    def _del_last_subentry(self, entry):
        if not self._flush_command_edits():
            return
        subs = entry.setdefault('subentries', [])
        if not subs:
            return
        self._delete_subentry(entry, len(subs) - 1)

    def _make_inserted_subentry(self, entry, index):
        subs = entry.setdefault('subentries', [])
        new_sub = make_default_mot_subentry(index + 1)

        neighbors = []
        if index > 0:
            neighbors.append(subs[index - 1])
        if index < len(subs):
            neighbors.append(subs[index])
        neighbors.extend(sub for sub in subs if sub not in neighbors)

        direct = neighbors[0] if neighbors else None
        raw_template = next(
            (
                sub for sub in neighbors
                if not sub.get('dmg_label') and len(sub.get('raw_bytes', b'')) >= MOT_SUB_SIZE
            ),
            None,
        )

        default_template = self._subentry_templates.get(new_sub.get('func_name'))
        if default_template is not None:
            new_sub['raw_bytes'] = bytes(default_template)
            new_sub['raw_func_name'] = new_sub.get('func_name')
        # A new command keeps its zero template when this opcode has no sample.

        if direct is not None and not direct.get('dmg_label'):
            new_sub['bone'] = direct.get('bone', '')
            new_sub['frame_w'] = direct.get('frame_w', 0)
            new_sub['frame_str'] = direct.get('frame_str', '0')

        return new_sub

    def _insert_subentry(self, entry, index, template=None):
        if not self._flush_command_edits():
            return
        subs = entry.setdefault('subentries', [])
        index = max(0, min(index, len(subs)))
        new_sub = copy.deepcopy(template) if template is not None else self._make_inserted_subentry(entry, index)
        new_sub['sub_off'] = None
        subs.insert(index, new_sub)
        entry['n_subs'] = len(subs)
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(entry)
        self.changed.emit()

    def _duplicate_subentry(self, entry, index):
        if not self._flush_command_edits():
            return
        subs = entry.setdefault('subentries', [])
        if not (0 <= index < len(subs)):
            return
        self._insert_subentry(entry, index + 1, subs[index])

    def _delete_subentry(self, entry, index):
        if not self._flush_command_edits():
            return
        subs = entry.setdefault('subentries', [])
        if not (0 <= index < len(subs)):
            return
        subs.pop(index)
        entry['n_subs'] = len(subs)
        self._structural_dirty = True
        self._refresh_list()
        self._show_entry(entry)
        self.changed.emit()

    def _make_sub_card(self, entry, r, s, section_title=None):
        from editors.skill_command_card import make_command_card
        return make_command_card(self, entry, r, s)

    def _move_command(self, entry, index, delta):
        if not self._flush_command_edits():
            return
        subs = entry['subentries']
        target = index + delta
        if 0 <= target < len(subs):
            subs[index], subs[target] = subs[target], subs[index]
            self._structural_dirty = True
            self._show_entry(entry)
            self.changed.emit()

    def _edit_raw_command(self, entry, sub):
        """Expose opaque parameters without inventing meanings or losing bytes."""
        size = motion_subentry_size(sub['dtype'])
        raw = bytearray(sub.get('raw_bytes', b'')[:size].ljust(size, b'\0'))
        write_mot_subentry(raw, {**sub, 'sub_off': 0})
        dialog = QDialog(self)
        dialog.setStyleSheet(ss_dialog())
        dialog.setWindowTitle(ui_text('skill_raw_parameters') + ' — ' + sub['func_name'])
        dialog.resize(720, 580)
        layout = QVBoxLayout(dialog)
        hint = QLabel(ui_text('skill_raw_hint'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        first_parameter = 0x38
        table = QTableWidget(max(0, (size - first_parameter) // 4), 4)
        configure_table(table)
        table.setHorizontalHeaderLabels([ui_text('skill_parameter_name'), ui_text('skill_number_unsigned'),
                                        ui_text('skill_number_signed'), ui_text('skill_number_decimal')])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row in range(table.rowCount()):
            off = first_parameter + row * 4
            values = (ui_text('skill_parameter_number', number=row + 1), str(struct.unpack_from('<I', raw, off)[0]),
                      str(struct.unpack_from('<i', raw, off)[0]),
                      f'{struct.unpack_from("<f", raw, off)[0]:.9g}')
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
        layout.addWidget(table, 1)
        row = QHBoxLayout()
        mode = QComboBox()
        configure_input(mode)
        mode.addItems([ui_text('skill_number_unsigned'), ui_text('skill_number_signed'), ui_text('skill_number_decimal')])
        row.addWidget(mode)
        value = QLineEdit()
        configure_input(value)
        row.addWidget(value, 1)
        apply = QPushButton(ui_text('skill_apply_parameter'))
        configure_button(apply)
        row.addWidget(apply)
        layout.addLayout(row)
        error = QLabel()
        error.setWordWrap(True)
        layout.addWidget(error)

        def selected():
            index = table.currentRow()
            apply.setEnabled(index >= 0)
            if index >= 0:
                value.setText(table.item(index, mode.currentIndex() + 1).text())

        def commit_parameter():
            index = table.currentRow()
            if index < 0:
                return
            try:
                kind = mode.currentIndex()
                text = value.text().strip()
                encoded = struct.pack(('<I', '<i', '<f')[kind], float(text) if kind == 2 else int(text, 0))
                updated = bytearray(raw)
                offset = first_parameter + index * 4
                updated[offset:offset + 4] = encoded
                parsed = parse_motion_subentry(updated)
                issues = [i for i in validate_skills({'mot': {'entries': [{**entry, 'subentries': [parsed]}]}}) if i['severity'] == 'error']
                if issues:
                    raise ValueError(issues[0]['message'])
                parsed['sub_off'] = sub.get('sub_off')
                sub.update(parsed)
                self._structural_dirty = True
                self.changed.emit()
                dialog.accept()
                self._show_entry(entry)
            except (ValueError, OverflowError, struct.error) as exc:
                error.setText(str(exc))

        table.itemSelectionChanged.connect(selected)
        mode.currentIndexChanged.connect(selected)
        apply.clicked.connect(commit_parameter)
        table.selectRow(0)
        selected()
        dialog.exec()

    def _move_tools(self, entry):
        menu = QMenu(self)
        for key, action in (('skill_shift_frames', 'shift'), ('skill_export_move', 'export'),
                            ('skill_import_move', 'import')):
            menu.addAction(ui_text(key), lambda a=action: self._run_move_tool(entry, a))
        menu.exec(self.cursor().pos())

    def _run_move_tool(self, entry, action):
        if not self._flush_command_edits():
            return
        try:
            if action == 'shift':
                delta, ok = QInputDialog.getInt(self, ui_text('skill_shift_frames'), ui_text('skill_shift_hint'), 1, -9997, 9997)
                if not ok:
                    return
                shift_frames(entry, delta)
            elif action == 'export':
                path, _ = QFileDialog.getSaveFileName(self, ui_text('skill_export_move'), entry['event_id'] + '.move.json', 'Move JSON (*.json)')
                if path:
                    with open(path, 'w', encoding='utf-8') as stream:
                        stream.write(export_move(entry))
                return
            else:
                path, _ = QFileDialog.getOpenFileName(self, ui_text('skill_import_move'), '', 'Move JSON (*.json)')
                if not path:
                    return
                if os.path.getsize(path) > 8_000_000:
                    raise ValueError('Move JSON is too large')
                with open(path, encoding='utf-8') as stream:
                    imported = import_move(stream.read())
                imported['event_id'] = self._unique_entry_id(imported['event_id'])
                self._entries.append(imported)
                entry = imported
                self._cur_entry = entry
            self._structural_dirty = True
            self._refresh_list()
            self._show_entry(entry)
            self.changed.emit()
        except (ValueError, OSError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, ui_text('dlg_title_error'), str(exc))

    def _on_ev_edited(self, text, entry):
        entry['event_id'] = text
        for btn, e in self._entry_btns:
            if e is entry:
                lbls = btn.findChildren(QLabel)
                if lbls:
                    lbls[0].setText(text)
                break
        if self._mot_raw is not None and entry.get('offset') is not None and not self._structural_dirty:
            write_mot_entry(self._mot_raw, entry)
        self.changed.emit()

    def _on_an_edited(self, text, entry):
        entry['anim_id'] = text
        if self._mot_raw is not None and entry.get('offset') is not None and not self._structural_dirty:
            write_mot_entry(self._mot_raw, entry)
        self.changed.emit()

    def _on_flag_edited(self, key, field, entry):
        try:
            value = int(field.text())
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError()
            field.setProperty('skill_invalid', False)
            configure_input(field)
            if value != entry.get(key, 0):
                entry[key] = value
                self._structural_dirty = True
                self.changed.emit()
            return True
        except ValueError:
            field.setProperty('skill_invalid', True)
            field.setStyleSheet(ss_input_validation(True))
            return False


# Main Editor
class SkillEditor(QWidget):
    _load_done_signal  = pyqtSignal(str, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):  # noqa: ARG002
        if embedded and parent is None:
            raise ValueError('Embedded Char Skills requires its editor host')
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.t = lang_func or (lambda k, **_: k)

        self._filepath  = None
        self._file_type = 'prm'
        self._raw       = None
        self._result    = None
        self._dirty     = False

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)
        self._build_ui()
        install_file_actions(self, self._save_btn, existing_button=self._save_as_btn)
        install_editor_chrome(self)

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        # Top bar — matches CharacterStats style
        top = EditorToolbar()
        tl = top.content_layout

        self._open_btn = QPushButton(ui_text("btn_open_file"))
        configure_button(self._open_btn, accent=True)
        self._open_btn.clicked.connect(self._load_file)
        self._open_btn.setProperty("designAction", 'open')
        tl.addWidget(self._open_btn)

        self._save_btn = QPushButton(ui_text("btn_save_file"))
        self._save_btn.setEnabled(False)
        configure_button(self._save_btn, accent=True)
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)

        self._save_as_btn = QPushButton(ui_text("btn_save_as"))
        configure_button(self._save_as_btn)
        self._save_as_btn.setEnabled(False)
        self._save_as_btn.clicked.connect(self._save_as)
        tl.addWidget(self._save_as_btn)

        self._file_lbl = QLabel(ui_text("no_file_loaded"))

        configure_file_label(self._file_lbl)
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        # Content area
        self._tabs = QTabWidget(self)
        self._tabs.setFont(ui_font(TypeSize.CODE))
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
        configure_file_label(self._file_lbl)
        self._show_empty_state(ui_text("ui_effect_loading"))

        file_type = self._file_type
        QTimer.singleShot(0, lambda p=path, ft=file_type: self._load_selected_path(p, ft))

    def _load_selected_path(self, path, file_type):
        try:
            if file_type == 'prm_load_standalone':
                raw, result = parse_prmload_xfbin(path)
            else:
                raw, result = parse_prm_xfbin(path)
            self._on_load_done(path, raw, result)
        except Exception as e:
            self._on_load_error(str(e))

    def _on_load_done(self, path, raw, result):
        self._filepath = path
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
                    initial = next((e for e in tab.get_entries() if e.get('anim_id')), None)
                    if initial is not None:
                        tab._on_entry_click(initial)
                    self._tabs.addTab(tab, mot_label)
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
                self._tabs.addTab(self._prmload_tab, ui_text("ui_skill_load_assets"))
            except Exception as e:
                errors.append(f"Load Assets: {e}")

        if errors:
            QMessageBox.warning(self, ui_text("ui_skill_parse_warnings"), "\n".join(errors))

        self._tabs.setVisible(True)
        self._save_btn.setEnabled(True)
        self._save_as_btn.setEnabled(True)
        install_editor_chrome(self)

    def _on_load_error(self, msg):
        self._filepath = None
        self._raw = None
        self._result = None
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._save_as_btn.setEnabled(False)
        set_file_label_empty(self._file_lbl, ui_text("no_file_loaded"))
        self._show_empty_state(ui_text("ui_effect_error_loading_file"))
        QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), msg)

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _save_as(self):
        if not self._result:
            return
        path, _ = QFileDialog.getSaveFileName(self, ui_text('skill_save_as'), self._filepath, 'XFBIN (*.xfbin)')
        if path:
            self._do_save(path)

    def _save_file(self):
        if self._filepath is None:
            return
        self._do_save(self._filepath)

    def _do_save(self, path):
        try:
            for tab in (self._mot_tab, self._gha_tab):
                if not tab._flush_command_edits():
                    raise ValueError(ui_text('skill_invalid_fields'))
            invalid = [w for w in self.findChildren(QWidget) if w.property('skill_invalid')]
            if invalid:
                raise ValueError(ui_text('skill_invalid_fields'))
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

            self._filepath = path
            for key, tab in (('mot', self._mot_tab), ('gha', self._gha_tab)):
                if key in self._result:
                    tab._mot_raw = self._result[key]['raw']
                    tab._structural_dirty = False
            self._dirty = False
            set_file_label(self._file_lbl, path)
        except Exception as e:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(e))
