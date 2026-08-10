"""editors/constparam_editor.py  –  Editor for *_constParam.xfbin files."""

import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from core.style_helpers import (
    ss_btn, ss_sep, ss_accent_sep, ss_input, ss_search, ss_scrollarea, ss_scrollarea_transparent,
    ss_sidebar_btn, ss_file_label, ss_transparent,
    ss_bg_dark, ss_bg_panel, ss_sidebar_frame, ss_main_label,
    make_empty_state, make_editor_field_shell, make_editor_grid_card,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.constparam_parser import parse_constparam_xfbin, save_constparam_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            w = item.widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


class ConstParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath = None
        self._original_data = None
        self._params = []
        self._dirty = False
        self._current_idx = -1
        self._param_buttons = []
        self._name_field = None
        self._value_field = None
        self._last_compact = None
        self._active_grid_columns = 2

        self._build_ui()

    # UI construction

    def _tr(self, key, fallback):
        value = self._t(key)
        return fallback if value == key else value

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

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        tl.addWidget(self._btn_save)

        self._file_lbl = QLabel(self._tr("no_file_loaded", ui_text("cpk_no_file")))
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
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(ss_sidebar_frame())
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 8, 8, 4)
        sl.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self._tr("search_placeholder", ui_text("search_placeholder")))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont(P.get("font_ui", "Segoe UI"), 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(self._filter_list)
        sl.addWidget(self._search_entry)

        abf = QWidget()
        abf.setStyleSheet(ss_transparent())
        abl = QHBoxLayout(abf)
        abl.setContentsMargins(0, 2, 0, 4)
        abl.setSpacing(4)
        bf = QFont(P.get("font_ui", "Segoe UI"), 10)

        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(bf)
        self._btn_add.setEnabled(False)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.clicked.connect(self._on_add)
        abl.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(bf)
        self._btn_dup.setEnabled(False)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.clicked.connect(self._on_dup)
        abl.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(bf)
        self._btn_del.setEnabled(False)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.clicked.connect(self._on_delete)
        abl.addWidget(self._btn_del, 1)

        sl.addWidget(abf)

        self._param_scroll = QScrollArea()
        self._param_scroll.setWidgetResizable(True)
        self._param_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._param_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._param_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._param_list_widget = QWidget()
        self._param_list_widget.setMinimumWidth(0)
        self._param_list_widget.setStyleSheet(ss_transparent())
        self._param_list_layout = QVBoxLayout(self._param_list_widget)
        self._param_list_layout.setContentsMargins(0, 0, 0, 0)
        self._param_list_layout.setSpacing(1)
        self._param_list_layout.addStretch()
        self._param_scroll.setWidget(self._param_list_widget)
        sl.addWidget(self._param_scroll)

        main_layout.addWidget(sidebar)

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        main_layout.addWidget(div)

        # Right panel
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

        self._set_editor_placeholder(ui_text("ui_constparam_open_a_constparam_xfbin_file_to_begin"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # Helpers

    def _set_editor_placeholder(self, text):
        _clear_layout(self._editor_layout)
        title = self._tr("no_file_loaded", ui_text("no_file_loaded")) if self._filepath is None else ui_text("ui_model_viewer_select_item")
        card = make_empty_state(
            self._editor_widget,
            title=title,
            text=text,
            icon_name="fa6s.sliders",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    # Data

    def _load_file(self, filepath):
        create_backup_on_open(filepath)
        try:
            data, params = parse_constparam_xfbin(filepath)
        except Exception as e:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=e))
            return

        self._filepath = filepath
        self._original_data = data
        self._params = params
        self._dirty = False
        self._current_idx = -1

        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)

        self._populate_list()
        if self._params:
            self._select_param(0)
        else:
            self._set_editor_placeholder(ui_text("ui_constparam_no_parameters_found"))

    def _populate_list(self):
        _clear_layout(self._param_list_layout)
        self._param_buttons = []
        for i, p in enumerate(self._params):
            btn = self._make_param_button(p, i)
            self._param_list_layout.addWidget(btn)
            self._param_buttons.append((btn, i))
        self._param_list_layout.addStretch()

    def _make_param_button(self, p, idx):
        name = p['name']
        btn = QPushButton()
        btn.setFixedHeight(36)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))
        bl = QVBoxLayout(btn)
        bl.setContentsMargins(10, 4, 10, 4)
        bl.setSpacing(0)
        lbl = QLabel(_truncate(name, 16))
        lbl.setFont(QFont(P.get("font_ui", "Segoe UI"), 12, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_main_label())
        lbl.setMinimumWidth(0)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lbl.setToolTip(name)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(lbl)
        btn.clicked.connect(lambda checked=False, i=idx: self._select_param(i))
        return btn

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, i in self._param_buttons:
            if i >= len(self._params):
                continue
            btn.setVisible(query in self._params[i]['name'].lower())

    def _select_param(self, idx):
        self._current_idx = idx
        for btn, i in self._param_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))
        self._build_editor(idx)

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

    def _field_position(self, row: int, col: int, max_columns: int) -> tuple[int, int]:
        columns = self._grid_columns(max_columns)
        logical_index = row * max_columns + col
        return divmod(logical_index, columns)

    def _build_editor(self, idx):
        _clear_layout(self._editor_layout)
        if idx < 0 or idx >= len(self._params):
            card = make_empty_state(
                self._editor_widget,
                title=ui_text("ui_model_viewer_select_item"),
                text=ui_text("ui_constparam_select_a_parameter"),
                icon_name="fa6s.sliders",
            )
            self._editor_layout.addStretch()
            self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
            self._editor_layout.addStretch()
            return

        p = self._params[idx]
        self._last_compact = self._is_compact_editor()
        card_title = _truncate(p['name'], 24 if self._last_compact else 72)

        card, grid = make_editor_grid_card(
            self._editor_widget,
            title=card_title,
            icon_name="fa6s.sliders",
            subtitle=ui_text("ui_constparam_value"),
            grid_margins=(0, 2, 0, 0),
            vertical_spacing=10,
        )
        self._prep_card(card)
        self._active_grid_columns = 2

        # Name field
        nf, nfl, _label, _hint = make_editor_field_shell(ui_text("bone_col_name"))
        self._prep_field_widget(nf)
        self._name_field = QLineEdit(p['name'])
        self._name_field.setFixedHeight(30)
        self._name_field.setFont(QFont("Consolas", 13))
        self._name_field.setStyleSheet(ss_input())
        self._name_field.setMinimumWidth(0)
        self._name_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._name_field.setCursorPosition(0)
        self._name_field.editingFinished.connect(lambda i=idx: self._commit_name(i))
        nfl.addWidget(self._name_field)
        row, col = self._field_position(0, 0, self._active_grid_columns)
        grid.addWidget(nf, row, col)
        grid.setColumnStretch(col, 1)

        # Value field
        vf, vfl, _label, _hint = make_editor_field_shell(ui_text("ui_constparam_value"))
        self._prep_field_widget(vf)
        self._value_field = QLineEdit(p['value'])
        self._value_field.setFixedHeight(30)
        self._value_field.setFont(QFont("Consolas", 13))
        self._value_field.setStyleSheet(ss_input())
        self._value_field.setMinimumWidth(0)
        self._value_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._value_field.setCursorPosition(0)
        self._value_field.editingFinished.connect(lambda i=idx: self._commit_value(i))
        vfl.addWidget(self._value_field)
        row, col = self._field_position(0, 1, self._active_grid_columns)
        grid.addWidget(vf, row, col)
        grid.setColumnStretch(col, 1)

        self._editor_layout.addWidget(card)
        self._editor_layout.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx >= 0 and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx < 0:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        self._build_editor(self._current_idx)

    def _commit_name(self, idx):
        if self._name_field is None or idx < 0 or idx >= len(self._params):
            return
        new_name = self._name_field.text()
        self._params[idx]['name'] = new_name
        for btn, i in self._param_buttons:
            if i == idx:
                lbls = btn.findChildren(QLabel)
                if lbls:
                    lbls[0].setText(_truncate(new_name, 16))
                    lbls[0].setToolTip(new_name)
                break
        self._mark_dirty()

    def _commit_value(self, idx):
        if self._value_field is None or idx < 0 or idx >= len(self._params):
            return
        self._params[idx]['value'] = self._value_field.text()
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(True)
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    # File I/O

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_constparam_open_constparam_xfbin"), game_files_dialog_dir(target_patterns="*constParam.xfbin"),
            "XFBIN Files (*constParam.xfbin);;All Files (*.*)"
        )
        if path:
            self._load_file(path)

    def _on_save(self):
        if not self._filepath or self._original_data is None:
            return
        try:
            save_constparam_xfbin(self._filepath, self._original_data, self._params)
            self._dirty = False
            name = os.path.basename(self._filepath)
            set_file_label(self._file_lbl, self._filepath)
            QMessageBox.information(self, ui_text("ui_assist_saved"), ui_text("ui_assist_file_saved_value", p0=name))
        except Exception as e:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=e))

    # Add / Dup / Delete

    def _on_add(self):
        self._params.append({'name': 'new_param', 'value': '0'})
        self._current_idx = len(self._params) - 1
        self._populate_list()
        self._mark_dirty()
        self._select_param(self._current_idx)

    def _on_dup(self):
        if self._current_idx < 0 or self._current_idx >= len(self._params):
            return
        new_param = copy.deepcopy(self._params[self._current_idx])
        new_idx = self._current_idx + 1
        self._params.insert(new_idx, new_param)
        self._current_idx = new_idx
        self._populate_list()
        self._mark_dirty()
        self._select_param(new_idx)

    def _on_delete(self):
        if self._current_idx < 0 or self._current_idx >= len(self._params):
            return
        if len(self._params) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_constparam_cannot_delete_the_last_parameter"))
            return
        name = self._params[self._current_idx]['name']
        result = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"), ui_text("ui_constparam_delete_parameter_value", p0=name)
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        del self._params[self._current_idx]
        new_idx = min(self._current_idx, len(self._params) - 1)
        self._current_idx = -1
        self._populate_list()
        self._mark_dirty()
        self._select_param(new_idx)
