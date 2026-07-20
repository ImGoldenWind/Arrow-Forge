import copy
import os

from PyQt6.QtCore import QRegularExpression, Qt
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
    make_empty_state,
    make_editor_grid_card,
    make_editor_field_shell,
    ss_accent_sep,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
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
    ss_sep,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_transparent,
)
from core.translations import ui_text
from parsers.onlinemissionparam_parser import (
    make_default_entry,
    parse_onlinemissionparam_xfbin,
    save_onlinemissionparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF


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


class OnlineMissionParamEditor(QWidget):
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

        self._show_placeholder(ui_text("ui_onlinemissionparam_open_file_to_begin_editing"))
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
            ui_text("ui_onlinemissionparam_open_title"),
            game_files_dialog_dir(target_patterns=("OnlineMissionParam.bin.xfbin", "OnlineMissionParam.xfbin")),
            ui_text("ui_onlinemissionparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        try:
            raw, result = parse_onlinemissionparam_xfbin(path)
        except Exception as exc:
            self._filepath = None
            self._raw_data = None
            self._result = None
            self._entries = []
            self._current_idx = None
            self._clear_entry_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_onlinemissionparam_open_file_to_begin_editing"))
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
            self._show_placeholder(ui_text("ui_onlinemissionparam_no_entries"))
        self._update_actions()

    def _do_save(self):
        if not self._filepath or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_onlinemissionparam_xfbin(self._filepath, self._raw_data, self._result)
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
        btn.setFixedHeight(52)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_idx))

        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(0)

        title = QLabel(self._entry_title(idx, entry))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
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
        title = entry.get("title_key", "") or ui_text("ui_onlinemissionparam_empty_title")
        return ui_text("ui_onlinemissionparam_entry_title", index=idx, title=title)

    def _entry_subtitle(self, entry: dict) -> str:
        return ui_text(
            "ui_onlinemissionparam_entry_subtitle",
            group=int(entry.get("group_id", 0)),
            mission=int(entry.get("mission_id", 0)),
            slot=int(entry.get("display_slot", 0)),
            reward=int(entry.get("reward_value", 0)),
        )

    def _filter_list(self):
        query = self._search.text().lower().strip()
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join(str(entry.get(key, "")) for key in (
                "group_id",
                "mission_id",
                "display_slot",
                "title_key",
                "character_id",
                "stage_id",
                "condition_id",
                "reward_card_id",
                "banner_id",
            )).lower()
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
            self._entry_count_label.setText(ui_text("ui_onlinemissionparam_entry_count_value", count=len(self._entries)))

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._entry_count_label = None
        self._loading_detail = True
        entry = self._entries[idx]

        header, header_layout = make_editor_grid_card(
            title=self._entry_title(idx, entry),
            icon_name="fa6s.globe",
            subtitle=self._entry_subtitle(entry),
            grid_margins=(0, 2, 0, 0),
            vertical_spacing=8,
        )
        self._add_uint_field(header_layout, 0, 0, "group_id", ui_text("ui_onlinemissionparam_group_id"), entry.get("group_id", 0), big=True)
        self._add_uint_field(header_layout, 0, 1, "mission_id", ui_text("ui_onlinemissionparam_mission_id"), entry.get("mission_id", 0), big=True)
        self._add_uint_field(header_layout, 0, 2, "display_slot", ui_text("ui_onlinemissionparam_display_slot"), entry.get("display_slot", 0), big=True)
        self._add_hint(header_layout, 1, 0, ui_text("ui_onlinemissionparam_group_hint"))
        self._add_hint(header_layout, 1, 1, ui_text("ui_onlinemissionparam_mission_hint"))
        self._add_hint(header_layout, 1, 2, ui_text("ui_onlinemissionparam_display_slot_hint"))
        for col in range(3):
            header_layout.setColumnStretch(col, 1)
        self._editor_layout.addWidget(header)

        self._add_section(ui_text("ui_onlinemissionparam_strings"))
        string_card = self._make_card()
        string_grid = self._card_grid(string_card)
        self._add_text_field(string_grid, 0, 0, "title_key", ui_text("ui_onlinemissionparam_title_key"), entry.get("title_key", ""))
        self._add_text_field(string_grid, 0, 1, "character_id", ui_text("ui_onlinemissionparam_character_id"), entry.get("character_id", ""))
        self._add_text_field(string_grid, 0, 2, "stage_id", ui_text("ui_onlinemissionparam_stage_id"), entry.get("stage_id", ""))
        self._add_text_field(string_grid, 2, 0, "condition_id", ui_text("ui_onlinemissionparam_condition_id"), entry.get("condition_id", ""))
        self._add_text_field(string_grid, 2, 1, "banner_id", ui_text("ui_onlinemissionparam_banner_id"), entry.get("banner_id", ""))
        self._add_hint(string_grid, 1, 0, ui_text("ui_onlinemissionparam_title_hint"), colspan=3)
        self._add_hint(string_grid, 3, 0, ui_text("ui_onlinemissionparam_condition_hint"), colspan=2)
        for col in range(3):
            string_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(string_card)

        self._add_section(ui_text("ui_onlinemissionparam_objective"))
        objective_card = self._make_card()
        objective_grid = self._card_grid(objective_card)
        self._add_uint_field(objective_grid, 0, 0, "mission_type", ui_text("ui_onlinemissionparam_mission_type"), entry.get("mission_type", 0))
        self._add_uint_field(objective_grid, 0, 1, "flag_08", ui_text("ui_onlinemissionparam_flag_08"), entry.get("flag_08", 0))
        self._add_uint_field(objective_grid, 0, 2, "objective_value", ui_text("ui_onlinemissionparam_objective_value"), entry.get("objective_value", 0))
        self._add_hint(objective_grid, 1, 0, ui_text("ui_onlinemissionparam_objective_hint"), colspan=3)
        for col in range(3):
            objective_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(objective_card)

        self._add_section(ui_text("ui_onlinemissionparam_rewards"))
        reward_card = self._make_card()
        reward_grid = self._card_grid(reward_card)
        self._add_uint_field(reward_grid, 0, 0, "reward_value", ui_text("ui_onlinemissionparam_reward_value"), entry.get("reward_value", 0))
        self._add_uint_field(reward_grid, 0, 1, "reward_type", ui_text("ui_onlinemissionparam_reward_type"), entry.get("reward_type", 0))
        self._add_text_field(reward_grid, 0, 2, "reward_card_id", ui_text("ui_onlinemissionparam_reward_card_id"), entry.get("reward_card_id", ""))
        self._add_hint(reward_grid, 1, 0, ui_text("ui_onlinemissionparam_reward_hint"), colspan=3)
        for col in range(3):
            reward_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(reward_card)

        self._add_section(ui_text("ui_onlinemissionparam_raw_values"))
        raw_card = self._make_card()
        raw_grid = self._card_grid(raw_card)
        self._entry_count_label = QLabel(ui_text("ui_onlinemissionparam_entry_count_value", count=len(self._entries)))
        self._entry_count_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._entry_count_label.setStyleSheet(ss_field_label())
        raw_grid.addWidget(self._entry_count_label, 0, 0)
        self._add_uint_field(raw_grid, 0, 1, "version", ui_text("ui_onlinemissionparam_version"), self._result.get("version", 1000) if self._result else 1000)
        self._add_text_field(raw_grid, 0, 2, "notes_hex", ui_text("ui_onlinemissionparam_notes_hex"), self._notes_hex())
        self._add_uint_field(raw_grid, 2, 0, "subtype_id", ui_text("ui_onlinemissionparam_subtype_id"), entry.get("subtype_id", 0))
        self._add_uint_field(raw_grid, 2, 1, "raw_14", ui_text("ui_onlinemissionparam_raw_14"), entry.get("raw_14", 0))
        self._add_uint_field(raw_grid, 2, 2, "raw_20", ui_text("ui_onlinemissionparam_raw_20"), entry.get("raw_20", 0))
        self._add_uint_field(raw_grid, 4, 0, "raw_24", ui_text("ui_onlinemissionparam_raw_24"), entry.get("raw_24", 0))
        self._add_uint_field(raw_grid, 4, 1, "raw_2c", ui_text("ui_onlinemissionparam_raw_2c"), entry.get("raw_2c", 0))
        self._add_uint_field(raw_grid, 4, 2, "raw_44", ui_text("ui_onlinemissionparam_raw_44"), entry.get("raw_44", 0))
        self._add_hint(raw_grid, 1, 1, ui_text("ui_onlinemissionparam_notes_hint"), colspan=2)
        self._add_hint(raw_grid, 3, 0, ui_text("ui_onlinemissionparam_raw_hint"), colspan=3)
        for col in range(3):
            raw_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(raw_card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _add_section(self, title: str):
        self._pending_section_title = title

    def _make_card(self) -> QFrame:
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(
            title=section_title,
            icon_name="fa6s.sliders",
            vertical_spacing=10,
        )
        card._editor_grid = grid
        return card

    def _card_grid(self, card: QFrame) -> QGridLayout:
        return card._editor_grid

    def _field_shell(self, label: str) -> tuple[QWidget, QVBoxLayout]:
        frame, layout, _label, _hint = make_editor_field_shell(label)
        return frame, layout

    def _add_hint(self, grid, row: int, col: int, text: str, colspan: int = 1):
        hint = QLabel(text)
        hint.setMinimumWidth(0)
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
        edit.setMinimumWidth(0)
        edit.setText(str(value))
        edit.textChanged.connect(lambda _text, k=key: self._on_text_changed(k))
        layout.addWidget(edit)
        grid.addWidget(frame, row, col)
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
        edit.setText(str(int(value)))
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key: self._on_uint_finished(k))
        layout.addWidget(edit)
        grid.addWidget(frame, row, col)
        self._fields[key] = edit

    def _on_text_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        self._mark_dirty()
        if key in ("notes_hex",):
            return
        self._entries[self._current_idx][key] = self._fields[key].text().strip()
        self._refresh_entry_button(self._current_idx)

    def _on_numeric_text_changed(self):
        if not self._loading_detail:
            self._mark_dirty()

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
                    ui_text("ui_onlinemissionparam_ascii_only", field=ui_text(f"ui_onlinemissionparam_{key}")),
                )
            return None
        return text

    def _read_uint(self, key: str, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
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
                    ui_text("ui_onlinemissionparam_invalid_integer", value=text, min=0, max=_UINT32_MAX),
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
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_onlinemissionparam_invalid_hex"))
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

        for key in ("title_key", "character_id", "stage_id", "condition_id", "reward_card_id", "banner_id"):
            value = self._read_ascii(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value

        for key in (
            "group_id",
            "mission_id",
            "flag_08",
            "mission_type",
            "subtype_id",
            "raw_14",
            "raw_20",
            "raw_24",
            "objective_value",
            "raw_2c",
            "display_slot",
            "raw_44",
            "reward_value",
            "reward_type",
        ):
            if key not in self._fields:
                continue
            value = self._read_uint(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
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
            self._show_placeholder(ui_text("ui_onlinemissionparam_no_entries"))
            self._update_actions()
