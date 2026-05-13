"""editors/projectile_editor.py  –  Editor for 0xxx00_x.xfbin projectile/skill files."""

import copy
import os
import re
import threading
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_scrollarea, ss_scrollarea_transparent,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.projectile_parser import parse_projectile_xfbin, save_projectile_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


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


_DEFAULT_SKILL_XML = (
    '<?xml version="1.0" encoding="Shift_JIS"?>\r\n'
    '<Skill id="new_skill" type="SKILL_TYPE_NORMAL"></Skill>'
)

XML_DETAILS = 'Details'
XML_ACTIONS = 'Actions'
XML_ACTION = 'Action'
XML_HIT = 'Hit'
XML_VELOCITY = 'Velocity'
XML_SKILL_ATTACK = 'SkillAttack'

ATTR_SHAPE = 'Shape'
ATTR_HIT_RADIUS = 'hitRadius'
ATTR_AMOUNT = 'Amount'
ATTR_KNOCK_BACK = 'KnockBack'
ATTR_GUARD_DAMAGE = 'GuardDamage'
ATTR_STRENGTH = 'Strength'
ATTR_HH_GAUGE = 'HHGauge'
ATTR_STUN_DAMAGE = 'StunDamage'
ATTR_HIT_STOP = 'HitStop'
ATTR_REAC_XY = 'ReacXY'
ATTR_REAC_Z = 'ReacZ'
ATTR_DMG_ID = 'dmgId'

# Fields per Action card: (label, xml_tag, xml_attr)
# xml_tag=None means attribute lives directly on <Action>
_ACTION_FIELDS = [
    (ui_text("ui_projectile_action_id"),  None,           'id'),
    (ui_text("ui_dlcinfoparam_type"),       None,           'type'),
    (ui_text("ui_projectile_hit_shape"),  XML_HIT,          ATTR_SHAPE),
    (ui_text("ui_projectile_hit_radius"), XML_HIT,          ATTR_HIT_RADIUS),
    (ui_text("ui_projectile_velocity"),   XML_VELOCITY,     'value'),
    (ui_text("skill_param_damage"),       XML_SKILL_ATTACK, ATTR_AMOUNT),
    (ui_text("ui_projectile_knock_back"), XML_SKILL_ATTACK, ATTR_KNOCK_BACK),
    (ui_text("ui_projectile_guard_dmg"),  XML_SKILL_ATTACK, ATTR_GUARD_DAMAGE),
    (ui_text("ui_projectile_strength"),   XML_SKILL_ATTACK, ATTR_STRENGTH),
    (ui_text("ui_projectile_hh_gauge"),   XML_SKILL_ATTACK, ATTR_HH_GAUGE),
    (ui_text("ui_projectile_stun"),       XML_SKILL_ATTACK, ATTR_STUN_DAMAGE),
    (ui_text("ui_projectile_hit_stop"),   XML_SKILL_ATTACK, ATTR_HIT_STOP),
    (ui_text("ui_projectile_reacxy"),     XML_SKILL_ATTACK, ATTR_REAC_XY),
    (ui_text("ui_projectile_reacz"),      XML_SKILL_ATTACK, ATTR_REAC_Z),
    (ui_text("ui_projectile_dmg_id"),     XML_SKILL_ATTACK, ATTR_DMG_ID),
]
_CARD_COLS = 5


# Skill Table Widget

class _SkillTable(QWidget):
    xml_changed      = pyqtSignal(str)
    skill_id_changed = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None):
        super().__init__(parent)
        self.t = lang_func or (lambda k, **kw: k)
        self._root_el     = None
        self._blocked     = False
        self._action_cards = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Skill Properties Card
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        card_inner = QWidget(card)
        card_inner.setStyleSheet("background: transparent;")
        card_grid = QGridLayout(card_inner)
        card_grid.setContentsMargins(16, 12, 16, 12)
        card_grid.setHorizontalSpacing(16)
        card_grid.setVerticalSpacing(4)
        card_main = QVBoxLayout(card)
        card_main.setContentsMargins(0, 0, 0, 0)
        card_main.addWidget(card_inner)

        self._id_fld = self._type_fld = self._det_fld = None
        for col, label_text in enumerate((ui_text("ui_projectile_skill_id"), ui_text("ui_dlcinfoparam_type"), ui_text("ui_projectile_details"))):
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)
            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(lbl)
            fld = QLineEdit()
            fld.setFixedHeight(30)
            fld.setFont(QFont("Consolas", 13))
            fld.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
                f"QLineEdit:focus {{ border: 1px solid {P['accent']}; }}"
            )
            fl.addWidget(fld)
            card_grid.addWidget(f, 0, col)
            card_grid.setColumnStretch(col, 1)
            if col == 0:
                self._id_fld = fld
            elif col == 1:
                self._type_fld = fld
            else:
                self._det_fld = fld

        root.addWidget(card)

        # Add Action button
        add_bar = QWidget()
        add_bar.setStyleSheet("background: transparent;")
        add_bar_layout = QHBoxLayout(add_bar)
        add_bar_layout.setContentsMargins(20, 8, 12, 4)
        add_bar_layout.setSpacing(4)

        self._add_btn = QPushButton(self.t("btn_new"))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(QFont("Segoe UI", 10))
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_action)
        add_bar_layout.addWidget(self._add_btn)
        add_bar_layout.addStretch()
        root.addWidget(add_bar)

        # Action cards scroll area
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_scroll.setStyleSheet(ss_scrollarea())

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 4, 0, 8)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()
        self._cards_scroll.setWidget(self._cards_widget)
        root.addWidget(self._cards_scroll, 1)

        self._id_fld.textChanged.connect(self._on_header_changed)
        self._type_fld.textChanged.connect(self._on_header_changed)
        self._det_fld.textChanged.connect(self._on_header_changed)

    # Public

    def load(self, xml_text):
        self._blocked = True
        self._id_fld.blockSignals(True)
        self._type_fld.blockSignals(True)
        self._det_fld.blockSignals(True)

        try:
            stripped = re.sub(r'<\?xml[^>]*\?>\s*', '', xml_text)
            self._root_el = ET.fromstring(stripped.encode('utf-8', errors='replace'))
        except ET.ParseError:
            self._root_el = None
            self._id_fld.blockSignals(False)
            self._type_fld.blockSignals(False)
            self._det_fld.blockSignals(False)
            self._blocked = False
            self._rebuild_cards()
            return

        self._id_fld.setText(self._root_el.get('id', ''))
        self._type_fld.setText(self._root_el.get('type', ''))
        det_el = self._root_el.find(XML_DETAILS)
        self._det_fld.setText(det_el.get('text', '') if det_el is not None else '')

        self._id_fld.blockSignals(False)
        self._type_fld.blockSignals(False)
        self._det_fld.blockSignals(False)
        self._blocked = False

        self._rebuild_cards()

    # Card building

    def _rebuild_cards(self):
        self._blocked = True
        _clear_layout(self._cards_layout)
        self._action_cards = []

        if self._root_el is not None:
            for idx, action_el in enumerate(list(self._root_el.iter(XML_ACTION))):
                card = self._make_action_card(action_el, idx)
                self._cards_layout.addWidget(card)
                self._action_cards.append(card)

        self._cards_layout.addStretch()
        self._blocked = False

    def _make_action_card(self, action_el, idx):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 12)
        card_layout.setSpacing(6)

        # Card header: "Action N" + inline Dup/Delete
        hdr = QWidget()
        hdr.setStyleSheet("background: transparent;")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(0, 0, 0, 0)
        hdr_layout.setSpacing(4)

        num_lbl = QLabel(ui_text("ui_projectile_action_value", p0=idx + 1))
        num_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        num_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        hdr_layout.addWidget(num_lbl)
        hdr_layout.addStretch()

        btn_font = QFont("Segoe UI", 9)

        dup_btn = QPushButton(self.t("btn_duplicate"))
        dup_btn.setFixedHeight(24)
        dup_btn.setFont(btn_font)
        dup_btn.setStyleSheet(ss_btn())
        dup_btn.clicked.connect(lambda checked=False, el=action_el: self._dup_action_el(el))
        hdr_layout.addWidget(dup_btn)

        del_btn = QPushButton(self.t("btn_delete"))
        del_btn.setFixedHeight(24)
        del_btn.setFont(btn_font)
        del_btn.setStyleSheet(ss_btn(danger=True))
        del_btn.clicked.connect(lambda checked=False, el=action_el: self._del_action_el(el))
        hdr_layout.addWidget(del_btn)

        card_layout.addWidget(hdr)

        # Fields grid
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        for i, (label_text, tag, attr) in enumerate(_ACTION_FIELDS):
            row, col = divmod(i, _CARD_COLS)

            if tag is None:
                value = action_el.get(attr, '')
            else:
                sub_el = action_el.find(tag)
                value = sub_el.get(attr, '') if sub_el is not None else ''

            f = QWidget()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)

            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(lbl)

            fld = QLineEdit()
            fld.setFixedHeight(30)
            fld.setFont(QFont("Consolas", 13))
            fld.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
                f"QLineEdit:focus {{ border: 1px solid {P['accent']}; }}"
            )
            fld.setText(value)
            fld.textChanged.connect(self._make_field_updater(action_el, tag, attr))
            fl.addWidget(fld)

            grid.addWidget(f, row, col)
            grid.setColumnStretch(col, 1)

        card_layout.addWidget(inner)
        return card

    def _make_field_updater(self, action_el, tag, attr):
        def updater(val):
            if self._blocked:
                return
            if tag is None:
                action_el.set(attr, val)
            else:
                el = action_el.find(tag)
                if el is None:
                    el = ET.SubElement(action_el, tag)
                el.set(attr, val)
            self._emit_xml()
        return updater

    # Signal handlers

    def _on_header_changed(self):
        if self._blocked or self._root_el is None:
            return
        self._root_el.set('id', self._id_fld.text())
        self._root_el.set('type', self._type_fld.text())
        det_text = self._det_fld.text()
        det_el = self._root_el.find(XML_DETAILS)
        if det_text:
            if det_el is None:
                det_el = ET.Element(XML_DETAILS)
                self._root_el.insert(0, det_el)
            det_el.set('text', det_text)
        self.skill_id_changed.emit(self._id_fld.text())
        self._emit_xml()

    def _emit_xml(self):
        if self._root_el is not None:
            self.xml_changed.emit(self._serialize())

    def _serialize(self) -> str:
        body = ET.tostring(self._root_el, encoding='unicode')
        return '<?xml version="1.0" encoding="Shift_JIS"?>\r\n' + body

    # Add / Dup / Delete actions

    def _add_action(self):
        if self._root_el is None:
            return
        all_actions = list(self._root_el.iter(XML_ACTION))
        new_id = str(len(all_actions))
        container = self._root_el.find(XML_ACTIONS) or self._root_el
        new_el = ET.SubElement(container, XML_ACTION)
        new_el.set('id', new_id)
        new_el.set('type', 'SKILL_ACTION_TYPE_ARROW')
        self._rebuild_cards()
        self._emit_xml()
        QTimer.singleShot(50, lambda: self._cards_scroll.verticalScrollBar().setValue(
            self._cards_scroll.verticalScrollBar().maximum()
        ))

    def _dup_action_el(self, action_el):
        if self._root_el is None:
            return
        parent_map = {c: p for p in self._root_el.iter() for c in p}
        new_el = copy.deepcopy(action_el)
        parent_map.get(action_el, self._root_el).append(new_el)
        self._rebuild_cards()
        self._emit_xml()

    def _del_action_el(self, action_el):
        if self._root_el is None:
            return
        parent_map = {c: p for p in self._root_el.iter() for c in p}
        parent_map.get(action_el, self._root_el).remove(action_el)
        self._rebuild_cards()
        self._emit_xml()


# Main Editor

class ProjectileEditor(QWidget):
    _load_done_signal  = pyqtSignal(str, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or (lambda k, **kw: k)

        self._filepath      = None
        self._raw_data      = None
        self._chunks        = []
        self._cur_idx       = -1
        self._current_chunk = None
        self._dirty         = False
        self._skill_buttons = []

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        self._build_ui()

    # UI Construction

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

        open_btn = QPushButton(self.t("btn_open_file"))
        open_btn.setFixedHeight(TOOLBAR_BTN_H)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._load_file)
        tl.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)

        self._file_lbl = QLabel(self.t("no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        tl.addWidget(self._file_lbl)

        tl.addStretch()
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        # Main area: sidebar + editor (always visible)
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        left_frame = QFrame()
        left_frame.setFixedWidth(260)
        left_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        lf_layout = QVBoxLayout(left_frame)
        lf_layout.setContentsMargins(8, 8, 8, 4)
        lf_layout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        self._search_entry.textChanged.connect(self._filter_skill_list)
        lf_layout.addWidget(self._search_entry)

        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._skill_add_btn = QPushButton(self.t("btn_new"))
        self._skill_add_btn.setFixedHeight(28)
        self._skill_add_btn.setFont(btn_font)
        self._skill_add_btn.setEnabled(False)
        self._skill_add_btn.setStyleSheet(ss_btn())
        self._skill_add_btn.clicked.connect(self._add_skill)
        actions_layout.addWidget(self._skill_add_btn, 1)

        self._skill_dup_btn = QPushButton(self.t("btn_duplicate"))
        self._skill_dup_btn.setFixedHeight(28)
        self._skill_dup_btn.setFont(btn_font)
        self._skill_dup_btn.setEnabled(False)
        self._skill_dup_btn.setStyleSheet(ss_btn())
        self._skill_dup_btn.clicked.connect(self._dup_skill)
        actions_layout.addWidget(self._skill_dup_btn, 1)

        self._skill_del_btn = QPushButton(self.t("btn_delete"))
        self._skill_del_btn.setFixedHeight(28)
        self._skill_del_btn.setFont(btn_font)
        self._skill_del_btn.setEnabled(False)
        self._skill_del_btn.setStyleSheet(ss_btn(danger=True))
        self._skill_del_btn.clicked.connect(self._del_skill)
        actions_layout.addWidget(self._skill_del_btn, 1)

        lf_layout.addWidget(actions_frame)

        self._skill_scroll = QScrollArea()
        self._skill_scroll.setWidgetResizable(True)
        self._skill_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._skill_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._skill_list_widget = QWidget()
        self._skill_list_widget.setStyleSheet("background-color: transparent;")
        self._skill_list_layout = QVBoxLayout(self._skill_list_widget)
        self._skill_list_layout.setContentsMargins(0, 0, 0, 0)
        self._skill_list_layout.setSpacing(1)
        self._skill_list_layout.addStretch()
        self._skill_scroll.setWidget(self._skill_list_widget)
        lf_layout.addWidget(self._skill_scroll)

        main_layout.addWidget(left_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Right: placeholder OR skill editor
        right_frame = QFrame()
        right_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_dark']}; }}")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._placeholder = QLabel(ui_text("ui_projectile_open_a_projectile_xfbin_file_to_begin_editing"))
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        right_layout.addWidget(self._placeholder, 1)

        self._skill_table = _SkillTable(lang_func=self.t)
        self._skill_table.setVisible(False)
        self._skill_table.xml_changed.connect(self._on_table_xml_changed)
        self._skill_table.skill_id_changed.connect(self._on_skill_id_changed)
        right_layout.addWidget(self._skill_table, 1)

        main_layout.addWidget(right_frame, 1)
        root.addWidget(main, 1)

    # File I/O

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_projectile_open_projectile_xfbin"), game_files_dialog_dir(target_patterns="*_x.xfbin"),
            "Projectile files (*_x.xfbin *.xfbin);;All files (*.*)"
        )
        if path:
            create_backup_on_open(path)
            self._start_load(path)

    def _start_load(self, path):
        self._filepath = path
        name = os.path.basename(path)
        self._file_lbl.setText(ui_text("ui_customcardparam_value_value", p0=self.t('loading'), p1=name))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")

        def _worker():
            try:
                raw, chunks = parse_projectile_xfbin(path)
                self._load_done_signal.emit(path, raw, chunks)
            except Exception as exc:
                import traceback
                self._load_error_signal.emit(f"{exc}\n{traceback.format_exc()}")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, path, raw, chunks):
        self._raw_data      = raw
        self._chunks        = chunks
        self._cur_idx       = -1
        self._current_chunk = None
        self._dirty         = False

        set_file_label(self._file_lbl, path)

        self._placeholder.setVisible(False)
        self._skill_table.setVisible(True)

        self._save_btn.setEnabled(True)
        self._skill_add_btn.setEnabled(True)
        self._skill_dup_btn.setEnabled(True)
        self._skill_del_btn.setEnabled(True)

        self._populate_skill_list()

    def _on_load_error(self, msg):
        self._placeholder.setVisible(True)
        self._skill_table.setVisible(False)
        self._file_lbl.setText(self.t("no_file_loaded"))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), msg)

    # Skill list

    def _clear_skill_list(self):
        _clear_layout(self._skill_list_layout)
        self._skill_list_layout.addStretch()

    def _populate_skill_list(self):
        self._clear_skill_list()
        self._skill_buttons = []
        for chunk in self._chunks:
            btn = self._make_skill_button(chunk)
            self._skill_list_layout.insertWidget(
                self._skill_list_layout.count() - 1, btn
            )
            self._skill_buttons.append((btn, chunk))
        if self._chunks:
            self._select_skill(self._chunks[0])

    def _make_skill_button(self, chunk):
        btn = QPushButton()
        btn.setFixedHeight(36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; border-radius: 6px; "
            f"text-align: left; padding: 0px; border: none; }} "
            f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
        )
        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 4, 10, 4)
        btn_layout.setSpacing(0)

        name_lbl = QLabel(chunk['skill_id'])
        name_lbl.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(name_lbl)

        btn.clicked.connect(lambda checked=False, c=chunk: self._select_skill(c))
        return btn

    def _filter_skill_list(self):
        query = self._search_entry.text().lower()
        for btn, chunk in self._skill_buttons:
            btn.setVisible(query in chunk['skill_id'].lower())

    def _select_skill(self, chunk):
        self._current_chunk = chunk
        self._cur_idx = self._chunks.index(chunk)

        for btn, c in self._skill_buttons:
            try:
                if c is chunk:
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

        self._skill_table.load(chunk['xml_text'])

    # Table ↔ chunk sync

    def _on_table_xml_changed(self, new_xml):
        if 0 <= self._cur_idx < len(self._chunks):
            norm = new_xml.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
            skill_close = norm.rfind('</Skill>')
            if skill_close >= 0:
                norm = norm[:skill_close + 8]
            self._chunks[self._cur_idx]['xml_text'] = norm
            self._mark_dirty()

    def _on_skill_id_changed(self, new_id):
        if 0 <= self._cur_idx < len(self._chunks):
            chunk = self._chunks[self._cur_idx]
            chunk['skill_id'] = new_id
            for btn, c in self._skill_buttons:
                if c is chunk:
                    labels = btn.findChildren(QLabel)
                    if labels:
                        labels[0].setText(new_id)
                    break

    # Add / Dup / Delete skills

    def _add_skill(self):
        if self._chunks is None:
            return
        new_chunk = {
            'skill_id':  'new_skill',
            'xml_start': 0,
            'xml_end':   0,
            'xml_text':  _DEFAULT_SKILL_XML,
        }
        self._chunks.append(new_chunk)
        self._populate_skill_list()
        self._select_skill(new_chunk)
        self._mark_dirty()

    def _dup_skill(self):
        if not self._chunks or self._current_chunk is None:
            return
        new_chunk = copy.deepcopy(self._current_chunk)
        self._chunks.append(new_chunk)
        self._populate_skill_list()
        self._select_skill(new_chunk)
        self._mark_dirty()

    def _del_skill(self):
        if not self._chunks or self._current_chunk is None:
            return
        if len(self._chunks) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_projectile_cannot_delete_the_last_skill"))
            return
        name = self._current_chunk['skill_id']
        result = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"), ui_text("ui_projectile_delete_skill_value", p0=name)
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._chunks.remove(self._current_chunk)
        self._current_chunk = None
        self._cur_idx = -1
        self._populate_skill_list()
        self._mark_dirty()

    # Save

    def _save_file(self):
        if not self._chunks:
            return
        if self._filepath:
            self._do_save(self._filepath)

    def _do_save(self, path):
        try:
            save_projectile_xfbin(path, self._raw_data, self._chunks)
            self._filepath = path
            self._dirty    = False
            set_file_label(self._file_lbl, path)
            self._raw_data, _ = parse_projectile_xfbin(path)
        except Exception as exc:
            import traceback
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_ASBR-Tools_value_value", p0=exc, p1=traceback.format_exc()))

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            set_file_label(self._file_lbl, self._filepath, dirty=True)
