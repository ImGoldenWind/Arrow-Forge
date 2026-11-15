from __future__ import annotations

import copy
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QGridLayout, QScrollArea, QFileDialog, QMessageBox, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.style_helpers import (
    make_editor_card, add_editor_card_title, make_editor_field_shell,
    make_empty_state, ss_transparent, ss_bg_dark, ss_dim_label,
    ss_input_validation,
)
from core.ui.editor_widgets import (
    EditorToolbar, EditorSidebar, EditorActionRow, EditorListRow,
    EditorSeparator, EditorFilterCombo, configure_layout, configure_button,
    configure_input, configure_search, configure_scrollarea,
    configure_file_label, configure_table,
)
from core.ui.value_combo import EditorValueCombo
from core.ui.vector_comparison import VectorComparison
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import install_file_actions, commit_save_path, refresh_file_actions, editor_path
from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.translations import ui_text, current_language
from core.message_text import MessageText
from core.hit_reactions import entry_name
from core.gimmick_damage import (
    FLAG_OFFSETS, word_text, parse_word, validate_identifier,
    flag_indices, launch_velocity, row_issues, reference_candidates, signed,
)
from core.stage_tools import float32_text
from parsers.gimmickdmgparam_parser import (
    load_gimmickdmgparam_xfbin, save_gimmickdmgparam_xfbin, make_default_entry,
    word_to_float,
)
from parsers.damageprm_parser import parse_damageprm_xfbin


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


class GimmickDmgParamEditor(QWidget):
    _load_done_signal = pyqtSignal(str, object, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self.t = t or ui_text
        self._filepath = self._xfbin = self._item = None
        self._current_idx = -1
        self._dirty = self._busy = False
        self._snapshots = []
        self._reactions, self._reaction_path = {}, ''
        self._stage_names = {}
        self._entry_buttons = []
        self._record_fields, self._header_fields = {}, {}
        self._initial_text = {}
        self._grids = []
        self._cards = []
        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._reflow)
        self.setStyleSheet(ss_transparent())
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        toolbar = EditorToolbar(self)
        self._open_btn = configure_button(QPushButton(self.t('btn_open_file')), accent=True)
        self._open_btn.setProperty('designAction', 'open')
        self._open_btn.clicked.connect(self._load_file)
        self._save_btn = configure_button(QPushButton(self.t('btn_save_file')), accent=True)
        self._save_btn.clicked.connect(lambda: self._save_file())
        self._save_btn.setEnabled(False)
        self._file_label = configure_file_label(QLabel(self.t('no_file_loaded')))
        for button in (self._open_btn, self._save_btn):
            toolbar.content_layout.addWidget(button)
        toolbar.content_layout.addWidget(self._file_label, 1)
        root.addWidget(toolbar)
        root.addWidget(EditorSeparator(accent=True))
        body = QWidget()
        layout = configure_layout(QHBoxLayout(body), LayoutRole.ROOT)
        side = EditorSidebar(width=300)
        self._search = configure_search(QLineEdit())
        self._search.textChanged.connect(self._filter_entries)
        side.content_layout.addWidget(self._search)
        self._stage_filter = EditorFilterCombo()
        self._stage_filter.addItem(self.t('ui_gimmickdmg_stage_id'), None)
        self._stage_filter.currentIndexChanged.connect(self._filter_entries)
        side.content_layout.addWidget(self._stage_filter)
        actions = EditorActionRow()
        self._add_btn = configure_button(QPushButton(self.t('btn_new')), height=Size.COMPACT_CONTROL)
        self._dup_btn = configure_button(QPushButton(self.t('btn_duplicate')), height=Size.COMPACT_CONTROL)
        self._del_btn = configure_button(QPushButton(self.t('btn_delete')), danger=True, height=Size.COMPACT_CONTROL)
        for button, action, callback in (
            (self._add_btn, 'new', self._add_entry),
            (self._dup_btn, 'duplicate', self._duplicate_entry),
            (self._del_btn, 'delete', self._delete_entry),
        ):
            button.setProperty('designAction', action)
            button.clicked.connect(callback)
            actions.content_layout.addWidget(button, 1)
        side.content_layout.addWidget(actions)
        self._entry_scroll = configure_scrollarea(QScrollArea(), transparent=True)
        self._entry_list_widget = QWidget()
        self._entry_list_layout = configure_layout(QVBoxLayout(self._entry_list_widget), LayoutRole.LIST)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        side.content_layout.addWidget(self._entry_scroll, 1)
        layout.addWidget(side)
        layout.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        layout.addWidget(self._editor_scroll, 1)
        root.addWidget(body, 1)
        install_file_actions(self, self._save_btn, save_to=self._save_file)
        install_editor_chrome(self)
        self._set_controls_enabled()
        self._show_placeholder()

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        self._record_fields = {}
        self._grids, self._cards = [], []
        card = make_empty_state(title=self.t('no_file_loaded'),
                                text=self.t('ui_gimmickdmg_open_file_to_begin_editing'), icon_name='fa6s.bomb')
        self._editor_layout.addStretch(1)
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch(1)

    def _load_file(self, path=None):
        if self._busy:
            return False
        if not self._apply_editor_fields():
            return False
        if self._dirty and QMessageBox.question(self, self.t('unsaved_changes_title'),
                                                self.t('gdm_discard')) != QMessageBox.StandardButton.Yes:
            return False
        direct = isinstance(path, (str, Path))
        if not direct:
            path, _ = QFileDialog.getOpenFileName(self, self.t('ui_gimmickdmg_open_title'),
                game_files_dialog_dir(target_patterns='gimmickDmgParam.bin.xfbin'), self.t('ui_gimmickdmg_file_filter'))
        if not path:
            return False
        self._busy = True
        self._set_controls_enabled()
        game_dir = load_settings().get('game_files_dir', '')
        language = current_language()

        def read():
            xfbin, item = load_gimmickdmgparam_xfbin(str(path))
            refs = ({}, '')
            for candidate in reference_candidates(path, 'damageprm.bin.xfbin', game_dir):
                try:
                    _, result = parse_damageprm_xfbin(candidate)
                    refs = (self._reaction_map(result), str(candidate))
                    break
                except (OSError, ValueError, IndexError):
                    continue
            neighboring_data = Path(path).resolve().parent / 'data'
            messages = MessageText(str(path), language,
                                   str(neighboring_data) if neighboring_data.is_dir() else game_dir)
            names = {stage: text for stage in {entry.stage_id for entry in item.entries if entry.stage_id}
                     if (text := messages.text(stage)[0])}
            create_backup_on_open(str(path))
            return xfbin, item, (*refs, names)

        if direct:
            try:
                xfbin, item, refs = read()
            except Exception as exc:
                self._on_load_error(str(exc))
                return False
            self._on_load_done(str(path), xfbin, item, refs)
            return True

        def worker():
            try:
                xfbin, item, refs = read()
                self._load_done_signal.emit(str(path), xfbin, item, refs)
            except Exception as exc:
                self._load_error_signal.emit(str(exc))
        threading.Thread(target=worker, daemon=True).start()
        return True

    @staticmethod
    def _reaction_map(result):
        # The game's named map resolves the last definition, like its loader.
        return {entry['name']: entry for entry in result['entries']}

    def _on_load_done(self, path, xfbin, item, references=None):
        self._filepath, self._xfbin, self._item = path, xfbin, item
        references = references or ({}, '')
        self._reactions, self._reaction_path = references[:2]
        self._stage_names = references[2] if len(references) > 2 else {}
        self._snapshots = copy.deepcopy(item.entries)
        self._current_idx = 0 if item.entries else -1
        self._dirty = self._busy = False
        with QSignalBlocker(self._search):
            self._search.clear()
        with QSignalBlocker(self._stage_filter):
            self._stage_filter.setCurrentIndex(0)
        self._update_stage_filter()
        self._rebuild_entry_list()
        self._build_editor()
        self._set_controls_enabled()
        set_file_label(self._file_label, path, dirty=False)

    def _on_load_error(self, message):
        self._busy = False
        self._set_controls_enabled()
        QMessageBox.critical(self, self.t('dlg_title_error'), message)

    def _set_controls_enabled(self, enabled=True):
        loaded = self._item is not None and not self._busy and enabled
        self._open_btn.setEnabled(not self._busy)
        self._add_btn.setEnabled(loaded)
        self._dup_btn.setEnabled(loaded and self._current_idx >= 0)
        self._del_btn.setEnabled(loaded and self._current_idx >= 0)
        self._save_btn.setEnabled(loaded and self._dirty)
        self._editor_scroll.setEnabled(not self._busy)
        self._entry_scroll.setEnabled(not self._busy)
        refresh_file_actions(self, loaded=self._item is not None)

    def _save_file(self, target_path=None):
        path = target_path or editor_path(self)
        if self._busy or self._item is None or not path or not self._apply_editor_fields():
            return False
        try:
            save_gimmickdmgparam_xfbin(self._xfbin, str(path), self._item)
        except Exception as exc:
            QMessageBox.critical(self, self.t('dlg_title_error'), self.t('msg_save_error', error=exc))
            return False
        self._snapshots = copy.deepcopy(self._item.entries)
        if 0 <= self._current_idx < len(self._item.entries) and self._record_fields:
            self._form_entry = copy.deepcopy(self._item.entries[self._current_idx])
            self._initial_text = {key: self._text(edit) for key, edit in self._record_fields.items()}
        self._dirty = False
        commit_save_path(self, str(path))
        set_file_label(self._file_label, str(path), dirty=False)
        self._set_controls_enabled()
        self._refresh_summary()
        return True

    def _update_stage_filter(self):
        options = tuple((stage, self._stage_caption(stage)) for stage in
                        sorted({entry.stage_id for entry in self._item.entries if entry.stage_id})) if self._item else ()
        if options == getattr(self, '_stage_options', None):
            if hasattr(self._search, '_design_filter_reset'):
                self._search._design_filter_reset.refresh()
            return
        self._stage_options = options
        old = self._stage_filter.currentData()
        self._stage_filter.blockSignals(True)
        self._stage_filter.clear()
        self._stage_filter.addItem(self.t('ui_gimmickdmg_stage_id'), None)
        for stage, caption in options:
            self._stage_filter.addItem(caption, stage)
        self._stage_filter.setCurrentIndex(max(0, self._stage_filter.findData(old)))
        self._stage_filter.blockSignals(False)
        if hasattr(self._search, '_design_filter_reset'):
            self._search._design_filter_reset.refresh()

    def _reaction_caption(self, identifier):
        if identifier in self._reactions:
            return entry_name(self._reactions[identifier], self.t)
        return identifier

    def _stage_caption(self, identifier):
        return self._stage_names.get(identifier, identifier)

    def _rebuild_entry_list(self, filter_text=None):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []
        if self._item:
            for idx, entry in enumerate(self._item.entries):
                button = EditorListRow()
                button.set_texts(self._stage_caption(entry.stage_id) or self.t('ui_gimmickdmg_blank_stage'),
                                 self._reaction_caption(entry.damage_id) or self.t('ui_gimmickdmg_blank_damage'),
                                 title_limit=26, subtitle_limit=32)
                button.setToolTip(f'{entry.stage_id}\n{entry.damage_id}')
                button.set_selected(idx == self._current_idx)
                button.clicked.connect(lambda _=False, i=idx: self._select_entry(i))
                self._entry_list_layout.addWidget(button)
                self._entry_buttons.append((idx, button))
        self._entry_list_layout.addStretch()
        self._filter_entries()

    def _filter_entries(self, *_):
        if self._item is None:
            return
        query = self._search.text().casefold().strip()
        stage = self._stage_filter.currentData()
        for idx, button in self._entry_buttons:
            if idx >= len(self._item.entries):
                button.hide()
                continue
            entry = self._item.entries[idx]
            hay = f'{entry.stage_id} {self._stage_caption(entry.stage_id)} {entry.damage_id} {self._reaction_caption(entry.damage_id)} {idx}'.casefold()
            button.setVisible((not query or query in hay) and (stage is None or entry.stage_id == stage))
            button.set_selected(idx == self._current_idx)

    def _select_entry(self, idx):
        if self._busy or self._item is None or not 0 <= idx < len(self._item.entries):
            return False
        if not self._apply_editor_fields():
            return False
        self._current_idx = idx
        self._build_editor()
        self._filter_entries()
        return True

    def _card(self, title, hint='', icon='fa6s.sliders'):
        panel, layout = make_editor_card(self._editor_widget)
        add_editor_card_title(layout, self.t(title), icon, self.t(hint) if hint else None)
        self._editor_layout.addWidget(panel)
        self._cards.append(panel)
        return layout

    def _grid(self, layout, fields, maximum=3):
        grid = configure_layout(QGridLayout(), LayoutRole.GRID)
        layout.addLayout(grid)
        self._grids.append((grid, fields, maximum))

    def _field(self, key, caption, value, hint='', choices=None, caption_text=None):
        frame, layout, label, _ = make_editor_field_shell(caption_text if caption_text is not None else self.t(caption))
        frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if choices is not None:
            edit = EditorValueCombo(choices, value)
            signal = edit.currentTextChanged
        else:
            edit = configure_input(QLineEdit(str(value)), monospace=True)
            signal = edit.textChanged
        edit.setMinimumWidth(0)
        edit.setProperty('messageReference', False)
        edit.setAccessibleName(label.text())
        edit.setToolTip(self.t(hint) if hint else label.text())
        edit._gdm_hint = edit.toolTip()
        layout.addWidget(edit)
        self._record_fields[key] = edit
        self._initial_text[key] = self._text(edit)
        signal.connect(self._on_record_changed)
        return frame

    @staticmethod
    def _text(edit):
        return edit.value_text() if isinstance(edit, EditorValueCombo) else edit.text()

    def _build_editor(self):
        if self._item is None or self._current_idx < 0:
            self._show_placeholder()
            return
        _clear_layout(self._editor_layout)
        self._record_fields, self._initial_text = {}, {}
        self._grids, self._cards = [], []
        entry = self._item.entries[self._current_idx]
        self._form_entry = copy.deepcopy(entry)
        layout = self._card('gdm_identity', 'gdm_identity_hint', 'fa6s.link')
        stages = sorted({e.stage_id for e in self._item.entries if e.stage_id})
        reactions = sorted(set(self._reactions) | {e.damage_id for e in self._item.entries if e.damage_id})
        self._grid(layout, [
            self._field('stage_id', 'ui_gimmickdmg_stage_id', entry.stage_id,
                        'gdm_stage_hint', [(s, f'{self._stage_names[s]} · {s}' if s in self._stage_names else s)
                                           for s in stages]),
            self._field('damage_id', 'gdm_reaction', entry.damage_id, 'gdm_reaction_hint',
                        [(s, f'{self._reaction_caption(s)} · {s}') for s in reactions]),
        ], 2)
        self._status = self._note('')
        layout.addWidget(self._status)
        self._reference_label = self._note(self.t('gdm_reference_source', path=self._reaction_path)
                                           if self._reaction_path else self.t('gdm_missing_reference'))
        layout.addWidget(self._reference_label)
        button = configure_button(QPushButton(self.t('gdm_choose_reactions')))
        button.clicked.connect(self._choose_reactions)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)

        layout = self._card('gdm_impact', 'gdm_impact_hint', 'fa6s.burst')
        self._grid(layout, [self._number(entry, off, key, hint) for off, key, hint in (
            (0x10, 'gdm_damage', 'gdm_damage_hint'),
            (0x14, 'gdm_forward_scale', 'gdm_scale_hint'),
            (0x18, 'gdm_up_scale', 'gdm_scale_hint'),
        )])
        self._comparison = configure_table(QTableWidget(3, 3))
        self._comparison.setHorizontalHeaderLabels([self.t('gdm_quantity'), self.t('gdm_saved'), self.t('gdm_current')])
        self._comparison.verticalHeader().hide()
        self._comparison.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._comparison.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._comparison.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._comparison.setFixedHeight(self._comparison.horizontalHeader().sizeHint().height()
                                        + Size.TABLE_ROW * 3 + self._comparison.frameWidth() * 2)
        layout.addWidget(self._comparison)
        self._velocity_plot = VectorComparison(self.t('gdm_axis_forward'), self.t('gdm_axis_up'),
            self.t('gdm_saved'), self.t('gdm_current'), self.t('gdm_no_velocity'))
        self._velocity_plot.setToolTip(self.t('gdm_velocity_limit'))
        layout.addWidget(self._velocity_plot)
        layout.addWidget(self._note(self.t('gdm_velocity_limit')))

        layout = self._card('gdm_secondary', 'gdm_secondary_hint', 'fa6s.wand-magic-sparkles')
        fields = [self._field('value_20', 'gdm_effect_kind', word_text(entry.words[8], 0x20), 'gdm_effect_kind_hint',
                    [('0', self.t('gdm_effect_off')), ('1', self.t('gdm_effect_kind_one'))])]
        fields += [self._number(entry, off, 'gdm_effect_argument', 'gdm_effect_argument_hint', argument=n)
                   for n, off in enumerate((0x24, 0x28, 0x2C, 0x30, 0x34), 1)]
        self._grid(layout, fields)

        layout = self._card('gdm_flags', 'gdm_flags_hint', 'fa6s.flag')
        choices = [('-1', self.t('gdm_flag_unused'))] + [(str(n), self.t('gdm_flag_index', index=n)) for n in range(128)]
        fields = [self._field(f'value_{off:02x}', 'gdm_flag_slot', word_text(entry.words[off // 4], off),
                              'gdm_flag_slot_hint', choices) for off in FLAG_OFFSETS]
        for n, field in enumerate(fields, 1):
            text = self.t('gdm_flag_slot_number', index=n)
            field.layout().itemAt(0).widget().setText(text)
            self._record_fields[f'value_{FLAG_OFFSETS[n - 1]:02x}'].setAccessibleName(text)
        self._grid(layout, fields)
        self._flag_summary = self._note('')
        layout.addWidget(self._flag_summary)
        layout = self._card('gdm_additional', 'gdm_additional_hint')
        self._grid(layout, [self._number(entry, off, key, hint) for off, key, hint in (
            (0x1C, 'gdm_contact_value', 'gdm_contact_hint'),
            (0x38, 'gdm_hit_value', 'gdm_hit_hint'),
        )])
        self._editor_layout.addStretch()
        self._refresh_summary()
        self._reflow()

    def _number(self, entry, off, caption, hint, **kwargs):
        return self._field(f'value_{off:02x}', caption, word_text(entry.words[off // 4], off), hint,
                           caption_text=self.t(caption, **kwargs))

    def _note(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_dim_label())
        return label

    def _apply_editor_fields(self, focus_error=True):
        if self._item is None or self._current_idx < 0 or not self._record_fields:
            return True
        entry = self._item.entries[self._current_idx]
        pending = copy.deepcopy(self._form_entry)
        invalid = []
        for key, edit in self._record_fields.items():
            text = self._text(edit)
            try:
                if text == self._initial_text[key]:
                    value = None  # Preserve noncanonical float/NaN bits unchanged.
                elif key in ('stage_id', 'damage_id'):
                    value = validate_identifier(text)
                else:
                    off = int(key.removeprefix('value_'), 16)
                    value = parse_word(text, off)
                    if off in FLAG_OFFSETS and signed(value) >= 128:
                        raise ValueError('gdm_invalid_flag')
                if value is not None:
                    if key in ('stage_id', 'damage_id'):
                        setattr(pending, key, value)
                        if not value:
                            index = 0 if key == 'stage_id' else 2
                            pending.words[index:index + 2] = [0, 0]
                    else:
                        pending.words[int(key.removeprefix('value_'), 16) // 4] = value
                edit.setStyleSheet(ss_input_validation(False))
                edit.setToolTip(edit._gdm_hint + ('\n' + text if isinstance(edit, EditorValueCombo) else ''))
            except ValueError as exc:
                edit.setStyleSheet(ss_input_validation(True))
                edit.setToolTip(self.t(str(exc)))
                invalid.append(edit)
        if invalid:
            if focus_error:
                invalid[0].setFocus()
            return False
        if pending != entry:
            self._item.entries[self._current_idx] = pending
            self._mark_dirty()
        return True

    def _on_record_changed(self, *_):
        valid = self._apply_editor_fields(focus_error=False)
        if not valid:
            self._mark_dirty()
            self._status.setText(self.t('gdm_pending_invalid'))
            self._velocity_plot.set_vectors(None, None)
            for row in range(3):
                self._comparison.setItem(row, 2, QTableWidgetItem('—'))
        else:
            self._refresh_summary()
            self._refresh_current_button()
        self._fit_timer.start(0)

    def _refresh_current_button(self):
        entry = self._item.entries[self._current_idx]
        self._update_stage_filter()
        for idx, button in self._entry_buttons:
            if idx == self._current_idx:
                button.set_texts(self._stage_caption(entry.stage_id) or self.t('ui_gimmickdmg_blank_stage'),
                    self._reaction_caption(entry.damage_id) or self.t('ui_gimmickdmg_blank_damage'),
                    title_limit=26, subtitle_limit=32)
                button.setToolTip(f'{entry.stage_id}\n{entry.damage_id}')
        self._filter_entries()

    def _refresh_summary(self):
        if not self._record_fields or self._item is None:
            return
        entry = self._item.entries[self._current_idx]
        issues = row_issues(entry, self._item.entries, self._reactions)
        self._status.setText('\n'.join(self.t(key) for key in issues) or self.t('gdm_links_ready'))
        self._flag_summary.setText(self.t('gdm_flag_summary', flags=', '.join(map(str, flag_indices(entry))) or '—'))
        saved = self._snapshots[self._current_idx] if self._current_idx < len(self._snapshots) else None
        vectors = []
        for column, row in ((1, saved), (2, entry)):
            values = ['—'] * 3
            vector = None
            if row is not None:
                values[0] = float32_text(word_to_float(row.words[4]))
                reaction = self._reactions.get(row.damage_id)
                if reaction:
                    vector = launch_velocity(row, reaction)
                    values[1:] = [float32_text(v) for v in vector]
            vectors.append(vector)
            for index, text in enumerate(values):
                self._comparison.setItem(index, column, QTableWidgetItem(text))
        self._velocity_plot.set_vectors(*vectors)
        for index, key in enumerate(('gdm_damage', 'gdm_forward_contribution', 'gdm_up_contribution')):
            self._comparison.setItem(index, 0, QTableWidgetItem(self.t(key)))

    def _choose_reactions(self):
        if not self._apply_editor_fields():
            return False
        path, _ = QFileDialog.getOpenFileName(self, self.t('gdm_choose_reactions'),
                     game_files_dialog_dir(target_patterns='damageprm.bin.xfbin'), 'XFBIN (*.xfbin)')
        if not path:
            return False
        try:
            _, result = parse_damageprm_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, self.t('dlg_title_error'), str(exc))
            return False
        self._reactions, self._reaction_path = self._reaction_map(result), path
        self._build_editor()
        self._rebuild_entry_list()
        return True

    def _reflow(self):
        if not self._cards:
            return
        width = self._editor_scroll.viewport().width() - Size.PAGE_INSET * 2
        for grid, fields, maximum in self._grids:
            columns = min(maximum, 3 if width >= 850 else 2 if width >= 580 else 1)
            while grid.count():
                grid.takeAt(0)
            for col in range(maximum):
                grid.setColumnStretch(col, int(col < columns))
                grid.setColumnMinimumWidth(col, 0)
            for index, field in enumerate(fields):
                grid.addWidget(field, index // columns, index % columns)
        for card in self._cards:
            layout = card.layout()
            layout.invalidate()
            height = layout.totalHeightForWidth(max(1, width))
            if height > 0:
                card.setFixedHeight(height)
        self._editor_layout.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_timer.start(0)

    def _add_entry(self):
        return self._insert_entry(False)

    def _duplicate_entry(self):
        return self._insert_entry(True)

    def _insert_entry(self, duplicate):
        if self._item is None or self._busy or not self._apply_editor_fields():
            return False
        source = self._item.entries[self._current_idx] if duplicate and self._current_idx >= 0 else None
        entry = make_default_entry(source)
        if not duplicate:
            used = {e.stage_id for e in self._item.entries}
            base, suffix = entry.stage_id, 1
            while entry.stage_id in used:
                entry.stage_id = f'{base}_{suffix}'
                suffix += 1
        index = self._current_idx + 1 if self._current_idx >= 0 else len(self._item.entries)
        self._item.entries.insert(index, entry)
        self._snapshots.insert(index, None)
        self._current_idx = index
        self._update_stage_filter()
        self._rebuild_entry_list()
        self._build_editor()
        self._mark_dirty()
        self._set_controls_enabled()
        return True

    def _delete_entry(self):
        if self._busy or self._item is None or not self._apply_editor_fields() or self._current_idx < 0:
            return False
        if len(self._item.entries) <= 1:
            QMessageBox.warning(self, self.t('dlg_title_warning'), self.t('ui_gimmickdmg_cannot_delete_last_entry'))
            return False
        entry = self._item.entries[self._current_idx]
        if QMessageBox.question(self, self.t('dlg_title_confirm_delete'),
            self.t('ui_gimmickdmg_delete_entry_confirm', stage=entry.stage_id)) != QMessageBox.StandardButton.Yes:
            return False
        self._item.entries.pop(self._current_idx)
        self._snapshots.pop(self._current_idx)
        self._current_idx = min(self._current_idx, len(self._item.entries) - 1)
        self._update_stage_filter()
        self._rebuild_entry_list()
        self._build_editor()
        self._mark_dirty()
        return True

    def _mark_dirty(self):
        self._dirty = True
        self._save_btn.setEnabled(not self._busy)
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=True)
