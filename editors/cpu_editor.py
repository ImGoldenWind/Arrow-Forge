"""Editor for ASBR CPU AI XML XFBIN files."""
from __future__ import annotations


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
    ss_error_label,
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
from core.ui.editor_actions import install_file_actions
import os
import copy
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
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

from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.translations import ui_text, current_language, TRANSLATIONS
from core.cpu_tools import (TOKEN_FIELDS, load_symbols, field_groups, free_identity,
                            numeric_field, valid_integer, CpuNames)
from parsers.cpu_parser import (
    ARCADE_CPU_LEVEL_COUNT,
    add_element_like,
    clone_element,
    editable_elements,
    find_parent,
    make_default_arcade_cpu_entry,
    parse_arcade_cpu_xfbin,
    parse_cpu_xfbin,
    remove_element,
    save_arcade_cpu_xfbin,
    save_cpu_xfbin,
    validate_cpu_tree,
)


_DEFAULT_DATA_ATTRS = {
    "OpStatus": "Neutral", "Position": "Near", "rid": "1",
    "Cond1": "0", "Cond2": "0", "Cond3": "0", "Rate": "1", "Combo": "0",
    "Act1": "0", "Delay2": "0", "Act2": "0", "Delay3": "0", "Act3": "0",
    "Delay4": "0", "Act4": "0", "Delay5": "0", "Act5": "0",
    "StiffCond": "0", "StiffMin": "0", "StiffMax": "0",
    "NextCond": "0", "NextRate": "100", "Next": "1",
}

_DEFAULT_COND_ATTRS = {
    "tid": "1", "name": "", "uid": "NEW_COND",
    "general1": "0", "general2": "0", "general3": "0",
    "genStr1": "0", "genStr2": "0", "genStr3": "0",
}

_DEFAULT_ACTION_ATTRS = {
    "tid": "1", "name": "", "uid": "NewAction", "id": "0",
    "keepTime": "0", "quitTime": "0", "strength": "0", "level": "0",
    "crouch": "0", "direction": "NONE", "stand": "0",
    "general1": "0", "general2": "0", "general3": "0",
    "genStr1": "0", "genStr2": "0",
}


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 3)] + "..."


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


class CpuEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._ui_texts = TRANSLATIONS.get(current_language(), TRANSLATIONS.get('en', {}))
        self._embedded = embedded
        self._filepath = None
        self._mode = None
        self._raw = None
        self._chunk = None
        self._tree = None
        self._arcade = None
        self._items = []
        self._buttons = []
        self._current_element = None
        self._current_arcade_index = None
        self._fields = {}
        self._catalog = {}
        self._dirty = False
        self._block_changes = False
        self._last_detail_columns = None
        self._symbols = {}
        self._token_captions = {}
        self._missing_sources = []
        self._original_tree = None
        self._group_labels = []
        self._detail_grids = []
        self._names = None

        self._build_ui()
        install_file_actions(self, self._save_btn, existing_button=self._save_as_btn)
        install_editor_chrome(self)

    def _tr(self, key, fallback=None, **kwargs):
        text = self._t(key, **kwargs) if kwargs else self._t(key)
        if text == key:
            text = self._ui_texts.get(key, TRANSLATIONS.get('en', {}).get(key, key))
            if kwargs:
                text = text.format(**kwargs)
        return fallback if fallback is not None and text == key else text

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        top = EditorToolbar()
        top_layout = top.content_layout

        self._open_btn = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        configure_button(self._open_btn, accent=True)
        self._open_btn.clicked.connect(self._on_open)
        self._open_btn.setProperty("designAction", 'open')
        top_layout.addWidget(self._open_btn)

        self._save_btn = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        configure_button(self._save_btn, accent=True)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        top_layout.addWidget(self._save_btn)

        self._save_as_btn = QPushButton(self._tr('cpu_save_as'))
        configure_button(self._save_as_btn)
        self._save_as_btn.setEnabled(False)
        self._save_as_btn.clicked.connect(self._on_save_as)
        top_layout.addWidget(self._save_as_btn)

        self._file_lbl = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))

        configure_file_label(self._file_lbl)
        self._file_lbl.setMinimumWidth(0)
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top_layout.addWidget(self._file_lbl, 1)
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        sidebar = EditorSidebar(width=276)


        sidebar_layout = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)
        configure_search(self._search)
        self._search.setClearButtonEnabled(True)
        self._section_filter = self._filter_combo(sidebar_layout, 'cpu_all_sections')
        self._pattern_filter = self._filter_combo(sidebar_layout, 'cpu_all_patterns')
        filters = QHBoxLayout()
        self._status_filter = self._filter_combo(filters, 'cpu_all_statuses')
        self._position_filter = self._filter_combo(filters, 'cpu_all_distances')
        sidebar_layout.addLayout(filters)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._add_btn = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        configure_button(self._add_btn, height=Size.COMPACT_CONTROL)
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add)
        self._add_btn.setProperty("designAction", 'new')
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        configure_button(self._dup_btn, height=Size.COMPACT_CONTROL)
        self._dup_btn.setEnabled(False)
        self._dup_btn.clicked.connect(self._on_duplicate)
        self._dup_btn.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        configure_button(self._del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._on_delete)
        self._del_btn.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._del_btn, 1)
        sidebar_layout.addWidget(actions)

        self._list_scroll = QScrollArea()


        configure_scrollarea(self._list_scroll, transparent=True)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_widget.setMinimumWidth(0)
        self._list_widget.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_widget)
        configure_layout(self._list_layout, LayoutRole.LIST)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        sidebar_layout.addWidget(self._list_scroll, 1)
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
        self._show_placeholder(self._tr("ui_cpu_open_cpu_xfbin", ui_text("ui_cpu_open_cpu_xfbin")))
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)

    def _filter_combo(self, layout, title):
        combo = EditorFilterCombo()
        combo.addItem(self._tr(title), '')
        configure_input(combo)
        combo.setMinimumWidth(0)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.currentIndexChanged.connect(self._filter_list)
        layout.addWidget(combo)
        return combo

    def shortcut_action(self, action_id):
        if action_id in ("editor.next", "editor.previous"):
            self._step(1 if action_id == "editor.next" else -1)
            return True
        return False

    def _step(self, direction):
        visible = [(btn, item) for btn, item in self._buttons if not btn.isHidden()]
        if not visible:
            return
        current = next((i for i, (_, item) in enumerate(visible)
                        if (item.get('element') is self._current_element if self._mode != 'arcade'
                            else item.get('index') == self._current_arcade_index)), -1)
        btn, item = visible[max(0, min(len(visible) - 1, current + direction))]
        self._select_item(item)
        self._list_scroll.ensureWidgetVisible(btn)

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        self._fields.clear()
        self._detail_grids = []
        self._last_detail_columns = None
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.microchip",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("ui_cpu_open_title", ui_text("ui_cpu_open_title")),
            game_files_dialog_dir(
                fallback="asbr_cpu",
                target_patterns=("*_cpu_*.xfbin", "*cpu*.xfbin", "ArcadeCpuParam.bin.xfbin", "ArcadeCpuParam.xfbin"),
            ),
            self._tr("ui_cpu_file_filter", ui_text("ui_cpu_file_filter")),
        )
        if path:
            self._load_file(path)

    def _load_file(self, path):
        if not self._confirm_discard():
            return False
        try:
            raw, chunk, tree = parse_cpu_xfbin(path)
            mode = "xml"
            arcade = None
        except Exception as exc:
            try:
                raw, arcade = parse_arcade_cpu_xfbin(path)
                chunk = None
                tree = None
                mode = "arcade"
            except Exception:
                QMessageBox.critical(self, self._tr("dlg_title_error", ui_text("dlg_title_error")), self._tr("msg_load_error", ui_text("msg_load_error"), error=exc))
                return

        self._filepath = path
        self._mode = mode
        self._raw = raw
        self._chunk = chunk
        self._tree = tree
        self._original_tree = copy.deepcopy(tree)
        self._arcade = arcade
        self._names = CpuNames(path)
        self._reload_symbols()
        self._dirty = False
        self._current_element = None
        self._current_arcade_index = None
        self._reset_filters()

        set_file_label(self._file_lbl, path)
        self._save_btn.setEnabled(True)
        self._save_as_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._rebuild_items()
        if self._items:
            self._select_item(self._items[0])
        else:
            self._show_placeholder(self._tr("ui_cpu_no_editable_entries", ui_text("ui_cpu_no_editable_entries")))
        create_backup_on_open(path)
        return True

    def _reload_symbols(self):
        self._token_captions.clear()
        self._symbols, self._missing_sources = load_symbols(self._filepath, self._tree.getroot()) if self._tree is not None else ({}, [])
        self._catalog = {}
        if self._tree is not None:
            for elem in self._tree.getroot().iter():
                for key, value in elem.attrib.items():
                    self._catalog.setdefault(key, set()).add(value)

    def _on_save(self):
        if not self._filepath or self._raw is None:
            return False
        return self._save_to(self._filepath)

    def _on_save_as(self):
        if not self._filepath:
            return False
        path, _ = QFileDialog.getSaveFileName(self, self._tr('cpu_save_as'), self._filepath, 'XFBIN (*.xfbin)')
        return self._save_to(path) if path else False

    def _save_to(self, path):
        selected_idx = 0
        if self._mode == "arcade":
            selected_idx = self._current_arcade_index or 0
        else:
            for idx, item in enumerate(self._items):
                if item.get("element") is self._current_element:
                    selected_idx = idx
                    break
        try:
            if self._mode == "arcade":
                save_arcade_cpu_xfbin(path, self._raw, self._arcade)
                self._raw, self._arcade = parse_arcade_cpu_xfbin(path)
            else:
                save_cpu_xfbin(path, self._raw, self._chunk, self._tree)
                self._raw, self._chunk, self._tree = parse_cpu_xfbin(path)
                self._original_tree = copy.deepcopy(self._tree)
            self._filepath = path
            self._reload_symbols()
            self._dirty = False
            set_file_label(self._file_lbl, self._filepath)
            self._current_element = None
            self._current_arcade_index = None
            self._rebuild_items()
            if self._items:
                self._select_item(self._items[min(selected_idx, len(self._items) - 1)])
            QMessageBox.information(
                self,
                self._tr("dlg_title_success", ui_text("dlg_title_success")),
                self._tr("ui_cpu_saved_value", ui_text("ui_cpu_saved_value"), p0=os.path.basename(self._filepath)),
            )
            return True
        except Exception as exc:
            QMessageBox.critical(self, self._tr("dlg_title_error", ui_text("dlg_title_error")), self._tr("msg_save_error", ui_text("msg_save_error"), error=exc))
            return False

    def _confirm_discard(self):
        if not self._dirty:
            return True
        result = QMessageBox.question(self, self._tr('unsaved_changes_title'),
                                      self._tr('unsaved_changes_message'),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if result == QMessageBox.StandardButton.Save:
            return self._on_save()
        return result == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if not self._embedded and not self._confirm_discard():
            event.ignore()
            return
        super().closeEvent(event)

    def _rebuild_items(self):
        _clear_layout(self._list_layout)
        self._buttons = []
        self._group_labels = []
        if self._mode == "arcade" and self._arcade is not None:
            self._items = self._arcade_items()
        else:
            self._items = editable_elements(self._tree.getroot()) if self._tree is not None else []
        last_group = None
        for item in self._items:
            self._present_item(item)
            group = (item.get('pattern_name', ''), item['group'])
            if group != last_group:
                label = QLabel(' · '.join(v for v in (item.get('pattern_name', ''), self._group_title(item['group'])) if v))
                label.setFont(ui_font(TypeSize.HINT, QFont.Weight.Bold))
                label.setStyleSheet(ss_dim_label())
                self._list_layout.addWidget(label)
                self._group_labels.append((label, group))
                last_group = group
            btn = self._make_item_button(item)
            self._list_layout.addWidget(btn)
            self._buttons.append((btn, item))
        self._list_layout.addStretch()
        self._populate_filters()
        self._filter_list()

    def _populate_filters(self):
        choices = ((self._section_filter, sorted({i['group'] for i in self._items}), self._group_title),
                   (self._pattern_filter, sorted({i.get('pattern_name', '') for i in self._items} - {''}), lambda s: s),
                   (self._status_filter, sorted({i['element'].get('OpStatus', '') for i in self._items if i['tag'] == 'Data'} - {''}), self._value_caption),
                   (self._position_filter, sorted({i['element'].get('Position', '') for i in self._items if i['tag'] == 'Data'} - {''}), self._value_caption))
        for combo, values, caption in choices:
            selected = combo.currentData()
            combo.blockSignals(True)
            while combo.count() > 1:
                combo.removeItem(1)
            for value in values:
                combo.addItem(caption(value), value)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)
            combo.setVisible(bool(values) and (combo is not self._pattern_filter or len(values) > 1))

    def _present_item(self, item):
        elem = item.get('element')
        if elem is None:
            return
        if elem.tag == 'Data':
            item['label'] = f"#{elem.get('rid', '?')} · {self._value_caption(elem.get('OpStatus', ''))}"
            item['subtitle'] = self._value_caption(elem.get('Position', '')) + ' · ' + ' → '.join(
                self._token_caption('Action', elem.get(f'Act{i}', '0')) for i in range(1, 6) if elem.get(f'Act{i}', '0') != '0')
        elif elem.tag in ('Pattern', 'BaseParam'):
            item['label'] = elem.get('name') or self._tr('ui_cpu_tag_' + elem.tag, elem.tag)
        else:
            item['label'] = self._token_caption(elem.tag, elem.get('uid', ''))
            item['subtitle'] = elem.get('name', '')

    def _value_caption(self, value):
        return self._tr('cpu_value_' + str(value), str(value))

    def _token_caption(self, kind, token):
        identity = (kind, token)
        if identity not in self._token_captions:
            self._token_captions[identity] = self._resolve_token_caption(kind, token)
        return self._token_captions[identity]

    def _resolve_token_caption(self, kind, token):
        contextual = self._tr(f'cpu_token_{kind}_{token}', '')
        if contextual:
            return contextual
        value = self._value_caption(token)
        if value != token:
            return value
        info = self._symbols.get(kind, {}).get(token, {})
        name = info.get('name', '')
        translated = self._names.display(name) if self._names and name else name
        if kind == 'Action' and translated == name and self._names:
            command_name = self._names.commands.get(info.get('id'))
            if command_name:
                translated = command_name + ' · ' + self._tr('cpu_variant', value=info.get('strength', '0'))
        return translated if translated and translated != '-' else token

    def _arcade_items(self):
        entries = self._arcade.get("entries", []) if self._arcade else []
        items = []
        for idx, entry in enumerate(entries):
            levels = entry.get("levels", [])
            subtitle = " / ".join(str(value) for value in levels)
            items.append({
                "index": idx,
                "tag": "ArcadeCpuParam",
                "group": "arcade",
                "label": entry.get("name") or f"Entry {idx + 1}",
                "subtitle": subtitle,
            })
        return items

    def _make_item_button(self, item):
        selected = (
            item.get("element") is self._current_element
            if self._mode != "arcade"
            else item.get("index") == self._current_arcade_index
        )
        btn = EditorListRow(height=50)

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = item["label"]
        title = btn.add_title(_truncate(title_text, 24))


        title.setToolTip(title_text)


        subtitle_text = item.get("subtitle", "")
        subtitle = btn.add_subtitle(_truncate(subtitle_text, 30))


        subtitle.setToolTip(subtitle_text)


        btn.clicked.connect(lambda checked=False, selected_item=item: self._select_item(selected_item))
        return btn

    def _select_item(self, item):
        if self._mode == "arcade":
            self._select_arcade_entry(item["index"])
        else:
            self._select_element(item["element"])

    def _filter_list(self, *_):
        if not hasattr(self, '_buttons'):
            return
        words = self._search.text().casefold().split()
        section = self._section_filter.currentData()
        pattern = self._pattern_filter.currentData()
        status = self._status_filter.currentData()
        position = self._position_filter.currentData()
        groups = set()
        count = 0
        for btn, item in self._buttons:
            elem = item.get('element')
            attrs = elem.attrib if elem is not None else {}
            descriptions = [text for key, kind in TOKEN_FIELDS.items() if key in attrs
                            for text in (self._token_caption(kind, attrs[key]),
                                         self._symbols.get(kind, {}).get(attrs[key], {}).get('name', ''))]
            blob = ' '.join([item['label'], item.get('subtitle', ''), item['tag'],
                             self._group_title(item['group']), item.get('pattern_name', ''),
                             *attrs.keys(), *attrs.values(), *descriptions]).casefold()
            show = (all(word in blob for word in words) and (not section or item['group'] == section)
                    and (not pattern or item.get('pattern_name') == pattern)
                    and (not status or attrs.get('OpStatus') == status)
                    and (not position or attrs.get('Position') == position))
            btn.setVisible(show)
            if show:
                count += 1
                groups.add((item.get('pattern_name', ''), item['group']))
        for label, group in self._group_labels:
            label.setVisible(group in groups)

    def _select_element(self, element):
        self._current_element = element
        self._current_arcade_index = None
        for btn, item in self._buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(item["element"] is element)))
        self._build_detail(element)
        self._update_action_buttons()
        self._editor_scroll.verticalScrollBar().setValue(0)

    def _select_arcade_entry(self, index):
        self._current_arcade_index = index
        self._current_element = None
        for btn, item in self._buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(item.get("index") == index)))
        self._build_arcade_detail(index)
        self._update_action_buttons()

    def _grid_columns(self, max_columns=3):
        width = self._editor_scroll.viewport().width() if hasattr(self, "_editor_scroll") else self.width()
        if width < 760:
            return 1
        if width < 920:
            return min(2, max_columns)
        return max_columns

    def _prep_card(self, card):
        configure_card(card, maximum_width=16777215, vertical_policy=QSizePolicy.Policy.Minimum)

    def _prep_field(self, wrap, widget):
        configure_field(wrap, widget, vertical_policy=QSizePolicy.Policy.Minimum)

    def _build_detail(self, element):
        _clear_layout(self._editor_layout)
        self._fields.clear()
        item = self._item_for_element(element)
        if item is None:
            self._show_placeholder(self._tr("ui_cpu_select_entry", ui_text("ui_cpu_select_entry")))
            return

        self._block_changes = True
        cols = self._grid_columns(3)
        self._last_detail_columns = cols
        self._detail_grids = []
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(ss_main_label())
        self._summary.setFont(ui_font(TypeSize.LABEL, QFont.Weight.Bold))
        self._editor_layout.addWidget(self._summary)
        info = QLabel(self._tr('cpu_help_' + element.tag, self._tr('cpu_help_definition')))
        info.setWordWrap(True)
        info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        info.setStyleSheet(ss_dim_label())
        self._editor_layout.addWidget(info)
        if self._missing_sources:
            missing = QLabel(self._tr('cpu_missing', files=', '.join(self._missing_sources)))
            missing.setWordWrap(True)
            missing.setStyleSheet(ss_dim_label())
            self._editor_layout.addWidget(missing)
        self._validation_lbl = QLabel()
        self._validation_lbl.setWordWrap(True)
        self._validation_lbl.setStyleSheet(ss_dim_label())
        self._editor_layout.addWidget(self._validation_lbl)
        for group, keys in field_groups(element):
            card, grid = make_editor_grid_card(self._editor_widget, title=self._tr('cpu_section_' + group), icon_name='fa6s.brain')
            self._prep_card(card)
            fields = [self._make_field(element, key, element.get(key, '')) for key in keys]
            self._detail_grids.append((grid, fields, group))
            self._place_fields(grid, fields, group, cols)
            self._editor_layout.addWidget(card)
        if element.tag == 'Data':
            jump = QPushButton(self._tr('cpu_jump_next'))
            configure_button(jump)
            jump.clicked.connect(self._jump_next)
            self._editor_layout.addWidget(jump)
        self._block_changes = False
        self._refresh_feedback()
        self._editor_layout.addStretch()
        QTimer.singleShot(0, self._fit_card_heights)

    def _fit_card_heights(self, settled=False):
        if self._mode != 'xml':
            return
        width = max(100, self._editor_scroll.viewport().width() - 24)
        for grid, fields, group in self._detail_grids:
            card = grid.parentWidget().parentWidget()
            target_width = min(width, card.maximumWidth())
            for field in fields:
                field.layout().invalidate()
            grid.invalidate()
            card.layout().invalidate()
            height = card.layout().totalHeightForWidth(target_width)
            if height > 0:
                card.setFixedHeight(height)
        self._editor_layout.invalidate()
        if not settled:
            QTimer.singleShot(0, lambda: self._fit_card_heights(True))

    def _place_fields(self, grid, fields, group, cols):
        while grid.count():
            grid.takeAt(0)
        for col in range(3):
            grid.setColumnStretch(col, 0)
        if group == 'sequence' and cols > 1:
            grid.addWidget(fields[0], 0, 0, 1, 2)
            for index, field in enumerate(fields[1:]):
                grid.addWidget(field, 1 + index // 2, index % 2)
            cols = 2
        else:
            for index, field in enumerate(fields):
                grid.addWidget(field, index // cols, index % cols)
        for col in range(cols):
            grid.setColumnStretch(col, 1)

    def _refresh_feedback(self):
        elem = self._current_element
        if elem is None or not hasattr(self, '_validation_lbl'):
            return
        item = self._item_for_element(elem)
        if item:
            self._summary.setText(' · '.join(v for v in (item.get('pattern_name', ''), item['label']) if v))
        try:
            validate_cpu_tree(self._tree, self._original_tree)
            text = ''
        except ValueError as exc:
            text = self._tr('cpu_invalid', error=str(exc))
        for key, value in elem.attrib.items():
            if numeric_field(key) and not valid_integer(value):
                text = self._tr('cpu_numeric_error', field=self._field_title(key), value=value)
                break
        if elem.tag == 'Data' and elem.get('NextCond', '0') != '0':
            pattern = item.get('pattern') if item else None
            matches = pattern.findall('ActionTable/Data') if pattern is not None else []
            if not any(e.get('rid') == elem.get('Next') for e in matches):
                text += ('\n' if text else '') + self._tr('cpu_missing_next', rid=elem.get('Next', ''))
        self._validation_lbl.setText(text)
        self._validation_lbl.setStyleSheet(ss_error_label() if text else ss_dim_label())
        self._validation_lbl.setVisible(bool(text))

    def _jump_next(self):
        elem = self._current_element
        item = self._item_for_element(elem)
        if item is None:
            return
        matches = [i for i in self._items if i['tag'] == 'Data' and i.get('pattern') is item.get('pattern')
                   and i['element'].get('rid') == elem.get('Next')]
        if len(matches) != 1:
            QMessageBox.information(self, self._tr('ui_cpu_select_entry'), self._tr('cpu_next_ambiguous', count=len(matches)))
            return
        self._reset_filters()
        self._select_item(matches[0])
        self._ensure_selected_visible()

    def _reset_filters(self):
        self._search.clear()
        for combo in (self._section_filter, self._pattern_filter, self._status_filter, self._position_filter):
            combo.setCurrentIndex(0)

    def _ensure_selected_visible(self):
        for btn, item in self._buttons:
            if item.get('element') is self._current_element:
                self._list_scroll.ensureWidgetVisible(btn)
                break

    def _build_arcade_detail(self, index):
        _clear_layout(self._editor_layout)
        self._fields.clear()
        if not self._arcade or index < 0 or index >= len(self._arcade.get("entries", [])):
            self._show_placeholder(self._tr("ui_cpu_select_entry", ui_text("ui_cpu_select_entry")))
            return

        entry = self._arcade["entries"][index]
        card, grid = make_editor_grid_card(self._editor_widget, title=entry.get('name') or f'Entry {index + 1}', icon_name='fa6s.brain', subtitle=' / '.join((str(value) for value in entry.get('levels', []))))
        self._prep_card(card)

        self._block_changes = True
        grid.addWidget(self._make_arcade_name_field(entry), 0, 0)
        cols = self._grid_columns(3)
        self._last_detail_columns = cols
        levels = list(entry.get("levels", []))[:ARCADE_CPU_LEVEL_COUNT]
        levels += [0] * (ARCADE_CPU_LEVEL_COUNT - len(levels))
        entry["levels"] = levels
        for idx, value in enumerate(levels):
            field = self._make_arcade_level_field(entry, idx, value)
            pos = idx + 1
            grid.addWidget(field, pos // cols, pos % cols)
        self._block_changes = False
        for col in range(cols):
            grid.setColumnStretch(col, 1)

        self._editor_layout.addWidget(card)
        self._editor_layout.addStretch()

    def _make_arcade_name_field(self, entry):
        wrap, layout, _label, _hint = make_editor_field_shell(self._tr("ui_cpu_arcade_name", "Name"))

        widget = QLineEdit(entry.get("name", ""))
        widget.setMinimumWidth(0)
        widget.textEdited.connect(lambda text, target=entry: self._set_arcade_name(target, text))
        configure_input(widget, monospace=True)
        widget.setCursorPosition(0)
        self._prep_field(wrap, widget)
        layout.addWidget(widget)
        self._fields["name"] = widget
        return wrap

    def _make_arcade_level_field(self, entry, index, value):
        wrap, layout, _label, _hint = make_editor_field_shell(
            self._tr(f"ui_cpu_arcade_level_{index + 1}", f"CPU Level {index + 1}")
        )

        widget = QLineEdit(str(value))
        widget.setMinimumWidth(0)
        widget.textEdited.connect(lambda text, target=entry, level_index=index: self._set_arcade_level(target, level_index, text))
        configure_input(widget, monospace=True)
        widget.setCursorPosition(0)
        self._prep_field(wrap, widget)
        layout.addWidget(widget)
        self._fields[f"level_{index + 1}"] = widget
        return wrap

    def _set_arcade_name(self, entry, value):
        if self._block_changes:
            return
        entry["name"] = value
        self._refresh_arcade_label()
        self._mark_dirty()

    def _set_arcade_level(self, entry, index, value):
        if self._block_changes:
            return
        try:
            parsed = int(value, 0)
        except ValueError:
            return
        levels = entry.setdefault("levels", [0] * ARCADE_CPU_LEVEL_COUNT)
        levels += [0] * (ARCADE_CPU_LEVEL_COUNT - len(levels))
        levels[index] = parsed
        self._refresh_arcade_label()
        self._mark_dirty()

    def _refresh_arcade_label(self):
        if self._mode != "arcade" or self._current_arcade_index is None:
            return
        self._items = self._arcade_items()
        for btn, item in self._buttons:
            if item.get("index") == self._current_arcade_index:
                item.update(self._items[self._current_arcade_index])
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(_truncate(item["label"], 24))
                    labels[0].setToolTip(item["label"])
                    labels[1].setText(_truncate(item.get("subtitle", ""), 30))
                    labels[1].setToolTip(item.get("subtitle", ""))
                break

    def _make_field(self, element, key, value):
        hint = self._tr('cpu_hint_' + key, '')
        if not hint and key.startswith(('general', 'genStr')):
            hint = self._tr('cpu_hint_general')
        wrap, layout, _label, _hint = make_editor_field_shell(self._field_title(key), hint)
        for label in (_label, _hint):
            if label is not None:
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        wrap.setToolTip(key + ('\n' + hint if hint else ''))
        kind = TOKEN_FIELDS.get(key)
        suggestions = set(self._catalog.get(key, []))
        if kind:
            suggestions.update(self._symbols.get(kind, {}))
            if key != 'OpStatus':
                suggestions.add('0')
        if key == 'Position':
            suggestions.update(('Near', 'Middle', 'Far'))
        if key == 'direction':
            suggestions.update(('NONE', 'FRONT', 'BACK', 'NEAR', 'FAR'))
        if key in ('crouch', 'stand'):
            suggestions.update(('0', '1'))
        if kind or key in ('Position', 'direction', 'crouch', 'stand', 'id'):
            widget = QComboBox()
            widget.setEditable(True)
            widget.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            widget.setMinimumWidth(0)
            widget.setMinimumContentsLength(1)
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            labels = {}
            for token in sorted(suggestions | {value}):
                if key in ('crouch', 'stand'):
                    caption = self._tr('cpu_enabled') if token == '1' else self._tr('cpu_disabled') if token == '0' else token
                else:
                    caption = self._token_caption(kind, token) if kind else self._value_caption(token)
                display = f'{caption}  [{token}]' if caption != token else token
                widget.addItem(display, token)
                labels[display] = token
                info = self._symbols.get(kind, {}).get(token, {})
                widget.setItemData(widget.count() - 1, '\n'.join(v for v in (token, info.get('name'), info.get('source')) if v), Qt.ItemDataRole.ToolTipRole)
            widget.setCurrentIndex(widget.findData(value))
            widget.completer().setFilterMode(Qt.MatchFlag.MatchContains)
            widget.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            widget.currentTextChanged.connect(lambda text, elem=element, attr=key, mapping=labels: self._set_attr(elem, attr, mapping.get(text, text)))
        else:
            widget = QLineEdit(value)
            widget.setMinimumWidth(0)
            widget.textEdited.connect(lambda text, elem=element, attr=key: self._set_attr(elem, attr, text))

        configure_input(widget, monospace=True)
        if hasattr(widget, "setCursorPosition"):
            widget.setCursorPosition(0)
        self._prep_field(wrap, widget)
        layout.addWidget(widget)
        self._fields[key] = widget
        if kind:
            detail = QLabel()
            detail.setWordWrap(True)
            detail.setStyleSheet(ss_dim_label())
            detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            detail.setMinimumWidth(0)
            def update_detail(*_):
                token = element.get(key, '')
                info = self._symbols.get(kind, {}).get(token, {})
                detail.setText(' · '.join(v for v in (info.get('name', ''), info.get('source', '')) if v)
                               or ('' if token == '0' else self._tr('cpu_custom_token')))
                detail.setVisible(bool(detail.text()))
            widget.currentTextChanged.connect(update_detail)
            update_detail()
            layout.addWidget(detail)
        return wrap

    def _set_attr(self, element, key, value):
        if self._block_changes:
            return
        if element.get(key) == value:
            return
        element.set(key, value)
        if key in ('name', 'uid', 'id', 'strength'):
            self._reload_symbols()
        self._refresh_current_label()
        self._mark_dirty()
        self._refresh_feedback()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_detail_columns is None:
            return
        columns = self._grid_columns(3)
        if columns == self._last_detail_columns:
            if self._mode == 'xml':
                QTimer.singleShot(0, self._fit_card_heights)
            return
        QTimer.singleShot(0, self._rebuild_current_detail_for_width)

    def _rebuild_current_detail_for_width(self):
        if self._mode == "arcade" and self._current_arcade_index is not None:
            self._build_arcade_detail(self._current_arcade_index)
            return
        if self._current_element is not None:
            columns = self._grid_columns(3)
            for grid, fields, group in self._detail_grids:
                self._place_fields(grid, fields, group, columns)
            self._last_detail_columns = columns
            self._fit_card_heights()

    def _refresh_current_label(self):
        if self._tree is None or self._current_element is None:
            return
        for item in editable_elements(self._tree.getroot()):
            if item["element"] is self._current_element:
                self._present_item(item)
                for btn, old_item in self._buttons:
                    if old_item["element"] is self._current_element:
                        old_item.update(item)
                        labels = btn.findChildren(QLabel)
                        if len(labels) >= 2:
                            labels[0].setText(_truncate(item["label"], 24))
                            labels[0].setToolTip(item["label"])
                            labels[1].setText(_truncate(item.get("subtitle", ""), 30))
                            labels[1].setToolTip(item.get("subtitle", ""))
                        break
                self._filter_list()
                return

    def _mark_dirty(self):
        if self._dirty:
            return
        self._dirty = True
        self._save_btn.setEnabled(True)
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _update_action_buttons(self):
        if self._mode == "arcade":
            mutable = self._current_arcade_index is not None
            self._add_btn.setEnabled(self._arcade is not None)
            self._dup_btn.setEnabled(mutable)
            self._del_btn.setEnabled(mutable)
            return
        mutable = self._current_element is not None and self._current_element.tag in ("Data", "Cond", "Action")
        self._add_btn.setEnabled(self._tree is not None and any(self._tree.getroot().find(p) is not None
                                 for p in ('Pattern/ActionTable', 'ConditionDefine', 'ActionDefine')))
        self._dup_btn.setEnabled(mutable)
        self._del_btn.setEnabled(mutable)

    def _on_add(self):
        if self._mode == "arcade":
            if self._arcade is None:
                return
            entries = self._arcade.setdefault("entries", [])
            source = entries[self._current_arcade_index] if self._current_arcade_index is not None and entries else None
            new_entry = make_default_arcade_cpu_entry(source)
            if source is not None:
                new_entry["name"] = f"{new_entry.get('name', 'Entry')}_COPY"
            entries.append(new_entry)
            self._rebuild_items()
            self._select_arcade_entry(len(entries) - 1)
            self._mark_dirty()
            return
        if self._tree is None:
            return
        root = self._tree.getroot()
        current = self._current_element
        tag = current.tag if current is not None and current.tag in ("Data", "Cond", "Action") else "Data"
        if current is not None and current.tag in ('Status', 'Combo', 'Stiff', 'Next'):
            tag = current.tag
        if current is None or current.tag not in ('Data', 'Cond', 'Action'):
            if self._tree.getroot().find('Pattern') is None:
                tag = 'Cond' if self._section_filter.currentData() == 'conditions' else 'Action'
        parent = self._parent_for_new(tag)
        if parent is None and (current is None or current.tag not in ('Data', 'Cond', 'Action')):
            for candidate in ('Cond', 'Action', 'Data'):
                parent = self._parent_for_new(candidate)
                if parent is not None:
                    tag = candidate
                    break
        if parent is None:
            QMessageBox.warning(self, self._tr("dlg_title_warning", ui_text("dlg_title_warning")), self._tr("ui_cpu_no_parent_for_new_entry", ui_text("ui_cpu_no_parent_for_new_entry")))
            return
        new_elem = add_element_like(parent, None, tag)
        if tag == "Data":
            new_elem.attrib.update(_DEFAULT_DATA_ATTRS)
        elif tag == "Cond":
            new_elem.attrib.update(_DEFAULT_COND_ATTRS)
        elif tag == "Action":
            new_elem.attrib.update(_DEFAULT_ACTION_ATTRS)
        free_identity(parent, new_elem)
        self._reload_symbols()
        self._current_element = new_elem
        self._reset_filters()
        self._rebuild_items()
        self._select_element(new_elem)
        self._mark_dirty()

    def _on_duplicate(self):
        if self._mode == "arcade":
            if self._arcade is None or self._current_arcade_index is None:
                return
            entries = self._arcade.setdefault("entries", [])
            if self._current_arcade_index >= len(entries):
                return
            new_entry = make_default_arcade_cpu_entry(entries[self._current_arcade_index])
            new_entry["name"] = f"{new_entry.get('name', 'Entry')}_COPY"
            entries.insert(self._current_arcade_index + 1, new_entry)
            self._rebuild_items()
            self._select_arcade_entry(self._current_arcade_index + 1)
            self._mark_dirty()
            return
        if self._tree is None or self._current_element is None:
            return
        root = self._tree.getroot()
        parent = find_parent(root, self._current_element)
        if parent is None:
            return
        new_elem = clone_element(self._current_element)
        if self._current_element.tag not in ('Data', 'Cond', 'Action'):
            return
        parent.append(new_elem)
        free_identity(parent, new_elem)
        self._reload_symbols()
        self._current_element = new_elem
        self._reset_filters()
        self._rebuild_items()
        self._select_element(new_elem)
        self._mark_dirty()

    def _on_delete(self):
        if self._mode == "arcade":
            if self._arcade is None or self._current_arcade_index is None:
                return
            entries = self._arcade.setdefault("entries", [])
            if self._current_arcade_index >= len(entries):
                return
            name = entries[self._current_arcade_index].get("name") or f"Entry {self._current_arcade_index + 1}"
            result = QMessageBox.question(
                self,
                self._tr("dlg_title_confirm_delete", ui_text("dlg_title_confirm_delete")),
                self._tr("ui_cpu_delete_entry_value", ui_text("ui_cpu_delete_entry_value"), p0=name),
            )
            if result != QMessageBox.StandardButton.Yes:
                return
            delete_idx = self._current_arcade_index
            del entries[delete_idx]
            self._current_arcade_index = None
            self._rebuild_items()
            if entries:
                self._select_arcade_entry(min(delete_idx, len(entries) - 1))
            else:
                self._show_placeholder(self._tr("ui_cpu_no_editable_entries", ui_text("ui_cpu_no_editable_entries")))
            self._mark_dirty()
            return
        if self._tree is None or self._current_element is None:
            return
        tag = self._current_element.tag
        if tag not in ("Data", "Cond", "Action"):
            return
        if self._referenced(self._current_element):
            QMessageBox.warning(self, self._tr('dlg_title_warning'), self._tr('cpu_referenced'))
            return
        item = self._item_for_element(self._current_element)
        name = item["label"] if item else tag
        result = QMessageBox.question(
            self,
            self._tr("dlg_title_confirm_delete", ui_text("dlg_title_confirm_delete")),
            self._tr("ui_cpu_delete_entry_value", ui_text("ui_cpu_delete_entry_value"), p0=name),
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        root = self._tree.getroot()
        parent = find_parent(root, self._current_element)
        if parent is None:
            return
        remove_element(parent, self._current_element)
        self._current_element = None
        self._fields.clear()
        self._reload_symbols()
        self._rebuild_items()
        if self._items:
            self._select_element(self._items[0]["element"])
        else:
            self._show_placeholder(self._tr("ui_cpu_no_editable_entries", ui_text("ui_cpu_no_editable_entries")))
        self._mark_dirty()

    def _parent_for_new(self, tag):
        root = self._tree.getroot()
        if tag == "Data":
            item = self._item_for_element(self._current_element)
            pattern = item.get('pattern') if item else None
            if pattern is None:
                name = self._pattern_filter.currentData()
                pattern = next((p for p in root.findall('Pattern') if p.get('name') == name), None)
            if pattern is None:
                pattern = root.find('Pattern')
            return pattern.find("ActionTable") if pattern is not None else None
        if tag == "Cond":
            return root.find("ConditionDefine")
        if tag == "Action":
            return root.find("ActionDefine")
        return None

    def _referenced(self, element):
        if element.tag == 'Data':
            item = self._item_for_element(element)
            pattern = item.get('pattern') if item else None
            return pattern is not None and any(e is not element and e.get('NextCond', '0') != '0'
                and e.get('Next') == element.get('rid') for e in pattern.findall('ActionTable/Data'))
        fields = ('Cond1', 'Cond2', 'Cond3') if element.tag == 'Cond' else tuple(f'Act{i}' for i in range(1, 6))
        token = element.get('uid')
        roots = [self._tree.getroot()]
        from pathlib import Path
        path = Path(self._filepath)
        prefix = path.stem.split('_cpu', 1)[0]
        paths = path.parent.glob('*_cpu*.xfbin') if prefix == 'cmn' else path.parent.glob(prefix + '_cpu*.xfbin')
        for sibling in paths:
            if sibling == path:
                continue
            try:
                roots.append(parse_cpu_xfbin(sibling)[2].getroot())
            except (OSError, ValueError, UnicodeError, ET.ParseError):
                continue
        return any(e.get(key) == token for root in roots for e in root.iter('Data') for key in fields)

    def _item_for_element(self, element):
        for item in self._items:
            if item["element"] is element:
                return item
        return None

    def _group_title(self, group):
        return self._tr(f"ui_cpu_group_{group}", group)

    def _field_title(self, key):
        return self._tr(f"ui_cpu_field_{key}", key)
