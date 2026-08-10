import copy
import os

from PyQt6.QtCore import QRegularExpression, Qt, QTimer
from PyQt6.QtGui import QFont, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
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
    add_editor_card_title,
    make_empty_state,
    make_editor_grid_card,
    make_editor_field_shell,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
    ss_accent_sep,
    ss_dim_label,
    ss_field_label,
    ss_file_label,
    ss_input,
    ss_main_label,
    ss_panel,
    ss_editor_card,
    ss_placeholder,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_search,
    ss_section_label,
    ss_sep,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_transparent,
)
from core.translations import ui_text
from parsers.netresultparam_parser import (
    make_default_entry,
    parse_netresultparam_xfbin,
    save_netresultparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF
_INT32_MIN = -0x80000000
_INT32_MAX = 0x7FFFFFFF
_BASE_VALUE_COUNT = 5


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


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


class NetResultParamEditor(QWidget):
    """Embedded editor for NetResultParam.bin.xfbin."""

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
        self._fields: dict[str, QLineEdit] = {}
        self._entry_count_label: QLabel | None = None
        self._dirty = False
        self._loading_detail = False
        self._last_compact: bool | None = None
        self._active_grid_columns = 3

        self._uint_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._int_validator = QRegularExpressionValidator(QRegularExpression(r"-?\d{0,10}"), self)

        self._build_ui()

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        if value == key and fallback is not None:
            return fallback
        return value

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
        sidebar.setFixedWidth(290)
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
        btn_font = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(btn_font)
        self._btn_add.setEnabled(False)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.clicked.connect(self._do_add)
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(btn_font)
        self._btn_dup.setEnabled(False)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.clicked.connect(self._do_dup)
        actions_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(btn_font)
        self._btn_del.setEnabled(False)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.clicked.connect(self._do_del)
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

        self._show_placeholder(ui_text("ui_netresultparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)

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
            ui_text("ui_netresultparam_open_title"),
            game_files_dialog_dir(target_patterns=("NetResultParam.bin.xfbin", "NetResultParam.xfbin")),
            ui_text("ui_netresultparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        try:
            raw, result = parse_netresultparam_xfbin(path)
        except Exception as exc:
            self._filepath = None
            self._raw_data = None
            self._result = None
            self._entries = []
            self._current_idx = None
            self._clear_entry_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_netresultparam_open_file_to_begin_editing"))
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._entries = result["entries"]
        self._current_idx = None
        self._dirty = False
        self._btn_add.setEnabled(True)
        self._btn_save.setEnabled(False)
        self._search.setText("")
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_netresultparam_no_entries"))
        self._update_actions()

    def _do_save(self):
        if not self._filepath or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_netresultparam_xfbin(self._filepath, self._raw_data, self._result)
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

        title_text = self._entry_title(idx)
        button_title = self._entry_button_title(idx)
        subtitle_text = self._entry_subtitle(entry)
        button_subtitle = self._entry_button_subtitle(entry)

        title = QLabel(_truncate(button_title, 21))
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        title.setToolTip(title_text)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)

        subtitle = QLabel(_truncate(button_subtitle, 25))
        subtitle.setFont(QFont("Consolas", 11))
        subtitle.setStyleSheet(ss_dim_label())
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        subtitle.setToolTip(subtitle_text)
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int) -> str:
        if idx < _BASE_VALUE_COUNT:
            return ui_text("ui_netresultparam_group_base")
        return ui_text("ui_netresultparam_group_difference")

    def _entry_button_title(self, idx: int) -> str:
        if idx < _BASE_VALUE_COUNT:
            return "BASE RESULT"
        return "RANK DIFF"

    def _entry_subtitle(self, entry: dict) -> str:
        return ui_text(
            "ui_netresultparam_entry_subtitle",
            threshold=entry.get("threshold", 0),
            value=entry.get("value", 0),
        )

    def _entry_button_subtitle(self, entry: dict) -> str:
        return f"T {entry.get('threshold', 0)} / V {entry.get('value', 0)}"

    def _filter_list(self):
        query = self._search.text().lower().strip()
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join([
                str(idx),
                self._entry_title(idx),
                str(entry.get("threshold", "")),
                str(entry.get("value", "")),
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
        if idx < 0 or idx >= len(self._entries):
            return
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if len(labels) >= 2:
                title_text = self._entry_title(idx)
                button_title = self._entry_button_title(idx)
                subtitle_text = self._entry_subtitle(self._entries[idx])
                button_subtitle = self._entry_button_subtitle(self._entries[idx])
                labels[0].setText(_truncate(button_title, 21))
                labels[0].setToolTip(title_text)
                labels[1].setText(_truncate(button_subtitle, 25))
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
            self._entry_count_label.setText(ui_text("ui_netresultparam_entry_count_value", count=len(self._entries)))

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._entry_count_label = None
        self._loading_detail = True
        entry = self._entries[idx]
        self._last_compact = self._is_compact_editor()

        header, header_layout = make_editor_grid_card(
            self._editor_widget,
            title=self._entry_title(idx),
            icon_name="fa6s.chart-line",
            subtitle=self._entry_subtitle(entry),
            grid_margins=(0, 0, 0, 0),
            vertical_spacing=8,
        )
        self._prep_card(header)
        self._active_grid_columns = 3

        self._add_int_field(
            header_layout,
            0,
            0,
            "threshold",
            ui_text("ui_netresultparam_threshold"),
            entry.get("threshold", 0),
            _INT32_MIN,
            _INT32_MAX,
            big=True,
        )
        self._add_int_field(
            header_layout,
            0,
            1,
            "value",
            ui_text("ui_netresultparam_value"),
            entry.get("value", 0),
            0,
            _UINT32_MAX,
            big=True,
        )
        self._add_int_field(
            header_layout,
            0,
            2,
            "version",
            ui_text("ui_netresultparam_version"),
            self._result.get("version", 1000) if self._result else 1000,
            0,
            _UINT32_MAX,
            big=True,
        )
        for col in range(self._grid_columns(3)):
            header_layout.setColumnStretch(col, 1)
        self._editor_layout.addWidget(header)

        info_card = self._make_card()
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info = QLabel(ui_text("ui_netresultparam_online_warning"))
        info.setFont(QFont("Segoe UI", 11))
        info.setStyleSheet(ss_dim_label())
        info.setMinimumWidth(0)
        info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        info.setWordWrap(True)
        info_layout.addWidget(info)
        self._editor_layout.addWidget(info_card)

        self._add_section(ui_text("ui_netresultparam_file_header"))
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        file_card, file_grid = make_editor_grid_card(
            self._editor_widget,
            title=section_title,
            icon_name="fa6s.sliders",
            vertical_spacing=10,
        )
        self._prep_card(file_card)
        self._active_grid_columns = 2
        self._entry_count_label = QLabel(ui_text("ui_netresultparam_entry_count_value", count=len(self._entries)))
        self._entry_count_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._entry_count_label.setStyleSheet(ss_field_label())
        self._entry_count_label.setMinimumWidth(0)
        self._entry_count_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        count_row, count_col = self._field_position(0, 0, 2)
        file_grid.addWidget(self._entry_count_label, count_row, count_col)
        self._add_text_field(
            file_grid,
            0,
            1,
            "notes_hex",
            ui_text("ui_netresultparam_notes_hex"),
            self._notes_hex(),
        )
        if self._grid_columns(2) > 1:
            file_grid.setColumnStretch(0, 1)
            file_grid.setColumnStretch(1, 2)
        else:
            file_grid.setColumnStretch(0, 1)
        self._editor_layout.addWidget(file_card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _add_section(self, title: str):
        self._pending_section_title = title

    def _make_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("EditorCard")
        card.setStyleSheet(ss_editor_card())
        self._prep_card(card)
        return card

    def _field_shell(self, label: str) -> tuple[QWidget, QVBoxLayout]:
        frame, layout, _label, _hint = make_editor_field_shell(label)
        return frame, layout

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < 780

    def _grid_columns(self, max_columns: int) -> int:
        width = self._editor_scroll.viewport().width()
        if width < 780:
            return 1
        if width < 960:
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

    def _add_int_field(self, grid, row, col, key, label, value, min_value, max_value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._int_validator if min_value < 0 else self._uint_validator)
        edit.setMaxLength(11 if min_value < 0 else 10)
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key, lo=min_value, hi=max_value: self._on_numeric_finished(k, lo, hi))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def _add_text_field(self, grid, row, col, key, label, value):
        frame, field_layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setFixedHeight(30)
        edit.setFont(QFont("Consolas", 13))
        edit.setStyleSheet(ss_input())
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(value))
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        field_layout.addWidget(edit)
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

    def _on_numeric_text_changed(self):
        if self._loading_detail:
            return
        self._mark_dirty()

    def _on_numeric_finished(self, key: str, min_value: int, max_value: int):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._read_int(key, min_value, max_value, show_errors=True)
        if value is None:
            return
        if key == "version":
            if self._result is not None:
                self._result["version"] = value
            return
        self._entries[self._current_idx][key] = value
        self._refresh_entry_button(self._current_idx)

    def _read_int(self, key: str, min_value: int, max_value: int, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        text = widget.text().strip()
        try:
            value = int(text or "0")
        except ValueError:
            value = min_value - 1
        if value < min_value or value > max_value:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_netresultparam_invalid_integer", value=text, min=min_value, max=max_value),
                )
            return None
        return value

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._current_idx is None:
            return True
        if self._result is not None:
            version = self._read_int("version", 0, _UINT32_MAX, show_errors=show_errors)
            if version is None:
                return False
            notes = self._read_notes_hex(show_errors=show_errors)
            if notes is None:
                return False
            self._result["version"] = version
            self._result["notes"] = notes
        for key, min_value, max_value in (
            ("threshold", _INT32_MIN, _INT32_MAX),
            ("value", 0, _UINT32_MAX),
        ):
            value = self._read_int(key, min_value, max_value, show_errors=show_errors)
            if value is None:
                return False
            self._entries[self._current_idx][key] = value
        self._refresh_entry_button(self._current_idx)
        return True

    def _notes_hex(self) -> str:
        if not self._result:
            return ""
        notes = bytes(self._result.get("notes", b""))
        return " ".join(f"{byte:02X}" for byte in notes)

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
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_netresultparam_invalid_hex"),
                )
            return None

    def _mark_dirty(self):
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
        new_entry = copy.deepcopy(self._entries[self._current_idx])
        self._entries.insert(self._current_idx + 1, new_entry)
        new_idx = self._current_idx + 1
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._select_entry(new_idx)

    def _do_del(self):
        if self._raw_data is None or self._current_idx is None:
            return
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("ui_netresultparam_delete_entry", index=self._current_idx),
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
            self._show_placeholder(ui_text("ui_netresultparam_no_entries"))
            self._update_actions()
