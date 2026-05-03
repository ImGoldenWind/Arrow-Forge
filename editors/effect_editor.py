"""editors/effect_editor.py  –  Editor for effectprm.bin.xfbin (Effect Param)."""

import os
import threading

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_panel, ss_sidebar_btn,
    ss_section_label, ss_field_label,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.effectprm_parser import parse_effectprm_xfbin, save_effectprm_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class EffectEditor(QWidget):
    _load_done_signal  = pyqtSignal(str, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or (lambda k, **kw: k)

        self._filepath      = None
        self._raw           = None
        self._result        = None
        self._dirty         = False
        self._entries       = []
        self._current_entry = None
        self._entry_buttons = []
        self._fields        = {}

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top toolbar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        self._open_btn = QPushButton(self.t("btn_open_file"))
        self._open_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._open_btn.setFont(QFont("Segoe UI", 10))
        self._open_btn.setStyleSheet(ss_btn(accent=True))
        self._open_btn.clicked.connect(self._load_file)
        tl.addWidget(self._open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)

        self._file_lbl = QLabel(self.t("no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']};")
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {P['mid']};")
        root.addWidget(sep)

        # Main area (sidebar + editor)
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        self._search_entry.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search_entry)

        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(self.t("btn_new"))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_entry)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._dup_entry)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._del_entry)
        actions_layout.addWidget(self._del_btn, 1)

        list_vlayout.addWidget(actions_frame)

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
        list_vlayout.addWidget(self._list_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Right editor panel
        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {P['bg_dark']}; border: none; }}"
        )
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)

        self._placeholder = QLabel(ui_text("ui_effect_open_effectprm_bin_xfbin_to_begin_editing"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()

        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)

    # Sidebar helpers

    def _clear_list(self):
        _clear_layout(self._list_layout)
        self._list_layout.addStretch()

    def _make_entry_button(self, entry):
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(False))

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        name_lbl = QLabel(entry['effect_name'])
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(name_lbl)

        id_lbl = QLabel(ui_text("ui_effect_slot_value", p0=entry['slot_id']))
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(id_lbl)

        btn.clicked.connect(lambda checked=False, e=entry: self._select_entry(e))
        return btn

    def _populate_list(self):
        self._clear_list()
        self._entry_buttons = []
        for entry in self._entries:
            btn = self._make_entry_button(entry)
            self._list_layout.insertWidget(self._list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, entry))

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, entry in self._entry_buttons:
            match = (
                query in entry['effect_name'].lower()
                or query in entry['xfbin_path'].lower()
                or query in str(entry['slot_id'])
            )
            btn.setVisible(match)

    def _select_entry(self, entry):
        self._apply_fields()
        self._current_entry = entry
        for btn, e in self._entry_buttons:
            try:
                btn.setStyleSheet(ss_sidebar_btn(e is entry))
            except Exception:
                pass
        self._build_editor(entry)

    # Editor panel

    def _clear_editor(self):
        _clear_layout(self._editor_layout)

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)

    def _make_field(self, label_text, value, font=None, color=None, height=30):
        frame = QWidget()
        frame.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        lbl = QLabel(label_text)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        layout.addWidget(lbl)

        e = QLineEdit()
        e.setFixedHeight(height)
        e.setFont(font or QFont("Consolas", 13))
        c = color or P['text_main']
        e.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {c}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e.setText(str(value))
        layout.addWidget(e)
        return frame, e

    def _build_editor(self, entry):
        self._clear_editor()
        self._fields = {}

        # Header card: Effect Name + Slot ID + Xfbins Count
        hdr = QFrame()
        hdr.setStyleSheet(ss_panel())
        hdr_inner = QWidget(hdr)
        hdr_inner.setStyleSheet("background: transparent;")
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(16, 12, 16, 12)
        hdr_grid.setHorizontalSpacing(16)
        hdr_grid.setVerticalSpacing(8)
        hdr_main = QVBoxLayout(hdr)
        hdr_main.setContentsMargins(0, 0, 0, 0)
        hdr_main.addWidget(hdr_inner)

        name_frame, e_name = self._make_field(
            ui_text("ui_effect_effect_name"), entry['effect_name'],
            font=QFont("Segoe UI", 18, QFont.Weight.Bold),
            color=P['accent'], height=36,
        )
        hdr_grid.addWidget(name_frame, 0, 0)
        hdr_grid.setColumnStretch(0, 2)
        self._fields['effect_name'] = e_name

        slot_frame, e_slot = self._make_field(
            ui_text("ui_effect_slot_id"), entry['slot_id'],
            font=QFont("Consolas", 16), height=36,
        )
        hdr_grid.addWidget(slot_frame, 0, 1)
        hdr_grid.setColumnStretch(1, 1)
        self._fields['slot_id'] = e_slot

        count_frame, e_count = self._make_field(
            ui_text("ui_effect_xfbins_count"), entry['xfbins_count'],
            font=QFont("Consolas", 16), height=36,
        )
        hdr_grid.addWidget(count_frame, 0, 2)
        hdr_grid.setColumnStretch(2, 1)
        self._fields['xfbins_count'] = e_count

        self._editor_layout.addWidget(hdr)

        # XFBIN Path section
        self._add_section(ui_text("ui_effect_xfbin_path"))
        path_card = QFrame()
        path_card.setStyleSheet(ss_panel())
        path_inner = QWidget(path_card)
        path_inner.setStyleSheet("background: transparent;")
        path_grid = QGridLayout(path_inner)
        path_grid.setContentsMargins(12, 12, 12, 12)
        path_grid.setHorizontalSpacing(16)
        path_grid.setVerticalSpacing(8)
        path_main = QVBoxLayout(path_card)
        path_main.setContentsMargins(0, 0, 0, 0)
        path_main.addWidget(path_inner)

        path_frame, e_path = self._make_field(ui_text("ui_effect_xfbin_path"), entry['xfbin_path'])
        path_grid.addWidget(path_frame, 0, 0)
        path_grid.setColumnStretch(0, 1)
        self._fields['xfbin_path'] = e_path

        self._editor_layout.addWidget(path_card)

        # Connect signals after all setText calls to avoid false dirty triggers
        e_name.textChanged.connect(self._mark_dirty)
        e_slot.textChanged.connect(self._mark_dirty)
        e_count.textChanged.connect(self._mark_dirty)
        e_path.textChanged.connect(self._mark_dirty)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    def _apply_fields(self):
        if not self._current_entry or not self._fields:
            return
        entry = self._current_entry
        try:
            entry['effect_name'] = self._fields['effect_name'].text().strip()
        except (KeyError, AttributeError):
            pass
        try:
            entry['slot_id'] = int(self._fields['slot_id'].text())
        except (KeyError, ValueError):
            pass
        try:
            entry['xfbins_count'] = int(self._fields['xfbins_count'].text())
        except (KeyError, ValueError):
            pass
        try:
            entry['xfbin_path'] = self._fields['xfbin_path'].text().strip()
        except (KeyError, AttributeError):
            pass
        for btn, e in self._entry_buttons:
            if e is entry:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(entry['effect_name'])
                    labels[1].setText(ui_text("ui_effect_slot_value", p0=entry['slot_id']))
                break

    # Add / Duplicate / Delete

    def _add_entry(self):
        if not self._result:
            return
        self._apply_fields()
        new_idx  = max((e['idx']     for e in self._entries), default=-1) + 1
        new_slot = max((e['slot_id'] for e in self._entries), default=-1) + 1
        new_entry = {
            'idx':          new_idx,
            'slot_id':      new_slot,
            'xfbins_count': 1,
            'xfbin_path':   'data/effect/ecmn.xfbin',
            'effect_name':  'ecmn_common_hit00',
        }
        self._entries.append(new_entry)
        self._populate_list()
        self._select_entry(new_entry)
        self._mark_dirty()

    def _dup_entry(self):
        if not self._result or not self._current_entry:
            return
        self._apply_fields()
        src = self._current_entry
        new_idx  = max((e['idx']     for e in self._entries), default=-1) + 1
        new_slot = max((e['slot_id'] for e in self._entries), default=-1) + 1
        new_entry = dict(src)
        new_entry['idx']         = new_idx
        new_entry['slot_id']     = new_slot
        new_entry['effect_name'] = src['effect_name'] + '_copy'
        self._entries.append(new_entry)
        self._populate_list()
        self._select_entry(new_entry)
        self._mark_dirty()

    def _del_entry(self):
        if not self._result or not self._current_entry:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("msg_cannot_delete_last_entry"))
            return
        result = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"),
            ui_text("ui_effect_delete_value", p0=self._current_entry['effect_name'])
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._entries.remove(self._current_entry)
        for i, e in enumerate(self._entries):
            e['idx'] = i
        self._current_entry = None
        self._fields = {}
        self._populate_list()
        if self._entries:
            self._select_entry(self._entries[0])
        else:
            self._clear_editor()
        self._mark_dirty()

    # File I/O

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_effect_open_effectprm_xfbin"), game_files_dialog_dir(target_patterns=("effectprm.bin.xfbin", "effectprm.xfbin")),
            "Effect PRM files (effectprm.bin.xfbin *.xfbin);;All files (*.*)"
        )
        if path:
            create_backup_on_open(path)
            self._start_load(path)

    def _start_load(self, path):
        self._filepath = path
        name = os.path.basename(path)
        self._file_lbl.setText(ui_text("ui_effect_loading_value", p0=name))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']};")
        self._current_entry = None
        self._entry_buttons = []
        self._fields = {}
        self._clear_list()
        self._clear_editor()
        placeholder = QLabel(ui_text("ui_effect_loading"))
        placeholder.setFont(QFont("Segoe UI", 16))
        placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(placeholder)
        self._editor_layout.addStretch()

        def _worker():
            try:
                raw, result = parse_effectprm_xfbin(path)
                self._load_done_signal.emit(path, raw, result)
            except Exception as e:
                import traceback
                self._load_error_signal.emit(f"{e}\n{traceback.format_exc()}")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, path, raw, result):
        self._raw     = raw
        self._result  = result
        self._dirty   = False
        self._entries = [dict(e) for e in result['entries']]

        set_file_label(self._file_lbl, path)

        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)

        self._current_entry = None
        self._entry_buttons = []
        self._populate_list()
        if self._entries:
            self._select_entry(self._entries[0])

    def _on_load_error(self, msg):
        self._clear_editor()
        err_lbl = QLabel(ui_text("ui_effect_error_loading_file"))
        err_lbl.setFont(QFont("Segoe UI", 16))
        err_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        err_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(err_lbl)
        self._editor_layout.addStretch()
        self._file_lbl.setText(self.t("no_file_loaded"))
        QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), msg)

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _save_file(self):
        if self._filepath:
            self._do_save(self._filepath)

    def _do_save(self, path):
        try:
            self._apply_fields()
            self._result['entries'] = self._entries
            save_effectprm_xfbin(path, self._raw, self._result)
            self._filepath = path
            self._dirty    = False
            set_file_label(self._file_lbl, path)
            self._raw, self._result = parse_effectprm_xfbin(path)
            self._entries = [dict(e) for e in self._result['entries']]
            current_slot = self._current_entry['slot_id'] if self._current_entry else None
            self._current_entry = None
            self._fields = {}
            self._populate_list()
            if current_slot is not None:
                target = next((e for e in self._entries if e['slot_id'] == current_slot), None)
                if target:
                    self._select_entry(target)
                    return
            if self._entries:
                self._select_entry(self._entries[0])
        except Exception as e:
            import traceback
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_ASBR-Tools_value_value", p0=e, p1=traceback.format_exc()))
