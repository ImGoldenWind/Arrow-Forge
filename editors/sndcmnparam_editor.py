"""Sound routing catalog with transactional forms and real resource inspection."""
import copy
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QRunnable, QSignalBlocker, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label
from core.record_session import RecordSession
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.soundparam_tools import (
    RELATED_KEYS, asset_inventory, caption, character_name, choices, data_root, display, fields,
    index_assets, issues, make_default, parse_field, related_entry, resource_matches,
)
from core.style_helpers import (
    make_editor_field_shell, make_editor_grid_card, make_empty_state,
    ss_bg_dark, ss_dim_label, ss_input_validation,
)
from core.translations import ui_text
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions, refresh_file_actions
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_widgets import (
    EditorActionRow, EditorFilterCombo, EditorSeparator, EditorSidebar, EditorToolbar,
    configure_button, configure_card, configure_field, configure_file_label,
    configure_input, configure_layout, configure_scrollarea, configure_search, fit_scroll_page,
)
from core.ui.number_input import FloatStepper, IntegerStepper
from core.ui.record_list import EditorRecordList, RecordListModel
from core.ui.value_combo import EditorValueCombo
from parsers.sndcmnparam_parser import SCHEMAS, parse_sndcmnparam_xfbin, save_sndcmnparam_xfbin


class _Signals(QObject):
    done = pyqtSignal(int, str, object, str)


class _LoadJob(QRunnable):
    def __init__(self, token, path, configured):
        super().__init__()
        self.token, self.path, self.configured = token, path, configured
        self.signals = _Signals()

    def run(self):
        try:
            raw, sections = parse_sndcmnparam_xfbin(self.path)
            root = data_root(self.path, self.configured)
            result, error = (raw, sections, root, asset_inventory(root)), ''
        except Exception as exc:
            result, error = None, str(exc)
        self.signals.done.emit(self.token, self.path, result, error)


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear(item.layout())


class SndCmnParamEditor(QWidget):
    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or ui_text
        self._filepath = self._raw = self._current_entry = None
        self._sections, self._sessions, self._fields, self._grids = [], {}, {}, []
        self._current_section_idx = None
        self._dirty = self._busy = self._building = False
        self._generation, self._jobs = 0, {}
        self._root, self._inventory, self._asset_index = None, (), {}
        self._choice_models = {}
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(180)
        self._detail_timer.timeout.connect(self._refresh_catalog)
        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=self._do_save)
        install_editor_chrome(self)
        self._update_actions()

    def _button(self, key, callback, action=None, danger=False, compact=False):
        button = configure_button(QPushButton(ui_text(key)), danger=danger,
            height=Size.COMPACT_CONTROL if compact else Size.CONTROL)
        button.clicked.connect(callback)
        if action:
            button.setProperty('designAction', action)
        return button

    def _label(self, text=''):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_dim_label())
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _build_ui(self):
        self.setStyleSheet(ss_bg_dark())
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        toolbar = EditorToolbar()
        self._open_btn = configure_button(QPushButton(ui_text('btn_open_file')), accent=True)
        self._open_btn.setProperty('designAction', 'open')
        self._open_btn.clicked.connect(self._load_file)
        self._save_btn = configure_button(QPushButton(ui_text('btn_save_file')), accent=True)
        self._save_btn.clicked.connect(self._save_file)
        self._file_lbl = configure_file_label(QLabel(ui_text('no_file_loaded')))
        self._file_lbl.setMinimumWidth(0)
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        for widget in (self._open_btn, self._save_btn):
            toolbar.content_layout.addWidget(widget)
        toolbar.content_layout.addWidget(self._file_lbl, 1)
        root.addWidget(toolbar)
        root.addWidget(EditorSeparator(accent=True))
        self._main = QWidget()
        main = configure_layout(QHBoxLayout(self._main), LayoutRole.ROOT)
        sidebar = EditorSidebar(width=290)
        side = sidebar.content_layout
        self._section_combo = configure_input(QComboBox())
        self._section_combo.setAccessibleName(ui_text('soundparam_section'))
        self._section_combo.setToolTip(ui_text('soundparam_section'))
        self._section_combo.currentIndexChanged.connect(self._section_changed)
        side.addWidget(self._section_combo)
        self._search_entry = configure_search(QLineEdit())
        self._search_entry.textChanged.connect(self._filter_list)
        side.addWidget(self._search_entry)
        self._state_filter = EditorFilterCombo()
        for key in ('all', 'modified', 'empty'):
            self._state_filter.addItem(ui_text('effect_filter_' + key), key)
        self._state_filter.setAccessibleName(ui_text('soundparam_record_filter'))
        self._state_filter.setToolTip(ui_text('soundparam_record_filter'))
        self._state_filter.currentIndexChanged.connect(self._filter_list)
        side.addWidget(self._state_filter)
        actions = EditorActionRow()
        self._add_btn = self._button('btn_new', self._add_entry, 'new', compact=True)
        self._dup_btn = self._button('btn_duplicate', self._duplicate_entry, 'duplicate', compact=True)
        self._del_btn = self._button('btn_delete', self._delete_entry, 'delete', danger=True, compact=True)
        for button in (self._add_btn, self._dup_btn, self._del_btn):
            actions.content_layout.addWidget(button, 1)
        side.addWidget(actions)
        self._catalog_model = RecordListModel(self)
        self._catalog = EditorRecordList(self._catalog_model, self._describe_row)
        self._catalog.setAccessibleName(ui_text('soundparam_catalog'))
        self._catalog.selectionModel().currentRowChanged.connect(self._catalog_selected)
        side.addWidget(self._catalog, 1)
        self._no_matches = self._label(ui_text('ui_sndcmnparam_no_matches'))
        self._no_matches.hide()
        side.addWidget(self._no_matches)
        main.addWidget(sidebar)
        main.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main.addWidget(self._editor_scroll, 1)
        root.addWidget(self._main, 1)
        self._placeholder()

    def _current_section(self):
        i = self._current_section_idx
        return self._sections[i] if i is not None and 0 <= i < len(self._sections) else None

    def _session(self):
        section = self._current_section()
        return self._sessions[id(section)] if section is not None else None

    def _title(self, entry, kind=None):
        kind = kind or self._current_section()['type']
        key = {'sndcmnparam': 'audio_id', 'pldata': 'char_id', 'cridata': 'str0'}[kind]
        value = character_name(entry[key]) if kind == 'pldata' else entry[key]
        return value or ui_text('soundparam_empty_entry')

    def _describe_row(self, index):
        _, entry, i = self._catalog_model.rows[index.row()]
        section = self._current_section()
        mark = '● ' if self._session().modified(entry) else ''
        subtitle = ui_text('soundparam_row', index=i)
        if section['type'] == 'cridata':
            subtitle += ' · ' + entry['str2']
        elif section['type'] == 'pldata':
            subtitle += ' · ' + entry['char_id']
        return mark + self._title(entry), subtitle, '\n'.join(display(entry[k]) for k in fields(section['type']))

    def _sync_selection(self):
        row = next((i for i, r in enumerate(self._catalog_model.rows) if r[1] is self._current_entry), -1)
        self._catalog.setCurrentIndex(self._catalog_model.index(row))

    def _filter_list(self, *_):
        section = self._current_section()
        rows = []
        if section is not None:
            query, state = self._search_entry.text().strip().casefold(), self._state_filter.currentData()
            kind = section['type']
            for i, entry in enumerate(section['entries']):
                if state == 'modified' and not self._session().modified(entry):
                    continue
                if state == 'empty' and self._title(entry) != ui_text('soundparam_empty_entry'):
                    continue
                if query and query not in (' '.join([str(i), self._title(entry),
                        *(display(entry[k]) for k in fields(kind))])).casefold():
                    continue
                rows.append((self._title(entry), entry, i))
        with QSignalBlocker(self._catalog.selectionModel()):
            self._catalog_model.reset_rows(rows)
            self._sync_selection()
        self._no_matches.setVisible(section is not None and not rows)

    def _refresh_catalog(self):
        self._filter_list()
        self._update_actions()

    def _section_changed(self, idx):
        if self._building:
            return
        if not self._select_category(idx):
            with QSignalBlocker(self._section_combo):
                self._section_combo.setCurrentIndex(self._current_section_idx if self._current_section_idx is not None else -1)

    def _select_category(self, idx):
        if self._busy or not 0 <= idx < len(self._sections) or not self._apply_fields():
            return False
        self._detail_timer.stop()
        self._current_section_idx = idx
        self._current_entry, self._fields = None, {}
        with QSignalBlocker(self._section_combo):
            self._section_combo.setCurrentIndex(idx)
        section = self._current_section()
        self._filter_list()
        if section['entries']:
            visible = self._catalog_model.rows
            self._select_entry(visible[0][1] if visible else section['entries'][0])
        else:
            self._placeholder()
        self._update_actions()
        return True

    def _catalog_selected(self, current, previous):
        if current.isValid() and not self._select_entry(self._catalog_model.rows[current.row()][1]):
            with QSignalBlocker(self._catalog.selectionModel()):
                self._sync_selection()

    def _select_entry(self, entry):
        if self._busy or not self._apply_fields():
            return False
        if entry is self._current_entry:
            return True
        self._detail_timer.stop()
        self._current_entry = entry
        with QSignalBlocker(self._catalog.selectionModel()):
            self._sync_selection()
        self._catalog.scrollTo(self._catalog.currentIndex())
        self._build_editor()
        self._editor_scroll.verticalScrollBar().setValue(0)
        self._update_actions()
        return True

    def _placeholder(self):
        self._fields, self._grids = {}, []
        _clear(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(self._editor_widget,
            title=ui_text('soundparam_catalog') if self._raw is not None else ui_text('no_file_loaded'),
            text=ui_text('soundparam_empty_section') if self._raw is not None else ui_text('ui_sndcmnparam_open_a_sndcmnparam_xfbin_file_to_begin_editing'),
            icon_name='fa6s.volume-high'), 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _card(self, title, subtitle=None):
        card, grid = make_editor_grid_card(self._editor_widget, title=title,
            icon_name='fa6s.volume-high', subtitle=subtitle)
        configure_card(card)
        self._editor_layout.addWidget(card)
        self._grids.append((grid, []))
        return grid

    def _add_field(self, key):
        section, entry = self._current_section(), self._current_entry
        kind = section['type']
        frame, layout, label, _ = make_editor_field_shell(caption(key))
        signature = (kind, key)
        options = choices(kind, key, self._sections, self._inventory) if signature not in self._choice_models else ()
        if options is not None:
            if signature not in self._choice_models:
                self._choice_models[signature] = EditorValueCombo.choice_model(options, self)
            edit = EditorValueCombo((), display(entry[key]), model=self._choice_models[signature])
            content = edit
        else:
            edit = configure_input(QLineEdit(display(entry[key])))
            content = IntegerStepper(edit, 0, 65535) if key == 'flag' else FloatStepper(edit, 1)
        edit.setProperty('messageReference', False)
        edit.setAccessibleName(caption(key))
        edit.setToolTip(ui_text('soundparam_hint_' + key))
        label.setBuddy(edit)
        configure_field(frame, edit, vertical_policy=QSizePolicy.Policy.Minimum)
        layout.addWidget(content)
        self._fields[key] = edit
        if isinstance(edit, EditorValueCombo):
            edit.currentTextChanged.connect(self._changed)
        else:
            edit.textChanged.connect(self._changed)
        self._grids[-1][1].append(frame)
        self._grids[-1][0].addWidget(frame, len(self._grids[-1][1]) - 1, 0)

    def _build_editor(self):
        self._building = True
        _clear(self._editor_layout)
        self._fields, self._grids, self._relation_buttons = {}, [], []
        self._relation_actions = None
        section, entry = self._current_section(), self._current_entry
        kind = section['type']
        self._card(ui_text('soundparam_section_' + kind), ui_text('soundparam_scope_' + kind))
        string_keys = [key for _, key, _ in SCHEMAS[kind][1]]
        for key in string_keys:
            self._add_field(key)
        if SCHEMAS[kind][2]:
            self._card(ui_text('soundparam_routing'))
            for _, key, _ in SCHEMAS[kind][2]:
                self._add_field(key)
        grid = self._card(ui_text('soundparam_inspection'))
        self._resource_status = self._label()
        grid.addWidget(self._resource_status, 0, 0)
        if kind == 'pldata':
            actions = EditorActionRow()
            self._relation_actions = actions
            for key in RELATED_KEYS:
                button = self._button('soundparam_jump', lambda _, k=key: self._jump_related(k))
                actions.content_layout.addWidget(button)
                self._relation_buttons.append((key, button))
            grid.addWidget(actions, 1, 0)
        self._diagnostics = self._label()
        grid.addWidget(self._diagnostics, 2, 0)
        self._restore_btn = self._button('font_restore_record', self._restore_entry)
        self._restore_btn.hide()
        grid.addWidget(self._restore_btn, 3, 0, Qt.AlignmentFlag.AlignLeft)
        self._editor_layout.addStretch()
        self._building = False
        self._refresh_detail()
        self._reflow()

    def _text(self, edit):
        return edit.value_text() if isinstance(edit, EditorValueCombo) else edit.text()

    def _draft(self):
        values, errors = {}, []
        if self._current_entry is None:
            return values, errors
        kind = self._current_section()['type']
        for key, edit in self._fields.items():
            try:
                values[key] = parse_field(kind, key, self._text(edit), self._current_entry)
                invalid = False
            except (ValueError, OverflowError, UnicodeError):
                errors.append(key)
                invalid = True
            if edit.property('soundparamInvalid') != invalid:
                edit.setStyleSheet(ss_input_validation(invalid))
                edit.setProperty('soundparamInvalid', invalid)
        return values, errors

    def _apply_fields(self, show_errors=True):
        if self._current_entry is None:
            return True
        values, errors = self._draft()
        if errors:
            if show_errors:
                QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('gallery_invalid', field=caption(errors[0])))
                self._editor_scroll.ensureWidgetVisible(self._fields[errors[0]])
                self._fields[errors[0]].setFocus()
            return False
        self._current_entry.update(values)
        return True

    def _changed(self, *_):
        if self._building:
            return
        self._apply_fields(show_errors=False)
        self._dirty = bool(self._draft()[1]) or any(s.dirty() for s in self._sessions.values())
        self._refresh_detail()
        self._update_actions()
        self._detail_timer.start()

    def _refresh_detail(self):
        if self._current_entry is None:
            return
        entry, section = self._current_entry, self._current_section()
        _, errors = self._draft()
        if errors:
            self._resource_status.setText(ui_text('gallery_pending'))
            self._diagnostics.clear()
        else:
            lines = []
            for _, key, _ in SCHEMAS[section['type']][1]:
                if key in ('char_id', 'audio_id'):
                    continue
                value = entry[key]
                matches = resource_matches(value, self._asset_index)
                if matches:
                    lines.append(caption(key) + ' →\n' + '\n'.join(matches))
                elif value and 'NULL' not in value:
                    lines.append(ui_text('soundparam_resource_missing', field=caption(key), value=value))
            if not self._root:
                lines.insert(0, ui_text('soundparam_resources_missing'))
            self._resource_status.setText('\n\n'.join(lines) or ui_text('soundparam_no_resource_reference'))
            self._diagnostics.setText('\n'.join([ui_text('soundparam_ordinal_warning'), *issues(section, entry)]))
        for key, button in self._relation_buttons:
            target = related_entry(section, entry[key]) if not errors else None
            button.setEnabled(target is not None)
            button.setText(ui_text('soundparam_jump_target', name=character_name(target[1]['char_id']))
                           if target else ui_text('soundparam_jump'))
            button.setToolTip(caption(key))
        original = self._session().original(entry)
        self._restore_btn.setEnabled(original is not None and (bool(errors) or self._session().modified(entry)))
        QTimer.singleShot(0, self._reflow)

    def _jump_related(self, key):
        if not self._apply_fields():
            return
        target = related_entry(self._current_section(), self._current_entry[key])
        if target:
            self._select_entry(target[1])

    def _restore_entry(self):
        original = self._session().original(self._current_entry)
        if original is None:
            return
        for key in fields(self._current_section()['type']):
            self._current_entry[key] = copy.deepcopy(original[key])
        self._build_editor()
        self._dirty = any(s.dirty() for s in self._sessions.values())
        self._refresh_catalog()

    def _reflow(self):
        columns = 1 if self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT else 2
        for grid, frames in self._grids:
            if not frames:
                continue
            for col in range(2):
                grid.setColumnStretch(col, int(col < columns))
            for i, frame in enumerate(frames):
                row, col = divmod(i, columns)
                at = grid.indexOf(frame)
                if grid.getItemPosition(at) != (row, col, 1, 1):
                    grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)
        actions = getattr(self, '_relation_actions', None)
        if actions is not None:
            actions.content_layout.setDirection(QHBoxLayout.Direction.TopToBottom if columns == 1
                                               else QHBoxLayout.Direction.LeftToRight)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _reset_models(self):
        # Existing controls are destroyed before their caller-owned models.
        for model in self._choice_models.values():
            model.deleteLater()
        self._choice_models.clear()

    def _insert_entry(self, duplicate=False):
        section = self._current_section()
        if self._busy or section is None or not self._apply_fields() or duplicate and self._current_entry is None:
            return
        if len(section['entries']) >= 32767:
            return
        entry = copy.deepcopy(self._current_entry) if duplicate else make_default(section['type'])
        entry['idx'] = len(section['entries'])
        section['entries'].append(entry)
        self._current_entry, self._fields = None, {}
        self._search_entry.clear()
        self._state_filter.setCurrentIndex(0)
        self._reset_models()
        self._filter_list()
        self._select_entry(entry)
        self._dirty = True
        self._update_actions()

    def _add_entry(self):
        self._insert_entry()

    def _duplicate_entry(self):
        self._insert_entry(duplicate=True)

    def _delete_entry(self):
        section = self._current_section()
        if self._busy or section is None or self._current_entry is None or not self._apply_fields():
            return
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'), ui_text('soundparam_delete_warning'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = next(i for i, e in enumerate(section['entries']) if e is self._current_entry)
        section['entries'].pop(index)
        self._current_entry, self._fields = None, {}
        for i, e in enumerate(section['entries']):
            e['idx'] = i
        self._reset_models()
        self._filter_list()
        if section['entries']:
            self._select_entry(section['entries'][min(index, len(section['entries']) - 1)])
        else:
            self._placeholder()
        self._dirty = True
        self._update_actions()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_sndcmnparam_open_sndcmnparam_xfbin'),
            game_files_dialog_dir(target_patterns=('sndcmnparam.xfbin', 'sndcmnparam.bin.xfbin')),
            'Sound CMN Param (*.xfbin);;All files (*)')
        if path:
            self._start_load(path)

    def _start_load(self, path):
        if self._dirty and QMessageBox.question(self, ui_text('unsaved_changes_title'), ui_text('effect_discard'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        self._generation += 1
        self._detail_timer.stop()
        self._busy = True
        self._main.setEnabled(False)
        self._update_actions()
        job = _LoadJob(self._generation, str(path), load_settings().get('game_files_dir', ''))
        job.signals.done.connect(self._load_ready)
        self._jobs[self._generation] = job
        QThreadPool.globalInstance().start(job)
        return True

    def _load_ready(self, token, path, result, error):
        self._jobs.pop(token, None)
        if token != self._generation:
            return
        self._busy = False
        self._main.setEnabled(True)
        if error:
            self._update_actions()
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=error))
            return
        raw, sections, root, inventory = result
        self._on_load_done(path, raw, sections, root, inventory)

    def _on_load_done(self, path, raw, sections, root=None, inventory=None):
        create_backup_on_open(path)
        self._filepath, self._raw, self._sections = str(path), raw, sections
        self._current_entry, self._current_section_idx, self._fields = None, None, {}
        self._sessions = {id(s): RecordSession(s, fields(s['type'])) for s in sections}
        self._root = root if root is not None else data_root(path, load_settings().get('game_files_dir', ''))
        self._inventory = asset_inventory(self._root) if inventory is None else inventory
        self._asset_index = index_assets(self._inventory)
        self._reset_models()
        self._dirty = self._busy = False
        self._main.setEnabled(True)
        self._building = True
        self._section_combo.clear()
        for section in sections:
            kind = ui_text('soundparam_section_' + section['type'])
            self._section_combo.addItem(f"{kind} · {section['name']}")
        self._search_entry.clear()
        self._state_filter.setCurrentIndex(0)
        self._building = False
        self._select_category(0)
        self._update_actions()

    def _update_actions(self):
        loaded = self._raw is not None and not self._busy
        selected = loaded and self._current_entry is not None
        self._save_btn.setEnabled(loaded)
        self._add_btn.setEnabled(loaded and self._current_section() is not None)
        self._dup_btn.setEnabled(selected)
        self._del_btn.setEnabled(selected)
        self._section_combo.setEnabled(loaded)
        if self._busy:
            self._file_lbl.setText(ui_text('loading'))
        elif self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=self._dirty)
        else:
            self._file_lbl.setText(ui_text('no_file_loaded'))
        refresh_file_actions(self, loaded=self._raw is not None)

    def _save_file(self, target_path=None):
        path = target_path if isinstance(target_path, (str, Path)) else editor_path(self)
        return self._do_save(path) if path else False

    def _do_save(self, path):
        if self._busy or self._raw is None or not self._apply_fields():
            return False
        try:
            save_sndcmnparam_xfbin(path, self._raw, self._sections)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False
        commit_save_path(self, str(path))
        for session in self._sessions.values():
            session.mark_saved()
        self._dirty = False
        self._update_actions()
        return True
