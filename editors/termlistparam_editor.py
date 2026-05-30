import copy
import os

from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QFont, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
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
from core.utils.ui_helpers import _add_card_section_title
from core.translations import ui_text
from parsers.termlistparam_parser import (
    make_default_entry,
    parse_termlistparam_xfbin,
    save_termlistparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF
_UINT64_MAX = 0xFFFFFFFFFFFFFFFF


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class TermListParamEditor(QWidget):
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

        self._uint32_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._uint64_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,20}"), self)

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
        sidebar.setFixedWidth(280)
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
        self._entry_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._entry_list_widget = QWidget()
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
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_termlistparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._entry_count_label = None
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 16))
        label.setStyleSheet(ss_placeholder())
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(label)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_termlistparam_open_title"),
            game_files_dialog_dir(target_patterns=("TermListParam.bin.xfbin", "TermListParam.xfbin")),
            ui_text("ui_termlistparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        try:
            raw, result = parse_termlistparam_xfbin(path)
        except Exception as exc:
            self._filepath = None
            self._raw_data = None
            self._result = None
            self._entries = []
            self._current_idx = None
            self._clear_entry_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_termlistparam_open_file_to_begin_editing"))
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
            self._show_placeholder(ui_text("ui_termlistparam_no_entries"))
        self._update_actions()

    def _do_save(self):
        if not self._filepath or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_termlistparam_xfbin(self._filepath, self._raw_data, self._result)
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
        btn.setFixedHeight(48)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_idx))

        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(0)

        title = QLabel(self._entry_title(idx, entry))
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)

        subtitle = QLabel(self._entry_subtitle(entry))
        subtitle.setFont(QFont("Consolas", 10))
        subtitle.setStyleSheet(ss_dim_label())
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        title_key = entry.get("title_key", "") or ui_text("ui_termlistparam_empty_text_key")
        return ui_text("ui_termlistparam_entry_title", index=idx, title=title_key)

    def _entry_subtitle(self, entry: dict) -> str:
        return ui_text(
            "ui_termlistparam_entry_subtitle",
            group=self._group_label(int(entry.get("group_id", 0))),
            description=entry.get("description_key", ""),
        )

    def _group_label(self, value: int) -> str:
        key = f"ui_termlistparam_group_{value}"
        translated = ui_text(key)
        if translated != key:
            return ui_text("ui_termlistparam_group_value", value=value, label=translated)
        return ui_text("ui_termlistparam_group_custom", value=value)

    def _filter_list(self):
        query = self._search.text().lower().strip()
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join([
                str(idx),
                str(entry.get("group_id", "")),
                str(entry.get("title_key", "")),
                str(entry.get("description_key", "")),
                str(entry.get("image_file", "")),
                str(entry.get("image_name", "")),
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
                labels[0].setText(self._entry_title(idx, self._entries[idx]))
                labels[1].setText(self._entry_subtitle(self._entries[idx]))
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
            self._entry_count_label.setText(ui_text("ui_termlistparam_entry_count_value", count=len(self._entries)))

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._entry_count_label = None
        self._loading_detail = True
        entry = self._entries[idx]

        header = QFrame()
        header.setStyleSheet(ss_panel())
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setHorizontalSpacing(16)
        header_layout.setVerticalSpacing(8)

        self._add_text_field(header_layout, 0, 0, "title_key", ui_text("ui_termlistparam_title_key"), entry.get("title_key", ""), big=True)
        self._add_uint_field(header_layout, 0, 1, "group_id", ui_text("ui_termlistparam_group_id"), entry.get("group_id", 0), 0, _UINT64_MAX, big=True)
        self._add_uint_field(header_layout, 0, 2, "unknown_16", ui_text("ui_termlistparam_unknown_16"), entry.get("unknown_16", 0), 0, _UINT64_MAX, big=True)
        self._add_hint(header_layout, 1, 1, ui_text("ui_termlistparam_group_id_hint"))
        self._add_hint(header_layout, 1, 2, ui_text("ui_termlistparam_unknown_16_hint"))
        for col in range(3):
            header_layout.setColumnStretch(col, 1)
        self._editor_layout.addWidget(header)

        self._add_section(ui_text("ui_termlistparam_text_keys"))
        text_card = self._make_card()
        text_grid = self._card_grid(text_card)
        self._add_text_field(text_grid, 0, 0, "description_key", ui_text("ui_termlistparam_description_key"), entry.get("description_key", ""))
        self._add_hint(text_grid, 1, 0, ui_text("ui_termlistparam_text_keys_hint"))
        text_grid.setColumnStretch(0, 1)
        self._editor_layout.addWidget(text_card)

        self._add_section(ui_text("ui_termlistparam_image_asset"))
        image_card = self._make_card()
        image_grid = self._card_grid(image_card)
        self._add_text_field(image_grid, 0, 0, "image_file", ui_text("ui_termlistparam_image_file"), entry.get("image_file", ""))
        self._add_text_field(image_grid, 0, 1, "image_name", ui_text("ui_termlistparam_image_name"), entry.get("image_name", ""))
        self._add_hint(image_grid, 1, 0, ui_text("ui_termlistparam_image_hint"), colspan=2)
        image_grid.setColumnStretch(0, 2)
        image_grid.setColumnStretch(1, 1)
        self._editor_layout.addWidget(image_card)

        self._add_section(ui_text("ui_termlistparam_file_header"))
        file_card = self._make_card()
        file_grid = self._card_grid(file_card)
        self._add_uint_field(file_grid, 0, 0, "version", ui_text("ui_termlistparam_version"), self._result.get("version", 1000) if self._result else 1000, 0, _UINT32_MAX)
        self._entry_count_label = QLabel(ui_text("ui_termlistparam_entry_count_value", count=len(self._entries)))
        self._entry_count_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._entry_count_label.setStyleSheet(ss_field_label())
        file_grid.addWidget(self._entry_count_label, 0, 1)
        self._add_text_field(file_grid, 0, 2, "notes_hex", ui_text("ui_termlistparam_notes_hex"), self._notes_hex())
        for col in range(3):
            file_grid.setColumnStretch(col, 1)
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
        card.setStyleSheet(ss_panel())
        return card

    def _card_grid(self, card: QFrame) -> QGridLayout:
        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        grid = QGridLayout(inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        layout = QVBoxLayout(card)
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        if section_title:
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)
            grid.setContentsMargins(0, 4, 0, 0)
            _add_card_section_title(layout, section_title)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)
        return grid

    def _field_shell(self, label: str) -> tuple[QWidget, QVBoxLayout]:
        frame = QWidget()
        frame.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label_widget = QLabel(label)
        label_widget.setFont(QFont("Segoe UI", 12))
        label_widget.setStyleSheet(ss_field_label())
        layout.addWidget(label_widget)
        return frame, layout

    def _add_hint(self, grid, row, col, text, colspan=1):
        hint = QLabel(text)
        hint.setWordWrap(True)
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet(ss_dim_label())
        grid.addWidget(hint, row, col, 1, colspan)

    def _add_text_field(self, grid, row, col, key, label, value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setText(str(value))
        edit.textChanged.connect(lambda _text, k=key: self._on_text_changed(k))
        layout.addWidget(edit)
        grid.addWidget(frame, row, col)
        self._fields[key] = edit

    def _add_uint_field(self, grid, row, col, key, label, value, min_value, max_value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._uint32_validator if max_value <= _UINT32_MAX else self._uint64_validator)
        edit.setMaxLength(10 if max_value <= _UINT32_MAX else 20)
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setText(str(int(value)))
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key, lo=min_value, hi=max_value: self._on_uint_finished(k, lo, hi))
        layout.addWidget(edit)
        grid.addWidget(frame, row, col)
        self._fields[key] = edit

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

    def _on_uint_finished(self, key: str, min_value: int, max_value: int):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._read_uint(key, min_value, max_value, show_errors=True)
        if value is None:
            return
        if key == "version":
            if self._result is not None:
                self._result["version"] = value
            return
        self._entries[self._current_idx][key] = value
        self._refresh_entry_button(self._current_idx)

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
                    ui_text("ui_termlistparam_ascii_only", field=ui_text(f"ui_termlistparam_{key}")),
                )
            return None
        return text

    def _read_uint(self, key: str, min_value: int, max_value: int, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        text = widget.text().strip()
        try:
            value = int(text or "0")
        except ValueError:
            value = max_value + 1
        if value < min_value or value > max_value:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_termlistparam_invalid_integer", value=text, min=min_value, max=max_value),
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
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_termlistparam_invalid_hex"))
            return None

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._current_idx is None:
            return True
        entry = self._entries[self._current_idx]
        if self._result is not None:
            version = self._read_uint("version", 0, _UINT32_MAX, show_errors=show_errors)
            if version is None:
                return False
            notes = self._read_notes_hex(show_errors=show_errors)
            if notes is None:
                return False
            self._result["version"] = version
            self._result["notes"] = notes
        for key in ("title_key", "description_key", "image_file", "image_name"):
            value = self._read_ascii(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        for key in ("group_id", "unknown_16"):
            value = self._read_uint(key, 0, _UINT64_MAX, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        self._refresh_entry_button(self._current_idx)
        return True

    def _mark_dirty(self):
        if self._dirty:
            return
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
            self._show_placeholder(ui_text("ui_termlistparam_no_entries"))
            self._update_actions()
