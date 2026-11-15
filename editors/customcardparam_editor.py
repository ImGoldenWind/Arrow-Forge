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

from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QThreadPool
from core.ui.editor_widgets import EditorFilterCombo, fit_scroll_page
from core.ui.editor_actions import refresh_file_actions
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper
from core.ui.message_preview import message_lookup
from core.ui.image_preview import ImagePreview, ImageLoadJob, ImageLoadSignals
from core.style_helpers import ss_dim_label, ss_input_validation
from core.customcard_tools import (INTEGER_RANGES, MESSAGE_KEYS, parse_field, choices,
    category_name, part_name, next_identity, entry_issues, name_message_id,
    granted_values, image_reference, data_root)
from core.gallery_tools import resource_path, load_image
from core.story_tools import character_name
from core.dictionary_tools import character_catalog

from core.editor_file_state import set_file_label
from parsers.customcardparam_parser import (
    parse_customcardparam_xfbin,
    save_customcardparam_xfbin,
    make_default_entry,
)
from core.translations import current_language, ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class CustomCardParamEditor(QWidget):
    """Embedded editor for CustomCardParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._dirty = False
        self._current_index: int | None = None
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._fields: dict[str, QWidget] = {}
        self._loading_detail = False
        self._list_dirty = False

        self._snapshot = []
        self._grids, self._captions = [], {}
        self._choice_models, self._search_cache = {}, {}
        self._characters = {}
        self._root = None
        self._image_token = 0
        self._image_signature = None
        self._signals = ImageLoadSignals()
        self._signals.finished.connect(self._image_ready)
        self._image_pool = QThreadPool(self)
        self._image_pool.setMaxThreadCount(1)
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(180)
        self._detail_timer.timeout.connect(self._refresh_detail)
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._on_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key, fallback):
        value = self._t(key)
        return fallback if value == key else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        top = EditorToolbar()
        tl = top.content_layout

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_open.setProperty("designAction", 'open')
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._on_save)
        tl.addWidget(self._btn_save)

        self._lbl_file = QLabel(self._tr("no_file_loaded", ui_text("cpk_no_file")))

        configure_file_label(self._lbl_file)
        tl.addWidget(self._lbl_file)
        tl.addStretch()
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main_l = QHBoxLayout(main)
        configure_layout(main_l, LayoutRole.ROOT)

        sidebar = EditorSidebar()


        sl = sidebar.content_layout


        self._search_box = QLineEdit()
        configure_search(self._search_box)
        self._search_box.textChanged.connect(self._on_filter_changed)
        sl.addWidget(self._search_box)
        self._filters = {}
        for key, label in (('medal_type', 'card_category'), ('char_id', 'ui_assist_character'),
                           ('part', 'ui_customcardparam_part')):
            combo = EditorFilterCombo()
            combo.addItem(ui_text(label), None)
            combo.currentIndexChanged.connect(self._filter_list)
            sl.addWidget(combo)
            self._filters[key] = combo

        actions = EditorActionRow()

        al = actions.content_layout


        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_add.setProperty("designAction", 'new')
        al.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.setEnabled(False)
        self._btn_dup.clicked.connect(self._on_duplicate)
        self._btn_dup.setProperty("designAction", 'duplicate')
        al.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_del.setProperty("designAction", 'delete')
        al.addWidget(self._btn_del, 1)

        sl.addWidget(actions)

        self._list_scroll = QScrollArea()


        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._list_scroll, transparent=True)
        self._list_widget = QWidget()
        self._list_widget.setMinimumWidth(0)
        self._list_widget.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_widget)
        configure_layout(self._list_layout, LayoutRole.LIST)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        sl.addWidget(self._list_scroll, 1)

        main_l.addWidget(sidebar)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_l.addWidget(divider)

        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main_l.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_customcardparam_open_a_customcardparam_bin_xfbin_file_to_begin_editing"))
        root.addWidget(main, 1)

    @staticmethod
    def _public(entry):
        return {k: v for k, v in entry.items() if not k.startswith('_')}

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_customcardparam_open_customcardparam_bin_xfbin'),
            game_files_dialog_dir(target_patterns='CustomCardParam.bin.xfbin'),
            'XFBIN files (*.xfbin);;All files (*)')
        if path:
            self._load(path)

    def _load(self, path):
        try:
            raw, version, entries = parse_customcardparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=exc))
            return False
        if self._dirty:
            answer = QMessageBox.question(self, ui_text('dlg_title_warning'), ui_text('term_discard_changes'),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard:
                return False
        create_backup_on_open(path)
        self._detail_timer.stop()
        self._image_token += 1
        self._image_pool.clear()
        self._current_index, self._fields = None, {}
        self._filepath, self._raw, self._version, self._entries = str(path), raw, version, entries
        self._root = data_root(path, load_settings().get('game_files_dir', ''))
        self._characters, _ = character_catalog(path, load_settings().get('game_files_dir', ''))
        self._snapshot = [self._public(e) for e in entries]
        self._dirty = False
        self._search_cache.clear()
        self._reset_choice_models()
        self._search_box.clear()
        self._refresh_filters(reset=True)
        self._populate_list(0 if entries else None)
        self._update_action_state()
        return True

    def _on_save(self, target_path=None):
        path = target_path or editor_path(self)
        if not path or self._raw is None or not self._apply_current_entry():
            return False
        try:
            save_customcardparam_xfbin(path, self._raw, self._version, self._entries)
            raw, _, saved = parse_customcardparam_xfbin(path)
            for entry, disk in zip(self._entries, saved):
                entry.update({k: v for k, v in disk.items() if k.startswith('_')})
            self._raw = raw
            commit_save_path(self, str(path))
            self._snapshot = [self._public(e) for e in self._entries]
            self._update_dirty()
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False

    def _title(self, entry):
        key = name_message_id(entry)
        text = message_lookup(self).text(key)[0] if key else ''
        return f'{text or category_name(entry["medal_type"])} · {character_name(entry["char_id"])}'

    def _entry_subtitle(self, entry):
        return f'{entry["card_id"]} · {entry["letter"]}'

    def _cache_search(self, entry):
        lookup = message_lookup(self)
        self._search_cache[id(entry)] = ' '.join([
            *(str(v) for k, v in entry.items() if not k.startswith('_')),
            self._title(entry), part_name(entry['part']),
            *(lookup.text(entry[k])[0] for k in MESSAGE_KEYS if entry[k])]).casefold()

    def _refresh_filters(self, reset=False):
        for key, combo in self._filters.items():
            selected = None if reset else combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(ui_text({'medal_type': 'card_category', 'char_id': 'ui_assist_character',
                                   'part': 'ui_customcardparam_part'}[key]), None)
            label = {'medal_type': category_name, 'char_id': character_name, 'part': part_name}[key]
            for value in sorted({e[key] for e in self._entries}):
                combo.addItem(label(value), value)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)

    def _populate_list(self, preserve_selection=None):
        _clear_layout(self._list_layout)
        self._entry_buttons = []
        self._list_layout.addStretch()
        for i, entry in enumerate(self._entries):
            self._cache_search(entry)
            button = EditorListRow()
            button.set_texts(self._title(entry), self._entry_subtitle(entry), title_limit=26, subtitle_limit=30)
            button.setToolTip(self._title(entry) + '\n' + self._entry_subtitle(entry))
            button.clicked.connect(lambda _, index=i: self._select_entry(index))
            self._list_layout.insertWidget(self._list_layout.count() - 1, button)
            self._entry_buttons.append((button, i))
        self._filter_list()
        self._list_dirty = False
        if preserve_selection is not None:
            self._select_entry(preserve_selection)
        elif not self._entries:
            self._show_placeholder(ui_text('ui_customcardparam_select_a_card_to_edit'))
        self._update_action_state()

    def _on_filter_changed(self, *args):
        self._filter_list()

    def _filter_list(self, *args):
        query = self._search_box.text().casefold().strip()
        for button, i in self._entry_buttons:
            entry = self._entries[i]
            button.setVisible((not query or query in self._search_cache.get(id(entry), '')) and
                all(combo.currentData() is None or combo.currentData() == entry[key]
                    for key, combo in self._filters.items()))

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries) or not self._apply_current_entry():
            return False
        self._detail_timer.stop()
        previous = self._current_index
        if self._list_dirty:
            self._refresh_detail()
        if previous == idx and self._fields:
            return True
        self._current_index = idx
        if previous is not None and previous < len(self._entry_buttons):
            self._entry_buttons[previous][0].set_selected(False)
        if idx < len(self._entry_buttons):
            button = self._entry_buttons[idx][0]
            button.set_selected(True)
            self._list_scroll.ensureWidgetVisible(button)
        self._build_editor(idx)
        self._editor_scroll.verticalScrollBar().setValue(0)
        self._update_action_state()
        return True

    def _show_placeholder(self, text):
        self._image_token += 1
        _clear_layout(self._editor_layout)
        self._fields, self._grids = {}, []
        card = make_empty_state(self._editor_widget, title=ui_text('no_file_loaded'), text=text,
                                icon_name='fa6s.id-card')
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _card(self, title, icon='fa6s.sliders', columns=2, subtitle=None):
        card, grid = make_editor_grid_card(self._editor_widget, title=title, icon_name=icon, subtitle=subtitle)
        configure_card(card)
        self._editor_layout.addWidget(card)
        self._grids.append((grid, [], columns))
        return grid

    def _add_field(self, key, caption, entry, hint=None):
        grid, frames, _ = self._grids[-1]
        frame, layout, label, _ = make_editor_field_shell(caption)
        model = self._choice_models.get((key, current_language()))
        options = choices(key, self._entries, self._characters) if model is None else ()
        if options is not None:
            if model is None:
                model = EditorValueCombo.choice_model(options, self)
                self._choice_models[(key, current_language())] = model
            edit = EditorValueCombo((), str(entry[key]), model=model)
            edit.currentTextChanged.connect(self._on_field_changed)
            content = edit
        else:
            edit = configure_input(QLineEdit(str(entry[key])))
            edit.textChanged.connect(self._on_field_changed)
            content = IntegerStepper(edit, *INTEGER_RANGES[key]) if key in INTEGER_RANGES else edit
        configure_field(frame, edit)
        edit.setAccessibleName(caption)
        edit.setToolTip(hint or ui_text('card_hint_' + key))
        edit.setProperty('messageReference', key in MESSAGE_KEYS)
        layout.addWidget(content)
        frames.append(frame)
        grid.addWidget(frame, len(frames) - 1, 0)
        self._fields[key], self._captions[key] = edit, caption
        self._field_labels[key] = label

    def _reset_choice_models(self):
        for model in self._choice_models.values():
            model.deleteLater()
        self._choice_models.clear()

    def _label(self):
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setMinimumWidth(0)
        label.setFont(ui_font(TypeSize.BODY))
        label.setStyleSheet(ss_dim_label())
        return label

    def _build_editor(self, idx):
        self._loading_detail = True
        self._image_token += 1
        self._image_signature = None
        _clear_layout(self._editor_layout)
        self._fields, self._captions, self._grids = {}, {}, []
        self._field_labels = {}
        entry = self._entries[idx]
        self._card(ui_text('card_identity'), 'fa6s.id-card')
        for key, caption in (('medal_type', 'card_category'), ('char_id', 'ui_assist_character'),
                ('letter', 'card_variant'), ('part', 'ui_customcardparam_part'),
                ('card_id', 'card_card_id'), ('index', 'card_index')):
            self._add_field(key, ui_text(caption), entry)
        grid = self._card(ui_text('card_inspector'), 'fa6s.image', columns=1,
                          subtitle=ui_text('card_preview_scope'))
        self._summary = self._label()
        self._preview = ImagePreview()
        self._preview_status = self._label()
        grid.addWidget(self._summary, 0, 0)
        grid.addWidget(self._preview, 1, 0)
        grid.addWidget(self._preview_status, 2, 0)
        self._card(ui_text('card_game_text'), 'fa6s.font', columns=1)
        for key in MESSAGE_KEYS:
            self._add_field(key, ui_text('card_' + key), entry)
        self._card(ui_text('gallery_access'), 'fa6s.lock')
        for key, caption in (('unlock_condition', 'ui_charviewer_unlock_condition'),
                ('price', 'gallery_price'), ('unk18', 'card_required'),
                ('dlc_id', 'ui_charviewer_dlc_id'), ('patch', 'ui_customcardparam_patch'),
                ('unk', 'card_native_access')):
            self._add_field(key, ui_text(caption), entry)
        self._card(ui_text('card_contents'), 'fa6s.list')
        for key in ('unk7_0', 'unk7_1', 'unk7_2', 'unk7_3'):
            self._add_field(key, self._operand_caption(key, entry), entry, ui_text('card_hint_operands'))
        for i in range(1, 5):
            self._add_field(f'sfx{i}', ui_text('card_sound_slot', slot=i), entry, ui_text('card_hint_sounds'))
        grid = self._card(ui_text('gallery_diagnostics'), 'fa6s.circle-info', columns=1)
        self._diagnostics = self._label()
        grid.addWidget(self._diagnostics, 0, 0)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._refresh_detail()

    def _operand_caption(self, key, entry):
        kind = entry['medal_type']
        if key in ('unk7_0', 'unk7_1') and kind == 4:
            return ui_text('card_victory_slot', slot=1 if key == 'unk7_0' else 2)
        if key in ('unk7_2', 'unk7_3') and kind == 3:
            return ui_text('card_taunt_slot', slot=1 if key == 'unk7_2' else 2)
        if key == 'unk7_2' and kind == 7:
            return ui_text('card_taunt_speech_count')
        if key == 'unk7_0' and kind == 7:
            return ui_text('card_victory_speech_count')
        return ui_text('card_stored_operand', field=key)

    def _draft(self):
        values, errors = {}, []
        for key, edit in self._fields.items():
            try:
                values[key] = parse_field(key, edit.value_text() if isinstance(edit, EditorValueCombo) else edit.text())
                invalid = False
            except (ValueError, OverflowError, UnicodeError):
                errors.append(key)
                invalid = True
            if bool(edit.property('cardInvalid')) != invalid:
                edit.setStyleSheet(ss_input_validation(invalid))
                edit.setProperty('cardInvalid', invalid)
        return values, errors

    def _apply_current_entry(self, show_errors=True):
        if self._current_index is None or not self._fields:
            return True
        values, errors = self._draft()
        if errors:
            if show_errors:
                edit = self._fields[errors[0]]
                QMessageBox.warning(self, ui_text('dlg_title_warning'),
                    ui_text('gallery_invalid', field=self._captions[errors[0]]))
                self._editor_scroll.ensureWidgetVisible(edit)
                edit.setFocus()
            return False
        self._entries[self._current_index].update(values)
        return True

    def _on_field_changed(self, *args):
        if self._loading_detail or self._current_index is None:
            return
        self._apply_current_entry(show_errors=False)
        self._list_dirty = True
        self._update_dirty()
        self._detail_timer.start()

    def _update_dirty(self):
        self._dirty = bool(self._draft()[1]) or [self._public(e) for e in self._entries] != self._snapshot
        self._update_action_state()

    def _update_action_state(self):
        loaded = self._raw is not None
        selected = self._current_index is not None and 0 <= self._current_index < len(self._entries)
        self._btn_save.setEnabled(loaded and self._dirty and not self._draft()[1])
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and selected)
        self._btn_del.setEnabled(loaded and selected)
        refresh_file_actions(self, loaded=loaded)
        set_file_label(self._lbl_file, self._filepath, dirty=self._dirty)

    def _refresh_detail(self):
        if self._current_index is None or not self._fields or self._loading_detail:
            return
        _, errors = self._draft()
        if errors:
            self._image_token += 1
            self._image_signature = None
            self._preview.set_image(None)
            self._summary.setText(ui_text('gallery_pending'))
            self._preview_status.clear()
            self._diagnostics.setText(ui_text('gallery_pending'))
            self._reflow()
            return
        entry = self._entries[self._current_index]
        if self._list_dirty:
            self._cache_search(entry)
            button = self._entry_buttons[self._current_index][0] if self._entry_buttons else None
            if button:
                button.set_texts(self._title(entry), self._entry_subtitle(entry), title_limit=26, subtitle_limit=30)
            self._refresh_filters()
            self._filter_list()
            self._list_dirty = False
        kind, values = granted_values(entry)
        self._summary.setText(self._title(entry) + '\n' + ui_text('card_grants_' + kind,
            values=', '.join(map(str, values))))
        self._diagnostics.setText('\n'.join(entry_issues(entry, self._entries, entry)) or ui_text('card_no_issues'))
        for key in ('unk7_0', 'unk7_1', 'unk7_2', 'unk7_3'):
            edit = self._fields[key]
            caption = self._operand_caption(key, entry)
            self._field_labels[key].setText(caption)
            edit.setAccessibleName(caption)
            self._captions[key] = caption
        reference = image_reference(entry)
        signature = (reference, current_language())
        if signature != self._image_signature:
            self._image_signature = signature
            self._image_token += 1
            self._image_pool.clear()
            self._preview.set_image(None)
            if reference is None:
                self._preview_status.setText(ui_text('card_preview_unavailable'))
            elif self._root is None:
                self._preview_status.setText(ui_text('gallery_resources_missing'))
            else:
                self._preview_status.setText(ui_text('gallery_loading'))
                self._image_pool.start(ImageLoadJob(self._signals, self._image_token, 'card',
                    self._root, *reference, current_language(), loader=load_image))
        self._reflow()

    def _image_ready(self, token, kind, image, names, error):
        if token != self._image_token or not self._fields:
            return
        self._preview.set_image(image)
        reference = self._image_signature[0]
        path = resource_path(self._root, reference[0])
        text = error or ui_text('gallery_image_size', width=image.width, height=image.height)
        self._preview_status.setText(text + '\n' + str(path) + '\n' + reference[1])
        self._reflow()

    def _reflow(self):
        width = self._editor_scroll.viewport().width()
        for grid, frames, maximum in self._grids:
            columns = 1 if width < Size.COMPACT_BREAKPOINT else maximum
            for column in range(maximum):
                grid.setColumnStretch(column, int(column < columns))
            for i, frame in enumerate(frames):
                row, column = divmod(i, columns)
                index = grid.indexOf(frame)
                if index < 0 or grid.getItemPosition(index) != (row, column, 1, 1):
                    grid.addWidget(frame, row, column, Qt.AlignmentFlag.AlignTop)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _insert_entry(self, duplicate=False):
        if self._raw is None or not self._apply_current_entry():
            return
        if duplicate and self._current_index is None:
            return
        entry = copy.deepcopy(self._entries[self._current_index]) if duplicate else make_default_entry()
        if not duplicate and self._current_index is not None:
            for key in ('char_id', 'part'):
                entry[key] = self._entries[self._current_index][key]
        try:
            entry['index'], entry['card_id'] = next_identity(self._entries)
        except ValueError as exc:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), str(exc))
            return
        index = self._current_index + 1 if duplicate else len(self._entries)
        self._entries.insert(index, entry)
        self._current_index, self._fields = None, {}
        self._reset_choice_models()
        self._search_box.clear()
        self._refresh_filters(reset=True)
        self._populate_list(index)
        self._update_dirty()

    def _on_add(self):
        self._insert_entry()

    def _on_duplicate(self):
        self._insert_entry(duplicate=True)

    def _on_delete(self):
        if self._current_index is None or not self._apply_current_entry():
            return
        entry = self._entries[self._current_index]
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'),
                ui_text('msg_confirm_delete_item', name=self._title(entry)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = self._current_index
        self._entries.pop(index)
        self._current_index, self._fields = None, {}
        self._reset_choice_models()
        self._search_cache.clear()
        self._refresh_filters()
        self._populate_list(min(index, len(self._entries) - 1) if self._entries else None)
        self._update_dirty()

    def closeEvent(self, event):
        self._detail_timer.stop()
        self._image_pool.clear()
        self._image_token += 1
        super().closeEvent(event)
