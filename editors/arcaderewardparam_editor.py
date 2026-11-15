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
    QCompleter,
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
from core.cumulative_research import reward_type_name
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.translations import ui_text
from parsers.arcaderewardparam_parser import (
    TYPE_ARCADE,
    ARCADE_RANK_FIELDS,
    rank_requirements,
    arcade_gp_delta,
    TYPE_CUMULATIVE,
    make_default_entry,
    parse_arcaderewardparam_xfbin,
    save_arcaderewardparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF
_INT32_MIN, _INT32_MAX = -0x80000000, 0x7FFFFFFF
_DIFFICULTY_KEYS = {
    0: "ui_arcaderewardparam_difficulty_veryeasy",
    1: "ui_arcaderewardparam_difficulty_easy",
    2: "ui_arcaderewardparam_difficulty_normal",
    3: "ui_arcaderewardparam_difficulty_hard",
    4: "ui_arcaderewardparam_difficulty_veryhard",
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


class ArcadeRewardParamEditor(QWidget):
    """Embedded editor for ArcadeRewardParam.bin.xfbin and CumulativeRewardParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._result: dict | None = None
        self._param_type = TYPE_ARCADE
        self._entries: list[dict] = []
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._current_idx: int | None = None
        self._fields: dict[str, QLineEdit] = {}
        self._dirty = False
        self._loading_detail = False
        self._last_compact: bool | None = None
        self._active_grid_columns = 3
        self._technical_expanded = False

        self._uint_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,20}"), self)
        self._int_validator = QRegularExpressionValidator(QRegularExpression(r"-?\d{0,20}"), self)
        self._ascii_validator = QRegularExpressionValidator(QRegularExpression(r"[\x20-\x7E]{0,96}"), self)

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

        self._show_placeholder(ui_text("ui_arcaderewardparam_open_file_to_begin_editing"))
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
            ui_text("ui_arcaderewardparam_open_title"),
            game_files_dialog_dir(target_patterns=(
                "ArcadeRewardParam.bin.xfbin",
                "ArcadeRewardParam.xfbin",
                "CumulativeRewardParam.bin.xfbin",
                "CumulativeRewardParam.xfbin",
            )),
            ui_text("ui_arcaderewardparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        try:
            raw, result = parse_arcaderewardparam_xfbin(path)
        except Exception as exc:
            self._filepath = None
            self._raw_data = None
            self._result = None
            self._param_type = TYPE_ARCADE
            self._entries = []
            self._current_idx = None
            self._clear_entry_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_arcaderewardparam_open_file_to_begin_editing"))
            self._update_actions()
            self._filter_list()
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._param_type = result.get("param_type", TYPE_ARCADE)
        self._entries = result["entries"]
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
            self._show_placeholder(ui_text("ui_arcaderewardparam_no_entries"))
        self._update_actions()

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_arcaderewardparam_xfbin(save_path, self._raw_data, self._result)
            with open(save_path, 'rb') as fh:
                self._raw_data = bytearray(fh.read())
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, save_path)
            QMessageBox.information(self, ui_text('dlg_title_success'), ui_text('msg_save_success', path=os.path.basename(save_path)))
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []

    def _populate_list(self):
        self._clear_entry_list()
        if self._param_type == TYPE_CUMULATIVE:
            options = [(value, ui_text(f'param_cumulative_group_{value}')) for value in range(4)]
            options += [(value, ui_text('battle_unknown_value', value=value))
                        for value in sorted({int(e.get('reward_group', 0)) for e in self._entries} - set(range(4)))]
        else:
            options = [(value, ui_text(key)) for value, key in _DIFFICULTY_KEYS.items()]
            options += [(value, ui_text('battle_unknown_value', value=value))
                        for value in sorted({int(e.get('difficulty_index', 0)) for e in self._entries} - set(range(5)))]
        self._list_filter.set_options(options)
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
        button_title = self._entry_button_title(entry)
        subtitle_text = self._entry_button_subtitle(entry)

        title = btn.add_title()


        title.setToolTip(title_text)

        title.ensurePolished()
        title.setText(title.fontMetrics().elidedText(button_title, Qt.TextElideMode.ElideRight, 244))


        subtitle = btn.add_subtitle(_truncate(subtitle_text, 28), value_font=mono_font(TypeSize.CODE))


        subtitle.setToolTip(subtitle_text)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        return entry.get("reward_id", "") or ui_text("ui_arcaderewardparam_empty_id")

    def _entry_button_title(self, entry: dict) -> str:
        reward_id = str(entry.get("reward_id", "") or ui_text("ui_arcaderewardparam_empty_id"))
        if self._param_type == TYPE_ARCADE:
            return ui_text('battle_arcade_payout', gp=arcade_gp_delta(entry))
        prefix_map = {
            "CCD_CUSTOM_CARD_ID_": "CARD ",
            "ID_ART_": "ART ",
            "ID_MUSIC_": "MUSIC ",
            "ID_TITLE_": "TITLE ",
        }
        upper = reward_id.upper()
        for prefix, label in prefix_map.items():
            if upper.startswith(prefix):
                return label + reward_id[len(prefix):]
        return reward_id

    def _entry_button_subtitle(self, entry: dict) -> str:
        if self._param_type == TYPE_CUMULATIVE:
            from core.cumulative_research import threshold_label
            group = int(entry.get('reward_group', 0))
            return f"{entry.get('threshold', 0)} · {threshold_label(group)} · {reward_type_name(entry.get('reward_type', 0))}"
        return f"{self._known_difficulty(entry)} · {entry.get('reward_id', '')}"

    def _filter_list(self):
        query = self._search.text().lower().strip()
        visible = 0
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join([
                str(idx),
                entry.get("reward_id", ""),
                self._known_difficulty(entry) if self._param_type == TYPE_ARCADE else "",
                str(entry.get("difficulty_index", "")),
                *(str(entry.get(key, "")) for key in ARCADE_RANK_FIELDS),
                str(entry.get("reward_value", "")),
                str(entry.get("reward_index", "")),
                str(entry.get("reward_group", "")),
                str(entry.get("threshold", "")),
                str(entry.get("reward_type", "")),
                self._entry_button_title(entry),
                self._entry_button_subtitle(entry),
            ]).lower()
            value = int(entry.get('reward_group' if self._param_type == TYPE_CUMULATIVE else 'difficulty_index', 0))
            matches = (not query or query in haystack) and self._list_filter.accepts(value)
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
                button_title = self._entry_button_title(entry)
                subtitle_text = self._entry_button_subtitle(entry)
                labels[0].setText(labels[0].fontMetrics().elidedText(button_title, Qt.TextElideMode.ElideRight, 244))
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
        self._loading_detail = True
        entry = self._entries[idx]
        self._last_compact = self._is_compact_editor()

        header, header_layout = make_editor_grid_card(self._editor_widget, title=ui_text('battle_arcade_reward_title') if self._param_type == TYPE_ARCADE else self._entry_button_title(entry), icon_name='fa6s.gift', subtitle=entry.get('reward_id', ''))
        self._prep_card(header)
        self._active_grid_columns = 2

        if self._param_type == TYPE_CUMULATIVE:
            self._add_text_field(header_layout, 0, 0, 'reward_id',
                                 ui_text('ui_arcaderewardparam_reward_id'), entry.get('reward_id', ''),
                                 ui_text('cum_reward_id_hint'), big=True)
            self._add_uint_field(
                header_layout,
                0,
                1,
                "threshold",
                self._cumulative_threshold_label(entry),
                entry.get("threshold", 0),
                0,
                _UINT32_MAX,
                ui_text("ui_arcaderewardparam_cumulative_threshold_hint"),
                big=True,
            )
        else:
            self._add_uint_field(
                header_layout,
                0,
                0,
                "reward_value",
                ui_text('battle_gp_amount'),
                arcade_gp_delta(entry),
                _INT32_MIN,
                _INT32_MAX,
                ui_text('battle_gp_amount_hint'),
                big=True,
            )
            self._add_combo_field(header_layout, 0, 1, 'difficulty_index',
                                  ui_text('battle_difficulty'), entry.get('difficulty_index', 0),
                                  self._difficulty_options(entry.get('difficulty_index', 0)),
                                  big=True)
            self._fields['difficulty_index'].setFont(ui_font(TypeSize.CODE))
        if self._grid_columns(2) > 1:
            header_layout.setColumnStretch(0, 2)
            header_layout.setColumnStretch(1, 1)
        else:
            header_layout.setColumnStretch(0, 1)
        self._editor_layout.addWidget(header)

        self._add_section(ui_text('battle_arcade_requirements') if self._param_type == TYPE_ARCADE
                          else ui_text('ui_arcaderewardparam_reward_parameters'))
        values_card = self._make_card()
        values_grid = self._card_grid(values_card)
        self._active_grid_columns = 3
        if self._param_type == TYPE_CUMULATIVE:
            self._build_cumulative_fields(values_grid, entry)
        else:
            self._build_arcade_fields(values_grid, entry)
        for col in range(self._grid_columns(3)):
            values_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(values_card)

        self._add_section(ui_text('battle_reward_condition'))
        self._research_card = self._make_card()
        summary = QLabel()
        summary.setWordWrap(True)
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setStyleSheet(ss_dim_label())
        self._research_card.research_label = summary
        self._card_grid(self._research_card).addWidget(summary, 0, 0)
        self._editor_layout.addWidget(self._research_card)

        technical = self._make_card()
        technical_grid = self._card_grid(technical)
        self._active_grid_columns = 2
        if self._param_type == TYPE_CUMULATIVE:
            self._add_uint_field(technical_grid, 0, 0, 'reward_index',
                                 ui_text('ui_arcaderewardparam_cumulative_index'),
                                 entry.get('reward_index', 0), 0, _UINT32_MAX,
                                 ui_text('ui_arcaderewardparam_cumulative_index_hint'))
        else:
            self._add_text_field(technical_grid, 0, 0, 'reward_id',
                                 ui_text('ui_arcaderewardparam_reward_id'), entry.get('reward_id', ''),
                                 ui_text('ui_arcaderewardparam_reward_id_hint'))
        self._editor_layout.addWidget(technical)

        self._refresh_cumulative_research()

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _build_arcade_fields(self, values_grid, entry: dict):
        for index, (rank, key, value) in enumerate(zip("SABCD", ARCADE_RANK_FIELDS, rank_requirements(entry))):
            self._add_uint_field(
                values_grid, index // 3, index % 3, key,
                ui_text("ui_arcaderewardparam_rank_count", rank=rank), value,
                0, _UINT32_MAX, ui_text("ui_arcaderewardparam_rank_count_hint"),
            )

    def _build_cumulative_fields(self, values_grid, entry: dict):
        self._add_combo_field(
            values_grid,
            0,
            0,
            "reward_group",
            ui_text("ui_arcaderewardparam_cumulative_group"),
            entry.get("reward_group", 0),
            [(value, ui_text(f"param_cumulative_group_{value}")) for value in range(4)] +
            ([(entry["reward_group"], str(entry["reward_group"]))] if int(entry.get("reward_group", 0)) not in range(4) else []),
            ui_text("ui_arcaderewardparam_cumulative_group_hint"),
        )
        self._fields['reward_group'].setFont(ui_font(TypeSize.CODE))
        self._add_combo_field(
            values_grid,
            0,
            1,
            "reward_type",
            ui_text("ui_arcaderewardparam_cumulative_type"),
            entry.get("reward_type", 0),
            [(value, f'{value} · {reward_type_name(value)}') for value in range(9)] +
            ([(entry['reward_type'], ui_text('battle_unknown_value', value=entry['reward_type']))]
             if int(entry.get('reward_type', 0)) not in range(9) else []),
            ui_text("ui_arcaderewardparam_cumulative_type_hint"),
        )
        self._fields['reward_type'].setFont(ui_font(TypeSize.CODE))

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
        if key == "reward_id":
            edit.setValidator(self._ascii_validator)
            edit.setMaxLength(96)
            completer = QCompleter([value for value, _ in self._reward_id_options()], edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            edit.setCompleter(completer)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
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

    def _add_uint_field(self, grid, row, col, key, label, value, min_value, max_value, hint="", big=False):
        frame, layout = self._field_shell(label, '' if key in ARCADE_RANK_FIELDS else hint)
        edit = QLineEdit()
        edit.setValidator(self._int_validator if min_value < 0 else self._uint_validator)
        edit.setMaxLength(20)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setToolTip(hint)
        edit.setCursorPosition(0)
        edit.textEdited.connect(lambda _text: self._mark_dirty())
        edit.editingFinished.connect(lambda k=key, lo=min_value, hi=max_value: self._on_uint_finished(k, lo, hi))
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
        if key == "reward_id":
            self._entries[self._current_idx]["reward_id"] = self._fields[key].text()
            self._refresh_entry_button(self._current_idx)
            self._refresh_cumulative_research()
        self._mark_dirty()

    def _on_combo_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        widget = self._fields.get(key)
        if not isinstance(widget, QComboBox):
            return
        value = widget.currentData()
        self._entries[self._current_idx][key] = value
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)
        self._refresh_cumulative_research()

    @staticmethod
    def _cumulative_threshold_label(entry):
        from core.cumulative_research import threshold_label
        return threshold_label(entry.get('reward_group', 0))

    def _refresh_cumulative_research(self):
        if self._current_idx is None:
            return
        if self._param_type == TYPE_ARCADE:
            entry = self._entries[self._current_idx]
            requirements = ', '.join(f'{rank} ≥ {count}' for rank, count in zip('SABCD', rank_requirements(entry)))
            card = getattr(self, '_research_card', None)
            if card is not None:
                card.research_label.setText(ui_text('battle_arcade_condition',
                    difficulty=self._known_difficulty(entry), requirements=requirements,
                    gp=arcade_gp_delta(entry)))
            return
        from core.cumulative_research import row_description, type_hint, threshold_hint
        from core.parameter_research import set_field_caption, set_field_hint
        entry = self._entries[self._current_idx]
        set_field_caption(self._fields, 'threshold', self._cumulative_threshold_label(entry))
        set_field_hint(self._fields, 'threshold', threshold_hint(entry.get('reward_group', 0)))
        set_field_hint(self._fields, 'reward_type', type_hint(entry.get('reward_type', 0)))
        card = getattr(self, '_research_card', None)
        if card is not None:
            card.research_label.setText(row_description(entry, self._entries))

    def _on_uint_finished(self, key: str, min_value: int, max_value: int):
        if self._loading_detail or self._current_idx is None:
            return
        if self._apply_uint_field(key, min_value, max_value, show_errors=True):
            self._mark_dirty()
            self._refresh_entry_button(self._current_idx)
            self._refresh_cumulative_research()

    def _read_uint(self, key: str, min_value: int, max_value: int, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        if isinstance(widget, QComboBox):
            value = widget.currentData()
            text = str(value)
        else:
            text = widget.text().strip()
            value = None
        try:
            value = int(value if value is not None else text)
        except ValueError:
            value = min_value - 1
        if value < min_value or value > max_value:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_arcaderewardparam_invalid_integer", value=text, min=min_value, max=max_value),
                )
            return None
        return value

    def _apply_uint_field(self, key: str, min_value: int, max_value: int, show_errors: bool = False) -> bool:
        value = self._read_uint(key, min_value, max_value, show_errors=show_errors)
        if value is None:
            return False
        if key == "version":
            if self._result is not None:
                self._result["version"] = value
            return True
        if self._current_idx is None or self._current_idx >= len(self._entries):
            return True
        self._entries[self._current_idx][key] = value
        return True

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._current_idx is None:
            return True
        if self._result is not None:
            if "version" in self._fields:
                version = self._read_uint("version", 0, _UINT32_MAX, show_errors=show_errors)
                if version is None:
                    return False
                self._result["version"] = version
            if "notes_hex" in self._fields:
                notes = self._read_notes_hex(show_errors=show_errors)
                if notes is None:
                    return False
                self._result["notes"] = notes
        if "reward_id" in self._fields:
            widget = self._fields["reward_id"]
            if isinstance(widget, QComboBox):
                self._entries[self._current_idx]["reward_id"] = widget.currentData()
            else:
                self._entries[self._current_idx]["reward_id"] = widget.text()
        pending = {}
        for key, min_value, max_value in self._entry_uint_fields():
            if key not in self._fields:
                continue
            value = self._read_uint(key, min_value, max_value, show_errors=show_errors)
            if value is None:
                return False
            pending[key] = value
        self._entries[self._current_idx].update(pending)
        self._refresh_entry_button(self._current_idx)
        self._refresh_cumulative_research()
        return True

    def _entry_uint_fields(self) -> tuple[tuple[str, int, int], ...]:
        if self._param_type == TYPE_CUMULATIVE:
            return (
                ("reward_index", 0, _UINT32_MAX),
                ("reward_group", 0, _UINT32_MAX),
                ("threshold", 0, _UINT32_MAX),
                ("reward_type", 0, _UINT32_MAX),
            )
        return (
            ("difficulty_index", 0, _UINT32_MAX),
            *((key, 0, _UINT32_MAX) for key in ARCADE_RANK_FIELDS),
            ("reward_value", _INT32_MIN, _INT32_MAX),
            ("padding_24", 0, _UINT32_MAX),
        )

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
                    ui_text("ui_arcaderewardparam_invalid_hex"),
                )
            return None

    def _reward_id_options(self, current_value: str = "") -> list[tuple[str, str]]:
        values = []
        seen = set()
        for entry in self._entries:
            value = entry.get("reward_id", "")
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        if current_value and current_value not in seen:
            values.append(current_value)
        if not values:
            values.append("NORMAL_1")
        return [(value, value) for value in values]

    def _difficulty_options(self, current_value: int) -> list[tuple[int, str]]:
        values = list(_DIFFICULTY_KEYS)
        if current_value not in values:
            values.append(current_value)
        return [
            (value, ui_text(_DIFFICULTY_KEYS[value]) if value in _DIFFICULTY_KEYS
             else ui_text('battle_unknown_value', value=value))
            for value in values
        ]

    def _known_difficulty(self, entry: dict) -> str:
        key = _DIFFICULTY_KEYS.get(int(entry.get("difficulty_index", 0)))
        return ui_text(key) if key else ui_text("ui_arcaderewardparam_unknown_difficulty")

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
        entry = make_default_entry(param_type=self._param_type)
        if self._param_type == TYPE_ARCADE:
            entry["reward_id"] = self._unique_arcade_reward_id(entry["reward_id"])
        else:
            from core.cumulative_research import next_slot
            entry['reward_index'] = next_slot(self._entries, entry['reward_group'])
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
        new_idx = self._current_idx + 1
        if self._param_type == TYPE_ARCADE:
            new_entry["reward_id"] = self._unique_arcade_reward_id(new_entry["reward_id"])
            new_idx = len(self._entries)
        else:
            from core.cumulative_research import next_slot
            new_entry['reward_index'] = next_slot(self._entries, new_entry['reward_group'])
        self._entries.insert(new_idx, new_entry)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._list_filter.clear()
        self._select_entry(new_idx)

    def _unique_arcade_reward_id(self, base: str) -> str:
        # Native 47644C indexes the map by CRC, not by the complete string.
        # Byte order of the existing message CRC helper does not affect equality.
        from parsers.messageinfo_parser import crc32_of
        used = {crc32_of(entry.get("reward_id", "")) for entry in self._entries}
        candidate = base or "REWARD"
        suffix = 2
        while crc32_of(candidate) in used:
            candidate = f"{base or 'REWARD'}_{suffix}"
            suffix += 1
        return candidate

    def _do_del(self):
        if self._raw_data is None or self._current_idx is None:
            return
        entry = self._entries[self._current_idx]
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("msg_confirm_delete_item", name=entry.get("reward_id", "")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        old_idx = self._current_idx
        group = entry.get('reward_group', 0)
        compact_group = False
        if self._param_type == TYPE_CUMULATIVE:
            from core.cumulative_research import has_dense_slots
            compact_group = has_dense_slots(self._entries, group)
        self._entries.pop(old_idx)
        if compact_group:
            from core.cumulative_research import compact_slots
            compact_slots(self._entries, group)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        if self._entries:
            self._select_entry(min(old_idx, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text("ui_arcaderewardparam_no_entries"))
            self._update_actions()
