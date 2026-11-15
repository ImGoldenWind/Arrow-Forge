"""Situation Finish Editor: authored stage-finish events and command inspector."""
import copy

from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QLayout,
)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.stagemotion_tools import COMMANDS, EVENT_LIMIT, FRAME_RATE, timeline_extent, unique_stage_id
from core.style_helpers import (
    make_editor_card, make_empty_state, add_editor_card_title, ss_bg_dark,
    ss_transparent, ss_dim_label, ss_error_label, ss_input_validation,
)
from core.translations import ui_text
from core.ui.editor_actions import install_file_actions, commit_save_path, editor_path
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_widgets import (
    EditorToolbar, EditorSidebar, EditorActionRow, EditorListRow, EditorSeparator,
    configure_layout, configure_button, configure_search,
    configure_scrollarea, configure_file_label, configure_card, configure_table,
)
from core.ui.event_timeline import EventTimeline, EventTimelineOverview, TimelineEvent
from core.ui.timeline_controls import TimelineZoomControls, timeline_icon_button
from core.ui.message_preview import message_lookup
from editors.stagemotion_forms import MotionForm, CommandForm, MotionFieldError, name_value, uint_value
from parsers.stagemotion_parser import parse_stagemotion_xfbin, save_stagemotion_xfbin


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def command_title(code):
    return ui_text(COMMANDS[code][0]) if code in COMMANDS else ui_text('motion_custom', p0=f'0x{code:X}')


class StageMotionEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or ui_text
        self._embedded = embedded
        self._filepath = None
        self._raw = self._result = None
        self._current_stage_idx = self._current_entry_idx = -1
        self._stage_btns = []
        self._dirty = False
        self._form = self._header_form = None
        self._baseline = {}
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    def _button(self, text, callback, layout, *, danger=False, accent=False, action=None):
        button = configure_button(QPushButton(ui_text(text)), danger=danger, accent=accent)
        button.clicked.connect(callback)
        if action:
            button.setProperty('designAction', action)
        layout.addWidget(button)
        return button

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        toolbar = EditorToolbar()
        self._btn_open = self._button('btn_open_file', self._open_file, toolbar.content_layout, accent=True, action='open')
        self._btn_save = self._button('btn_save_file', lambda: self._save_file(), toolbar.content_layout, accent=True)
        self._btn_save.setEnabled(False)
        self._file_lbl = configure_file_label(QLabel(ui_text('xfa_no_file')))
        toolbar.content_layout.addWidget(self._file_lbl, 1)
        root.addWidget(toolbar)
        root.addWidget(EditorSeparator(accent=True))
        main = configure_layout(QHBoxLayout(), LayoutRole.ROOT)
        sidebar = EditorSidebar()
        side = sidebar.content_layout
        self._search = configure_search(QLineEdit())
        self._search.textChanged.connect(self._filter_list)
        side.addWidget(self._search)
        actions = EditorActionRow()
        self._btn_add = self._button('ui_messageinfo_add', self._add_stage, actions.content_layout, action='new')
        self._btn_dup = self._button('btn_duplicate', self._dup_stage, actions.content_layout, action='duplicate')
        self._btn_del = self._button('btn_delete', self._del_stage, actions.content_layout, danger=True, action='delete')
        for button in (self._btn_add, self._btn_dup, self._btn_del):
            configure_button(button, danger=button is self._btn_del, height=Size.COMPACT_CONTROL)
            button.setEnabled(False)
        side.addWidget(actions)
        self._list_scroll = configure_scrollarea(QScrollArea(), transparent=True)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet(ss_transparent())
        self._list_layout = configure_layout(QVBoxLayout(inner), LayoutRole.LIST)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(inner)
        side.addWidget(self._list_scroll)
        main.addWidget(sidebar)
        main.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._right = QWidget()
        self._right.setMinimumWidth(0)
        self._right.setStyleSheet(ss_bg_dark())
        right = configure_layout(QVBoxLayout(self._right), LayoutRole.ROOT)
        self._placeholder_wrap = QWidget()
        self._placeholder_layout = configure_layout(QVBoxLayout(self._placeholder_wrap), LayoutRole.ROOT)
        right.addWidget(self._placeholder_wrap, 1)
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_inner = QWidget()
        self._editor_inner.setStyleSheet(ss_bg_dark())
        self._editor_inner.setMinimumWidth(0)
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_inner), LayoutRole.PAGE)
        self._editor_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._editor_scroll.setWidget(self._editor_inner)
        self._editor_scroll.hide()
        right.addWidget(self._editor_scroll, 1)
        main.addWidget(self._right, 1)
        root.addLayout(main, 1)
        self._show_placeholder(ui_text('ui_stagemotion_open_a_xcmnsfprm_bin_xfbin_file_to_begin_editing'),
                               title=ui_text('no_file_loaded'))

    def _show_placeholder(self, text, *, title=None):
        _clear_layout(self._placeholder_layout)
        self._placeholder_layout.addStretch()
        self._placeholder_layout.addWidget(make_empty_state(title=title or ui_text('ui_stageinfo_select_a_stage'),
                                                            text=text), 0, Qt.AlignmentFlag.AlignCenter)
        self._placeholder_layout.addStretch()
        self._placeholder_wrap.show()

    def _confirm_replace(self):
        if not self._dirty:
            return True
        answer = QMessageBox.question(self, ui_text('btn_save_file'), ui_text('motion_unsaved'),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                      QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Discard or (
            answer == QMessageBox.StandardButton.Save and self._save_file())

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_stagemotion_open_stage_motion_file'),
                                              game_files_dialog_dir(target_patterns='Xcmnsfprm.bin.xfbin'),
                                              'XFBIN Files (*.xfbin);;All Files (*)')
        if path:
            self._load(path)

    def _load(self, path):
        if not self._confirm_replace():
            return False
        try:
            raw, result = parse_stagemotion_xfbin(path)
            create_backup_on_open(path)
        except Exception as error:
            QMessageBox.critical(self, ui_text('dlg_title_error'),
                                 ui_text('ui_stagemotion_failed_to_parse_file_value', p0=error))
            return False
        self._raw, self._result, self._filepath = raw, result, str(path)
        self._dirty = False
        self._current_stage_idx = self._current_entry_idx = -1
        self._form = self._header_form = None
        self._baseline = {id(e): copy.deepcopy(e) for s in result['stages'] for e in s['entries']}
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        set_file_label(self._file_lbl, str(path))
        self._rebuild_stage_list()
        if result['stages']:
            self._on_stage_selected(0)
        else:
            self._btn_dup.setEnabled(False)
            self._btn_del.setEnabled(False)
            self._editor_scroll.hide()
            self._show_placeholder(ui_text('motion_empty_stages'))
        return True

    def _save_file(self, target_path=None):
        path = target_path or editor_path(self)
        # Ctrl+S need not move focus out of an editable type combo, so its
        # editingFinished signal is not a reliable commit boundary.
        if self._form is not None and self._type_combo.currentText() != self._type_value:
            self._type_changed()
        if not path or self._result is None or not self._flush_current(show_errors=True):
            return False
        try:
            save_stagemotion_xfbin(path, self._raw, self._result)
        except Exception as error:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('ui_spm_save_failed_value', p0=error))
            return False
        commit_save_path(self, str(path))
        self._dirty = False
        set_file_label(self._file_lbl, str(path))
        return True

    def _stage(self):
        return self._result['stages'][self._current_stage_idx]

    def _entry(self):
        return self._stage()['entries'][self._current_entry_idx]

    def _flush_current(self, *, show_errors=False):
        if self._header_form is None:
            return True
        try:
            header = self._header_form.collect()
            candidate = self._form.collect_entry() if self._form is not None else None
            if candidate is not None:
                try:
                    candidate['type_code'] = uint_value(self._type_combo.currentText().split(' · ')[0])
                except ValueError:
                    raise MotionFieldError(self._type_combo, ui_text('motion_invalid_field')) from None
                self._type_combo.setStyleSheet(ss_input_validation(False))
        except MotionFieldError as error:
            error.widget.setStyleSheet(ss_input_validation(True))
            if show_errors:
                self._error.setText(str(error))
                error.widget.setFocus()
                self._editor_scroll.ensureWidgetVisible(error.widget)
            return False
        self._stage().update(header)
        if candidate is not None:
            self._entry().update(candidate)
        self._error.clear()
        return True

    def _edited(self):
        self._mark_dirty()
        if self._flush_current():
            if self._form is not None and self._type_combo.currentText() != self._type_value:
                self._type_changed()
                return
            self._update_sidebar_btn(self._current_stage_idx)
            self._refresh_events(changed_row=self._current_entry_idx)

    def _mark_dirty(self):
        self._dirty = True
        set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _rebuild_stage_list(self):
        _clear_layout(self._list_layout)
        self._stage_btns = []
        for i, stage in enumerate(self._result['stages']):
            row = EditorListRow()
            row.set_texts(stage['stage_id'], f'#{i:02d}', title_limit=24)
            row.set_selected(i == self._current_stage_idx)
            row.clicked.connect(lambda _, index=i: self._on_stage_selected(index))
            self._list_layout.addWidget(row)
            self._stage_btns.append((row, i))
        self._list_layout.addStretch()
        self._filter_list()

    def _filter_list(self):
        if self._result is None:
            return
        query = self._search.text().casefold()
        for button, index in self._stage_btns:
            stage = self._result['stages'][index]
            matches = ' '.join([stage['stage_id'], f'{index:02d}', *[e['name'] for e in stage['entries']]])
            button.setVisible(not query or query in matches.casefold())

    def _update_sidebar_btn(self, index):
        if index >= 0:
            for button, i in self._stage_btns:
                if i == index:
                    button.set_texts(self._stage()['stage_id'], f'#{i:02d}', title_limit=24)
        self._filter_list()

    def _on_stage_selected(self, index):
        if not self._flush_current(show_errors=True):
            return False
        self._current_stage_idx = index
        self._current_entry_idx = -1
        self._form = self._header_form = None
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        for button, i in self._stage_btns:
            button.set_selected(i == index)
        self._placeholder_wrap.hide()
        self._editor_scroll.show()
        self._rebuild_right_panel(self._stage())
        return True

    def _card(self, title, icon, subtitle=None):
        card, layout = make_editor_card()
        configure_card(card)
        add_editor_card_title(layout, ui_text(title), icon, subtitle)
        self._editor_layout.addWidget(card)
        return card, layout

    def _rebuild_right_panel(self, stage):
        _clear_layout(self._editor_layout)
        self._form = None
        _, header = self._card('ui_stagemotion_stage_header', 'fa6s.sliders')
        self._header_form = MotionForm()
        for key, label, choices in (
            ('stage_id', 'ui_mainmodeparam_stage_id', [s['stage_id'] for s in self._result['stages']]),
            ('nut_type', 'ui_stagemotion_nut_type', [s['nut_type'] for s in self._result['stages']]),
        ):
            edit = self._header_form.add(key, ui_text(label), stage[key], ui_text('motion_name_hint'),
                                          choices=choices, reader=name_value)
            edit.currentTextChanged.connect(self._edited)
        header.addWidget(self._header_form)
        _, layout = self._card('motion_timeline', 'fa6s.timeline', ui_text('motion_timeline_hint'))
        bar = EditorActionRow()
        self._compare = self._button('motion_compare', self._compare_changed, bar.content_layout)
        self._compare.setCheckable(True)
        self._compare.setChecked(True)
        self._compare.setMinimumWidth(self._compare.sizeHint().width())
        self._timeline = EventTimeline()
        self._zoom_controls = TimelineZoomControls(self._timeline, show_fit=False)
        self._zoom_slider = self._zoom_controls.slider
        bar.content_layout.addWidget(self._zoom_controls)
        self._position = QLabel()
        self._position.setFont(ui_font(TypeSize.BODY))
        self._position.setStyleSheet(ss_dim_label())
        bar.content_layout.addWidget(self._position, 1)
        layout.addWidget(bar)
        self._timeline.selected.connect(self._select_entry)
        self._timeline.moved.connect(self._move_event)
        self._timeline.resized.connect(self._resize_caption)
        self._timeline.cursorChanged.connect(self._cursor_changed)
        layout.addWidget(self._timeline)
        navigation = EditorActionRow()
        navigation.content_layout.addWidget(timeline_icon_button(ui_text('ui_lipsync_scroll_left'), 'fa6s.chevron-left',
                                                                 lambda: self._timeline.shift_view(-1)))
        self._timeline_overview = EventTimelineOverview()
        self._timeline_overview.set_timeline(self._timeline)
        navigation.content_layout.addWidget(self._timeline_overview, 1)
        navigation.content_layout.addWidget(timeline_icon_button(ui_text('ui_lipsync_scroll_right'), 'fa6s.chevron-right',
                                                                 lambda: self._timeline.shift_view(1)))
        layout.addWidget(navigation)
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setFont(ui_font(TypeSize.BODY))
        self._warning.setStyleSheet(ss_dim_label())
        layout.addWidget(self._warning)
        _, layout = self._card('ui_stagemotion_entries', 'fa6s.list')
        actions = EditorActionRow()
        self._button('ui_messageinfo_add', self._add_entry, actions.content_layout)
        self._entry_dup = self._button('btn_duplicate', self._dup_entry_item, actions.content_layout)
        self._entry_del = self._button('btn_delete', self._del_entry, actions.content_layout, danger=True)
        layout.addWidget(actions)
        self._table = configure_table(QTableWidget(0, 4))
        self._table.setHorizontalHeaderLabels([ui_text('motion_order'), ui_text('motion_frame'),
                                                ui_text('ui_dlcinfoparam_type'), ui_text('ui_stagemotion_action_name')])
        self._table.verticalHeader().hide()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for col in (2, 3):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self._table.setFixedHeight(Size.TABLE_ROW * 6)
        self._table.currentCellChanged.connect(lambda row, *_: self._select_entry(row))
        layout.addWidget(self._table)
        actions = EditorActionRow()
        self._up = self._button('motion_up', lambda: self._reorder(-1), actions.content_layout)
        self._down = self._button('motion_down', lambda: self._reorder(1), actions.content_layout)
        self._restore = self._button('motion_restore', self._restore_entry, actions.content_layout)
        self._restore.hide()
        layout.addWidget(actions)
        self._inspector_card, self._inspector_layout = self._card('motion_event', 'fa6s.sliders')
        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setFont(ui_font(TypeSize.BODY))
        self._error.setStyleSheet(ss_error_label())
        self._editor_layout.addWidget(self._error)
        self._editor_layout.addStretch()
        self._current_entry_idx = -1
        self._refresh_events()
        if stage['entries']:
            self._select_entry(0)
        else:
            self._inspector_card.hide()
        self._cursor_changed(0)

    def _refresh_events(self, *, changed_row=None):
        entries = self._stage()['entries']
        with QSignalBlocker(self._table):
            self._table.setRowCount(len(entries))
            indices = range(len(entries)) if changed_row is None else ([changed_row] if changed_row >= 0 else [])
            for i in indices:
                entry = entries[i]
                values = [str(i), str(entry['frame']), command_title(entry['type_code']), entry['name']]
                for col, value in enumerate(values):
                    item = self._table.item(i, col)
                    if item is None:
                        item = QTableWidgetItem()
                        self._table.setItem(i, col, item)
                    item.setText(value)
                    item.setToolTip(value)
            if self._current_entry_idx >= 0:
                self._table.setCurrentCell(self._current_entry_idx, 0)
        events = [TimelineEvent(i, f'0x{e["type_code"]:04X}',
                                f'#{i} · {command_title(e["type_code"])} · {e["frame"]} · {e["name"]}',
                                e['frame'], e['val3'] if e['type_code'] == 0x84 and e['val3'] < 0x80000000 else 0,
                                self._baseline.get(id(e), {}).get('frame'), command_title(e['type_code']),
                                e['type_code'] == 0x84) for i, e in enumerate(entries[:EVENT_LIMIT])]
        extent = max(timeline_extent(entries[:EVENT_LIMIT]), max((event.original_start or 0 for event in events), default=0))
        self._timeline.set_events(events, extent, self._current_entry_idx)
        self._warning.setText(ui_text('motion_limit_hint') if len(entries) > EVENT_LIMIT else
                              ui_text('motion_empty_events') if not entries else '')
        self._warning.setVisible(bool(self._warning.text()))
        self._table.setFixedHeight(Size.TABLE_ROW * (min(5, max(1, len(entries))) + 1))
        selected = 0 <= self._current_entry_idx < len(entries)
        for button in (self._entry_dup, self._entry_del):
            button.setEnabled(selected)
        self._up.setEnabled(selected and self._current_entry_idx > 0)
        self._down.setEnabled(selected and self._current_entry_idx + 1 < len(entries))
        self._restore.setEnabled(selected and id(entries[self._current_entry_idx]) in self._baseline)

    def _select_entry(self, index):
        if index < 0 or index >= len(self._stage()['entries']):
            return False
        if index == self._current_entry_idx:
            return True
        if not self._flush_current(show_errors=True):
            with QSignalBlocker(self._table):
                self._table.setCurrentCell(self._current_entry_idx, 0)
            return False
        self._current_entry_idx = index
        self._form = None
        _clear_layout(self._inspector_layout)
        entry = self._entry()
        add_editor_card_title(self._inspector_layout, ui_text('motion_event_index', p0=index), 'fa6s.sliders')
        types = MotionForm()
        options = [f'0x{code:04X} · {command_title(code)}' for code in COMMANDS]
        value = next((text for text in options if text.startswith(f'0x{entry["type_code"]:04X} ·')),
                     f'0x{entry["type_code"]:X}')
        self._type_combo = types.add('type_code', ui_text('ui_dlcinfoparam_type'), value,
                                     ui_text('motion_type_hint'), choices=options)
        self._type_value = value
        self._type_combo.activated.connect(self._type_changed)
        self._type_combo.lineEdit().editingFinished.connect(self._type_changed)
        self._type_combo.lineEdit().textEdited.connect(self._mark_dirty)
        self._inspector_layout.addWidget(types)
        explanation = QLabel(ui_text(COMMANDS[entry['type_code']][1]) if entry['type_code'] in COMMANDS
                             else ui_text('motion_custom_hint'))
        explanation.setFont(ui_font(TypeSize.BODY))
        explanation.setStyleSheet(ss_dim_label())
        explanation.setWordWrap(True)
        self._inspector_layout.addWidget(explanation)
        self._form = CommandForm(entry, self._result['stages'], self._edited,
                                 lookup=message_lookup(self) if entry['type_code'] == 0x84 else None)
        self._inspector_layout.addWidget(self._form)
        self._inspector_card.show()
        self._timeline.cursor = entry['frame']
        self._cursor_changed(entry['frame'])
        self._refresh_events()
        self._timeline.reveal(entry['frame'])
        return True

    def _type_changed(self, *_):
        text = self._type_combo.currentText()
        if text == self._type_value:
            return
        try:
            code = uint_value(text.split(' · ')[0])
        except ValueError:
            self._flush_current(show_errors=True)
            return
        if not self._flush_current(show_errors=True):
            return
        self._entry()['type_code'] = code
        index = self._current_entry_idx
        self._current_entry_idx = -1
        self._form = None
        self._select_entry(index)
        self._mark_dirty()

    def _move_event(self, index, frame):
        if self._select_entry(index) and self._flush_current(show_errors=True):
            self._form._fields['frame'].setText(str(frame))
            self._timeline.cursor = frame
            self._cursor_changed(frame)

    def _resize_caption(self, index, duration):
        if self._select_entry(index) and self._entry()['type_code'] == 0x84 and self._flush_current(show_errors=True):
            self._form._fields[0x38].setText(str(duration))

    def _cursor_changed(self, frame):
        self._position.setText(ui_text('motion_position', p0=frame, p1=f'{frame / FRAME_RATE:.3f}'))

    def _compare_changed(self):
        self._timeline.compare = self._compare.isChecked()
        self._timeline.update()

    def _add_entry(self):
        if not self._flush_current(show_errors=True):
            return
        self._stage()['entries'].append(dict(name='', frame=0, type_code=0x44, val3=0, float_val=1.))
        self._select_entry(len(self._stage()['entries']) - 1)
        self._mark_dirty()

    def _dup_entry_item(self):
        if self._current_entry_idx < 0 or not self._flush_current(show_errors=True):
            return
        index = self._current_entry_idx + 1
        self._stage()['entries'].insert(index, copy.deepcopy(self._entry()))
        self._select_entry(index)
        self._mark_dirty()

    def _del_entry(self):
        if self._current_entry_idx < 0 or not self._flush_current(show_errors=True):
            return
        index = self._current_entry_idx
        self._stage()['entries'].pop(index)
        self._form = None
        self._current_entry_idx = -1
        self._refresh_events()
        if self._stage()['entries']:
            self._select_entry(min(index, len(self._stage()['entries']) - 1))
        else:
            self._inspector_card.hide()
        self._mark_dirty()

    def _reorder(self, direction):
        if not self._flush_current(show_errors=True):
            return
        index, entries = self._current_entry_idx, self._stage()['entries']
        target = index + direction
        if not (0 <= index < len(entries) and 0 <= target < len(entries)):
            return
        entries[index], entries[target] = entries[target], entries[index]
        self._form = None
        self._current_entry_idx = -1
        self._select_entry(target)
        self._mark_dirty()

    def _restore_entry(self):
        if self._current_entry_idx < 0:
            return
        entry = self._entry()
        baseline = self._baseline.get(id(entry))
        if baseline is None:
            return
        try:
            header = self._header_form.collect()
        except MotionFieldError as error:
            self._error.setText(str(error))
            error.widget.setFocus()
            return
        self._stage().update(header)
        # Explicit restore may discard invalid input in this command only.
        entry.clear()
        entry.update(copy.deepcopy(baseline))
        index = self._current_entry_idx
        self._form = None
        self._current_entry_idx = -1
        self._select_entry(index)
        self._mark_dirty()

    def _add_stage(self):
        if self._result is None or not self._flush_current(show_errors=True):
            return
        stages = self._result['stages']
        template = self._stage() if self._current_stage_idx >= 0 else (stages[0] if stages else None)
        stage = copy.deepcopy(template) if template else dict(nut_type='PL_ANM_NUT', sub_count=2)
        stage.update(stage_id=unique_stage_id(stages, 'SF_NEW_STAGE'), entries=[])
        stages.append(stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(stages) - 1)
        self._mark_dirty()

    def _dup_stage(self):
        if self._current_stage_idx < 0 or not self._flush_current(show_errors=True):
            return
        stages = self._result['stages']
        stage = copy.deepcopy(self._stage())
        stage['stage_id'] = unique_stage_id(stages, stage['stage_id'][:26] + '_copy')
        stages.append(stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(stages) - 1)
        self._mark_dirty()

    def _del_stage(self):
        if self._current_stage_idx < 0:
            return
        answer = QMessageBox.question(self, ui_text('ui_stagemotion_remove_stage'),
                                      ui_text('ui_stagemotion_remove_stage_value_and_all_its_entries',
                                              p0=self._stage()['stage_id']),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        index = self._current_stage_idx
        self._result['stages'].pop(index)
        self._form = self._header_form = None
        self._current_stage_idx = self._current_entry_idx = -1
        self._rebuild_stage_list()
        self._btn_dup.setEnabled(False)
        self._btn_del.setEnabled(False)
        if self._result['stages']:
            self._on_stage_selected(min(index, len(self._result['stages']) - 1))
        else:
            self._editor_scroll.hide()
            self._show_placeholder(ui_text('motion_empty_stages'))
        self._mark_dirty()
