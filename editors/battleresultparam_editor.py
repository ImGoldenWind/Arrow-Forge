from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    mono_font,
    ui_font,
)
from core.style_helpers import (
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_bg_dark,
    ss_dim_label,
    ss_sidebar_btn,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorListRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_card,
    configure_field,
    configure_file_label,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
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
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.battle_editor_ui import BattleListFilter
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.translations import ui_text
from parsers.battleresultparam_parser import (
    make_default_entry,
    parse_battleresultparam_xfbin,
    save_battleresultparam_xfbin,
    signed_value,
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
    "JUDGE_TOTAL_3": "ui_battleresultparam_id_judge_total_3",
    "JUDGE_TOTAL_8": "ui_battleresultparam_id_judge_total_8",
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
    "JUDGE_TOTAL_3": "ui_battleresultparam_hint_judge_total_3",
    "JUDGE_TOTAL_8": "ui_battleresultparam_hint_judge_total_8",
    **{f"ID_QUALITY_{suffix}": f"ui_battleresultparam_hint_quality_{suffix.lower()}"
       for suffix in "PGHSVTDL"},
}


# Exact keys traced through 229944 / 47D650. Custom suffixes have no established use.
_QUALITY_BONUSES = {f"ID_QUALITY_{suffix}" for suffix in "PGHVTDL"}
_TOURNAMENT_IDS = {"ID_GP_TOURNAMENT_1", "ID_GP_TOURNAMENT_2",
                   "ID_GP_TOURNAMENT_3", "ID_GP_TOURNAMENT_FIRST_CHAMPION"}
_BRANCH_IDS = {"ID_GP_TEAM", "ID_GP_ENDLESS", "ID_GP_ENDLESS_UP"}
_THRESHOLD_IDS = {"ID_TIME", "ID_LIFE", "ID_QUALITY", "ID_TOTAL", "JUDGE_TOTAL_8"}
_DIFFICULTY_KEYS = ("veryeasy", "easy", "normal", "hard", "veryhard")


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
        self._technical_expanded = False
        self._uint_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._int_validator = QRegularExpressionValidator(QRegularExpression(r"-?\d{0,10}"), self)

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        if value == key and fallback is not None:
            return fallback
        return value

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        top = EditorToolbar()
        top_layout = top.content_layout

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._do_open)
        self._btn_open.setProperty("designAction", 'open')
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._do_save)
        top_layout.addWidget(self._btn_save)

        self._file_label = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()

        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        sidebar = EditorSidebar(width=290)


        sidebar_layout = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)
        self._list_filter = BattleListFilter(self._search)
        self._list_filter.set_options([(key, ui_text('battle_category_' + key))
                                       for key in ('ranks', 'quality', 'gp', 'other')])
        self._list_filter.changed.connect(self._filter_list)
        sidebar_layout.addWidget(self._list_filter)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._btn_add = QPushButton(ui_text('battle_new'))
        self._btn_add.setEnabled(False)
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.clicked.connect(self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(ui_text('battle_copy'))
        self._btn_dup.setEnabled(False)
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.clicked.connect(self._do_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._btn_del.setEnabled(False)
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.clicked.connect(self._do_del)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_del, 1)

        sidebar_layout.addWidget(actions)

        self._entry_scroll = QScrollArea()


        self._entry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._entry_scroll, transparent=True)
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setMinimumWidth(0)
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        configure_layout(self._entry_list_layout, LayoutRole.LIST)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        sidebar_layout.addWidget(self._entry_scroll, 1)

        main_layout.addWidget(sidebar)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
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
            self._update_actions()
            self._filter_list()
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
        self._list_filter.clear()
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_battleresultparam_no_entries"))
        self._update_actions()

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_battleresultparam_xfbin(save_path, self._raw_data, self._version, self._entries)
            with open(save_path, 'rb') as fh:
                self._raw_data = bytearray(fh.read())
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, save_path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))

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
        btn = EditorListRow(height=48)

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = self._entry_title(idx, entry)
        subtitle_text = self._entry_button_subtitle(entry)

        title = btn.add_title()


        title.setToolTip(title_text)

        title.ensurePolished()
        title.setText(title.fontMetrics().elidedText(title_text, Qt.TextElideMode.ElideRight, 244))


        subtitle = btn.add_subtitle(_truncate(subtitle_text, 28), value_font=mono_font(TypeSize.CODE))


        subtitle.setToolTip(subtitle_text)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        result_id = entry.get("result_id", "")
        return self._known_label(result_id) if result_id in _RESULT_LABEL_KEYS else (
            result_id or ui_text("ui_battleresultparam_empty_id"))

    def _entry_button_subtitle(self, entry: dict) -> str:
        return entry.get('result_id', '')

    @staticmethod
    def _entry_category(entry):
        result_id = entry.get('result_id', '')
        if result_id in _THRESHOLD_IDS | {'ID_POINT'}:
            return 'ranks'
        if result_id in _QUALITY_BONUSES:
            return 'quality'
        if result_id in _BRANCH_IDS | _TOURNAMENT_IDS | {'ID_GP', 'ID_GP_ARCADE_DIFFICULT_RATE'}:
            return 'gp'
        return 'other'

    def _filter_list(self):
        query = self._search.text().lower().strip()
        visible = 0
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
            matches = (not query or query in haystack) and self._list_filter.accepts(self._entry_category(entry))
            btn.setVisible(matches)
            visible += matches

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
                labels[0].setText(labels[0].fontMetrics().elidedText(title_text, Qt.TextElideMode.ElideRight, 244))
                labels[0].setToolTip(title_text)
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

        result_id = entry.get('result_id', '')
        header, header_layout = make_editor_grid_card(self._editor_widget, title=self._entry_title(idx, entry), icon_name='fa6s.chart-column', subtitle=result_id)
        self._prep_card(header)
        description = QLabel(self._known_hint(result_id))
        description.setWordWrap(True)
        description.setTextFormat(Qt.TextFormat.PlainText)
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        description.setStyleSheet(ss_dim_label())
        header_layout.addWidget(description, 0, 0)
        self._editor_layout.addWidget(header)

        self._add_section(self._values_section_title(result_id))
        values_card = self._make_card()
        values_grid = self._card_grid(values_card)
        self._active_grid_columns = 3
        values = entry.get("values", [0, 0, 0, 0, 0])
        technical = []
        active = []
        for value_idx in range(5):
            inactive = (result_id in _QUALITY_BONUSES and value_idx > 0
                        or result_id in _BRANCH_IDS and value_idx in (1, 2, 3)
                        or result_id == 'ID_GP_ENDLESS_UP' and value_idx == 4
                        or result_id in _THRESHOLD_IDS - {'JUDGE_TOTAL_8'} and value_idx == 4)
            (technical if inactive else active).append(value_idx)
        for position, value_idx in enumerate(active):
            self._add_uint_field(
                values_grid,
                position // 3,
                position % 3,
                f"value_{value_idx}",
                self._value_label(entry.get("result_id", ""), value_idx),
                values[value_idx] if value_idx < len(values) else 0,
                self._value_hint(entry.get("result_id", ""), value_idx),
                signed=True,
            )
        for col in range(self._grid_columns(3)):
            values_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(values_card)

        technical_card = self._make_card()
        technical_grid = self._card_grid(technical_card)
        self._active_grid_columns = 2
        options = [(value, ui_text('ui_battleresultparam_id_option',
                    result_id=value, label=self._known_label(value)))
                   for value, _label in self._result_id_options(result_id)]
        if not result_id:
            options.insert(0, ('', ui_text('ui_battleresultparam_empty_id')))
        self._add_combo_field(technical_grid, 0, 0, 'result_id',
                              ui_text('ui_battleresultparam_result_id'), result_id,
                              options, ui_text('ui_battleresultparam_result_id_hint'))
        configure_input(self._fields['result_id'], font=ui_font(TypeSize.BODY))
        for position, value_idx in enumerate(technical, 1):
            self._add_uint_field(technical_grid, position // 2, position % 2,
                                 f'value_{value_idx}', self._value_label(result_id, value_idx),
                                 values[value_idx] if value_idx < len(values) else 0,
                                 self._value_hint(result_id, value_idx), signed=True)
        self._editor_layout.addWidget(technical_card)


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
        arcade = os.path.basename(self._filepath or "").lower().startswith("arcaderesultparam")
        if not self._filepath:
            arcade = any(e.get("result_id", "").startswith("JUDGE_TOTAL_") for e in self._entries)
        for result_id in _RESULT_LABEL_KEYS:
            if result_id.startswith("JUDGE_TOTAL_") != arcade:
                continue
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
        if result_id == "ID_GP_ARCADE_DIFFICULT_RATE":
            return ui_text("ui_battleresultparam_arcade_rate_values")
        if result_id == "ID_POINT":
            return ui_text("param_rank_points")
        if result_id in _THRESHOLD_IDS:
            return ui_text("ui_battleresultparam_rank_thresholds")
        if result_id in _QUALITY_BONUSES:
            return ui_text("ui_battleresultparam_quality_bonus_values")
        if result_id in _BRANCH_IDS | _TOURNAMENT_IDS | {"ID_GP", "ID_GP_ARCADE_DIFFICULT_RATE"}:
            return ui_text("ui_battleresultparam_gp_reward_values")
        return ui_text("ui_battleresultparam_result_values")

    def _rank_slot_label(self, value_idx: int) -> str:
        keys = (
            "ui_battleresultparam_rank_s",
            "ui_battleresultparam_rank_a",
            "ui_battleresultparam_rank_b",
            "ui_battleresultparam_rank_c",
            "ui_battleresultparam_rank_d",
        )
        return ui_text(keys[value_idx])

    def _value_label(self, result_id: str, value_idx: int) -> str:
        slot = self._rank_slot_label(value_idx)
        if result_id in {"ID_POINT", "ID_GP"}:
            return ui_text("param_rank_points_slot" if result_id == "ID_POINT" else "param_rank_gp_slot", rank=('S', 'A', 'B', 'C', 'D')[value_idx])
        if result_id in _BRANCH_IDS:
            if value_idx in (0, 4):
                if result_id == "ID_GP_ENDLESS_UP":
                    return ui_text("ui_battleresultparam_endless_ten_wins" if value_idx == 0
                                   else "ui_battleresultparam_unread_slot", index=value_idx + 1)
                return ui_text("ui_battleresultparam_win_gp" if value_idx == 0 else "ui_battleresultparam_loss_gp")
            return ui_text("param_getter_unused", index=value_idx + 1)
        if result_id == "ID_GP_ARCADE_DIFFICULT_RATE" or result_id in _TOURNAMENT_IDS:
            name = ui_text("ui_arcaderewardparam_difficulty_" + _DIFFICULTY_KEYS[value_idx])
            return ui_text("param_difficulty_slot", index=value_idx, name=name)
        if result_id in _THRESHOLD_IDS - {"JUDGE_TOTAL_8"} and value_idx == 4:
            return ui_text("ui_battleresultparam_d_fallback")
        if result_id == "ID_TIME":
            return ui_text("ui_battleresultparam_time_threshold_label", slot=slot)
        if result_id == "ID_LIFE":
            return ui_text("ui_battleresultparam_life_threshold_label", slot=slot)
        if result_id in {"ID_QUALITY", "ID_TOTAL", "JUDGE_TOTAL_8"}:
            return ui_text("ui_battleresultparam_score_threshold_label", slot=slot)
        if result_id in _QUALITY_BONUSES:
            if value_idx == 0:
                return ui_text("ui_battleresultparam_quality_bonus_label")
            return ui_text("ui_battleresultparam_unused_value_label", index=value_idx + 1)
        return ui_text(f"ui_battleresultparam_value_{value_idx + 1}")

    def _value_hint(self, result_id: str, value_idx: int) -> str:
        if result_id in _THRESHOLD_IDS - {"JUDGE_TOTAL_8"} and value_idx == 4:
            return ui_text("ui_battleresultparam_d_fallback_hint")
        if result_id == "ID_POINT":
            return ui_text("param_rank_points_hint")
        if result_id == "ID_TIME":
            return ui_text("ui_battleresultparam_time_threshold_hint")
        if result_id == "ID_LIFE":
            return ui_text("ui_battleresultparam_life_threshold_hint")
        if result_id == "ID_QUALITY":
            return ui_text("ui_battleresultparam_quality_threshold_hint")
        if result_id == "ID_TOTAL":
            return ui_text("ui_battleresultparam_score_threshold_hint")
        if result_id in _QUALITY_BONUSES:
            return ui_text("ui_battleresultparam_quality_bonus_hint" if value_idx == 0
                           else "ui_battleresultparam_quality_unused_hint")
        if result_id in {"ID_QUALITY_S", "JUDGE_TOTAL_3"}:
            return ui_text("ui_battleresultparam_no_consumer_hint")
        if result_id == "JUDGE_TOTAL_8":
            return ui_text("ui_battleresultparam_arcade_threshold_hint")
        if result_id == "ID_GP_ARCADE_DIFFICULT_RATE":
            return ui_text("ui_battleresultparam_arcade_rate_hint")
        if result_id in _BRANCH_IDS | _TOURNAMENT_IDS | {"ID_GP"}:
            if result_id in _BRANCH_IDS and value_idx in (1, 2, 3):
                return ui_text("ui_battleresultparam_quality_unused_hint")
            if result_id == "ID_GP_ENDLESS_UP":
                return ui_text("ui_battleresultparam_endless_up_slot_hint" if value_idx == 0
                               else "ui_battleresultparam_no_caller_hint")
            return ui_text("ui_battleresultparam_gp_slot_hint")
        return ui_text(f"ui_battleresultparam_value_{value_idx + 1}_hint")

    def _add_section(self, title: str):
        self._pending_section_title = title

    def _make_card(self) -> QFrame:
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(self._editor_widget, title=section_title, icon_name='fa6s.sliders')
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
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        return card

    def _prep_field_widget(self, frame: QWidget, editor: QWidget):
        configure_field(frame, editor, vertical_policy=QSizePolicy.Policy.Minimum)

    def _add_text_field(self, grid, row, col, key, label, value, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setMaxLength(96)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(value))
        edit.setCursorPosition(0)
        edit.textEdited.connect(lambda _text: self._mark_dirty())
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
        configure_input(combo, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
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

    def _add_uint_field(self, grid, row, col, key, label, value, hint="", big=False, signed=False):
        frame, layout = self._field_shell(label, hint if key == 'reserved' else '')
        edit = QLineEdit()
        edit.setValidator(self._int_validator if signed else self._uint_validator)
        edit.setMaxLength(11 if signed else 10)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(signed_value(value) if signed else int(value)))
        edit.setToolTip(hint)
        edit.setCursorPosition(0)
        edit.textEdited.connect(lambda _text: self._mark_dirty())
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
        if not self._apply_current_entry():
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
            previous = self._entries[self._current_idx].get("result_id", "")
            if not self._apply_current_entry(show_errors=True):
                self._entries[self._current_idx]["result_id"] = previous
                widget.blockSignals(True)
                widget.setCurrentIndex(widget.findData(previous))
                widget.blockSignals(False)
                return
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
        signed = key.startswith("value_")
        minimum, maximum = (-0x80000000, 0x7FFFFFFF) if signed else (0, _UINT32_MAX)
        try:
            value = int(text)
        except ValueError:
            value = minimum - 1
        if value < minimum or value > maximum:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_battleresultparam_invalid_int32" if signed
                            else "ui_battleresultparam_invalid_uint32", value=text),
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
        pending = {}
        for key in self._fields:
            if key != 'result_id':
                value = self._read_uint(key, show_errors=show_errors)
                if value is None:
                    return False
                pending[key] = value
        if "result_id" in self._fields:
            widget = self._fields["result_id"]
            if isinstance(widget, QComboBox):
                self._entries[self._current_idx]["result_id"] = widget.currentData()
            else:
                self._entries[self._current_idx]["result_id"] = widget.text().strip()
        entry = self._entries[self._current_idx]
        values = list(entry.get('values', [])) + [0] * 5
        for key, value in pending.items():
            if key == 'reserved':
                entry[key] = value
            else:
                values[int(key.split('_')[1])] = value
        entry['values'] = values[:5]
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
        entry = make_default_entry()
        existing = {row.get('result_id', '') for row in self._entries}
        missing = next((key for key, _ in self._result_id_options() if key not in existing), None)
        if missing:
            entry['result_id'] = missing
        self._entries.append(entry)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._list_filter.clear()
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
        self._list_filter.clear()
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
