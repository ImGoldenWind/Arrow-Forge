"""Story Mode editor using the shared Arrow Forge editor components."""
import threading

from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QCompleter,
    QScrollArea, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox,
)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label, set_file_label_empty
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.story_tools import (character_name, part_name, type_name, panel_title,
                              load_rules, rule_name, panel_issues)
from core.style_helpers import (
    make_editor_card, make_editor_grid_card, make_editor_field_shell,
    add_editor_card_title, make_empty_state, ss_bg_dark, ss_transparent,
    ss_dim_label, ss_input_validation,
)
from core.translations import ui_text, TRANSLATIONS
from core.ui.editor_actions import install_file_actions, commit_save_path, editor_path
from core.ui.editor_chrome import install_editor_chrome, capture_pending_fields
from core.ui.editor_widgets import (
    EditorToolbar, EditorSidebar, EditorSeparator, EditorActionRow,
    EditorListRow, EditorFilterCombo, configure_layout, configure_button,
    configure_input, configure_search, configure_file_label,
    configure_scrollarea, configure_card, configure_field,
)
from parsers.mainmodeparam_parser import (
    parse_mainmodeparam, save_mainmodeparam, make_default_panel, _F,
)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class MainModeParamEditor(QWidget):
    _sig_done = pyqtSignal(str, object, object)
    _sig_error = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or ui_text
        self._raw = self._result = self._filepath = None
        self._panels = []
        self._items = []
        self._fields = {}
        self._field_labels = {}
        self._rules = {}
        self._catalog_status = ''
        self._current = -1
        self._last_editor_compact = None
        self._dirty = False
        self._busy = False
        self._building = False
        self._sig_done.connect(self._on_load_done)
        self._sig_error.connect(self._on_load_error)
        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())
        toolbar = EditorToolbar()
        self._open_btn = configure_button(QPushButton(self.t('btn_open_file')), accent=True)
        self._open_btn.setProperty('designAction', 'open')
        self._open_btn.clicked.connect(self._load_file)
        self._save_btn = configure_button(QPushButton(self.t('btn_save_file')), accent=True)
        self._save_btn.clicked.connect(lambda: self._save_file())
        self._save_btn.setEnabled(False)
        self._file_lbl = configure_file_label(QLabel())
        toolbar.content_layout.addWidget(self._open_btn)
        toolbar.content_layout.addWidget(self._save_btn)
        toolbar.content_layout.addWidget(self._file_lbl, 1)
        set_file_label_empty(self._file_lbl, self.t('no_file_loaded'))
        root.addWidget(toolbar)
        root.addWidget(EditorSeparator(accent=True))
        main = QWidget()
        layout = configure_layout(QHBoxLayout(main), LayoutRole.ROOT)
        sidebar = EditorSidebar(width=306)
        body = sidebar.content_layout
        self._search = configure_search(QLineEdit())
        self._search.textChanged.connect(self._filter_list)
        body.addWidget(self._search)
        self._part_filter = EditorFilterCombo()
        self._type_filter = EditorFilterCombo()
        for combo, caption in ((self._part_filter, 'ui_mainmodeparam_part_jojo_arc'),
                               (self._type_filter, 'ui_mainmodeparam_panel_type')):
            combo.addItem(ui_text(caption), None)
            combo.currentIndexChanged.connect(self._filter_list)
            body.addWidget(combo)
        actions = EditorActionRow()
        for attr, key, callback, action in (
            ('_add_btn', 'btn_new', self._add_panel, 'new'),
            ('_dup_btn', 'btn_duplicate', self._duplicate_panel, 'duplicate'),
            ('_del_btn', 'btn_delete', self._delete_panel, 'delete'),
        ):
            button = configure_button(QPushButton(self.t(key)), height=Size.COMPACT_CONTROL,
                                      danger=action == 'delete')
            button.setEnabled(False)
            button.setProperty('designAction', action)
            button.clicked.connect(callback)
            actions.content_layout.addWidget(button, 1)
            setattr(self, attr, button)
        body.addWidget(actions)
        self._list_scroll = configure_scrollarea(QScrollArea(), transparent=True)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_inner = QWidget()
        self._list_inner.setStyleSheet(ss_transparent())
        self._list_layout = configure_layout(QVBoxLayout(self._list_inner), LayoutRole.LIST)
        self._list_scroll.setWidget(self._list_inner)
        body.addWidget(self._list_scroll, 1)
        layout.addWidget(sidebar)
        layout.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)
        self._show_placeholder()

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._editor_layout.addStretch()
        card = make_empty_state(title=ui_text('story_no_panels') if self._result is not None else ui_text('no_file_loaded'),
                                text=ui_text('story_add_hint') if self._result is not None else ui_text('ui_mainmodeparam_open_a_mainmodeparam_bin_xfbin_file_to_begin_editing'))
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _load_file(self):
        if not self._flush_panel(report=True):
            return
        if self._dirty and QMessageBox.question(
                self, ui_text('dlg_title_warning'), ui_text('story_discard'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t('file_open_mainmodeparam'),
            game_files_dialog_dir(target_patterns='MainModeParam.bin.xfbin'),
            'XFBIN files (*.xfbin);;All files (*.*)')
        if not path:
            return
        create_backup_on_open(path)
        self._busy = True
        self._open_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._editor_widget.setEnabled(False)
        self._list_inner.setEnabled(False)
        for button in (self._add_btn, self._dup_btn, self._del_btn):
            button.setEnabled(False)
        self._file_actions.refresh()

        def worker():
            try:
                raw, result = parse_mainmodeparam(path)
                self._sig_done.emit(path, raw, result)
            except Exception as error:
                self._sig_error.emit(str(error))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_loading(self):
        self._busy = False
        self._open_btn.setEnabled(True)
        self._editor_widget.setEnabled(True)
        self._list_inner.setEnabled(True)
        loaded = self._result is not None
        self._save_btn.setEnabled(loaded)
        self._add_btn.setEnabled(loaded)
        self._dup_btn.setEnabled(self._current >= 0)
        self._del_btn.setEnabled(self._current >= 0)
        self._file_actions.refresh()

    def _on_load_done(self, path, raw, result):
        self._raw, self._result, self._filepath = raw, result, path
        self._panels = result['panels']
        self._current = -1
        self._fields = {}
        self._dirty = False
        self._busy = False
        self._rules, self._catalog_status = load_rules(path)
        set_file_label(self._file_lbl, path)
        self._clear_filters()
        self._rebuild_list()
        if self._panels:
            self._select_panel(0)
        else:
            self._show_placeholder()
        self._finish_loading()

    def _on_load_error(self, message):
        self._finish_loading()
        QMessageBox.critical(self, ui_text('dlg_title_error'), self.t('msg_load_error', error=message))

    def _save_file(self, target_path=None):
        if self._busy or self._result is None or not self._flush_panel(report=True):
            return False
        path = target_path or editor_path(self)
        if not path:
            return False
        try:
            save_mainmodeparam(path, self._raw, self._result)
        except Exception as error:
            QMessageBox.critical(self, ui_text('dlg_title_error'), self.t('msg_save_error', error=error))
            return False
        self._dirty = False
        commit_save_path(self, path)
        set_file_label(self._file_lbl, path)
        QMessageBox.information(self, ui_text('dlg_title_success'), self.t('msg_save_success', path=path))
        return True

    def _mark_dirty(self):
        if self._building:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _clear_filters(self):
        self._search.clear()
        self._part_filter.setCurrentIndex(0)
        self._type_filter.setCurrentIndex(0)

    def _rebuild_list(self, keep_scroll=False):
        scroll = self._list_scroll.verticalScrollBar().value() if keep_scroll else 0
        _clear_layout(self._list_layout)
        self._items = []
        self._refresh_filter_options()
        for index, panel in enumerate(self._panels):
            item = EditorListRow()
            item.set_texts(panel_title(panel), self._panel_subtitle(panel), title_limit=27, subtitle_limit=31)
            item.setToolTip(panel_title(panel) + '\n' + self._panel_subtitle(panel))
            item.clicked.connect(lambda _checked=False, i=index: self._select_panel(i))
            item.set_selected(index == self._current)
            self._list_layout.addWidget(item)
            self._items.append((item, panel))
        self._no_matches = QLabel(ui_text('story_no_matches'))
        self._no_matches.setWordWrap(True)
        self._no_matches.setStyleSheet(ss_dim_label())
        self._no_matches.setFont(ui_font(TypeSize.BODY))
        self._list_layout.addWidget(self._no_matches)
        self._list_layout.addStretch()
        self._filter_list()
        if keep_scroll:
            QTimer.singleShot(0, lambda: self._list_scroll.verticalScrollBar().setValue(scroll))

    def _refresh_filter_options(self):
        for combo, key, caption in ((self._part_filter, 'part', part_name),
                                    (self._type_filter, 'type', type_name)):
            previous = combo.currentData()
            combo.blockSignals(True)
            while combo.count() > 1:
                combo.removeItem(1)
            for value in sorted({p.get(key, 0) for p in self._panels}):
                combo.addItem(caption(value), value)
            combo.setCurrentIndex(max(0, combo.findData(previous)))
            combo.blockSignals(False)
        self._search._design_filter_reset.refresh()

    def _panel_subtitle(self, panel):
        return ui_text('story_panel_subtitle', id=panel.get('ptr_panel_id', ''),
                       page=panel.get('page', 0), kind=type_name(panel.get('type', 0)))

    def _filter_list(self, *args):
        query = self._search.text().casefold().split()
        visible = False
        for item, panel in self._items:
            matches = (self._part_filter.currentData() in (None, panel.get('part'))
                       and self._type_filter.currentData() in (None, panel.get('type')))
            if matches and query:
                hay = ' '.join([str(panel.get(key, '')) for key in _F]
                               + [panel_title(panel), part_name(panel.get('part', 0)), type_name(panel.get('type', 0))]
                               + [rule_name(panel.get(key, -1), self._rules) for key in
                                  ('spec_rule_1', 'spec_rule_2', 'spec_rule_3', 'm1_cond', 'm2_cond', 'm3_cond', 'm4_cond')]).casefold()
                matches = all(word in hay for word in query)
            item.setVisible(matches)
            visible |= matches
        if hasattr(self, '_no_matches'):
            self._no_matches.setVisible(not visible)

    def _select_panel(self, index):
        if self._busy or not 0 <= index < len(self._panels) or not self._flush_panel(report=True):
            return False
        self._current = index
        for i, (item, _) in enumerate(self._items):
            item.set_selected(i == index)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._build_form(self._panels[index])
        return True

    def _new_panel(self, duplicate=False):
        if self._busy or self._result is None or not self._flush_panel(report=True):
            return
        reference = self._panels[self._current] if self._current >= 0 else None
        panel = make_default_panel(reference if duplicate else None)
        if reference and not duplicate:
            panel.update(part=reference['part'], page=reference['page'])
        used = {p['ptr_panel_id'] for p in self._panels}
        number = 1
        while f'PANEL_{panel["page"]:02d}_{number:02d}' in used:
            number += 1
        panel['ptr_panel_id'] = f'PANEL_{panel["page"]:02d}_{number:02d}'
        indices = {p['total_idx'] for p in self._panels}
        panel['total_idx'] = next(i for i in range(1, len(indices) + 2) if i not in indices)
        insert_at = self._current + 1 if self._current >= 0 else len(self._panels)
        self._panels.insert(insert_at, panel)
        self._result['count'] = len(self._panels)
        self._current = -1
        self._fields = {}
        self._clear_filters()
        self._rebuild_list()
        self._select_panel(insert_at)
        self._mark_dirty()
        self._list_scroll.ensureWidgetVisible(self._items[insert_at][0])

    def _add_panel(self):
        self._new_panel()

    def _duplicate_panel(self):
        if self._current >= 0:
            self._new_panel(duplicate=True)

    def _delete_panel(self):
        if self._busy or self._current < 0 or not self._flush_panel(report=True):
            return
        panel_id = self._panels[self._current]['ptr_panel_id']
        message = self.t('msg_confirm_delete_item', name=panel_id)
        links = ('ptr_boss_id', 'ptr_up', 'ptr_down', 'ptr_left', 'ptr_right')
        if panel_id and any(p is not self._panels[self._current] and any(p.get(k) == panel_id for k in links) for p in self._panels):
            message += '\n\n' + ui_text('story_delete_linked')
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'), message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = self._current
        del self._panels[index]
        self._result['count'] = len(self._panels)
        self._current = -1
        self._fields = {}
        self._rebuild_list(keep_scroll=True)
        if self._panels:
            index = min(index, len(self._panels) - 1)
            self._clear_filters()
            self._select_panel(index)
        else:
            self._dup_btn.setEnabled(False)
            self._del_btn.setEnabled(False)
            self._show_placeholder()
        self._mark_dirty()

    @staticmethod
    def _control_value(widget):
        if isinstance(widget, QComboBox):
            current = widget.currentIndex()
            if current >= 0 and widget.itemText(current) == widget.currentText():
                return widget.itemData(current)
            index = widget.findText(widget.currentText(), Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive)
            if index >= 0:
                return widget.itemData(index)
            return widget.currentText()
        return widget.text()

    def _flush_panel(self, report=False):
        if self._building or self._current < 0 or not self._fields:
            return True
        panel = self._panels[self._current]
        candidate = {}
        invalid = []
        for key, widget in self._fields.items():
            kind = _F[key][1]
            value = self._control_value(widget)
            try:
                if kind == 'ptr':
                    value = str(value)
                    value.encode('ascii')
                    if '\x00' in value:
                        raise ValueError()
                else:
                    text = str(value).strip()
                    # Decimal only; Python int otherwise accepts underscores.
                    if not text or not text.lstrip('+-').isascii() or not text.lstrip('+-').isdigit():
                        raise ValueError()
                    value = int(text, 10)
                    lower, upper = (-0x80000000, 0x7fffffff) if kind == 'i32' else (0, 0xffffffff)
                    if not lower <= value <= upper:
                        raise ValueError()
                candidate[key] = value
                widget.setStyleSheet(ss_input_validation(False))
            except (ValueError, TypeError, UnicodeError):
                invalid.append((key, widget))
                widget.setStyleSheet(ss_input_validation(True))
        if invalid:
            if report:
                key, widget = invalid[0]
                kind = _F[key][1]
                lower, upper = (-0x80000000, 0x7fffffff) if kind == 'i32' else (0, 0xffffffff)
                message = ui_text('story_invalid_id', field=self._field_labels[key]) if kind == 'ptr' else ui_text(
                    'story_invalid_number', field=self._field_labels[key], minimum=lower, maximum=upper)
                QMessageBox.warning(self, ui_text('dlg_title_warning'), message)
                self._editor_scroll.ensureWidgetVisible(widget)
                widget.setFocus()
            return False
        changed = any(panel.get(key) != value for key, value in candidate.items())
        panel.update(candidate)
        if changed:
            self._mark_dirty()
            if self._current < len(self._items):
                item = self._items[self._current][0]
                item.set_texts(panel_title(panel), self._panel_subtitle(panel), title_limit=27, subtitle_limit=31)
                item.setToolTip(panel_title(panel) + '\n' + self._panel_subtitle(panel))
            if hasattr(self, '_issues_label'):
                self._issues_label.setText(panel_issues(panel, self._panels, self._rules))
                self._issues_label.setVisible(bool(self._issues_label.text()))
                self._summary_title.setText(panel_title(panel))
                self._summary_subtitle.setText(part_name(panel['part']) + ' · ' + self._panel_subtitle(panel))
            self._refresh_filter_options()
            self._filter_list()
        return True

    def _choice(self, value, options):
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setMaxVisibleItems(12)
        for number, caption in options:
            combo.addItem(caption, number)
            combo.setItemData(combo.count() - 1, caption, Qt.ItemDataRole.ToolTipRole)
        index = combo.findData(value)
        if index < 0:
            combo.addItem(str(value), value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)
        configure_input(combo, monospace=False)
        combo.setMinimumWidth(0)
        combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        combo.lineEdit().setCursorPosition(0)
        combo.installEventFilter(self)
        return combo

    def _add_field(self, grid, key, caption, hint='', options=None):
        value = self._panels[self._current].get(key, '' if _F[key][1] == 'ptr' else 0)
        widget = self._choice(value, options) if options is not None else configure_input(QLineEdit(str(value)), monospace=True)
        if isinstance(widget, QLineEdit):
            widget.setCursorPosition(0)
        widget.setAccessibleName(caption)
        widget.setToolTip(hint)
        frame, layout, _, _ = make_editor_field_shell(caption)
        configure_field(frame, widget)
        layout.addWidget(widget)
        n = grid.count()
        columns = 1 if self._is_compact_editor() else 2
        grid.addWidget(frame, n // columns, n % columns, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(n % columns, 1)
        self._fields[key] = widget
        self._field_labels[key] = caption
        signal = widget.currentTextChanged if isinstance(widget, QComboBox) else widget.textChanged
        signal.connect(self._mark_dirty)
        if isinstance(widget, QComboBox):
            widget.lineEdit().editingFinished.connect(self._flush_panel)
            widget.activated.connect(lambda: self._flush_panel())
        else:
            widget.editingFinished.connect(self._flush_panel)
        return widget

    def _card(self, title, icon='fa6s.sliders', subtitle=None):
        card, grid = make_editor_grid_card(title=title, icon_name=icon, subtitle=subtitle)
        configure_card(card, maximum_width=16777215)
        self._editor_layout.addWidget(card)
        return grid

    def _build_form(self, panel):
        self._building = True
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._field_labels = {}
        self._rule_hint_refreshes = []
        self._last_editor_compact = self._is_compact_editor()
        overview, body = make_editor_card()
        configure_card(overview, maximum_width=16777215)
        _, self._summary_title, self._summary_subtitle = add_editor_card_title(
            body, panel_title(panel), 'fa6s.map-location-dot',
            subtitle=part_name(panel['part']) + ' · ' + self._panel_subtitle(panel))
        self._issues_label = QLabel(panel_issues(panel, self._panels, self._rules))
        self._issues_label.setWordWrap(True)
        self._issues_label.setTextFormat(Qt.TextFormat.PlainText)
        self._issues_label.setStyleSheet(ss_dim_label())
        self._issues_label.setVisible(bool(self._issues_label.text()))
        body.addWidget(self._issues_label)
        self._editor_layout.addWidget(overview)
        g = self._card(ui_text('story_panel_settings'), 'fa6s.circle-info')
        self._add_field(g, 'part', ui_text('ui_mainmodeparam_part_jojo_arc'), options=[(i, part_name(i)) for i in range(1, 9)])
        self._add_field(g, 'page', ui_text('ui_mainmodeparam_page'), ui_text('story_page_hint'))
        self._add_field(g, 'ptr_panel_id', ui_text('ui_mainmodeparam_panel_id'), ui_text('story_id_hint'))
        self._add_field(g, 'total_idx', ui_text('ui_mainmodeparam_total_panel_index'), ui_text('story_index_hint'))
        self._add_field(g, 'type', ui_text('ui_mainmodeparam_panel_type'), options=[(i, f'{i} · {type_name(i)}') for i in range(3)])
        self._add_field(g, 'gold_reward', ui_text('story_gp_win'))
        self._add_field(g, 'disp_diff', ui_text('ui_mainmodeparam_display_difficulty'), ui_text('story_difficulty_hint'))
        self._add_field(g, 'cpu_level', ui_text('ui_mainmodeparam_cpu_level'), ui_text('story_difficulty_hint'))
        stages = sorted({p['ptr_stage_id'] for p in self._panels if p['ptr_stage_id']})
        self._add_field(g, 'ptr_stage_id', ui_text('ui_mainmodeparam_stage_id'), options=[(s, s) for s in stages])
        character_codes = sorted({key[5:] for key in TRANSLATIONS['en'] if key.startswith('char_')})
        characters = [('', ui_text('story_no_character'))] + [(c, f'{character_name(c)} · {c}') for c in character_codes]
        for side, title, fields in (
            ('player', 'ui_mainmodeparam_player_information', (
                ('ptr_player_id', 'ui_mainmodeparam_player_id'), ('ptr_plyr_asst', 'ui_mainmodeparam_player_assist_id'),
                ('ptr_plyr_btlst', 'ui_mainmodeparam_player_start_dialogue'), ('ptr_plyr_win', 'ui_mainmodeparam_player_win_dialogue'))),
            ('enemy', 'ui_mainmodeparam_enemy_information', (
                ('ptr_enemy_id', 'ui_mainmodeparam_enemy_id'), ('ptr_enmy_asst', 'ui_mainmodeparam_enemy_assist_id'),
                ('ptr_enmy_btlst', 'ui_mainmodeparam_enemy_start_dialogue'), ('ptr_enmy_win', 'ui_mainmodeparam_enemy_win_dialogue'))),
        ):
            g = self._card(ui_text(title), 'fa6s.user' if side == 'player' else 'fa6s.user-ninja')
            for i, (key, caption) in enumerate(fields):
                self._add_field(g, key, ui_text(caption), options=characters if i < 2 else None)
        g = self._card(ui_text('story_navigation'), 'fa6s.arrows-up-down-left-right', ui_text('story_link_hint'))
        links = [('', ui_text('story_no_link'))] + [(p['ptr_panel_id'], p['ptr_panel_id'] + ' · ' + panel_title(p)) for p in self._panels if p['ptr_panel_id']]
        for key, caption in (('ptr_up', 'ui_mainmodeparam_above'), ('ptr_down', 'ui_mainmodeparam_below'),
                             ('ptr_left', 'ui_mainmodeparam_left'), ('ptr_right', 'ui_mainmodeparam_right'),
                             ('ptr_boss_id', 'ui_mainmodeparam_boss_panel_id')):
            self._add_field(g, key, ui_text(caption), options=links)
        status = ui_text('story_rules_hint') if self._rules else ui_text('story_catalog_missing')
        g = self._card(ui_text('ui_mainmodeparam_special_rules'), 'fa6s.gavel', status)
        choices = self._rule_choices(mission=False)
        for i in range(1, 4):
            control = self._add_field(g, f'spec_rule_{i}', ui_text('story_rule_slot', value=i), options=choices)
            self._add_rule_hint(control)
        choices = self._rule_choices(mission=True)
        for i in range(1, 5):
            value = panel[f'm{i}_cond']
            g = self._card(ui_text('ui_mainmodeparam_mission_value', p0=i), 'fa6s.medal')
            control = self._add_field(g, f'm{i}_cond', ui_text('ui_mainmodeparam_condition'), options=choices)
            self._add_rule_hint(control)
            categories = [(0, ui_text('story_reward_gp'))] + [(n, ui_text(f'cum_type_{n}')) for n in range(1, 9)]
            self._add_field(g, f'm{i}_unk', ui_text('ui_mainmodeparam_reward_type'), ui_text('story_reward_hint'),
                            options=[(n, f'{n} · {caption}') for n, caption in categories])
            rewards = sorted({p[f'ptr_m{n}_reward'] for p in self._panels for n in range(1, 5) if p[f'ptr_m{n}_reward']})
            self._add_field(g, f'ptr_m{i}_reward', ui_text('ui_mainmodeparam_reward_id'),
                            options=[('', ui_text('story_no_item'))] + [(r, r) for r in rewards])
            self._add_field(g, f'm{i}_gold', ui_text('story_gp_mission'))
        g = self._card(ui_text('story_stored_fields'), 'fa6s.database', ui_text('story_stored_hint'))
        for number, key in enumerate(('unk1', 'ptr_str05', 'unk3', 'first_speak', 'ptr_str14', 'ptr_str19', 'spec_rule_4', 'extra_unk1', 'extra_unk2', 'extra_unk3'), 1):
            self._add_field(g, key, ui_text('story_stored_field', number=number))
        self._editor_layout.addStretch()
        self._editor_scroll.verticalScrollBar().setValue(0)
        self._building = False

    def _rule_choices(self, mission):
        # 4E39BC routes battle types 0/2/3/4, and mission type 1.
        return [(-1, ui_text('story_disabled'))] + [
            (v, f'{v} · {rule_name(v, self._rules)}') for v, rule in sorted(self._rules.items())
            if v != -1 and (len(rule) < 3 or rule[2] in ((1,) if mission else (0, 2, 3, 4)))]

    def _add_rule_hint(self, control):
        # A child of the field shell grows with its text, using shared spacing.
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setStyleSheet(ss_dim_label())
        label.setFont(ui_font(TypeSize.HINT))
        control.parentWidget().layout().addWidget(label)

        def refresh(*args):
            try:
                number = int(self._control_value(control))
                text = self._rules.get(number, ('', ''))[1]
                label.setText(text)
                label.setVisible(bool(text))
                control.setToolTip(text)
            except (ValueError, TypeError):
                label.clear()
        control.currentTextChanged.connect(refresh)
        self._rule_hint_refreshes.append(refresh)
        refresh()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and isinstance(watched, QComboBox) and not watched.hasFocus():
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def _is_compact_editor(self):
        return self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current >= 0 and self._last_editor_compact != self._is_compact_editor():
            QTimer.singleShot(0, self._rebuild_current_panel_for_width)

    def _rebuild_current_panel_for_width(self):
        if 0 <= self._current < len(self._panels) and self._last_editor_compact != self._is_compact_editor():
            restore = capture_pending_fields(self)
            scroll = self._editor_scroll.verticalScrollBar().value()
            self._build_form(self._panels[self._current])
            restore()
            for refresh in self._rule_hint_refreshes:
                refresh()
            self._editor_scroll.verticalScrollBar().setValue(scroll)
