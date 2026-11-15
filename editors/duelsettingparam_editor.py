from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
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
    EditorFilterCombo,
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
import math
import os
import re
import struct
from decimal import Decimal

from PyQt6.QtCore import QRegularExpression, Qt, QTimer
from PyQt6.QtGui import QFont, QFontMetrics, QRegularExpressionValidator
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
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.movelist_text import MoveListText
from core.duel_research import editable_arguments, rule_description
from core.translations import current_language, ui_text
from parsers.duelsettingparam_parser import (
    argument_values,
    make_default_entry,
    parse_duelsettingparam_xfbin,
    save_duelsettingparam_xfbin,
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


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _float_text(value):
    """Shortest readable decimal which keeps the exact stored f32 bits."""
    value = float(value)
    packed = struct.pack('<f', value)
    for precision in range(1, 10):
        text = format(value, f'.{precision}g')
        try:
            if struct.pack('<f', float(text)) == packed:
                if 'e' in text and 1e-4 <= abs(value) < 1e7:
                    text = format(Decimal(text), 'f')
                return text
        except OverflowError:
            continue
    return format(value, '.9g')


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
        self._dirty = False
        self._loading_detail = False
        self._last_compact: bool | None = None
        self._active_grid_columns = 3
        self._research_card = None
        self._argument_hint_label = None
        self._text_lookup = None
        self._last_columns = None
        self._text_previews = {}

        self._uint32_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._float_validator = QRegularExpressionValidator(
            QRegularExpression(r"[-+]?(?:\d+\.?\d*|\.\d+)?(?:[eE][-+]?\d+)?"),
            self,
        )

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if value == key and fallback is not None else value

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

        sidebar = EditorSidebar()


        sidebar_layout = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.setClearButtonEnabled(True)
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)

        self._type_filter = EditorFilterCombo()
        configure_input(self._type_filter)
        self._type_filter.setAccessibleName(ui_text('duel_filter_type'))
        self._type_filter.addItem(ui_text('duel_all_types'), None)
        for kind in range(5):
            self._type_filter.addItem(ui_text(f'duel_type_{kind}'), kind)
        self._type_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._type_filter)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


        self._btn_add = self._make_action_button("btn_new", self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        self._btn_dup = self._make_action_button("btn_duplicate", self._do_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        self._btn_del = self._make_action_button("btn_delete", self._do_del, danger=True)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_add, 1)
        actions_layout.addWidget(self._btn_dup, 1)
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
        self._no_results = QLabel(ui_text('duel_no_results'))
        self._no_results.setWordWrap(True)
        self._no_results.setStyleSheet(ss_dim_label())
        self._no_results.hide()
        sidebar_layout.addWidget(self._no_results)
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

        self._show_placeholder(ui_text("ui_duelsettingparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)
        self._update_actions()

    def _make_action_button(self, key: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(ui_text('duel_' + key))
        btn.setToolTip(self._tr(key, ui_text(key)))
        btn.setEnabled(False)
        configure_button(btn, danger=danger, height=Size.COMPACT_CONTROL)
        btn.clicked.connect(slot)
        return btn

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._research_card = None
        self._text_previews = {}
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
            self._dirty = False
            self._text_lookup = None
            self._clear_entry_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_duelsettingparam_open_file_to_begin_editing"))
            self._filter_list()
            self._update_actions()
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._text_lookup = MoveListText(path, current_language(), load_settings().get('game_files_dir', ''))
        self._entries = result["entries"]
        self._current_idx = None
        self._dirty = False
        self._btn_save.setEnabled(False)
        self._search.setText("")
        self._type_filter.setCurrentIndex(0)
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_duelsettingparam_no_entries"))
        self._update_actions()

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_duelsettingparam_xfbin(save_path, self._raw_data, self._result)
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
        for idx, entry in enumerate(self._entries):
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = EditorListRow(height=68)

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = self._entry_title(idx, entry)
        subtitle_text = self._entry_subtitle(entry)
        btn._search_text = self._entry_search_text(idx, entry)

        title = btn.add_title()
        title.setWordWrap(True)
        title.setFixedHeight(38)
        title.setTextFormat(Qt.TextFormat.PlainText)

        title.setText(self._sidebar_title(title_text, title.font()))


        title.setToolTip(title_text)


        subtitle = btn.add_subtitle(_truncate(subtitle_text, 28), value_font=ui_font(TypeSize.CODE))


        subtitle.setToolTip(subtitle_text)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        return (self._game_text(entry.get('title_key', '')) or entry.get('title_key', '')
                or ui_text('duel_untitled'))

    @staticmethod
    def _sidebar_title(text, font):
        """Two readable lines with an ellipsis; the tooltip keeps the full name."""
        metrics = QFontMetrics(font)
        words = str(text).split()
        first = ''
        for index, word in enumerate(words):
            candidate = f'{first} {word}'.strip()
            if metrics.horizontalAdvance(candidate) > 210:
                remainder = ' '.join(words[index:])
                if not first:
                    return metrics.elidedText(' '.join(words), Qt.TextElideMode.ElideRight, 210)
                return first + '\n' + metrics.elidedText(remainder, Qt.TextElideMode.ElideRight, 210)
            first = candidate
        return first

    def _game_text(self, key):
        if not key or self._text_lookup is None:
            return ''
        text, language = self._text_lookup.text(key)
        text = re.sub(r'<[^>]*>', '', text).strip()
        if text and language == 'jpn' and getattr(self._text_lookup, 'language', 'en') not in ('ja', 'jpn'):
            # Two legacy Pucci titles exist only in Japanese. Keep the authored
            # text, with a readable key even in themes without Japanese glyphs.
            return f'{key} · {text}'
        return text

    def _entry_subtitle(self, entry: dict) -> str:
        kind = int(entry.get('type_id', 0))
        name = ui_text(f'duel_type_{kind}') if kind in range(5) else ui_text('duel_unknown_type', value=kind)
        if kind in range(5):
            name = name.split(' — ', 1)[-1]
        return f"{name} · ID {int(entry.get('sequence_id', 0))}"

    def _entry_search_text(self, idx, entry):
        return ' '.join([str(idx), *(str(value) for value in entry.values()),
                         self._entry_title(idx, entry), self._entry_subtitle(entry),
                         self._game_text(entry.get('hidden_title_key', '')),
                         self._game_text(entry.get('hint_key', ''))]).lower()

    def _filter_list(self):
        query = self._search.text().lower().strip()
        kind = self._type_filter.currentData()
        visible = 0
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = btn._search_text
            matches = (kind is None or int(entry.get('type_id', 0)) == kind) and all(
                word in haystack for word in query.split())
            btn.setVisible(matches)
            visible += int(matches)
        self._no_results.setVisible(bool(self._entries) and not visible)

    def _select_entry(self, idx: int):
        if idx < 0 or idx >= len(self._entries):
            return
        if not self._apply_current_entry(show_errors=True):
            return
        previous_idx = self._current_idx
        self._current_idx = idx
        for btn, button_idx in self._entry_buttons:
            if button_idx in (previous_idx, idx):
                btn.setStyleSheet(ss_sidebar_btn(selected=button_idx == idx))
        self._build_editor(idx)
        self._update_actions()
        self._editor_scroll.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._scroll_to_current_entry)

    def _scroll_to_current_entry(self):
        if self._current_idx is None:
            return
        for button, index in self._entry_buttons:
            if index == self._current_idx and not button.isHidden():
                self._entry_scroll.ensureWidgetVisible(button)
                break

    def _refresh_entry_button(self, idx: int):
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if labels:
                title_text = self._entry_title(idx, self._entries[idx])
                labels[0].setText(self._sidebar_title(title_text, labels[0].font()))
                labels[0].setToolTip(title_text)
            if len(labels) >= 2:
                subtitle_text = self._entry_subtitle(self._entries[idx])
                labels[1].setText(_truncate(subtitle_text, 28))
                labels[1].setToolTip(subtitle_text)
            btn._search_text = self._entry_search_text(idx, self._entries[idx])
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
        self._text_previews = {}
        self._loading_detail = True
        entry = self._entries[idx]
        self._last_compact = self._is_compact_editor()
        self._last_columns = self._grid_columns(2)

        header, body = make_editor_card(self._editor_widget)
        self._prep_card(header)
        _, self._header_title, self._header_subtitle = add_editor_card_title(
            body, self._entry_title(idx, entry), 'fa6s.flag-checkered', self._entry_subtitle(entry))
        self._header_title.setTextFormat(Qt.TextFormat.PlainText)
        header_layout = QGridLayout()
        header_layout.setHorizontalSpacing(Size.GRID_GAP)
        header_layout.setVerticalSpacing(Size.CARD_GAP)
        body.addLayout(header_layout)
        self._active_grid_columns = 2
        self._add_combo_field(header_layout, 0, 0, "type_id", ui_text("ui_duelsettingparam_type_id"), entry.get("type_id", 0), [(ui_text(f"duel_type_{value}"), value) for value in range(5)], big=True)
        self._add_uint_field(header_layout, 0, 1, "sequence_id", ui_text("ui_duelsettingparam_sequence_id"), entry.get("sequence_id", 0), big=True)
        self._fields['sequence_id'].setToolTip(ui_text('duel_handler_hint'))
        shell, shell_layout = self._field_shell(ui_text('duel_handler'))
        self._rule_combo = QComboBox()
        self._rule_combo.setEditable(True)
        self._rule_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        configure_input(self._rule_combo, monospace=False)
        self._rule_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._rule_combo.setToolTip(ui_text('duel_handler_hint'))
        self._rule_combo.setAccessibleName(ui_text('duel_handler'))
        shell_layout.addWidget(self._rule_combo)
        body.addWidget(shell)
        self._rule_combo.activated.connect(self._choose_handler)
        self._rule_combo.lineEdit().editingFinished.connect(self._finish_handler_search)
        self._refresh_handler_choices()
        self._identity_hint = self._plain_hint('')
        body.addWidget(self._identity_hint)
        self._editor_layout.addWidget(header)

        self._add_section(ui_text('duel_settings'))
        self._settings_card = self._make_card()
        self._settings_grid = self._card_grid(self._settings_card)
        self._research_card = self._settings_card
        self._research_card.research_label = self._plain_hint('')
        self._settings_card.layout().insertWidget(1, self._research_card.research_label)
        self._active_grid_columns = 2
        from core.duel_research import control_label
        for index in range(5):
            self._add_float_field(self._settings_grid, index // 2, index % 2,
                                  f'value_{index + 1}', control_label(entry, index), self._entry_value(entry, index))
        self._editor_layout.addWidget(self._settings_card)

        self._add_section(ui_text('duel_stored_values'))
        self._stored_card = self._make_card()
        self._stored_grid = self._card_grid(self._stored_card)
        self._editor_layout.addWidget(self._stored_card)

        self._add_section(ui_text("ui_duelsettingparam_conditions"))
        cond_card = self._make_card()
        cond_grid = self._card_grid(cond_card)
        self._active_grid_columns = 2
        self._add_text_field(cond_grid, 0, 0, "condition_id", ui_text("ui_duelsettingparam_condition_id"), entry.get("condition_id", ""))
        self._add_text_field(cond_grid, 0, 1, "target_names", ui_text("ui_duelsettingparam_target_names"), entry.get("target_names", ""))
        for key, hint_key in (('condition_id', 'duel_scm_help'), ('target_names', 'duel_attacks_help')):
            widget = self._fields[key]
            widget.setToolTip(ui_text(hint_key))
            widget.parentWidget().layout().addWidget(self._plain_hint(ui_text(hint_key)))
        self._editor_layout.addWidget(cond_card)

        self._add_section(ui_text("ui_duelsettingparam_text_keys"))
        text_card = self._make_card()
        text_grid = self._card_grid(text_card)
        self._active_grid_columns = 2
        self._add_text_field(text_grid, 0, 0, "title_key", ui_text("ui_duelsettingparam_title_key"), entry.get("title_key", ""))
        self._add_text_field(text_grid, 0, 1, "hidden_title_key", ui_text("ui_duelsettingparam_hidden_title_key"), entry.get("hidden_title_key", ""))
        self._add_text_field(text_grid, 1, 0, "hint_key", ui_text("ui_duelsettingparam_hint_key"), entry.get("hint_key", ""))
        text_card.layout().insertWidget(1, self._plain_hint(ui_text('duel_text_help')))
        for key in ('title_key', 'hidden_title_key', 'hint_key'):
            label = self._plain_hint('')
            self._fields[key].parentWidget().layout().addWidget(label)
            self._text_previews[key] = label
        self._editor_layout.addWidget(text_card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._refresh_argument_captions()
        self._refresh_text_previews()
        self._loading_detail = False

    def _plain_hint(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(ss_dim_label())
        label.setFont(ui_font(TypeSize.HINT))
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _arrange_arguments(self):
        entry = self._entries[self._current_idx]
        active = editable_arguments(entry)
        columns = self._grid_columns(2)
        positions = [0, 0]
        frames = [self._fields[f'value_{i + 1}'].parentWidget() for i in range(5)]
        for frame in frames:
            self._settings_grid.removeWidget(frame)
            self._stored_grid.removeWidget(frame)
        for index, frame in enumerate(frames):
            group = 0 if index in active else 1
            grid = self._settings_grid if group == 0 else self._stored_grid
            row, col = divmod(positions[group], columns)
            grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(col, 1)
            frame.show()
            positions[group] += 1
        self._stored_card.setVisible(bool(positions[1]))

    def _refresh_handler_choices(self):
        entry = self._entries[self._current_idx]
        kind = int(entry.get('type_id', 0))
        choices = [(index, row) for index, row in enumerate(self._entries)
                   if int(row.get('type_id', 0)) == kind]
        combo = self._rule_combo
        combo.blockSignals(True)
        combo.clear()
        for index, row in sorted(choices, key=lambda choice: int(choice[1].get('sequence_id', 0))):
            ident = int(row.get('sequence_id', 0))
            text = f"{ident} · {self._entry_title(0, row)}"
            combo.addItem(text, index)
            combo.setItemData(combo.count() - 1, text, Qt.ItemDataRole.ToolTipRole)
        combo.setCurrentIndex(combo.findData(self._current_idx))
        combo.setToolTip(combo.currentText() + '\n\n' + ui_text('duel_handler_hint'))
        combo.blockSignals(False)
        completer = combo.completer()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

    def _choose_handler(self, index):
        if self._loading_detail or index < 0:
            return
        row_index = self._rule_combo.itemData(index)
        if row_index is None or row_index == self._current_idx:
            return
        # IDs are also lookup identities. Navigate to the authored row instead
        # of changing this row to an ID already owned by a different rule.
        self._select_entry(row_index)
        self._refresh_handler_choices()
        if self._current_idx == row_index:
            self._reset_filters()

    def _finish_handler_search(self):
        if not self._loading_detail:
            # QComboBox emits editingFinished before accepting a completion.
            # Rebuilding its model in that signal discards the chosen result.
            QTimer.singleShot(0, self._restore_handler_choice)

    def _restore_handler_choice(self):
        if self._current_idx is not None and not self._loading_detail:
            self._refresh_handler_choices()

    def _refresh_text_previews(self):
        if self._current_idx is None:
            return
        entry = self._entries[self._current_idx]
        for key, label in self._text_previews.items():
            text = self._game_text(entry.get(key, ''))
            label.setText(text or ui_text('duel_text_missing'))
        self._header_title.setText(self._entry_title(self._current_idx, entry))
        self._header_subtitle.setText(self._entry_subtitle(entry))
        index = self._rule_combo.findData(self._current_idx)
        if index >= 0:
            self._rule_combo.blockSignals(True)
            self._rule_combo.setItemText(index, f"{int(entry.get('sequence_id', 0))} · {self._entry_title(self._current_idx, entry)}")
            self._rule_combo.blockSignals(False)

    def _entry_value(self, entry: dict, idx: int) -> float:
        return float(argument_values(entry)[idx])

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
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        return card

    def _prep_field_widget(self, frame: QWidget, editor: QWidget):
        configure_field(frame, editor, vertical_policy=QSizePolicy.Policy.Minimum)

    def _make_card(self) -> QFrame:
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(self._editor_widget, title=section_title, icon_name='fa6s.sliders')
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
        hint.setFont(ui_font(TypeSize.HINT))
        hint.setStyleSheet(ss_dim_label())
        hint.setMinimumWidth(0)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        max_cols = max_columns or getattr(self, "_active_grid_columns", 3)
        mapped_row, mapped_col = self._field_position(row, col, max_cols)
        grid.addWidget(hint, mapped_row, mapped_col, 1, colspan)
        return hint

    def _add_text_field(self, grid, row, col, key, label, value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(value))
        edit.setCursorPosition(0)
        edit.textChanged.connect(lambda _text, k=key: self._on_text_changed(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def _add_uint_field(self, grid, row, col, key, label, value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._uint32_validator)
        edit.setMaxLength(10)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key: self._on_uint_finished(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def _add_combo_field(self, grid, row, col, key, label, value, options, big=False):
        frame, layout = self._field_shell(label)
        combo = QComboBox()
        configure_input(combo, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for text, data in options:
            combo.addItem(text, data)
        selected = combo.findData(int(value))
        if selected < 0:
            combo.addItem(ui_text('duel_unknown_type', value=int(value)), int(value))
            selected = combo.count() - 1
        combo.setCurrentIndex(selected)
        combo.currentIndexChanged.connect(lambda _idx, k=key: self._on_combo_changed(k))
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = combo

    def _add_float_field(self, grid, row, col, key, label, value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._float_validator)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(_float_text(value))
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key: self._on_float_finished(k))
        layout.addWidget(edit)
        layout.addWidget(self._plain_hint(''))
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col, Qt.AlignmentFlag.AlignTop)
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
        if compact == self._last_compact and self._grid_columns(2) == self._last_columns:
            return
        if not self._apply_current_entry(show_errors=False):
            return
        position = self._editor_scroll.verticalScrollBar().value()
        self._build_editor(self._current_idx)
        self._editor_scroll.verticalScrollBar().setValue(position)

    def _on_text_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        if key == "notes_hex":
            self._mark_dirty()
            return
        self._entries[self._current_idx][key] = self._fields[key].text()
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)
        if key in ('condition_id', 'target_names', 'title_key', 'hidden_title_key', 'hint_key'):
            self._refresh_research_text()
            self._refresh_text_previews()

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
        self._refresh_handler_choices()
        self._refresh_text_previews()
        self._refresh_argument_captions()

    def _refresh_argument_captions(self):
        from core.parameter_research import duel_value_hint, set_field_caption
        from core.duel_research import control_hint, control_label
        entry = self._entries[self._current_idx]
        for i in range(5):
            set_field_caption(self._fields, f'value_{i + 1}', control_label(entry, i))
            self._fields[f'value_{i + 1}'].setToolTip(duel_value_hint(entry, i))
            shell = self._fields[f'value_{i + 1}'].parentWidget().layout()
            shell.itemAt(2).widget().setText(control_hint(entry, i))
        if self._argument_hint_label is not None:
            self._argument_hint_label.setText(duel_value_hint(entry, 0))
        self._refresh_research_text()
        self._arrange_arguments()

    def _refresh_research_text(self):
        if self._research_card is None or self._current_idx is None:
            return
        entry = self._entries[self._current_idx]
        self._research_card.research_label.setText(rule_description(entry))
        sequence = int(entry.get('sequence_id', 0))
        duplicates = sum(int(row.get('sequence_id', 0)) == sequence for row in self._entries)
        text = ui_text('duel_duplicate_id', value=sequence) if duplicates > 1 else ui_text('duel_handler_hint')
        self._identity_hint.setText(text)

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
        if key == 'sequence_id':
            self._refresh_handler_choices()
            self._refresh_text_previews()
            self._refresh_argument_captions()

    def _on_float_finished(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._read_float(key, show_errors=True)
        if value is None:
            return
        value_idx = int(key.rsplit("_", 1)[1]) - 1
        values = argument_values(self._entries[self._current_idx])
        values[value_idx] = value
        self._entries[self._current_idx]["values"] = values

    def _read_ascii(self, key: str, show_errors: bool = False) -> str | None:
        widget = self._fields.get(key)
        if widget is None:
            return ""
        text = widget.text()
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
            if not math.isfinite(value):
                raise ValueError('Non-finite float')
            # Validate and store the actual f32 value. Short round-trip decimal
            # strings near FLT_MAX can lie just above its exact Python double.
            value = struct.unpack('<f', struct.pack('<f', value))[0]
        except (ValueError, OverflowError, struct.error):
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
        for key in ("type_id", "sequence_id", "reserved_28"):
            if key not in self._fields:
                continue
            value = self._read_uint(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        values = argument_values(entry)
        for idx, key in enumerate(("value_1", "value_2", "value_3", "value_4", "value_5")):
            if key not in self._fields:
                continue
            value = self._read_float(key, show_errors=show_errors)
            if value is None:
                return False
            values[idx] = value
        entry["values"] = values
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
        entry = make_default_entry()
        entry['sequence_id'] = self._next_sequence_id()
        self._entries.append(entry)
        self._current_idx = None
        self._reset_filters()
        self._mark_dirty()
        self._populate_list()
        self._select_entry(len(self._entries) - 1)

    def _do_dup(self):
        if self._raw_data is None or self._current_idx is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        entry = make_default_entry(copy.deepcopy(self._entries[self._current_idx]))
        entry['sequence_id'] = self._next_sequence_id()
        self._entries.insert(self._current_idx + 1, entry)
        new_idx = self._current_idx + 1
        self._current_idx = None
        self._reset_filters()
        self._mark_dirty()
        self._populate_list()
        self._select_entry(new_idx)

    def _next_sequence_id(self):
        used = {int(entry.get('sequence_id', 0)) for entry in self._entries}
        candidate = max((value for value in used if value != _UINT32_MAX), default=-1) + 1
        if candidate < _UINT32_MAX:
            return candidate
        candidate = 0
        while candidate in used:
            candidate += 1
        return candidate

    def _reset_filters(self):
        self._search.clear()
        self._type_filter.setCurrentIndex(0)

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
