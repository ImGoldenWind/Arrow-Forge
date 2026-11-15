from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_bg_dark,
    ss_dim_label,
    ss_main_label,
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
import os

from PyQt6.QtCore import QEvent, QRegularExpression, Qt, QTimer
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
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.movelist_text import MoveListText
from core.translations import current_language
from core.translations import ui_text
from parsers.commandlistparam_parser import (
    TYPE_DISABLED,
    TYPE_NAMES,
    make_default_entry,
    parse_commandlistparam_xfbin,
    save_commandlistparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF
_INT32_MIN = -0x80000000
_INT32_MAX = 0x7FFFFFFF

_TYPE_LABEL_KEYS = {
    0: "ui_commandlistparam_type_unk",
    1: "ui_commandlistparam_type_skl",
    2: "ui_commandlistparam_type_hha",
    3: "ui_commandlistparam_type_gha",
    5: "ui_commandlistparam_type_btlcmd_th",
    6: "ui_commandlistparam_type_btlcmd",
    7: "ui_commandlistparam_type_skl_02",
    TYPE_DISABLED: "ui_commandlistparam_type_disabled",
}

_NUMERIC_FIELDS = (
    ("unk5", "ui_commandlistparam_unk5", 0, _UINT32_MAX),
    ("unk6", "ui_commandlistparam_unk6", 0, _UINT32_MAX),
    ("unk7", "ui_commandlistparam_unk7", 0, _UINT32_MAX),
    ("unk8", "ui_commandlistparam_unk8", 0, _UINT32_MAX),
    ("unk9", "ui_commandlistparam_unk9", 0, _UINT32_MAX),
    ("unk10", "ui_commandlistparam_unk10", 0, _UINT32_MAX),
    ("command_list_num", "ui_commandlistparam_command_list_num", _INT32_MIN, _INT32_MAX),
    ("unk12", "ui_commandlistparam_unk12", _INT32_MIN, _INT32_MAX),
)


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


class CommandListParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._result: dict | None = None
        self._entries: list[dict] = []
        self._current_idx: int | None = None
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._fields: dict[str, QLineEdit] = {}
        self._type_combo: QComboBox | None = None
        self._dirty = False
        self._loading_detail = False
        self._last_compact: int | None = None
        self._texts = MoveListText()
        self._text_root = ''
        self._type_labels = {}
        self._character_labels = {}
        self._search_index = {}
        self._active_grid_columns = 3

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

        self._btn_texts = QPushButton(ui_text('movelist_text_folder'))
        configure_button(self._btn_texts)
        self._btn_texts.clicked.connect(self._choose_text_folder)
        top_layout.addWidget(self._btn_texts)

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
        self._search.setClearButtonEnabled(True)
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)
        configure_search(self._search)
        self._char_filter = EditorFilterCombo()
        configure_input(self._char_filter)
        self._char_filter.addItem(ui_text('movelist_all_characters'), '')
        self._char_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._char_filter)
        self._type_filter = EditorFilterCombo()
        configure_input(self._type_filter)
        self._type_filter.addItem(ui_text('movelist_all_types'), None)
        self._type_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._type_filter)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._btn_add.setEnabled(False)
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.clicked.connect(self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
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
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_commandlistparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._type_combo = None
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_commandlistparam_open_title"),
            game_files_dialog_dir(target_patterns=("CommandListParam.bin.xfbin", "CommandListParam.xfbin")),
            ui_text("ui_commandlistparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        if self._dirty and not self._confirm_discard():
            return
        create_backup_on_open(path)
        try:
            raw, result = parse_commandlistparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._texts = MoveListText(path, current_language(), self._text_root or load_settings().get('game_files_dir', ''))
        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._entries = result["entries"]
        self._current_idx = None
        self._dirty = False
        self._btn_add.setEnabled(True)
        self._btn_save.setEnabled(False)
        self._clear_filters()
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_commandlistparam_no_entries"))
        self._update_actions()

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_commandlistparam_xfbin(save_path, self._raw_data, self._result)
            with open(save_path, 'rb') as fh:
                self._raw_data = bytearray(fh.read())
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, save_path)
            QMessageBox.information(self, ui_text('dlg_title_success'), ui_text('msg_save_success', path=os.path.basename(save_path)))
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))

    def _populate_list(self):
        self._search_index.clear()
        char = self._char_filter.currentData()
        kind = self._type_filter.currentData()
        for combo in (self._char_filter, self._type_filter):
            combo.blockSignals(True)
            combo.clear()
        self._char_filter.addItem(ui_text('movelist_all_characters'), '')
        for code in sorted({e.get('char_id', '') for e in self._entries}):
            name = self._character_name(code)
            self._char_filter.addItem(f'{name} ({code})' if name != code else code or ui_text('ui_commandlistparam_empty_char'), code)
        self._char_filter.setCurrentIndex(max(0, self._char_filter.findData(char)))
        self._type_filter.addItem(ui_text('movelist_all_types'), None)
        for value in sorted({int(e.get('move_type', 0)) for e in self._entries}):
            self._type_filter.addItem(self._type_label(value), value)
        self._type_filter.setCurrentIndex(max(0, self._type_filter.findData(kind)))
        for combo in (self._char_filter, self._type_filter):
            combo.blockSignals(False)
        self._clear_entry_list()
        for idx, entry in enumerate(self._entries):
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = EditorListRow(height=50)

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = self._entry_title(idx, entry)
        subtitle_text = self._entry_subtitle(entry)
        button_title = self._entry_button_title(idx, entry)
        button_subtitle = self._entry_button_subtitle(entry)

        title = btn.add_title(_truncate(button_title, 24))


        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setToolTip(self._entry_tooltip(idx, entry))


        subtitle = btn.add_subtitle(_truncate(button_subtitle, 30))


        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        subtitle.setToolTip(self._entry_tooltip(idx, entry))


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        btn.installEventFilter(self)
        return btn

    def eventFilter(self, watched, event):
        keys = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End)
        if event.type() == QEvent.Type.KeyPress and event.key() in keys:
            visible = [(button, idx) for button, idx in self._entry_buttons if not button.isHidden()]
            position = next((i for i, (button, _) in enumerate(visible) if button is watched), None)
            if position is not None:
                if event.key() == Qt.Key.Key_Home:
                    target = 0
                elif event.key() == Qt.Key.Key_End:
                    target = len(visible) - 1
                else:
                    target = max(0, min(len(visible) - 1, position + (1 if event.key() == Qt.Key.Key_Down else -1)))
                button, idx = visible[target]
                self._select_entry(idx)
                if self._current_idx == idx:
                    button.setFocus()
                    self._entry_scroll.ensureWidgetVisible(button)
                return True
        return super().eventFilter(watched, event)

    def _type_label(self, value: int) -> str:
        value = int(value)
        if value in self._type_labels:
            return self._type_labels[value]
        key = _TYPE_LABEL_KEYS.get(int(value))
        if key:
            label = ui_text(key)
        else:
            label = ui_text("ui_commandlistparam_type_custom", value=value)
        self._type_labels[value] = label
        return label

    def _entry_title(self, idx, entry):
        return self._texts.name(entry) or ui_text('ui_commandlistparam_empty_text_key')

    def _entry_button_title(self, idx, entry):
        return self._entry_title(idx, entry)

    def _entry_subtitle(self, entry):
        character = self._character_name(entry.get('char_id', ''))
        return f"{character} · {self._type_label(entry.get('move_type', 0))} · {entry.get('name_key', '')}"

    def _entry_button_subtitle(self, entry):
        return f"{self._character_name(entry.get('char_id', ''))} · {self._type_label(entry.get('move_type', 0))}"

    def _filter_list(self):
        words = self._search.text().casefold().split()
        character = self._char_filter.currentData()
        kind = self._type_filter.currentData()
        visible = 0
        for button, idx in self._entry_buttons:
            if idx >= len(self._entries):
                button.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = self._search_index.get(idx)
            if haystack is None:
                key = entry.get('name_key', '')
                japanese = self._texts.text(key, japanese=True)[0]
                english = self._texts._resolve(key, self._texts.tables.get('eng', {}))
                haystack = ' '.join((str(idx + 1), self._texts.name(entry), japanese, english,
                                    self._character_name(entry.get('char_id', '')),
                                    self._type_label(entry.get('move_type', 0)),
                                    *(str(entry.get(k, '')) for k in ('char_id', 'name_key', 'detail_key', 'input_key', 'command_list_num')))).casefold()
                self._search_index[idx] = haystack
            matches = ((not character or character == entry.get('char_id', ''))
                       and (kind is None or int(entry.get('move_type', 0)) == kind)
                       and all(word in haystack for word in words))
            button.setVisible(matches)
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
        self._search_index.pop(idx, None)
        if idx < 0 or idx >= len(self._entries):
            return
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if len(labels) >= 2:
                entry = self._entries[idx]
                title_text = self._entry_title(idx, entry)
                subtitle_text = self._entry_subtitle(entry)
                labels[0].setText(_truncate(self._entry_button_title(idx, entry), 24))
                labels[0].setToolTip(self._entry_tooltip(idx, entry))
                labels[1].setText(_truncate(self._entry_button_subtitle(entry), 30))
                labels[1].setToolTip(self._entry_tooltip(idx, entry))
            break
        if idx == self._current_idx and hasattr(self, '_header_title_label'):
            if self._header_title_label is not None:
                self._header_title_label.setText(self._entry_title(idx, self._entries[idx]))
            if self._header_subtitle_label is not None:
                self._header_subtitle_label.setText(self._entry_subtitle(self._entries[idx]))
        self._filter_list()

    def _update_actions(self):
        loaded = self._raw_data is not None
        has_selection = self._current_idx is not None and 0 <= self._current_idx < len(self._entries)
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and has_selection)
        self._btn_del.setEnabled(loaded and has_selection)
        self._btn_save.setEnabled(loaded and self._dirty)

    def _entry_tooltip(self, idx, entry):
        original = self._texts.text(entry.get('name_key', ''), japanese=True)[0]
        return '\n'.join(filter(None, (self._entry_title(idx, entry), self._entry_subtitle(entry),
                                      original, f"#{idx + 1} · {entry.get('char_id', '')}")))

    def _build_preview_card(self, entry):
        self._add_section(ui_text('ui_commandlistparam_preview_title'))
        card = self._make_card()
        grid = self._card_grid(card)
        self._preview_labels = {}
        self._preview_sources = {}
        for row, (key, caption) in enumerate((('name_key', 'movelist_name_preview'),
                                              ('detail_key', 'movelist_input_preview'),
                                              ('input_key', 'movelist_description_preview'))):
            shell, layout = self._field_shell(ui_text(caption))
            shell.setMinimumWidth(0)
            shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            label.setFont(ui_font(TypeSize.TITLE, QFont.Weight.Bold if key == 'name_key' else QFont.Weight.Normal))
            label.setStyleSheet(ss_main_label())
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
            grid.addWidget(shell, row, 0)
            self._preview_labels[key] = label
        self._translation_status = QLabel()
        self._translation_status.setWordWrap(True)
        self._translation_status.setMinimumWidth(0)
        self._translation_status.setTextFormat(Qt.TextFormat.PlainText)
        self._translation_status.setFont(ui_font(TypeSize.HINT))
        self._translation_status.setStyleSheet(ss_dim_label())
        grid.addWidget(self._translation_status, 3, 0)
        self._editor_layout.addWidget(card)
        self._refresh_preview()

    def _refresh_preview(self):
        entry = self._entries[self._current_idx]
        for key, label in self._preview_labels.items():
            text, source = self._texts.text(entry.get(key, ''), name=key == 'name_key')
            label.setText(text or ui_text('movelist_text_missing'))
            label.setToolTip(self._texts.text(entry.get(key, ''), japanese=True)[0])
            self._preview_sources[key] = source
        source = self._preview_sources.get('name_key')
        if not self._texts.tables:
            status = ui_text('movelist_no_data')
        elif source == 'ru':
            status = ui_text('movelist_translation_local')
        elif source == 'eng' and current_language() == 'en':
            status = ui_text('movelist_translation_game')
        elif source == 'rus':
            status = ui_text('movelist_translation_native', language=source)
        else:
            status = ui_text('movelist_translation_fallback', language=source or '—')
        japanese = self._texts.text(entry.get('name_key', ''), japanese=True)[0]
        if japanese:
            status += '\n' + ui_text('movelist_japanese', text=japanese)
        self._translation_status.setText(status)


    def _build_editor(self, idx: int):
        self._loading_detail = True
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._type_combo = None
        self._loading_detail = True
        entry = self._entries[idx]
        self._last_compact = self._grid_columns(3)

        header, header_layout = make_editor_grid_card(self._editor_widget, title=self._entry_title(idx, entry), icon_name='fa6s.list-check', subtitle=self._entry_subtitle(entry))
        self._prep_card(header)
        labels = header.findChildren(QLabel)
        self._header_title_label = next((label for label in labels if label.text() == self._entry_title(idx, entry)), None)
        self._header_subtitle_label = next((label for label in labels if label.text() == self._entry_subtitle(entry)), None)
        for label in header.findChildren(QLabel):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._active_grid_columns = 3

        self._add_text_field(
            header_layout,
            0,
            0,
            "char_id",
            ui_text("ui_commandlistparam_char_id"),
            entry.get("char_id", ""),
            big=True,
        )
        self._add_type_field(header_layout, 0, 1, int(entry.get("move_type", 0)))
        self._add_int_field(
            header_layout,
            0,
            2,
            "command_list_num",
            ui_text("ui_commandlistparam_command_list_num"),
            entry.get("command_list_num", 0),
            _INT32_MIN,
            _INT32_MAX,
            big=True,
        )
        self._add_hint(header_layout, 1, 2, ui_text("ui_commandlistparam_command_list_num_hint"))
        for col in range(self._grid_columns(3)):
            header_layout.setColumnStretch(col, 1)
        self._editor_layout.addWidget(header)
        self._build_preview_card(entry)

        self._add_section(ui_text("ui_commandlistparam_text_keys"))
        text_card = self._make_card()
        text_grid = self._card_grid(text_card)
        self._active_grid_columns = 3
        self._add_hint(text_grid, 0, 0, ui_text("ui_commandlistparam_text_keys_hint"), colspan=3)
        self._add_text_field(
            text_grid,
            1,
            0,
            "name_key",
            ui_text("ui_commandlistparam_name_key"),
            entry.get("name_key", ""),
        )
        self._add_text_field(
            text_grid,
            1,
            1,
            "detail_key",
            ui_text("ui_commandlistparam_detail_key"),
            entry.get("detail_key", ""),
        )
        self._add_text_field(
            text_grid,
            1,
            2,
            "input_key",
            ui_text("ui_commandlistparam_input_key"),
            entry.get("input_key", ""),
        )
        for col in range(self._grid_columns(3)):
            text_grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(text_card)

        self._add_section(ui_text("ui_commandlistparam_raw_values"))
        raw_card = self._make_card()
        raw_grid = self._card_grid(raw_card)
        self._active_grid_columns = 3
        row = col = 0
        for key, label_key, min_value, max_value in _NUMERIC_FIELDS:
            if key == "command_list_num":
                continue
            add_field = self._add_choice_field if key != 'unk12' else self._add_int_field
            add_field(
                raw_grid,
                row,
                col,
                key,
                ui_text(label_key),
                entry.get(key, 0),
                min_value,
                max_value,
            )
            hint = 'movelist_flag_hint' if key == 'unk10' else 'movelist_link_hint' if key == 'unk12' else 'movelist_tag_hint'
            self._fields[key].setToolTip(ui_text(hint))
            col += 1
            if col >= 3:
                row += 1
                col = 0
        for grid_col in range(self._grid_columns(3)):
            raw_grid.setColumnStretch(grid_col, 1)
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
        card, grid = make_editor_grid_card(self._editor_widget, title=section_title, icon_name='fa6s.sliders')
        self._prep_card(card)
        card._editor_grid = grid
        return card

    def _card_grid(self, card: QFrame) -> QGridLayout:
        return card._editor_grid

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

    def _field_span(self, col: int, requested: int, max_columns: int) -> int:
        columns = self._grid_columns(max_columns)
        return max(1, min(requested, columns - (col % columns)))

    def _prep_card(self, card: QFrame):
        configure_card(card)
        return card

    def _prep_field_widget(self, frame: QWidget, editor: QWidget):
        configure_field(frame, editor)

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
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def _add_hint(self, grid, row, col, text, colspan=1):
        hint = QLabel(text)
        hint.setMinimumWidth(0)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        hint.setWordWrap(True)
        hint.setFont(ui_font(TypeSize.HINT))
        hint.setStyleSheet(ss_dim_label())
        max_cols = getattr(self, "_active_grid_columns", 3)
        mapped_row, mapped_col = self._field_position(row, col, max_cols)
        grid.addWidget(hint, mapped_row, mapped_col, 1, self._field_span(mapped_col, colspan, max_cols))

    def _add_type_field(self, grid, row, col, value: int):
        frame, layout = self._field_shell(ui_text("ui_commandlistparam_move_type"))
        combo = QComboBox()
        configure_input(combo, height=Size.LARGE_CONTROL, monospace=True)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        type_values = list(_TYPE_LABEL_KEYS)
        if value not in type_values:
            type_values.append(value)
        for type_value in type_values:
            combo.addItem(ui_text("ui_commandlistparam_type_option", value=type_value, label=self._type_label(type_value)), type_value)
        selected = combo.findData(value)
        combo.setCurrentIndex(max(0, selected))
        combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._type_combo = combo

    def _add_int_field(self, grid, row, col, key, label, value, min_value, max_value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._int_validator if min_value < 0 else self._uint_validator)
        edit.setMaxLength(11 if min_value < 0 else 10)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx is None or self._loading_detail:
            return
        compact = self._grid_columns(3)
        if compact == self._last_compact:
            return
        if self._apply_current_entry(show_errors=False):
            self._build_editor(self._current_idx)

    def _on_text_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._fields[key].text()
        self._entries[self._current_idx][key] = value
        if key == 'char_id' and self._char_filter.findData(value) < 0:
            self._char_filter.addItem(f'{self._character_name(value)} ({value})', value)
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)
        if key in ('name_key', 'detail_key', 'input_key'):
            self._refresh_preview()

    def _on_type_changed(self):
        if self._loading_detail or self._current_idx is None or self._type_combo is None:
            return
        self._entries[self._current_idx]["move_type"] = int(self._type_combo.currentData())
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)

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
        self._entries[self._current_idx][key] = value
        self._refresh_entry_button(self._current_idx)


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
                    ui_text("ui_commandlistparam_ascii_only", field=ui_text(f"ui_commandlistparam_{key}")),
                )
            return None
        return text

    def _read_int(self, key: str, min_value: int, max_value: int, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        text = widget.text().strip()
        try:
            value = int(text.split(' — ', 1)[0])
        except ValueError:
            value = min_value - 1
        if value < min_value or value > max_value:
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("ui_commandlistparam_invalid_integer", value=text, min=min_value, max=max_value),
                )
            return None
        return value

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._current_idx is None:
            return True
        entry = self._entries[self._current_idx]
        changes = {}
        for key in ('char_id', 'name_key', 'detail_key', 'input_key'):
            value = self._read_ascii(key, show_errors)
            if value is None or '\0' in value:
                if value is not None and show_errors:
                    QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('movelist_invalid_text'))
                return False
            changes[key] = value
        if self._type_combo is not None:
            changes['move_type'] = int(self._type_combo.currentData())
        for key, _, lo, hi in _NUMERIC_FIELDS:
            value = self._read_int(key, lo, hi, show_errors)
            if value is None:
                return False
            changes[key] = value
        entry.update(changes)
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
        new_entry = make_default_entry()
        new_entry['char_id'] = self._char_filter.currentData() or (self._entries[self._current_idx]['char_id'] if self._current_idx is not None else 'newchr')
        new_entry['command_list_num'] = self._free_command_id(new_entry['char_id'])
        self._entries.append(new_entry)
        self._clear_filters()
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._select_entry(len(self._entries) - 1)

    def _do_dup(self):
        if self._raw_data is None or self._current_idx is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        new_entry = make_default_entry(copy.deepcopy(self._entries[self._current_idx]))
        new_entry['command_list_num'] = self._free_command_id(new_entry['char_id'])
        new_entry['unk12'] = -1
        self._entries.insert(self._current_idx + 1, new_entry)
        self._clear_filters()
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

        if not self._apply_current_entry(show_errors=True):
            return
        old_idx = self._current_idx
        self._entries.pop(old_idx)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        if self._entries:
            self._select_entry(min(old_idx, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text("ui_commandlistparam_no_entries"))
            self._update_actions()

    def _character_name(self, code):
        if code not in self._character_labels:
            key = 'char_' + code
            value = ui_text(key)
            self._character_labels[code] = value if value != key else code
        return self._character_labels[code]

    def _confirm_discard(self):
        return QMessageBox.question(self, ui_text('dlg_title_warning'), ui_text('movelist_discard'),
                                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _free_command_id(self, char_id):
        used = {int(e.get(k, -1)) for e in self._entries if e.get('char_id') == char_id for k in ('command_list_num', 'unk12')}
        value = 0
        while value in used:
            value += 1
        return value

    def _clear_filters(self):
        self._search.clear()
        self._char_filter.setCurrentIndex(0)
        self._type_filter.setCurrentIndex(0)

    def _choose_text_folder(self):
        folder = QFileDialog.getExistingDirectory(self, ui_text('movelist_text_folder_title'), game_files_dialog_dir())
        if not folder:
            return
        if self._current_idx is not None and not self._apply_current_entry(show_errors=True):
            return
        self._texts = MoveListText('', current_language(), folder)
        self._text_root = folder
        self._populate_list()
        if self._current_idx is not None:
            self._select_entry(self._current_idx)

    def _add_choice_field(self, grid, row, col, key, label, value, min_value, max_value):
        frame, layout = self._field_shell(label)
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        configure_input(combo, height=Size.CONTROL, monospace=False)
        combo.setMinimumWidth(0)
        if key == 'unk10':
            choices = {0: ui_text('movelist_mark_no'), 1: ui_text('movelist_mark_yes')}
        else:
            choices = {0: ui_text('movelist_tag_none')}
            choices.update({i: ui_text('movelist_tag_value', value=i) for i in range(1, 21)})
            for i, name in ((5, 'combo'), (6, 'air'), (7, 'charge'), (8, 'down'), (9, 'rush')):
                choices[i] = ui_text('movelist_tag_' + name)
        if value not in choices:
            choices[value] = ui_text('movelist_custom_value', value=value)
        for number, caption in choices.items():
            combo.addItem(f'{number} — {caption}', number)
        combo.setCurrentIndex(combo.findData(value))
        edit = combo.lineEdit()
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda: self._on_numeric_finished(key, min_value, max_value))
        combo.activated.connect(lambda: self._on_numeric_finished(key, min_value, max_value))
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        mapped_row, mapped_col = self._field_position(row, col, self._active_grid_columns)
        grid.addWidget(frame, mapped_row, mapped_col)
        self._fields[key] = edit
