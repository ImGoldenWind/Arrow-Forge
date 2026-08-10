"""editors/stagemotion_editor.py  –  Editor for Xcmnsfprm.bin.xfbin (Stage Motion Parameters)."""

import copy
import os

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QVBoxLayout, QHBoxLayout, QScrollArea, QGridLayout,
    QFileDialog, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from core.style_helpers import (
    add_editor_card_title, make_empty_state,
    ss_btn, ss_sep, ss_accent_sep, ss_input,
    ss_sidebar_btn, ss_search, ss_scrollarea, ss_scrollarea_transparent,
    ss_editor_card, ss_transparent, ss_bg_dark, ss_bg_panel,
    ss_sidebar_frame, ss_file_label,
    ss_accent_label, ss_dim_label, ss_main_label,
    make_editor_field_shell, make_editor_grid_card,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.stagemotion_parser import (
    parse_stagemotion_xfbin, save_stagemotion_xfbin,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


# Type-code catalogue

TYPE_OPTIONS = [
    (0x0044, ui_text("ui_stagemotion_0x0044_anim_speed_d")),
    (0x00EE, ui_text("ui_stagemotion_0x00ee_face_expression")),
    (0x0084, ui_text("ui_stagemotion_0x0084_speaking_voice")),
    (0x0111, ui_text("ui_stagemotion_0x0111_sync_marker")),
    (0x0070, ui_text("ui_stagemotion_0x0070_unknown_70")),
    (0x006F, ui_text("ui_stagemotion_0x006f_unknown_6f")),
]


# Local UI helpers

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


def _card_frame():
    f = QFrame()
    f.setObjectName("EditorCard")
    f.setStyleSheet(ss_editor_card())
    f.setMinimumWidth(0)
    f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return f


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "..."


def _make_field(label_text, value_text, hint_text=""):
    f, fl, _label, _hint = make_editor_field_shell(label_text, hint_text)
    f.setMinimumWidth(0)
    f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    e = QLineEdit(str(value_text))
    e.setFixedHeight(30)
    e.setMinimumWidth(0)
    e.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    e.setFont(QFont("Consolas", 13))
    e.setStyleSheet(ss_input())
    e.setCursorPosition(0)
    fl.addWidget(e)
    return f, e


def _make_combo_field(label_text, options_with_data, current_data):
    """Returns (container_widget, QComboBox). options_with_data = [(data, label), ...]"""
    f, fl, _label, _hint = make_editor_field_shell(label_text)
    f.setMinimumWidth(0)
    f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    cb = QComboBox()
    cb.setFixedHeight(30)
    cb.setMinimumWidth(0)
    cb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    cb.setMinimumContentsLength(1)
    cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    cb.setFont(QFont("Consolas", 12))
    cb.setStyleSheet(ss_input())
    for data, text in options_with_data:
        cb.addItem(text, data)
    matched = False
    for i in range(cb.count()):
        if cb.itemData(i) == current_data:
            cb.setCurrentIndex(i)
            matched = True
            break
    if not matched:
        cb.addItem(f"0x{current_data:04X}  (custom)", current_data)
        cb.setCurrentIndex(cb.count() - 1)
    fl.addWidget(cb)
    return f, cb


def _sidebar_entry_btn(title, subtitle, selected, on_click):
    btn = QPushButton()
    btn.setFixedHeight(44)
    btn.setMinimumWidth(0)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(ss_sidebar_btn(selected=selected))
    bl = QVBoxLayout(btn)
    bl.setContentsMargins(10, 3, 10, 3)
    bl.setSpacing(0)
    name_lbl = QLabel(_truncate(title, 24))
    name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    name_lbl.setStyleSheet(ss_main_label())
    name_lbl.setMinimumWidth(0)
    name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    name_lbl.setToolTip(title)
    name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    bl.addWidget(name_lbl)
    if subtitle:
        sub_lbl = QLabel(_truncate(subtitle, 28))
        sub_lbl.setFont(QFont("Segoe UI", 11))
        sub_lbl.setStyleSheet(ss_dim_label())
        sub_lbl.setMinimumWidth(0)
        sub_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        sub_lbl.setToolTip(subtitle)
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(sub_lbl)
    btn.clicked.connect(on_click)
    return btn


# Main editor widget

class StageMotionEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath = None
        self._raw = None
        self._result = None
        self._current_stage_idx = -1
        self._stage_btns = []
        self._entries_layout = None
        self._entry_section_lbl = None
        self._last_compact: bool | None = None

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
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
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(ss_sidebar_frame())
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
        actions_frame.setStyleSheet(ss_transparent())
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
        self._list_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_inner = QWidget()
        self._list_inner.setMinimumWidth(0)
        self._list_inner.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_inner)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_inner)
        list_vlay.addWidget(self._list_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        # Right panel
        right = QWidget()
        right.setStyleSheet(ss_bg_dark())
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self._placeholder_wrap = QWidget(right)
        self._placeholder_wrap.setStyleSheet(ss_transparent())
        self._placeholder_layout = QVBoxLayout(self._placeholder_wrap)
        self._placeholder_layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder_layout.setSpacing(0)
        self._show_placeholder(
            ui_text("ui_stagemotion_open_a_xcmnsfprm_bin_xfbin_file_to_begin_editing"),
            title=ui_text("no_file_loaded"),
            icon_name="fa6s.route",
        )
        right_lay.addWidget(self._placeholder_wrap, 1)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_inner = QWidget()
        self._editor_inner.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_inner)
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(10)
        self._editor_scroll.setWidget(self._editor_inner)
        self._editor_scroll.setVisible(False)

        right_lay.addWidget(self._editor_scroll, 1)
        main_layout.addWidget(right, 1)
        root.addWidget(main, 1)

    def _show_placeholder(self, text, *, title=None, icon_name="fa6s.list"):
        _clear_layout(self._placeholder_layout)
        card = make_empty_state(
            self._placeholder_wrap,
            title=title or ui_text("ui_model_viewer_select_item"),
            text=text,
            icon_name=icon_name,
        )
        self._placeholder_layout.addStretch()
        self._placeholder_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._placeholder_layout.addStretch()
        self._placeholder_wrap.setVisible(True)

    # File I/O

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_stagemotion_open_stage_motion_file"), game_files_dialog_dir(target_patterns="Xcmnsfprm.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if path:
            self._load(path)

    def _load(self, path):
        create_backup_on_open(path)
        try:
            raw, result = parse_stagemotion_xfbin(path)
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_stagemotion_failed_to_parse_file_value", p0=e))
            return
        self._filepath = path
        self._raw = raw
        self._result = result
        self._current_stage_idx = -1

        set_file_label(self._file_lbl, path)
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)

        self._show_placeholder(ui_text("ui_stageinfo_select_a_stage"))
        self._editor_scroll.setVisible(False)

        self._rebuild_stage_list()

    def _save_file(self):
        if not self._filepath or self._result is None:
            return
        try:
            save_stagemotion_xfbin(self._filepath, self._raw, self._result)
            set_file_label(self._file_lbl, self._filepath)
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_spm_save_failed_value", p0=e))

    # Stage list

    def _rebuild_stage_list(self):
        _clear_layout(self._list_layout)
        self._stage_btns = []
        if self._result is None:
            self._list_layout.addStretch()
            return
        for i, s in enumerate(self._result['stages']):
            sid = s.get('stage_id', '') or f"Stage {i:02d}"
            n = len(s.get('entries', []))
            btn = _sidebar_entry_btn(
                sid, f"#{i:02d}  ·  {n} entries",
                selected=(i == self._current_stage_idx),
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
            sid = s.get('stage_id', '').lower()
            btn.setVisible(not q or q in sid or q in f"{i:02d}")

    def _on_stage_selected(self, idx):
        self._current_stage_idx = idx
        for btn, i in self._stage_btns:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))
        stage = self._result['stages'][idx]
        self._placeholder_wrap.setVisible(False)
        self._editor_scroll.setVisible(True)
        self._rebuild_right_panel(stage)

    def _update_sidebar_btn(self, idx):
        if self._result is None or idx >= len(self._result['stages']):
            return
        s = self._result['stages'][idx]
        sid = s.get('stage_id', '') or f"Stage {idx:02d}"
        n = len(s.get('entries', []))
        for btn, i in self._stage_btns:
            if i == idx:
                lbls = btn.findChildren(QLabel)
                if len(lbls) >= 2:
                    subtitle = ui_text("ui_stagemotion_value_value_entries", p0=idx, p1=n)
                    lbls[0].setText(_truncate(sid, 24))
                    lbls[0].setToolTip(sid)
                    lbls[1].setText(_truncate(subtitle, 28))
                    lbls[1].setToolTip(subtitle)
                break

    def _add_stage(self):
        if self._result is None:
            return
        new_stage = {
            'id_flag':   0,
            'nut_type':  'PL_ANM_NUT',
            'stage_id':  'SF_NEW_STAGE',
            'sub_count': 2,
            'entries':   [],
        }
        self._result['stages'].append(new_stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(self._result['stages']) - 1)
        self._mark_dirty()

    def _dup_stage(self):
        if self._result is None or self._current_stage_idx < 0:
            return
        src = self._result['stages'][self._current_stage_idx]
        new_stage = copy.deepcopy(src)
        new_stage['stage_id'] = src.get('stage_id', '') + '_copy'
        self._result['stages'].append(new_stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(self._result['stages']) - 1)
        self._mark_dirty()

    def _del_stage(self):
        if self._result is None or self._current_stage_idx < 0:
            return
        idx = self._current_stage_idx
        sid = self._result['stages'][idx].get('stage_id', str(idx))
        reply = QMessageBox.question(
            self, ui_text("ui_stagemotion_remove_stage"),
            ui_text("ui_stagemotion_remove_stage_value_and_all_its_entries", p0=sid),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._result['stages'].pop(idx)
        self._current_stage_idx = -1
        self._show_placeholder(ui_text("ui_stageinfo_select_a_stage"))
        self._editor_scroll.setVisible(False)
        self._rebuild_stage_list()
        self._mark_dirty()

    # Right panel

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < 780

    def _grid_columns(self, max_columns: int) -> int:
        width = self._editor_scroll.viewport().width()
        if width < 780:
            return 1
        if width < 1080:
            return min(2, max_columns)
        return max_columns

    def _prep_card(self, card: QFrame):
        card.setMinimumWidth(0)
        card.setMaximumWidth(980)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def _add_editor_card(self, card: QFrame):
        self._editor_layout.addWidget(card)

    def _grid_add(self, grid: QGridLayout, widget: QWidget, index: int, max_columns: int, stretch: int = 1):
        columns = self._grid_columns(max_columns)
        row, col = divmod(index, columns)
        grid.addWidget(widget, row, col)
        grid.setColumnStretch(col, stretch)

    def _rebuild_right_panel(self, stage):
        _clear_layout(self._editor_layout)
        self._last_compact = self._is_compact_editor()

        # Stage Header card
        hdr_card, hdr_grid = make_editor_grid_card(
            self._editor_inner,
            title=ui_text("ui_stagemotion_stage_header"),
            icon_name="fa6s.sliders",
            subtitle=stage.get('stage_id', ''),
            grid_margins=(0, 4, 0, 0),
            vertical_spacing=8,
        )
        self._prep_card(hdr_card)

        fw0, f_sid = _make_field(
            ui_text("ui_mainmodeparam_stage_id"),
            stage.get('stage_id', ''),
        )
        fw1, f_nut = _make_field(ui_text("ui_stagemotion_nut_type"), stage.get('nut_type', 'PL_ANM_NUT'))
        fw2, f_flg = _make_field(ui_text("ui_stagemotion_id_flag"), stage.get('id_flag', 0))

        self._grid_add(hdr_grid, fw0, 0, 3, 2)
        self._grid_add(hdr_grid, fw1, 1, 3, 2)
        self._grid_add(hdr_grid, fw2, 2, 3, 1)

        cur_idx = self._current_stage_idx

        def commit_header(stage=stage):
            stage['stage_id'] = f_sid.text()[:31]
            stage['nut_type'] = f_nut.text() or 'PL_ANM_NUT'
            try:
                stage['id_flag'] = int(f_flg.text())
            except ValueError:
                pass
            self._update_sidebar_btn(cur_idx)
            self._mark_dirty()

        f_sid.editingFinished.connect(commit_header)
        f_nut.editingFinished.connect(commit_header)
        f_flg.editingFinished.connect(commit_header)

        self._add_editor_card(hdr_card)

        # Entries section
        entries = stage.setdefault('entries', [])

        ent_bar = _card_frame()
        self._prep_card(ent_bar)
        ent_bar_lay = QVBoxLayout(ent_bar)
        ent_bar_lay.setContentsMargins(12, 12, 12, 12)
        ent_bar_lay.setSpacing(8)
        _row, self._entry_section_lbl, _subtitle = add_editor_card_title(
            ent_bar_lay,
            ui_text("ui_stagemotion_entries_value", p0=len(entries)),
            "fa6s.list",
        )

        ent_buttons = QHBoxLayout()
        ent_buttons.setContentsMargins(0, 0, 0, 0)
        ent_buttons.setSpacing(4)

        bf = QFont("Segoe UI", 10)

        btn_add_e = QPushButton(ui_text("ui_messageinfo_add"))
        btn_add_e.setFixedHeight(28); btn_add_e.setFont(bf)
        btn_add_e.setStyleSheet(ss_btn())
        btn_add_e.clicked.connect(lambda: self._add_entry(stage))
        ent_buttons.addWidget(btn_add_e)

        ent_buttons.addStretch()
        ent_bar_lay.addLayout(ent_buttons)
        self._add_editor_card(ent_bar)

        # Entry cards container
        self._entries_container = QWidget()
        self._entries_container.setMinimumWidth(0)
        self._entries_container.setMaximumWidth(980)
        self._entries_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._entries_container.setStyleSheet(ss_transparent())
        self._entries_layout = QVBoxLayout(self._entries_container)
        self._entries_layout.setContentsMargins(0, 8, 0, 0)
        self._entries_layout.setSpacing(8)

        for i, e in enumerate(entries):
            self._entries_layout.addWidget(self._make_entry_card(i, e, stage))

        self._add_editor_card(self._entries_container)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_stage_idx >= 0 and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._result is None or self._current_stage_idx < 0:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        stages = self._result.get('stages') or []
        if 0 <= self._current_stage_idx < len(stages):
            self._rebuild_right_panel(stages[self._current_stage_idx])

    def _make_entry_card(self, idx, entry, stage):
        card = _card_frame()
        self._prep_card(card)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        # Card header row: index label + Dup / Delete buttons
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(4)
        hdr_lbl = QLabel(ui_text("ui_stagemotion_value", p0=idx))
        hdr_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        hdr_lbl.setStyleSheet(ss_accent_label())
        hdr_row.addWidget(hdr_lbl)
        hdr_row.addStretch()

        cbf = QFont("Segoe UI", 10)
        btn_dup_card = QPushButton(ui_text("btn_dup_short"))
        btn_dup_card.setFixedHeight(26)
        btn_dup_card.setFont(cbf)
        btn_dup_card.setStyleSheet(ss_btn())
        btn_dup_card.clicked.connect(lambda _, e=entry, s=stage: self._dup_entry_item(e, s))
        hdr_row.addWidget(btn_dup_card)

        btn_del_card = QPushButton(ui_text("btn_delete"))
        btn_del_card.setFixedHeight(26)
        btn_del_card.setFont(cbf)
        btn_del_card.setStyleSheet(ss_btn(danger=True))
        btn_del_card.clicked.connect(lambda _, e=entry, s=stage: self._del_entry(e, s))
        hdr_row.addWidget(btn_del_card)

        cl.addLayout(hdr_row)

        # Fields grid
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        fw0, f_name  = _make_field(ui_text("ui_stagemotion_action_name"), entry.get('name', ''))
        fw1, f_frame = _make_field(ui_text("skill_field_frame_num"), entry.get('frame', 0))
        fw3, f_val3  = _make_field(ui_text("ui_stagemotion_val3_duration"), entry.get('val3', 0))
        fw4, f_float = _make_field(ui_text("skill_param_float"), f"{entry.get('float_val', 0.0):.6g}")
        fw2, f_type  = _make_combo_field(
            ui_text("ui_dlcinfoparam_type"),
            [(code, label) for code, label in TYPE_OPTIONS],
            entry.get('type_code', 0x0044),
        )

        for field_index, (field_widget, stretch) in enumerate([
            (fw0, 3),
            (fw2, 3),
            (fw1, 1),
            (fw3, 1),
            (fw4, 1),
        ]):
            self._grid_add(grid, field_widget, field_index, 3, stretch)

        cl.addLayout(grid)

        def commit(entry=entry):
            entry['name'] = f_name.text()[:32]
            try:
                entry['frame'] = max(0, int(f_frame.text()))
            except ValueError:
                pass
            entry['type_code'] = f_type.currentData()
            try:
                entry['val3'] = max(0, int(f_val3.text()))
            except ValueError:
                pass
            try:
                entry['float_val'] = float(f_float.text())
            except ValueError:
                pass
            self._mark_dirty()

        f_name.editingFinished.connect(commit)
        f_frame.editingFinished.connect(commit)
        f_val3.editingFinished.connect(commit)
        f_float.editingFinished.connect(commit)
        f_type.currentIndexChanged.connect(lambda _: commit())

        return card

    def _rebuild_entries(self, stage):
        """Rebuild only the entries area without touching the header card."""
        if self._entries_layout is None:
            return
        _clear_layout(self._entries_layout)
        entries = stage.get('entries', [])
        for i, e in enumerate(entries):
            self._entries_layout.addWidget(self._make_entry_card(i, e, stage))
        if self._entry_section_lbl is not None:
            self._entry_section_lbl.setText(ui_text("ui_stagemotion_entries_value", p0=len(entries)).upper())
        self._update_sidebar_btn(self._current_stage_idx)

    # Entry operations

    def _add_entry(self, stage):
        stage.setdefault('entries', []).append(
            {'name': '', 'frame': 0, 'type_code': 0x0044, 'val3': 0, 'float_val': 1.0}
        )
        self._rebuild_entries(stage)
        self._mark_dirty()

    def _dup_entry_item(self, entry, stage):
        entries = stage.setdefault('entries', [])
        try:
            idx = entries.index(entry)
        except ValueError:
            return
        entries.insert(idx + 1, copy.deepcopy(entry))
        self._rebuild_entries(stage)
        self._mark_dirty()

    def _del_entry(self, entry, stage):
        entries = stage.get('entries', [])
        try:
            entries.remove(entry)
        except ValueError:
            return
        self._rebuild_entries(stage)
        self._mark_dirty()

    # Dirty state

    def _mark_dirty(self):
        self._btn_save.setEnabled(True)
        set_file_label(self._file_lbl, self._filepath, dirty=True)
