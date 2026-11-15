"""editors/spm_editor.py  –  SPM (Special Move Parameters) XFBIN editor."""

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    mono_font,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card_frame,
    make_editor_card_layout,
    make_editor_field_shell,
    make_empty_state,
    ss_badge,
    ss_bg_dark,
    ss_dim_label,
    ss_field_label,
    ss_main_label,
    ss_panel,
    ss_panel_title,
    ss_sidebar_btn,
    ss_sidebar_treewidget,
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
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy
import os
import re
import xml.etree.ElementTree as ET

import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QSplitter, QTabWidget, QComboBox, QTreeWidget, QTreeWidgetItem,
    QStackedWidget, QSizePolicy, QToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from core.themes import P
from core.editor_file_state import set_file_label
from parsers.spm_parser import parse_spm_xfbin, save_spm_xfbin, get_moves
from core.translations import ui_text
from core.spm_tools import SpmNames, field_label, trigger_label, command_preview, TRIGGERS, next_action_id, ACTION_LIMITS
from core.settings import create_backup_on_open, game_files_dialog_dir


# Constants

XML_SPECIAL_MOVE = 'SpecialMove'
XML_ENTRY_SPM = 'EntrySPM'
XML_DECORATOR = 'Decorator'
XML_COMMAND = 'Command'
XML_COM_ELEMENT = 'ComElement'
XML_SELECT_ANM_LIST = 'SelectAnmList'

ATTR_ACT_ID = 'actID'
ATTR_ACT_KIND = 'actKind'
ATTR_COMMAND_LIST_NUM = 'commandListNum'
ATTR_ENABLE_TIME = 'enableTime'
ATTR_AS_DERIVED = 'asDerived'
ATTR_DISABLE_AIR_INV = 'disableAirInv'
ATTR_START_ANM_ID = 'startAnmID'
ATTR_START_SET_DIRC = 'startSetDirc'
ATTR_IGNORE_END_POS_TYPE = 'ignoreEndPosType'
ATTR_WAIT_END_LAND = 'waitEndLand'
ATTR_USE_CANCEL_EFFECT = 'useCancelEffect'
ATTR_DISABLE_MISS_HIT_CANCEL = 'disableMissHitCancel'
ATTR_ACT_PRIORITY = 'actPriority'
ATTR_CHECK_FLG = 'checkFlg'
ATTR_WAIT_CANCEL_FLAG = 'waitCancelFlag'
ATTR_CHECK_ONLY = 'checkOnly'
ATTR_CHECK_GROUP_EX1 = 'checkGroupEx1'
ATTR_GROUP_EX1_ON = 'groupEx1On'
ATTR_CHECK_BEFORE_ANM = 'checkBeforeAnm'
ATTR_BEFORE_ANM_ID = 'beforeAnmID'
ATTR_ATTACK_FLAG = 'attackFlag'
ATTR_HIGH_FLAG = 'highFlag'

BOOL_ATTRS = {
    ATTR_START_SET_DIRC, ATTR_IGNORE_END_POS_TYPE, ATTR_WAIT_END_LAND, ATTR_USE_CANCEL_EFFECT,
    ATTR_DISABLE_MISS_HIT_CANCEL, ATTR_AS_DERIVED, ATTR_DISABLE_AIR_INV, ATTR_CHECK_FLG,
    ATTR_WAIT_CANCEL_FLAG, ATTR_CHECK_ONLY, ATTR_CHECK_GROUP_EX1, ATTR_GROUP_EX1_ON, ATTR_CHECK_BEFORE_ANM,
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
    'hhaStart':       {'path': 'hhaStart.xml',       'endCutInCnt': '30'},
    'hitDerived':     {'path': 'hitDerived.xml',      'hitDrvID': '1_spm',
                       'hitType': '0', 'checkFlg': 'false', 'waitCancelFlag': 'false'},
    'startAnmSelect': {'path': 'startAnmSelect.xml'},
    'gaugeCnsm':      {'path': 'gaugeCnsm.xml',       'startConsumption': '25',
                       'keepConsumption': '0', 'checkOnly': 'false'},
    'styleMark':      {'path': 'styleMark.xml'},
}

DEC_TYPES = list(DEC_DEFAULTS.keys())


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
    f, fl, _label, _hint = make_editor_field_shell(label_text)
    f.setMinimumWidth(0)
    e = QLineEdit(str(value_text))
    e.setMinimumWidth(0)
    e.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    configure_input(e, monospace=True)
    fl.addWidget(e)
    return f, e


def _card_frame():
    return make_editor_card_frame()


def _card_layout(card, margins=Insets.CARD, spacing=Size.CARD_GAP):
    return make_editor_card_layout(card, margins=margins, spacing=spacing)


def _title_row(title, subtitle="", icon_name=None):
    row = QWidget()
    row.setStyleSheet(ss_transparent())
    layout = QVBoxLayout(row)
    configure_layout(layout, LayoutRole.ROOT)
    add_editor_card_title(layout, title, icon_name, subtitle)
    return row


def _bool_combo(value):
    combo = QComboBox()
    combo.addItem(ui_text('spm_value_false'), 'false')
    combo.addItem(ui_text('spm_value_true'), 'true')
    if str(value) not in ('true', 'false'):
        combo.addItem(str(value), str(value))
    combo.setCurrentIndex(combo.findData(str(value)))
    configure_input(combo, monospace=False)
    return combo


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


def _right_scroll():
    scroll = QScrollArea()


    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    configure_scrollarea(scroll)
    inner = QWidget()
    inner.setMinimumWidth(0)
    inner.setStyleSheet(ss_bg_dark())
    layout = QVBoxLayout(inner)
    configure_layout(layout, LayoutRole.PAGE)
    scroll.setWidget(inner)
    return scroll, layout


def _placeholder_label(text, *, title=None, icon_name="fa6s.list"):
    return make_empty_state(
        title=title or ui_text("ui_model_viewer_select_item"),
        text=text,
        icon_name=icon_name,
    )


def _sidebar_buttons_row():
    """Returns (frame, new_btn, dup_btn, del_btn) — matches CharStats sidebar style."""
    frame = EditorActionRow()

    layout = frame.content_layout


    bf = ui_font(TypeSize.HINT)


    new_btn = QPushButton(ui_text("btn_new"))
    new_btn.setMinimumWidth(0)
    configure_button(new_btn, height=Size.COMPACT_CONTROL)
    layout.addWidget(new_btn, 1)

    dup_btn = QPushButton(ui_text("btn_duplicate"))
    dup_btn.setMinimumWidth(0)
    configure_button(dup_btn, height=Size.COMPACT_CONTROL)
    layout.addWidget(dup_btn, 1)

    del_btn = QPushButton(ui_text("btn_delete"))
    del_btn.setMinimumWidth(0)
    configure_button(del_btn, danger=True, height=Size.COMPACT_CONTROL)
    layout.addWidget(del_btn, 1)

    return frame, new_btn, dup_btn, del_btn


def _make_sidebar(width=240):
    sidebar = EditorSidebar(width=width)


    sl = sidebar.content_layout


    return sidebar, sl


# _AttrForm

class _AttrForm(QScrollArea):
    """Scrollable attribute form for any ET.Element."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._elem = None
        inner = QWidget()
        inner.setMinimumWidth(0)
        inner.setStyleSheet(ss_bg_dark())
        self._grid = QGridLayout(inner)
        configure_layout(self._grid, LayoutRole.PAGE_GRID)
        self._grid.setColumnStretch(1, 1)
        self.setWidget(inner)


        configure_scrollarea(self)

    def set_element(self, elem):
        self._elem = None
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        if elem is None:
            lbl = QLabel(ui_text("ui_spm_nothing_selected"))
            lbl.setStyleSheet(ss_dim_label())
            lbl.setFont(ui_font(TypeSize.LABEL))
            self._grid.addWidget(lbl, 0, 0, 1, 2)
            return

        for row, (attr, val) in enumerate(elem.attrib.items()):
            lbl = QLabel(attr + ':')
            lbl.setFont(ui_font(TypeSize.CODE))
            lbl.setStyleSheet(ss_field_label())
            lbl.setFixedWidth(180)
            self._grid.addWidget(lbl, row, 0, Qt.AlignmentFlag.AlignTop)

            if attr in BOOL_ATTRS:
                w = QComboBox()
                w.addItems(['true', 'false'])
                w.setCurrentText(val)
                configure_input(w, monospace=True)
                w.currentTextChanged.connect(lambda v, a=attr: self._set(a, v))
            else:
                w = QLineEdit(val)
                configure_input(w)
                w.textChanged.connect(lambda v, a=attr: self._set(a, v))

            self._grid.addWidget(w, row, 1)

        self._grid.setRowStretch(len(elem.attrib), 1)
        self._elem = elem

    def _set(self, attr, val):
        if self._elem is not None:
            self._elem.set(attr, val)
            self.changed.emit()


# _MoveInfoTab

class _MoveInfoTab(QScrollArea):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._move = None
        self._elem = None
        self.names = SpmNames()
        self.on_edit = None
        self._loading = False
        self._editors = []
        self._compact = None
        self._extra_open = False
        self._inner = QWidget()
        self._inner.setMinimumWidth(0)
        self._inner.setStyleSheet(ss_bg_dark())
        self._layout = QVBoxLayout(self._inner)
        configure_layout(self._layout, LayoutRole.PAGE)
        self.setWidget(self._inner)


        configure_scrollarea(self)

    def load(self, move_dict):
        self._loading = True
        self._compact = self.viewport().width() < 900
        self._editors = []
        _clear_layout(self._layout)
        self._move = move_dict
        self._elem = move_dict.get('spm_elem') if move_dict else None
        if self._elem is None:
            self._layout.addStretch()
            self._layout.addWidget(_placeholder_label(ui_text("ui_spm_open_a_spm_xfbin_file_to_begin_editing")))
            self._layout.addStretch()
            self._loading = False
            return

        self._layout.addWidget(self._hero_card())

        top = QGridLayout()
        configure_layout(top, LayoutRole.GRID)
        top.addWidget(self._basic_card(), 0, 0)
        top.addWidget(self._binding_card(), 1 if self.viewport().width() < 900 else 0, 0 if self.viewport().width() < 900 else 1)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 0 if self.viewport().width() < 900 else 1)
        self._layout.addLayout(top)

        self._layout.addWidget(self._animation_card())
        self._add_extra_attributes()
        self._layout.addStretch()
        self._loading = False

    def _hero_card(self):
        card = _card_frame()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(24)

        badge = QLabel()
        badge.setFixedSize(72, 72)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(qta.icon("fa6s.explosion", color=P["accent"]).pixmap(52, 52))
        badge.setStyleSheet(
            ss_badge(round=True)
        )
        layout.addWidget(badge)

        title = QWidget()
        title.setStyleSheet(ss_transparent())
        tl = QVBoxLayout(title)
        configure_layout(tl, LayoutRole.FIELD)
        name_lbl = QLabel(self.names.display(self._elem.get('name', '')))
        name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        name_lbl.setWordWrap(True)
        name_lbl.setMinimumWidth(0)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._name_label = name_lbl
        name_lbl.setToolTip(self._elem.get('name', ''))
        name_lbl.setFont(ui_font(TypeSize.HERO, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        tl.addWidget(name_lbl)
        sub = QLabel(self._elem.get('name', ''))
        sub.setTextFormat(Qt.TextFormat.PlainText)
        sub.setWordWrap(True)
        sub.setMinimumWidth(0)
        sub.setFont(ui_font(TypeSize.LABEL))
        sub.setStyleSheet(ss_dim_label())
        tl.addWidget(sub)
        layout.addWidget(title, 2)

        for label, value in [
            ("View", self._elem.get('view', '')),
            ("Type", self._elem.get('type', '')),
            ("Path", self._elem.get('path', '')),
        ]:
            if self.viewport().width() >= 900:
                layout.addWidget(self._summary_value(field_label(label), value), 1)
        return card

    def _summary_value(self, label, value):
        frame = QWidget()
        frame.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(frame)
        configure_layout(layout, LayoutRole.FIELD)
        lbl = QLabel(label)
        lbl.setFont(ui_font(TypeSize.LABEL))
        lbl.setStyleSheet(ss_field_label())
        layout.addWidget(lbl)
        val = QLabel(str(value))
        val.setFont(mono_font(TypeSize.SUBHEADING))
        val.setStyleSheet(ss_main_label())
        layout.addWidget(val)
        return frame

    def _basic_card(self):
        card = _card_frame()
        layout = _card_layout(card)
        layout.addWidget(_title_row(ui_text('spm_basic_title'), ui_text('spm_basic_hint'), 'fa6s.file-lines'))
        grid = QGridLayout()
        configure_layout(grid, LayoutRole.GRID)
        for row, attr in enumerate(['name', 'view', 'type', 'path']):
            grid.addWidget(self._field_label(attr), row, 0)
            editor = self._line_editor(attr)
            grid.addWidget(editor, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card

    def _binding_card(self):
        card = _card_frame()
        layout = _card_layout(card)
        layout.addWidget(_title_row(ui_text('spm_binding_title'), ui_text('spm_binding_hint'), 'fa6s.crosshairs'))
        grid = QGridLayout()
        configure_layout(grid, LayoutRole.GRID)
        for row, attr in enumerate([ATTR_COMMAND_LIST_NUM, ATTR_ACT_ID, ATTR_ACT_KIND, ATTR_ACT_PRIORITY]):
            grid.addWidget(self._field_label(attr), row, 0)
            grid.addWidget(self._line_editor(attr), row, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card

    def _animation_card(self):
        card = _card_frame()
        layout = _card_layout(card)
        layout.addWidget(_title_row(ui_text('spm_animation_title'), ui_text('spm_animation_hint'), 'fa6s.person-running'))
        grid = QGridLayout()
        grid.setContentsMargins(*Insets.NONE)
        configure_layout(grid, LayoutRole.GRID)
        grid.addWidget(self._field_label(ATTR_START_ANM_ID), 0, 0)
        grid.addWidget(self._line_editor(ATTR_START_ANM_ID), 0, 1)
        bools = [
            ATTR_IGNORE_END_POS_TYPE, ATTR_START_SET_DIRC,
            ATTR_USE_CANCEL_EFFECT, ATTR_WAIT_END_LAND,
            ATTR_DISABLE_MISS_HIT_CANCEL,
        ]
        for idx, attr in enumerate(bools, start=1):
            row = 1 + (idx - 1) // 2
            compact = self.viewport().width() < 900
            row = idx if compact else row
            base_col = 0 if compact or idx % 2 == 1 else 2
            grid.addWidget(self._field_label(attr), row, base_col)
            combo = _bool_combo(self._elem.get(attr, 'false'))
            combo.currentIndexChanged.connect(lambda _, a=attr, w=combo: self._set_attr(a, w.currentData()))
            grid.addWidget(combo, row, base_col + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        return card

    def _field_label(self, text):
        lbl = QLabel(field_label(text))
        lbl.setToolTip(text)
        lbl.setWordWrap(True)
        lbl.setMinimumWidth(0)
        lbl.setFont(ui_font(TypeSize.LABEL))
        lbl.setStyleSheet(ss_field_label())
        return lbl

    def _line_editor(self, attr):
        editor = QLineEdit(self._elem.get(attr, ''))
        editor.setMinimumWidth(0)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        editor.setToolTip(attr)
        self._editors.append((editor, attr))
        configure_input(editor, height=Size.CONTROL, monospace=True)
        editor.editingFinished.connect(lambda a=attr, e=editor: self._set_attr(a, e.text()))
        return editor

    def _set_attr(self, attr, value):
        if self._loading or self._elem is None:
            return True
        if value == self._elem.get(attr, ''):
            return True
        if self.on_edit is not None:
            if not self.on_edit(self._move, attr, value):
                return False
        else:
            self._elem.set(attr, value)
        self._name_label.setText(self.names.display(self._elem.get('name', '')))
        self.changed.emit()
        return True

    def commit_pending(self):
        return all(self._set_attr(attr, editor.text()) for editor, attr in self._editors)

    def _add_extra_attributes(self):
        shown = {'name', 'view', 'type', 'path', ATTR_COMMAND_LIST_NUM, ATTR_ACT_ID,
                 ATTR_ACT_KIND, ATTR_ACT_PRIORITY, ATTR_START_ANM_ID,
                 ATTR_IGNORE_END_POS_TYPE, ATTR_START_SET_DIRC, ATTR_USE_CANCEL_EFFECT,
                 ATTR_WAIT_END_LAND, ATTR_DISABLE_MISS_HIT_CANCEL}
        extra = [(key, value) for key, value in self._elem.attrib.items() if key not in shown]
        if not extra:
            return
        card = _card_frame()
        body = _card_layout(card)
        hint = QLabel(ui_text('spm_extra_hint'))
        hint.setWordWrap(True)
        hint.setStyleSheet(ss_dim_label())
        body.addWidget(hint)
        for attr, value in extra:
            frame, layout, _, _ = make_editor_field_shell(field_label(attr))
            if value in ('true', 'false'):
                editor = _bool_combo(value)
                editor.currentIndexChanged.connect(lambda _, a=attr, w=editor: self._set_attr(a, w.currentData()))
            else:
                editor = self._line_editor(attr)
            editor.setToolTip(attr)
            layout.addWidget(editor)
            body.addWidget(frame)
        self._layout.addWidget(card)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._move is not None and not self._loading:
            QTimer.singleShot(0, self._reflow)

    def _reflow(self):
        if self._move is not None and not self._loading and self._compact != (self.viewport().width() < 900):
            if self.commit_pending():
                self.load(self._move)


# _CommandsTab

class _CommandsTab(QWidget):
    changed = pyqtSignal()
    entry_created = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry_elem   = None
        self._root_elem    = None
        self._actID        = ''
        self._actKind      = ''
        self._selected_cmd = None
        self._pending_edits = []
        self._cmd_btns     = []
        self._cur_cmd_elem = None  # command whose detail is currently shown
        self._compact = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        self._stack = QStackedWidget()

        # Page 0: no EntrySPM
        no_entry = QWidget()
        no_entry.setStyleSheet(ss_bg_dark())
        nl = QVBoxLayout(no_entry)
        nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.setSpacing(14)

        msg = QLabel(ui_text("ui_spm_this_move_has_no_input_commands_non_inputtable_d"))
        msg.setFont(ui_font(TypeSize.TITLE))
        msg.setStyleSheet(ss_dim_label())
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.addWidget(msg)

        create_btn = QPushButton(ui_text("ui_spm_create_entryspm"))
        configure_button(create_btn, accent=True)
        create_btn.clicked.connect(self._create_entry)
        create_btn.setProperty("designAction", 'new')
        nl.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(no_entry)

        # Page 1: command editor
        entry_w = QWidget()
        entry_w.setStyleSheet(ss_bg_dark())
        ev = QHBoxLayout(entry_w)
        configure_layout(ev, LayoutRole.ROOT)

        # Left sidebar: search + buttons + list
        sidebar, sl = _make_sidebar(240)

        self._cmd_search = QLineEdit()
        configure_search(self._cmd_search)
        self._cmd_search.textChanged.connect(self._filter_cmds)
        sl.addWidget(self._cmd_search)

        btn_frame, self._add_cmd_btn, self._dup_cmd_btn, self._del_cmd_btn = _sidebar_buttons_row()
        self._add_cmd_btn.clicked.connect(self._add_command)
        self._add_cmd_btn.setProperty("designAction", 'new')
        self._dup_cmd_btn.clicked.connect(self._dup_command)
        self._dup_cmd_btn.setProperty("designAction", 'duplicate')
        self._del_cmd_btn.clicked.connect(self._del_command)
        self._del_cmd_btn.setProperty("designAction", 'delete')
        sl.addWidget(btn_frame)

        self._cmd_scroll, self._cmd_list_widget, self._cmd_list_layout = _sidebar_scroll()
        sl.addWidget(self._cmd_scroll)
        ev.addWidget(sidebar)

        div = EditorSeparator(orientation=Qt.Orientation.Vertical)


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
        self._pending_edits = []
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
            if self._cmd_btns:
                self._select_cmd(self._cmd_btns[0][1])

    # command list

    def _refresh_cmd_list(self):
        _clear_layout(self._cmd_list_layout)
        self._cmd_btns = []
        if self._entry_elem is None:
            self._cmd_list_layout.addStretch()
            return
        for i, cmd in enumerate(self._entry_elem.findall(XML_COMMAND)):
            selected = cmd is self._selected_cmd
            btn = self._make_cmd_btn(i, cmd, selected)
            self._cmd_list_layout.insertWidget(self._cmd_list_layout.count(), btn)
            self._cmd_btns.append((btn, cmd))
        self._cmd_list_layout.addStretch()

    def _make_cmd_btn(self, idx, cmd_elem, selected):
        btn = EditorListRow()


        bl = btn.content_layout


        name_lbl = btn.add_title(ui_text('ui_spm_command_value', p0=idx + 1))


        sub_lbl = btn.add_subtitle(command_preview(cmd_elem), value_font=ui_font(TypeSize.CODE))
        sub_lbl.setToolTip(command_preview(cmd_elem))


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
        if not self.commit_pending():
            return
        self._selected_cmd = cmd_elem
        for btn, cmd in self._cmd_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(cmd is cmd_elem)))
        self._build_cmd_editor(cmd_elem)

    # command detail card

    def _build_cmd_editor(self, cmd_elem):
        self._pending_edits = []
        self._cur_cmd_elem = cmd_elem
        _clear_layout(self._right_layout)
        compact = self._right_scroll.viewport().width() < 760
        self._compact = compact

        card = _card_frame()
        card_main = _card_layout(card)
        card_main.addWidget(_title_row(ui_text('spm_command_title'), ui_text('spm_command_hint'), 'fa6s.gear'))
        grid = QGridLayout()
        grid.setContentsMargins(*Insets.NONE)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(Size.CARD_GAP)

        fields_def = [
            ('trigger', field_label('trigger')),
            (ATTR_ENABLE_TIME, field_label(ATTR_ENABLE_TIME)),
            ('condition', field_label('condition')),
        ]
        for ci, (key, label) in enumerate(fields_def):
            fw, fe = _make_field(label, cmd_elem.get(key, ''))
            row = ci if compact else 0
            col = 0 if compact else ci
            grid.addWidget(fw, row, col)
            grid.setColumnStretch(col, 1)
            self._pending_edits.append((fe, cmd_elem, key))
            fe.editingFinished.connect(lambda k=key, f=fe, e=cmd_elem: self._set_value(e, k, f.text()))
            if key == 'trigger':
                fe.setToolTip(ui_text('spm_trigger_hint'))
                self._trigger_choices(grid, len(fields_def) if compact else 2, col, cmd_elem, fe)

        bool_row_offset = len(fields_def) + 1 if compact else 1
        for ci, (key, label) in enumerate([
            (ATTR_AS_DERIVED, field_label(ATTR_AS_DERIVED)),
            (ATTR_DISABLE_AIR_INV, field_label(ATTR_DISABLE_AIR_INV)),
        ]):
            frame = QWidget()
            frame.setStyleSheet(ss_transparent())
            fl = QVBoxLayout(frame)
            configure_layout(fl, LayoutRole.FIELD)
            lbl = QLabel(label)
            lbl.setFont(ui_font(TypeSize.LABEL))
            lbl.setStyleSheet(ss_field_label())
            fl.addWidget(lbl)
            combo = _bool_combo(cmd_elem.get(key, 'false'))
            combo.currentIndexChanged.connect(lambda _, k=key, w=combo, e=cmd_elem: self._set_value(e, k, w.currentData()))
            fl.addWidget(combo)
            row = bool_row_offset + ci if compact else 1
            col = 0 if compact else ci
            grid.addWidget(frame, row, col)

        card_main.addLayout(grid)
        self._right_layout.addWidget(card)
        self._build_comel_card(cmd_elem)
        self._right_layout.addStretch()

    def _build_comel_card(self, cmd_elem):
        compact = self._right_scroll.viewport().width() < 760
        card = _card_frame()
        cl = _card_layout(card)
        cl.addWidget(_title_row(
            ui_text("ui_spm_input_sequence"),
            ui_text('spm_sequence_hint'),
            "fa6s.sliders",
        ))

        els = list(cmd_elem.findall(XML_COM_ELEMENT))
        if els:
            for el in els:
                cl.addWidget(self._make_comel_row(el, cmd_elem))
        else:
            hint = QLabel(ui_text("ui_spm_no_inputs_yet_add_directions_below"))
            hint.setFont(ui_font(TypeSize.CODE))
            hint.setStyleSheet(ss_field_label())
            cl.addWidget(hint)

        # Direction picker label
        bottom = QWidget()
        bottom.setStyleSheet(ss_transparent())
        bottom_l = QVBoxLayout(bottom) if compact else QHBoxLayout(bottom)
        bottom_l.setContentsMargins(*Insets.GRID_TITLE)
        bottom_l.setSpacing(14 if compact else 28)

        picker_shell = QWidget()
        picker_shell.setStyleSheet(ss_transparent())
        picker_l = QVBoxLayout(picker_shell)
        configure_layout(picker_l, LayoutRole.TITLE)
        pick_lbl = QLabel(ui_text("ui_spm_add_direction"))
        pick_lbl.setFont(ui_font(TypeSize.LABEL, QFont.Weight.Bold))
        pick_lbl.setStyleSheet(ss_panel_title())
        picker_l.addWidget(pick_lbl)

        # 3×3 numpad picker
        picker = QWidget()
        picker.setStyleSheet(ss_transparent())
        pg = QGridLayout(picker)
        pg.setContentsMargins(*Insets.NONE)
        pg.setSpacing(6)
        for r, row_keys in enumerate(NUMPAD_LAYOUT):
            for c, key in enumerate(row_keys):
                btn = QPushButton(KEY_HINTS[key])
                btn.setFixedSize(48, 42)
                configure_button(btn)
                btn.clicked.connect(
                    lambda checked=False, k=key, ce=cmd_elem: self._add_direction(k, ce))
                btn.setProperty("designAction", 'new')
                pg.addWidget(btn, r, c)
        picker_l.addWidget(picker)
        bottom_l.addWidget(picker_shell, 0, Qt.AlignmentFlag.AlignTop)

        preview = QWidget()
        preview.setStyleSheet(ss_transparent())
        preview_l = QVBoxLayout(preview)
        preview_l.setContentsMargins(*Insets.NONE)
        preview_l.setSpacing(Size.CARD_GAP)
        preview_lbl = QLabel(ui_text('spm_sequence_preview'))
        preview_lbl.setFont(ui_font(TypeSize.TITLE))
        preview_lbl.setStyleSheet(ss_main_label())
        preview_l.addWidget(preview_lbl)
        preview_row = QWidget()
        preview_row.setStyleSheet(ss_transparent())
        pr = QGridLayout(preview_row)
        pr.setContentsMargins(*Insets.NONE)
        pr.setSpacing(6)
        columns = max(1, (self._right_scroll.viewport().width() - 100) // 76)
        for idx, el in enumerate(els):
            tile = QLabel(KEY_HINTS.get(el.get('key', '?'), el.get('key', '?')))
            tile.setFixedSize(62, 38)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setFont(ui_font(TypeSize.DISPLAY))
            tile.setToolTip(f"{idx + 1}: key={el.get('key', '?')}")
            tile.setStyleSheet(ss_badge(accent=True))
            pr.addWidget(tile, idx // columns, idx % columns)
        preview_l.addWidget(preview_row)
        bottom_l.addWidget(preview, 1, Qt.AlignmentFlag.AlignVCenter)
        cl.addWidget(bottom)

        self._right_layout.addWidget(card)

    def _make_comel_row(self, el, cmd_elem):
        row_w = QWidget()
        row_w.setStyleSheet(
            ss_panel()
        )
        rl = QHBoxLayout(row_w)
        configure_layout(rl, LayoutRole.TOOLBAR)

        direction = QComboBox()
        direction.setFixedSize(76, 34)
        configure_input(direction)
        for key, arrow in KEY_HINTS.items():
            direction.addItem(f'{arrow} {key}', key)
        current = el.get('key', '?')
        if direction.findData(current) < 0:
            direction.addItem(current, current)
        direction.setCurrentIndex(direction.findData(current))
        direction.activated.connect(lambda _: self._change_direction(el, cmd_elem, direction.currentData()))
        rl.addWidget(direction)

        time_lbl = QLabel(ui_text("ui_spm_time"))
        time_lbl.setFont(ui_font(TypeSize.BODY))
        time_lbl.setStyleSheet(ss_field_label())
        rl.addWidget(time_lbl)

        time_edit = QLineEdit(el.get('time', '0'))
        time_edit.setFixedWidth(60)
        configure_input(time_edit, monospace=True)
        self._pending_edits.append((time_edit, el, 'time'))
        time_edit.editingFinished.connect(lambda fe=time_edit, e=el: self._set_value(e, 'time', fe.text()))
        rl.addWidget(time_edit)
        rl.addStretch()
        for delta, arrow, caption in ((-1, '↑', 'spm_up'), (1, '↓', 'spm_down')):
            button = QPushButton(arrow)
            button.setFixedSize(30, 30)
            button.setToolTip(ui_text(caption))
            configure_button(button)
            button.clicked.connect(lambda _, e=el, c=cmd_elem, d=delta: self._move_direction(e, c, d))
            rl.addWidget(button)

        del_btn = QPushButton(ui_text("btn_delete"))
        if self.width() < 760:
            del_btn.setText("")
            del_btn.setFixedWidth(34)
        del_btn.setIcon(qta.icon("fa6s.trash-can", color=P["accent"]))
        configure_button(del_btn, danger=True)
        del_btn.clicked.connect(
            lambda _, e=el, ce=cmd_elem: self._del_direction(e, ce))
        del_btn.setProperty("designAction", 'delete')
        rl.addWidget(del_btn)
        return row_w

    def _add_direction(self, key, cmd_elem):
        if not self.commit_pending():
            return
        el = ET.SubElement(cmd_elem, XML_COM_ELEMENT)
        el.set('key', key)
        el.set('time', '0')
        self._build_cmd_editor(cmd_elem)
        self.changed.emit()

    def _del_direction(self, el, cmd_elem):
        if not self.commit_pending():
            return
        try:
            cmd_elem.remove(el)
        except ValueError:
            pass
        self._build_cmd_editor(cmd_elem)
        self.changed.emit()

    # command CRUD

    def _set_value(self, elem, attr, value):
        if value == elem.get(attr, ''):
            return True
        if attr in ('trigger', 'enableTime', 'condition', 'time'):
            try:
                number = int(value)
                valid = -0x80000000 <= number <= 0xffffffff
            except ValueError:
                valid = False
            if not valid:
                QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('spm_invalid_number', field=field_label(attr)))
                return False
        elem.set(attr, value)
        self.changed.emit()
        for index, (button, command) in enumerate(self._cmd_btns):
            labels = button.findChildren(QLabel)
            if len(labels) >= 2:
                labels[1].setText(command_preview(command))
                button.setToolTip(command_preview(command))
        return True

    def commit_pending(self):
        return all(self._set_value(elem, attr, widget.text()) for widget, elem, attr in self._pending_edits)

    def _trigger_choices(self, grid, row, col, command, field):
        choices = QComboBox()
        configure_input(choices)
        choices.setMinimumWidth(0)
        choices.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        choices.setToolTip(ui_text('spm_trigger_hint'))
        choices.addItem(ui_text('spm_trigger_preset'), None)
        for code in TRIGGERS:
            choices.addItem(f'{trigger_label(str(code))} ({code})', str(code))
        def choose(index):
            value = choices.itemData(index)
            if value is not None:
                field.setText(value)
                self._set_value(command, 'trigger', value)
        choices.activated.connect(choose)
        grid.addWidget(choices, row, col)

    def _change_direction(self, elem, command, value):
        if self.commit_pending():
            elem.set('key', value)
            self.changed.emit()
            self._build_cmd_editor(command)

    def _move_direction(self, elem, command, delta):
        if not self.commit_pending():
            return
        directions = list(command.findall(XML_COM_ELEMENT))
        index = directions.index(elem)
        other = index + delta
        if not 0 <= other < len(directions):
            return
        children = list(command)
        left, right = children.index(elem), children.index(directions[other])
        children[left], children[right] = children[right], children[left]
        command[:] = children
        self.changed.emit()
        self._build_cmd_editor(command)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_right_scroll') and self._cur_cmd_elem is not None:
            QTimer.singleShot(0, self._reflow)

    def _reflow(self):
        if self._cur_cmd_elem is not None and self._compact != (self._right_scroll.viewport().width() < 760):
            if self.commit_pending():
                self._build_cmd_editor(self._cur_cmd_elem)

    def _create_entry(self):
        if self._root_elem is None:
            return
        e = ET.SubElement(self._root_elem, XML_ENTRY_SPM)
        e.set(ATTR_ACT_ID, self._actID)
        e.set(ATTR_ACT_KIND, self._actKind)
        self._entry_elem = e
        self.entry_created.emit(e)
        self._stack.setCurrentIndex(1)
        self._refresh_cmd_list()
        _clear_layout(self._right_layout)
        self._right_layout.addWidget(_placeholder_label(ui_text("ui_spm_select_a_command")))
        self._right_layout.addStretch()

    def _add_command(self):
        if self._entry_elem is None or not self.commit_pending():
            return
        cmd = ET.SubElement(self._entry_elem, XML_COMMAND)
        for k, v in [('trigger', '262144'), (ATTR_ENABLE_TIME, '8'),
                     ('condition', '0'), (ATTR_AS_DERIVED, 'false'),
                     (ATTR_DISABLE_AIR_INV, 'false')]:
            cmd.set(k, v)
        self._refresh_cmd_list()
        self._select_cmd(cmd)
        self.changed.emit()

    def _dup_command(self):
        if self._selected_cmd is None or self._entry_elem is None:
            return
        if not self.commit_pending():
            return
        new_cmd = copy.deepcopy(self._selected_cmd)
        self._entry_elem.append(new_cmd)
        self._refresh_cmd_list()
        self._select_cmd(new_cmd)
        self.changed.emit()

    def _del_command(self):
        if self._selected_cmd is None or self._entry_elem is None:
            return
        if not self.commit_pending():
            return
        try:
            self._entry_elem.remove(self._selected_cmd)
        except ValueError:
            pass
        self._selected_cmd = None
        self._cur_cmd_elem = None
        self._pending_edits = []
        self._refresh_cmd_list()
        self.changed.emit()
        _clear_layout(self._right_layout)
        self._right_layout.addWidget(_placeholder_label(ui_text("ui_spm_select_a_command")))
        self._right_layout.addStretch()


# _DecoratorsTab

class _DecoratorsTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending_edits = []
        self._elems     = []
        self._root_elem = None
        self._actID     = ''
        self._actKind   = ''
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        # Left sidebar
        sidebar, sl = _make_sidebar(260)

        # Decorator type selector
        type_frame = QWidget()
        type_frame.setStyleSheet(ss_transparent())
        tf = QVBoxLayout(type_frame)
        tf.setContentsMargins(0, 0, 0, 4)
        tf.setSpacing(Size.GAP_XS)
        type_lbl = QLabel(ui_text("ui_spm_decorator_type"))
        type_lbl.setFont(ui_font(TypeSize.BODY))
        type_lbl.setStyleSheet(ss_field_label())
        tf.addWidget(type_lbl)
        self._type_combo = QComboBox()
        self._type_combo.addItems(DEC_TYPES)
        self._type_combo.setEditable(True)
        configure_input(self._type_combo, monospace=True)
        tf.addWidget(self._type_combo)
        sl.addWidget(type_frame)

        btn_frame, self._add_dec_btn, self._dup_dec_btn, self._del_dec_btn = _sidebar_buttons_row()
        self._add_dec_btn.clicked.connect(self._add_decorator)
        self._add_dec_btn.setProperty("designAction", 'new')
        self._dup_dec_btn.clicked.connect(self._dup_decorator)
        self._dup_dec_btn.setProperty("designAction", 'duplicate')
        self._del_dec_btn.clicked.connect(self._del_decorator)
        self._del_dec_btn.setProperty("designAction", 'delete')
        sl.addWidget(btn_frame)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(ss_sidebar_treewidget())
        self._tree.setFont(ui_font(TypeSize.CODE))
        self._tree.itemSelectionChanged.connect(self._on_tree_sel)
        sl.addWidget(self._tree, 1)

        # Child item buttons below tree
        child_frame = QWidget()
        child_frame.setStyleSheet(ss_transparent())
        cf = QHBoxLayout(child_frame)
        cf.setContentsMargins(*Insets.GRID_TITLE)
        cf.setSpacing(Size.GAP_SM)
        bf = ui_font(TypeSize.BODY)

        self._add_child_btn = QPushButton(ui_text("ui_spm_add_child"))
        configure_button(self._add_child_btn, height=Size.COMPACT_CONTROL)
        self._add_child_btn.clicked.connect(self._add_child_item)
        self._add_child_btn.setProperty("designAction", 'new')
        cf.addWidget(self._add_child_btn, 1)

        self._del_child_btn = QPushButton(ui_text("ui_spm_delete_child"))
        configure_button(self._del_child_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_child_btn.clicked.connect(self._del_child_item)
        self._del_child_btn.setProperty("designAction", 'delete')
        cf.addWidget(self._del_child_btn, 1)
        sl.addWidget(child_frame)

        root.addWidget(sidebar)

        div = EditorSeparator(orientation=Qt.Orientation.Vertical)


        root.addWidget(div)

        self._right_scroll, self._right_layout = _right_scroll()
        self._show_empty_detail()
        root.addWidget(self._right_scroll, 1)

    # public

    def load(self, decorator_elems, root_elem, actID, actKind):
        self._pending_edits = []
        self._elems     = list(decorator_elems)
        self._root_elem = root_elem
        self._actID     = actID
        self._actKind   = actKind
        current_type = self._type_combo.currentText()
        types = list(dict.fromkeys([*DEC_TYPES, *(e.get('type', '') for e in root_elem if e.tag == XML_DECORATOR)])) if root_elem is not None else DEC_TYPES
        self._type_combo.clear()
        self._type_combo.addItems(types)
        self._type_combo.setCurrentText(current_type)
        self._refresh_tree()
        self._show_empty_detail()

    # internal

    def _refresh_tree(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        for dec in self._elems:
            label = dec.get('type', '?')
            top   = QTreeWidgetItem(self._tree, [label])
            top.setData(0, Qt.ItemDataRole.UserRole, dec)
            for child in dec:
                if not isinstance(child.tag, str):
                    continue
                preview = child.tag + ': ' + ', '.join(
                    f"{k}={v}" for k, v in list(child.attrib.items())[:3])
                ch_item = QTreeWidgetItem(top, [preview])
                ch_item.setData(0, Qt.ItemDataRole.UserRole, child)
                ch_item.setFont(0, mono_font(TypeSize.BODY))
        self._tree.expandAll()
        self._tree.blockSignals(False)

    def _on_tree_sel(self):
        self.commit_pending()
        items = self._tree.selectedItems()
        if not items:
            self._show_empty_detail()
            return
        item = items[0]
        parent = item.parent() or item
        elem = parent.data(0, Qt.ItemDataRole.UserRole)
        self._dup_dec_btn.setEnabled(True)
        self._del_dec_btn.setEnabled(True)
        self._del_child_btn.setEnabled(item.parent() is not None)
        self._add_child_btn.setEnabled(elem.get('type') == 'startAnmSelect' or any(isinstance(child.tag, str) for child in elem))
        self._add_child_btn.setToolTip(ui_text('spm_child_template_hint'))
        self._show_detail(items[0].data(0, Qt.ItemDataRole.UserRole))

    def _show_empty_detail(self):
        self._pending_edits = []
        for button in (self._dup_dec_btn, self._del_dec_btn, self._add_child_btn, self._del_child_btn):
            button.setEnabled(False)
        _clear_layout(self._right_layout)
        self._right_layout.addStretch()
        self._right_layout.addWidget(_placeholder_label(ui_text("ui_spm_nothing_selected")))
        self._right_layout.addStretch()

    def _show_detail(self, elem):
        self._pending_edits = []
        _clear_layout(self._right_layout)
        if elem is None:
            self._show_empty_detail()
            return

        self._right_layout.addWidget(self._decorator_summary(elem))
        self._right_layout.addWidget(self._decorator_details(elem))
        if elem.tag == XML_DECORATOR:
            self._right_layout.addWidget(self._decorator_children(elem))
        self._right_layout.addStretch()

    def _decorator_summary(self, elem):
        card = _card_frame()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(24)

        badge = QLabel()
        badge.setFixedSize(72, 72)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(qta.icon("fa6s.sitemap", color=P["accent"]).pixmap(50, 50))
        badge.setStyleSheet(
            ss_badge(round=True)
        )
        layout.addWidget(badge)

        title = QWidget()
        title.setStyleSheet(ss_transparent())
        tl = QVBoxLayout(title)
        configure_layout(tl, LayoutRole.FIELD)
        name = elem.get('type', elem.tag)
        name_lbl = QLabel(name)
        name_lbl.setFont(ui_font(TypeSize.HERO, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        tl.addWidget(name_lbl)
        sub = QLabel(elem.get('path', elem.tag))
        sub.setFont(ui_font(TypeSize.LABEL))
        sub.setStyleSheet(ss_dim_label())
        tl.addWidget(sub)
        layout.addWidget(title, 2)

        for label, value in [
            ("Type", elem.get('type', elem.tag)),
            ("Path", elem.get('path', '')),
            ("Children", len(list(elem))),
            ("End Cut-In Count", elem.get('endCutInCnt', '')),
        ]:
            if self._right_scroll.viewport().width() >= 900:
                layout.addWidget(self._summary_value(field_label(label), value), 1)
        return card

    def _summary_value(self, label, value):
        frame = QWidget()
        frame.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(frame)
        configure_layout(layout, LayoutRole.FIELD)
        lbl = QLabel(label)
        lbl.setFont(ui_font(TypeSize.LABEL))
        lbl.setStyleSheet(ss_field_label())
        layout.addWidget(lbl)
        val = QLabel(str(value))
        val.setFont(mono_font(TypeSize.SUBHEADING))
        val.setStyleSheet(ss_main_label())
        layout.addWidget(val)
        return frame

    def _decorator_details(self, elem):
        card = _card_frame()
        layout = _card_layout(card)
        layout.addWidget(_title_row(ui_text('spm_decorator_details'), ui_text('spm_decorator_hint'), "fa6s.file-lines"))
        grid = QGridLayout()
        configure_layout(grid, LayoutRole.GRID)
        for row, (attr, val) in enumerate(elem.attrib.items()):
            lbl = QLabel(ui_text('ui_spm_decorator_type').rstrip(':') if attr == 'type' else field_label(attr))
            lbl.setToolTip(attr)
            lbl.setWordWrap(True)
            lbl.setFont(ui_font(TypeSize.CODE))
            lbl.setStyleSheet(ss_field_label())
            grid.addWidget(lbl, row, 0)
            if val in ('true', 'false') or attr in BOOL_ATTRS:
                editor = _bool_combo(val)
                editor.currentIndexChanged.connect(lambda _, e=elem, a=attr, w=editor: self._set_attr(e, a, w.currentData()))
            else:
                editor = QLineEdit(val)
                configure_input(editor, height=Size.CONTROL, monospace=True)
                if elem.tag == XML_DECORATOR and attr in (ATTR_ACT_ID, ATTR_ACT_KIND):
                    editor.setReadOnly(True)
                    editor.setToolTip(ui_text('spm_identity_in_info'))
                self._pending_edits.append((editor, elem, attr))
                editor.editingFinished.connect(lambda e=elem, a=attr, w=editor: self._set_attr(e, a, w.text()))
            grid.addWidget(editor, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card

    def _decorator_children(self, elem):
        card = _card_frame()
        layout = _card_layout(card)
        layout.addWidget(_title_row(ui_text('spm_children_title'), ui_text('spm_children_hint'), "fa6s.sitemap"))
        children = [child for child in elem if isinstance(child.tag, str)]
        if not children:
            empty = QLabel(ui_text('spm_no_children'))
            empty.setFont(ui_font(TypeSize.TITLE))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(ss_dim_label())
            layout.addWidget(empty)
            return card
        for child in children:
            row = QLabel(child.tag + ": " + ", ".join(f"{k}={v}" for k, v in list(child.attrib.items())[:4]))
            row.setFont(mono_font(TypeSize.CODE))
            row.setStyleSheet(ss_main_label())
            layout.addWidget(row)
        return card

    def _set_attr(self, elem, attr, value):
        if value != elem.get(attr, ''):
            elem.set(attr, value)
            self.changed.emit()

    def commit_pending(self):
        for editor, elem, attr in self._pending_edits:
            self._set_attr(elem, attr, editor.text())
        return True

    def _sel_top_dec(self):
        items = self._tree.selectedItems()
        if not items:
            return None
        item = items[0]
        if item.parent() is not None:
            item = item.parent()
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _add_decorator(self):
        self._add_decorator_of_type(self._type_combo.currentText().strip())

    def _add_decorator_of_type(self, dtype):
        if self._root_elem is None:
            return
        if not dtype:
            return
        dec = ET.Element(XML_DECORATOR)
        dec.set('type', dtype)
        for k, v in DEC_DEFAULTS.get(dtype, {'path': f'{dtype}.xml'}).items():
            dec.set(k, v)
        dec.set(ATTR_ACT_ID,   self._actID)
        dec.set(ATTR_ACT_KIND, self._actKind)
        self._insert_decorator(dec)
        self._elems.append(dec)
        self._refresh_tree()
        self.changed.emit()

    def _insert_decorator(self, dec):
        root_children = list(self._root_elem)
        insert_at = len(root_children)
        for i, elem in enumerate(root_children):
            if elem.get(ATTR_ACT_ID, '') == self._actID and elem.get(ATTR_ACT_KIND, '') == self._actKind:
                insert_at = i + 1
        self._root_elem.insert(insert_at, dec)

    def _dup_decorator(self):
        dec = self._sel_top_dec()
        if dec is None or self._root_elem is None:
            return
        new_dec = copy.deepcopy(dec)
        self._root_elem.append(new_dec)
        self._elems.append(new_dec)
        self._refresh_tree()
        self.changed.emit()

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
        self._show_empty_detail()
        self.changed.emit()

    def _add_child_item(self):
        self.commit_pending()
        dec = self._sel_top_dec()
        if dec is None:
            return
        prototype = next((child for child in dec if isinstance(child.tag, str)), None)
        if prototype is not None:
            child = copy.deepcopy(prototype)
            dec.append(child)
        elif dec.get('type') == 'startAnmSelect':
            child = ET.SubElement(dec, XML_SELECT_ANM_LIST)
            for k, v in [(ATTR_START_ANM_ID, '0'), (ATTR_CHECK_GROUP_EX1, 'false'),
                         (ATTR_GROUP_EX1_ON, 'false'), (ATTR_CHECK_BEFORE_ANM, 'false'),
                         (ATTR_BEFORE_ANM_ID, '0'), (ATTR_ATTACK_FLAG, '1'), (ATTR_HIGH_FLAG, '3')]:
                child.set(k, v)
        else:
            return
        self._refresh_tree()
        self.changed.emit()

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
        self._show_empty_detail()
        self.changed.emit()


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
        self._dirty = False
        self._names = SpmNames()
        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        root_l = QVBoxLayout(self)
        configure_layout(root_l, LayoutRole.ROOT)

        root_l.addWidget(self._make_toolbar())

        sep = EditorSeparator(accent=True)


        root_l.addWidget(sep)

        sp = QSplitter(Qt.Orientation.Horizontal)
        sp.setStyleSheet(ss_bg_dark())
        sp.addWidget(self._make_left_panel())
        sp.addWidget(self._make_right_panel())
        sp.setSizes([230, 1000])
        root_l.addWidget(sp, 1)

    def _make_toolbar(self):
        bar = EditorToolbar()
        bl = bar.content_layout

        self._open_btn = QPushButton(ui_text("btn_open_file"))
        configure_button(self._open_btn, accent=True)
        self._open_btn.clicked.connect(self._open_file)
        self._open_btn.setProperty("designAction", 'open')
        bl.addWidget(self._open_btn)

        self._save_btn = QPushButton(ui_text("btn_save_file"))
        self._save_btn.setEnabled(False)
        configure_button(self._save_btn, accent=True)
        self._save_btn.clicked.connect(self._save_file)
        bl.addWidget(self._save_btn)

        self._path_lbl = QLabel(ui_text("xfa_no_file"))

        configure_file_label(self._path_lbl)
        bl.addWidget(self._path_lbl)
        bl.addStretch()
        return bar

    def _make_left_panel(self):
        sidebar, sl = _make_sidebar(230)

        self._move_search = QLineEdit()
        configure_search(self._move_search)
        self._move_search.setClearButtonEnabled(True)
        configure_search(self._move_search)
        self._move_search.textChanged.connect(self._filter_moves)
        sl.addWidget(self._move_search)

        btn_frame, self._add_move_btn, self._dup_move_btn, self._del_move_btn = _sidebar_buttons_row()
        self._add_move_btn.clicked.connect(self._add_move)
        self._add_move_btn.setProperty("designAction", 'new')
        self._dup_move_btn.clicked.connect(self._dup_move)
        self._dup_move_btn.setProperty("designAction", 'duplicate')
        self._del_move_btn.clicked.connect(self._del_move)
        self._del_move_btn.setProperty("designAction", 'delete')
        self._add_move_btn.setEnabled(False)
        self._dup_move_btn.setEnabled(False)
        self._del_move_btn.setEnabled(False)
        sl.addWidget(btn_frame)

        self._move_scroll, self._move_list_widget, self._move_list_layout = _sidebar_scroll()
        sl.addWidget(self._move_scroll)
        return sidebar

    def _make_right_panel(self):
        ph = QWidget()
        ph.setStyleSheet(ss_bg_dark())
        pl = QVBoxLayout(ph)
        configure_layout(pl, LayoutRole.PAGE)
        pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_card = make_empty_state(
            ph,
            title=ui_text("no_file_loaded"),
            text=ui_text("ui_spm_open_a_spm_xfbin_file_to_begin_editing"),
            icon_name="fa6s.list-ol",
        )
        pl.addWidget(ph_card, 0, Qt.AlignmentFlag.AlignCenter)

        self._tabs = QTabWidget()
        self._tabs.setFont(ui_font(TypeSize.LABEL))
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(ss_tab_widget())

        self._info_form = _MoveInfoTab()
        self._info_form.changed.connect(self._on_info_changed)
        self._info_form.on_edit = self._edit_move_attribute
        self._tabs.addTab(self._info_form, ui_text("ui_spm_move_info"))
        self._tabs.setTabIcon(0, qta.icon("fa6s.circle-info", color=P["accent"]))

        self._cmd_tab = _CommandsTab()
        self._cmd_tab.entry_created.connect(self._on_entry_created)
        self._cmd_tab.changed.connect(self._mark_dirty)
        self._tabs.addTab(self._cmd_tab, ui_text("ui_spm_commands"))
        self._tabs.setTabIcon(1, qta.icon("fa6s.terminal", color=P["accent"]))

        self._dec_tab = _DecoratorsTab()
        self._dec_tab.changed.connect(self._mark_dirty)
        self._tabs.addTab(self._dec_tab, ui_text("ui_spm_decorators"))
        self._tabs.setTabIcon(2, qta.icon("fa6s.wand-magic-sparkles", color=P["accent"]))

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
        self._load(path)

    def _load(self, path):
        if self._dirty:
            if QMessageBox.question(self, ui_text('dlg_title_warning'), ui_text('spm_discard'),
                                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
                return
        create_backup_on_open(path)
        try:
            raw, result = parse_spm_xfbin(path)
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=e))
            return

        self._info_form.load(None)
        self._cmd_tab.load(None, None, '', '')
        self._dec_tab.load([], None, '', '')
        self._raw      = raw
        self._result   = result
        self._filepath = path
        self._moves    = get_moves(result['root'])
        self._dirty = False
        self._cur_idx = -1
        self._names = SpmNames(path)
        self._info_form.names = self._names
        self._move_search.clear()

        set_file_label(self._path_lbl, path)
        self._save_btn.setEnabled(False)
        self._add_move_btn.setEnabled(True)
        self._dup_move_btn.setEnabled(True)
        self._del_move_btn.setEnabled(True)
        self._right_stack.setCurrentIndex(1)
        self._refresh_move_list()

    def _save_file(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._result is None:
            return
        if not self._commit_pending():
            return
        try:
            save_spm_xfbin(save_path, self._raw, self._result)
            with open(save_path, 'rb') as stream:
                self._raw = bytearray(stream.read())
            self._result['_tree_signature'] = ET.tostring(self._result['root'], encoding='utf-8')
            commit_save_path(self, save_path)
            self._dirty = False
            self._save_btn.setEnabled(False)
            set_file_label(self._path_lbl, save_path)
        except Exception as e:
            QMessageBox.critical(self, ui_text('ui_assist_save_error'), ui_text('ui_spm_save_failed_value', p0=e))

    def _mark_dirty(self):
        self._dirty = True
        self._save_btn.setEnabled(True)
        if self._filepath:
            set_file_label(self._path_lbl, self._filepath, dirty=True)

    def _commit_pending(self):
        return self._info_form.commit_pending() and self._cmd_tab.commit_pending() and self._dec_tab.commit_pending()

    def _on_info_changed(self):
        self._mark_dirty()
        for button, move in self._move_btns:
            labels = button.findChildren(QLabel)
            if len(labels) < 2:
                continue
            original = move['spm_elem'].get('name', '')
            name = self._names.display(original)
            labels[0].setText(labels[0].fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 200))
            labels[0].setToolTip(name + '\n' + original)
            labels[1].setText(f"{move[ATTR_ACT_ID]} · {move[ATTR_ACT_KIND]}")
        self._filter_moves()

    def _edit_move_attribute(self, move, attr, value):
        elem = move['spm_elem']
        if attr in (ATTR_ACT_ID, ATTR_ACT_KIND):
            aid = value if attr == ATTR_ACT_ID else move[ATTR_ACT_ID]
            kind = value if attr == ATTR_ACT_KIND else move[ATTR_ACT_KIND]
            limit = ACTION_LIMITS.get(kind)
            if limit is not None:
                try:
                    valid = 1 <= int(aid) <= limit
                except ValueError:
                    valid = False
                if not valid:
                    QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('spm_action_limit', kind=kind, limit=limit))
                    return False
            if any(m is not move and (m[ATTR_ACT_ID], m[ATTR_ACT_KIND]) == (aid, kind) for m in self._moves):
                QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('spm_duplicate_id', id=aid, kind=kind))
                return False
            for linked in (elem, move['entry_elem'], *move['decorator_elems']):
                if linked is not None:
                    linked.set(attr, value)
            move[attr] = value
            self._cmd_tab._actID, self._cmd_tab._actKind = move[ATTR_ACT_ID], move[ATTR_ACT_KIND]
            self._dec_tab._actID, self._dec_tab._actKind = move[ATTR_ACT_ID], move[ATTR_ACT_KIND]
        else:
            elem.set(attr, value)
        return True

    # Move list

    def _refresh_move_list(self, keep_idx=None):
        _clear_layout(self._move_list_layout)
        self._move_btns = []
        for m in self._moves:
            btn = self._make_move_btn(m)
            self._move_list_layout.insertWidget(self._move_list_layout.count(), btn)
            self._move_btns.append((btn, m))
        self._move_list_layout.addStretch()
        self._filter_moves()

        target = keep_idx if (keep_idx is not None and 0 <= keep_idx < len(self._moves)) \
                 else (0 if self._moves else -1)
        if target >= 0:
            self._select_move(self._moves[target])
        else:
            self._cur_idx = -1
            self._info_form.load(None)
            self._cmd_tab.load(None, None, '', '')
            self._dec_tab.load([], None, '', '')

    def _make_move_btn(self, move_dict):
        original = move_dict['spm_elem'].get('name', '?')
        name = self._names.display(original)
        aid  = move_dict[ATTR_ACT_ID]
        btn = EditorListRow()


        bl = btn.content_layout


        name_lbl = btn.add_title(name)
        name_lbl.setTextFormat(Qt.TextFormat.PlainText)


        name_lbl.setToolTip(name + "\n" + original)
        name_lbl.setText(name_lbl.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 200))


        id_lbl = btn.add_subtitle(f'{aid} · {move_dict[ATTR_ACT_KIND]}')


        btn.clicked.connect(lambda _, m=move_dict: self._select_move(m))
        return btn

    def _filter_moves(self):
        q = self._move_search.text().lower()
        for btn, m in self._move_btns:
            original = m['spm_elem'].get('name', '')
            name = self._names.display(original).casefold()
            aid = m[ATTR_ACT_ID].lower()
            haystack = ' '.join((name, original.casefold(), aid, m[ATTR_ACT_KIND], m['spm_elem'].get('commandListNum', '')))
            btn.setVisible(all(word in haystack for word in q.casefold().split()))

    def _select_move(self, move_dict):
        if not self._commit_pending():
            return
        self._cur_idx = self._moves.index(move_dict) if move_dict in self._moves else -1
        for btn, m in self._move_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(m is move_dict)))
        self._info_form.load(move_dict)
        self._cmd_tab.load(
            move_dict['entry_elem'], self._result['root'],
            move_dict[ATTR_ACT_ID], move_dict[ATTR_ACT_KIND])
        self._dec_tab.load(
            move_dict['decorator_elems'], self._result['root'],
            move_dict[ATTR_ACT_ID], move_dict[ATTR_ACT_KIND])

    def _on_entry_created(self, entry_elem):
        if 0 <= self._cur_idx < len(self._moves):
            self._moves[self._cur_idx]['entry_elem'] = entry_elem
            self._mark_dirty()

    # Move CRUD

    def _add_move(self):
        if self._result is None:
            return
        if not self._commit_pending():
            return
        next_id = next_action_id(self._moves, 'spm')
        if next_id is None:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('spm_no_free_id', kind='spm', limit=45))
            return

        elem = ET.SubElement(self._result['root'], XML_SPECIAL_MOVE)
        for k, v in [
            ('name', ui_text('ui_spm_new_move')), ('view', '0'), ('type', 'normal'),
            ('path', 'normal.xml'), (ATTR_COMMAND_LIST_NUM, '-1'),
            (ATTR_ACT_ID, next_id), (ATTR_ACT_KIND, 'spm'),
            (ATTR_START_ANM_ID, '0'), (ATTR_START_SET_DIRC, 'true'),
            (ATTR_IGNORE_END_POS_TYPE, 'false'), (ATTR_WAIT_END_LAND, 'false'),
            (ATTR_USE_CANCEL_EFFECT, 'true'), (ATTR_DISABLE_MISS_HIT_CANCEL, 'false'),
            (ATTR_ACT_PRIORITY, '6'),
        ]:
            elem.set(k, v)

        m = {'actID': next_id, 'actKind': 'spm',
             'spm_elem': elem, 'entry_elem': None, 'decorator_elems': []}
        self._moves.append(m)
        self._move_search.clear()
        self._refresh_move_list(keep_idx=len(self._moves) - 1)
        self._mark_dirty()

    def _dup_move(self):
        if self._cur_idx < 0 or self._cur_idx >= len(self._moves) or self._result is None:
            return
        src = self._moves[self._cur_idx]
        if not self._commit_pending():
            return
        next_id = next_action_id(self._moves, src[ATTR_ACT_KIND])
        if next_id is None:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('spm_no_free_id', kind=src[ATTR_ACT_KIND], limit=ACTION_LIMITS.get(src[ATTR_ACT_KIND], '?')))
            return

        new_elem = copy.deepcopy(src['spm_elem'])
        new_elem.set(ATTR_ACT_ID, next_id)
        # Preserve the source name so the translated variant remains identifiable.
        self._result['root'].append(new_elem)

        new_entry = None
        if src['entry_elem'] is not None:
            new_entry = copy.deepcopy(src['entry_elem'])
            new_entry.set(ATTR_ACT_ID, next_id)
            self._result['root'].append(new_entry)

        new_decs = []
        for dec in src['decorator_elems']:
            new_dec = copy.deepcopy(dec)
            new_dec.set(ATTR_ACT_ID, next_id)
            self._result['root'].append(new_dec)
            new_decs.append(new_dec)

        m = {ATTR_ACT_ID: next_id, ATTR_ACT_KIND: src[ATTR_ACT_KIND],
             'spm_elem': new_elem, 'entry_elem': new_entry, 'decorator_elems': new_decs}
        self._moves.append(m)
        self._move_search.clear()
        self._refresh_move_list(keep_idx=len(self._moves) - 1)
        self._mark_dirty()

    def _del_move(self):
        row = self._cur_idx
        if row < 0 or row >= len(self._moves) or self._result is None:
            return
        if not self._commit_pending():
            return
        m    = self._moves[row]
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'), ui_text('msg_confirm_delete_item', name=self._names.display(m['spm_elem'].get('name', ''))), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
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
