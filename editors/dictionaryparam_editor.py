"""JoJo glossary workspace. Data semantics live in core.dictionary_tools."""
import copy
import os

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit, QCheckBox,
                             QComboBox, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QFileDialog, QMessageBox, QSizePolicy)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.style_helpers import (make_editor_field_shell, make_editor_grid_card,
    make_empty_state, ss_bg_dark, ss_transparent, ss_check, ss_dim_label,
    ss_input_validation)
from core.ui.editor_widgets import (EditorToolbar, EditorSidebar, EditorActionRow,
    EditorSeparator, EditorListRow, EditorFilterCombo, configure_button,
    configure_card, configure_field, configure_input, configure_file_label,
    configure_layout, configure_search, configure_scrollarea, fit_scroll_page)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import (commit_save_path, editor_path, install_file_actions,
                                    refresh_file_actions)
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper
from core.ui.message_preview import message_lookup
from core.dictionary_tools import (CATEGORY_KEYS, SHARED_GALLERY_KEYS, STRING_KEYS,
    UINT32_MAX, parse_field, category_label, categories, unlock_choices,
    next_identity, panel_catalog, entry_issues, character_catalog,
    stored_caption, stored_hint, stored_choices)
from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.translations import ui_text
from parsers.dictionaryparam_parser import (parse_dictionaryparam_xfbin,
    save_dictionaryparam_xfbin, make_default_entry)


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


class DictionaryParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or ui_text
        self._embedded = embedded
        self._filepath = self._original_data = None
        self._version = 1000
        self._entries = []
        self._current_entry = None
        self._entry_buttons = []
        self._fields, self._captions = {}, {}
        self._grids = []
        self._panels, self._panel_error = {}, ''
        self._characters, self._character_error = frozenset(), ''
        self._search_text = {}
        self._dirty = self._loading_detail = False
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(120)
        self._detail_timer.timeout.connect(self._refresh_diagnostics)
        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=self._on_save)
        install_editor_chrome(self)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())
        top = EditorToolbar()
        open_btn = configure_button(QPushButton(self._t('btn_open_file')), accent=True)
        open_btn.setProperty('designAction', 'open')
        open_btn.clicked.connect(self._on_open)
        self._save_btn = configure_button(QPushButton(self._t('btn_save_file')), accent=True)
        self._save_btn.clicked.connect(lambda: self._on_save())
        self._save_btn.setEnabled(False)
        self._file_lbl = configure_file_label(QLabel(self._t('no_file_loaded')))
        self._file_lbl.setMinimumWidth(0)
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        for widget in (open_btn, self._save_btn):
            top.content_layout.addWidget(widget)
        top.content_layout.addWidget(self._file_lbl, 1)
        root.addWidget(top)
        root.addWidget(EditorSeparator(accent=True))
        main = QWidget()
        body = configure_layout(QHBoxLayout(main), LayoutRole.ROOT)
        sidebar = EditorSidebar(width=290)
        self._search_entry = configure_search(QLineEdit())
        self._search_entry.textChanged.connect(self._filter_list)
        sidebar.content_layout.addWidget(self._search_entry)
        self._category_filter = EditorFilterCombo()
        self._category_filter.addItem(ui_text('dictionary_categories'), None)
        for key in CATEGORY_KEYS:
            self._category_filter.addItem(category_label(key), key)
        self._category_filter.currentIndexChanged.connect(self._filter_list)
        sidebar.content_layout.addWidget(self._category_filter)
        self._unlock_filter = EditorFilterCombo()
        self._unlock_filter.addItem(ui_text('ui_charviewer_unlock_condition'), None)
        self._unlock_filter.currentIndexChanged.connect(self._filter_list)
        sidebar.content_layout.addWidget(self._unlock_filter)
        actions = EditorActionRow()
        for attr, key, callback, action in (
            ('_add_btn', 'btn_new', self._add_new_entry, 'new'),
            ('_dup_btn', 'btn_duplicate', self._duplicate_entry, 'duplicate'),
            ('_del_btn', 'btn_delete', self._delete_entry, 'delete')):
            button = configure_button(QPushButton(self._t(key)),
                danger=action == 'delete', height=Size.COMPACT_CONTROL)
            button.setProperty('designAction', action)
            button.setEnabled(False)
            button.clicked.connect(callback)
            actions.content_layout.addWidget(button, 1)
            setattr(self, attr, button)
        sidebar.content_layout.addWidget(actions)
        self._entry_scroll = configure_scrollarea(QScrollArea(), transparent=True)
        self._entry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setMinimumWidth(0)
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = configure_layout(QVBoxLayout(self._entry_list_widget), LayoutRole.LIST)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        sidebar.content_layout.addWidget(self._entry_scroll, 1)
        body.addWidget(sidebar)
        body.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_widget.setMinimumWidth(0)
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        body.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)
        self._show_placeholder(ui_text('ui_dictionaryparam_open_a_dictionaryparam_xfbin_file_to_begin_editing'))

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        self._fields, self._grids = {}, []
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(self._editor_widget,
            title=ui_text('no_file_loaded') if not self._filepath else ui_text('select_entry'), text=text),
            0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(self,
            ui_text('ui_dictionaryparam_open_dictionaryparam_xfbin'),
            game_files_dialog_dir(target_patterns=('DictionaryParam.xfbin', 'DictionaryParam.bin.xfbin')),
            'XFBIN Files (*.xfbin);;All Files (*.*)')
        if path:
            self._load_file(path)

    def _load_file(self, filepath):
        try:
            raw, version, entries = parse_dictionaryparam_xfbin(filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=exc))
            return False
        if self._dirty:
            reply = QMessageBox.question(self, ui_text('dlg_title_warning'),
                ui_text('term_discard_changes'),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Discard:
                return False
        create_backup_on_open(filepath)
        self._detail_timer.stop()
        self._filepath, self._original_data, self._version = filepath, raw, version
        self._entries = entries
        self._current_entry = None
        self._fields = {}
        self._dirty = False
        self._panels, self._panel_error = panel_catalog(filepath, load_settings().get('game_files_dir', ''))
        self._characters, self._character_error = character_catalog(filepath, load_settings().get('game_files_dir', ''))
        self._search_entry.clear()
        self._category_filter.setCurrentIndex(0)
        self._unlock_filter.setCurrentIndex(0)
        self._refresh_unlock_filter()
        set_file_label(self._file_lbl, filepath)
        self._populate_list()
        if entries:
            self._select_entry(entries[0])
        else:
            self._show_placeholder(ui_text('select_entry'))
        self._update_actions()
        return True

    def _on_save(self, target_path=None):
        path = target_path or editor_path(self)
        if not path or self._original_data is None or not self._apply_fields():
            return False
        try:
            save_dictionaryparam_xfbin(path, self._original_data, self._version, self._entries)
            # Refresh record offsets after structural changes, so later edits patch
            # the newly saved table instead of relying on stale source metadata.
            raw, version, entries = parse_dictionaryparam_xfbin(path)
            for current, saved in zip(self._entries, entries):
                current.update({k: v for k, v in saved.items() if k.startswith('_')})
            self._original_data = raw
            commit_save_path(self, path)
            self._dirty = False
            set_file_label(self._file_lbl, path)
            self._update_actions()
            QMessageBox.information(self, ui_text('dlg_title_success'),
                ui_text('ui_dictionaryparam_saved_to_value', p0=os.path.basename(path)))
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False

    def _refresh_unlock_filter(self):
        selected = self._unlock_filter.currentData()
        self._unlock_filter.blockSignals(True)
        self._unlock_filter.clear()
        self._unlock_filter.addItem(ui_text('ui_charviewer_unlock_condition'), None)
        for value, caption in unlock_choices(self._entries):
            if any(e['no_panel'] == value for e in self._entries):
                self._unlock_filter.addItem(caption, value)
        self._unlock_filter.setCurrentIndex(max(0, self._unlock_filter.findData(selected)))
        self._unlock_filter.blockSignals(False)

    def _entry_title(self, entry):
        return message_lookup(self).text(entry['title'])[0] or entry['title'] or entry['char_id']

    def _refresh_row(self, button, entry):
        title, subtitle = button.findChildren(QLabel)[:2]
        name = self._entry_title(entry).replace('\n', ' ')
        title.setText(name)
        title.setToolTip(name)
        subtitle.setText(entry['char_id'])
        subtitle.setToolTip(entry['char_id'])
        button.setToolTip(name + '\n' + ' · '.join(category_label(k) for k in categories(entry)))
        # Resolve text once per modified row, not on every search keystroke.
        self._search_text[id(entry)] = ' '.join((name, *(str(v) for k, v in entry.items() if not k.startswith('_')),
            message_lookup(self).text(entry['header'])[0],
            *(category_label(k) for k in categories(entry)), self._panels.get(entry['panel'], ''))).casefold()

    def _populate_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons, self._search_text = [], {}
        for entry in self._entries:
            button = EditorListRow()
            button.add_title()
            button.add_subtitle()
            self._refresh_row(button, entry)
            button.clicked.connect(lambda checked=False, e=entry: self._select_entry(e))
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, button)
            self._entry_buttons.append((button, entry))
        self._filter_list()

    def _filter_list(self):
        query = self._search_entry.text().strip().casefold()
        category = self._category_filter.currentData()
        unlock = self._unlock_filter.currentData()
        for button, entry in self._entry_buttons:
            button.setVisible((not query or query in self._search_text.get(id(entry), '')) and
                (category is None or entry[category] != 0) and
                (unlock is None or entry['no_panel'] == unlock))

    def _select_entry(self, entry):
        if not self._apply_fields():
            return False
        self._detail_timer.stop()
        self._current_entry = entry
        for button, candidate in self._entry_buttons:
            button.set_selected(candidate is entry)
        self._build_editor(entry)
        self._update_actions()
        return True

    def _draft(self):
        if self._current_entry is None:
            return {}, []
        values, errors = {}, []
        for key, widget in self._fields.items():
            try:
                if isinstance(widget, QCheckBox):
                    # Preserve noncanonical truthy words unless explicitly toggled.
                    before = self._current_entry[key]
                    value = before if bool(before) == widget.isChecked() else int(widget.isChecked())
                else:
                    value = parse_field(key, widget.value_text() if isinstance(widget, EditorValueCombo) else widget.text())
                values[key] = value
                invalid = False
            except (ValueError, UnicodeError, OverflowError):
                errors.append(key)
                invalid = True
            if not isinstance(widget, QCheckBox) and bool(widget.property('dictionaryInvalid')) != invalid:
                widget.setStyleSheet(ss_input_validation(invalid))
                widget.setProperty('dictionaryInvalid', invalid)
        return values, errors

    def _apply_fields(self, show_errors=True):
        if self._current_entry is None:
            return True
        values, errors = self._draft()
        if errors:
            key = errors[0]
            widget = self._fields[key]
            if show_errors:
                QMessageBox.warning(self, ui_text('dlg_title_warning'),
                    ui_text('dictionary_invalid_field', field=self._captions[key]))
                self._editor_scroll.ensureWidgetVisible(widget)
                widget.setFocus()
            return False
        if all(self._current_entry[key] == value for key, value in values.items()):
            return True
        self._current_entry.update(values)
        for button, entry in self._entry_buttons:
            if entry is self._current_entry:
                self._refresh_row(button, entry)
                break
        self._refresh_unlock_filter()
        self._filter_list()
        return True

    def _card(self, title, icon, columns=2):
        card, grid = make_editor_grid_card(self._editor_widget, title=title, icon_name=icon)
        configure_card(card)
        self._editor_layout.addWidget(card)
        self._grids.append((grid, [], columns))
        return grid

    def _field(self, grid, key, caption, *, choices=None, hint='', step=False):
        if key in CATEGORY_KEYS:
            frame = QWidget()
            layout = configure_layout(QVBoxLayout(frame), LayoutRole.FIELD)
        else:
            frame, layout, _, _ = make_editor_field_shell(caption)
        value = self._current_entry[key]
        if choices is not None:
            widget = EditorValueCombo(choices, value)
            widget.lineEdit().setCursorPosition(0)
            widget.editTextChanged.connect(self._mark_dirty)
        elif key in CATEGORY_KEYS:
            widget = QCheckBox(category_label(key))
            widget.setFont(ui_font(TypeSize.LABEL))
            widget.setStyleSheet(ss_check())
            widget.setChecked(value != 0)
            widget.toggled.connect(self._mark_dirty)
        else:
            widget = configure_input(QLineEdit(str(value)))
            widget.textChanged.connect(self._mark_dirty)
        widget.setProperty('messageReference', key in ('title', 'header', 'availability_message1', 'availability_message2'))
        widget.setProperty('messageTextOnly', key in ('title', 'header'))
        widget.setToolTip(hint)
        widget.setAccessibleName(caption)
        layout.addWidget(IntegerStepper(widget, 0, UINT32_MAX) if step else widget)
        configure_field(frame, widget)
        self._fields[key], self._captions[key] = widget, caption
        next(frames for candidate, frames, _ in self._grids if candidate is grid).append(frame)
        return widget

    def _build_editor(self, entry):
        self._loading_detail = True
        _clear_layout(self._editor_layout)
        self._fields, self._captions, self._grids = {}, {}, []
        grid = self._card(ui_text('dictionary_article'), 'fa6s.book-open', 1)
        self._field(grid, 'title', ui_text('ui_dictionaryparam_title_key'))
        self._field(grid, 'header', ui_text('ui_dictionaryparam_header_key'))
        grid = self._card(ui_text('dictionary_categories'), 'fa6s.layer-group', 3)
        for key in CATEGORY_KEYS:
            self._field(grid, key, category_label(key), hint=ui_text('dictionary_category_hint'))
        grid = self._card(ui_text('dictionary_links'), 'fa6s.link')
        self._field(grid, 'char_id', ui_text('dictionary_lookup_id'), hint=ui_text('dictionary_lookup_hint'))
        self._field(grid, 'index', ui_text('dictionary_save_index'), step=True, hint=ui_text('dictionary_index_hint'))
        panel_ids = sorted(set(self._panels) | {e['panel'] for e in self._entries} | {''})
        self._field(grid, 'panel', ui_text('ui_dictionaryparam_panel'),
            choices=[(key, f'{key} — {self._panels[key]}' if key in self._panels else key) for key in panel_ids],
            hint=ui_text('dictionary_panel_hint'))
        self._field(grid, 'no_panel', ui_text('ui_charviewer_unlock_condition'),
            choices=unlock_choices(self._entries), hint=ui_text('dictionary_unlock_hint'))
        for key, caption in (('dlc_id', ui_text('ui_charviewer_dlc_id')), ('patch', ui_text('ui_dictionaryparam_patch_version'))):
            values = sorted({e[key] for e in self._entries})
            choices = [(v, ui_text('ui_charviewer_base_game') if key == 'dlc_id' and v == 0 else str(v)) for v in values]
            self._field(grid, key, caption, choices=choices, hint=ui_text('dictionary_content_hint'))
        grid = self._card(ui_text('dictionary_saved_values'), 'fa6s.sliders', 3)
        for key in SHARED_GALLERY_KEYS:
            choices = stored_choices(key, self._entries, self._characters)
            self._field(grid, key, stored_caption(key), choices=choices, hint=stored_hint(key),
                        step=choices is None and key not in STRING_KEYS)
        grid = self._card(ui_text('dictionary_connections'), 'fa6s.circle-info', 1)
        self._diagnostics = QLabel()
        self._diagnostics.setFont(ui_font(TypeSize.BODY))
        self._diagnostics.setStyleSheet(ss_dim_label())
        self._diagnostics.setWordWrap(True)
        self._diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self._diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(self._diagnostics)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._reflow()
        self._refresh_diagnostics()
        self._editor_scroll.verticalScrollBar().setValue(0)

    def _reflow(self):
        width = self._editor_scroll.viewport().width()
        for grid, frames, maximum in self._grids:
            if not frames:
                continue
            columns = 1 if width < 760 else min(2 if width < 1060 else 3, maximum)
            for col in range(maximum):
                stretch = int(col < columns)
                if grid.columnStretch(col) != stretch:
                    grid.setColumnStretch(col, stretch)
            for i, frame in enumerate(frames):
                row, col = divmod(i, columns)
                if grid.indexOf(frame) < 0 or grid.getItemPosition(grid.indexOf(frame)) != (row, col, 1, 1):
                    grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _refresh_diagnostics(self):
        if self._current_entry is None or not self._fields:
            return
        values, errors = self._draft()
        if errors:
            self._diagnostics.setText(ui_text('dictionary_pending_input'))
            fit_scroll_page(self._editor_scroll)
            return
        draft = dict(self._current_entry, **values)
        rows = [draft if e is self._current_entry else e for e in self._entries]
        issues = entry_issues(draft, rows, self._panels)
        summary = ' · '.join(category_label(k) for k in categories(draft)) or ui_text('dictionary_no_category')
        panel = self._panels.get(draft['panel'], draft['panel'])
        if panel:
            summary += '\n' + ui_text('dictionary_linked_panel', panel=panel)
        if self._panel_error:
            issues.append(ui_text('dictionary_panel_catalog_error', error=self._panel_error))
        if self._character_error:
            issues.append(ui_text('dictionary_character_catalog_error', error=self._character_error))
        self._diagnostics.setText('\n'.join((summary, *issues)))
        fit_scroll_page(self._editor_scroll)

    def _mark_dirty(self, *_):
        if self._loading_detail:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)
        self._detail_timer.start()
        self._update_actions()

    def _update_actions(self):
        loaded = self._original_data is not None
        selected = self._current_entry is not None
        self._save_btn.setEnabled(loaded)
        self._add_btn.setEnabled(loaded)
        self._dup_btn.setEnabled(loaded and selected)
        self._del_btn.setEnabled(loaded and selected)
        refresh_file_actions(self, loaded=loaded)

    def _add_new_entry(self):
        if self._original_data is None or not self._apply_fields():
            return
        identity = self._allocate_identity()
        if identity is None:
            return
        index, ident = identity
        entry = make_default_entry(index)
        entry['char_id'] = ident
        self._insert_entry(entry)

    def _duplicate_entry(self):
        if self._current_entry is None or not self._apply_fields():
            return
        identity = self._allocate_identity()
        if identity is None:
            return
        entry = copy.deepcopy(self._current_entry)
        entry['index'], entry['char_id'] = identity
        entry.pop('_offset', None)
        self._insert_entry(entry)

    def _allocate_identity(self):
        try:
            return next_identity(self._entries)
        except ValueError:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('dictionary_no_free_index'))
            return None

    def _insert_entry(self, entry):
        self._entries.append(entry)
        self._current_entry = None
        self._fields = {}
        self._search_entry._design_filter_reset.clear()
        self._populate_list()
        self._select_entry(entry)
        self._entry_scroll.ensureWidgetVisible(self._entry_buttons[-1][0])
        self._mark_dirty()

    def _delete_entry(self):
        if self._current_entry is None or not self._apply_fields():
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('msg_cannot_delete_last_entry'))
            return
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'),
            ui_text('ui_dictionaryparam_delete_entry_value_this_cannot_be_undone', p0=self._current_entry['char_id']),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = next(i for i, entry in enumerate(self._entries) if entry is self._current_entry)
        del self._entries[index]
        self._current_entry = None
        self._fields = {}
        self._populate_list()
        self._select_entry(self._entries[min(index, len(self._entries) - 1)])
        self._mark_dirty()
