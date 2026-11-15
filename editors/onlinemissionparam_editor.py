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
    ss_bg_dark,
    ss_dim_label,
    ss_sidebar_btn,
    ss_transparent,
)
from core.ui.editor_widgets import (
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
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy
import os

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label
from core.online_research import next_identity
from core.online_tools import INTEGER_RANGES, STRING_KEYS, field_value, catalogs, choices, group_slots, event_match, entry_issues
from core.ui.editor_widgets import EditorFilterCombo, fit_scroll_page
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper
from core.ui.message_preview import MessagePreview, message_lookup
from core.style_helpers import ss_input_validation
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.translations import ui_text
from parsers.onlinemissionparam_parser import (
    make_default_entry,
    parse_onlinemissionparam_xfbin,
    save_onlinemissionparam_xfbin,
)


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


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


class OnlineMissionParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._result: dict | None = None
        self._entries: list[dict] = []
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._current_idx: int | None = None
        self._fields: dict[str, QLineEdit] = {}
        self._dirty = False
        self._loading_detail = False
        self._last_compact: bool | None = None
        self._grids = []
        self._combos = {}
        self._choice_models = {}
        self._resources = {}
        self._catalog_error = ''
        self._title_cache = {}
        self._probe_text = ''
        self._probe_assist = False

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if value == key and fallback is not None else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        top = EditorToolbar()
        top_layout = top.content_layout

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._do_open)
        self._btn_open.setProperty("designAction", 'open')
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._do_save)
        top_layout.addWidget(self._btn_save)

        self._file_label = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        sidebar = EditorSidebar(width=290)


        sidebar_layout = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)
        self._group_filter = EditorFilterCombo()
        self._group_filter.addItem(ui_text('om_group_filter'), None)
        self._group_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._group_filter)
        self._scope_filter = EditorFilterCombo()
        self._scope_filter.addItem(ui_text('om_scope_filter'), None)
        self._scope_filter.addItem(ui_text('om_scope_both'), 6)
        self._scope_filter.addItem(ui_text('om_scope_ranked'), 7)
        self._scope_filter.currentIndexChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._scope_filter)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


        self._btn_add = self._make_action_button("btn_new", self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        self._btn_dup = self._make_action_button("btn_duplicate", self._do_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        self._btn_del = self._make_action_button("btn_delete", self._do_del, danger=True)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_add, 1)
        actions_layout.addWidget(self._btn_dup, 1)
        actions_layout.addWidget(self._btn_del, 1)
        sidebar_layout.addWidget(actions)

        self._entry_scroll = QScrollArea()


        self._entry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._entry_scroll, transparent=True)
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setMinimumWidth(0)
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        configure_layout(self._entry_list_layout, LayoutRole.LIST)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        sidebar_layout.addWidget(self._entry_scroll, 1)
        main_layout.addWidget(sidebar)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        self._editor_scroll.viewport().installEventFilter(self)
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_onlinemissionparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)
        self._update_actions()

    def _make_action_button(self, key: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(self._tr(key, ui_text(key)))
        btn.setEnabled(False)
        configure_button(btn, danger=danger, height=Size.COMPACT_CONTROL)
        btn.clicked.connect(slot)
        return btn

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields, self._combos, self._grids = {}, {}, []
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_onlinemissionparam_open_title"),
            game_files_dialog_dir(target_patterns=("OnlineMissionParam.bin.xfbin", "OnlineMissionParam.xfbin")),
            ui_text("ui_onlinemissionparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        try:
            raw, result = parse_onlinemissionparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return False

        if self._dirty:
            reply = QMessageBox.question(self, ui_text('dlg_title_warning'), ui_text('term_discard_changes'),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Discard:
                return False
        create_backup_on_open(path)

        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._entries = result["entries"]
        self._resources, self._catalog_error = catalogs(path, load_settings().get('game_files_dir', ''))
        self._title_cache.clear()
        self._reset_choice_models()
        self._group_filter.blockSignals(True)
        self._group_filter.clear()
        self._group_filter.addItem(ui_text('om_group_filter'), None)
        for group in sorted({e['group_id'] for e in self._entries}):
            self._group_filter.addItem(ui_text('om_group', value=group), group)
        self._group_filter.blockSignals(False)
        self._scope_filter.setCurrentIndex(0)
        self._current_idx = None
        self._dirty = False
        self._btn_save.setEnabled(False)
        self._search.setText("")
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_onlinemissionparam_no_entries"))
        self._update_actions()
        return True

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_onlinemissionparam_xfbin(save_path, self._raw_data, self._result)
            raw, saved = parse_onlinemissionparam_xfbin(save_path)
            self._raw_data = raw
            for entry, stored in zip(self._entries, saved['entries']):
                for key, value in stored.items():
                    if key.startswith('_') or key == 'index':
                        entry[key] = value
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, save_path)
            QMessageBox.information(self, ui_text('dlg_title_success'), ui_text('msg_save_success', path=os.path.basename(save_path)))
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []

    def _populate_list(self):
        self._clear_entry_list()
        group = self._group_filter.currentData()
        self._group_filter.blockSignals(True)
        self._group_filter.clear()
        self._group_filter.addItem(ui_text('om_group_filter'), None)
        for value in sorted({e['group_id'] for e in self._entries}):
            self._group_filter.addItem(ui_text('om_group', value=value), value)
        self._group_filter.setCurrentIndex(max(0, self._group_filter.findData(group)))
        self._group_filter.blockSignals(False)
        for idx, entry in enumerate(self._entries):
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = self._entry_title(idx, entry)
        button_title = self._entry_button_title(idx, entry)
        subtitle_text = self._entry_subtitle(entry)
        button_subtitle = self._entry_button_subtitle(entry)

        title = btn.add_title(_truncate(button_title, 21))
        title.setTextFormat(Qt.TextFormat.PlainText)


        title.setToolTip(title_text)


        subtitle = btn.add_subtitle(_truncate(button_subtitle, 28), value_font=mono_font(TypeSize.CODE))
        subtitle.setTextFormat(Qt.TextFormat.PlainText)


        subtitle.setToolTip(subtitle_text)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _resolved_title(self, entry):
        key = entry.get('title_key', '')
        if key not in self._title_cache:
            result = message_lookup(self).resolve(key) if key else None
            self._title_cache[key] = result.text.replace('\n', ' ') if result and result.text else key
        return self._title_cache[key] or ui_text('ui_onlinemissionparam_empty_title')

    def _entry_title(self, idx, entry):
        return self._resolved_title(entry)

    def _entry_button_title(self, idx, entry):
        return self._resolved_title(entry)

    def _entry_subtitle(self, entry):
        return ui_text('om_list_detail', group=entry['group_id'], slot=entry['display_slot'],
                       mission=entry['mission_id'], gp=entry['reward_value'])

    def _entry_button_subtitle(self, entry):
        return self._entry_subtitle(entry)

    def _filter_list(self):
        query = self._search.text().lower().strip()
        group = self._group_filter.currentData()
        scope = self._scope_filter.currentData()
        for btn, idx in self._entry_buttons:
            entry = self._entries[idx]
            haystack = ' '.join([self._resolved_title(entry), *(str(v) for k, v in entry.items()
                                  if not k.startswith('_'))]).lower()
            accepted = (group is None or entry['group_id'] == group) and (
                scope is None or (entry['mission_type'] == 6) == (scope == 6))
            btn.setVisible(accepted and (not query or query in haystack))

    def _select_entry(self, idx: int):
        if idx < 0 or idx >= len(self._entries):
            return
        if not self._apply_current_entry(show_errors=True):
            return
        self._current_idx = idx
        for btn, button_idx in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=button_idx == idx))
        self._build_editor(idx)
        self._update_actions()
        QTimer.singleShot(0, self._ensure_selected_visible)

    def _ensure_selected_visible(self):
        for btn, index in self._entry_buttons:
            if index == self._current_idx and not btn.isHidden():
                self._entry_scroll.ensureWidgetVisible(btn)
                break

    def _refresh_entry_button(self, idx: int):
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if len(labels) >= 2:
                title_text = self._entry_title(idx, self._entries[idx])
                button_title = self._entry_button_title(idx, self._entries[idx])
                subtitle_text = self._entry_subtitle(self._entries[idx])
                button_subtitle = self._entry_button_subtitle(self._entries[idx])
                labels[0].setText(_truncate(button_title, 21))
                labels[0].setToolTip(title_text)
                labels[1].setText(_truncate(button_subtitle, 28))
                labels[1].setToolTip(subtitle_text)
            break
        self._filter_list()

    def _update_actions(self):
        loaded = self._raw_data is not None
        has_selection = self._current_idx is not None and 0 <= self._current_idx < len(self._entries)
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and has_selection)
        self._btn_del.setEnabled(loaded and has_selection)
        self._btn_save.setEnabled(loaded and self._dirty)

    def _reset_choice_models(self):
        for model in self._choice_models.values():
            model.deleteLater()
        self._choice_models.clear()

    def _label(self, text=''):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        label.setFont(ui_font(TypeSize.BODY))
        label.setStyleSheet(ss_dim_label())
        return label

    def _card(self, title, subtitle=None, columns=2, icon='fa6s.sliders'):
        card, grid = make_editor_grid_card(self._editor_widget, title=title, subtitle=subtitle, icon_name=icon)
        configure_card(card)
        self._editor_layout.addWidget(card)
        self._last_card = card
        self._grids.append((grid, [], columns))
        return grid

    def _add_field(self, key, entry, hint=None):
        grid, frames, _ = self._grids[-1]
        caption = ui_text('ui_messageinfo_string_id') if key == 'title_key' else ui_text('ui_onlinemissionparam_' + key)
        frame, layout, _, _ = make_editor_field_shell(caption)
        signature = (key, entry.get('reward_type') if key == 'reward_card_id' else None)
        options = () if signature in self._choice_models else choices(
            key, self._entries, self._resources, message_lookup(self), entry.get('reward_type'))
        if options is not None:
            if signature not in self._choice_models:
                self._choice_models[signature] = EditorValueCombo.choice_model(options, self)
            combo = EditorValueCombo((), entry[key], model=self._choice_models[signature])
            self._combos[key] = combo
            edit, content = combo.lineEdit(), combo
            edit.setCursorPosition(0)
            combo.currentTextChanged.connect(lambda _text, k=key: self._on_field_changed(k))
        else:
            edit = configure_input(QLineEdit(str(entry[key])))
            content = IntegerStepper(edit, *INTEGER_RANGES[key]) if key in INTEGER_RANGES else edit
            edit.textChanged.connect(lambda _text, k=key: self._on_field_changed(k))
        configure_field(frame, content)
        content.setAccessibleName(caption)
        edit.setAccessibleName(caption)
        content.setToolTip(hint or ui_text('om_reference_hint' if key in STRING_KEYS else 'om_integer_hint'))
        edit.setProperty('messageReference', key == 'title_key')
        edit.setToolTip(content.toolTip())
        self._fields[key] = edit
        edit.editingFinished.connect(lambda k=key: self._on_uint_finished(k))
        layout.addWidget(content)
        if key == 'objective_value':
            self._count_hint = self._label()
            layout.addWidget(self._count_hint)
        if key == 'title_key':
            # Resolve the authored ID, not the human caption in the combo edit.
            self._message_preview_input = QLineEdit(str(entry[key]), frame)
            self._message_preview_input.hide()
            self._message_preview = MessagePreview(self._message_preview_input, message_lookup(self))
            layout.addWidget(self._message_preview)
        frames.append(frame)
        grid.addWidget(frame, len(frames) - 1, 0)

    def _build_editor(self, idx):
        self._loading_detail = True
        _clear_layout(self._editor_layout)
        self._fields, self._combos, self._grids = {}, {}, []
        entry = self._entries[idx]
        grid = self._card(ui_text('om_group_overview'), ui_text('om_group_overview_hint'), columns=5, icon='fa6s.layer-group')
        self._slot_buttons = []
        for slot in range(5):
            button = EditorListRow()
            button.set_texts(ui_text('om_slot', value=slot), '')
            button.subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
            button.clicked.connect(lambda _checked=False, s=slot: self._select_group_slot(s))
            grid.addWidget(button, slot, 0)
            self._grids[-1][1].append(button)
            self._slot_buttons.append(button)
        self._group_reward = self._label()
        grid.addWidget(self._group_reward, 5, 0)
        self._grids[-1][1].append(self._group_reward)

        self._card(self._entry_title(idx, entry), self._entry_subtitle(entry), icon='fa6s.globe')
        labels = self._last_card.findChildren(QLabel)
        self._header_title = next(label for label in labels if label.text() == self._entry_title(idx, entry))
        self._header_subtitle = next(label for label in labels if label.text() == self._entry_subtitle(entry))
        self._header_title.setTextFormat(Qt.TextFormat.PlainText)
        for key, hint in (('group_id', 'ui_onlinemissionparam_group_hint'),
                          ('display_slot', 'ui_onlinemissionparam_display_slot_hint'),
                          ('mission_id', 'ui_onlinemissionparam_mission_hint'),
                          ('title_key', 'om_title_hint')):
            self._add_field(key, entry, ui_text(hint))

        self._card(ui_text('ui_onlinemissionparam_objective'))
        for key, hint in (('mission_type', 'online_scope_ranked'), ('flag_08', 'om_victory_hint'),
                          ('condition_id', 'ui_onlinemissionparam_condition_hint'),
                          ('objective_value', 'om_count_hint')):
            self._add_field(key, entry, ui_text(hint))

        self._card(ui_text('om_fighter_filters'), ui_text('om_filters_hint'))
        for key, hint in (('character_id', 'om_local_hint'), ('subtype_id', 'online_part_hint'),
                          ('opponent_character_id', 'om_opponent_hint'), ('stage_id', 'om_stage_hint')):
            self._add_field(key, entry, ui_text(hint))

        self._card(ui_text('ui_onlinemissionparam_rewards'), ui_text('ui_onlinemissionparam_reward_hint'))
        for key, hint in (('reward_value', 'om_gp_hint'), ('reward_type', 'ui_onlinemissionparam_reward_hint'),
                          ('reward_card_id', 'om_catalog_hint'), ('banner_id', 'om_banner_hint')):
            self._add_field(key, entry, ui_text(hint))

        grid = self._card(ui_text('om_event_probe'), ui_text('om_event_probe_hint'), columns=1)
        self._event_input = configure_input(QLineEdit(self._probe_text))
        self._event_input.setAccessibleName(ui_text('om_event_input'))
        self._event_input.setProperty('messageReference', False)
        self._event_input.setPlaceholderText(ui_text('om_event_input'))
        self._event_input.textChanged.connect(self._probe_changed)
        self._probe_mode = EditorValueCombo([(0, ui_text('om_event_normal')), (1, ui_text('om_event_assist'))], int(self._probe_assist))
        self._probe_mode.setEditable(False)
        self._probe_mode.currentIndexChanged.connect(self._probe_changed)
        self._probe_result = self._label()
        for widget in (self._probe_mode, self._event_input, self._probe_result):
            grid.addWidget(widget, len(self._grids[-1][1]), 0)
            self._grids[-1][1].append(widget)

        self._editor_layout.addStretch()
        self._loading_detail = False
        self._refresh_detail()
        self._reflow()

    def _value_text(self, key):
        combo = self._combos.get(key)
        return combo.value_text() if combo else self._fields[key].text()

    def _draft(self, show_errors=False):
        if self._current_idx is None:
            return None
        draft = dict(self._entries[self._current_idx])
        valid = True
        for key, edit in self._fields.items():
            try:
                text = self._value_text(key)
                # Preserve opaque bytes from a nonstandard file if untouched.
                if key in STRING_KEYS and text == draft[key]:
                    value = draft[key]
                else:
                    value = field_value(key, text)
                draft[key] = value
                edit.setStyleSheet(ss_input_validation(False))
            except (ValueError, UnicodeError):
                valid = False
                edit.setStyleSheet(ss_input_validation(True))
                if show_errors:
                    edit.setFocus()
                    QMessageBox.warning(self, ui_text('dlg_title_warning'),
                                        ui_text('om_invalid_field', field=edit.accessibleName() or ui_text('ui_onlinemissionparam_' + key)))
                    return None
        return draft if valid else None

    def _on_field_changed(self, key):
        if self._loading_detail or self._current_idx is None:
            return
        self._mark_dirty()
        if key == 'title_key':
            self._message_preview_input.setText(self._value_text(key))
        if self._apply_current_entry():
            if key == 'reward_type':
                self._refresh_reward_choices()
        else:
            self._probe_result.setText(ui_text('om_fix_fields'))
        self._reflow()

    def _refresh_reward_choices(self):
        combo = self._combos['reward_card_id']
        value = combo.value_text()
        kind = self._entries[self._current_idx]['reward_type']
        signature = ('reward_card_id', kind)
        if signature not in self._choice_models:
            options = choices('reward_card_id', self._entries, self._resources, reward_type=kind)
            self._choice_models[signature] = EditorValueCombo.choice_model(options, self)
        combo.blockSignals(True)
        combo.setModel(self._choice_models[signature])
        index = combo.findData(value)
        combo.setCurrentIndex(index)
        if index < 0:
            combo.setEditText(value)
        combo.blockSignals(False)

    def _apply_current_entry(self, show_errors=False):
        if self._current_idx is None:
            return True
        draft = self._draft(show_errors)
        if draft is None:
            return False
        self._entries[self._current_idx].update(draft)
        self._refresh_entry_button(self._current_idx)
        self._refresh_detail()
        return True

    def _on_uint_finished(self, key):
        if not self._loading_detail:
            self._apply_current_entry()

    def _refresh_detail(self):
        if self._current_idx is None:
            return
        entry = self._entries[self._current_idx]
        self._header_title.setText(self._entry_title(self._current_idx, entry))
        self._header_subtitle.setText(self._entry_subtitle(entry))
        count = entry['objective_value']
        self._count_hint.setText(ui_text('om_effective_count', stored=count, effective=count & 255))
        self._refresh_group()
        self._probe_changed()

    def _refresh_group(self):
        entry = self._entries[self._current_idx]
        indices = group_slots(self._entries, entry['group_id'])
        for slot, (button, index) in enumerate(zip(self._slot_buttons, indices)):
            title = self._resolved_title(self._entries[index]) if index is not None else ui_text('om_empty_slot')
            button.set_texts(ui_text('om_slot', value=slot), title, subtitle_limit=90)
            button.set_selected(index == self._current_idx)
            button.setEnabled(index is not None)
        if indices[0] is None:
            text = ui_text('om_missing_reward_slot')
        else:
            from core.cumulative_research import reward_type_name
            source = self._entries[indices[0]]
            text = ui_text('om_effective_reward', kind=reward_type_name(source['reward_type']),
                           value=source['reward_card_id'] or '?')
        missing = [str(slot) for slot, index in enumerate(indices) if index is None]
        if missing:
            text += '\n' + ui_text('om_missing_slots', slots=', '.join(missing))
        if self._catalog_error:
            text += '\n' + ui_text('om_catalog_error', error=self._catalog_error)
        issues = entry_issues(entry, self._entries)
        if issues:
            text += '\n' + '\n'.join(issues)
        self._group_reward.setText(text)

    def _select_group_slot(self, slot):
        if not self._apply_current_entry(show_errors=True):
            return
        group = self._entries[self._current_idx]['group_id']
        index = group_slots(self._entries, group)[slot]
        if index is not None:
            self._select_entry(index)

    def _probe_changed(self, *_):
        if self._loading_detail or self._current_idx is None:
            return
        self._probe_text = self._event_input.text()
        self._probe_assist = self._probe_mode.currentData() == '1'
        draft = self._draft()
        if draft is None:
            key = 'om_fix_fields'
        elif not self._probe_text:
            key = 'om_probe_empty'
        elif not self._probe_assist and not draft['condition_id']:
            key = 'om_probe_matches'
        else:
            result = event_match(draft, self._probe_text, assist=self._probe_assist)
            key = 'om_probe_runtime' if result is None else ('om_probe_yes' if result else 'om_probe_no')
        self._probe_result.setText(ui_text(key))
        QTimer.singleShot(0, self._reflow)

    def _reflow(self):
        width = self._editor_scroll.viewport().width()
        self._last_compact = width < Size.COMPACT_BREAKPOINT
        for grid, frames, maximum in self._grids:
            if maximum == 5:
                columns = 5 if width >= 960 else (2 if width >= Size.COMPACT_BREAKPOINT else 1)
                for col in range(maximum):
                    grid.setColumnStretch(col, int(col < columns))
                for index, frame in enumerate(frames[:5]):
                    row, col = divmod(index, columns)
                    grid.addWidget(frame, row, col)
                grid.addWidget(frames[5], (5 + columns - 1) // columns, 0, 1, columns)
                continue
            columns = 1 if self._last_compact else maximum
            for col in range(maximum):
                grid.setColumnStretch(col, int(col < columns))
            for index, frame in enumerate(frames):
                row, col = divmod(index, columns)
                position = grid.indexOf(frame)
                if position < 0 or grid.getItemPosition(position) != (row, col, 1, 1):
                    grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)
        fit_scroll_page(self._editor_scroll)

    def _is_compact_editor(self):
        return self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT

    def _maybe_rebuild_for_compact(self):
        self._reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._reflow)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            if self._filepath:
                set_file_label(self._file_label, self._filepath, dirty=True)
        self._update_actions()

    def _do_add(self):
        if self._raw_data is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        identity = next_identity(self._entries)
        if identity is None:
            QMessageBox.information(self, ui_text('dlg_title_warning'), ui_text('online_no_free_slot'))
            return
        entry = make_default_entry()
        entry.update(identity)
        self._entries.append(entry)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._select_entry(len(self._entries) - 1)

    def _do_dup(self):
        if self._raw_data is None or self._current_idx is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        source = self._entries[self._current_idx]
        identity = next_identity(self._entries, int(source.get('group_id', 0)))
        if identity is None:
            QMessageBox.information(self, ui_text('dlg_title_warning'), ui_text('online_no_free_slot'))
            return
        entry = make_default_entry(copy.deepcopy(source))
        entry.update(identity)
        self._entries.insert(self._current_idx + 1, entry)
        new_idx = self._current_idx + 1
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        self._select_entry(new_idx)

    def _do_del(self):
        if self._raw_data is None or self._current_idx is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        entry = self._entries[self._current_idx]
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("msg_confirm_delete_item", name=self._entry_title(self._current_idx, entry)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        old_idx = self._current_idx
        self._entries.pop(old_idx)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        if self._entries:
            self._select_entry(min(old_idx, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text("ui_onlinemissionparam_no_entries"))
            self._update_actions()
