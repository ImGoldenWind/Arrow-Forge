from core.design_tokens import (
    LayoutRole,
    Size,
)
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
from core.ui.message_preview import message_lookup
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy
import os

from PyQt6.QtCore import QEvent, QRegularExpression, Qt, QTimer
from PyQt6.QtGui import QRegularExpressionValidator
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

from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
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
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


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
        self._fields: dict[str, QWidget] = {}
        self._form_fields = []
        self._dirty = False
        self._loading_detail = False
        self._active_grid_columns = 3

        self._uint32_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._uint64_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,20}"), self)

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

        sidebar = EditorSidebar(width=290)


        sidebar_layout = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)

        self._group_filter = EditorFilterCombo()
        self._group_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._group_filter)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


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
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_termlistparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)

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
            ui_text("ui_termlistparam_open_title"),
            game_files_dialog_dir(target_patterns=("TermListParam.bin.xfbin", "TermListParam.xfbin")),
            ui_text("ui_termlistparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        try:
            raw, result = parse_termlistparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        if self._dirty:
            reply = QMessageBox.question(self, ui_text('dlg_title_warning'),
                                         ui_text('term_discard_changes'),
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
        self._btn_add.setEnabled(True)
        self._btn_save.setEnabled(False)
        self._search.setText("")
        self._group_filter.setCurrentIndex(0)
        self._refresh_group_filter()
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_termlistparam_no_entries"))
        self._update_actions()

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_termlistparam_xfbin(save_path, self._raw_data, self._result)
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

    def _refresh_group_filter(self):
        selected = self._group_filter.currentData()
        self._group_filter.blockSignals(True)
        self._group_filter.clear()
        self._group_filter.addItem(ui_text('ui_termlistparam_group_id'), None)
        for group in sorted({int(e['group_id']) for e in self._entries}):
            self._group_filter.addItem(self._group_label(group), group)
        self._group_filter.setCurrentIndex(max(0, self._group_filter.findData(selected)))
        self._group_filter.blockSignals(False)

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = self._entry_title(idx, entry)
        button_title = self._entry_button_title(idx, entry)
        subtitle_text = self._entry_subtitle(entry)
        button_subtitle = self._entry_button_subtitle(entry)

        title = btn.add_title(_truncate(button_title, 24))


        title.setToolTip(title_text)


        subtitle = btn.add_subtitle(_truncate(button_subtitle, 30))


        subtitle.setToolTip(subtitle_text)
        btn.setToolTip(title_text)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int, entry: dict) -> str:
        key = entry.get('title_key', '')
        return message_lookup(self).text(key)[0] or key or ui_text('ui_termlistparam_empty_text_key')

    def _entry_button_title(self, idx: int, entry: dict) -> str:
        return self._entry_title(idx, entry)

    def _entry_subtitle(self, entry: dict) -> str:
        return ui_text(
            "ui_termlistparam_entry_subtitle",
            group=self._group_label(int(entry.get("group_id", 0))),
            description=entry.get("description_key", ""),
        )

    def _entry_button_subtitle(self, entry: dict) -> str:
        return self._group_label(int(entry.get('group_id', 0)))

    def _group_label(self, value: int) -> str:
        key = f"ui_termlistparam_group_{value}"
        translated = ui_text(key)
        if translated != key:
            return ui_text("ui_termlistparam_group_value", value=value, label=translated)
        return ui_text("ui_termlistparam_group_custom", value=value)

    def _filter_list(self):
        query = self._search.text().lower().strip()
        group = self._group_filter.currentData()
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
                self._entry_title(idx, entry),
                self._group_label(int(entry.get('group_id', 0))),
                message_lookup(self).text(entry.get('description_key', ''))[0],
            ]).lower()
            btn.setVisible((group is None or entry['group_id'] == group) and (not query or query in haystack))

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
                entry = self._entries[idx]
                title_text = self._entry_title(idx, entry)
                subtitle_text = self._entry_subtitle(entry)
                labels[0].setText(_truncate(self._entry_button_title(idx, entry), 24))
                labels[0].setToolTip(title_text)
                labels[1].setText(_truncate(self._entry_button_subtitle(entry), 30))
                labels[1].setToolTip(subtitle_text)
                btn.setToolTip(title_text)
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

        header, header_layout = make_editor_grid_card(self._editor_widget, title=self._entry_title(idx, entry), icon_name='fa6s.book', subtitle=self._entry_subtitle(entry))
        self._prep_card(header)
        self._active_grid_columns = 1
        frame, layout = self._field_shell(ui_text('ui_termlistparam_group_id'))
        combo = QComboBox()
        combo.setEditable(True)
        configure_input(combo, monospace=False)
        group = int(entry.get('group_id', 0))
        for value in dict.fromkeys((0, 1, 2, group)):
            combo.addItem(self._group_label(value), value)
        combo.setCurrentIndex(combo.findData(group))
        combo.setToolTip(ui_text('ui_termlistparam_group_id_hint'))
        combo.editTextChanged.connect(self._on_numeric_text_changed)
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        self._place_field(header_layout, frame, 0, 0)
        self._fields['group_id'] = combo
        self._editor_layout.addWidget(header)

        self._add_section(ui_text("ui_termlistparam_text_keys"))
        text_card = self._make_card()
        text_grid = self._card_grid(text_card)
        self._active_grid_columns = 2
        self._add_text_field(text_grid, 0, 0, "title_key", ui_text("ui_termlistparam_title_key"), entry.get("title_key", ""))
        self._add_text_field(text_grid, 0, 1, "description_key", ui_text("ui_termlistparam_description_key"), entry.get("description_key", ""))
        self._editor_layout.addWidget(text_card)

        self._add_section(ui_text("ui_termlistparam_image_asset"))
        image_card = self._make_card()
        image_grid = self._card_grid(image_card)
        self._active_grid_columns = 2
        self._add_text_field(image_grid, 0, 0, "image_file", ui_text("ui_termlistparam_image_file"), entry.get("image_file", ""))
        self._add_text_field(image_grid, 0, 1, "image_name", ui_text("ui_termlistparam_image_name"), entry.get("image_name", ""))
        self._editor_layout.addWidget(image_card)

        self._add_section(ui_text('term_stored_values'))
        stored_card = self._make_card()
        self._active_grid_columns = 1
        self._add_uint_field(self._card_grid(stored_card), 0, 0, 'unknown_16',
                             ui_text('ui_termlistparam_unknown_16'), entry.get('unknown_16', 0), 0, _UINT64_MAX)
        self._fields['unknown_16'].setToolTip(ui_text('ui_termlistparam_unknown_16_hint'))
        self._editor_layout.addWidget(stored_card)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._reflow_fields()

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
        configure_card(card)
        return card

    def _prep_field_widget(self, frame: QWidget, editor: QWidget):
        configure_field(frame, editor)

    def _place_field(self, grid, frame, row, col):
        maximum = self._active_grid_columns
        self._form_fields.append((grid, frame, row * maximum + col, maximum))
        mapped_row, mapped_col = self._field_position(row, col, maximum)
        grid.addWidget(frame, mapped_row, mapped_col, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(mapped_col, 1)

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
        if key in ('title_key', 'description_key'):
            edit.setProperty('messageTextOnly', True)
        else:
            edit.setToolTip(ui_text('ui_termlistparam_image_hint'))
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame, row, col)
        self._fields[key] = edit

    def _add_uint_field(self, grid, row, col, key, label, value, min_value, max_value, big=False):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._uint32_validator if max_value <= _UINT32_MAX else self._uint64_validator)
        edit.setMaxLength(10 if max_value <= _UINT32_MAX else 20)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(lambda k=key, lo=min_value, hi=max_value: self._on_uint_finished(k, lo, hi))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame, row, col)
        self._fields[key] = edit

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
        columns = self._grid_columns(2)
        for grid, frame, index, maximum in self._form_fields:
            for col in range(maximum):
                grid.setColumnStretch(col, int(col < min(columns, maximum)))
            grid.addWidget(frame, *divmod(index, min(columns, maximum)), Qt.AlignmentFlag.AlignTop)

    def _on_text_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        self._mark_dirty()
        value = self._read_ascii(key)
        if value is None:
            return
        self._entries[self._current_idx][key] = value
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
            if '\0' in text:
                raise ValueError('embedded null')
        except (UnicodeEncodeError, ValueError):
            if show_errors:
                QMessageBox.warning(
                    self,
                    ui_text("dlg_title_warning"),
                    ui_text("term_invalid_reference", field=ui_text(f"ui_termlistparam_{key}")),
                )
            return None
        return text

    def _read_uint(self, key: str, min_value: int, max_value: int, show_errors: bool = False) -> int | None:
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

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._current_idx is None:
            return True
        entry = self._entries[self._current_idx]
        pending = {}
        for key in ("title_key", "description_key", "image_file", "image_name"):
            value = self._read_ascii(key, show_errors=show_errors)
            if value is None:
                return False
            pending[key] = value
        for key in ("group_id", "unknown_16"):
            value = self._read_uint(key, 0, _UINT64_MAX, show_errors=show_errors)
            if value is None:
                return False
            pending[key] = value
        group_changed = entry['group_id'] != pending['group_id']
        entry.update(pending)
        if group_changed:
            self._refresh_group_filter()
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
        entry = make_default_entry()
        group = self._group_filter.currentData()
        if group is not None:
            entry['group_id'] = group
        self._entries.append(entry)
        self._search.clear()
        self._refresh_group_filter()
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
        self._refresh_group_filter()
        self._populate_list()
        if self._entries:
            self._select_entry(min(old_idx, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text("ui_termlistparam_no_entries"))
            self._update_actions()
