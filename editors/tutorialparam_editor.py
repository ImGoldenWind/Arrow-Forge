from core.design_tokens import LayoutRole, Size
from core.style_helpers import (
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_bg_dark,
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

from PyQt6.QtCore import QEvent, QRegularExpression, Qt, QTimer
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
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

from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.translations import ui_text
from core.ui.message_preview import message_lookup
from parsers.tutorialparam_parser import (
    FLOAT_FIELDS,
    STRING_FIELDS,
    UINT_FIELDS,
    make_default_entry,
    parse_tutorialparam_xfbin,
    save_tutorialparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF
_FLOAT_MIN = -3.4028234663852886e38
_FLOAT_MAX = 3.4028234663852886e38
_STRING_KEYS = tuple(key for key, _offset in STRING_FIELDS)
_UINT_KEYS = tuple(key for key, _offset in UINT_FIELDS)
_FLOAT_KEYS = tuple(key for key, _offset in FLOAT_FIELDS)


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


class TutorialParamEditor(QWidget):
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
        self._form_fields = []
        self._dirty = False
        self._loading_detail = False
        self._active_grid_columns = 3

        self._uint_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._float_validator = QRegularExpressionValidator(
            QRegularExpression(r"[-+]?(?:\d+\.?\d*|\.\d+)?(?:[eE][-+]?\d+)?"),
            self,
        )
        self._ascii_validator = QRegularExpressionValidator(QRegularExpression(r"[\x20-\x7E]{0,192}"), self)
        self._path_validator = QRegularExpressionValidator(QRegularExpression(r"[\x20-\x7E]{0,260}"), self)
        self._hex_validator = QRegularExpressionValidator(QRegularExpression(r"(?:[0-9A-Fa-f]{2}\s*)*"), self)

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

        sidebar = EditorSidebar(width=300)


        sidebar_layout = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)

        self._type_filter = EditorFilterCombo()
        self._type_filter.addItem(ui_text('ui_tutorialparam_entry_type'), None)
        self._type_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._type_filter)
        self._page_filter = EditorFilterCombo()
        self._page_filter.addItem(ui_text('tutorial_page'), None)
        self._page_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._page_filter)

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
        self._editor_scroll.viewport().installEventFilter(self)
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_tutorialparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)
        self._update_actions()

    def _make_action_button(self, key: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(self._tr(key, ui_text(key)))
        btn.setEnabled(False)
        configure_button(btn, danger=danger, height=Size.COMPACT_CONTROL)
        btn.clicked.connect(slot)
        return btn

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._form_fields = []
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
            ui_text("ui_tutorialparam_open_title"),
            game_files_dialog_dir(target_patterns=("TutorialParam.bin.xfbin", "TutorialParam.xfbin")),
            ui_text("ui_tutorialparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        try:
            raw, result = parse_tutorialparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        if self._dirty:
            reply = QMessageBox.question(
                self, ui_text('unsaved_changes_title'), ui_text('unsaved_changes_message'),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Discard:
                return
        create_backup_on_open(path)

        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._entries = result["entries"]
        self._current_idx = None
        self._dirty = False
        self._btn_save.setEnabled(False)
        self._search.setText("")
        self._type_filter.setCurrentIndex(0)
        self._page_filter.setCurrentIndex(0)
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_tutorialparam_no_entries"))
        self._update_actions()

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_tutorialparam_xfbin(save_path, self._raw_data, self._result)
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
        self._sync_filters()
        for idx, entry in enumerate(self._entries):
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = self._entry_title(idx, entry)
        button_title = self._entry_button_title(idx, entry)
        subtitle_text = self._entry_subtitle(entry)
        button_subtitle = self._entry_button_subtitle(entry)
        title = btn.add_title(_truncate(button_title, 28))


        title.setToolTip(title_text)


        subtitle = btn.add_subtitle(_truncate(button_subtitle, 34))


        subtitle.setToolTip(subtitle_text)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        key = entry.get('text_key', '')
        text = message_lookup(self).text(key)[0] if entry.get('entry_type') == 1 else ''
        return text or key or entry.get('category') or ui_text('tutorial_empty_node')

    def _entry_button_title(self, idx: int, entry: dict) -> str:
        return self._entry_title(idx, entry).replace('\n', ' ')

    def _entry_subtitle(self, entry: dict) -> str:
        idx = next((i for i, item in enumerate(self._entries) if item is entry), 0)
        page = self._page_contexts()[idx][1] if self._entries else ''
        return ui_text('tutorial_row_context', page=page or ui_text('ui_tutorialparam_no_category'),
                       kind=self._type_label(int(entry.get('entry_type', 0))))

    def _entry_button_subtitle(self, entry: dict) -> str:
        return self._entry_subtitle(entry)

    def _type_label(self, value):
        return ui_text(f'tutorial_type_{value}') if value in (0, 1, 2) else ui_text('tutorial_custom_value', value=value)

    def _page_contexts(self):
        page = (None, '')
        result = []
        for idx, entry in enumerate(self._entries):
            if entry.get('entry_type') == 0:
                page = (idx, entry.get('category') or entry.get('text_key') or ui_text('tutorial_empty_node'))
            result.append(page)
        return result

    def _sync_filters(self):
        pages = [(i, name) for i, name in self._page_contexts() if i is not None]
        choices = (
            (self._type_filter, [(value, self._type_label(value)) for value in sorted({int(e.get('entry_type', 0)) for e in self._entries})]),
            (self._page_filter, list(dict.fromkeys(pages))),
        )
        for combo, items in choices:
            selected = combo.currentData()
            combo.blockSignals(True)
            while combo.count() > 1:
                combo.removeItem(combo.count() - 1)
            for value, label in items:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)

    def _filter_list(self):
        query = self._search.text().lower().strip()
        contexts = self._page_contexts()
        selected_type = self._type_filter.currentData()
        selected_page = self._page_filter.currentData()
        lookup = message_lookup(self) if query else None
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            matches = True
            if query:
                text = lookup.text(entry.get('text_key', ''))[0] if entry.get('entry_type') == 1 else ''
                haystack = ' '.join(str(entry.get(key, '')) for key in (
                    'category', 'asset_path', 'entry_type', 'text_key', 'dummy_key',
                    'raw_28', 'raw_2c', 'raw_44',
                )).lower() + ' ' + text.lower() + ' ' + contexts[idx][1].lower() + ' ' + self._type_label(entry.get('entry_type', 0)).lower()
                matches = query in haystack or query == str(idx)
            btn.setVisible((selected_type is None or entry.get('entry_type') == selected_type)
                           and (selected_page is None or contexts[idx][0] == selected_page)
                           and matches)

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
            if len(labels) >= 1:
                title_text = self._entry_title(idx, self._entries[idx])
                button_title = self._entry_button_title(idx, self._entries[idx])
                labels[0].setText(_truncate(button_title, 28))
                labels[0].setToolTip(title_text)
            if len(labels) >= 2:
                subtitle_text = self._entry_subtitle(self._entries[idx])
                button_subtitle = self._entry_button_subtitle(self._entries[idx])
                labels[1].setText(_truncate(button_subtitle, 34))
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
        self._form_fields = []
        self._loading_detail = True
        entry = self._entries[idx]

        header, grid = make_editor_grid_card(
            self._editor_widget, title=_truncate(self._entry_button_title(idx, entry), 80),
            icon_name='fa6s.graduation-cap', subtitle=self._entry_subtitle(entry))
        self._prep_card(header)
        self._active_grid_columns = 2
        self._add_choice_field(grid, 0, 0, 'entry_type', entry,
                               ui_text('ui_tutorialparam_entry_type'),
                               [(value, self._type_label(value)) for value in (0, 1, 2)],
                               ui_text('ui_tutorialparam_entry_type_hint'))
        self._add_text_field(grid, 0, 1, 'category', entry,
                             ui_text('ui_tutorialparam_category'), ui_text('ui_tutorialparam_category_hint'))
        self._editor_layout.addWidget(header)

        self._add_section(ui_text('tutorial_content'))
        content = self._make_card()
        grid = self._card_grid(content)
        self._active_grid_columns = 1
        self._add_text_field(grid, 0, 0, 'text_key', entry, ui_text('ui_tutorialparam_text_key'))
        self._add_text_field(grid, 1, 0, 'asset_path', entry, ui_text('ui_tutorialparam_asset_path'),
                             ui_text('ui_tutorialparam_asset_path_hint'), path_mode=True)
        self._add_text_field(grid, 2, 0, 'dummy_key', entry, ui_text('ui_tutorialparam_dummy_key'),
                             ui_text('ui_tutorialparam_dummy_key_hint'))
        self._editor_layout.addWidget(content)

        self._add_section(ui_text('tutorial_placement'))
        placement = self._make_card()
        self._active_grid_columns = 1
        anchors = [(value, ui_text(f'tutorial_anchor_{value}')) for value in range(9)]
        self._add_choice_field(self._card_grid(placement), 0, 0, 'raw_28', entry,
                               ui_text('ui_tutorialparam_raw_28'), anchors,
                               ui_text('ui_tutorialparam_raw_28_hint'))
        self._editor_layout.addWidget(placement)

        self._add_section(ui_text('tutorial_text_format'))
        self._text_card = self._make_card()
        grid = self._card_grid(self._text_card)
        self._active_grid_columns = 2
        self._add_choice_field(grid, 0, 0, 'raw_2c', entry, ui_text('ui_tutorialparam_raw_2c'),
                               [(value, ui_text(f'tutorial_colour_{value}')) for value in range(6)],
                               ui_text('ui_tutorialparam_raw_2c_hint'))
        self._add_choice_field(grid, 0, 1, 'raw_50', entry, ui_text('ui_tutorialparam_raw_50'),
                               [(value, ui_text(f'tutorial_alignment_{value}')) for value in range(3)],
                               ui_text('ui_tutorialparam_raw_50_hint'))
        for row, col, key, hint in (
            (1, 0, 'value_38', 'ui_tutorialparam_width_hint'),
            (1, 1, 'value_3c', 'ui_tutorialparam_position_hint'),
            (2, 0, 'value_40', 'ui_tutorialparam_position_hint'),
            (2, 1, 'value_34', 'ui_tutorialparam_font_hint'),
            (3, 0, 'value_4c', 'ui_tutorialparam_font_hint'),
        ):
            self._add_float_field(grid, row, col, key, entry, ui_text('ui_tutorialparam_' + key), ui_text(hint))
        for row, col, key in ((3, 1, 'raw_30'), (4, 0, 'raw_48')):
            # Native setters use bit zero only. Choices preserve all other bits.
            high_bits = int(entry.get(key, 0)) & ~1
            self._add_choice_field(grid, row, col, key, entry, ui_text('ui_tutorialparam_' + key),
                                   [(high_bits | bit, ui_text(f'tutorial_outline_{bit}')) for bit in (0, 1)],
                                   ui_text('ui_tutorialparam_' + key + '_hint'))
        self._editor_layout.addWidget(self._text_card)

        self._editor_layout.addStretch()
        self._loading_detail = False
        self._update_type_fields()
        self._reflow_fields()

    def _update_type_fields(self):
        from core.parameter_research import set_field_caption
        value = self._read_uint('entry_type')
        is_text = value == 1
        field = self._fields['text_key']
        caption = ui_text('ui_messageinfo_string_id' if is_text else 'ui_tutorialparam_text_key')
        set_field_caption(self._fields, 'text_key', caption)
        field.setAccessibleName(caption)
        field.setProperty('messageReference', is_text)
        field.setProperty('messageTextOnly', is_text)
        field.setToolTip('' if is_text else ui_text('ui_tutorialparam_text_key_hint'))
        self._text_card.setVisible(value not in (0, 2))
        anchor = self._fields['raw_28']
        # A type-2 property is not a text anchor. Keep its raw numeric value.
        current = self._read_uint('raw_28')
        if current is not None:
            anchor.blockSignals(True)
            anchor.clear()
            if is_text:
                for number in range(9):
                    anchor.addItem(ui_text(f'tutorial_anchor_{number}'), number)
            if anchor.findData(current) < 0:
                anchor.addItem(str(current), current)
            anchor.setCurrentIndex(anchor.findData(current))
            anchor.blockSignals(False)
        caption = ui_text('tutorial_text_anchor' if is_text else 'tutorial_asset_property')
        set_field_caption(self._fields, 'raw_28', caption)
        anchor.setAccessibleName(caption)

    def _add_choice_field(self, grid, row, col, key, entry, label, choices, hint=''):
        frame, layout = self._field_shell(label)
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        configure_input(combo, monospace=False)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for value, text in choices:
            combo.addItem(text, value)
        current = int(entry.get(key, 0))
        if combo.findData(current) < 0:
            combo.addItem(ui_text('tutorial_custom_value', value=current), current)
        combo.setCurrentIndex(combo.findData(current))
        combo.setToolTip(hint)
        combo.setAccessibleName(label)
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        self._fields[key] = combo
        self._place_field(grid, frame, row, col)
        combo.editTextChanged.connect(self._on_numeric_text_changed)
        combo.currentIndexChanged.connect(lambda _index, k=key: self._on_uint_finished(k))
        combo.lineEdit().editingFinished.connect(lambda k=key: self._on_uint_finished(k))

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

    def _add_text_field(self, grid, row, col, key, entry, label, hint="", colspan=1, path_mode=False, big=False):
        self._add_text_value_field(grid, row, col, key, label, str(entry.get(key, "")), hint, colspan=colspan, path_mode=path_mode, big=big)

    def _add_text_value_field(self, grid, row, col, key, label, value, hint="", colspan=1, hex_mode=False, path_mode=False, big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        if hex_mode:
            edit.setValidator(self._hex_validator)
        else:
            edit.setValidator(self._path_validator if path_mode else self._ascii_validator)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(value))
        edit.setCursorPosition(0)
        edit.setToolTip(hint)
        edit.setAccessibleName(label)
        edit.textChanged.connect(lambda _text, k=key: self._on_text_changed(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame, row, col)
        self._fields[key] = edit

    def _add_uint_field(self, grid, row, col, key, entry, label, hint="", big=False):
        self._add_uint_value_field(grid, row, col, key, label, int(entry.get(key, 0)), hint, big=big)

    def _add_uint_value_field(self, grid, row, col, key, label, value, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setValidator(self._uint_validator)
        edit.setMaxLength(10)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setCursorPosition(0)
        edit.setToolTip(hint)
        edit.setAccessibleName(label)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key: self._on_uint_finished(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame, row, col)
        self._fields[key] = edit

    def _add_float_field(self, grid, row, col, key, entry, label, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setValidator(self._float_validator)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(f"{float(entry.get(key, 0.0)):.9g}")
        edit.setCursorPosition(0)
        edit.setToolTip(hint)
        edit.setAccessibleName(label)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key: self._on_float_finished(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame, row, col)
        self._fields[key] = edit

    def _place_field(self, grid, frame, row, col):
        maximum = self._active_grid_columns
        self._form_fields.append((grid, frame, row * maximum + col, maximum))
        grid.addWidget(frame, *self._field_position(row, col, maximum), Qt.AlignmentFlag.AlignTop)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._reflow_fields)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow_fields)
        return super().eventFilter(watched, event)

    def _maybe_rebuild_for_compact(self):
        self._reflow_fields()

    def _reflow_fields(self):
        if self._loading_detail or not self._form_fields:
            return
        for grid, frame, index, maximum in self._form_fields:
            columns = self._grid_columns(maximum)
            for col in range(maximum):
                stretch = int(col < columns)
                if grid.columnStretch(col) != stretch:
                    grid.setColumnStretch(col, stretch)
            row, col = divmod(index, columns)
            if grid.getItemPosition(grid.indexOf(frame)) != (row, col, 1, 1):
                grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)

    def _on_text_changed(self, key: str):
        if self._loading_detail:
            return
        if key == "notes_hex":
            self._mark_dirty()
            return
        if self._current_idx is None:
            return
        value = self._read_ascii(key)
        if value is None:
            self._mark_dirty()
            return
        self._entries[self._current_idx][key] = value
        if key == 'category':
            self._sync_filters()
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)

    def _on_numeric_text_changed(self):
        if not self._loading_detail:
            self._mark_dirty()

    def _on_uint_finished(self, key: str):
        if self._loading_detail:
            return
        value = self._read_uint(key, show_errors=True)
        if value is None:
            return
        if key == "version":
            if self._result is not None:
                self._result["version"] = value
            return
        if self._current_idx is not None:
            self._entries[self._current_idx][key] = value
            if key == 'entry_type':
                self._sync_filters()
                self._update_type_fields()
            elif key in ('raw_30', 'raw_48'):
                combo = self._fields[key]
                high_bits = value & ~1
                combo.blockSignals(True)
                combo.clear()
                for bit in (0, 1):
                    combo.addItem(ui_text(f'tutorial_outline_{bit}'), high_bits | bit)
                combo.setCurrentIndex(combo.findData(value))
                combo.blockSignals(False)
            self._refresh_entry_button(self._current_idx)

    def _on_float_finished(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._read_float(key, show_errors=True)
        if value is not None:
            self._entries[self._current_idx][key] = value

    def _label_for_key(self, key: str) -> str:
        return ui_text(f"ui_tutorialparam_{key}")

    def _read_ascii(self, key: str, show_errors: bool = False) -> str | None:
        widget = self._fields.get(key)
        if widget is None:
            return ""
        text = widget.text()
        try:
            text.encode("ascii")
            if "\0" in text:
                raise ValueError("embedded null")
        except (UnicodeEncodeError, ValueError):
            if show_errors:
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_tutorialparam_ascii_only", field=self._label_for_key(key)))
            return None
        return text

    def _read_uint(self, key: str, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        if isinstance(widget, QComboBox):
            if widget.currentText() == widget.itemText(widget.currentIndex()):
                return widget.currentData()
            text = widget.currentText().strip()
        else:
            text = widget.text().strip()
        try:
            value = int(text)
        except ValueError:
            value = _UINT32_MAX + 1
        if value < 0 or value > _UINT32_MAX:
            if show_errors:
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_tutorialparam_invalid_integer", value=text, min=0, max=_UINT32_MAX))
            return None
        return value

    def _read_float(self, key: str, show_errors: bool = False) -> float | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        text = widget.text().strip()
        try:
            value = float(text)
        except ValueError:
            value = math.inf
        if not math.isfinite(value) or value < _FLOAT_MIN or value > _FLOAT_MAX:
            if show_errors:
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_tutorialparam_invalid_float", value=text))
            return None
        return value

    def _notes_hex(self) -> str:
        if not self._result:
            return ""
        return " ".join(f"{byte:02X}" for byte in bytes(self._result.get("notes", b"")))

    def _read_hex(self, key: str, error_key: str, show_errors: bool = False) -> bytes | None:
        widget = self._fields.get(key)
        if widget is None:
            return b""
        text = widget.text().strip().replace(" ", "")
        if not text:
            return b""
        try:
            return bytes.fromhex(text)
        except ValueError:
            if show_errors:
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text(error_key))
            return None

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._result is not None and "version" in self._fields:
            version = self._read_uint("version", show_errors=show_errors)
            if version is None:
                return False
            self._result["version"] = version
        if self._result is not None and "notes_hex" in self._fields:
            notes = self._read_hex("notes_hex", "ui_tutorialparam_invalid_hex", show_errors=show_errors)
            if notes is None:
                return False
            self._result["notes"] = notes

        if self._current_idx is None:
            return True
        entry = self._entries[self._current_idx]
        pending = {}
        for key in _STRING_KEYS:
            if key not in self._fields:
                continue
            value = self._read_ascii(key, show_errors=show_errors)
            if value is None:
                return False
            pending[key] = value
        for key in _UINT_KEYS:
            if key not in self._fields:
                continue
            value = self._read_uint(key, show_errors=show_errors)
            if value is None:
                return False
            pending[key] = value
        for key in _FLOAT_KEYS:
            if key not in self._fields:
                continue
            value = self._read_float(key, show_errors=show_errors)
            if value is None:
                return False
            pending[key] = value
        type_changed = entry.get('entry_type') != pending.get('entry_type')
        entry.update(pending)
        if type_changed:
            self._sync_filters()
            self._update_type_fields()
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
            self._show_placeholder(ui_text("ui_tutorialparam_no_entries"))
            self._update_actions()
