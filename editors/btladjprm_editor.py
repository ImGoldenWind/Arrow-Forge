"""editors/btladjprm_editor.py  –  Editor for btladjprm.bin.xfbin (Battle Adjust Params)."""

import os

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QFileDialog, QMessageBox,
    QLineEdit,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_search, ss_file_label, ss_section_label,
    ss_panel, ss_scrollarea, ss_placeholder, ss_dim_label, ss_input,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.btladjprm_parser import parse_btladjprm_xfbin, save_btladjprm_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir

# Parameter groups

_PARAM_META = {
    "DAMAGERATE_SKILL_GUARDHIT":                   ("", 0),
    "DAMAGERATE_SUPPORT_SKILL":                    ("", 0),
    "DAMAGERATE_SUPPORT_SKILL_TWOMANCELL":         ("", 0),
    "DAMAGERATE_SUPPORT_COVERING_FIRE":            ("", 0),
    "DAMAGERATE_SUPPORT_COVERING_FIRE_TWOMANCELL": ("", 0),
    "DAMAGERATE_SUPPORT_COMBO_JOIN":               ("", 0),
    "DAMAGERATE_SUPPORT_COMBO_JOIN_TWOMANCELL":    ("", 0),
    "DAMAGERATE_AT_DOWN":                          ("", 0),
    "RATE_DAMAGE_LIFE_TO_CHAKRA":                  ("", 0),
    "DAMAGE_VAL_CRASH_WALL":                       ("", 0),
    "DAMAGE_VAL_CRASH_GROUND":                     ("", 0),
    "DAMAGE_RATE_TEAMSKILL":                       ("", 0),
    "MANY_DAMAGE_SAVING_RATE":                     ("", 0),
    "GUARDBREAK_AUTO_RECOVER_FRAME":               ("", 1),
    "GUARDBREAK_RECOVER_SCORE":                    ("", 1),
    "ASLEEP_RECOVER_SCORE":                        ("", 1),
    "APL_HANDICAP_RATE_STEP":                      ("", 0),
    "LIFE_DYING":                                  ("", 0),
    "LIFE_NODEAD_MIN":                             ("", 0),
    "DAMAGE_LIMIT_FOR_ONE_COMBO":                  ("", 0),
    "GUARD_POW_MAX":                               ("", 1),
    "GUARD_POW_RECOVER_SPD":                       ("", 1),
    "GUARD_POW_MIN":                               ("", 1),
    "DAMAGE_RATE_LIFE_TO_GUARD":                   ("", 1),
    "HITSTOP_GUARD_BREAK":                         ("", 1),
    "GUARD_HIT_EFF_THRES3":                        ("", 1),
    "GUARD_HIT_EFF_THRES2":                        ("", 1),
    "COMBO_COUNTER_INTERVAL_MAX":                  ("", 0),
    "AWAKE_GAUGE_LENGTH":                          ("", 0),
    "WAIT_CHAKRA_LOAD_CLEAR":                      ("", 2),
    "WAIT_CHAKRA_LOAD_INTERVAL":                   ("", 2),
    "CHAKRA_USE_AT_CHAKRA_DASH":                   ("", 2),
    "CHAKRA_USE_AT_CHAKRA_PROJ":                   ("", 2),
    "CHAKRA_USE_AT_DODGE":                         ("", 2),
    "CHAKRA_RECOVER_AT_CHARGE":                    ("", 2),
    "CHAKRA_RECOVER_AUTO":                         ("", 2),
    "CHAKRA_LOST":                                 ("", 2),
    "CHAKRA_BALL_RECOVER":                         ("", 2),
    "CHAKRA_BALL_NUM":                             ("", 2),
    "CHAKRA_USE_RATE_AT_SPSKILL_MISS":             ("", 2),
    "CHAKRA_USE_RATE_AT_TEAMSKILL_MISS":           ("", 2),
    "SUPPORT_GAUGE_USE_NORMAL":                    ("", 3),
    "SUPPORT_GAUGE_RECOVER_SPD":                   ("", 3),
    "SUPPORT_GAUGE_RECOVER_SPD_TWOMANCELL":        ("", 3),
    "SUP_GAUGE_RECOVER_RATE_ATTACKTYPE":           ("", 3),
    "SUP_GAUGE_RECOVER_RATE_GUARDTYPE":            ("", 3),
    "SUP_GAUGE_RECOVER_RATE_BALANCETYPE":          ("", 3),
    "RATE_SUPPORT_DAMAGE_TO_TEAM_POW":             ("", 4),
    "TEAM_POW_MAX_KEEP_FRAME":                     ("", 4),
    "TEAM_POW_CALL":                               ("", 4),
    "TEAM_POW_CALL_AUTO":                          ("", 4),
    "TEAM_POW_FOLLOWATK":                          ("", 4),
    "TEAM_POW_FOLLOWATK_CHAIN":                    ("", 4),
    "TEAM_POW_SUPPORTDAMAGE":                      ("", 4),
    "DOWN_DAMAGE_COUNT_MAX":                       ("", 0),
    "FRAME_DOWN_COUNT":                            ("", 0),
    "CHAKRA_CHARGE_WAIT":                          ("", 2),
    "TEAM_SPSKILL_ATK_SPEED":                      ("", 5),
    "TEAM_SPSKILL_ATK_CHECK_TIME":                 ("", 5),
    "TEAM_SPSKILL_ATK_LOOP_TIME":                  ("", 5),
    "TEAM_SPSKILL_ATK_HOMING_END_TIME":            ("", 5),
    "TEAM_SPSKILL_ATK_DEG":                        ("", 5),
    "SUPPORT_LIFE_MAX":                            ("", 3),
    "SUPPORT_INJURED_WAIT_SEC":                    ("", 3),
    "TEAM_BONUS_COOPERATION_LV1":                  ("", 6),
    "TEAM_BONUS_COOPERATION_LV2":                  ("", 6),
    "TEAM_BONUS_COOPERATION_LV3":                  ("", 6),
    "TEAM_BONUS_COOPERATION_LV4":                  ("", 6),
    "TEAM_BONUS_COOPERATION_LV5":                  ("", 6),
    "TEAM_BONUS_COOPERATION_LV6":                  ("", 6),
    "TEAM_BONUS_SUPPORT_LV1":                      ("", 6),
    "TEAM_BONUS_SUPPORT_LV2":                      ("", 6),
    "TEAM_BONUS_SUPPORT_LV3":                      ("", 6),
    "TEAM_BONUS_SUPPORT_LV4":                      ("", 6),
    "TEAM_BONUS_SUPPORT_LV5":                      ("", 6),
    "TEAM_BONUS_SUPPORT_LV6":                      ("", 6),
    "TEAM_BONUS_UNION_LV1":                        ("", 6),
    "TEAM_BONUS_UNION_LV2":                        ("", 6),
    "TEAM_BONUS_UNION_LV3":                        ("", 6),
    "TEAM_BONUS_UNION_LV4":                        ("", 6),
    "TEAM_BONUS_UNION_LV5":                        ("", 6),
    "TEAM_BONUS_UNION_LV6":                        ("", 6),
}

_GROUP_NAMES = {
    0: ui_text("skill_param_damage"),
    1: ui_text("skill_field_grd_byte"),
    2: ui_text("ui_btladjprm_chakra"),
    3: ui_text("ui_btladjprm_support"),
    4: ui_text("ui_btladjprm_team_power"),
    5: ui_text("ui_btladjprm_team_sp_skill"),
    6: ui_text("ui_btladjprm_team_bonus"),
}

_COLS = 3  # parameters per row inside a group card


class BtlAdjPrmEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t        = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath = None
        self._raw      = None
        self._result   = None
        self._dirty    = False
        self._param_inputs = {}  # name -> QLineEdit

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        lo = QHBoxLayout(top)
        lo.setContentsMargins(12, 8, 12, 8)
        lo.setSpacing(4)

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        lo.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        lo.addWidget(self._btn_save)

        self._file_lbl = QLabel(ui_text("ui_btladjprm_no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        lo.addWidget(self._file_lbl)
        lo.addStretch(1)

        root.addWidget(top)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        # Body
        body = QWidget()
        body.setStyleSheet(f"background-color: {P['bg_dark']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 10, 16, 12)
        bl.setSpacing(8)

        # Search row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("ui_btladjprm_search_parameters"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._on_filter)
        search_row.addWidget(self._search, 1)

        self._count_lbl = QLabel("")
        self._count_lbl.setFont(QFont("Segoe UI", 10))
        self._count_lbl.setStyleSheet(ss_dim_label())
        search_row.addWidget(self._count_lbl)

        bl.addLayout(search_row)

        # Scroll area with cards
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(ss_scrollarea())

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 12, 0)
        self._cards_layout.setSpacing(0)

        self._scroll.setWidget(self._cards_widget)
        bl.addWidget(self._scroll, 1)

        root.addWidget(body, 1)

        self._show_placeholder()

    # Card helpers

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_placeholder(self):
        self._clear_cards()
        self._param_inputs.clear()
        self._count_lbl.setText("")

        ph = QLabel(ui_text("ui_btladjprm_open_a_btladjprm_bin_xfbin_file_to_begin_editing"))
        ph.setFont(QFont("Segoe UI", 16))
        ph.setStyleSheet(ss_placeholder())
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._cards_layout.addStretch()
        self._cards_layout.addWidget(ph)
        self._cards_layout.addStretch()

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(20, 10, 0, 2)
        self._cards_layout.addWidget(lbl)

    # Data

    def _populate_cards(self, filter_text=""):
        if self._result is None:
            self._show_placeholder()
            return

        self._clear_cards()
        self._param_inputs.clear()

        entries  = self._result['entries']
        ft       = filter_text.strip().lower()
        visible  = [e for e in entries if not ft or ft in e['name'].lower()]

        # Bucket visible entries by group, preserving original order
        groups = {}
        for e in visible:
            _, gid = _PARAM_META.get(e['name'], ("", 0))
            groups.setdefault(gid, []).append(e)

        for gid in sorted(groups.keys()):
            group_entries = groups[gid]
            if not group_entries:
                continue

            self._add_section(_GROUP_NAMES.get(gid, ui_text("ui_btladjprm_misc")))

            card = QFrame()
            card.setStyleSheet(ss_panel())
            card_vl = QVBoxLayout(card)
            card_vl.setContentsMargins(0, 0, 0, 0)

            inner = QWidget()
            inner.setStyleSheet("background: transparent;")
            grid = QGridLayout(inner)
            grid.setContentsMargins(12, 12, 12, 12)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(8)
            card_vl.addWidget(inner)

            for i, e in enumerate(group_entries):
                row, col = divmod(i, _COLS)
                name = e['name']

                cell = QWidget()
                cell.setStyleSheet("background: transparent;")
                cell_vl = QVBoxLayout(cell)
                cell_vl.setContentsMargins(0, 0, 0, 0)
                cell_vl.setSpacing(2)

                lbl = QLabel(name)
                lbl.setFont(QFont("Segoe UI", 10))
                lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
                lbl.setWordWrap(True)
                cell_vl.addWidget(lbl)

                inp = QLineEdit()
                inp.setFixedHeight(30)
                inp.setFont(QFont("Consolas", 13))
                inp.setStyleSheet(ss_input())
                inp.setText(ui_text("ui_btladjprm_value", p0=e['value']))
                inp.editingFinished.connect(self._make_value_handler(name, inp))
                cell_vl.addWidget(inp)

                grid.addWidget(cell, row, col)
                grid.setColumnStretch(col, 1)
                self._param_inputs[name] = inp

            self._cards_layout.addWidget(card)

        self._cards_layout.addStretch()

        total = len(entries)
        shown = len(visible)
        self._count_lbl.setText(
            f"{shown} / {total} params" if ft else f"{total} params"
        )

    def _make_value_handler(self, name, inp):
        def _handler():
            if self._result is None:
                return
            text = inp.text().strip()
            try:
                value = float(text)
            except ValueError:
                QMessageBox.warning(
                    self, ui_text("ui_btladjprm_invalid_value"),
                    ui_text("ui_btladjprm_value_is_not_a_valid_float_value_was_not_saved", p0=text)               )
                for e in self._result['entries']:
                    if e['name'] == name:
                        inp.blockSignals(True)
                        inp.setText(ui_text("ui_btladjprm_value", p0=e['value']))
                        inp.blockSignals(False)
                        break
                return
            for e in self._result['entries']:
                if e['name'] == name:
                    e['value'] = value
                    self._dirty = True
                    self._btn_save.setEnabled(True)
                    set_file_label(self._file_lbl, self._filepath, dirty=True)
                    break
        return _handler

    def _on_filter(self, text):
        self._populate_cards(text)

    # File I/O

    def _load_file(self, filepath):
        create_backup_on_open(filepath)
        try:
            raw, result = parse_btladjprm_xfbin(filepath)
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=e))
            return

        self._filepath = filepath
        self._raw      = raw
        self._result   = result
        self._dirty    = False

        self._populate_cards(self._search.text())
        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_btladjprm_open_btladjprm_bin_xfbin"), game_files_dialog_dir(target_patterns="btladjprm.bin.xfbin"),
            "XFBIN Files (btladjprm.bin.xfbin);;All Files (*.*)"
        )
        if path:
            self._load_file(path)

    def _on_save(self):
        if not self._filepath or self._raw is None:
            return
        self._save_to(self._filepath)

    def _save_to(self, filepath):
        try:
            save_btladjprm_xfbin(filepath, self._raw, self._result)
            self._dirty = False
            set_file_label(self._file_lbl, filepath)
            QMessageBox.information(self, ui_text("ui_assist_saved"),
                                    ui_text("ui_assist_file_saved_value", p0=os.path.basename(filepath)))
        except Exception as e:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=e))
