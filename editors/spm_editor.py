"""editors/spm_editor.py  –  SPM (Special Move Parameters) XFBIN editor."""

import copy
import os
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QSplitter, QTabWidget, QComboBox, QTreeWidget, QTreeWidgetItem,
    QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_input, ss_search, ss_sidebar_btn,
    ss_section_label, ss_field_label, ss_file_label, ss_scrollarea, ss_sep,
    ss_panel, ss_scrollarea_transparent,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.spm_parser import parse_spm_xfbin, save_spm_xfbin, get_moves
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


# Constants

BOOL_ATTRS = {
    ui_text("ui_spm_startsetdirc"), ui_text("ui_spm_ignoreendpostype"), ui_text("ui_spm_waitendland"), ui_text("ui_spm_usecanceleffect"),
    ui_text("ui_spm_disablemisshitcancel"), ui_text("ui_spm_asderived"), ui_text("ui_spm_disableairinv"), ui_text("ui_spm_checkflg"),
    ui_text("ui_spm_waitcancelflag"), ui_text("ui_spm_checkonly"), ui_text("ui_spm_checkgroupex1"), ui_text("ui_spm_groupex1on"), ui_text("ui_spm_checkbeforeanm"),
}

KEY_HINTS = {
    '1': '↙', '2': '↓', '3': '↘',
    '4': '←', '5': '●', '6': '→',
    '7': '↖', '8': '↑', '9': '↗',
}

# 3×3 numpad layout: top row = 7/8/9, middle = 4/5/6, bottom = 1/2/3
NUMPAD_LAYOUT = [
    ['7', '8', '9'],
    ['4', '5', '6'],
    ['1', '2', '3'],
]

DEC_DEFAULTS = {
    'hhaStart':       {'path': ui_text("ui_spm_hhastart_xml"),       'endCutInCnt': '30'},
    'hitDerived':     {'path': ui_text("ui_spm_hitderived_xml"),      'hitDrvID': '1_spm',
                       'hitType': '0', 'checkFlg': 'false', 'waitCancelFlag': 'false'},
    'startAnmSelect': {'path': ui_text("ui_spm_startanmselect_xml")},
    'gaugeCnsm':      {'path': ui_text("ui_spm_gaugecnsm_xml"),       'startConsumption': '25',
                       'keepConsumption': '0', 'checkOnly': 'false'},
    'styleMark':      {'path': ui_text("ui_spm_stylemark_xml")},
}

DEC_TYPES = list(DEC_DEFAULTS.keys())


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


def _card_frame():
    f = QFrame()
    f.setStyleSheet(ss_panel())
    return f


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


def _right_scroll():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(ss_scrollarea())
    inner = QWidget()
    inner.setStyleSheet(f"background-color: {P['bg_dark']};")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)
    scroll.setWidget(inner)
    return scroll, layout


def _placeholder_label(text):
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 15))
    lbl.setStyleSheet(f"color: {P['text_dim']};")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


def _sidebar_buttons_row():
    """Returns (frame, new_btn, dup_btn, del_btn) — matches CharStats sidebar style."""
    frame = QWidget()
    frame.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 2, 0, 4)
    layout.setSpacing(4)
    bf = QFont("Segoe UI", 10)

    new_btn = QPushButton(ui_text("btn_new"))
    new_btn.setFixedHeight(28)
    new_btn.setFont(bf)
    new_btn.setStyleSheet(ss_btn())
    layout.addWidget(new_btn, 1)

    dup_btn = QPushButton(ui_text("btn_duplicate"))
    dup_btn.setFixedHeight(28)
    dup_btn.setFont(bf)
    dup_btn.setStyleSheet(ss_btn())
    layout.addWidget(dup_btn, 1)

    del_btn = QPushButton(ui_text("btn_delete"))
    del_btn.setFixedHeight(28)
    del_btn.setFont(bf)
    del_btn.setStyleSheet(ss_btn(danger=True))
    layout.addWidget(del_btn, 1)

    return frame, new_btn, dup_btn, del_btn


def _make_sidebar(width=240):
    sidebar = QFrame()
    sidebar.setFixedWidth(width)
    sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
    sl = QVBoxLayout(sidebar)
    sl.setContentsMargins(8, 8, 8, 4)
    sl.setSpacing(4)
    return sidebar, sl


# _AttrForm

class _AttrForm(QScrollArea):
    """Scrollable attribute form for any ET.Element."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._elem = None
        inner = QWidget()
        inner.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._grid = QGridLayout(inner)
        self._grid.setContentsMargins(16, 12, 16, 12)
        self._grid.setSpacing(6)
        self._grid.setColumnStretch(1, 1)
        self.setWidget(inner)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(ss_scrollarea())

    def set_element(self, elem):
        self._elem = None
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        if elem is None:
            lbl = QLabel(ui_text("ui_spm_nothing_selected"))
            lbl.setStyleSheet(f"color: {P['text_dim']}; padding: 12px;")
            lbl.setFont(QFont("Segoe UI", 12))
            self._grid.addWidget(lbl, 0, 0, 1, 2)
            return

        for row, (attr, val) in enumerate(elem.attrib.items()):
            lbl = QLabel(attr + ':')
            lbl.setFont(QFont("Segoe UI", 11))
            lbl.setStyleSheet(ss_field_label())
            lbl.setFixedWidth(180)
            self._grid.addWidget(lbl, row, 0, Qt.AlignmentFlag.AlignTop)

            if attr in BOOL_ATTRS:
                w = QComboBox()
                w.addItems(['true', 'false'])
                w.setCurrentText(val)
                w.setFont(QFont("Consolas", 11))
                w.setFixedHeight(28)
                w.setStyleSheet(ss_input())
                w.currentTextChanged.connect(lambda v, a=attr: self._set(a, v))
            else:
                w = QLineEdit(val)
                w.setFont(QFont("Consolas", 11))
                w.setFixedHeight(28)
                w.setStyleSheet(ss_input())
                w.textChanged.connect(lambda v, a=attr: self._set(a, v))

            self._grid.addWidget(w, row, 1)

        self._grid.setRowStretch(len(elem.attrib), 1)
        self._elem = elem

    def _set(self, attr, val):
        if self._elem is not None:
            self._elem.set(attr, val)
            self.changed.emit()


# _CommandsTab

class _CommandsTab(QWidget):
    entry_created = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry_elem   = None
        self._root_elem    = None
        self._actID        = ''
        self._actKind      = ''
        self._selected_cmd = None
        self._cmd_btns     = []
        self._cur_cmd_elem = None  # command whose detail is currently shown
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()

        # Page 0: no EntrySPM
        no_entry = QWidget()
        no_entry.setStyleSheet(f"background-color: {P['bg_dark']};")
        nl = QVBoxLayout(no_entry)
        nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.setSpacing(14)

        msg = QLabel(ui_text("ui_spm_this_move_has_no_input_commands_non_inputtable_d"))
        msg.setFont(QFont("Segoe UI", 13))
        msg.setStyleSheet(f"color: {P['text_dim']};")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.addWidget(msg)

        create_btn = QPushButton(ui_text("ui_spm_create_entryspm"))
        create_btn.setFixedHeight(TOOLBAR_BTN_H)
        create_btn.setFont(QFont("Segoe UI", 10))
        create_btn.setStyleSheet(ss_btn(accent=True))
        create_btn.clicked.connect(self._create_entry)
        nl.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(no_entry)

        # Page 1: command editor
        entry_w = QWidget()
        entry_w.setStyleSheet(f"background-color: {P['bg_dark']};")
        ev = QHBoxLayout(entry_w)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(0)

        # Left sidebar: search + buttons + list
        sidebar, sl = _make_sidebar(240)

        self._cmd_search = QLineEdit()
        self._cmd_search.setPlaceholderText(ui_text("ui_spm_search_commands"))
        self._cmd_search.setFixedHeight(32)
        self._cmd_search.setFont(QFont("Segoe UI", 13))
        self._cmd_search.setStyleSheet(ss_search())
        self._cmd_search.textChanged.connect(self._filter_cmds)
        sl.addWidget(self._cmd_search)

        btn_frame, self._add_cmd_btn, self._dup_cmd_btn, self._del_cmd_btn = _sidebar_buttons_row()
        self._add_cmd_btn.clicked.connect(self._add_command)
        self._dup_cmd_btn.clicked.connect(self._dup_command)
        self._del_cmd_btn.clicked.connect(self._del_command)
        sl.addWidget(btn_frame)

        self._cmd_scroll, self._cmd_list_widget, self._cmd_list_layout = _sidebar_scroll()
        sl.addWidget(self._cmd_scroll)
        ev.addWidget(sidebar)

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        ev.addWidget(div)

        # Right: scrollable detail area
        self._right_scroll, self._right_layout = _right_scroll()
        self._right_layout.addWidget(_placeholder_label(ui_text("ui_spm_select_a_command")))
        self._right_layout.addStretch()
        ev.addWidget(self._right_scroll, 1)

        self._stack.addWidget(entry_w)
        root.addWidget(self._stack, 1)

    # public

    def load(self, entry_elem, root_elem, actID, actKind):
        self._entry_elem   = entry_elem
        self._root_elem    = root_elem
        self._actID        = actID
        self._actKind      = actKind
        self._selected_cmd = None
        self._cur_cmd_elem = None
        if entry_elem is None:
            self._stack.setCurrentIndex(0)
        else:
            self._stack.setCurrentIndex(1)
            self._refresh_cmd_list()
            _clear_layout(self._right_layout)
            self._right_layout.addWidget(_placeholder_label(ui_text("ui_spm_select_a_command")))
            self._right_layout.addStretch()

    # command list

    def _refresh_cmd_list(self):
        _clear_layout(self._cmd_list_layout)
        self._cmd_btns = []
        if self._entry_elem is None:
            self._cmd_list_layout.addStretch()
            return
        for i, cmd in enumerate(self._entry_elem.findall(ui_text("skill_section_command"))):
            selected = cmd is self._selected_cmd
            btn = self._make_cmd_btn(i, cmd, selected)
            self._cmd_list_layout.insertWidget(self._cmd_list_layout.count(), btn)
            self._cmd_btns.append((btn, cmd))
        self._cmd_list_layout.addStretch()

    def _make_cmd_btn(self, idx, cmd_elem, selected):
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=selected))
        bl = QVBoxLayout(btn)
        bl.setContentsMargins(10, 3, 10, 3)
        bl.setSpacing(0)
        name_lbl = QLabel(ui_text("ui_spm_command_value", p0=idx + 1))
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(name_lbl)
        sub_lbl = QLabel(ui_text("ui_spm_trigger_value", p0=cmd_elem.get('trigger', '?')))
        sub_lbl.setFont(QFont("Segoe UI", 11))
        sub_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(sub_lbl)
        btn.clicked.connect(lambda _, c=cmd_elem: self._select_cmd(c))
        return btn

    def _filter_cmds(self):
        q = self._cmd_search.text().lower()
        for btn, cmd in self._cmd_btns:
            btn.setVisible(
                q == '' or q in cmd.get('trigger', '').lower()
                or q in cmd.get('condition', '').lower()
            )

    def _select_cmd(self, cmd_elem):
        self._selected_cmd = cmd_elem
        for btn, cmd in self._cmd_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(cmd is cmd_elem)))
        self._build_cmd_editor(cmd_elem)

    # command detail card

    def _build_cmd_editor(self, cmd_elem):
        self._cur_cmd_elem = cmd_elem
        _clear_layout(self._right_layout)

        # Fields card
        card = _card_frame()
        inner = QWidget(card)
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        card_main = QVBoxLayout(card)
        card_main.setContentsMargins(0, 0, 0, 0)
        card_main.addWidget(inner)

        fields_def = [
            ('trigger',       ui_text("ui_spm_trigger")),
            (ui_text("ui_spm_enabletime"),    ui_text("ui_spm_enable_time")),
            ('condition',     ui_text("ui_mainmodeparam_condition")),
            (ui_text("ui_spm_asderived"),     ui_text("ui_spm_as_derived")),
            (ui_text("ui_spm_disableairinv"), ui_text("ui_spm_disable_air_inv")),
        ]
        for ci, (key, label) in enumerate(fields_def):
            row, col = divmod(ci, 3)
            fw, fe = _make_field(label, cmd_elem.get(key, ''))
            grid.addWidget(fw, row, col)
            grid.setColumnStretch(col, 1)
            fe.editingFinished.connect(
                lambda k=key, f=fe: cmd_elem.set(k, f.text()))

        self._right_layout.addWidget(card)
        self._build_comel_card(cmd_elem)
        self._right_layout.addStretch()

    def _build_comel_card(self, cmd_elem):
        card = _card_frame()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(8)

        sec_lbl = QLabel(ui_text("ui_spm_input_sequence"))
        sec_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        sec_lbl.setStyleSheet(ss_section_label())
        cl.addWidget(sec_lbl)

        els = list(cmd_elem.findall(ui_text("ui_spm_comelement")))
        if els:
            for el in els:
                cl.addWidget(self._make_comel_row(el, cmd_elem))
        else:
            hint = QLabel(ui_text("ui_spm_no_inputs_yet_add_directions_below"))
            hint.setFont(QFont("Segoe UI", 11))
            hint.setStyleSheet(ss_field_label())
            cl.addWidget(hint)

        # Direction picker label
        pick_lbl = QLabel(ui_text("ui_spm_add_direction"))
        pick_lbl.setFont(QFont("Segoe UI", 11))
        pick_lbl.setStyleSheet(ss_field_label())
        cl.addWidget(pick_lbl)

        # 3×3 numpad picker
        picker = QWidget()
        picker.setStyleSheet("background: transparent;")
        pg = QGridLayout(picker)
        pg.setContentsMargins(0, 0, 0, 0)
        pg.setSpacing(3)
        for r, row_keys in enumerate(NUMPAD_LAYOUT):
            for c, key in enumerate(row_keys):
                btn = QPushButton(KEY_HINTS[key])
                btn.setFixedSize(40, 40)
                btn.setFont(QFont("Segoe UI", 16))
                btn.setStyleSheet(ss_btn())
                btn.clicked.connect(
                    lambda checked=False, k=key, ce=cmd_elem: self._add_direction(k, ce))
                pg.addWidget(btn, r, c)
        cl.addWidget(picker)

        self._right_layout.addWidget(card)

    def _make_comel_row(self, el, cmd_elem):
        row_w = QWidget()
        row_w.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        arrow = KEY_HINTS.get(el.get('key', '?'), el.get('key', '?'))
        dir_lbl = QLabel(arrow)
        dir_lbl.setFixedSize(34, 34)
        dir_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dir_lbl.setFont(QFont("Segoe UI", 18))
        dir_lbl.setStyleSheet(
            f"color: {P['accent']}; background-color: {P['mid']}; "
            f"border-radius: 6px;"
        )
        rl.addWidget(dir_lbl)

        time_lbl = QLabel(ui_text("ui_spm_time"))
        time_lbl.setFont(QFont("Segoe UI", 10))
        time_lbl.setStyleSheet(ss_field_label())
        rl.addWidget(time_lbl)

        time_edit = QLineEdit(el.get('time', '0'))
        time_edit.setFixedWidth(60)
        time_edit.setFixedHeight(30)
        time_edit.setFont(QFont("Consolas", 12))
        time_edit.setStyleSheet(ss_input())
        time_edit.editingFinished.connect(
            lambda fe=time_edit, e=el: e.set('time', fe.text()))
        rl.addWidget(time_edit)
        rl.addStretch()

        del_btn = QPushButton(ui_text("btn_delete"))
        del_btn.setFixedHeight(30)
        del_btn.setFont(QFont("Segoe UI", 10))
        del_btn.setStyleSheet(ss_btn(danger=True))
        del_btn.clicked.connect(
            lambda _, e=el, ce=cmd_elem: self._del_direction(e, ce))
        rl.addWidget(del_btn)
        return row_w

    def _add_direction(self, key, cmd_elem):
        el = ET.SubElement(cmd_elem, ui_text("ui_spm_comelement"))
        el.set('key', key)
        el.set('time', '0')
        self._build_cmd_editor(cmd_elem)

    def _del_direction(self, el, cmd_elem):
        try:
            cmd_elem.remove(el)
        except ValueError:
            pass
        self._build_cmd_editor(cmd_elem)

    # command CRUD

    def _create_entry(self):
        if self._root_elem is None:
            return
        e = ET.SubElement(self._root_elem, ui_text("ui_spm_entryspm"))
        e.set(ui_text("ui_spm_actid"), self._actID)
        e.set(ui_text("ui_spm_actkind"), self._actKind)
        self._entry_elem = e
        self.entry_created.emit(e)
        self._stack.setCurrentIndex(1)
        self._refresh_cmd_list()
        _clear_layout(self._right_layout)
        self._right_layout.addWidget(_placeholder_label(ui_text("ui_spm_select_a_command")))
        self._right_layout.addStretch()

    def _add_command(self):
        if self._entry_elem is None:
            return
        cmd = ET.SubElement(self._entry_elem, ui_text("skill_section_command"))
        for k, v in [('trigger', '262144'), (ui_text("ui_spm_enabletime"), '8'),
                     ('condition', '0'), (ui_text("ui_spm_asderived"), 'false'),
                     (ui_text("ui_spm_disableairinv"), 'false')]:
            cmd.set(k, v)
        self._refresh_cmd_list()

    def _dup_command(self):
        if self._selected_cmd is None or self._entry_elem is None:
            return
        new_cmd = copy.deepcopy(self._selected_cmd)
        self._entry_elem.append(new_cmd)
        self._refresh_cmd_list()

    def _del_command(self):
        if self._selected_cmd is None or self._entry_elem is None:
            return
        try:
            self._entry_elem.remove(self._selected_cmd)
        except ValueError:
            pass
        self._selected_cmd = None
        self._cur_cmd_elem = None
        self._refresh_cmd_list()
        _clear_layout(self._right_layout)
        self._right_layout.addWidget(_placeholder_label(ui_text("ui_spm_select_a_command")))
        self._right_layout.addStretch()


# _DecoratorsTab

class _DecoratorsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._elems     = []
        self._root_elem = None
        self._actID     = ''
        self._actKind   = ''
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left sidebar
        sidebar, sl = _make_sidebar(260)

        # Decorator type selector
        type_frame = QWidget()
        type_frame.setStyleSheet("background: transparent;")
        tf = QVBoxLayout(type_frame)
        tf.setContentsMargins(0, 0, 0, 4)
        tf.setSpacing(2)
        type_lbl = QLabel(ui_text("ui_spm_decorator_type"))
        type_lbl.setFont(QFont("Segoe UI", 10))
        type_lbl.setStyleSheet(ss_field_label())
        tf.addWidget(type_lbl)
        self._type_combo = QComboBox()
        self._type_combo.addItems(DEC_TYPES)
        self._type_combo.setEditable(True)
        self._type_combo.setFixedHeight(30)
        self._type_combo.setFont(QFont("Consolas", 11))
        self._type_combo.setStyleSheet(ss_input())
        tf.addWidget(self._type_combo)
        sl.addWidget(type_frame)

        btn_frame, self._add_dec_btn, self._dup_dec_btn, self._del_dec_btn = _sidebar_buttons_row()
        self._add_dec_btn.clicked.connect(self._add_decorator)
        self._dup_dec_btn.clicked.connect(self._dup_decorator)
        self._del_dec_btn.clicked.connect(self._del_decorator)
        sl.addWidget(btn_frame)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background-color: transparent; color: {P['text_main']}; "
            f"border: none; outline: none; }}"
            f"QTreeWidget::item {{ padding: 3px 8px; border-radius: 4px; }}"
            f"QTreeWidget::item:selected {{ background-color: {P['bg_card']}; }}"
            f"QTreeWidget::branch {{ background: transparent; }}"
        )
        self._tree.setFont(QFont("Segoe UI", 11))
        self._tree.itemSelectionChanged.connect(self._on_tree_sel)
        sl.addWidget(self._tree, 1)

        # Child item buttons below tree
        child_frame = QWidget()
        child_frame.setStyleSheet("background: transparent;")
        cf = QHBoxLayout(child_frame)
        cf.setContentsMargins(0, 4, 0, 0)
        cf.setSpacing(4)
        bf = QFont("Segoe UI", 10)

        self._add_child_btn = QPushButton(ui_text("ui_spm_add_child"))
        self._add_child_btn.setFixedHeight(28)
        self._add_child_btn.setFont(bf)
        self._add_child_btn.setStyleSheet(ss_btn())
        self._add_child_btn.clicked.connect(self._add_child_item)
        cf.addWidget(self._add_child_btn, 1)

        self._del_child_btn = QPushButton(ui_text("ui_spm_delete_child"))
        self._del_child_btn.setFixedHeight(28)
        self._del_child_btn.setFont(bf)
        self._del_child_btn.setStyleSheet(ss_btn(danger=True))
        self._del_child_btn.clicked.connect(self._del_child_item)
        cf.addWidget(self._del_child_btn, 1)
        sl.addWidget(child_frame)

        root.addWidget(sidebar)

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        root.addWidget(div)

        # Right: attribute form (no header label)
        self._attr_form = _AttrForm()
        root.addWidget(self._attr_form, 1)

    # public

    def load(self, decorator_elems, root_elem, actID, actKind):
        self._elems     = list(decorator_elems)
        self._root_elem = root_elem
        self._actID     = actID
        self._actKind   = actKind
        self._refresh_tree()
        self._attr_form.set_element(None)

    # internal

    def _refresh_tree(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        for dec in self._elems:
            label = dec.get('type', '?')
            top   = QTreeWidgetItem(self._tree, [label])
            top.setData(0, Qt.ItemDataRole.UserRole, dec)
            for child in dec:
                preview = child.tag + ': ' + ', '.join(
                    f"{k}={v}" for k, v in list(child.attrib.items())[:3])
                ch_item = QTreeWidgetItem(top, [preview])
                ch_item.setData(0, Qt.ItemDataRole.UserRole, child)
                ch_item.setFont(0, QFont("Consolas", 10))
        self._tree.expandAll()
        self._tree.blockSignals(False)

    def _on_tree_sel(self):
        items = self._tree.selectedItems()
        if not items:
            self._attr_form.set_element(None)
            return
        self._attr_form.set_element(items[0].data(0, Qt.ItemDataRole.UserRole))

    def _sel_top_dec(self):
        items = self._tree.selectedItems()
        if not items:
            return None
        item = items[0]
        if item.parent() is not None:
            item = item.parent()
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _add_decorator(self):
        if self._root_elem is None:
            return
        dtype = self._type_combo.currentText().strip()
        if not dtype:
            return
        dec = ET.SubElement(self._root_elem, ui_text("ui_spm_decorator"))
        dec.set('type', dtype)
        for k, v in DEC_DEFAULTS.get(dtype, {'path': f'{dtype}.xml'}).items():
            dec.set(k, v)
        dec.set(ui_text("ui_spm_actid"),   self._actID)
        dec.set(ui_text("ui_spm_actkind"), self._actKind)
        self._elems.append(dec)
        self._refresh_tree()

    def _dup_decorator(self):
        dec = self._sel_top_dec()
        if dec is None or self._root_elem is None:
            return
        new_dec = copy.deepcopy(dec)
        self._root_elem.append(new_dec)
        self._elems.append(new_dec)
        self._refresh_tree()

    def _del_decorator(self):
        dec = self._sel_top_dec()
        if dec is None or self._root_elem is None:
            return
        try:
            self._root_elem.remove(dec)
            self._elems.remove(dec)
        except ValueError:
            pass
        self._refresh_tree()
        self._attr_form.set_element(None)

    def _add_child_item(self):
        dec = self._sel_top_dec()
        if dec is None:
            return
        child = ET.SubElement(dec, ui_text("ui_spm_selectanmlist"))
        for k, v in [(ui_text("ui_spm_startanmid"), '0'), (ui_text("ui_spm_checkgroupex1"), 'false'),
                     (ui_text("ui_spm_groupex1on"), 'false'), (ui_text("ui_spm_checkbeforeanm"), 'false'),
                     (ui_text("ui_spm_beforeanmid"), '0'), (ui_text("ui_spm_attackflag"), '1'), (ui_text("ui_spm_highflag"), '3')]:
            child.set(k, v)
        self._refresh_tree()

    def _del_child_item(self):
        items = self._tree.selectedItems()
        if not items:
            return
        item = items[0]
        if item.parent() is None:
            return
        parent_dec = item.parent().data(0, Qt.ItemDataRole.UserRole)
        child_elem = item.data(0, Qt.ItemDataRole.UserRole)
        if parent_dec is not None and child_elem is not None:
            try:
                parent_dec.remove(child_elem)
            except ValueError:
                pass
        self._refresh_tree()
        self._attr_form.set_element(None)


# SpmEditor

class SpmEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=True):
        super().__init__(parent)
        self._t        = t or (lambda k, **kw: k)
        self._raw      = None
        self._result   = None
        self._filepath = None
        self._moves    = []
        self._cur_idx  = -1
        self._move_btns = []
        self._build_ui()

    def _build_ui(self):
        root_l = QVBoxLayout(self)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)

        root_l.addWidget(self._make_toolbar())

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root_l.addWidget(sep)

        sp = QSplitter(Qt.Orientation.Horizontal)
        sp.setStyleSheet(f"QSplitter::handle {{ background: {P['mid']}; width: 2px; }}")
        sp.addWidget(self._make_left_panel())
        sp.addWidget(self._make_right_panel())
        sp.setSizes([230, 1000])
        root_l.addWidget(sp, 1)

    def _make_toolbar(self):
        bar = QFrame()
        bar.setFixedHeight(TOOLBAR_H)
        bar.setStyleSheet(f"background-color: {P['bg_panel']};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(4)

        self._open_btn = QPushButton(ui_text("btn_open_file"))
        self._open_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._open_btn.setFont(QFont("Segoe UI", 10))
        self._open_btn.setStyleSheet(ss_btn(accent=True))
        self._open_btn.clicked.connect(self._open_file)
        bl.addWidget(self._open_btn)

        self._save_btn = QPushButton(ui_text("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        bl.addWidget(self._save_btn)

        self._path_lbl = QLabel(ui_text("xfa_no_file"))
        self._path_lbl.setFont(QFont("Consolas", 12))
        self._path_lbl.setStyleSheet(ss_file_label())
        bl.addWidget(self._path_lbl)
        bl.addStretch()
        return bar

    def _make_left_panel(self):
        sidebar, sl = _make_sidebar(230)

        self._move_search = QLineEdit()
        self._move_search.setPlaceholderText(ui_text("ui_spm_search_moves"))
        self._move_search.setFixedHeight(32)
        self._move_search.setFont(QFont("Segoe UI", 13))
        self._move_search.setStyleSheet(ss_search())
        self._move_search.textChanged.connect(self._filter_moves)
        sl.addWidget(self._move_search)

        btn_frame, self._add_move_btn, self._dup_move_btn, self._del_move_btn = _sidebar_buttons_row()
        self._add_move_btn.clicked.connect(self._add_move)
        self._dup_move_btn.clicked.connect(self._dup_move)
        self._del_move_btn.clicked.connect(self._del_move)
        self._add_move_btn.setEnabled(False)
        self._dup_move_btn.setEnabled(False)
        self._del_move_btn.setEnabled(False)
        sl.addWidget(btn_frame)

        self._move_scroll, self._move_list_widget, self._move_list_layout = _sidebar_scroll()
        sl.addWidget(self._move_scroll)
        return sidebar

    def _make_right_panel(self):
        ph = QWidget()
        ph.setStyleSheet(f"background-color: {P['bg_dark']};")
        pl = QVBoxLayout(ph)
        pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lbl = QLabel(ui_text("ui_spm_open_a_spm_xfbin_file_to_begin_editing"))
        ph_lbl.setFont(QFont("Segoe UI", 16))
        ph_lbl.setStyleSheet(f"color: {P['text_dim']};")
        ph_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(ph_lbl)

        self._tabs = QTabWidget()
        self._tabs.setFont(QFont("Segoe UI", 12))
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: none; background-color: {P['bg_dark']}; }}"
            f"QTabBar::tab {{ background-color: {P['bg_panel']}; color: {P['text_sec']}; "
            f"padding: 8px 20px; border: none; border-bottom: 2px solid transparent; }}"
            f"QTabBar::tab:selected {{ color: {P['accent']}; "
            f"border-bottom: 2px solid {P['accent']}; }}"
            f"QTabBar::tab:hover {{ color: {P['text_main']}; }}"
        )

        self._info_form = _AttrForm()
        self._info_form.changed.connect(self._mark_dirty)
        self._tabs.addTab(self._info_form, ui_text("ui_spm_move_info"))

        self._cmd_tab = _CommandsTab()
        self._cmd_tab.entry_created.connect(self._on_entry_created)
        self._tabs.addTab(self._cmd_tab, ui_text("ui_spm_commands"))

        self._dec_tab = _DecoratorsTab()
        self._tabs.addTab(self._dec_tab, ui_text("ui_spm_decorators"))

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(ph)
        self._right_stack.addWidget(self._tabs)
        return self._right_stack

    # File I/O

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_spm_open_spm_xfbin"), game_files_dialog_dir(target_patterns="*_SPM.xfbin"),
            "SPM XFBIN Files (*_SPM.xfbin);;XFBIN Files (*.xfbin);;All Files (*)")
        if not path:
            return
        create_backup_on_open(path)
        try:
            raw, result = parse_spm_xfbin(path)
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=e))
            return

        self._raw      = raw
        self._result   = result
        self._filepath = path
        self._moves    = get_moves(result['root'])

        set_file_label(self._path_lbl, path)
        self._save_btn.setEnabled(True)
        self._add_move_btn.setEnabled(True)
        self._dup_move_btn.setEnabled(True)
        self._del_move_btn.setEnabled(True)
        self._right_stack.setCurrentIndex(1)
        self._refresh_move_list()

    def _save_file(self):
        if not self._filepath or self._result is None:
            return
        try:
            save_spm_xfbin(self._filepath, self._raw, self._result)
            set_file_label(self._path_lbl, self._filepath)
        except Exception as e:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_spm_save_failed_value", p0=e))

    def _mark_dirty(self):
        self._save_btn.setEnabled(True)
        if self._filepath:
            set_file_label(self._path_lbl, self._filepath, dirty=True)

    # Move list

    def _refresh_move_list(self, keep_idx=None):
        _clear_layout(self._move_list_layout)
        self._move_btns = []
        for m in self._moves:
            btn = self._make_move_btn(m)
            self._move_list_layout.insertWidget(self._move_list_layout.count(), btn)
            self._move_btns.append((btn, m))
        self._move_list_layout.addStretch()

        target = keep_idx if (keep_idx is not None and 0 <= keep_idx < len(self._moves)) \
                 else (0 if self._moves else -1)
        if target >= 0:
            self._select_move(self._moves[target])
        else:
            self._cur_idx = -1
            self._info_form.set_element(None)
            self._cmd_tab.load(None, None, '', '')
            self._dec_tab.load([], None, '', '')

    def _make_move_btn(self, move_dict):
        name = move_dict['spm_elem'].get('name', '?')
        aid  = move_dict[ui_text("ui_spm_actid")]
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=False))
        bl = QVBoxLayout(btn)
        bl.setContentsMargins(10, 3, 10, 3)
        bl.setSpacing(0)
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(name_lbl)
        id_lbl = QLabel(aid)
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(id_lbl)
        btn.clicked.connect(lambda _, m=move_dict: self._select_move(m))
        return btn

    def _filter_moves(self):
        q = self._move_search.text().lower()
        for btn, m in self._move_btns:
            name = m['spm_elem'].get('name', '').lower()
            aid  = m[ui_text("ui_spm_actid")].lower()
            btn.setVisible(q == '' or q in name or q in aid)

    def _select_move(self, move_dict):
        self._cur_idx = self._moves.index(move_dict) if move_dict in self._moves else -1
        for btn, m in self._move_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(m is move_dict)))
        self._info_form.set_element(move_dict['spm_elem'])
        self._cmd_tab.load(
            move_dict['entry_elem'], self._result['root'],
            move_dict[ui_text("ui_spm_actid")], move_dict[ui_text("ui_spm_actkind")])
        self._dec_tab.load(
            move_dict['decorator_elems'], self._result['root'],
            move_dict[ui_text("ui_spm_actid")], move_dict[ui_text("ui_spm_actkind")])

    def _on_entry_created(self, entry_elem):
        if 0 <= self._cur_idx < len(self._moves):
            self._moves[self._cur_idx]['entry_elem'] = entry_elem

    # Move CRUD

    def _add_move(self):
        if self._result is None:
            return
        existing = {(m[ui_text("ui_spm_actid")], m[ui_text("ui_spm_actkind")]) for m in self._moves}
        next_id = next(
            str(i) for i in range(1, 200)
            if (str(i), 'spm') not in existing)

        elem = ET.SubElement(self._result['root'], ui_text("ui_spm_specialmove"))
        for k, v in [
            ('name', ui_text("ui_spm_new_move")), ('view', '0'), ('type', 'normal'),
            ('path', 'normal.xml'), (ui_text("ui_spm_commandlistnum"), '-1'),
            (ui_text("ui_spm_actid"), next_id), (ui_text("ui_spm_actkind"), 'spm'),
            (ui_text("ui_spm_startanmid"), '0'), (ui_text("ui_spm_startsetdirc"), 'true'),
            (ui_text("ui_spm_ignoreendpostype"), 'false'), (ui_text("ui_spm_waitendland"), 'false'),
            (ui_text("ui_spm_usecanceleffect"), 'true'), (ui_text("ui_spm_disablemisshitcancel"), 'false'),
            (ui_text("ui_spm_actpriority"), '6'),
        ]:
            elem.set(k, v)

        m = {'actID': next_id, 'actKind': 'spm',
             'spm_elem': elem, 'entry_elem': None, 'decorator_elems': []}
        self._moves.append(m)
        self._refresh_move_list(keep_idx=len(self._moves) - 1)
        self._mark_dirty()

    def _dup_move(self):
        if self._cur_idx < 0 or self._cur_idx >= len(self._moves) or self._result is None:
            return
        src = self._moves[self._cur_idx]
        existing = {(m[ui_text("ui_spm_actid")], m[ui_text("ui_spm_actkind")]) for m in self._moves}
        next_id = next(
            str(i) for i in range(1, 200)
            if (str(i), src[ui_text("ui_spm_actkind")]) not in existing)

        new_elem = copy.deepcopy(src['spm_elem'])
        new_elem.set(ui_text("ui_spm_actid"), next_id)
        new_elem.set('name', src['spm_elem'].get('name', '') + ui_text("ui_spm_copy"))
        self._result['root'].append(new_elem)

        new_entry = None
        if src['entry_elem'] is not None:
            new_entry = copy.deepcopy(src['entry_elem'])
            new_entry.set(ui_text("ui_spm_actid"), next_id)
            self._result['root'].append(new_entry)

        new_decs = []
        for dec in src['decorator_elems']:
            new_dec = copy.deepcopy(dec)
            new_dec.set(ui_text("ui_spm_actid"), next_id)
            self._result['root'].append(new_dec)
            new_decs.append(new_dec)

        m = {'actID': next_id, 'actKind': src[ui_text("ui_spm_actkind")],
             'spm_elem': new_elem, 'entry_elem': new_entry, 'decorator_elems': new_decs}
        self._moves.append(m)
        self._refresh_move_list(keep_idx=len(self._moves) - 1)
        self._mark_dirty()

    def _del_move(self):
        row = self._cur_idx
        if row < 0 or row >= len(self._moves) or self._result is None:
            return
        m    = self._moves[row]
        root = self._result['root']
        for elem in [m['spm_elem'], m['entry_elem']] + m['decorator_elems']:
            if elem is not None:
                try:
                    root.remove(elem)
                except ValueError:
                    pass
        self._moves.pop(row)
        self._cur_idx = -1
        self._refresh_move_list(keep_idx=min(row, len(self._moves) - 1))
        self._mark_dirty()
