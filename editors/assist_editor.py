"""editors/assist_editor.py  –  Editor for SupportCharaParam.bin.xfbin."""

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_accent_label,
    ss_bg_dark,
    ss_dim_label,
    ss_error_label,
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
    fit_scroll_page,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import install_file_actions
import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QSizePolicy,
    QComboBox, QCheckBox,
)
from PyQt6.QtCore import Qt, QTimer, QRegularExpression, QEvent
from PyQt6.QtGui import QFont, QRegularExpressionValidator

from core.editor_file_state import set_file_label
from parsers.assist_parser import (
    parse_assist_xfbin, save_assist_xfbin, make_default_entry,
    validate_entries,
)
from core.assist_research import field_groups, field_key, caption, hint, cooldown_rows, field_options
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


# Character display names (fallback when translation key not found)

_CHAR_NAMES = {
    "1jnt01": ui_text("char_1jnt01"),
    "1zpl01": ui_text("char_1zpl01"),
    "1dio01": ui_text("char_1dio01"),
    "1sdw01": ui_text("char_1sdw01"),
    "2jsp01": ui_text("char_2jsp01"),
    "2csr01": ui_text("char_2csr01"),
    "2esd01": ui_text("char_2esd01"),
    "2wmu01": ui_text("char_2wmu01"),
    "2krs01": ui_text("char_2krs01"),
    "2lsa01": ui_text("char_2lsa01"),
    "2shm01": ui_text("char_2shm01"),
    "3jtr01": ui_text("char_3jtr01"),
    "3kki01": ui_text("char_3kki01"),
    "3jsp01": ui_text("char_3jsp01"),
    "3pln01": ui_text("char_3pln01"),
    "3abd01": ui_text("char_3abd01"),
    "3igy01": ui_text("char_3igy01"),
    "3hhs01": ui_text("char_3hhs01"),
    "3vni01": ui_text("char_3vni01"),
    "3dio01": "DIO",
    "3mra01": ui_text("char_3mra01"),
    "3psp01": ui_text("char_3psp01"),
    "4jsk01": ui_text("char_4jsk01"),
    "4koi01": ui_text("char_4koi01"),
    "4oky01": ui_text("char_4oky01"),
    "4kch01": ui_text("char_4kch01"),
    "4rhn01": ui_text("char_4rhn01"),
    "4sgc01": ui_text("char_4sgc01"),
    "4fgm01": ui_text("char_4fgm01"),
    "4oti01": ui_text("char_4oti01"),
    "4kir01": ui_text("char_4kir01"),
    "4kwk01": ui_text("char_4kwk01"),
    "4jtr01": ui_text("char_4jtr01"),
    "4ykk01": ui_text("char_4ykk01"),
    "5grn01": ui_text("char_5grn01"),
    "5mst01": ui_text("char_5mst01"),
    "5fgo01": ui_text("char_5fgo01"),
    "5nrc01": ui_text("char_5nrc01"),
    "5bct01": ui_text("char_5bct01"),
    "5abc01": ui_text("char_5abc01"),
    "5dvl01": ui_text("char_5dvl01"),
    "5gac01": ui_text("char_5gac01"),
    "5prs01": ui_text("char_5prs01"),
    "5trs01": ui_text("char_5trs01"),
    "5ris01": ui_text("char_5ris01"),
    "6jln01": ui_text("char_6jln01"),
    "6elm01": ui_text("char_6elm01"),
    "6ans01": ui_text("char_6ans01"),
    "6pci01": ui_text("char_6pci01"),
    "6pci02": ui_text("char_6pci02"),
    "6fit01": ui_text("char_6fit01"),
    "6wet01": ui_text("char_6wet01"),
    "7jny01": ui_text("char_7jny01"),
    "7jir01": ui_text("char_7jir01"),
    "7vtn01": ui_text("char_7vtn01"),
    "7dio01": ui_text("char_7dio01"),
    "7dio02": ui_text("char_7dio02"),
    "8jsk01": ui_text("char_8jsk01"),
    "8wou01": ui_text("char_8wou01"),
    "0bao01": ui_text("char_0bao01"),
}


# Field grouping for card layout

# Helpers

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
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "..."


# Editor

class AssistEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath = None
        self._original_data = None
        self._entries = []
        self._dirty = False
        self._current_idx = -1
        self._current_entry = None
        self._entry_buttons = []
        self._fields = {}
        self._display_name_lbl = None
        self._last_compact: bool | None = None
        self._version = 1000
        self._advanced = False
        self._original_entries = []
        self._numeric_validator = QRegularExpressionValidator(QRegularExpression(r'-?\d{0,10}'), self)
        self._id_validator = QRegularExpressionValidator(QRegularExpression(r'[A-Za-z0-9_]{0,128}'), self)

        self._build_ui()
        install_file_actions(self, self._btn_save, existing_button=self._btn_save_as)
        install_editor_chrome(self)

    # Name resolution

    def _get_display_name(self, char_id):
        key = f"char_{char_id}"
        translated = self._t(key)
        if translated != key:
            return translated
        return _CHAR_NAMES.get(char_id, char_id)

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        # Toolbar
        top = EditorToolbar()
        tl = top.content_layout

        self._btn_open = QPushButton(self._t("btn_open_file"))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_open.setProperty("designAction", 'open')
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._t("btn_save_file"))
        configure_button(self._btn_save, accent=True)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        tl.addWidget(self._btn_save)

        self._btn_save_as = QPushButton(ui_text('assist_save_as'))
        configure_button(self._btn_save_as)
        self._btn_save_as.setEnabled(False)
        self._btn_save_as.clicked.connect(self._on_save_as)
        tl.addWidget(self._btn_save_as)

        self._file_lbl = QLabel(self._t("no_file_loaded"))

        configure_file_label(self._file_lbl)
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Left sidebar
        sidebar = EditorSidebar()


        sl = sidebar.content_layout


        self._search_entry = QLineEdit()
        configure_search(self._search_entry)
        self._search_entry.textChanged.connect(self._filter_list)
        sl.addWidget(self._search_entry)

        abf = EditorActionRow()

        abl = abf.content_layout


        bf = ui_font(TypeSize.BODY)

        self._btn_add = QPushButton(self._t("btn_new"))
        self._btn_add.setEnabled(False)
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_add.setProperty("designAction", 'new')
        abl.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._t("btn_duplicate"))
        self._btn_dup.setEnabled(False)
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.clicked.connect(self._on_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        abl.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._t("btn_delete"))
        self._btn_del.setEnabled(False)
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_del.setProperty("designAction", 'delete')
        abl.addWidget(self._btn_del, 1)

        sl.addWidget(abf)

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
        sl.addWidget(self._entry_scroll)

        main_layout.addWidget(sidebar)

        div = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(div)

        # Right panel
        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        content_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        content_policy.setHeightForWidth(True)
        self._editor_widget.setSizePolicy(content_policy)
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)

        self._set_editor_placeholder(ui_text("ui_assist_open_a_supportcharaparam_bin_xfbin_file_to_begin"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # Helpers

    def _set_editor_placeholder(self, text):
        _clear_layout(self._editor_layout)
        title = self._t("no_file_loaded") if self._filepath is None else ui_text("ui_model_viewer_select_item")
        card = make_empty_state(
            self._editor_widget,
            title=title,
            text=text,
            icon_name="fa6s.handshake-angle",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _add_section(self, title):
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

    def _prep_card(self, card: QFrame):
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        return card

    def _prep_field_widget(self, widget: QWidget):
        configure_field(widget, vertical_policy=QSizePolicy.Policy.Minimum)
        return widget

    def _add_editor_card(self, card: QFrame):
        self._editor_layout.addWidget(card)

    def _field_position(self, row: int, col: int, max_columns: int = 3) -> tuple[int, int]:
        columns = self._grid_columns(max_columns)
        logical_index = row * max_columns + col
        return divmod(logical_index, columns)

    def _build_field_card(self, field_indices, entry, cols=3):
        field_indices = [fi for fi in field_indices if field_key(fi, self._version) != 'reserved']
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(self._editor_widget, title=section_title, icon_name='fa6s.sliders')
        self._prep_card(card)
        actual_cols = self._grid_columns(cols)

        for i, fi in enumerate(field_indices):
            row, col = divmod(i, actual_cols)
            f, fl, label, _hint = make_editor_field_shell(caption(fi, self._version), hint(fi, self._version))
            for text_widget in (label, _hint):
                if text_widget is not None:
                    text_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            self._prep_field_widget(f)
            label.setToolTip(hint(fi, self._version))
            self._add_numeric(fl, fi, entry)

            grid.addWidget(f, row, col)
            grid.setColumnStretch(col, 1)
        return card

    def _add_numeric(self, layout, fi, entry):
        options = field_options(fi, self._version)
        if options:
            e = QComboBox()
            e.setEditable(True)
            e.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            for value, text in options:
                e.addItem(text, value)
            value = entry[f'f{fi}']
            index = e.findData(value)
            if index < 0:
                e.addItem(ui_text('assist_custom_value', value=value), value)
                index = e.count() - 1
            e.setCurrentIndex(index)
            e.currentTextChanged.connect(self._mark_dirty)
        else:
            e = QLineEdit(str(entry[f'f{fi}']))
            e.setValidator(self._numeric_validator)
            e.textEdited.connect(self._mark_dirty)
        e.setMinimumWidth(0)
        e.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        configure_input(e, monospace=True)
        e.setToolTip(hint(fi, self._version))
        layout.addWidget(e)
        self._fields[f'f{fi}'] = e

    def _build_cooldowns(self, entry):
        card, grid = make_editor_grid_card(
            self._editor_widget, title=ui_text('assist_ai_title'),
            icon_name='fa6s.robot', subtitle=ui_text('assist_cooldowns_hint'))
        self._prep_card(card)
        fi = 18 + int(self._version >= 1001)
        field, layout, _, _ = make_editor_field_shell(caption(fi, self._version), hint(fi, self._version))
        self._prep_field_widget(field)
        self._add_numeric(layout, fi, entry)
        grid.addWidget(field, 0, 0, 1, 3 if self._last_compact else 4)
        for row, (name, indices) in enumerate(cooldown_rows(self._version)):
            if self._last_compact:
                label = QLabel(name)
                label.setStyleSheet(ss_accent_label())
                label.setWordWrap(True)
                grid.addWidget(label, row * 2 + 1, 0, 1, 3)
                for col, fi in enumerate(indices):
                    field, layout, _, _ = make_editor_field_shell(ui_text('assist_cd_column', index=col + 1))
                    self._prep_field_widget(field)
                    self._add_numeric(layout, fi, entry)
                    grid.addWidget(field, row * 2 + 2, col)
                    grid.setColumnStretch(col, 1)
            else:
                label = QLabel(name)
                label.setStyleSheet(ss_dim_label())
                label.setWordWrap(True)
                label.setMinimumWidth(0)
                grid.addWidget(label, row + 2, 0)
                for col, fi in enumerate(indices):
                    if row == 0:
                        head = QLabel(ui_text('assist_cd_column', index=col + 1))
                        head.setWordWrap(True)
                        head.setStyleSheet(ss_dim_label())
                        grid.addWidget(head, 1, col + 1)
                    shell, layout, _, _ = make_editor_field_shell('')
                    self._prep_field_widget(shell)
                    layout.itemAt(0).widget().hide()
                    self._add_numeric(layout, fi, entry)
                    grid.addWidget(shell, row + 2, col + 1)
                    grid.setColumnStretch(col + 1, 1)
        return card

    # Data

    def _load_file(self, filepath):
        if not self._confirm_discard():
            return False
        try:
            data, entries = parse_assist_xfbin(filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=exc))
            return False

        create_backup_on_open(filepath)

        self._filepath = filepath
        self._original_data = data
        self._entries = entries
        self._original_entries = copy.deepcopy(entries)
        from parsers.assist_parser import _layout
        self._version = _layout(data)[3]
        self._dirty = False
        self._current_idx = -1
        self._current_entry = None
        self._fields = {}

        self._search_entry.clear()

        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(bool(entries))
        self._btn_del.setEnabled(bool(entries))

        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._set_editor_placeholder(ui_text("ui_assist_no_entries_found"))
        return True

    def _populate_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []
        for i, entry in enumerate(self._entries):
            btn = self._make_entry_button(entry, i)
            self._entry_list_layout.addWidget(btn)
            self._entry_buttons.append((btn, i))
        self._entry_list_layout.addStretch()
        self._filter_list()

    def _make_entry_button(self, entry, idx):
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        bl = btn.content_layout


        char_id = entry['char_id']
        display_name = self._get_display_name(char_id)
        name_lbl = btn.add_title(_truncate(display_name, 24))


        name_lbl.setToolTip(display_name)


        id_lbl = btn.add_subtitle(_truncate(char_id, 28))


        id_lbl.setToolTip(char_id)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        btn.installEventFilter(self)
        return btn

    def _filter_list(self):
        query = self._search_entry.text().strip().casefold()
        visible = 0
        for btn, i in self._entry_buttons:
            if i >= len(self._entries):
                continue
            entry = self._entries[i]
            char_id = entry['char_id']
            name = self._get_display_name(char_id)
            matches = all(part in (char_id + ' ' + name).casefold() for part in query.split())
            btn.setVisible(matches)
            visible += int(matches)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            visible = [(btn, idx) for btn, idx in self._entry_buttons if not btn.isHidden()]
            pos = next((i for i, (btn, _) in enumerate(visible) if btn is obj), None)
            if pos is not None and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
                target = (0 if event.key() == Qt.Key.Key_Home else len(visible) - 1
                          if event.key() == Qt.Key.Key_End else
                          max(0, min(len(visible) - 1, pos + (1 if event.key() == Qt.Key.Key_Down else -1))))
                btn, idx = visible[target]
                if self._select_entry(idx):
                    btn.setFocus()
                    self._entry_scroll.ensureWidgetVisible(btn)
                return True
        return super().eventFilter(obj, event)

    def _select_entry(self, idx):
        if not self._apply_fields():
            return False
        self._current_idx = idx
        self._current_entry = self._entries[idx] if 0 <= idx < len(self._entries) else None
        for btn, i in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))
        if self._current_entry is not None:
            self._build_editor(self._current_entry)
        else:
            self._set_editor_placeholder(ui_text("ui_assist_select_an_entry"))
        self._btn_dup.setEnabled(self._current_entry is not None)
        self._btn_del.setEnabled(self._current_entry is not None)
        return True

    def _apply_fields(self):
        if not self._current_entry or not self._fields:
            return True
        candidate = copy.deepcopy(self._current_entry)
        for key, field in self._fields.items():
            try:
                if key == 'char_id':
                    text = field.text()
                    if not text or len(text.encode('ascii')) > 128 or '\0' in text:
                        raise ValueError()
                    candidate[key] = text
                else:
                    if isinstance(field, QComboBox):
                        text = field.currentText()
                        index = field.currentIndex()
                        value = (field.itemData(index) if index >= 0 and text == field.itemText(index)
                                 else int(text.strip()))
                    else:
                        value = int(field.text().strip())
                    if not -0x80000000 <= value <= 0x7fffffff:
                        raise ValueError()
                    candidate[key] = value
            except (ValueError, UnicodeError):
                if self._technical_card.isAncestorOf(field):
                    self._validation_label.setText(ui_text('assist_invalid', field=(
                    ui_text('ui_assist_char_id') if key == 'char_id' else caption(int(key[1:]), self._version))))
                self._validation_label.show()
                field.setFocus()
                self._editor_scroll.ensureWidgetVisible(field)
                return False
        all_entries = [candidate if i == self._current_idx else e for i, e in enumerate(self._entries)]
        try:
            validate_entries(all_entries, self._original_entries)
        except (ValueError, UnicodeError):
            self._validation_label.setText(ui_text('assist_duplicate_hint'))
            self._validation_label.show()
            return False
        old_id = self._current_entry['char_id']
        self._current_entry.update(candidate)
        self._validation_label.clear()
        self._validation_label.hide()
        if old_id != candidate['char_id']:
            self._populate_list()
        return True

    def _build_editor(self, entry):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._display_name_lbl = None
        self._last_compact = self._is_compact_editor()
        self._last_columns = self._grid_columns(3)
        self._version = entry.get('_version', self._version)
        display_name = self._get_display_name(entry['char_id'])
        display_limit = 22 if self._last_compact else 30
        display_font = ui_font(TypeSize.SECTION if self._last_compact else TypeSize.DISPLAY, QFont.Weight.Bold)
        display_height = 34 if self._last_compact else 36

        # Header card
        hdr, hdr_grid = make_editor_grid_card(self._editor_widget, title=ui_text('ui_assist_character'), icon_name='fa6s.handshake-angle', subtitle=_truncate(display_name, display_limit))
        self._prep_card(hdr)

        # Column 0: display name (cosmetic, non-editable)
        name_frame, name_layout, _label, _hint = make_editor_field_shell(ui_text("ui_assist_character"))
        self._prep_field_widget(name_frame)

        self._display_name_lbl = QLabel(_truncate(display_name, display_limit))
        self._display_name_lbl.setMinimumWidth(0)
        self._display_name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._display_name_lbl.setFont(display_font)
        self._display_name_lbl.setStyleSheet(ss_accent_label())
        self._display_name_lbl.setFixedHeight(display_height)
        self._display_name_lbl.setToolTip(display_name)
        name_layout.addWidget(self._display_name_lbl)

        row, col = self._field_position(0, 0, max_columns=2)
        hdr_grid.addWidget(name_frame, row, col)
        hdr_grid.setColumnStretch(col, 2)

        # Column 1: char_id (editable)
        id_frame, id_layout, _label, _hint = make_editor_field_shell(ui_text("ui_assist_char_id"))
        self._prep_field_widget(id_frame)

        e_id = QLineEdit(entry['char_id'])
        e_id.setValidator(self._id_validator)
        e_id.setMaxLength(128)
        e_id.setToolTip(ui_text('assist_id_hint'))
        e_id.setMinimumWidth(0)
        e_id.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        configure_input(e_id, height=Size.LARGE_CONTROL, monospace=True)
        e_id.setCursorPosition(0)
        e_id.textEdited.connect(self._on_char_id_edited)
        id_layout.addWidget(e_id)
        self._fields['char_id'] = e_id

        row, col = self._field_position(0, 1, max_columns=2)
        hdr_grid.addWidget(id_frame, row, col)
        hdr_grid.setColumnStretch(col, 1)

        self._add_editor_card(hdr)

        self._validation_label = QLabel()
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet(ss_error_label())
        self._validation_label.hide()
        self._editor_layout.addWidget(self._validation_label)

        nav = QWidget()
        nav.setStyleSheet(ss_transparent())
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(*Insets.NONE)
        nav_layout.setSpacing(6)
        self._section_cards = {}
        for key in ('stocks', 'sequence', 'ai'):
            button = QPushButton(ui_text('assist_nav_' + key))
            configure_button(button, height=Size.COMPACT_CONTROL)
            button.clicked.connect(lambda checked=False, section=key: self._jump_section(section))
            nav_layout.addWidget(button)
        nav_layout.addStretch()
        self._editor_layout.addWidget(nav)

        # Field group cards
        groups = field_groups(self._version)
        for section, field_indices in groups[:-1]:
            self._add_section(ui_text('assist_group_' + section))
            card = self._build_field_card(field_indices, entry, cols=3)
            self._section_cards[section] = card
            self._add_editor_card(card)

        ai_card = self._build_cooldowns(entry)
        self._section_cards['ai'] = ai_card
        self._add_editor_card(ai_card)
        self._add_section(ui_text('assist_group_technical'))
        self._technical_card = self._build_field_card(groups[-1][1][1:], entry, cols=3)
        self._add_editor_card(self._technical_card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        QTimer.singleShot(0, self._fit_editor_page)

    def _fit_editor_page(self):
        fit_scroll_page(self._editor_scroll)

    def _jump_section(self, section):
        card = self._section_cards.get(section)
        if card is not None:
            self._editor_scroll.verticalScrollBar().setValue(card.y() - 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_entry is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_entry is None:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact and self._grid_columns(3) == self._last_columns:
            self._fit_editor_page()
            return
        if not self._apply_fields():
            return
        self._build_editor(self._current_entry)

    def _on_char_id_edited(self, new_id):
        if self._display_name_lbl is not None:
            display_name = self._get_display_name(new_id)
            display_limit = 22 if self._is_compact_editor() else 30
            self._display_name_lbl.setText(_truncate(display_name, display_limit))
            self._display_name_lbl.setToolTip(display_name)
        self._mark_dirty()

    def _mark_dirty(self, *_):
        self._dirty = True
        self._btn_save.setEnabled(True)
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    # File I/O

    def closeEvent(self, event):
        if not self._embedded and not self._confirm_discard():
            event.ignore()
            return
        super().closeEvent(event)

    def _confirm_discard(self):
        if not self._dirty:
            return True
        result = QMessageBox.question(
            self, ui_text('assist_unsaved_title'), ui_text('assist_unsaved_text'),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if result == QMessageBox.StandardButton.Save:
            return self._on_save()
        return result == QMessageBox.StandardButton.Discard

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_assist_open_supportcharaparam_bin_xfbin"), game_files_dialog_dir(target_patterns="SupportCharaParam.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if path:
            self._load_file(path)

    def _on_save(self):
        if not self._filepath or self._original_data is None:
            return False
        return self._save_to(self._filepath)

    def _on_save_as(self):
        if self._original_data is None or not self._apply_fields():
            return False
        path, _ = QFileDialog.getSaveFileName(self, ui_text('assist_save_as'), self._filepath,
                                            'XFBIN Files (*.xfbin);;All Files (*)')
        return self._save_to(path) if path else False

    def _save_to(self, path):
        if not self._apply_fields():
            return False
        try:
            save_assist_xfbin(path, self._original_data, self._entries)
            data, entries = parse_assist_xfbin(path)
            self._filepath = path
            self._original_data = data
            self._entries = entries
            self._original_entries = copy.deepcopy(entries)
            self._current_entry = entries[self._current_idx] if 0 <= self._current_idx < len(entries) else None
            self._dirty = False
            name = os.path.basename(self._filepath)
            set_file_label(self._file_lbl, self._filepath)
            QMessageBox.information(self, ui_text("ui_assist_saved"), ui_text("ui_assist_file_saved_value", p0=name))
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=exc))
            return False

    # Add / Dup / Delete

    def _on_add(self):
        if not self._apply_fields():
            return
        new_entry = make_default_entry(self._unique_id('assist'), version=self._version)
        self._entries.append(new_entry)
        self._current_entry = None
        self._fields = {}
        self._search_entry.clear()
        self._populate_list()
        self._mark_dirty()
        self._select_entry(len(self._entries) - 1)
        self._fields['char_id'].setFocus()
        self._fields['char_id'].selectAll()

    def _unique_id(self, base):
        used = {e['char_id'] for e in self._entries}
        i = 1
        while f'{base[:110]}_{i}' in used:
            i += 1
        return f'{base[:110]}_{i}'

    def _on_dup(self):
        if self._current_idx < 0 or self._current_idx >= len(self._entries):
            return
        if not self._apply_fields():
            return
        new_entry = copy.deepcopy(self._entries[self._current_idx])
        new_entry['char_id'] = self._unique_id(new_entry['char_id'])
        new_idx = self._current_idx + 1
        self._entries.insert(new_idx, new_entry)
        self._current_entry = None
        self._fields = {}
        self._search_entry.clear()
        self._populate_list()
        self._mark_dirty()
        self._select_entry(new_idx)
        self._fields['char_id'].setFocus()
        self._fields['char_id'].selectAll()

    def _on_delete(self):
        if self._current_idx < 0 or self._current_idx >= len(self._entries):
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("msg_cannot_delete_last_entry"))
            return
        name = self._get_display_name(self._entries[self._current_idx]['char_id'])
        result = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"), ui_text("ui_assist_delete_entry_for_value", p0=name)
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        del self._entries[self._current_idx]
        new_idx = min(self._current_idx, len(self._entries) - 1)
        self._current_idx = -1
        self._current_entry = None
        self._fields = {}
        self._populate_list()
        self._mark_dirty()
        self._select_entry(new_idx)
