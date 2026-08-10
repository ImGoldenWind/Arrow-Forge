"""editors/effect_editor.py  –  Editor for effectprm.bin.xfbin (Effect Param)."""

import os
import threading

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from core.style_helpers import (
    make_empty_state, make_editor_field_shell, make_editor_grid_card,
    ss_btn, ss_accent_sep, ss_input, ss_search, ss_sidebar_btn,
    ss_scrollarea, ss_scrollarea_transparent, ss_file_label,
    ss_sep, ss_transparent, ss_bg_dark, ss_bg_panel, ss_sidebar_frame,
    ss_accent_label, ss_dim_label, ss_main_label,
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
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _effect_title(entry):
    name = str(entry.get('effect_name') or '').strip()
    if name:
        return name
    return ui_text("ui_effect_slot_value", p0=entry.get('slot_id', 0))


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "..."


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
        self._last_compact: bool | None = None

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
        top.setStyleSheet(ss_bg_panel())
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
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        # Main area (sidebar + editor)
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(ss_sidebar_frame())
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search_entry)

        actions_frame = QWidget()
        actions_frame.setStyleSheet(ss_transparent())
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
        self._list_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_widget.setMinimumWidth(0)
        self._list_widget.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        list_vlayout.addWidget(self._list_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        # Right editor panel
        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)
        self._editor_scroll.setWidget(self._editor_widget)

        self._placeholder = make_empty_state(
            self._editor_widget,
            title=self.t("no_file_loaded"),
            text=ui_text("ui_effect_open_effectprm_bin_xfbin_to_begin_editing"),
            icon_name="fa6s.wand-magic-sparkles",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder, 0, Qt.AlignmentFlag.AlignCenter)
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
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(False))

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        title = _effect_title(entry)
        name_lbl = QLabel(_truncate(title, 24))
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label() if str(entry.get('effect_name') or '').strip() else ss_dim_label())
        name_lbl.setMinimumWidth(0)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        name_lbl.setToolTip(title)
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(name_lbl)

        id_text = ui_text("ui_effect_slot_value", p0=entry['slot_id'])
        id_lbl = QLabel(_truncate(id_text, 28))
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(ss_dim_label())
        id_lbl.setMinimumWidth(0)
        id_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        id_lbl.setToolTip(id_text)
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

    def _prep_field_widget(self, widget: QWidget):
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return widget

    def _add_editor_card(self, card: QFrame):
        self._editor_layout.addWidget(card)

    def _field_position(self, row: int, col: int) -> tuple[int, int]:
        columns = self._grid_columns(3)
        logical_index = row * 3 + col
        return divmod(logical_index, columns)

    def _add_section(self, title):
        self._pending_section_title = title

    def _make_field(self, label_text, value, font=None, accent=False, height=30, placeholder=None):
        frame, layout, _label, _hint = make_editor_field_shell(label_text)
        self._prep_field_widget(frame)

        e = QLineEdit()
        e.setFixedHeight(height)
        e.setMinimumWidth(0)
        e.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        e.setFont(font or QFont("Consolas", 13))
        e.setStyleSheet(ss_input())
        if accent:
            _label.setStyleSheet(ss_accent_label())

        if placeholder and str(value) == "":
            e.setPlaceholderText(placeholder)
        e.setText(str(value))
        e.setCursorPosition(0)
        layout.addWidget(e)
        return frame, e

    def _build_editor(self, entry):
        self._clear_editor()
        self._fields = {}
        self._last_compact = self._is_compact_editor()
        title = _effect_title(entry)
        title_limit = 22 if self._last_compact else 50
        name_font = QFont("Segoe UI", 15 if self._last_compact else 18, QFont.Weight.Bold)
        name_height = 34 if self._last_compact else 36

        # Header card: Effect Name + Slot ID + Xfbins Count
        hdr, hdr_grid = make_editor_grid_card(
            self._editor_widget,
            title=_truncate(title, title_limit),
            icon_name="fa6s.wand-magic-sparkles",
            subtitle=ui_text("ui_effect_slot_value", p0=entry['slot_id']),
            grid_margins=(0, 2, 0, 0),
            vertical_spacing=8,
        )
        self._prep_card(hdr)

        name_frame, e_name = self._make_field(
            ui_text("ui_effect_effect_name"), entry['effect_name'],
            font=name_font,
            accent=True, height=name_height,
            placeholder=title,
        )
        row, col = self._field_position(0, 0)
        hdr_grid.addWidget(name_frame, row, col)
        hdr_grid.setColumnStretch(col, 2)
        self._fields['effect_name'] = e_name

        slot_frame, e_slot = self._make_field(
            ui_text("ui_effect_slot_id"), entry['slot_id'],
            font=QFont("Consolas", 16), height=36,
        )
        row, col = self._field_position(0, 1)
        hdr_grid.addWidget(slot_frame, row, col)
        hdr_grid.setColumnStretch(col, 1)
        self._fields['slot_id'] = e_slot

        count_frame, e_count = self._make_field(
            ui_text("ui_effect_xfbins_count"), entry['xfbins_count'],
            font=QFont("Consolas", 16), height=36,
        )
        row, col = self._field_position(0, 2)
        hdr_grid.addWidget(count_frame, row, col)
        hdr_grid.setColumnStretch(col, 1)
        self._fields['xfbins_count'] = e_count

        self._add_editor_card(hdr)

        # XFBIN Path section
        self._add_section(ui_text("ui_effect_xfbin_path"))
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        path_card, path_grid = make_editor_grid_card(
            self._editor_widget,
            title=section_title,
            icon_name="fa6s.folder-open",
            grid_margins=(0, 4, 0, 0),
            vertical_spacing=10,
        )
        self._prep_card(path_card)

        path_frame, e_path = self._make_field(
            ui_text("ui_effect_xfbin_path"), entry['xfbin_path'],
            placeholder=ui_text("xfa_no_file"),
        )
        path_grid.addWidget(path_frame, 0, 0)
        path_grid.setColumnStretch(0, 1)
        self._fields['xfbin_path'] = e_path

        self._add_editor_card(path_card)

        # Connect signals after all setText calls to avoid false dirty triggers
        e_name.textChanged.connect(self._mark_dirty)
        e_slot.textChanged.connect(self._mark_dirty)
        e_count.textChanged.connect(self._mark_dirty)
        e_path.textChanged.connect(self._mark_dirty)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_entry is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_entry is None:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        self._apply_fields()
        self._build_editor(self._current_entry)

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
                    title = _effect_title(entry)
                    labels[0].setText(_truncate(title, 24))
                    labels[0].setStyleSheet(ss_main_label() if entry['effect_name'] else ss_dim_label())
                    labels[0].setToolTip(title)
                    id_text = ui_text("ui_effect_slot_value", p0=entry['slot_id'])
                    labels[1].setText(_truncate(id_text, 28))
                    labels[1].setToolTip(id_text)
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
            ui_text("ui_effect_delete_value", p0=_effect_title(self._current_entry))
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
        self._file_lbl.setStyleSheet(ss_file_label())
        self._current_entry = None
        self._entry_buttons = []
        self._fields = {}
        self._clear_list()
        self._clear_editor()
        placeholder = make_empty_state(
            self._editor_widget,
            title=ui_text("ui_effect_loading"),
            text=name,
            icon_name="fa6s.spinner",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(placeholder, 0, Qt.AlignmentFlag.AlignCenter)
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
        err_lbl = make_empty_state(
            self._editor_widget,
            title=ui_text("ui_effect_error_loading_file"),
            text=msg,
            icon_name="fa6s.triangle-exclamation",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(err_lbl, 0, Qt.AlignmentFlag.AlignCenter)
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
