"""Evidence-backed BP award editor using shared Arrow Forge components."""
import os

from PyQt6.QtCore import QEvent, QSignalBlocker, QSortFilterProxyModel, Qt, QTimer
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label
from core.netresult_tools import (BASE_COUNT, FIELDS, GRADES, INT32_MIN, INT32_MAX,
    POINTS_MAX, ResultSession, bonus_ranges, calculate, parse_integer)
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (make_editor_field_shell, make_editor_grid_card, make_empty_state,
    ss_bg_dark, ss_dim_label, ss_main_label, ss_input_validation, ss_slider)
from core.translations import ui_text
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions, refresh_file_actions
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_widgets import (EditorActionRow, EditorFilterCombo, EditorSeparator,
    EditorSidebar, EditorToolbar, configure_button, configure_card, configure_field,
    configure_file_label, configure_input, configure_layout, configure_scrollarea,
    configure_search, fit_scroll_page)
from core.ui.number_input import IntegerStepper
from core.ui.record_list import EditorRecordList, RecordListModel
from core.ui.series_comparison import SeriesComparison
from parsers.netresultparam_parser import make_default_entry, parse_netresultparam_xfbin, save_netresultparam_xfbin


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class ResultFilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query, self.group = '', None

    def set_filters(self, query, group):
        self.query, self.group = query.casefold().strip(), group
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        title, subtitle, search, group, modified = self.sourceModel().rows[row]
        return (self.group is None or (modified if self.group == 'modified' else group == self.group)) and all(
            word in search for word in self.query.split())


class NetResultParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t, self._embedded = t or ui_text, embedded
        self._filepath = self._raw_data = self._result = self._session = None
        self._entries, self._fields, self._grids = [], {}, []
        self._current_idx = None
        self._dirty = self._loading_detail = False
        self._probe_values = [0, 0]
        self._probe_texts = ['0', '0']
        self._outcome, self._grade = 2, 0
        self._matched_row = None
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(150)
        self._detail_timer.timeout.connect(self._refresh_detail)
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _button(self, key, slot, *, accent=False, danger=False, compact=False):
        button = configure_button(QPushButton(ui_text(key)), accent=accent, danger=danger,
                                  height=Size.COMPACT_CONTROL if compact else Size.CONTROL)
        button.clicked.connect(slot)
        return button

    def _label(self, text):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_dim_label())
        return label

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
        self._search.setToolTip(ui_text('netresult_search_hint'))
        self._search.textChanged.connect(self._filter_list)
        side.addWidget(self._search)
        self._group_filter = EditorFilterCombo()
        for key, value in (('netresult_filter_hint', None), ('netresult_bases', 'base'),
                           ('netresult_bonuses', 'bonus'), ('trophy_filter_modified', 'modified')):
            self._group_filter.addItem(ui_text(key), value)
        self._group_filter.currentIndexChanged.connect(self._filter_list)
        side.addWidget(self._group_filter)
        actions = EditorActionRow()
        for attr, key, slot, action in (('_btn_add', 'btn_new', self._do_add, 'new'),
                ('_btn_dup', 'btn_duplicate', self._do_dup, 'duplicate'),
                ('_btn_del', 'btn_delete', self._do_del, 'delete')):
            button = self._button(key, slot, danger=action == 'delete', compact=True)
            button.setProperty('designAction', action)
            setattr(self, attr, button)
            actions.content_layout.addWidget(button, 1)
        side.addWidget(actions)
        self._catalog_model = RecordListModel(self)
        self._catalog_proxy = ResultFilterModel(self)
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
        self._show_placeholder(ui_text('ui_netresultparam_open_file_to_begin_editing'))
        self._update_actions()

    def _show_placeholder(self, text):
        self._fields, self._grids = {}, []
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(self._editor_widget,
            title=ui_text('no_file_loaded') if self._raw_data is None else ui_text('ui_netresultparam_no_entries'),
            text=text, icon_name='fa6s.chart-line'), 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_netresultparam_open_title'),
            game_files_dialog_dir(target_patterns=('NetResultParam.bin.xfbin', 'NetResultParam.xfbin')),
            ui_text('ui_netresultparam_file_filter'))
        if path:
            self._load(path)

    def _load(self, path):
        try:
            raw, result = parse_netresultparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=exc))
            return False
        if self._dirty and QMessageBox.question(self, ui_text('unsaved_changes_title'),
                ui_text('netresult_discard'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        create_backup_on_open(path)
        self._detail_timer.stop()
        self._filepath, self._raw_data, self._result = str(path), raw, result
        self._session = ResultSession(result)
        self._entries, self._current_idx, self._fields = result['entries'], None, {}
        self._dirty = False
        self._probe_values, self._outcome, self._grade = [0, 0], 2, 0
        self._probe_texts = ['0', '0']
        self._search.clear()
        self._group_filter.setCurrentIndex(0)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text('netresult_short_table'))
        self._update_actions()
        return True

    def _do_save(self, target_path=None):
        path = target_path or editor_path(self)
        if not path or self._result is None or not self._apply_current_entry(show_errors=True):
            return False
        try:
            save_netresultparam_xfbin(path, self._raw_data, self._result)
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

    def _entry_title(self, idx):
        return (ui_text('netresult_base_title', grade=GRADES[idx]) if idx < BASE_COUNT else
                ui_text('netresult_bonus_title', difference=f"{self._entries[idx]['threshold']:+,}"))

    def _entry_subtitle(self, idx):
        return ui_text('netresult_row', row=idx + 1, amount=f"{self._entries[idx]['value']:+,}")

    def _describe_row(self, index):
        title, subtitle, *_ = index.data(Qt.ItemDataRole.UserRole)
        return title, subtitle, title + '\n' + subtitle

    def _modified(self, idx):
        entry = self._entries[idx]
        return self._session.modified(entry) or self._session.original_index(entry) != idx

    def _populate_list(self):
        rows = []
        for idx, entry in enumerate(self._entries):
            title, subtitle = self._entry_title(idx), self._entry_subtitle(idx)
            search = ' '.join((title, subtitle, str(idx + 1), *(str(entry[k]) for k in FIELDS))).casefold()
            rows.append((title, subtitle, search, 'base' if idx < BASE_COUNT else 'bonus', self._modified(idx)))
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._catalog_model.reset_rows(rows)
        self._filter_list()
        del blocker

    def _filter_list(self, *_):
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._catalog_proxy.set_filters(self._search.text(), self._group_filter.currentData())
        self._sync_selection(scroll=False)
        del blocker
        self._no_matches.setVisible(bool(self._entries) and self._catalog_proxy.rowCount() == 0)

    def _sync_selection(self, scroll=True):
        source = self._catalog_model.index(self._current_idx if self._current_idx is not None else -1, 0)
        index = self._catalog_proxy.mapFromSource(source)
        self._catalog.setCurrentIndex(index)
        if scroll and index.isValid():
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

    def _card(self, title, icon='fa6s.chart-line'):
        card, grid = make_editor_grid_card(self._editor_widget, title=title, icon_name=icon)
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        self._editor_layout.addWidget(card)
        return card, grid

    def _number_field(self, caption, value, minimum, maximum, hint):
        frame, layout, _, _ = make_editor_field_shell(caption)
        edit = configure_input(QLineEdit(str(value)), monospace=True)
        edit.setProperty('messageReference', False)
        edit.setAccessibleName(caption)
        edit.setToolTip(hint)
        layout.addWidget(IntegerStepper(edit, minimum, maximum))
        configure_field(frame, edit, vertical_policy=QSizePolicy.Policy.Minimum)
        return frame, layout, edit

    def _build_editor(self, idx):
        if self._session is None or self._session.result is not self._result:
            self._session = ResultSession(self._result)
        self._loading_detail = True
        self._fields, self._grids, self._comparisons = {}, [], {}
        _clear_layout(self._editor_layout)
        entry = self._entries[idx]
        title = self._entry_title(idx) if idx < BASE_COUNT else ui_text('netresult_bonus_record_title', row=idx + 1)
        self._entry_card, grid = self._card(title)
        frames = []
        self._captions = {'threshold': ui_text('netresult_unused_threshold' if idx < BASE_COUNT else 'netresult_threshold'),
                          'value': ui_text('netresult_base_amount' if idx < BASE_COUNT else 'netresult_bonus_amount')}
        for key in FIELDS:
            hint = ui_text('netresult_unused_hint' if key == 'threshold' and idx < BASE_COUNT else
                           'netresult_threshold_hint' if key == 'threshold' else 'netresult_amount_hint')
            frame, layout, edit = self._number_field(self._captions[key], entry[key], INT32_MIN, INT32_MAX, hint)
            comparison = self._label('')
            layout.addWidget(comparison)
            comparison.hide()
            self._fields[key], self._comparisons[key] = edit, comparison
            edit.textChanged.connect(self._on_field_changed)
            frames.append(frame)
        self._grids.append((grid, frames))
        self._diagnostics = self._label('')
        self._entry_card.layout().addWidget(self._diagnostics)
        actions = EditorActionRow()
        self._btn_restore = self._button('trophy_restore', self._restore_entry)
        self._btn_restore.hide()
        self._btn_restore.setToolTip(ui_text('trophy_restore_hint'))
        self._entry_card.layout().addWidget(self._btn_restore, 0, Qt.AlignmentFlag.AlignLeft)
        self._btn_up = self._button('skill_command_up', lambda: self._move_entry(-1))
        self._btn_down = self._button('skill_command_down', lambda: self._move_entry(1))
        for button in (self._btn_up, self._btn_down):
            actions.content_layout.addWidget(button)
        self._btn_up.setToolTip(ui_text('netresult_order_hint'))
        self._btn_down.setToolTip(ui_text('netresult_order_hint'))
        actions.content_layout.addStretch()
        self._entry_card.layout().addWidget(actions)

        self._preview_card, preview_grid = self._card(ui_text('netresult_calculator'), 'fa6s.calculator')
        probe_frames, self._probes, self._probe_sliders = [], [], []
        for player in range(2):
            caption = ui_text('netresult_player_bp', player=player + 1)
            frame, controls, edit = self._number_field(caption, self._probe_values[player], 0, POINTS_MAX,
                                                      ui_text('netresult_probe_hint'))
            edit.setText(self._probe_texts[player])
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setStyleSheet(ss_slider())
            slider.setFixedHeight(Size.COMPACT_CONTROL)
            slider.setRange(0, POINTS_MAX)
            slider.setValue(self._probe_values[player])
            slider.setAccessibleName(caption)
            slider.setToolTip(ui_text('netresult_probe_hint'))
            controls.addWidget(slider)
            slider.valueChanged.connect(lambda value, target=edit: target.setText(str(value)))
            edit.textChanged.connect(self._probe_changed)
            self._probes.append(edit)
            self._probe_sliders.append(slider)
            probe_frames.append(frame)
        for caption, items, current, attr in (
                ('netresult_outcome', [('netresult_p1_wins', 2), ('netresult_p2_wins', 3), ('netresult_draw', 1)], self._outcome, '_outcome_combo'),
                ('netresult_grade', [(grade, i) for i, grade in enumerate(GRADES)], self._grade, '_grade_combo')):
            frame, layout, _, _ = make_editor_field_shell(ui_text(caption))
            combo = configure_input(QComboBox(), monospace=False)
            for key, data in items:
                combo.addItem(key if caption == 'netresult_grade' else ui_text(key), data)
            combo.setCurrentIndex(combo.findData(current))
            combo.setAccessibleName(ui_text(caption))
            combo.setToolTip(ui_text('netresult_grade_hint' if caption == 'netresult_grade' else 'netresult_outcome_hint'))
            combo.currentIndexChanged.connect(self._probe_changed)
            layout.addWidget(combo)
            configure_field(frame, combo, vertical_policy=QSizePolicy.Policy.Minimum)
            setattr(self, attr, combo)
            probe_frames.append(frame)
        self._grids.append((preview_grid, probe_frames))
        self._probe_result = self._label('')
        self._probe_result.setFont(ui_font(TypeSize.BODY))
        self._probe_result.setStyleSheet(ss_main_label())
        self._probe_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._preview_card.layout().addWidget(self._probe_result)
        self._btn_match = self._button('netresult_show_bonus', self._select_matched)
        self._preview_card.layout().addWidget(self._btn_match)
        self._preview_card.layout().addWidget(self._label(ui_text('netresult_preview_scope')))

        self._chart_card, chart_grid = self._card(ui_text('netresult_bonus_comparison'))
        self._chart = SeriesComparison(ui_text('customize_original'), ui_text('netrank_current'), ui_text('netresult_bonus_order'))
        self._chart.selected.connect(lambda row: self._select_entry(row + BASE_COUNT))
        chart_grid.addWidget(self._chart, 0, 0)
        self._chart_card.layout().addWidget(self._label(ui_text('netresult_chart_hint')))
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._refresh_detail()

    def _draft(self):
        values, errors = {}, []
        for key, edit in self._fields.items():
            try:
                values[key] = parse_integer(edit.text())
                invalid = False
            except ValueError:
                errors.append(key)
                invalid = True
            if bool(edit.property('netresultInvalid')) != invalid:
                edit.setStyleSheet(ss_input_validation(invalid))
                edit.setProperty('netresultInvalid', invalid)
        return values, errors

    def _apply_current_entry(self, show_errors=False):
        if self._current_idx is None or not self._fields:
            return True
        values, errors = self._draft()
        if errors:
            if show_errors:
                edit = self._fields[errors[0]]
                QMessageBox.warning(self, ui_text('dlg_title_warning'),
                    ui_text('netresult_invalid', field=self._captions[errors[0]], minimum=INT32_MIN, maximum=INT32_MAX))
                self._editor_scroll.ensureWidgetVisible(edit)
                edit.setFocus()
            return False
        self._entries[self._current_idx].update(values)
        return True

    def _on_field_changed(self, *_):
        if self._loading_detail:
            return
        valid = self._apply_current_entry()
        self._dirty = True
        # Never display a stale valid calculation during the debounce interval.
        self._preview_card.setEnabled(valid)
        if not valid:
            self._probe_result.setText(ui_text('netresult_pending'))
        self._update_actions()
        self._detail_timer.start()

    def _refresh_detail(self):
        if self._current_idx is None or not self._fields:
            return
        _, errors = self._draft()
        self._dirty = bool(errors) or self._session.dirty()
        idx = self._current_idx
        entry, original = self._entries[idx], self._session.original(self._entries[idx])
        for key, label in self._comparisons.items():
            label.setText(ui_text('netrank_original_value', value=original[key]) if original else ui_text('netrank_new_row'))
        self._btn_restore.setEnabled(original is not None and (bool(errors) or self._session.modified(entry)))
        self._btn_up.setEnabled(idx > 0)
        self._btn_down.setEnabled(idx + 1 < len(self._entries))
        issues = []
        if errors:
            issues.append(ui_text('netresult_pending'))
        if idx < BASE_COUNT:
            issues.append(ui_text('netresult_base_hint', grade=GRADES[idx]))
        else:
            interval = bonus_ranges(self._entries)[idx]
            issues.append(ui_text('netresult_shadowed') if interval is None else
                ui_text('netresult_interval', low=f'{interval[0]:+,}', high=f'{interval[1]:+,}'))
            if idx > BASE_COUNT and entry['threshold'] >= self._entries[idx - 1]['threshold']:
                issues.append(ui_text('netresult_order_warning'))
        origin_idx = self._session.original_index(entry)
        if origin_idx is not None and origin_idx != idx:
            issues.append(ui_text('netresult_moved', row=origin_idx + 1))
        if len(self._entries) < BASE_COUNT:
            issues.append(ui_text('netresult_short_table'))
        if any(e['value'] < 0 for e in self._entries):
            issues.append(ui_text('netresult_negative_warning'))
        self._diagnostics.setText('\n'.join(issues))
        self._preview_card.setEnabled(not errors)
        self._populate_list()
        self._chart.set_series([e['value'] for e in self._session.original_entries[BASE_COUNT:]],
                               [e['value'] for e in self._entries[BASE_COUNT:]],
                               idx - BASE_COUNT if idx >= BASE_COUNT else None)
        self._probe_changed()
        self._update_actions()

    def _probe_changed(self, *_):
        if self._loading_detail or not hasattr(self, '_probes'):
            return
        self._probe_texts = [edit.text() for edit in self._probes]
        points, invalid = [], False
        for edit, slider in zip(self._probes, self._probe_sliders):
            try:
                value = parse_integer(edit.text(), 0, POINTS_MAX)
                points.append(value)
                blocker = QSignalBlocker(slider)
                slider.setValue(value)
                del blocker
                edit.setStyleSheet(ss_input_validation(False))
            except ValueError:
                edit.setStyleSheet(ss_input_validation(True))
                invalid = True
        self._outcome, self._grade = self._outcome_combo.currentData(), self._grade_combo.currentData()
        self._grade_combo.setEnabled(self._outcome != 1)
        self._matched_row = None
        self._btn_match.setEnabled(False)
        if invalid:
            self._probe_result.setText(ui_text('netresult_probe_invalid', maximum=POINTS_MAX))
        elif self._draft()[1]:
            self._probe_result.setText(ui_text('netresult_pending'))
        else:
            self._probe_values = points
            lines = []
            for label, entries in ((ui_text('customize_original'), self._session.original_entries),
                                    (ui_text('netrank_current'), self._entries)):
                try:
                    award = calculate(entries, *points, self._outcome, self._grade)
                except ValueError:
                    lines.append(label + ': ' + ui_text('netresult_short_table'))
                    continue
                if entries is self._entries:
                    self._matched_row = award.row
                lines.append(ui_text('netresult_award', label=label,
                    delta1=f'{award.deltas[0]:+,}', total1=f'{award.totals[0]:,}',
                    delta2=f'{award.deltas[1]:+,}', total2=f'{award.totals[1]:,}'))
                if award.difference is not None:
                    lines.append(ui_text('netresult_formula', difference=f'{award.difference:+,}',
                        base=f'{award.base:+,}', bonus=f'{award.bonus:+,}',
                        row=str(award.row + 1) if award.row is not None else ui_text('netresult_no_match')))
            self._probe_result.setText('\n'.join(lines))
            self._btn_match.setEnabled(self._matched_row is not None)
        self._reflow()

    def _select_matched(self):
        if self._matched_row is not None and self._apply_current_entry(show_errors=True):
            self._search.clear()
            self._group_filter.setCurrentIndex(0)
            self._select_entry(self._matched_row)

    def _restore_entry(self):
        original = self._session.original(self._entries[self._current_idx])
        if original is None:
            return
        self._loading_detail = True
        for key, edit in self._fields.items():
            edit.setText(str(original[key]))
        self._loading_detail = False
        self._apply_current_entry()
        self._refresh_detail()

    def _insert(self, duplicate=False):
        if self._raw_data is None or not self._apply_current_entry(show_errors=True):
            return
        if duplicate and self._current_idx is None:
            return
        entry = make_default_entry(self._entries[self._current_idx] if duplicate else None)
        index = self._current_idx + 1 if duplicate else len(self._entries)
        if index < BASE_COUNT and len(self._entries) >= BASE_COUNT:
            if not self._confirm_roles():
                return
        self._entries.insert(index, entry)
        self._after_structure(index)

    def _confirm_roles(self):
        return QMessageBox.question(self, ui_text('dlg_title_warning'), ui_text('netresult_role_warning'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _after_structure(self, index):
        self._detail_timer.stop()
        self._current_idx, self._fields, self._dirty = None, {}, True
        self._search.clear()
        self._group_filter.setCurrentIndex(0)
        self._populate_list()
        if self._entries:
            self._select_entry(min(index, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text('netresult_short_table'))
        self._update_actions()

    def _move_entry(self, direction):
        if self._current_idx is None or not self._apply_current_entry(show_errors=True):
            return
        idx, target = self._current_idx, self._current_idx + direction
        if not 0 <= target < len(self._entries):
            return
        if min(idx, target) < BASE_COUNT and not self._confirm_roles():
            return
        self._entries[idx], self._entries[target] = self._entries[target], self._entries[idx]
        self._after_structure(target)

    def _do_add(self):
        self._insert()

    def _do_dup(self):
        self._insert(True)

    def _do_del(self):
        if self._current_idx is None or not self._apply_current_entry(show_errors=True):
            return
        idx = self._current_idx
        warning = ui_text('msg_confirm_delete_item', name=self._entry_title(idx))
        if idx < BASE_COUNT:
            warning += '\n\n' + ui_text('netresult_role_warning')
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'), warning,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._entries.pop(idx)
        self._after_structure(idx)

    def _update_actions(self):
        loaded, selected = self._raw_data is not None, self._current_idx is not None
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and selected)
        self._btn_del.setEnabled(loaded and selected)
        self._btn_save.setEnabled(loaded and self._dirty)
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=self._dirty)
        if hasattr(self, '_file_actions'):
            refresh_file_actions(self, loaded=loaded)

    def _reflow(self):
        for grid, frames in self._grids:
            columns = 1 if self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT else 2
            for col in range(2):
                grid.setColumnStretch(col, int(col < columns))
            for i, frame in enumerate(frames):
                row, col = divmod(i, columns)
                grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)
