"""editors/stageinfo_editor.py  –  Editor for StageInfo.bin.xfbin."""

import copy
import os
import struct

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QScrollArea,
    QFileDialog, QMessageBox,
    QTabWidget, QGridLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_input,
    ss_sidebar_btn, ss_search, ss_scrollarea,
    ss_section_label, ss_field_label, ss_tab_widget,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from parsers.stageinfo_parser import (
    parse_stageinfo_xfbin, save_stageinfo_xfbin,
    STAGE_PARAM_SIZE,
    params_get_color, params_set_color,
    params_get_float, params_set_float,
    params_get_uint32, params_set_uint32,
    params_get_bytes, params_set_bytes,
    clump_get_skip_flag, clump_get_skip_float,
)
from core.translations import ui_text


# Local UI helpers

def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _card_frame():
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
    return f


def _section_lbl(text):
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
    lbl.setStyleSheet(ss_section_label())
    lbl.setContentsMargins(20, 10, 0, 2)
    return lbl


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


# Colour-byte editor widget

class _ColorWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._edits = []
        for _ in range(4):
            e = QLineEdit("00")
            e.setFixedWidth(36)
            e.setFixedHeight(28)
            e.setMaxLength(2)
            e.setFont(QFont("Consolas", 10))
            e.setStyleSheet(ss_input())
            e.textChanged.connect(self._on_change)
            row.addWidget(e)
            self._edits.append(e)
        self._preview = QLabel()
        self._preview.setFixedSize(24, 18)
        self._preview.setStyleSheet(f"border: 1px solid {P['border']}; border-radius: 3px;")
        row.addWidget(self._preview)
        row.addStretch()

    def _on_change(self):
        self._update_preview()
        self.changed.emit()

    def _update_preview(self):
        try:
            r, g, b = (int(self._edits[i].text() or '0', 16) for i in range(3))
        except ValueError:
            return
        self._preview.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid {P['border']}; border-radius: 3px;"
        )

    def get_bytes(self):
        out = []
        for e in self._edits:
            try:
                out.append(int(e.text() or '0', 16) & 0xFF)
            except ValueError:
                out.append(0)
        return bytes(out)

    def set_bytes(self, data):
        self._edits[0].blockSignals(True)
        for e, b in zip(self._edits, data[:4]):
            e.setText(ui_text("ui_stageinfo_value", p0=b))
        self._edits[0].blockSignals(False)
        self._update_preview()


# General tab

class _GeneralTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage = None
        self._building = False
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_scrollarea())
        inner = QWidget()
        inner.setStyleSheet(f"background-color: {P['bg_dark']};")
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 8, 0, 8)
        root.setSpacing(8)

        # Stage Code card
        root.addWidget(_section_lbl(ui_text("ui_stageinfo_stage_code_max_23_chars")))
        code_card = _card_frame()
        code_inner = QWidget(code_card)
        code_inner.setStyleSheet("background: transparent;")
        code_lay = QHBoxLayout(code_inner)
        code_lay.setContentsMargins(12, 12, 12, 12)
        code_main = QVBoxLayout(code_card)
        code_main.setContentsMargins(0, 0, 0, 0)
        code_main.addWidget(code_inner)

        self._code_edit = QLineEdit()
        self._code_edit.setMaxLength(23)
        self._code_edit.setFixedHeight(36)
        self._code_edit.setFont(QFont("Consolas", 16))
        self._code_edit.setStyleSheet(ss_input())
        self._code_edit.editingFinished.connect(self._on_change)
        code_lay.addWidget(self._code_edit)
        root.addWidget(code_card)

        # XfbinPaths card
        root.addWidget(_section_lbl(ui_text("ui_stageinfo_xfbin_paths_asset_files_this_stage_loads")))
        self._paths_card = _card_frame()
        paths_lay = QVBoxLayout(self._paths_card)
        paths_lay.setContentsMargins(12, 12, 12, 12)
        paths_lay.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        btn_add_path = QPushButton(ui_text("ui_stageinfo_add_path"))
        btn_add_path.setFixedHeight(28)
        btn_add_path.setFont(QFont("Segoe UI", 10))
        btn_add_path.setStyleSheet(ss_btn())
        btn_add_path.clicked.connect(self._add_path)
        btn_row.addWidget(btn_add_path)

        btn_del_path = QPushButton(ui_text("ui_stageinfo_remove_last"))
        btn_del_path.setFixedHeight(28)
        btn_del_path.setFont(QFont("Segoe UI", 10))
        btn_del_path.setStyleSheet(ss_btn(danger=True))
        btn_del_path.clicked.connect(self._del_path)
        btn_row.addWidget(btn_del_path)
        btn_row.addStretch()
        paths_lay.addLayout(btn_row)

        self._paths_container = QWidget()
        self._paths_container.setStyleSheet("background: transparent;")
        self._paths_layout = QVBoxLayout(self._paths_container)
        self._paths_layout.setContentsMargins(0, 0, 0, 0)
        self._paths_layout.setSpacing(4)
        paths_lay.addWidget(self._paths_container)
        root.addWidget(self._paths_card)
        root.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_change(self):
        if not self._building:
            self.changed.emit()

    def _make_path_edit(self, text="data/stage/new.xfbin"):
        e = QLineEdit(text)
        e.setFixedHeight(30)
        e.setFont(QFont("Consolas", 13))
        e.setStyleSheet(ss_input())
        e.editingFinished.connect(self._on_change)
        return e

    def _add_path(self):
        if self._stage is None:
            return
        self._paths_layout.addWidget(self._make_path_edit())
        self._on_change()

    def _del_path(self):
        count = self._paths_layout.count()
        if count > 0:
            item = self._paths_layout.takeAt(count - 1)
            if item.widget():
                item.widget().deleteLater()
            self._on_change()

    def load_stage(self, stage):
        self._stage = stage
        self._building = True
        self._code_edit.setText(stage['code'])
        _clear_layout(self._paths_layout)
        for p in stage['paths']:
            self._paths_layout.addWidget(self._make_path_edit(p))
        self._building = False

    def collect(self, stage):
        stage['code'] = self._code_edit.text()[:23]
        paths = []
        for i in range(self._paths_layout.count()):
            item = self._paths_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QLineEdit):
                paths.append(item.widget().text())
        stage['paths'] = paths


# Params tab

class _ParamsTab(QWidget):
    changed = pyqtSignal()

    _COLOR_OFFSETS = [0, 4, 8, 12, 16, 20, 40, 60]
    _COLOR_LABELS = [
        ui_text("ui_stageinfo_color_1_fog_far_a"),
        ui_text("ui_stageinfo_color_2_fog_far_b"),
        ui_text("ui_stageinfo_color_3_ambient_a"),
        ui_text("ui_stageinfo_color_4_ambient_b"),
        ui_text("ui_stageinfo_color_5_sky_a"),
        ui_text("ui_stageinfo_color_6_sky_b"),
        ui_text("ui_stageinfo_color_7_highlight"),
        ui_text("ui_stageinfo_color_8_shadow"),
    ]

    _SCALAR_FIELDS = [
        (24, ui_text("ui_customizedefaultparam_pos_x"),    True),
        (28, ui_text("ui_customizedefaultparam_pos_y"),    True),
        (32, ui_text("ui_stageinfo_pos_z"),    True),
        (36, ui_text("ui_stageinfo_flag_1"),   False),
        (52, ui_text("ui_sndcmnparam_float_1"),  True),
        (56, ui_text("ui_sndcmnparam_float_2"),  True),
        (64, ui_text("ui_stageinfo_flag_2"),   False),
        (68, ui_text("ui_sndcmnparam_float_3"),  True),
        (72, ui_text("ui_stageinfo_float_4"),  True),
        (76, ui_text("ui_stageinfo_float_5"),  True),
        (80, ui_text("ui_stageinfo_float_6"),  True),
        (84, ui_text("ui_stageinfo_float_7"),  True),
        (88, ui_text("ui_stageinfo_float_8"),  True),
        (92, ui_text("ui_stageinfo_float_9"),  True),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage = None
        self._building = False
        self._color_widgets = []
        self._scalar_widgets = {}
        self._reserved_edits = {}
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_scrollarea())
        inner = QWidget()
        inner.setStyleSheet(f"background-color: {P['bg_dark']};")
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 8, 0, 8)
        root.setSpacing(8)

        # Colours card
        root.addWidget(_section_lbl(ui_text("ui_stageinfo_colours_4_bytes_each_b0_b1_b2_b3_raw_hex")))
        col_card = _card_frame()
        col_inner = QWidget(col_card)
        col_inner.setStyleSheet("background: transparent;")
        col_grid = QGridLayout(col_inner)
        col_grid.setContentsMargins(12, 12, 12, 12)
        col_grid.setHorizontalSpacing(20)
        col_grid.setVerticalSpacing(8)
        col_main = QVBoxLayout(col_card)
        col_main.setContentsMargins(0, 0, 0, 0)
        col_main.addWidget(col_inner)

        for idx, (off, lbl_text) in enumerate(zip(self._COLOR_OFFSETS, self._COLOR_LABELS)):
            lbl = QLabel(lbl_text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(ss_field_label())
            cw = _ColorWidget()
            cw.changed.connect(self._on_change)
            col_grid.addWidget(lbl, idx, 0)
            col_grid.addWidget(cw, idx, 1)
            self._color_widgets.append((off, cw))

        root.addWidget(col_card)

        # Scalar params card
        root.addWidget(_section_lbl(ui_text("ui_stageinfo_scalar_parameters")))
        scl_card = _card_frame()
        scl_inner = QWidget(scl_card)
        scl_inner.setStyleSheet("background: transparent;")
        scl_grid = QGridLayout(scl_inner)
        scl_grid.setContentsMargins(12, 12, 12, 12)
        scl_grid.setHorizontalSpacing(16)
        scl_grid.setVerticalSpacing(8)
        scl_main = QVBoxLayout(scl_card)
        scl_main.setContentsMargins(0, 0, 0, 0)
        scl_main.addWidget(scl_inner)

        for fi, (off, lbl_text, is_float) in enumerate(self._SCALAR_FIELDS):
            row, col = divmod(fi, 3)
            fw = self._make_scalar_field(off, lbl_text, is_float)
            scl_grid.addWidget(fw, row, col)
            scl_grid.setColumnStretch(col, 1)

        root.addWidget(scl_card)

        # Reserved bytes card
        root.addWidget(_section_lbl(ui_text("ui_stageinfo_reserved_unknown_bytes_hex")))
        res_card = _card_frame()
        res_inner = QWidget(res_card)
        res_inner.setStyleSheet("background: transparent;")
        res_grid = QGridLayout(res_inner)
        res_grid.setContentsMargins(12, 12, 12, 12)
        res_grid.setHorizontalSpacing(16)
        res_grid.setVerticalSpacing(8)
        res_main = QVBoxLayout(res_card)
        res_main.setContentsMargins(0, 0, 0, 0)
        res_main.addWidget(res_inner)

        for ci, (off, sz, lbl_text) in enumerate([
            (44, 8,  ui_text("ui_stageinfo_reserved_1_44_8_bytes")),
            (96, 40, ui_text("ui_stageinfo_reserved_2_96_40_bytes")),
        ]):
            fw = QWidget()
            fw.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(fw)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)
            lbl = QLabel(lbl_text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(ss_field_label())
            fl.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(ss_input())
            e.editingFinished.connect(self._on_change)
            fl.addWidget(e)
            res_grid.addWidget(fw, 0, ci)
            res_grid.setColumnStretch(ci, 1)
            self._reserved_edits[off] = (e, sz)

        root.addWidget(res_card)
        root.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _make_scalar_field(self, off, lbl_text, is_float):
        fw = QWidget()
        fw.setStyleSheet("background: transparent;")
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(2)
        lbl = QLabel(ui_text("ui_stageinfo_value_value", p0=lbl_text, p1=off))
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        fl.addWidget(lbl)
        w = QLineEdit()
        w.setFixedHeight(30)
        w.setFont(QFont("Consolas", 13))
        w.setStyleSheet(ss_input())
        w.editingFinished.connect(self._on_change)
        fl.addWidget(w)
        self._scalar_widgets[off] = (w, is_float)
        return fw

    def _on_change(self):
        if not self._building:
            self.changed.emit()

    def load_stage(self, stage):
        self._stage = stage
        self._building = True
        params = stage['params']
        for off, cw in self._color_widgets:
            cw.set_bytes(params_get_color(params, off))
        for off, (w, is_float) in self._scalar_widgets.items():
            if is_float:
                w.setText(ui_text("ui_btladjprm_value", p0=params_get_float(params, off)))
            else:
                w.setText(str(params_get_uint32(params, off)))
        for off, (e, sz) in self._reserved_edits.items():
            e.setText(params_get_bytes(params, off, sz).hex().upper())
        self._building = False

    def collect(self, stage):
        params = stage['params']
        for off, cw in self._color_widgets:
            params_set_color(params, off, cw.get_bytes())
        for off, (w, is_float) in self._scalar_widgets.items():
            try:
                if is_float:
                    params_set_float(params, off, float(w.text()))
                else:
                    params_set_uint32(params, off, int(w.text()))
            except ValueError:
                pass
        for off, (e, sz) in self._reserved_edits.items():
            try:
                raw = bytes.fromhex(e.text().replace(' ', ''))[:sz]
                raw += b'\x00' * (sz - len(raw))
                params_set_bytes(params, off, raw)
            except ValueError:
                pass


# Clumps tab

class _ClumpsTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        btn_bar = QFrame()
        btn_bar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border: none; }}")
        btn_bar_lay = QHBoxLayout(btn_bar)
        btn_bar_lay.setContentsMargins(12, 6, 12, 6)
        btn_bar_lay.setSpacing(4)

        bf = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(ui_text("ui_messageinfo_add"))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(bf)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.clicked.connect(self._add_clump)
        btn_bar_lay.addWidget(self._btn_add)

        self._btn_dup = QPushButton(ui_text("btn_dup_short"))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(bf)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.clicked.connect(self._dup_clump)
        btn_bar_lay.addWidget(self._btn_dup)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(bf)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.clicked.connect(self._del_clump)
        btn_bar_lay.addWidget(self._btn_del)
        btn_bar_lay.addStretch()

        root.addWidget(btn_bar)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        self._scroll, self._cards_layout = _right_scroll()
        root.addWidget(self._scroll, 1)

    def load_stage(self, stage):
        self._stage = stage
        self._rebuild()

    def _rebuild(self):
        _clear_layout(self._cards_layout)
        if self._stage is None:
            return
        for i, c in enumerate(self._stage['clumps']):
            self._cards_layout.addWidget(self._make_card(i, c))
        self._cards_layout.addStretch()

    def _make_card(self, idx, c):
        skip_flag  = clump_get_skip_flag(c['skip_data'])
        skip_float = clump_get_skip_float(c['skip_data'])

        card = _card_frame()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        hdr = QLabel(ui_text("ui_mainmodeparam_value_value", p0=idx, p1=c['clump_name']))
        hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        cl.addWidget(hdr)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        fw0, f_path  = _make_field(ui_text("ui_effect_xfbin_path"),  c['xfbin_path'])
        fw1, f_clump = _make_field(ui_text("ui_stageinfo_clump_name"),  c['clump_name'])
        fw2, f_unk   = _make_field(ui_text("ui_stageinfo_unk_name"),    c['unk_name'])
        fw3, f_unk2  = _make_field(ui_text("ui_stageinfo_unk2_name"),   c['unk2_name'])
        fw4, f_flag  = _make_field(ui_text("ui_stageinfo_skip_flag"),   skip_flag)
        fw5, f_float = _make_field(ui_text("ui_stageinfo_skip_float"),  f"{skip_float:.6f}")
        fw6, f_val1  = _make_field(ui_text("ui_stageinfo_val1_hex"),  f"{c['val1']:02X}")
        fw7, f_val2  = _make_field(ui_text("ui_stageinfo_val2_hex"),  f"{c['val2']:02X}")

        grid.addWidget(fw0, 0, 0); grid.setColumnStretch(0, 2)
        grid.addWidget(fw1, 0, 1); grid.setColumnStretch(1, 2)
        grid.addWidget(fw2, 1, 0)
        grid.addWidget(fw3, 1, 1)
        grid.addWidget(fw4, 2, 0); grid.setColumnStretch(0, 1)
        grid.addWidget(fw5, 2, 1); grid.setColumnStretch(1, 1)
        grid.addWidget(fw6, 2, 2); grid.setColumnStretch(2, 1)
        grid.addWidget(fw7, 2, 3); grid.setColumnStretch(3, 1)

        cl.addLayout(grid)

        def commit(c=c, hdr=hdr, idx=idx,
                   f_path=f_path, f_clump=f_clump, f_unk=f_unk, f_unk2=f_unk2,
                   f_flag=f_flag, f_float=f_float, f_val1=f_val1, f_val2=f_val2):
            c['xfbin_path'] = f_path.text()
            c['clump_name'] = f_clump.text()
            c['unk_name']   = f_unk.text()
            c['unk2_name']  = f_unk2.text()
            sd = bytearray(16)
            try:
                struct.pack_into('<I', sd, 0, int(f_flag.text()))
            except (ValueError, struct.error):
                pass
            try:
                struct.pack_into('<f', sd, 4, float(f_float.text()))
            except (ValueError, struct.error):
                pass
            c['skip_data'] = bytes(sd)
            try:
                c['val1'] = int(f_val1.text(), 16)
            except ValueError:
                pass
            try:
                c['val2'] = int(f_val2.text(), 16)
            except ValueError:
                pass
            hdr.setText(ui_text("ui_mainmodeparam_value_value", p0=idx, p1=c['clump_name']))
            self.changed.emit()

        for field in (f_path, f_clump, f_unk, f_unk2, f_flag, f_float, f_val1, f_val2):
            field.editingFinished.connect(commit)

        return card

    def _add_clump(self):
        if self._stage is None:
            return
        self._stage['clumps'].append({
            'xfbin_path': 'data/stage/new.xfbin',
            'clump_name': 'new_clump00',
            'unk_name':   '',
            'unk2_name':  '',
            'skip_data':  b'\x00' * 16,
            'val1': 0x3C,
            'val2': 0x78,
        })
        self._rebuild()
        self.changed.emit()

    def _dup_clump(self):
        if self._stage is None or not self._stage['clumps']:
            return
        self._stage['clumps'].append(copy.deepcopy(self._stage['clumps'][-1]))
        self._rebuild()
        self.changed.emit()

    def _del_clump(self):
        if self._stage is None or not self._stage['clumps']:
            return
        self._stage['clumps'].pop()
        self._rebuild()
        self.changed.emit()

    def collect(self, stage):
        pass  # Auto-committed via editingFinished in each card


# Main editor widget

class StageInfoEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath = None
        self._raw = None
        self._result = None
        self._dirty = False
        self._current_idx = -1
        self._stage_btns = []

        self._build_ui()

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

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._open_file)
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._save_file)
        tl.addWidget(self._btn_save)

        self._file_lbl = QLabel(ui_text("xfa_no_file"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']};")
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {P['mid']};")
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
        list_vlay = QVBoxLayout(list_frame)
        list_vlay.setContentsMargins(8, 8, 8, 4)
        list_vlay.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("ui_stageinfo_search_stages"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_list)
        list_vlay.addWidget(self._search)

        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        bf = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(ui_text("ui_messageinfo_add"))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(bf)
        self._btn_add.setEnabled(False)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.clicked.connect(self._add_stage)
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(ui_text("btn_dup_short"))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(bf)
        self._btn_dup.setEnabled(False)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.clicked.connect(self._dup_stage)
        actions_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(bf)
        self._btn_del.setEnabled(False)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.clicked.connect(self._del_stage)
        actions_layout.addWidget(self._btn_del, 1)

        list_vlay.addWidget(actions_frame)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background-color: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        list_vlay.addWidget(self._list_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Right panel
        right = QWidget()
        right.setStyleSheet(f"background-color: {P['bg_dark']};")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self._placeholder = QLabel(ui_text("ui_stageinfo_open_a_stageinfo_bin_xfbin_file_to_begin_editing"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_lay.addWidget(self._placeholder, 1)

        self._tabs = QTabWidget()
        self._tabs.setFont(QFont("Segoe UI", 11))
        self._tabs.setStyleSheet(ss_tab_widget())
        self._tabs.setVisible(False)

        self._tab_general = _GeneralTab()
        self._tab_params  = _ParamsTab()
        self._tab_clumps  = _ClumpsTab()

        self._tab_general.changed.connect(self._on_data_changed)
        self._tab_params.changed.connect(self._on_data_changed)
        self._tab_clumps.changed.connect(self._on_data_changed)

        self._tabs.addTab(self._tab_general, ui_text("ui_stageinfo_general"))
        self._tabs.addTab(self._tab_params,  ui_text("ui_stageinfo_params"))
        self._tabs.addTab(self._tab_clumps,  ui_text("ui_stageinfo_clumps"))

        right_lay.addWidget(self._tabs, 1)

        main_layout.addWidget(right, 1)
        root.addWidget(main, 1)

    # File I/O

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_stageinfo_open_stageinfo_bin_xfbin"), "",
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if path:
            self._load(path)

    def _load(self, path):
        try:
            raw, result = parse_stageinfo_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), str(exc))
            return

        self._filepath = path
        self._raw      = raw
        self._result   = result
        self._dirty    = False
        self._current_idx = -1

        self._file_lbl.setText(os.path.basename(path))
        self._file_lbl.setStyleSheet(f"color: {P['text_file']}; background: transparent;")
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)

        self._placeholder.setText(ui_text("ui_stageinfo_select_a_stage"))
        self._placeholder.setVisible(True)
        self._tabs.setVisible(False)

        self._rebuild_stage_list()

    def _save_file(self):
        if not self._filepath or self._result is None:
            return
        self._flush_current()
        try:
            save_stageinfo_xfbin(self._filepath, self._raw, self._result)
            self._dirty = False
            self._file_lbl.setText(os.path.basename(self._filepath))
            self._file_lbl.setStyleSheet(f"color: {P['text_file']}; background: transparent;")
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(exc))

    # Stage list

    def _rebuild_stage_list(self):
        _clear_layout(self._list_layout)
        self._stage_btns = []
        for i, s in enumerate(self._result['stages']):
            label = s['code'] if s['code'] else f"Stage {i:02d}"
            subtitle = f"#{i:02d}  ·  {len(s['clumps'])} clumps"
            btn = _entry_btn(
                label, subtitle,
                selected=(i == self._current_idx),
                on_click=lambda _, idx=i: self._on_stage_selected(idx),
            )
            self._list_layout.insertWidget(self._list_layout.count(), btn)
            self._stage_btns.append((btn, i))
        self._list_layout.addStretch()

    def _filter_list(self):
        if self._result is None:
            return
        q = self._search.text().lower()
        for btn, i in self._stage_btns:
            if i >= len(self._result['stages']):
                continue
            s = self._result['stages'][i]
            btn.setVisible(not q or q in s['code'].lower() or q in f"{i:02d}")

    def _on_stage_selected(self, idx):
        self._flush_current()
        self._current_idx = idx

        for btn, i in self._stage_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))

        stage = self._result['stages'][idx]
        self._tab_general.load_stage(stage)
        self._tab_params.load_stage(stage)
        self._tab_clumps.load_stage(stage)

        self._placeholder.setVisible(False)
        self._tabs.setVisible(True)

    def _flush_current(self):
        if self._current_idx < 0 or self._result is None:
            return
        stage = self._result['stages'][self._current_idx]
        self._tab_general.collect(stage)
        self._tab_params.collect(stage)
        self._tab_clumps.collect(stage)
        for btn, i in self._stage_btns:
            if i == self._current_idx:
                lbls = btn.findChildren(QLabel)
                if lbls:
                    label = stage['code'] if stage['code'] else f"Stage {i:02d}"
                    lbls[0].setText(label)
                break

    def _add_stage(self):
        if self._result is None:
            return
        new_stage = {
            'code':   'STAGE_NEW',
            'paths':  ['data/stage/new.xfbin'],
            'clumps': [{
                'xfbin_path': 'data/stage/new.xfbin',
                'clump_name': 'new_clump00',
                'unk_name':   '',
                'unk2_name':  '',
                'skip_data':  b'\x00' * 16,
                'val1': 0x3C,
                'val2': 0x78,
            }],
            'params': bytearray(STAGE_PARAM_SIZE),
        }
        self._flush_current()
        self._result['stages'].append(new_stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(self._result['stages']) - 1)
        self._mark_dirty()

    def _dup_stage(self):
        if self._result is None or self._current_idx < 0:
            return
        self._flush_current()
        src = self._result['stages'][self._current_idx]
        new_stage = copy.deepcopy(src)
        new_stage['code'] = src['code'] + '_copy'
        self._result['stages'].append(new_stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(self._result['stages']) - 1)
        self._mark_dirty()

    def _del_stage(self):
        if self._result is None or not self._result['stages']:
            return
        row = self._current_idx
        if row < 0:
            return
        code = self._result['stages'][row]['code']
        reply = QMessageBox.question(
            self, ui_text("ui_stageinfo_delete_stage"),
            ui_text("ui_stageinfo_remove_stage_value_value", p0=row, p1=code),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._current_idx = -1
        del self._result['stages'][row]
        self._tabs.setVisible(False)
        self._placeholder.setVisible(True)
        self._placeholder.setText(ui_text("ui_stageinfo_select_a_stage"))
        self._rebuild_stage_list()
        self._mark_dirty()

    # Dirty state

    def _on_data_changed(self):
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(True)
        name = os.path.basename(self._filepath) if self._filepath else ''
        self._file_lbl.setText(ui_text("ui_effect_value", p0=name))
        self._file_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
