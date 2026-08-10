import copy
import math
import os

from PyQt6.QtCore import QRegularExpression, Qt, QTimer
from PyQt6.QtGui import QFont, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    make_empty_state,
    make_editor_grid_card,
    make_editor_field_shell,
    ss_accent_sep,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
    ss_dim_label,
    ss_file_label,
    ss_input,
    ss_main_label,
    ss_panel,
    ss_placeholder,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_search,
    ss_sep,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_transparent,
)
from core.translations import ui_text
from parsers.duelsettingparam_parser import (
    make_default_entry,
    parse_duelsettingparam_xfbin,
    save_duelsettingparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF
_FLOAT_MIN = -3.4028234663852886e38
_FLOAT_MAX = 3.4028234663852886e38


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


class DuelSettingParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._result: dict | None = None
        self._entries: list[dict] = []
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._current_idx: int | None = None
        self._fields: dict[str, QLineEdit | QComboBox] = {}
        self._entry_count_label: QLabel | None = None
        self._dirty = False
        self._loading_detail = False
        self._last_compact: bool | None = None
        self._active_grid_columns = 3

        self._uint32_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._float_validator = QRegularExpressionValidator(
            QRegularExpression(r"[-+]?(?:\d+\.?\d*|\.\d+)?(?:[eE][-+]?\d+)?"),
            self,
        )

        self._build_ui()

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if value == key and fallback is not None else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(ss_bg_dark())

        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._do_open)
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._do_save)
        top_layout.addWidget(self._btn_save)

        self._file_label = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(ss_sidebar_frame())
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 4)
        sidebar_layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(self._tr("search_placeholder", ui_text("search_placeholder")))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)

        actions = QWidget()
        actions.setStyleSheet(ss_transparent())
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        self._btn_add = self._make_action_button("btn_new", self._do_add)
        self._btn_dup = self._make_action_button("btn_duplicate", self._do_dup)
        self._btn_del = self._make_action_button("btn_delete", self._do_del, danger=True)
        actions_layout.addWidget(self._btn_add, 1)
        actions_layout.addWidget(self._btn_dup, 1)
        actions_layout.addWidget(self._btn_del, 1)
        sidebar_layout.addWidget(actions)

        self._entry_scroll = QScrollArea()
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._entry_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setMinimumWidth(0)
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(1)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        sidebar_layout.addWidget(self._entry_scroll, 1)
        main_layout.addWidget(sidebar)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

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
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_duelsettingparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)
        self._update_actions()

    def _make_action_button(self, key: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(self._tr(key, ui_text(key)))
        btn.setFixedHeight(28)
        btn.setFont(QFont("Segoe UI", 10))
        btn.setEnabled(False)
        btn.setStyleSheet(ss_btn(danger=danger))
        btn.clicked.connect(slot)
        return btn

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._entry_count_label = None
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_duelsettingparam_open_title"),
            game_files_dialog_dir(target_patterns=("DuelSettingParam.bin.xfbin", "DuelSettingsParam.bin.xfbin")),
            ui_text("ui_duelsettingparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        try:
            raw, result = parse_duelsettingparam_xfbin(path)
        except Exception as exc:
            self._filepath = None
            self._raw_data = None
            self._result = None
            self._entries = []
            self._current_idx = None
            self._clear_entry_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_duelsettingparam_open_file_to_begin_editing"))
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._entries = result["entries"]
        self._current_idx = None
        self._dirty = False
        self._btn_save.setEnabled(False)
        self._search.setText("")
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_duelsettingparam_no_entries"))
        self._update_actions()

    def _do_save(self):
        if not self._filepath or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_duelsettingparam_xfbin(self._filepath, self._raw_data, self._result)
            with open(self._filepath, "rb") as fh:
                self._raw_data = bytearray(fh.read())
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, self._filepath)
            QMessageBox.information(
                self,
                ui_text("dlg_title_success"),
                ui_text("msg_save_success", path=os.path.basename(self._filepath)),
            )
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []

    def _populate_list(self):
        self._clear_entry_list()
        for idx, entry in enumerate(self._entries):
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_idx))

        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(0)

        title_text = self._entry_title(idx, entry)
        subtitle_text = self._entry_subtitle(entry)

        title = QLabel(_truncate(title_text, 24))
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        title.setToolTip(title_text)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)

        subtitle = QLabel(_truncate(subtitle_text, 28))
        subtitle.setFont(QFont("Consolas", 11))
        subtitle.setStyleSheet(ss_dim_label())
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        subtitle.setToolTip(subtitle_text)
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        title = entry.get("title_key", "") or ui_text("ui_duelsettingparam_empty_text_key")
        return ui_text("ui_duelsettingparam_entry_title", title=title)

    def _entry_subtitle(self, entry: dict) -> str:
        condition = entry.get("condition_id", "") or ui_text("ui_duelsettingparam_no_condition")
        return ui_text(
            "ui_duelsettingparam_entry_subtitle",
            type_id=int(entry.get("type_id", 0)),
            sequence=int(entry.get("sequence_id", 0)),
            condition=condition,
        )

    def _filter_list(self):
        query = self._search.text().lower().strip()
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join([
                str(idx),
                str(entry.get("type_id", "")),
                str(entry.get("sequence_id", "")),
                str(entry.get("title_key", "")),
                str(entry.get("hidden_title_key", "")),
                str(entry.get("hint_key", "")),
                str(entry.get("condition_id", "")),
                str(entry.get("target_names", "")),
            ]).lower()
            btn.setVisible(not query or query in haystack)

    def _select_entry(self, idx: int):
        if idx < 0 or idx >= len(self._entries):
            return
        if not self._apply_current_entry(show_errors=True):
            return
        self._current_idx = idx
        for btn, button_idx in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=button_idx == idx))
        self._build_editor(idx)
        self._update_actions()

    def _refresh_entry_button(self, idx: int):
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if labels:
                title_text = self._entry_title(idx, self._entries[idx])
                labels[0].setText(_truncate(title_text, 24))
                labels[0].setToolTip(title_text)
            if len(labels) >= 2:
                subtitle_text = self._entry_subtitle(self._entries[idx])
                labels[1].setText(_truncate(subtitle_text, 28))
                labels[1].setToolTip(subtitle_text)
            break
        self._filter_list()

    def _update_actions(self):
        loaded = self._raw_data is not None
        has_selection = self._current_idx is not None and 0 <= self._current_idx < len(self._entries)
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and has_selection)
        self._btn_del.setEnabled(loaded and has_selection)
        self._btn_save.setEnabled(loaded and self._dirty)
        if self._entry_count_label is not None:
            self._entry_count_label.setText(ui_text("ui_duelsettingparam_entry_count_value", count=len(self._entries)))

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._entry_count_label = None
        self._loading_detail = True
        entry = self._entries[idx]
        self._last_compact = self._is_compact_editor()
        title = _truncate(self._entry_title(idx, entry), 30 if self._last_compact else 86)
        summary = _truncate(self._entry_subtitle(entry), 38 if self._last_compact else 92)

        header, header_layout = make_editor_grid_card(
            self._editor_widget,
            title=title,
            icon_name="fa6s.flag-checkered",
            subtitle=summary,
            grid_margins=(0, 2, 0, 0),
            vertical_spacing=8,
        )
        self._prep_card(header)
        self._active_grid_columns = 3

        self._add_combo_field(header_layout, 0, 0, "type_id", ui_text("ui_duelsettingparam_type_id"), entry.get("type_id", 0), [(str(value), value) for value in range(5)], big=True)
        self._add_uint_field(header_layout, 0, 1, "sequence_id", ui_text("ui_duelsettingparam_sequence_id"), entry.get("sequence_id", 0), big=True)
        self._add_float_field(header_layout, 0, 2, "value_1", ui_text("ui_duelsettingparam_value_1"), self._entry_value(entry, 0), big=True)
        self._add_hint(header_layout, 1, 0, ui_text("ui_duelsettingparam_type_hint"))
        self._add_hint(header_layout, 1, 1, ui_text("ui_duelsettingparam_sequence_hint"))
        self._add_hint(header_layout, 1, 2, ui_text("ui_duelsettingparam_value_hint"))
        self._editor_layout.addWidget(header)

        self._add_section(ui_text("ui_duelsettingparam_text_keys"))
        text_card = self._make_card()
        text_grid = self._card_grid(text_card)
        self._active_grid_columns = 3
        self._add_text_field(text_grid, 0, 0, "title_key", ui_text("ui_duelsettingparam_title_key"), entry.get("title_key", ""))
        self._add_text_field(text_grid, 0, 1, "hidden_title_key", ui_text("ui_duelsettingparam_hidden_title_key"), entry.get("hidden_title_key", ""))
        self._add_text_field(text_grid, 0, 2, "hint_key", ui_text("ui_duelsettingparam_hint_key"), entry.get("hint_key", ""))
        self._editor_layout.addWidget(text_card)

        self._add_section(ui_text("ui_duelsettingparam_conditions"))
        cond_card = self._make_card()
        cond_grid = self._card_grid(cond_card)
        self._active_grid_columns = 2
        self._add_text_field(cond_grid, 0, 0, "condition_id", ui_text("ui_duelsettingparam_condition_id"), entry.get("condition_id", ""))
        self._add_text_field(cond_grid, 0, 1, "target_names", ui_text("ui_duelsettingparam_target_names"), entry.get("target_names", ""))
        self._add_hint(cond_grid, 1, 0, ui_text("ui_duelsettingparam_condition_hint"), colspan=self._grid_columns(2), max_columns=2)
        self._editor_layout.addWidget(cond_card)

        if not self._raw_values_are_zero(entry):
            self._add_section(ui_text("ui_duelsettingparam_raw_values"))
            raw_card = self._make_card()
            raw_grid = self._card_grid(raw_card)
            self._active_grid_columns = 3
            self._add_float_field(raw_grid, 0, 0, "value_2", ui_text("ui_duelsettingparam_value_2"), self._entry_value(entry, 1))
            self._add_float_field(raw_grid, 0, 1, "value_3", ui_text("ui_duelsettingparam_value_3"), self._entry_value(entry, 2))
            self._add_float_field(raw_grid, 0, 2, "value_4", ui_text("ui_duelsettingparam_value_4"), self._entry_value(entry, 3))
            self._add_uint_field(raw_grid, 2, 0, "reserved_24", ui_text("ui_duelsettingparam_reserved_24"), entry.get("reserved_24", 0))
            self._add_uint_field(raw_grid, 2, 1, "reserved_28", ui_text("ui_duelsettingparam_reserved_28"), entry.get("reserved_28", 0))
            self._add_hint(raw_grid, 1, 0, ui_text("ui_duelsettingparam_value_hint"), colspan=3)
            self._add_hint(raw_grid, 3, 0, ui_text("ui_duelsettingparam_reserved_hint"), colspan=2)
            self._editor_layout.addWidget(raw_card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _entry_value(self, entry: dict, idx: int) -> float:
        values = list(entry.get("values", [0.0, 0.0, 0.0, 0.0]))
        values += [0.0] * (4 - len(values))
        return float(values[idx])

    def _raw_values_are_zero(self, entry: dict) -> bool:
        return (
            abs(self._entry_value(entry, 1)) <= 1e-9
            and abs(self._entry_value(entry, 2)) <= 1e-9
            and abs(self._entry_value(entry, 3)) <= 1e-9
            and int(entry.get("reserved_24", 0)) == 0
            and int(entry.get("reserved_28", 0)) == 0
        )

    def _add_section(self, title: str):
        self._pending_section_title = title

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

    def _field_position(self, row: int, col: int, max_columns: int) -> tuple[int, int]:
        columns = self._grid_columns(max_columns)
        logical_index = row * max_columns + col
        return divmod(logical_index, columns)

    def _prep_card(self, card: QFrame):
        card.setMinimumWidth(0)
        card.setMaximumWidth(980)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def _prep_field_widget(self, frame: QWidget, editor: QWidget):
        frame.setMinimumWidth(0)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor.setMinimumWidth(0)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def _make_card(self) -> QFrame:
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(
            self._editor_widget,
            title=section_title,
            icon_name="fa6s.sliders",
            vertical_spacing=10,
        )
        self._prep_card(card)
        card._editor_grid = grid
        return card

    def _card_grid(self, card: QFrame) -> QGridLayout:
        return card._editor_grid

    def _field_shell(self, label: str) -> tuple[QWidget, QVBoxLayout]:
        frame, layout, _label, _hint = make_editor_field_shell(label)
        return frame, layout

    def _add_hint(self, grid, row: int, col: int, text: str, colspan: int = 1, max_columns: int | None = None):
        hint = QLabel(text)
        hint.setWordWrap(True)
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet(ss_dim_label())
        hint.setMinimumWidth(0)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        max_cols = max_columns or getattr(self, "_active_grid_columns", 3)
        mapped_row, mapped_col = self._field_position(row, col, max_cols)
        grid.addWidget(hint, mapped_row, mapped_col, 1, colspan)

    def _add_text_field(self, grid, row, col, key, label, value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(value))
        edit.setCursorPosition(0)
        edit.textChanged.connect(lambda _text, k=key: self._on_text_changed(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def _add_uint_field(self, grid, row, col, key, label, value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._uint32_validator)
        edit.setMaxLength(10)
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key: self._on_uint_finished(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def _add_combo_field(self, grid, row, col, key, label, value, options, big=False):
        frame, layout = self._field_shell(label)
        combo = QComboBox()
        combo.setFixedHeight(36 if big else 30)
        combo.setFont(QFont("Consolas", 16 if big else 13))
        combo.setStyleSheet(ss_input())
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for text, data in options:
            combo.addItem(text, data)
        selected = combo.findData(int(value))
        combo.setCurrentIndex(max(0, selected))
        combo.currentIndexChanged.connect(lambda _idx, k=key: self._on_combo_changed(k))
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = combo

    def _add_float_field(self, grid, row, col, key, label, value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._float_validator)
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(f"{float(value):.9g}")
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key: self._on_float_finished(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx is None or self._loading_detail:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        self._build_editor(self._current_idx)

    def _on_text_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        if key == "notes_hex":
            self._mark_dirty()
            return
        self._entries[self._current_idx][key] = self._fields[key].text().strip()
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)

    def _on_numeric_text_changed(self):
        if not self._loading_detail:
            self._mark_dirty()

    def _on_combo_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        widget = self._fields.get(key)
        if not isinstance(widget, QComboBox):
            return
        self._entries[self._current_idx][key] = int(widget.currentData())
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)

    def _on_uint_finished(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._read_uint(key, show_errors=True)
        if value is None:
            return
        if key == "version":
            if self._result is not None:
                self._result["version"] = value
            return
        self._entries[self._current_idx][key] = value
        self._refresh_entry_button(self._current_idx)

    def _on_float_finished(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._read_float(key, show_errors=True)
        if value is None:
            return
        value_idx = int(key.rsplit("_", 1)[1]) - 1
        values = list(self._entries[self._current_idx].get("values", [0.0, 0.0, 0.0, 0.0]))
        values += [0.0] * (4 - len(values))
        values[value_idx] = value
        self._entries[self._current_idx]["values"] = values[:4]

    def _read_ascii(self, key: str, show_errors: bool = False) -> str | None:
        widget = self._fields.get(key)
        if widget is None:
            return ""
        text = widget.text().strip()
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_duelsettingparam_ascii_only", field=ui_text(f"ui_duelsettingparam_{key}")),
                )
            return None
        return text

    def _read_uint(self, key: str, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        if isinstance(widget, QComboBox):
            return int(widget.currentData())
        text = widget.text().strip()
        try:
            value = int(text or "0")
        except ValueError:
            value = _UINT32_MAX + 1
        if value < 0 or value > _UINT32_MAX:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_duelsettingparam_invalid_integer", value=text, min=0, max=_UINT32_MAX),
                )
            return None
        return value

    def _read_float(self, key: str, show_errors: bool = False) -> float | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        if isinstance(widget, QComboBox):
            return float(widget.currentData())
        text = widget.text().strip()
        try:
            value = float(text or "0")
        except ValueError:
            value = math.inf
        if not math.isfinite(value) or value < _FLOAT_MIN or value > _FLOAT_MAX:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_duelsettingparam_invalid_float", value=text),
                )
            return None
        return value

    def _notes_hex(self) -> str:
        if not self._result:
            return ""
        return " ".join(f"{byte:02X}" for byte in bytes(self._result.get("notes", b"")))

    def _read_notes_hex(self, show_errors: bool = False) -> bytes | None:
        widget = self._fields.get("notes_hex")
        if widget is None:
            return b""
        text = widget.text().strip().replace(" ", "")
        if not text:
            return b""
        try:
            return bytes.fromhex(text)
        except ValueError:
            if show_errors:
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_duelsettingparam_invalid_hex"))
            return None

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._current_idx is None:
            return True
        entry = self._entries[self._current_idx]
        if self._result is not None and "version" in self._fields:
            version = self._read_uint("version", show_errors=show_errors)
            if version is None:
                return False
            self._result["version"] = version
        if self._result is not None and "notes_hex" in self._fields:
            notes = self._read_notes_hex(show_errors=show_errors)
            if notes is None:
                return False
            self._result["notes"] = notes

        for key in ("title_key", "hidden_title_key", "hint_key", "condition_id", "target_names"):
            value = self._read_ascii(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        for key in ("type_id", "sequence_id", "reserved_24", "reserved_28"):
            if key not in self._fields:
                continue
            value = self._read_uint(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        values = list(entry.get("values", [0.0, 0.0, 0.0, 0.0]))
        values += [0.0] * (4 - len(values))
        for idx, key in enumerate(("value_1", "value_2", "value_3", "value_4")):
            if key not in self._fields:
                continue
            value = self._read_float(key, show_errors=show_errors)
            if value is None:
                return False
            values[idx] = value
        entry["values"] = values[:4]
        self._refresh_entry_button(self._current_idx)
        return True

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            if self._filepath:
                set_file_label(self._file_label, self._filepath, dirty=True)
        self._update_actions()

    def _do_add(self):
        if self._raw_data is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        self._entries.append(make_default_entry())
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._select_entry(len(self._entries) - 1)

    def _do_dup(self):
        if self._raw_data is None or self._current_idx is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        self._entries.insert(self._current_idx + 1, make_default_entry(copy.deepcopy(self._entries[self._current_idx])))
        new_idx = self._current_idx + 1
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._select_entry(new_idx)

    def _do_del(self):
        if self._raw_data is None or self._current_idx is None:
            return
        entry = self._entries[self._current_idx]
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("msg_confirm_delete_item", name=self._entry_title(self._current_idx, entry)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        old_idx = self._current_idx
        self._entries.pop(old_idx)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        if self._entries:
            self._select_entry(min(old_idx, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text("ui_duelsettingparam_no_entries"))
            self._update_actions()
