"""editors/speaking_editor.py  –  Editor for SpeakingLineParam.bin.xfbin."""

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
    ss_accent_label,
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
from core.ui.message_preview import MessagePreview
from core.message_text import MessageText
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox,
    QSizePolicy, QComboBox, QCompleter,
)
from PyQt6.QtCore import Qt, QTimer

from parsers.speaking_parser import (
    parse_speaking_xfbin, save_speaking_xfbin,
)
from core.translations import current_language, ui_text
from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            w = item.widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


_CHAR_NAMES = {
    "0bao01": ui_text("char_0bao01"),
    "1jnt01": ui_text("char_1jnt01"),     "1zpl01": ui_text("char_1zpl01"),
    "1dio01": ui_text("char_1dio01"),           "1sdw01": ui_text("char_1sdw01"),
    "2jsp01": ui_text("char_2jsp01"),       "2csr01": ui_text("char_2csr01"),
    "2esd01": ui_text("char_2esd01"),              "2wmu01": ui_text("char_2wmu01"),
    "2krs01": ui_text("char_2krs01"),                 "2lsa01": ui_text("char_2lsa01"),
    "2shm01": ui_text("char_2shm01"),
    "3jtr01": ui_text("char_3jtr01"),          "3kki01": ui_text("char_3kki01"),
    "3jsp01": ui_text("char_3jsp01"),   "3pln01": ui_text("char_3pln01"),
    "3abd01": ui_text("char_3abd01"),       "3igy01": ui_text("char_3igy01"),
    "3hhs01": ui_text("char_3hhs01"),            "3vni01": ui_text("char_3vni01"),
    "3dio01": "DIO",                  "3mra01": ui_text("char_3mra01"),
    "3psp01": ui_text("char_3psp01"),
    "4jsk01": ui_text("char_4jsk01"), "4koi01": ui_text("char_4koi01"),
    "4oky01": ui_text("char_4oky01"),     "4kch01": ui_text("char_4kch01"),
    "4rhn01": ui_text("char_4rhn01"),        "4sgc01": ui_text("char_4sgc01"),
    "4fgm01": ui_text("char_4fgm01"),         "4oti01": ui_text("char_4oti01"),
    "4kir01": ui_text("char_4kir01"),       "4kwk01": ui_text("char_4kwk01"),
    "4jtr01": ui_text("char_4jtr01"), "4ykk01": ui_text("char_4ykk01"),
    "5grn01": ui_text("char_5grn01"),      "5mst01": ui_text("char_5mst01"),
    "5fgo01": ui_text("char_5fgo01"),      "5nrc01": ui_text("char_5nrc01"),
    "5bct01": ui_text("char_5bct01"),     "5abc01": ui_text("char_5abc01"),
    "5dvl01": ui_text("char_5dvl01"),              "5gac01": ui_text("char_5gac01"),
    "5prs01": ui_text("char_5prs01"),           "5trs01": ui_text("char_5trs01"),
    "5ris01": ui_text("char_5ris01"),
    "6jln01": ui_text("char_6jln01"),         "6elm01": ui_text("char_6elm01"),
    "6ans01": ui_text("char_6ans01"),       "6pci01": ui_text("char_6pci01"),
    "6pci02": ui_text("char_6pci02"),         "6fit01": ui_text("char_6fit01"),
    "6wet01": ui_text("char_6wet01"),
    "7jny01": ui_text("char_7jny01"),       "7jir01": ui_text("char_7jir01"),
    "7vtn01": ui_text("char_7vtn01"),      "7dio01": ui_text("char_7dio01"),
    "7dio02": ui_text("char_7dio02"),
    "8jsk01": ui_text("char_8jsk01"), "8wou01": ui_text("char_8wou01"),
}

_TYPE_ORDER = [1, 2, 3]  # Battle Start, Round Win, Battle Win


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "..."


def _character_name(code):
    if code not in _CHAR_NAMES or code == '3dio01':
        return _CHAR_NAMES.get(code, code)
    return ui_text('char_' + code)


class SpeakingEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t             = t or (lambda k, **kw: k)
        self._embedded      = embedded
        self._filepath      = None
        self._original_data = None
        self._version       = 1000
        self._entries:      list[dict] = []
        self._orig_entries: list[dict] = []
        self._dirty         = False
        self._selected_pair: tuple[str, str] | None = None
        self._pair_buttons:  list[tuple[QPushButton, str, str]] = []
        self._last_compact: bool | None = None
        self._fields = {}
        self._texts = MessageText()
        self._pair_search = {}
        self._rebuilding = False
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._on_save(target_path=path))
        install_editor_chrome(self)

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        # Toolbar
        top = EditorToolbar()
        top_layout = top.content_layout

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_open.setProperty("designAction", 'open')
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._on_save)
        top_layout.addWidget(self._btn_save)

        self._file_lbl = QLabel(ui_text("xfa_no_file"))

        configure_file_label(self._file_lbl)
        top_layout.addWidget(self._file_lbl)
        top_layout.addStretch()

        root.addWidget(top)

        # Separator
        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Left sidebar
        list_frame = EditorSidebar()


        list_vlayout = list_frame.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search)
        self._type_filter = EditorFilterCombo()
        self._type_filter.addItem(ui_text('dialogue_filter_type'), None)
        for value in _TYPE_ORDER:
            self._type_filter.addItem(self._type_name(value), value)
        self._type_filter.currentIndexChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._type_filter)

        actions_frame = EditorActionRow()

        actions_layout = actions_frame.content_layout


        self._btn_add = QPushButton(ui_text("ui_messageinfo_add"))
        self._btn_add.setEnabled(False)
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_add.setProperty("designAction", 'new')
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(ui_text("btn_dup_short"))
        self._btn_dup.setEnabled(False)
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.clicked.connect(self._on_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setEnabled(False)
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_del, 1)

        list_vlayout.addWidget(actions_frame)

        self._pair_scroll = QScrollArea()


        configure_scrollarea(self._pair_scroll, transparent=True)
        self._pair_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pair_list_widget = QWidget()
        self._pair_list_widget.setMinimumWidth(0)
        self._pair_list_widget.setStyleSheet(ss_transparent())
        self._pair_list_layout = QVBoxLayout(self._pair_list_widget)
        configure_layout(self._pair_list_layout, LayoutRole.LIST)
        self._pair_list_layout.addStretch()
        self._pair_scroll.setWidget(self._pair_list_widget)
        list_vlayout.addWidget(self._pair_scroll)

        main_layout.addWidget(list_frame)

        # Thin vertical divider
        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        # Right editor panel
        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)

        self._show_placeholder(ui_text("ui_speaking_open_a_file_to_get_started"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # Placeholder

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        title = ui_text("no_file_loaded") if self._filepath is None else ui_text("ui_model_viewer_select_item")
        card = make_empty_state(
            self._editor_widget,
            title=title,
            text=text,
            icon_name="fa6s.comments",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    # Pair list

    def _get_pairs(self) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        result: list[tuple[str, str]] = []
        for e in self._entries:
            key = (e["char1"], e["char2"])
            if key not in seen:
                seen.add(key)
                result.append(key)
        return result

    def _entries_for_pair(self, c1: str, c2: str) -> list[tuple[int, dict]]:
        return [(i, e) for i, e in enumerate(self._entries)
                if e["char1"] == c1 and e["char2"] == c2]

    def _populate_list(self, select: tuple[str, str] | None = None):
        self._rebuild_pair_buttons()
        pairs = self._get_pairs()

        if not pairs:
            self._selected_pair = None
            self._btn_dup.setEnabled(False)
            self._btn_del.setEnabled(False)
            self._show_placeholder(ui_text("ui_speaking_no_interactions_press_add_to_create_one"))
            return

        target = select if (select and select in pairs) else pairs[0]
        self._select_pair(*target)
        self._filter_list()

    def _rebuild_pair_buttons(self):
        _clear_layout(self._pair_list_layout)
        self._pair_buttons = []
        self._pair_search = {}
        self._pair_list_layout.addStretch()

        pairs = self._get_pairs()
        for c1, c2 in pairs:
            btn = self._make_pair_button(c1, c2)
            self._pair_list_layout.insertWidget(
                self._pair_list_layout.count() - 1, btn
            )
            self._pair_buttons.append((btn, c1, c2))

    def _make_pair_button(self, c1: str, c2: str) -> QPushButton:
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        n1 = _character_name(c1)
        n2 = _character_name(c2)

        pair_text = ui_text("ui_speaking_value_vs_value", p0=n1, p1=n2)
        pair_lbl = btn.add_title(_truncate(pair_text, 24))


        pair_lbl.setToolTip(pair_text)


        id_text = ui_text("ui_sound_value_value_2", p0=c1, p1=c2)
        id_lbl = btn.add_subtitle(_truncate(id_text, 28), value_font=mono_font(TypeSize.CODE))


        id_lbl.setToolTip(id_text)


        btn.clicked.connect(
            lambda checked=False, _c1=c1, _c2=c2: self._select_pair(_c1, _c2)
        )
        entries = self._entries_for_pair(c1, c2)
        parts = [c1, c2, n1, n2]
        for _, entry in entries:
            parts.append(self._type_name(entry['interaction_type']))
            for key in ('dialogue1', 'dialogue2'):
                value = entry[key]
                result = self._texts.resolve(value)
                parts.extend((value, result.description() if result else ''))
        self._pair_search[(c1, c2)] = '\n'.join(parts).casefold()
        btn.setToolTip('\n'.join(parts))
        return btn

    def _filter_list(self):
        query = self._search.text().casefold().strip()
        itype = self._type_filter.currentData()
        for btn, c1, c2 in self._pair_buttons:
            match = query in self._pair_search.get((c1, c2), '')
            if itype is not None:
                match = match and any(e['interaction_type'] == itype for _, e in self._entries_for_pair(c1, c2))
            btn.setVisible(match)

    def _select_pair(self, c1: str, c2: str):
        old = self._selected_pair
        if not self._flush_characters():
            return
        if old == (c1, c2) and self._selected_pair != old:
            c1, c2 = self._selected_pair
        self._selected_pair = (c1, c2)
        for btn, bc1, bc2 in self._pair_buttons:
            selected = (bc1 == c1 and bc2 == c2)
            btn.setStyleSheet(ss_sidebar_btn(selected=selected))
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        self._build_editor(c1, c2)

    @staticmethod
    def _type_name(value):
        return ui_text('dialogue_type_' + str(value)) if value in _TYPE_ORDER else ui_text('duel_unknown_type', value=value)

    def _flush_characters(self):
        if not self._selected_pair or 'char1' not in self._fields:
            return True
        pair = tuple(self._fields[key].text() for key in ('char1', 'char2'))
        if any(not code or '\x00' in code for code in pair):
            QMessageBox.warning(self, ui_text('dlg_title_error'), ui_text('dialogue_invalid_character'))
            return False
        if pair != self._selected_pair:
            for _, entry in self._entries_for_pair(*self._selected_pair):
                entry['char1'], entry['char2'] = pair
            self._selected_pair = pair
            self._mark_dirty()
            self._rebuild_pair_buttons()
            for btn, c1, c2 in self._pair_buttons:
                btn.set_selected((c1, c2) == pair)
            self._filter_list()
        return True

    # Editor

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT

    def _grid_columns(self, max_columns: int) -> int:
        width = self._editor_scroll.viewport().width()
        if width < Size.COMPACT_BREAKPOINT:
            return 1
        if width < 1080:
            return min(2, max_columns)
        return max_columns

    def _prep_card(self, card: QFrame):
        configure_card(card)
        return card

    def _prep_field_widget(self, widget: QWidget):
        configure_field(widget)
        return widget

    def _add_editor_card(self, card: QFrame):
        self._editor_layout.addWidget(card)

    def _field_position(self, index: int, columns: int) -> tuple[int, int]:
        return divmod(index, max(1, columns))

    def _make_text_field(self, label_text: str, value: str, *, font=None, accent=False, height=Size.CONTROL):
        frame, layout, _label, _hint = make_editor_field_shell(label_text)
        self._prep_field_widget(frame)
        edit = QLineEdit(value)
        configure_input(edit, height=height, monospace=True, font=font)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setCursorPosition(0)
        if accent:
            _label.setStyleSheet(ss_accent_label())
        layout.addWidget(edit)
        return frame, edit

    def _build_editor(self, c1: str, c2: str):
        self._rebuilding = True
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._last_compact = self._is_compact_editor()
        columns = self._grid_columns(2)

        pair_entries = self._entries_for_pair(c1, c2)

        # Character header
        hdr, hdr_grid = make_editor_grid_card(self._editor_widget, title=ui_text('ui_speaking_value_vs_value', p0=_character_name(c1), p1=_character_name(c2)), icon_name='fa6s.comments', subtitle=ui_text('dialogue_pair_help'))
        self._prep_card(hdr)

        for col, (field, code, label_text) in enumerate([
            ("char1", c1, ui_text("ui_speaking_character_1")),
            ("char2", c2, ui_text("ui_speaking_character_2")),
        ]):
            frame, edit = self._make_text_field(
                label_text, code,
                font=mono_font(TypeSize.LARGE),
                accent=True,
                height=Size.LARGE_CONTROL,
            )

            self._fields[field] = edit
            edit.setObjectName('dialogue_' + field)
            edit.textChanged.connect(self._mark_dirty)
            completer = QCompleter(sorted(set(_CHAR_NAMES) | {e[field] for e in self._entries}), edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            edit.setCompleter(completer)

            row, mapped_col = self._field_position(col, columns)
            hdr_grid.addWidget(frame, row, mapped_col)
            hdr_grid.setColumnStretch(mapped_col, 1)

        self._add_editor_card(hdr)

        # Three dialogue cards
        types = list(dict.fromkeys((*_TYPE_ORDER, *(e['interaction_type'] for _, e in pair_entries))))
        for itype in types:
            type_name = self._type_name(itype)

            typed = [(i, e) for i, e in pair_entries if e["interaction_type"] == itype]

            card, card_grid = make_editor_grid_card(self._editor_widget, title=type_name, icon_name='fa6s.quote-left')
            self._prep_card(card)

            if not typed:
                empty_lbl = QLabel(ui_text("ui_speaking_no_entry_for_this_interaction_type"))
                empty_lbl.setFont(ui_font(TypeSize.CODE))
                empty_lbl.setStyleSheet(ss_dim_label())
                empty_lbl.setMinimumWidth(0)
                empty_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                card_grid.addWidget(empty_lbl, 0, 0)

                add_btn = QPushButton(ui_text("ui_speaking_add_entry"))
                configure_button(add_btn, height=Size.COMPACT_CONTROL)
                add_btn.clicked.connect(
                    lambda checked=False, _c1=c1, _c2=c2, _itype=itype:
                        self._add_type_entry(_c1, _c2, _itype)
                )
                add_btn.setProperty("designAction", 'new')
                card_grid.addWidget(add_btn, 1, 0, 1, columns, Qt.AlignmentFlag.AlignLeft)
            else:
                for row_idx, (entry_idx, entry) in enumerate(typed):
                    base_row = row_idx * (3 if columns == 1 else 2)
                    for col_idx, (dkey, dlabel) in enumerate([
                        ("dialogue1", ui_text("ui_speaking_dialogue_1")),
                        ("dialogue2", ui_text("ui_speaking_dialogue_2")),
                    ]):
                        f, edit = self._make_text_field(dlabel, entry[dkey])
                        self._fields[(entry_idx, dkey)] = edit
                        edit.setObjectName(f'dialogue_{entry_idx}_{dkey}')
                        f.layout().addWidget(MessagePreview(edit, self._texts, f))
                        edit.textChanged.connect(
                            lambda text, _idx=entry_idx, _key=dkey:
                                self._update_entry_field(_idx, _key, text)
                        )

                        row, mapped_col = base_row + col_idx // columns, col_idx % columns
                        card_grid.addWidget(f, row, mapped_col)
                        card_grid.setColumnStretch(mapped_col, 1)
                    controls = EditorActionRow()
                    flag_frame, flag_layout, _, _ = make_editor_field_shell(ui_text('dialogue_flag'))
                    flag_frame.setMaximumWidth(240)
                    flag = configure_input(QComboBox(), monospace=False)
                    for value in dict.fromkeys((0, 1, entry['is_round_win'])):
                        flag.addItem(str(value), value)
                    flag.setCurrentIndex(flag.findData(entry['is_round_win']))
                    flag.setToolTip(ui_text('dialogue_flag_help'))
                    flag.currentIndexChanged.connect(lambda _, idx=entry_idx, combo=flag: self._update_entry_field(idx, 'is_round_win', combo.currentData()))
                    self._fields[(entry_idx, 'is_round_win')] = flag
                    flag_layout.addWidget(flag)
                    controls.content_layout.addWidget(flag_frame)
                    controls.content_layout.addStretch()
                    remove = configure_button(QPushButton(ui_text('btn_delete')), danger=True, height=Size.COMPACT_CONTROL)
                    remove.clicked.connect(lambda _, idx=entry_idx: self._delete_entry(idx))
                    controls.content_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignBottom)
                    card_grid.addWidget(controls, base_row + (2 if columns == 1 else 1), 0, 1, columns)
                add_btn = configure_button(QPushButton(ui_text('ui_speaking_add_entry')), height=Size.COMPACT_CONTROL)
                add_btn.clicked.connect(lambda _, value=itype: self._add_type_entry(c1, c2, value))
                card_grid.addWidget(add_btn, len(typed) * (3 if columns == 1 else 2), 0, 1, columns, Qt.AlignmentFlag.AlignLeft)

            self._add_editor_card(card)

        self._editor_layout.addStretch()
        self._rebuilding = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._selected_pair is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._selected_pair is None or self._rebuilding:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        pending = {key: (self._fields[key].text(), self._fields[key].cursorPosition())
                   for key in ('char1', 'char2') if key in self._fields}
        self._build_editor(*self._selected_pair)
        for key, (text, cursor) in pending.items():
            self._fields[key].setText(text)
            self._fields[key].setCursorPosition(cursor)

    # Field update helpers

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(True)
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _update_entry_field(self, idx: int, key: str, value: str):
        if 0 <= idx < len(self._entries) and self._entries[idx].get(key) != value:
            self._entries[idx][key] = value
            self._mark_dirty()
            pair = (self._entries[idx]['char1'], self._entries[idx]['char2'])
            parts = [*pair, *(_character_name(c) for c in pair)]
            for _, entry in self._entries_for_pair(*pair):
                parts.append(self._type_name(entry['interaction_type']))
                for dkey in ('dialogue1', 'dialogue2'):
                    result = self._texts.resolve(entry[dkey])
                    parts.extend((entry[dkey], result.description() if result else ''))
            self._pair_search[pair] = '\n'.join(parts).casefold()
            self._filter_list()

    def _add_type_entry(self, c1: str, c2: str, itype: int):
        """Add a new entry for the given interaction type to the current pair."""
        if not self._flush_characters():
            return
        c1, c2 = self._selected_pair or (c1, c2)
        new_e = {
            "interaction_type": itype,
            "is_round_win": int(itype == 2),
            "char1": c1, "char2": c2,
            "dialogue1": "", "dialogue2": "",
        }
        self._entries.append(new_e)
        self._orig_entries.append(dict(new_e))
        self._mark_dirty()
        self._build_editor(c1, c2)

    def _delete_entry(self, idx):
        if not self._flush_characters():
            return
        if QMessageBox.question(self, ui_text('ui_speaking_delete_interaction'), ui_text('dialogue_delete_entry'),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        del self._entries[idx]
        self._fields = {}
        self._mark_dirty()
        self._populate_list(select=self._selected_pair)

    # CRUD

    def _on_add(self):
        if self._original_data is None or not self._flush_characters():
            return
        new_c1, new_c2 = self._new_pair()
        for itype in _TYPE_ORDER:
            e = {
                "interaction_type": itype,
                "is_round_win": int(itype == 2),
                "char1": new_c1, "char2": new_c2,
                "dialogue1": "", "dialogue2": "",
            }
            self._entries.append(e)
            self._orig_entries.append(dict(e))
        self._mark_dirty()
        self._fields = {}
        self._populate_list(select=(new_c1, new_c2))

    def _new_pair(self):
        pairs = set(self._get_pairs())
        index = 1
        while True:
            code = 'new_chr' if index == 1 else f'new_chr_{index}'
            if (code, code) not in pairs:
                return code, code
            index += 1

    def _on_dup(self):
        if not self._selected_pair or not self._flush_characters():
            return
        c1, c2 = self._selected_pair
        pair_entries = self._entries_for_pair(c1, c2)
        if not pair_entries:
            return
        new_c1, new_c2 = self._new_pair()
        for _, e in pair_entries:
            new_e = dict(e)
            new_e["char1"] = new_c1
            new_e["char2"] = new_c2
            self._entries.append(new_e)
            self._orig_entries.append(dict(new_e))
        self._mark_dirty()
        self._fields = {}
        self._populate_list(select=(new_c1, new_c2))

    def _on_delete(self):
        if not self._selected_pair or not self._flush_characters():
            return
        c1, c2 = self._selected_pair
        n1 = _character_name(c1)
        n2 = _character_name(c2)
        reply = QMessageBox.question(
            self, ui_text("ui_speaking_delete_interaction"),
            ui_text("ui_speaking_delete_all_entries_for_value_vs_value_value_valu", p0=n1, p1=n2, p2=c1, p3=c2),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        to_remove = sorted(
            [i for i, e in enumerate(self._entries)
             if e["char1"] == c1 and e["char2"] == c2],
            reverse=True,
        )
        for i in to_remove:
            del self._entries[i]
            if i < len(self._orig_entries):
                del self._orig_entries[i]
        self._mark_dirty()
        self._selected_pair = None
        self._fields = {}
        self._populate_list()

    # File I/O

    def _load_file(self, filepath: str):
        try:
            data, version, entries = parse_speaking_xfbin(filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=exc))
            return

        if self._dirty and QMessageBox.question(
            self, ui_text('unsaved_changes_title'), ui_text('dialogue_discard'),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Discard:
            return
        create_backup_on_open(filepath)

        self._filepath      = filepath
        self._original_data = data
        self._version       = version
        self._entries       = entries
        self._orig_entries  = [dict(e) for e in entries]
        self._dirty         = False
        self._selected_pair = None
        self._fields = {}
        self._texts = MessageText(filepath, current_language(), load_settings().get('game_files_dir', ''))
        self._type_filter.blockSignals(True)
        self._type_filter.clear()
        self._type_filter.addItem(ui_text('dialogue_filter_type'), None)
        for value in dict.fromkeys((*_TYPE_ORDER, *(e['interaction_type'] for e in entries))):
            self._type_filter.addItem(self._type_name(value), value)
        self._type_filter.blockSignals(False)

        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)

        self._populate_list()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_speaking_open_speakinglineparam_bin_xfbin"), game_files_dialog_dir(target_patterns="SpeakingLineParam.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)",
        )
        if path:
            self._load_file(path)

    def _on_save(self, target_path=None):
        if self._original_data is None or not self._flush_characters():
            return
        save_path = target_path or editor_path(self)
        if not save_path:
            return
        try:
            save_speaking_xfbin(save_path, self._original_data, self._version, self._entries)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('ui_customcardparam_failed_to_save_file_value', p0=exc))
            return
        commit_save_path(self, save_path)
        self._dirty = False
        try:
            self._original_data, self._version, saved = parse_speaking_xfbin(save_path)
            self._orig_entries = [dict(e) for e in saved]
        except Exception:
            self._orig_entries = [dict(e) for e in self._entries]
        set_file_label(self._file_lbl, save_path)
        QMessageBox.information(self, ui_text('ui_assist_saved'), ui_text('ui_assist_file_saved_value', p0=save_path))
