"""Evidence-backed rank progression editor using shared Arrow Forge controls."""
import os

from PyQt6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (make_editor_field_shell, make_editor_grid_card, make_empty_state,
    ss_bg_dark, ss_dim_label, ss_error_label, ss_input_validation, ss_slider)
from core.translations import ui_text
from core.netrank_tools import (FIELDS, UINT32_MAX, RankSession, duplicate_ids,
    eligibility_ranges, next_id, parse_field, rank_at_points)
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions, refresh_file_actions
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_widgets import (EditorActionRow, EditorFilterCombo, EditorSeparator,
    EditorSidebar, EditorToolbar, configure_button, configure_card, configure_field,
    configure_file_label, configure_input, configure_layout, configure_scrollarea,
    configure_search, fit_scroll_page)
from core.ui.message_preview import MessagePreview, message_lookup
from core.ui.number_input import IntegerStepper
from core.ui.record_list import EditorRecordList
from core.ui.series_comparison import SeriesComparison
from core.ui.value_combo import EditorValueCombo
from editors.netrankparam_model import RankFilterModel, RankListModel
from parsers.netrankparam_parser import make_default_entry, parse_netrankparam_xfbin, save_netrankparam_xfbin


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class NetRankParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t, self._embedded = t or ui_text, embedded
        self._filepath = self._raw_data = self._result = self._session = None
        self._entries, self._fields = [], {}
        self._current_idx = None
        self._dirty = self._loading_detail = False
        self._grids, self._name_cache = [], {}
        self._name_model = None
        self._probe_value = 0
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(150)
        self._detail_timer.timeout.connect(self._refresh_detail)
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())
        toolbar = EditorToolbar()
        self._btn_open = self._button('btn_open_file', self._do_open, accent=True)
        self._btn_open.setProperty('designAction', 'open')
        self._btn_save = self._button('btn_save_file', lambda: self._do_save(), accent=True)
        self._file_label = configure_file_label(QLabel(ui_text('no_file_loaded')))
        for widget in (self._btn_open, self._btn_save, self._file_label):
            toolbar.content_layout.addWidget(widget)
        toolbar.content_layout.addStretch()
        root.addWidget(toolbar)
        root.addWidget(EditorSeparator(accent=True))
        main = configure_layout(QHBoxLayout(), LayoutRole.ROOT)
        sidebar = EditorSidebar(width=290)
        side = sidebar.content_layout
        self._search = configure_search(QLineEdit())
        self._search.setToolTip(ui_text('netrank_search_hint'))
        self._search.textChanged.connect(self._filter_list)
        side.addWidget(self._search)
        self._status_filter = EditorFilterCombo()
        self._status_filter.addItem(ui_text('netrank_filter_hint'), False)
        self._status_filter.addItem(ui_text('netrank_modified'), True)
        self._status_filter.currentIndexChanged.connect(self._filter_list)
        side.addWidget(self._status_filter)
        actions = EditorActionRow()
        for attr, key, slot, action in (('_btn_add', 'btn_new', self._do_add, 'new'),
                ('_btn_dup', 'btn_duplicate', self._do_dup, 'duplicate'),
                ('_btn_del', 'btn_delete', self._do_del, 'delete')):
            button = self._button(key, slot, danger=action == 'delete', compact=True)
            button.setProperty('designAction', action)
            setattr(self, attr, button)
            actions.content_layout.addWidget(button, 1)
        side.addWidget(actions)
        self._catalog_model = RankListModel(self)
        self._catalog_proxy = RankFilterModel(self)
        self._catalog_proxy.setSourceModel(self._catalog_model)
        self._catalog = EditorRecordList(self._catalog_proxy, self._describe_row)
        self._catalog.selectionModel().currentChanged.connect(self._on_catalog_selection)
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
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main.addWidget(self._editor_scroll, 1)
        root.addLayout(main, 1)
        self._show_placeholder(ui_text('ui_netrankparam_open_file_to_begin_editing'))
        self._update_actions()

    def _button(self, key, slot, *, accent=False, danger=False, compact=False):
        button = configure_button(QPushButton(ui_text(key)), accent=accent, danger=danger,
                                  height=Size.COMPACT_CONTROL if compact else Size.CONTROL)
        button.clicked.connect(slot)
        return button

    def _label(self, text, *, error=False):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_error_label() if error else ss_dim_label())
        return label

    def _show_placeholder(self, text):
        self._fields, self._grids = {}, []
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(self._editor_widget,
            title=ui_text('no_file_loaded') if self._raw_data is None else ui_text('ui_netrankparam_no_entries'),
            text=text, icon_name='fa6s.medal'), 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_netrankparam_open_title'),
            game_files_dialog_dir(target_patterns=('NetRankParam.bin.xfbin', 'NetRankParam.xfbin')),
            ui_text('ui_netrankparam_file_filter'))
        if path:
            self._load(path)

    def _load(self, path):
        try:
            raw, result = parse_netrankparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=exc))
            return False
        if self._dirty and QMessageBox.question(self, ui_text('unsaved_changes_title'),
                ui_text('netrank_discard'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        create_backup_on_open(path)
        self._detail_timer.stop()
        self._filepath, self._raw_data, self._result = str(path), raw, result
        self._session = RankSession(result)
        self._entries, self._current_idx, self._fields = result['entries'], None, {}
        self._dirty, self._probe_value = False, 0
        self._name_cache.clear()
        self._reset_name_model()
        self._search.clear()
        self._status_filter.setCurrentIndex(0)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text('netrank_empty_hint'))
        self._update_actions()
        return True

    def _do_save(self, target_path=None):
        path = target_path or editor_path(self)
        if not path or self._result is None or not self._apply_current_entry(show_errors=True):
            return False
        try:
            save_netrankparam_xfbin(path, self._raw_data, self._result)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False
        commit_save_path(self, str(path))
        self._session.mark_saved()
        self._dirty = False
        self._update_actions()
        QMessageBox.information(self, ui_text('dlg_title_success'),
                                ui_text('msg_save_success', path=os.path.basename(path)))
        return True

    def _name(self, entry):
        key = entry['name_key']
        if key not in self._name_cache:
            reference = message_lookup(self).resolve(key)
            self._name_cache[key] = reference.text if reference and reference.text else key
        return self._name_cache[key] or ui_text('netrank_unnamed')

    def _entry_title(self, idx, entry):
        return self._name(entry)

    def _entry_subtitle(self, entry):
        return ui_text('netrank_row', rank_id=entry['rank_id'], points=f"{entry['required_points']:,}")

    def _describe_row(self, index):
        title, subtitle, search, modified = index.data(Qt.ItemDataRole.UserRole)
        return title, subtitle, title + '\n' + subtitle

    def _populate_list(self):
        rows = []
        for index, entry in enumerate(self._entries):
            title, subtitle = self._name(entry), self._entry_subtitle(entry)
            search = ' '.join((title, subtitle, str(index + 1), *(str(entry[k]) for k in FIELDS))).casefold()
            rows.append((title, subtitle, search, self._session.modified(entry)))
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._catalog_model.reset_rows(rows)
        self._filter_list()
        del blocker

    def _filter_list(self, *_):
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._catalog_proxy.set_filters(self._search.text(), bool(self._status_filter.currentData()))
        self._sync_selection()
        del blocker
        self._no_matches.setVisible(bool(self._entries) and self._catalog_proxy.rowCount() == 0)

    def _sync_selection(self):
        source = self._catalog_model.index(self._current_idx, 0) if self._current_idx is not None else self._catalog_model.index(-1, 0)
        index = self._catalog_proxy.mapFromSource(source)
        self._catalog.setCurrentIndex(index)
        if index.isValid():
            self._catalog.scrollTo(index)

    def _on_catalog_selection(self, current, previous):
        if current.isValid() and not self._select_entry(self._catalog_proxy.mapToSource(current).row()):
            blocker = QSignalBlocker(self._catalog.selectionModel())
            self._sync_selection()
            del blocker

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries) or not self._apply_current_entry(show_errors=True):
            return False
        if idx != self._current_idx or not self._fields:
            self._detail_timer.stop()
            self._current_idx = idx
            self._build_editor(idx)
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._sync_selection()
        del blocker
        self._update_actions()
        return True

    def _card(self, title, icon='fa6s.medal'):
        card, grid = make_editor_grid_card(self._editor_widget, title=title, icon_name=icon)
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        self._editor_layout.addWidget(card)
        return card, grid

    def _build_editor(self, idx):
        self._loading_detail = True
        self._fields, self._grids = {}, []
        _clear_layout(self._editor_layout)
        entry = self._entries[idx]
        card, grid = self._card(ui_text('ui_netrankparam_rank_parameters'))
        frames = []
        self._comparisons = {}
        captions = {'rank_id': ui_text('ui_netrankparam_rank_id'),
                    'required_points': ui_text('ui_netrankparam_required_points'),
                    'name_key': ui_text('netrank_name_id')}
        self._captions = captions
        for key in FIELDS:
            frame, layout, _, _ = make_editor_field_shell(captions[key])
            if key == 'name_key':
                if self._name_model is None:
                    keys = dict.fromkeys(e['name_key'] for e in self._entries if e['name_key'])
                    choices = [(key_, f'{key_} - {self._name(dict(name_key=key_))}') for key_ in keys]
                    self._name_model = EditorValueCombo.choice_model(choices, self)
                edit = EditorValueCombo((), entry[key], model=self._name_model)
                edit.setProperty('messageReference', True)
                layout.addWidget(edit)
                self._message_preview = MessagePreview(edit.lineEdit(), message_lookup(self))
                self._message_preview.refresh(edit.value_text())
                edit.currentTextChanged.connect(lambda _, combo=edit, preview=self._message_preview:
                                                preview.refresh(combo.value_text()))
                layout.addWidget(self._message_preview)
                edit.currentTextChanged.connect(self._on_field_changed)
            else:
                edit = configure_input(QLineEdit(str(entry[key])), monospace=True)
                edit.setProperty('messageReference', False)
                layout.addWidget(IntegerStepper(edit, 0, UINT32_MAX))
                edit.textChanged.connect(self._on_field_changed)
            edit.setAccessibleName(captions[key])
            edit.setToolTip(ui_text('netrank_' + key + '_hint'))
            if key == 'name_key':
                edit.lineEdit().setToolTip(edit.toolTip())
            comparison = self._label('')
            layout.addWidget(comparison)
            comparison.hide()
            configure_field(frame, edit, vertical_policy=QSizePolicy.Policy.Minimum)
            self._fields[key], self._comparisons[key] = edit, comparison
            frames.append(frame)
        self._grids.append((grid, frames, 2))
        self._diagnostics = self._label('')
        self._btn_restore = self._button('netrank_restore', self._restore_entry)
        self._btn_restore.hide()
        card.layout().addWidget(self._diagnostics)
        actions = EditorActionRow()
        self._btn_up = self._button('skill_command_up', lambda: self._move_entry(-1))
        self._btn_down = self._button('skill_command_down', lambda: self._move_entry(1))
        for button in (self._btn_restore, self._btn_up, self._btn_down):
            actions.content_layout.addWidget(button)
        actions.content_layout.addStretch()
        card.layout().addWidget(actions)

        self._preview_card, preview_grid = self._card(ui_text('netrank_progression'), 'fa6s.chart-line')
        frame, controls, _, _ = make_editor_field_shell(ui_text('netrank_probe_points'))
        self._probe_edit = configure_input(QLineEdit(str(self._probe_value)), monospace=True)
        self._probe_edit.setAccessibleName(ui_text('netrank_probe_points'))
        self._probe_edit.setProperty('messageReference', False)
        self._probe_scale = max(1, self._probe_value,
                               max((e['required_points'] for e in self._entries), default=0),
                               max((e['required_points'] for e in self._session.original_entries), default=0))
        controls.addWidget(IntegerStepper(self._probe_edit, 0, UINT32_MAX))
        self._probe_slider = QSlider(Qt.Orientation.Horizontal)
        self._probe_slider.setStyleSheet(ss_slider())
        self._probe_slider.setFixedHeight(Size.COMPACT_CONTROL)
        self._probe_slider.setRange(0, 1000)
        self._probe_slider.setAccessibleName(ui_text('netrank_probe_points'))
        self._probe_slider.setToolTip(ui_text('netrank_probe_hint'))
        controls.addWidget(self._probe_slider)
        configure_field(frame, self._probe_edit, vertical_policy=QSizePolicy.Policy.Minimum)
        preview_grid.addWidget(frame, 0, 0)
        self._probe_result = self._label('')
        preview_grid.addWidget(self._probe_result, 1, 0)
        self._chart = SeriesComparison(ui_text('customize_original'), ui_text('netrank_current'),
                                       ui_text('netrank_file_order'))
        self._chart.setToolTip(ui_text('netrank_chart_hint'))
        self._chart.selected.connect(self._select_entry)
        preview_grid.addWidget(self._chart, 2, 0)
        self._preview_card.layout().addWidget(self._label(ui_text('netrank_preview_scope')))
        self._probe_edit.textChanged.connect(self._probe_changed)
        self._probe_slider.valueChanged.connect(self._probe_slide)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._refresh_detail()
        self._reflow()

    def _draft(self):
        values, errors = {}, []
        for key, edit in self._fields.items():
            try:
                values[key] = parse_field(key, edit.value_text() if isinstance(edit, EditorValueCombo) else edit.text())
                invalid = False
            except (ValueError, UnicodeError, OverflowError):
                errors.append(key)
                invalid = True
            if bool(edit.property('netrankInvalid')) != invalid:
                edit.setStyleSheet(ss_input_validation(invalid))
                edit.setProperty('netrankInvalid', invalid)
        return values, errors

    def _apply_current_entry(self, show_errors=False):
        if self._current_idx is None or not self._fields:
            return True
        values, errors = self._draft()
        if errors:
            if show_errors:
                edit = self._fields[errors[0]]
                QMessageBox.warning(self, ui_text('dlg_title_warning'),
                                    ui_text('netrank_invalid', field=self._captions[errors[0]]))
                self._editor_scroll.ensureWidgetVisible(edit)
                edit.setFocus()
            return False
        self._entries[self._current_idx].update(values)
        return True

    def _on_field_changed(self, *_):
        if self._loading_detail:
            return
        self._apply_current_entry()
        self._dirty = True
        self._update_actions()
        self._detail_timer.start()

    def _refresh_detail(self):
        if self._current_idx is None or not self._fields:
            return
        _, errors = self._draft()
        self._dirty = bool(errors) or self._session.dirty()
        entry = self._entries[self._current_idx]
        original = self._session.original(entry)
        for key, label in self._comparisons.items():
            label.setText(ui_text('netrank_original_value', value=original[key]) if original else ui_text('netrank_new_row'))
        self._btn_restore.setEnabled(original is not None and (bool(errors) or self._session.modified(entry)))
        self._btn_up.setEnabled(self._current_idx > 0)
        self._btn_down.setEnabled(self._current_idx + 1 < len(self._entries))
        issues = []
        if errors:
            issues.append(ui_text('netrank_pending'))
        else:
            interval = eligibility_ranges(self._entries)[self._current_idx]
            issues.append(ui_text('netrank_shadowed') if interval is None else
                ui_text('netrank_interval', low=f'{interval[0]:,}', high=f'{interval[1]:,}'))
            if entry['rank_id'] in duplicate_ids(self._entries):
                issues.append(ui_text('netrank_duplicate'))
            if entry['rank_id'] not in {e['rank_id'] for e in self._session.original_entries}:
                issues.append(ui_text('netrank_new_id_warning'))
            if self._current_idx and entry['required_points'] <= self._entries[self._current_idx - 1]['required_points']:
                issues.append(ui_text('netrank_order_warning'))
            if not entry['name_key']:
                issues.append(ui_text('netrank_empty_name'))
        self._diagnostics.setText('\n'.join(issues))
        self._preview_card.setEnabled(not errors)
        self._populate_list()
        self._chart.set_series([e['required_points'] for e in self._session.original_entries],
                               [e['required_points'] for e in self._entries], self._current_idx)
        self._probe_changed()
        self._update_actions()
        self._reflow()

    def _probe_changed(self, *_):
        try:
            points = parse_field('required_points', self._probe_edit.text())
        except ValueError:
            self._probe_edit.setStyleSheet(ss_input_validation(True))
            self._probe_result.setText(ui_text('netrank_probe_invalid'))
            return
        self._probe_edit.setStyleSheet(ss_input_validation(False))
        self._probe_value = points
        self._probe_scale = max(self._probe_scale, 1, points, max((e['required_points'] for e in self._entries), default=0),
                                max((e['required_points'] for e in self._session.original_entries), default=0))
        blocker = QSignalBlocker(self._probe_slider)
        self._probe_slider.setValue(round(points * 1000 / self._probe_scale))
        del blocker
        results = []
        for label, entries in ((ui_text('customize_original'), self._session.original_entries),
                                (ui_text('netrank_current'), self._entries)):
            index = rank_at_points(entries, points)
            if index is None:
                value = ui_text('netrank_no_rank')
            else:
                entry = entries[index]
                value = ui_text('netrank_probe_rank', name=self._name(entry), rank_id=entry['rank_id'], row=index + 1)
            results.append(f'{label}: {value}')
        self._probe_result.setText('\n'.join(results))

    def _probe_slide(self, value):
        self._probe_edit.setText(str((value * self._probe_scale + 500) // 1000))

    def _restore_entry(self):
        original = self._session.original(self._entries[self._current_idx])
        if original is None:
            return
        for key, edit in self._fields.items():
            if isinstance(edit, EditorValueCombo):
                index = edit.findData(original[key])
                if index >= 0:
                    edit.setCurrentIndex(index)
                else:
                    edit.setCurrentIndex(-1)
                    edit.setEditText(original[key])
            else:
                edit.setText(str(original[key]))
        self._apply_current_entry()
        self._refresh_detail()

    def _insert(self, duplicate=False):
        if self._raw_data is None or not self._apply_current_entry(show_errors=True):
            return
        if duplicate and self._current_idx is None:
            return
        rank_id = next_id(self._entries)
        entry = make_default_entry(self._entries[self._current_idx] if duplicate else None, rank_id)
        entry['rank_id'] = rank_id
        if not duplicate:
            entry['required_points'] = max((e['required_points'] for e in self._entries), default=0)
        index = self._current_idx + 1 if duplicate else len(self._entries)
        self._entries.insert(index, entry)
        self._reset_name_model()
        self._current_idx, self._fields = None, {}
        self._dirty = True
        self._search.clear()
        self._status_filter.setCurrentIndex(0)
        self._populate_list()
        self._select_entry(index)

    def _move_entry(self, direction):
        if self._current_idx is None or not self._apply_current_entry(show_errors=True):
            return
        index = self._current_idx
        target = index + direction
        if not 0 <= target < len(self._entries):
            return
        self._entries[index], self._entries[target] = self._entries[target], self._entries[index]
        self._current_idx, self._fields = None, {}
        self._populate_list()
        self._select_entry(target)

    def _do_add(self):
        self._insert()

    def _do_dup(self):
        self._insert(True)

    def _do_del(self):
        if self._current_idx is None or not self._apply_current_entry(show_errors=True):
            return
        entry = self._entries[self._current_idx]
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'),
                ui_text('msg_confirm_delete_item', name=self._name(entry)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = self._current_idx
        self._entries.pop(index)
        self._reset_name_model()
        self._current_idx, self._fields, self._dirty = None, {}, True
        self._populate_list()
        if self._entries:
            self._select_entry(min(index, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text('netrank_empty_hint'))
            self._update_actions()

    def _update_actions(self):
        loaded = self._raw_data is not None
        selected = self._current_idx is not None
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and selected)
        self._btn_del.setEnabled(loaded and selected)
        self._btn_save.setEnabled(loaded and self._dirty)
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=self._dirty)
        if hasattr(self, '_file_actions'):
            refresh_file_actions(self, loaded=loaded)

    def _reset_name_model(self):
        if self._name_model is not None:
            self._name_model.deleteLater()
        self._name_model = None

    def _reflow(self):
        for grid, frames, maximum in self._grids:
            columns = 1 if self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT else maximum
            for col in range(maximum):
                grid.setColumnStretch(col, int(col < columns))
            for i, frame in enumerate(frames):
                row, column = divmod(i, columns)
                span = columns if i == len(frames) - 1 and column == 0 else 1
                grid.addWidget(frame, row, column, 1, span, Qt.AlignmentFlag.AlignTop)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)
