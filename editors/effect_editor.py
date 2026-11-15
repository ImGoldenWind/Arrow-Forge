"""Effect bindings: exact catalog editing and read-only resource inspection."""
import copy
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QRunnable, QSignalBlocker, QThreadPool, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label
from core.effect_tools import (
    FACTORIES, NATIVE_SLOT_COUNT, damage_references, data_root, duplicate_slots,
    effective_entry, effect_names, load_asset_index, next_slot, parse_field, path_choices,
)
from core.record_session import RecordSession
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.style_helpers import (
    make_editor_field_shell, make_editor_grid_card, make_empty_state,
    ss_bg_dark, ss_dim_label, ss_error_label, ss_input_validation,
)
from core.translations import ui_text
from core.ui.editor_actions import commit_save_path, install_file_actions, refresh_file_actions
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_widgets import (
    EditorActionRow, EditorFilterCombo, EditorSeparator, EditorSidebar, EditorToolbar,
    configure_button, configure_card, configure_field, configure_file_label,
    configure_input, configure_layout, configure_scrollarea, configure_search, fit_scroll_page,
)
from core.ui.number_input import IntegerStepper
from core.ui.record_list import EditorRecordList, RecordListModel
from core.ui.value_combo import EditorValueCombo
from parsers.effectprm_parser import FIELDS, parse_effectprm_xfbin, save_effectprm_xfbin


class _ReadSignals(QObject):
    finished = pyqtSignal(int, str, object, str)


class _ReadJob(QRunnable):
    def __init__(self, token, path, read):
        super().__init__()
        self.token, self.path, self.read = token, path, read
        self.signals = _ReadSignals()

    def run(self):
        try:
            result, error = self.read(), ''
        except Exception as exc:
            result, error = None, str(exc)
        self.signals.finished.emit(self.token, self.path, result, error)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _effect_title(entry):
    return entry['effect_name'] or ui_text('effect_empty_binding')


class EffectEditor(QWidget):
    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or ui_text
        self._filepath = self._raw = self._result = self._session = None
        self._entries, self._fields = [], {}
        self._current_entry = None
        self._dirty = self._busy = False
        self._load_generation = self._resource_generation = 0
        self._root = None
        self._asset_index, self._asset_reference = (), None
        self._references, self._reference_path, self._reference_error = {}, '', ''
        self._jobs = {}
        self._resource_timer = QTimer(self)
        self._resource_timer.setSingleShot(True)
        self._resource_timer.setInterval(200)
        self._resource_timer.timeout.connect(self._inspect_resource)
        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=self._do_save)
        install_editor_chrome(self)
        self._update_actions()

    def _button(self, key, callback, *, action=None, danger=False, compact=False):
        button = configure_button(QPushButton(ui_text(key)), danger=danger,
                                  height=Size.COMPACT_CONTROL if compact else Size.CONTROL)
        if action:
            button.setProperty('designAction', action)
        button.clicked.connect(callback)
        return button

    def _label(self, text='', *, error=False):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_error_label() if error else ss_dim_label())
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _build_ui(self):
        self.setStyleSheet(ss_bg_dark())
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        top = EditorToolbar()
        self._open_btn = configure_button(QPushButton(ui_text('btn_open_file')), accent=True)
        self._open_btn.setProperty('designAction', 'open')
        self._open_btn.clicked.connect(self._load_file)
        self._save_btn = configure_button(QPushButton(ui_text('btn_save_file')), accent=True)
        self._save_btn.clicked.connect(self._save_file)
        self._file_lbl = configure_file_label(QLabel(ui_text('no_file_loaded')))
        for widget in (self._open_btn, self._save_btn, self._file_lbl):
            top.content_layout.addWidget(widget)
        top.content_layout.addStretch()
        root.addWidget(top)
        root.addWidget(EditorSeparator(accent=True))
        self._main = QWidget()
        main = configure_layout(QHBoxLayout(self._main), LayoutRole.ROOT)
        sidebar = EditorSidebar(width=290)
        side = sidebar.content_layout
        self._search_entry = configure_search(QLineEdit())
        self._search_entry.setToolTip(ui_text('effect_search_hint'))
        self._search_entry.textChanged.connect(self._filter_list)
        side.addWidget(self._search_entry)
        self._state_filter = EditorFilterCombo()
        for key in ('all', 'assigned', 'empty', 'duplicates', 'modified'):
            self._state_filter.addItem(ui_text('effect_filter_' + key), key)
        self._state_filter.currentIndexChanged.connect(self._filter_list)
        side.addWidget(self._state_filter)
        actions = EditorActionRow()
        self._add_btn = self._button('btn_new', self._add_entry, action='new', compact=True)
        self._dup_btn = self._button('btn_duplicate', self._dup_entry, action='duplicate', compact=True)
        self._del_btn = self._button('btn_delete', self._del_entry, action='delete', danger=True, compact=True)
        for button in (self._add_btn, self._dup_btn, self._del_btn):
            actions.content_layout.addWidget(button, 1)
        side.addWidget(actions)
        self._catalog_model = RecordListModel(self)
        self._catalog = EditorRecordList(self._catalog_model, self._describe_row)
        self._catalog.setAccessibleName(ui_text('effect_catalog'))
        self._catalog.selectionModel().currentRowChanged.connect(self._catalog_selected)
        side.addWidget(self._catalog, 1)
        self._no_matches = self._label(ui_text('trophy_no_matches'))
        self._no_matches.hide()
        side.addWidget(self._no_matches)
        main.addWidget(sidebar)
        main.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main.addWidget(self._editor_scroll, 1)
        root.addWidget(self._main, 1)
        self._placeholder()

    def _placeholder(self):
        self._fields = {}
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(
            self._editor_widget, title=ui_text('no_file_loaded') if self._result is None else ui_text('effect_catalog'),
            text=ui_text('ui_effect_open_effectprm_bin_xfbin_to_begin_editing') if self._result is None else ui_text('effect_empty_catalog'),
            icon_name='fa6s.wand-magic-sparkles'), 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _describe_row(self, index):
        row = self._catalog_model.rows[index.row()]
        entry = row[1]
        mark = '● ' if self._session.modified(entry) else ''
        return mark + _effect_title(entry), ui_text('effect_row', row=row[2] + 1, slot=entry['slot_id'],
            factory=entry['xfbins_count']), entry['xfbin_path'] + '\n' + entry['effect_name']

    def _sync_selection(self):
        for i, row in enumerate(self._catalog_model.rows):
            if row[1] is self._current_entry:
                self._catalog.setCurrentIndex(self._catalog_model.index(i))
                return
        self._catalog.setCurrentIndex(self._catalog_model.index(-1))

    def _populate_list(self):
        self._filter_list()

    def _filter_list(self, *_):
        query = self._search_entry.text().casefold().strip()
        state = self._state_filter.currentData()
        duplicates = duplicate_slots(self._entries)
        rows = []
        for i, entry in enumerate(self._entries):
            assigned = bool(entry['effect_name'] and entry['xfbin_path'] and entry['xfbins_count'])
            if state == 'assigned' and not assigned or state == 'empty' and assigned:
                continue
            if state == 'duplicates' and entry['slot_id'] not in duplicates:
                continue
            if state == 'modified' and not self._session.modified(entry):
                continue
            terms = f"{entry['slot_id']} {entry['slot_id']:#x} {entry['xfbins_count']} {entry['effect_name']} {entry['xfbin_path']} {i + 1}"
            if query and query not in terms.casefold():
                continue
            rows.append((_effect_title(entry), entry, i))
        with QSignalBlocker(self._catalog.selectionModel()):
            self._catalog_model.reset_rows(rows)
            self._sync_selection()
        self._no_matches.setVisible(bool(self._result is not None and not rows))

    def _catalog_selected(self, current, previous):
        if current.isValid():
            if not self._select_entry(self._catalog_model.rows[current.row()][1]):
                with QSignalBlocker(self._catalog.selectionModel()):
                    self._sync_selection()

    def _select_entry(self, entry):
        if self._busy or not self._apply_fields(show_errors=True):
            return False
        if entry is self._current_entry:
            return True
        self._resource_timer.stop()
        self._resource_generation += 1
        self._current_entry = entry
        with QSignalBlocker(self._catalog.selectionModel()):
            self._sync_selection()
        self._catalog.scrollTo(self._catalog.currentIndex())
        self._build_editor(entry)
        self._update_actions()
        return True

    def _card(self, title, icon='fa6s.sliders'):
        card, grid = make_editor_grid_card(self._editor_widget, title=title, icon_name=icon)
        configure_card(card)
        self._editor_layout.addWidget(card)
        return card, grid

    def _field(self, key, control, hint):
        caption = self._caption(key)
        frame, layout, label, _ = make_editor_field_shell(caption)
        configure_field(frame, control, vertical_policy=QSizePolicy.Policy.Minimum)
        control.setAccessibleName(caption)
        control.setProperty('messageReference', False)
        control.setToolTip(hint)
        label.setBuddy(control)
        if key == 'slot_id':
            layout.addWidget(IntegerStepper(control, 0, 0xffffffff))
        else:
            layout.addWidget(control)
        self._fields[key] = control
        return frame

    def _caption(self, key):
        return ui_text({'slot_id': 'ui_effect_slot_id', 'xfbins_count': 'effect_handler',
                        'xfbin_path': 'ui_effect_xfbin_path', 'effect_name': 'ui_effect_effect_name'}[key])

    def _build_editor(self, entry):
        self._fields, self._grids = {}, []
        _clear_layout(self._editor_layout)
        self._asset_index, self._asset_reference = (), None
        card, grid = self._card(ui_text('effect_binding'), 'fa6s.wand-magic-sparkles')
        slot = configure_input(QLineEdit(str(entry['slot_id'])), monospace=True)
        factory = EditorValueCombo([(n, ui_text('effect_factory_' + str(n))) for n in FACTORIES], entry['xfbins_count'])
        frames = [self._field('slot_id', slot, ui_text('effect_slot_hint', maximum=NATIVE_SLOT_COUNT - 1)),
                  self._field('xfbins_count', factory, ui_text('effect_handler_hint'))]
        self._grids.append((grid, frames))
        path_card, path_grid = self._card(ui_text('effect_resource'), 'fa6s.folder-open')
        path = EditorValueCombo(path_choices(self._root, self._entries), entry['xfbin_path'])
        name = EditorValueCombo(self._name_choices(entry['xfbin_path']), entry['effect_name'])
        for row, key, control in ((0, 'xfbin_path', path), (1, 'effect_name', name)):
            hint = ui_text('effect_string_hint', maximum=self._result['string_len'] - 1)
            frame = self._field(key, control, hint)
            path_grid.addWidget(frame, row, 0)
        path_grid.setColumnStretch(0, 1)
        actions = EditorActionRow()
        self._browse_btn = self._button('effect_browse_asset', self._browse_asset)
        self._root_btn = self._button('effect_resources_folder', self._choose_root)
        self._root_btn.setToolTip(str(self._root or ui_text('effect_root_missing')))
        self._refresh_btn = self._button('effect_check_resource', self._inspect_resource)
        for button in (self._browse_btn, self._root_btn, self._refresh_btn):
            actions.content_layout.addWidget(button)
        path_card.layout().addWidget(actions)
        self._resource_actions = actions
        self._resource_status = self._label()
        self._resource_types = self._label()
        self._resource_status.setFont(ui_font(TypeSize.BODY))
        path_card.layout().addWidget(self._resource_status)
        path_card.layout().addWidget(self._resource_types)
        self._diagnostics = self._label()
        card.layout().addWidget(self._diagnostics)
        self._effective_btn = self._button('effect_show_effective', self._show_effective)
        card.layout().addWidget(self._effective_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self._usage = self._label()
        path_card.layout().addWidget(self._usage)
        path_card.layout().addWidget(self._label(ui_text('effect_inspection_scope')))
        compare, compare_grid = self._card(ui_text('effect_comparison'), 'fa6s.code-compare')
        compare.hide()
        self._comparisons = {}
        for i, key in enumerate(FIELDS):
            label = self._label()
            self._comparisons[key] = label
            compare_grid.addWidget(label, i, 0)
        compare_grid.setColumnStretch(0, 1)
        self._restore_btn = self._button('font_restore_record', self._restore_entry)
        self._restore_btn.hide()
        self._restore_btn.setToolTip(ui_text('trophy_restore_hint'))
        compare.layout().addWidget(self._restore_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self._editor_layout.addStretch()
        for key, control in self._fields.items():
            signal = control.editTextChanged if isinstance(control, EditorValueCombo) else control.textChanged
            signal.connect(lambda _, field=key: self._field_changed(field))
        self._refresh_detail()
        self._reflow()
        self._inspect_resource()

    def _name_choices(self, path):
        names = {e['effect_name'] for e in self._entries if e['xfbin_path'] == path and e['effect_name']}
        if path == self._asset_reference:
            names.update(effect_names(self._asset_index))
        return [(name, name) for name in sorted(names)]

    def _draft(self):
        values, errors = {}, []
        if self._current_entry is None:
            return values, errors
        for key, control in self._fields.items():
            text = control.value_text() if isinstance(control, EditorValueCombo) else control.text()
            try:
                values[key] = parse_field(key, text, self._current_entry, self._result['string_len'])
                invalid = False
            except (ValueError, UnicodeError):
                errors.append(key)
                invalid = True
            if control.property('effectInvalid') != invalid:
                control.setStyleSheet(ss_input_validation(invalid))
                control.setProperty('effectInvalid', invalid)
        return values, errors

    def _apply_fields(self, show_errors=False):
        if self._current_entry is None or not self._fields:
            return True
        values, errors = self._draft()
        if errors:
            if show_errors:
                self._fields[errors[0]].setFocus()
                self._editor_scroll.ensureWidgetVisible(self._fields[errors[0]])
            return False
        self._current_entry.update(values)
        return True

    def _field_changed(self, key):
        self._apply_fields()
        self._dirty = True
        if key in ('xfbin_path', 'effect_name'):
            self._resource_generation += 1
            self._asset_reference = None
            self._resource_status.setText(ui_text('effect_check_pending'))
            self._resource_types.clear()
            self._resource_timer.start()
        self._refresh_detail()
        self._filter_list()
        self._update_actions()

    def _refresh_detail(self):
        entry = self._current_entry
        if entry is None:
            return
        values, errors = self._draft()
        messages = []
        for key in errors:
            messages.append(ui_text('effect_invalid_number' if key in ('slot_id', 'xfbins_count') else 'effect_invalid_string',
                                    field=self._caption(key), maximum=self._result['string_len'] - 1))
        if not errors:
            if entry['xfbins_count'] == 0:
                messages.append(ui_text('effect_no_creator'))
            if entry['slot_id'] >= NATIVE_SLOT_COUNT:
                messages.append(ui_text('effect_slot_unsafe', maximum=NATIVE_SLOT_COUNT - 1))
            if entry['xfbins_count'] not in FACTORIES:
                messages.append(ui_text('effect_factory_unsafe'))
            if entry['slot_id'] in duplicate_slots(self._entries):
                effective = effective_entry(self._entries, entry['slot_id'])
                messages.append(ui_text('effect_duplicate_effective' if effective is entry else 'effect_duplicate_shadowed'))
            if entry['xfbins_count'] and (not entry['effect_name'] or not entry['xfbin_path']):
                messages.append(ui_text('effect_incomplete_binding'))
            if self._result['string_len'] != 32:
                messages.append(ui_text('effect_legacy_layout'))
        self._diagnostics.setText('\n'.join(messages))
        self._diagnostics.setStyleSheet(ss_error_label() if errors else ss_dim_label())
        effective = effective_entry(self._entries, entry['slot_id'])
        self._effective_btn.setVisible(effective is not entry)
        self._effective_btn.setEnabled(not errors)
        original = self._session.original(entry)
        for key, label in self._comparisons.items():
            before = str(original[key]) if original else ui_text('effect_new_record')
            current = self._fields[key].value_text() if isinstance(self._fields[key], EditorValueCombo) else self._fields[key].text()
            label.setText(ui_text('effect_compare_field', field=self._caption(key), before=before or '∅', current=current or '∅'))
        self._restore_btn.setEnabled(original is not None and (bool(errors) or self._session.modified(entry)))
        uses = self._references.get(entry['slot_id'], [])
        if self._reference_error:
            usage = ui_text('effect_reference_error', error=self._reference_error)
        elif not self._reference_path:
            usage = ui_text('effect_references_unavailable')
        elif uses:
            usage = ui_text('effect_references', links='; '.join(ui_text('effect_reference_row', row=i + 1, slot=slot, channel=channel)
                for i, slot, channel in uses))
        else:
            usage = ui_text('effect_no_references')
        self._usage.setText(usage)
        self._usage.setToolTip(self._reference_path)
        QTimer.singleShot(0, self._reflow)

    def _restore_entry(self):
        original = self._session.original(self._current_entry)
        if original is not None:
            self._current_entry.update(copy.deepcopy(original))
            self._dirty = self._session.dirty()
            self._build_editor(self._current_entry)
            self._populate_list()
            self._update_actions()

    def _show_effective(self):
        if self._current_entry is not None:
            self._select_entry(effective_entry(self._entries, self._current_entry['slot_id']))

    def _reflow(self):
        if not self._fields:
            return
        compact = self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT
        for grid, frames in self._grids:
            for frame in frames:
                grid.removeWidget(frame)
            grid.setColumnStretch(1, 0)
            for i, frame in enumerate(frames):
                row, col = (i, 0) if compact else (0, i)
                grid.addWidget(frame, row, col)
                grid.setColumnStretch(col, 1)
        self._resource_actions.content_layout.setDirection(QHBoxLayout.Direction.TopToBottom if compact else QHBoxLayout.Direction.LeftToRight)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _inspect_resource(self):
        self._resource_timer.stop()
        if self._current_entry is None or self._busy:
            return
        values, errors = self._draft()
        self._resource_generation += 1
        token = self._resource_generation
        self._asset_index, self._asset_reference = (), None
        self._resource_types.clear()
        if errors:
            self._resource_status.setText(ui_text('effect_resource_invalid'))
            return
        reference = values['xfbin_path']
        if not reference:
            self._resource_status.setText(ui_text('effect_no_asset'))
            return
        if self._root is None:
            self._resource_status.setText(ui_text('effect_root_missing'))
            return
        self._resource_status.setText(ui_text('effect_check_pending'))
        root = self._root
        job = _ReadJob(token, reference, lambda: load_asset_index(root, reference))
        job.signals.finished.connect(self._resource_ready)
        self._jobs[('resource', token)] = job
        QThreadPool.globalInstance().start(job)

    def _resource_ready(self, token, reference, result, error):
        self._jobs.pop(('resource', token), None)
        if token != self._resource_generation or not self._fields:
            return
        if error:
            self._resource_status.setText(ui_text('effect_asset_error', error=error))
            self._reflow()
            return
        path, index = result
        self._asset_index, self._asset_reference = index, reference
        combo = self._fields['effect_name']
        text = combo.value_text()
        with QSignalBlocker(combo), QSignalBlocker(combo.lineEdit()):
            combo.clear()
            for key, caption in self._name_choices(reference):
                combo.addItem(caption, key)
            combo.setCurrentIndex(-1)
            combo.setEditText(text)
        kinds = sorted({kind for kind, name in index if name == text})
        self._resource_status.setText(ui_text('effect_asset_found' if kinds else 'effect_name_missing', name=text or '∅'))
        self._resource_types.setText('\n'.join((str(path), ', '.join(kinds))))
        self._reflow()

    def _choose_root(self):
        path = QFileDialog.getExistingDirectory(self, ui_text('effect_resources_folder'), str(self._root or ''))
        if path:
            root = data_root(None, path)
            if root is None:
                QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('effect_root_missing'))
                return
            self._root = root
            self._root_btn.setToolTip(str(root))
            self._update_resource_choices()

    def _update_resource_choices(self):
        self._read_references()
        combo = self._fields.get('xfbin_path')
        if combo is not None:
            text = combo.value_text()
            with QSignalBlocker(combo), QSignalBlocker(combo.lineEdit()):
                combo.clear()
                for key, caption in path_choices(self._root, self._entries):
                    combo.addItem(caption, key)
                combo.setCurrentIndex(-1)
                combo.setEditText(text)
            self._refresh_detail()
            self._inspect_resource()

    def _browse_asset(self):
        if not self._apply_fields(show_errors=True):
            return
        path, _ = QFileDialog.getOpenFileName(self, ui_text('effect_browse_asset'), str(self._root or ''), 'XFBIN (*.xfbin)')
        if not path:
            return
        candidate = Path(path).resolve()
        root = self._root or data_root(candidate)
        if root is None or not candidate.is_relative_to(root):
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('effect_asset_outside_root'))
            return
        reference = 'data/' + candidate.relative_to(root).as_posix()
        try:
            parse_field('xfbin_path', reference, self._current_entry, self._result['string_len'])
        except (ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), str(exc))
            return
        self._root = root
        self._fields['xfbin_path'].setEditText(reference)

    def _read_references(self):
        self._reference_error = ''
        try:
            self._reference_path, self._references = damage_references(self._filepath, self._root)
        except Exception as exc:
            self._reference_path, self._references, self._reference_error = '', {}, str(exc)

    def _add_entry(self):
        if self._busy or self._result is None or not self._apply_fields(show_errors=True):
            return
        slot = next_slot(self._entries)
        if slot is None:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('effect_slots_full'))
            return
        entry = dict(idx=len(self._entries), slot_id=slot, xfbins_count=0, xfbin_path='', effect_name='')
        self._entries.append(entry)
        self._select_entry(entry)
        self._dirty = True
        self._populate_list()
        self._update_actions()

    def _dup_entry(self):
        if self._busy or self._current_entry is None or not self._apply_fields(show_errors=True):
            return
        slot = next_slot(self._entries)
        if slot is None:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('effect_slots_full'))
            return
        # Resource names are references. Appending '_copy' would break the link.
        entry = copy.deepcopy(self._current_entry)
        entry.update(idx=len(self._entries), slot_id=slot)
        self._entries.append(entry)
        self._select_entry(entry)
        self._dirty = True
        self._populate_list()
        self._update_actions()

    def _del_entry(self):
        if self._busy or self._current_entry is None or not self._apply_fields(show_errors=True):
            return
        entry = self._current_entry
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'),
                ui_text('effect_delete_warning', slot=entry['slot_id']),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        i = next(i for i, e in enumerate(self._entries) if e is entry)
        self._entries.pop(i)
        self._current_entry, self._fields = None, {}
        self._resource_generation += 1
        self._populate_list()
        if self._entries:
            self._select_entry(self._entries[min(i, len(self._entries) - 1)])
        else:
            self._placeholder()
        self._dirty = True
        self._update_actions()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_effect_open_effectprm_xfbin'),
            game_files_dialog_dir(target_patterns=('effectprm.bin.xfbin', 'effectprm.xfbin')),
            'Effect PRM (*.xfbin);;All files (*)')
        if path:
            self._start_load(path)

    def _start_load(self, path):
        if self._dirty and QMessageBox.question(self, ui_text('unsaved_changes_title'), ui_text('effect_discard'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        self._load_generation += 1
        self._resource_generation += 1
        self._resource_timer.stop()
        self._busy = True
        self._main.setEnabled(False)
        self._update_actions()
        path = str(path)
        token = self._load_generation
        job = _ReadJob(token, path, lambda: parse_effectprm_xfbin(path))
        job.signals.finished.connect(self._load_ready)
        self._jobs[('file', token)] = job
        QThreadPool.globalInstance().start(job)
        return True

    def _load_ready(self, token, path, result, error):
        self._jobs.pop(('file', token), None)
        if token != self._load_generation:
            return
        self._busy = False
        self._main.setEnabled(True)
        if error:
            self._update_actions()
            if self._current_entry is not None:
                self._inspect_resource()
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=error))
            return
        self._on_load_done(path, *result)

    def _on_load_done(self, path, raw, result):
        create_backup_on_open(path)
        self._filepath, self._raw, self._result = str(path), raw, result
        self._entries = result['entries']
        self._session = RecordSession(result, FIELDS)
        self._current_entry, self._fields = None, {}
        self._dirty = self._busy = False
        self._main.setEnabled(True)
        self._root = data_root(path, load_settings().get('game_files_dir', ''))
        self._read_references()
        self._search_entry.clear()
        self._state_filter.setCurrentIndex(0)
        self._populate_list()
        if self._entries:
            self._select_entry(self._entries[0])
        else:
            self._placeholder()
        self._update_actions()

    def _update_actions(self):
        loaded = self._result is not None and not self._busy
        self._save_btn.setEnabled(loaded)
        self._add_btn.setEnabled(loaded)
        self._dup_btn.setEnabled(loaded and self._current_entry is not None)
        self._del_btn.setEnabled(loaded and self._current_entry is not None)
        if self._busy:
            self._file_lbl.setText(ui_text('ui_effect_loading'))
        elif self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=self._dirty)
        else:
            self._file_lbl.setText(ui_text('no_file_loaded'))
        refresh_file_actions(self, loaded=self._result is not None)

    def _save_file(self):
        if self._filepath:
            return self._do_save(self._filepath)
        return False

    def _do_save(self, path):
        if self._busy or self._result is None or not self._apply_fields(show_errors=True):
            return False
        try:
            save_effectprm_xfbin(path, self._raw, self._result)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False
        # Retain identities, original snapshot, selected duplicate and controls.
        # The writer always rebuilds from the original envelope + current rows.
        commit_save_path(self, str(path))
        self._session.mark_saved()
        self._dirty = False
        self._update_actions()
        return True
