"""Editor for ASBR CPU AI XML XFBIN files."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
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
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
    ss_accent_sep,
    ss_file_label,
    ss_input,
    ss_main_label,
    ss_dim_label,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_sep,
    ss_search,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_transparent,
    make_empty_state,
    make_editor_field_shell,
    make_editor_grid_card,
)
from core.translations import ui_text
from parsers.cpu_parser import (
    ARCADE_CPU_LEVEL_COUNT,
    add_element_like,
    clone_element,
    collect_cpu_value_catalog,
    editable_elements,
    find_parent,
    make_default_arcade_cpu_entry,
    parse_arcade_cpu_xfbin,
    parse_cpu_xfbin,
    remove_element,
    save_arcade_cpu_xfbin,
    save_cpu_xfbin,
)


_COMBO_FIELDS = {
    "OpStatus", "Position", "Cond1", "Cond2", "Cond3", "Combo", "StiffCond", "NextCond",
    "Act1", "Act2", "Act3", "Act4", "Act5", "direction", "uid", "id",
}

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

        self._build_ui()

    def _tr(self, key, fallback=None, **kwargs):
        text = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if fallback is not None and text == key else text

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

        self._open_btn = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        self._open_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._open_btn.setFont(QFont("Segoe UI", 10))
        self._open_btn.setStyleSheet(ss_btn(accent=True))
        self._open_btn.clicked.connect(self._on_open)
        top_layout.addWidget(self._open_btn)

        self._save_btn = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        top_layout.addWidget(self._save_btn)

        self._file_lbl = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_lbl)
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
        sidebar.setFixedWidth(260)
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

        self._add_btn = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.setEnabled(False)
        self._dup_btn.clicked.connect(self._on_duplicate)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._on_delete)
        actions_layout.addWidget(self._del_btn, 1)
        sidebar_layout.addWidget(actions)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_widget.setMinimumWidth(0)
        self._list_widget.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        sidebar_layout.addWidget(self._list_scroll, 1)
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
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)
        self._editor_scroll.setWidget(self._editor_widget)
        self._show_placeholder(self._tr("ui_cpu_open_cpu_xfbin", ui_text("ui_cpu_open_cpu_xfbin")))
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
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
        create_backup_on_open(path)
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
        self._arcade = arcade
        self._catalog = collect_cpu_value_catalog(os.path.dirname(path)) if mode == "xml" else {}
        self._dirty = False
        self._current_element = None
        self._current_arcade_index = None

        set_file_label(self._file_lbl, path)
        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._rebuild_items()
        if self._items:
            self._select_item(self._items[0])
        else:
            self._show_placeholder(self._tr("ui_cpu_no_editable_entries", ui_text("ui_cpu_no_editable_entries")))

    def _on_save(self):
        if not self._filepath or self._raw is None:
            return
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
                save_arcade_cpu_xfbin(self._filepath, self._raw, self._arcade)
                self._raw, self._arcade = parse_arcade_cpu_xfbin(self._filepath)
            else:
                save_cpu_xfbin(self._filepath, self._raw, self._chunk, self._tree)
                self._raw, self._chunk, self._tree = parse_cpu_xfbin(self._filepath)
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
        except Exception as exc:
            QMessageBox.critical(self, self._tr("dlg_title_error", ui_text("dlg_title_error")), self._tr("msg_save_error", ui_text("msg_save_error"), error=exc))

    def _rebuild_items(self):
        _clear_layout(self._list_layout)
        self._buttons = []
        if self._mode == "arcade" and self._arcade is not None:
            self._items = self._arcade_items()
        else:
            self._items = editable_elements(self._tree.getroot()) if self._tree is not None else []
        last_group = None
        for item in self._items:
            if item["group"] != last_group:
                label = QLabel(self._group_title(item["group"]))
                label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                label.setStyleSheet(ss_dim_label())
                self._list_layout.addWidget(label)
                last_group = item["group"]
            btn = self._make_item_button(item)
            self._list_layout.addWidget(btn)
            self._buttons.append((btn, item))
        self._list_layout.addStretch()
        self._filter_list()

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
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=selected))
        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(0)

        title = QLabel(item["label"])
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        title.setMinimumWidth(0)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)

        subtitle = QLabel(item.get("subtitle", ""))
        subtitle.setFont(QFont("Consolas", 11))
        subtitle.setStyleSheet(ss_dim_label())
        subtitle.setMinimumWidth(0)
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, selected_item=item: self._select_item(selected_item))
        return btn

    def _select_item(self, item):
        if self._mode == "arcade":
            self._select_arcade_entry(item["index"])
        else:
            self._select_element(item["element"])

    def _filter_list(self):
        query = self._search.text().lower() if self._search else ""
        for btn, item in self._buttons:
            blob = " ".join([item["label"], item["tag"], item["group"]]).lower()
            btn.setVisible(query in blob)

    def _select_element(self, element):
        self._current_element = element
        self._current_arcade_index = None
        for btn, item in self._buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(item["element"] is element)))
        self._build_detail(element)
        self._update_action_buttons()

    def _select_arcade_entry(self, index):
        self._current_arcade_index = index
        self._current_element = None
        for btn, item in self._buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(item.get("index") == index)))
        self._build_arcade_detail(index)
        self._update_action_buttons()

    def _build_detail(self, element):
        _clear_layout(self._editor_layout)
        self._fields.clear()
        item = self._item_for_element(element)
        if item is None:
            self._show_placeholder(self._tr("ui_cpu_select_entry", ui_text("ui_cpu_select_entry")))
            return

        card, grid = make_editor_grid_card(
            self._editor_widget,
            title=item["label"],
            icon_name="fa6s.brain",
            subtitle=item.get("subtitle", ""),
            grid_margins=(0, 2, 0, 0),
            horizontal_spacing=12,
            vertical_spacing=8,
        )

        self._block_changes = True
        cols = 1 if self.width() < 900 else 2
        for idx, (key, value) in enumerate(element.attrib.items()):
            field = self._make_field(element, key, value)
            grid.addWidget(field, idx // cols, idx % cols)
        self._block_changes = False
        for col in range(cols):
            grid.setColumnStretch(col, 1)

        self._editor_layout.addWidget(card)
        self._editor_layout.addStretch()

    def _build_arcade_detail(self, index):
        _clear_layout(self._editor_layout)
        self._fields.clear()
        if not self._arcade or index < 0 or index >= len(self._arcade.get("entries", [])):
            self._show_placeholder(self._tr("ui_cpu_select_entry", ui_text("ui_cpu_select_entry")))
            return

        entry = self._arcade["entries"][index]
        card, grid = make_editor_grid_card(
            self._editor_widget,
            title=entry.get("name") or f"Entry {index + 1}",
            icon_name="fa6s.brain",
            subtitle=" / ".join(str(value) for value in entry.get("levels", [])),
            grid_margins=(0, 2, 0, 0),
            horizontal_spacing=12,
            vertical_spacing=8,
        )

        self._block_changes = True
        grid.addWidget(self._make_arcade_name_field(entry), 0, 0)
        cols = 1 if self.width() < 900 else 2
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
        widget.setFixedHeight(30)
        widget.setFont(QFont("Consolas", 13))
        widget.setStyleSheet(ss_input())
        widget.setCursorPosition(0)
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
        widget.setFixedHeight(30)
        widget.setFont(QFont("Consolas", 13))
        widget.setStyleSheet(ss_input())
        widget.setCursorPosition(0)
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
                    labels[0].setText(item["label"])
                    labels[1].setText(item.get("subtitle", ""))
                break

    def _make_field(self, element, key, value):
        wrap, layout, _label, _hint = make_editor_field_shell(self._field_title(key))

        suggestions = self._catalog.get(key, [])
        if key in _COMBO_FIELDS and suggestions:
            widget = QComboBox()
            widget.setEditable(True)
            widget.setMinimumWidth(0)
            widget.setMinimumContentsLength(1)
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            for item in suggestions:
                widget.addItem(item)
            if value not in suggestions:
                widget.insertItem(0, value)
            widget.setCurrentText(value)
            widget.currentTextChanged.connect(lambda text, elem=element, attr=key: self._set_attr(elem, attr, text))
        else:
            widget = QLineEdit(value)
            widget.setMinimumWidth(0)
            widget.textEdited.connect(lambda text, elem=element, attr=key: self._set_attr(elem, attr, text))

        widget.setFixedHeight(30)
        widget.setFont(QFont("Consolas", 13))
        widget.setStyleSheet(ss_input())
        if hasattr(widget, "setCursorPosition"):
            widget.setCursorPosition(0)
        layout.addWidget(widget)
        self._fields[key] = widget

        return wrap

    def _set_attr(self, element, key, value):
        if self._block_changes:
            return
        element.set(key, value)
        self._refresh_current_label()
        self._mark_dirty()

    def _refresh_current_label(self):
        if self._tree is None or self._current_element is None:
            return
        for item in editable_elements(self._tree.getroot()):
            if item["element"] is self._current_element:
                for btn, old_item in self._buttons:
                    if old_item["element"] is self._current_element:
                        old_item.update(item)
                        labels = btn.findChildren(QLabel)
                        if len(labels) >= 2:
                            labels[0].setText(item["label"])
                            labels[1].setText(item.get("subtitle", ""))
                        break
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
        parent = self._parent_for_new(tag)
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
        self._current_element = new_elem
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
        parent.append(new_elem)
        self._current_element = new_elem
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
        self._rebuild_items()
        if self._items:
            self._select_element(self._items[0]["element"])
        else:
            self._show_placeholder(self._tr("ui_cpu_no_editable_entries", ui_text("ui_cpu_no_editable_entries")))
        self._mark_dirty()

    def _parent_for_new(self, tag):
        root = self._tree.getroot()
        if tag == "Data":
            pattern = root.find("Pattern")
            return pattern.find("ActionTable") if pattern is not None else None
        if tag == "Cond":
            return root.find("ConditionDefine")
        if tag == "Action":
            return root.find("ActionDefine")
        return None

    def _item_for_element(self, element):
        for item in self._items:
            if item["element"] is element:
                return item
        return None

    def _group_title(self, group):
        return self._tr(f"ui_cpu_group_{group}", group)

    def _field_title(self, key):
        return self._tr(f"ui_cpu_field_{key}", key)
