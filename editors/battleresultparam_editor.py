import copy
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
    ss_bg_dark,
    ss_bg_panel,
    ss_accent_sep,
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
from parsers.battleresultparam_parser import (
    make_default_entry,
    parse_battleresultparam_xfbin,
    save_battleresultparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF

_RESULT_LABEL_KEYS = {
    "ID_TIME": "ui_battleresultparam_id_time",
    "ID_LIFE": "ui_battleresultparam_id_life",
    "ID_QUALITY": "ui_battleresultparam_id_quality",
    "ID_POINT": "ui_battleresultparam_id_point",
    "ID_TOTAL": "ui_battleresultparam_id_total",
    "ID_QUALITY_P": "ui_battleresultparam_id_quality_p",
    "ID_QUALITY_G": "ui_battleresultparam_id_quality_g",
    "ID_QUALITY_H": "ui_battleresultparam_id_quality_h",
    "ID_QUALITY_S": "ui_battleresultparam_id_quality_s",
    "ID_QUALITY_V": "ui_battleresultparam_id_quality_v",
    "ID_QUALITY_T": "ui_battleresultparam_id_quality_t",
    "ID_QUALITY_D": "ui_battleresultparam_id_quality_d",
    "ID_QUALITY_L": "ui_battleresultparam_id_quality_l",
    "ID_GP": "ui_battleresultparam_id_gp",
    "ID_GP_TEAM": "ui_battleresultparam_id_gp_team",
    "ID_GP_ENDLESS": "ui_battleresultparam_id_gp_endless",
    "ID_GP_ENDLESS_UP": "ui_battleresultparam_id_gp_endless_up",
    "ID_GP_TOURNAMENT_1": "ui_battleresultparam_id_gp_tournament_1",
    "ID_GP_TOURNAMENT_2": "ui_battleresultparam_id_gp_tournament_2",
    "ID_GP_TOURNAMENT_3": "ui_battleresultparam_id_gp_tournament_3",
    "ID_GP_TOURNAMENT_FIRST_CHAMPION": "ui_battleresultparam_id_gp_tournament_first_champion",
    "ID_GP_ARCADE_DIFFICULT_RATE": "ui_battleresultparam_id_gp_arcade_difficult_rate",
}

_RESULT_HINT_KEYS = {
    "ID_TIME": "ui_battleresultparam_hint_time",
    "ID_LIFE": "ui_battleresultparam_hint_life",
    "ID_QUALITY": "ui_battleresultparam_hint_quality",
    "ID_POINT": "ui_battleresultparam_hint_point",
    "ID_TOTAL": "ui_battleresultparam_hint_total",
    "ID_GP": "ui_battleresultparam_hint_gp",
    "ID_GP_TEAM": "ui_battleresultparam_hint_gp_team",
    "ID_GP_ENDLESS": "ui_battleresultparam_hint_gp_endless",
    "ID_GP_ENDLESS_UP": "ui_battleresultparam_hint_gp_endless_up",
    "ID_GP_TOURNAMENT_1": "ui_battleresultparam_hint_gp_tournament",
    "ID_GP_TOURNAMENT_2": "ui_battleresultparam_hint_gp_tournament",
    "ID_GP_TOURNAMENT_3": "ui_battleresultparam_hint_gp_tournament",
    "ID_GP_TOURNAMENT_FIRST_CHAMPION": "ui_battleresultparam_hint_gp_first_champion",
    "ID_GP_ARCADE_DIFFICULT_RATE": "ui_battleresultparam_hint_gp_arcade_difficult_rate",
}


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


class BattleResultParamEditor(QWidget):
    """Embedded editor for BattleResultParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._current_idx: int | None = None
        self._fields: dict[str, QLineEdit | QComboBox] = {}
        self._dirty = False
        self._loading_detail = False
        self._last_compact: bool | None = None
        self._active_grid_columns = 3
        self._uint_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)

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

        self._show_placeholder(ui_text("ui_battleresultparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
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
            ui_text("ui_battleresultparam_open_title"),
            game_files_dialog_dir(target_patterns=(
                "BattleResultParam.bin.xfbin",
                "BattleResultParam.xfbin",
                "ArcadeResultParam.bin.xfbin",
                "ArcadeResultParam.xfbin",
            )),
            ui_text("ui_battleresultparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        try:
            raw, version, entries = parse_battleresultparam_xfbin(path)
        except Exception as exc:
            self._filepath = None
            self._raw_data = None
            self._entries = []
            self._current_idx = None
            self._clear_entry_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_battleresultparam_open_file_to_begin_editing"))
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._filepath = path
        self._raw_data = raw
        self._version = version
        self._entries = entries
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
            self._show_placeholder(ui_text("ui_battleresultparam_no_entries"))
        self._update_actions()

    def _do_save(self):
        if not self._filepath or self._raw_data is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_battleresultparam_xfbin(self._filepath, self._raw_data, self._version, self._entries)
            with open(self._filepath, "rb") as fh:
                self._raw_data = bytearray(fh.read())
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, self._filepath)
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
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_idx))

        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(0)

        title_text = self._entry_title(idx, entry)
        subtitle_text = self._entry_button_subtitle(entry)

        title = QLabel(_truncate(title_text, 22))
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        title.setToolTip(self._known_label(entry.get("result_id", "")))
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)

        subtitle = QLabel(_truncate(subtitle_text, 28))
        subtitle.setFont(QFont("Consolas", 10))
        subtitle.setStyleSheet(ss_dim_label())
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        subtitle.setToolTip(subtitle_text)
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        return entry.get("result_id", "") or ui_text("ui_battleresultparam_empty_id")

    def _entry_button_subtitle(self, entry: dict) -> str:
        values = entry.get("values", [])
        preview = " / ".join(str(value) for value in values[:3])
        reserved = int(entry.get("reserved", 0))
        return f"{self._known_label(entry.get('result_id', ''))} | {preview} | R {reserved}"

    def _filter_list(self):
        query = self._search.text().lower().strip()
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join([
                entry.get("result_id", ""),
                self._known_label(entry.get("result_id", "")),
                " ".join(str(value) for value in entry.get("values", [])),
                str(entry.get("reserved", "")),
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
            if labels:
                entry = self._entries[idx]
                title_text = self._entry_title(idx, entry)
                subtitle_text = self._entry_button_subtitle(entry)
                labels[0].setText(_truncate(title_text, 22))
                labels[0].setToolTip(self._known_label(entry.get("result_id", "")))
                if len(labels) > 1:
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

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        entry = self._entries[idx]
        self._loading_detail = True
        self._last_compact = self._is_compact_editor()

        header, header_layout = make_editor_grid_card(
            self._editor_widget,
            title=self._entry_title(idx, entry),
            icon_name="fa6s.chart-column",
            subtitle=self._known_label(entry.get("result_id", "")),
            grid_margins=(0, 0, 0, 0),
            vertical_spacing=8,
        )
        self._prep_card(header)
        self._active_grid_columns = 2

        self._add_combo_field(
            header_layout,
            0,
            0,
            "result_id",
            ui_text("ui_battleresultparam_result_id"),
            entry.get("result_id", ""),
            self._result_id_options(entry.get("result_id", "")),
            ui_text("ui_battleresultparam_result_id_hint"),
            big=True,
        )
        self._add_uint_field(
            header_layout,
            0,
            1,
            "reserved",
            ui_text("ui_battleresultparam_reserved"),
            entry.get("reserved", 0),
            ui_text("ui_battleresultparam_reserved_hint"),
        )
        for col in range(self._grid_columns(2)):
            header_layout.setColumnStretch(col, 1)
        self._editor_layout.addWidget(header)

        self._add_section(self._values_section_title(entry.get("result_id", "")))
        values_card = self._make_card()
        values_grid = self._card_grid(values_card)
        self._active_grid_columns = 3
        values = entry.get("values", [0, 0, 0, 0, 0])
        for value_idx in range(5):
            self._add_uint_field(
                values_grid,
                value_idx // 3,
                value_idx % 3,
                f"value_{value_idx}",
                self._value_label(entry.get("result_id", ""), value_idx),
                values[value_idx] if value_idx < len(values) else 0,
                self._value_hint(entry.get("result_id", ""), value_idx),
            )
        for col in range(self._grid_columns(3)):
            values_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(values_card)

        self._add_section(ui_text("ui_battleresultparam_ingame_checks"))
        checks = self._make_card()
        checks_grid = self._card_grid(checks)
        checks_text = QLabel(self._check_text(entry.get("result_id", "")))
        checks_text.setFont(QFont("Segoe UI", 10))
        checks_text.setStyleSheet(ss_dim_label())
        checks_text.setMinimumWidth(0)
        checks_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        checks_text.setWordWrap(True)
        checks_grid.addWidget(checks_text, 0, 0)
        checks_grid.setColumnStretch(0, 1)
        self._editor_layout.addWidget(checks)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _known_label(self, result_id: str) -> str:
        key = _RESULT_LABEL_KEYS.get(result_id)
        return ui_text(key) if key else ui_text("ui_battleresultparam_unknown_result_id")

    def _known_hint(self, result_id: str) -> str:
        key = _RESULT_HINT_KEYS.get(result_id)
        return ui_text(key) if key else ui_text("ui_battleresultparam_unknown_result_id_hint")

    def _result_id_options(self, current_value: str = "") -> list[tuple[str, str]]:
        values = []
        seen = set()
        for result_id in _RESULT_LABEL_KEYS:
            seen.add(result_id)
            values.append(result_id)
        for entry in self._entries:
            result_id = entry.get("result_id", "")
            if result_id and result_id not in seen:
                seen.add(result_id)
                values.append(result_id)
        if current_value and current_value not in seen:
            values.append(current_value)
        if not values:
            values.append("ID_TIME")
        return [(value, value) for value in values]

    def _values_section_title(self, result_id: str) -> str:
        if result_id in {"ID_TIME", "ID_LIFE", "ID_QUALITY", "ID_POINT", "ID_TOTAL"}:
            return ui_text("ui_battleresultparam_rank_thresholds")
        if result_id.startswith("ID_QUALITY_"):
            return ui_text("ui_battleresultparam_quality_bonus_values")
        if result_id.startswith("ID_GP"):
            return ui_text("ui_battleresultparam_gp_reward_values")
        return ui_text("ui_battleresultparam_result_values")

    def _rank_slot_label(self, value_idx: int) -> str:
        keys = (
            "ui_battleresultparam_rank_s",
            "ui_battleresultparam_rank_a",
            "ui_battleresultparam_rank_b",
            "ui_battleresultparam_rank_c",
            "ui_battleresultparam_rank_d_or_unused",
        )
        return ui_text(keys[value_idx])

    def _value_label(self, result_id: str, value_idx: int) -> str:
        slot = self._rank_slot_label(value_idx)
        if result_id == "ID_TIME":
            return ui_text("ui_battleresultparam_time_threshold_label", slot=slot)
        if result_id == "ID_LIFE":
            return ui_text("ui_battleresultparam_life_threshold_label", slot=slot)
        if result_id in {"ID_QUALITY", "ID_POINT", "ID_TOTAL"}:
            return ui_text("ui_battleresultparam_score_threshold_label", slot=slot)
        if result_id.startswith("ID_QUALITY_"):
            if value_idx == 0:
                return ui_text("ui_battleresultparam_quality_bonus_label")
            return ui_text("ui_battleresultparam_unused_value_label", index=value_idx + 1)
        if result_id == "ID_GP_ARCADE_DIFFICULT_RATE":
            return ui_text("ui_battleresultparam_arcade_rate_label", index=value_idx + 1)
        if result_id.startswith("ID_GP_TOURNAMENT"):
            return ui_text("ui_battleresultparam_tournament_reward_label", index=value_idx + 1)
        if result_id.startswith("ID_GP"):
            return ui_text("ui_battleresultparam_gp_reward_label", index=value_idx + 1)
        return ui_text(f"ui_battleresultparam_value_{value_idx + 1}")

    def _value_hint(self, result_id: str, value_idx: int) -> str:
        if result_id == "ID_TIME":
            return ui_text("ui_battleresultparam_time_threshold_hint")
        if result_id == "ID_LIFE":
            return ui_text("ui_battleresultparam_life_threshold_hint")
        if result_id == "ID_QUALITY":
            return ui_text("ui_battleresultparam_quality_threshold_hint")
        if result_id in {"ID_POINT", "ID_TOTAL"}:
            return ui_text("ui_battleresultparam_score_threshold_hint")
        if result_id.startswith("ID_QUALITY_"):
            return ui_text("ui_battleresultparam_quality_bonus_hint")
        if result_id == "ID_GP_ARCADE_DIFFICULT_RATE":
            return ui_text("ui_battleresultparam_arcade_rate_hint")
        if result_id.startswith("ID_GP"):
            return ui_text("ui_battleresultparam_gp_reward_hint")
        return ui_text(f"ui_battleresultparam_value_{value_idx + 1}_hint")

    def _check_text(self, result_id: str) -> str:
        if result_id == "ID_TIME":
            return ui_text("ui_battleresultparam_check_time")
        if result_id == "ID_LIFE":
            return ui_text("ui_battleresultparam_check_life")
        if result_id in {"ID_QUALITY", "ID_POINT", "ID_TOTAL"}:
            return ui_text("ui_battleresultparam_check_rank")
        if result_id.startswith("ID_QUALITY_"):
            return ui_text("ui_battleresultparam_check_quality_bonus")
        if result_id == "ID_GP_ARCADE_DIFFICULT_RATE":
            return ui_text("ui_battleresultparam_check_arcade_rate")
        if result_id.startswith("ID_GP"):
            return ui_text("ui_battleresultparam_check_gp")
        return ui_text("ui_battleresultparam_check_unknown")

    def _add_section(self, title: str):
        self._pending_section_title = title

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

    def _field_shell(self, label: str, hint: str = "") -> tuple[QWidget, QVBoxLayout]:
        frame, layout, _label, _hint = make_editor_field_shell(label, hint)
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

    def _add_text_field(self, grid, row, col, key, label, value, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setMaxLength(96)
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

    def _add_combo_field(self, grid, row, col, key, label, value, options, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        combo = QComboBox()
        combo.setFixedHeight(36 if big else 30)
        combo.setFont(QFont("Consolas", 16 if big else 13))
        combo.setStyleSheet(ss_input())
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        combo.setMinimumContentsLength(1)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

        selected = 0
        for idx, (data, text) in enumerate(options):
            combo.addItem(text, data)
            if data == value:
                selected = idx
        combo.setCurrentIndex(selected)
        combo.currentIndexChanged.connect(lambda _idx, k=key: self._on_combo_changed(k))

        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = combo

    def _add_uint_field(self, grid, row, col, key, label, value, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setValidator(self._uint_validator)
        edit.setMaxLength(10)
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setCursorPosition(0)
        edit.editingFinished.connect(lambda k=key: self._on_uint_finished(k))
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
        if key == "result_id":
            result_id = self._fields[key].text().strip()
            self._entries[self._current_idx]["result_id"] = result_id
            self._mark_dirty()
            self._refresh_entry_button(self._current_idx)

    def _on_combo_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        widget = self._fields.get(key)
        if not isinstance(widget, QComboBox):
            return
        if key == "result_id":
            self._entries[self._current_idx]["result_id"] = widget.currentData()
            self._mark_dirty()
            self._refresh_entry_button(self._current_idx)
            self._build_editor(self._current_idx)

    def _on_uint_finished(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        if self._apply_uint_field(key, show_errors=True):
            self._mark_dirty()
            self._refresh_entry_button(self._current_idx)

    def _read_uint(self, key: str, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        if isinstance(widget, QComboBox):
            text = str(widget.currentData())
        else:
            text = widget.text().strip()
        try:
            value = int(text or "0")
        except ValueError:
            value = -1
        if value < 0 or value > _UINT32_MAX:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_battleresultparam_invalid_uint32", value=text),
                )
            return None
        return value

    def _apply_uint_field(self, key: str, show_errors: bool = False) -> bool:
        if self._current_idx is None or self._current_idx >= len(self._entries):
            return True
        value = self._read_uint(key, show_errors=show_errors)
        if value is None:
            return False
        entry = self._entries[self._current_idx]
        if key == "reserved":
            entry["reserved"] = value
        elif key.startswith("value_"):
            value_idx = int(key.split("_", 1)[1])
            values = list(entry.get("values", [0, 0, 0, 0, 0]))
            values += [0] * (5 - len(values))
            values[value_idx] = value
            entry["values"] = values[:5]
        return True

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._current_idx is None:
            return True
        if "result_id" in self._fields:
            widget = self._fields["result_id"]
            if isinstance(widget, QComboBox):
                self._entries[self._current_idx]["result_id"] = widget.currentData()
            else:
                self._entries[self._current_idx]["result_id"] = widget.text().strip()
        for key in list(self._fields):
            if key == "result_id":
                continue
            if not self._apply_uint_field(key, show_errors=show_errors):
                return False
        self._refresh_entry_button(self._current_idx)
        return True

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
        entry = self._entries[self._current_idx]
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("msg_confirm_delete_item", name=entry.get("result_id", "")),
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
            self._show_placeholder(ui_text("ui_battleresultparam_no_entries"))
            self._update_actions()
