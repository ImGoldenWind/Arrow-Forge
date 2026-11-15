"""Guide events, named UI characters and four localized dialogue variants."""

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
    ss_input_validation,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorFilterCombo,
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
from core.guide_tools import character_label, event_label, unique_event
from core.ui.message_preview import MessagePreview, message_lookup
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox,
    QScrollArea, QSizePolicy, QCompleter,
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QSignalBlocker

from core.editor_file_state import set_file_label
from parsers.guidecharparam_parser import (
    parse_guidecharparam_xfbin,
    save_guidecharparam_xfbin,
    make_default_entry,
    KNOWN_CHARACTERS,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir
class GuideCharParamEditor(QWidget):
    """Embedded editor for GuideCharParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._dirty = False
        self._loading_detail = False
        self._filter_text = ""
        self._visible_indices: list[int] = []
        self._current_idx: int = -1
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._detail_widgets: dict = {}
        self._last_compact: bool | None = None
        self._previews = []

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._on_save(target_path=path))
        install_editor_chrome(self)

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        root.addWidget(self._build_top_bar())

        sep = EditorSeparator(accent=True)

        root.addWidget(sep)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        main_layout.addWidget(self._build_sidebar())

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
        self._editor_scroll.viewport().installEventFilter(self)
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)

        self._show_placeholder(ui_text("ui_guidecharparam_open_a_guidecharparam_bin_xfbin_file_to_begin_editing"))
        self.setStyleSheet(ss_bg_dark())

    def _build_top_bar(self) -> QFrame:
        bar = EditorToolbar()

        layout = bar.content_layout

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_open.setProperty("designAction", 'open')
        layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._on_save)
        layout.addWidget(self._btn_save)

        self._lbl_file = QLabel(ui_text("xfa_no_file"))

        configure_file_label(self._lbl_file)
        layout.addWidget(self._lbl_file)
        layout.addStretch()

        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = EditorSidebar()

        layout = sidebar.content_layout

        self._search_box = QLineEdit()
        configure_search(self._search_box)
        self._search_box.textChanged.connect(self._on_filter_changed)
        self._search_box.setToolTip(ui_text("guide_search_hint"))
        layout.addWidget(self._search_box)

        self._character_filter = EditorFilterCombo()
        self._character_filter.addItem(ui_text("guide_character_filter"), None)
        self._character_filter.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._character_filter)

        btn_row = EditorActionRow()

        btn_layout = btn_row.content_layout

        self._btn_add = QPushButton(ui_text("btn_new"))
        self._btn_add.setEnabled(False)
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_add.setProperty("designAction", 'new')
        btn_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(ui_text("btn_duplicate"))
        self._btn_dup.setEnabled(False)
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.clicked.connect(self._on_duplicate)
        self._btn_dup.setProperty("designAction", 'duplicate')
        btn_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setEnabled(False)
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_del.setProperty("designAction", 'delete')
        btn_layout.addWidget(self._btn_del, 1)

        layout.addWidget(btn_row)

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
        layout.addWidget(self._list_scroll)

        return sidebar

    # Placeholder / editor clear

    def _show_placeholder(self, text=None):
        text = text or ui_text("ui_dictionaryparam_select_an_entry_to_edit")
        self._clear_editor()
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("guide_select_event" if self._raw is not None else "no_file_loaded"),
            text=text,
            icon_name="fa6s.book-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _clear_editor(self):
        self._detail_widgets = {}
        self._previews = []
        self._last_compact = None
        while self._editor_layout.count():
            item = self._editor_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    # List management

    def _refresh_filters(self):
        current = self._character_filter.currentData()
        with QSignalBlocker(self._character_filter):
            self._character_filter.clear()
            self._character_filter.addItem(ui_text("guide_character_filter"), None)
            values = sorted({e.get("character", "") for e in self._entries}, key=character_label)
            for value in values:
                self._character_filter.addItem(character_label(value) or ui_text("guide_empty_character"), value)
            self._character_filter.setCurrentIndex(max(0, self._character_filter.findData(current)))
        reset = getattr(self._search_box, '_design_filter_reset', None)
        if reset:
            reset.refresh()

    def _matches(self, entry, lookup):
        selected = self._character_filter.currentData()
        if selected is not None and entry.get("character", "") != selected:
            return False
        parts = [event_label(entry.get("event", "")), character_label(entry.get("character", ""))]
        parts.extend(str(v) for k, v in entry.items() if not k.startswith('_'))
        for i in range(4):
            for key in (f"msg{i}_name", f"msg{i}_string"):
                parts.append(lookup.text(entry.get(key, ""))[0])
        haystack = " ".join(parts).casefold()
        return all(word in haystack for word in self._filter_text.casefold().split())

    def _rebuild_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._visible_indices = []
        self._entry_buttons = []
        lookup = message_lookup(self)
        for i, entry in enumerate(self._entries):
            if not self._matches(entry, lookup):
                continue
            self._visible_indices.append(i)
            btn = EditorListRow()
            btn.set_selected(i == self._current_idx)
            self._set_row_text(btn, entry)
            btn.clicked.connect(lambda checked=False, index=i: self._select_entry(index))
            self._list_layout.insertWidget(self._list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, i))
        if not self._visible_indices:
            label = QLabel(ui_text("guide_no_matches" if self._entries else "guide_no_events"))
            label.setWordWrap(True)
            label.setFont(ui_font(TypeSize.BODY))
            label.setStyleSheet(ss_dim_label())
            self._list_layout.insertWidget(0, label)

    def _set_row_text(self, button, entry):
        event = entry.get("event", "")
        character = entry.get("character", "")
        button.set_texts(event_label(event), character_label(character), title_limit=27, subtitle_limit=29)
        button.title_label.setTextFormat(Qt.TextFormat.PlainText)
        button.subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        button.setToolTip("\n".join((event_label(event), event, character_label(character), character)))
        button.setAccessibleName(" · ".join((event_label(event), event, character_label(character))))

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries):
            return
        if not self._apply_current_entry(mark_dirty=False):
            return
        self._current_idx = idx
        for button, index in self._entry_buttons:
            button.set_selected(index == idx)
            if index == idx:
                self._list_scroll.ensureWidgetVisible(button)
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        self._build_editor(self._entries[idx])
        self._editor_scroll.verticalScrollBar().setValue(0)

    def _on_filter_changed(self):
        self._filter_text = self._search_box.text()
        self._rebuild_list()
        # Filtering leaves the current form intact, including unfinished input.

    # Editor building

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT

    def _add_card(self, title, icon="fa6s.sliders", subtitle=None):
        card, grid = make_editor_grid_card(self._editor_widget, title=title,
                                          icon_name=icon, subtitle=subtitle)
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        self._editor_layout.addWidget(card)
        return grid

    def _add_field(self, grid, row, col, label, value, key, *, hint="", choices=None, preview=False, span=1):
        shell, layout, caption, _ = make_editor_field_shell(label, hint)
        configure_field(shell, vertical_policy=QSizePolicy.Policy.Preferred)
        if choices is not None:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            configure_input(combo)
            combo.setMinimumContentsLength(1)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            for ident, name in choices:
                combo.addItem(f"{name} · {ident}" if name != ident else ident, ident)
            combo.setEditText(str(value))
            combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
            combo.activated.connect(lambda index, c=combo: c.setEditText(c.itemData(index)))
            edit = combo.lineEdit()
            # The ID is kept in the editable text, independently of the chosen label.
            layout.addWidget(combo)
            configure_field(shell, combo, vertical_policy=QSizePolicy.Policy.Preferred)
        else:
            edit = configure_input(QLineEdit(str(value)), monospace=True)
            layout.addWidget(edit)
            configure_field(shell, edit, vertical_policy=QSizePolicy.Policy.Preferred)
        edit.setCursorPosition(0)
        edit.setAccessibleName(label)
        edit.setToolTip(hint)
        caption.setBuddy(edit)
        if preview:
            resolved = MessagePreview(edit, message_lookup(self), shell)
            layout.addWidget(resolved)
            self._previews.append(resolved)
        grid.addWidget(shell, row, col, 1, span)
        grid.setColumnStretch(col, 1)
        self._detail_widgets[key] = edit
        edit.textChanged.connect(self._save_current_entry)
        if key == 'character':
            edit.editingFinished.connect(self._refresh_filters)
        return edit

    def _build_editor(self, entry, pending=None):
        self._loading_detail = True
        self._clear_editor()
        self._last_compact = self._is_compact_editor()
        compact = self._last_compact
        grid = self._add_card(ui_text("skill_section_identity"), "fa6s.id-card")
        event = self._add_field(grid, 0, 0, ui_text("ui_guidecharparam_event_id"), entry.get("event", ""),
                                "event", hint=ui_text("guide_event_hint"))
        completer = QCompleter(sorted({e.get('event', '') for e in self._entries}), event)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        event.setCompleter(completer)
        self._event_caption = QLabel(event_label(event.text()))
        self._event_caption.setTextFormat(Qt.TextFormat.PlainText)
        self._event_caption.setWordWrap(True)
        self._event_caption.setFont(ui_font(TypeSize.BODY))
        self._event_caption.setStyleSheet(ss_dim_label())
        grid.addWidget(self._event_caption, 1, 0)
        characters = sorted(set(KNOWN_CHARACTERS) | {e.get('character', '') for e in self._entries})
        character = self._add_field(grid, 2 if compact else 0, 0 if compact else 1,
                                    ui_text("guide_character"), entry.get('character', ''), 'character',
                                    choices=[(v, character_label(v)) for v in characters],
                                    hint=ui_text("guide_character_hint"))
        self._guide_caption = QLabel(character_label(character.text()))
        self._guide_caption.setTextFormat(Qt.TextFormat.PlainText)
        self._guide_caption.setFont(ui_font(TypeSize.BODY))
        self._guide_caption.setStyleSheet(ss_dim_label())
        self._guide_caption.setWordWrap(True)
        grid.addWidget(self._guide_caption, 3 if compact else 1, 0 if compact else 1)
        self._diagnostic = QLabel()
        self._diagnostic.setWordWrap(True)
        self._diagnostic.setTextFormat(Qt.TextFormat.PlainText)
        self._diagnostic.setFont(ui_font(TypeSize.HINT))
        self._diagnostic.setStyleSheet(ss_dim_label())
        grid.addWidget(self._diagnostic, 4 if compact else 2, 0, 1, 1 if compact else 2)

        lookup = message_lookup(self)
        speakers = sorted({e.get(f'msg{i}_name', '') for e in self._entries for i in range(4)} - {''})
        speaker_choices = [('', ui_text('guide_empty_speaker'))] + [(v, lookup.text(v)[0] or v) for v in speakers]
        messages = sorted({e.get(f'msg{i}_string', '') for e in self._entries for i in range(4)} - {''})
        for i in range(4):
            grid = self._add_card(ui_text("guide_variant", index=i + 1), "fa6s.comment",
                                  ui_text("guide_variants_hint") if i == 0 else None)
            self._add_field(grid, 0, 0, ui_text("guide_speaker"), entry.get(f'msg{i}_name', ''),
                            f'msg{i}_name', choices=speaker_choices, preview=True)
            edit = self._add_field(grid, 1 if compact else 0, 0 if compact else 1,
                                   ui_text("ui_guidecharparam_message_id"), entry.get(f'msg{i}_string', ''),
                                   f'msg{i}_string', preview=True)
            complete = QCompleter(messages, edit)
            complete.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            edit.setCompleter(complete)

        grid = self._add_card(ui_text('guide_behavior'), subtitle=ui_text('guide_behavior_hint'))
        for i, offset in enumerate((0x50, 0x54, 0x58)):
            key = f'raw_{offset:02x}'
            self._add_field(grid, i if compact else i // 2, 0 if compact else i % 2,
                            ui_text('guide_' + key), str(entry.get(key, 0)), key,
                            hint=ui_text('guide_' + key + '_hint'))
        self._editor_layout.addStretch()
        if pending:
            for key, value in pending.items():
                if key in self._detail_widgets:
                    self._detail_widgets[key].setText(value)
        self._loading_detail = False
        if pending:
            self._apply_current_entry(mark_dirty=False)
        else:
            self._update_diagnostics()
        QTimer.singleShot(0, self._fit_editor_page)

    def _fit_editor_page(self):
        from core.ui.editor_widgets import fit_scroll_page
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx < 0 or self._last_compact is None:
            return
        if self._is_compact_editor() != self._last_compact:
            pending = {key: w.text() for key, w in self._detail_widgets.items()}
            position = self._editor_scroll.verticalScrollBar().value()
            self._build_editor(self._entries[self._current_idx], pending)
            self._editor_scroll.verticalScrollBar().setValue(position)
        self._fit_editor_page()

    def _update_diagnostics(self, error=""):
        if not self._detail_widgets or not hasattr(self, '_diagnostic'):
            return
        event = self._detail_widgets['event'].text()
        self._event_caption.setText(event_label(event))
        character = self._detail_widgets['character'].text()
        self._guide_caption.setText(character_label(character))
        warnings = [error] if error else []
        if any(i != self._current_idx and e.get('event', '') == event for i, e in enumerate(self._entries)):
            warnings.append(ui_text('guide_duplicate_event'))
        if event.startswith('GUIDE_NEW_EVENT_') or '_COPY' in event:
            warnings.append(ui_text('guide_custom_event_hint'))
        seen_empty = False
        entry = self._entries[self._current_idx]
        nulls = entry.get('_null_fields')
        for i in range(4):
            key = f'msg{i}_string'
            text = self._detail_widgets[key].text()
            is_null = not text and (nulls is None or key in nulls or text != entry.get(key))
            if seen_empty and not is_null:
                warnings.append(ui_text('guide_variant_gap'))
                break
            seen_empty = seen_empty or is_null
        self._diagnostic.setText("\n".join(warnings))
        self._diagnostic.setVisible(bool(warnings))

    def _save_current_entry(self):
        if not self._loading_detail:
            if not self._apply_current_entry(mark_dirty=True):
                self._mark_dirty()

    def _apply_current_entry(self, *, mark_dirty):
        if self._current_idx < 0 or self._loading_detail or not self._detail_widgets:
            return True
        values = {}
        error = ""
        invalid = None
        for key, widget in self._detail_widgets.items():
            if key.startswith('raw_'):
                widget.setStyleSheet(ss_input_validation(False))
            value = widget.text()
            try:
                if key.startswith('raw_'):
                    value = int(value.strip(), 16 if value.strip().lower().startswith('0x') else 10)
                    if not 0 <= value <= 0xFFFFFFFF:
                        raise ValueError()
                elif '\x00' in value:
                    raise ValueError()
            except ValueError:
                error = ui_text('guide_invalid_number' if key.startswith('raw_') else 'guide_invalid_id')
                invalid = widget
                if key.startswith('raw_'):
                    widget.setStyleSheet(ss_input_validation(True))
                break
            values[key] = value
        self._update_diagnostics(error)
        if invalid is not None:
            self._invalid_field = invalid
            return False
        self._invalid_field = None
        entry = self._entries[self._current_idx]
        changed = any(entry.get(k) != v for k, v in values.items())
        if '_null_fields' in entry:
            nulls = set(entry['_null_fields'])
            for key, value in values.items():
                if not key.startswith('raw_') and value != entry.get(key):
                    if value:
                        nulls.discard(key)
                    else:
                        nulls.add(key)
            entry['_null_fields'] = tuple(sorted(nulls))
        entry.update(values)
        if changed and mark_dirty:
            self._mark_dirty()
        for button, index in self._entry_buttons:
            if index == self._current_idx:
                self._set_row_text(button, entry)
                break
        return True

    # File operations

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_guidecharparam_open_guidecharparam_bin_xfbin"), game_files_dialog_dir(target_patterns="GuideCharParam.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path):
        create_backup_on_open(path)
        try:
            raw, version, entries = parse_guidecharparam_xfbin(path)
        except Exception as ex:
            QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), str(ex))
            return
        self._filepath    = path
        self._raw         = raw
        self._version     = version
        self._entries     = entries
        self._dirty       = False
        self._current_idx = -1
        set_file_label(self._lbl_file, path)
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(False)
        self._btn_del.setEnabled(False)
        self._clear_editor()
        self._search_box.clear()
        self._refresh_filters()
        self._character_filter.setCurrentIndex(0)
        self._rebuild_list()
        if self._visible_indices:
            self._select_entry(self._visible_indices[0])
        else:
            self._show_placeholder(ui_text("ui_assist_no_entries_found"))

    def _on_save(self, target_path=None):
        if self._raw is None:
            return False
        if not self._apply_current_entry(mark_dirty=False):
            self._invalid_field.setFocus()
            QMessageBox.warning(self, ui_text('ui_assist_save_error'), self._diagnostic.text())
            return False
        save_path = target_path or editor_path(self)
        if not save_path or self._raw is None:
            path, _ = QFileDialog.getSaveFileName(self, ui_text('ui_guidecharparam_save_guidecharparam_bin_xfbin'), ui_text('ui_guidecharparam_guidecharparam_bin_xfbin'), 'XFBIN Files (*.xfbin);;All Files (*)')
            if not path:
                return
            save_path = path
        try:
            save_guidecharparam_xfbin(save_path, self._raw, self._version, self._entries)
            self._raw, self._version, self._entries = parse_guidecharparam_xfbin(save_path)
            commit_save_path(self, save_path)
            self._dirty = False
            set_file_label(self._lbl_file, save_path)
            QMessageBox.information(self, ui_text('ui_assist_saved'), ui_text('ui_charviewer_saved_value_entries_to_value', p0=len(self._entries), p1=save_path))
            return True
        except Exception as ex:
            QMessageBox.critical(self, ui_text('ui_assist_save_error'), str(ex))
            return False

    # Add / Duplicate / Delete

    def _mark_dirty(self):
        self._dirty = True
        if self._filepath:
            set_file_label(self._lbl_file, self._filepath, dirty=True)

    def _on_add(self):
        if self._raw is None or not self._apply_current_entry(mark_dirty=False):
            return
        new_e = make_default_entry(len(self._entries))
        new_e['event'] = unique_event(new_e['event'], self._entries)
        self._entries.append(new_e)
        self._mark_dirty()
        self._reveal_new_entry()
        self._rebuild_list()
        self._select_entry(len(self._entries) - 1)

    def _reveal_new_entry(self):
        self._search_box.clear()
        self._refresh_filters()
        self._character_filter.setCurrentIndex(0)

    def _on_duplicate(self):
        if self._current_idx < 0 or not self._apply_current_entry(mark_dirty=False):
            return
        new_e = copy.deepcopy(self._entries[self._current_idx])
        new_e.pop('_offset', None)
        new_e["event"] = unique_event(new_e["event"] + "_COPY", self._entries)
        insert_at = self._current_idx + 1
        self._entries.insert(insert_at, new_e)
        self._mark_dirty()
        self._reveal_new_entry()
        self._rebuild_list()
        self._select_entry(insert_at)

    def _on_delete(self):
        if self._current_idx < 0 or not self._apply_current_entry(mark_dirty=False):
            return
        e = self._entries[self._current_idx]
        reply = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"),
            ui_text("ui_charviewer_delete_entry_value", p0=e.get('event', self._current_idx)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        old_idx = self._current_idx
        del self._entries[old_idx]
        self._mark_dirty()
        self._current_idx = -1
        self._clear_editor()
        self._refresh_filters()
        self._rebuild_list()
        if self._visible_indices:
            target = next((i for i in self._visible_indices if i >= old_idx), self._visible_indices[-1])
            self._select_entry(target)
        else:
            self._show_placeholder(ui_text("ui_dictionaryparam_select_an_entry_to_edit"))
            self._btn_dup.setEnabled(False)
            self._btn_del.setEnabled(False)
