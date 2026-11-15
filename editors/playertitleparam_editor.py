"""Player Title catalog and original-resource inspection; semantics live in core.playertitle_tools."""

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

from PyQt6.QtCore import Qt, QTimer, QEvent, QThreadPool
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from parsers.playertitleparam_parser import (
    make_default_entry,
    parse_playertitleparam_xfbin,
    save_playertitleparam_xfbin,
)
from core.translations import ui_text, current_language
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.editor_file_state import set_file_label
from core.settings import load_settings
from core.style_helpers import ss_dim_label, ss_input_validation
from core.ui.editor_widgets import EditorFilterCombo, fit_scroll_page
from core.ui.editor_actions import refresh_file_actions
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper
from core.ui.message_preview import MessagePreview, message_lookup
from core.ui.image_preview import ImagePreview, ImageLoadJob, ImageLoadSignals
from core.gallery_tools import resource_path, load_image
from core.dictionary_tools import character_catalog
from core.playertitle_tools import (INTEGER_RANGES, MESSAGE_KEYS, parse_field, choices,
    access_name, part_name, character_name, next_identity, entry_issues, data_root, background_reference)


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class PlayerTitleParamEditor(QWidget):
    """Embedded player-card title catalog using Arrow Forge's shared editor UI."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._current_index: int | None = None
        self._fields: dict[str, QWidget] = {}
        self._dirty = False
        self._block_detail = False
        self._grids = []
        self._snapshot = []
        self._search_cache = {}
        self._list_dirty = False
        self._characters = ()
        self._choice_models = {}
        self._root = None
        self._image_token = 0
        self._image_signature = None
        self._signals = ImageLoadSignals()
        self._signals.finished.connect(self._image_ready)
        self._image_pool = QThreadPool(self)
        self._image_pool.setMaxThreadCount(1)
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(150)
        self._detail_timer.timeout.connect(self._refresh_detail)

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key: str, fallback: str, **kwargs) -> str:
        text = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if text == key else text

    # UI construction

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
        self._btn_save.clicked.connect(lambda: self._do_save())
        top_layout.addWidget(self._btn_save)

        self._lbl_file = QLabel(self._tr("no_file_loaded", ui_text("ui_btladjprm_no_file_loaded")))

        configure_file_label(self._lbl_file)
        top_layout.addWidget(self._lbl_file)
        top_layout.addStretch()

        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        list_frame = EditorSidebar()


        list_layout = list_frame.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        list_layout.addWidget(self._search)

        self._access_filter = EditorFilterCombo()
        self._part_filter = EditorFilterCombo()
        self._character_filter = EditorFilterCombo()
        for combo in (self._access_filter, self._part_filter, self._character_filter):
            combo.currentIndexChanged.connect(self._filter_list)
            list_layout.addWidget(combo)

        actions_frame = EditorActionRow()

        actions_layout = actions_frame.content_layout


        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._btn_add.setEnabled(False)
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.clicked.connect(self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._btn_dup.setEnabled(False)
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.clicked.connect(self._do_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._btn_del.setEnabled(False)
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.clicked.connect(self._do_del)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_del, 1)

        list_layout.addWidget(actions_frame)

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
        list_layout.addWidget(self._list_scroll)

        main_layout.addWidget(list_frame)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_scroll.viewport().installEventFilter(self)
        self._list_scroll.viewport().installEventFilter(self)

        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        self._show_placeholder(ui_text("ui_playertitleparam_open_a_playertitleparam_xfbin_file_to_begin_editing"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # File I/O

    @staticmethod
    def _public(entry):
        return {k: v for k, v in entry.items() if not k.startswith('_')}

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_playertitleparam_open_playertitleparam'),
            game_files_dialog_dir(target_patterns=('PlayerTitleParam.xfbin', 'PlayerTitleParam.bin.xfbin')),
            'XFBIN files (*.xfbin);;All files (*)')
        if path:
            self._load(path)

    def _load(self, path):
        try:
            raw, version, entries = parse_playertitleparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=exc))
            return False
        if self._dirty:
            reply = QMessageBox.question(self, ui_text('dlg_title_warning'), ui_text('term_discard_changes'),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Discard:
                return False
        create_backup_on_open(path)
        self._detail_timer.stop()
        self._image_token += 1
        self._image_pool.clear()
        self._current_index, self._fields = None, {}
        self._filepath, self._raw_data, self._version, self._entries = str(path), raw, version, entries
        self._root = data_root(path, load_settings().get('game_files_dir', ''))
        self._characters, _ = character_catalog(path, load_settings().get('game_files_dir', ''))
        self._reset_choice_models()
        self._snapshot = [self._public(e) for e in entries]
        self._dirty = False
        self._search_cache.clear()
        self._search.clear()
        self._refresh_filters(reset=True)
        self._populate_list(0 if entries else None)
        self._update_action_state()
        return True

    def _do_save(self, target_path=None):
        path = target_path or editor_path(self)
        if not path or self._raw_data is None or not self._apply_current_entry():
            return False
        try:
            save_playertitleparam_xfbin(path, self._raw_data, self._version, self._entries)
            raw, _, saved = parse_playertitleparam_xfbin(path)
            for entry, disk in zip(self._entries, saved):
                entry.update({k: v for k, v in disk.items() if k.startswith('_')})
            self._raw_data = raw
            commit_save_path(self, str(path))
            self._snapshot = [self._public(e) for e in self._entries]
            self._update_dirty()
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False

    # Read-only catalogs and navigation

    def _title(self, entry):
        text, _ = message_lookup(self).text(entry['card_string1']) if entry['card_string1'] else ('', '')
        return text.replace('\n', ' ') if text else entry['title_id'] or ui_text('title_untitled')

    def _entry_title(self, idx):
        return self._title(self._entries[idx])

    def _entry_subtitle(self, entry):
        return f"{entry['title_id']} · {character_name(entry['chara_code'])}"

    def _cache_search(self, entry):
        lookup = message_lookup(self)
        messages = [lookup.text(entry[key])[0] for key in MESSAGE_KEYS if entry[key]]
        self._search_cache[id(entry)] = ' '.join([*(str(v) for k, v in entry.items() if not k.startswith('_')),
            *messages, character_name(entry['chara_code']), part_name(entry['part']),
            access_name(entry['unlock_cond'])]).casefold()

    def _refresh_filters(self, reset=False):
        for combo, key, caption, label in (
                (self._access_filter, 'unlock_cond', 'ui_charviewer_unlock_condition', access_name),
                (self._part_filter, 'part', 'ui_customcardparam_part', part_name),
                (self._character_filter, 'chara_code', 'ui_assist_character', character_name)):
            value = None if reset else combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(ui_text(caption), None)
            for item in sorted({e[key] for e in self._entries}):
                combo.addItem(label(item), item)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        reset_button = self._search.parentWidget().findChild(QPushButton, 'EditorFilterReset')
        if reset_button:
            reset_button.refresh()

    def _clear_entry_list(self):
        _clear_layout(self._list_layout)
        self._list_layout.addStretch()
        self._entry_buttons = []

    def _populate_list(self, selected=None):
        self._clear_entry_list()
        for idx, entry in enumerate(self._entries):
            self._cache_search(entry)
            button = EditorListRow()
            button.set_texts(self._title(entry), self._entry_subtitle(entry), title_limit=26, subtitle_limit=30)
            button.setToolTip(self._title(entry) + '\n' + self._entry_subtitle(entry))
            button.clicked.connect(lambda _, i=idx: self._select_entry(i))
            self._list_layout.insertWidget(self._list_layout.count() - 1, button)
            self._entry_buttons.append((button, idx))
        self._list_dirty = False
        self._filter_list()
        if selected is not None:
            self._select_entry(selected)
        elif not self._entries:
            self._show_placeholder(ui_text('ui_playertitleparam_select_a_player_title_entry_to_edit'))
        self._update_action_state()

    def _filter_list(self, *args):
        query = self._search.text().casefold().strip()
        filters = ((self._access_filter, 'unlock_cond'), (self._part_filter, 'part'),
                   (self._character_filter, 'chara_code'))
        for button, idx in self._entry_buttons:
            entry = self._entries[idx]
            button.setVisible((not query or query in self._search_cache.get(id(entry), '')) and
                all(combo.currentData() is None or combo.currentData() == entry[key] for combo, key in filters))

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries) or not self._apply_current_entry():
            return False
        self._detail_timer.stop()
        if self._list_dirty:
            self._refresh_detail()
        previous = self._current_index
        self._current_index = idx
        if previous is not None and previous != idx and previous < len(self._entry_buttons):
            self._entry_buttons[previous][0].set_selected(False)
        self._entry_buttons[idx][0].set_selected(True)
        self._list_scroll.ensureWidgetVisible(self._entry_buttons[idx][0])
        self._build_editor(idx)
        self._editor_scroll.verticalScrollBar().setValue(0)
        # A newly populated list has not received its LayoutRequest yet.
        # Scroll after Qt positions the rows, using the current selection so
        # a queued callback never pulls a later selection back to an old row.
        QTimer.singleShot(0, self._ensure_selected_visible)
        self._update_action_state()
        return True

    def _ensure_selected_visible(self):
        idx = self._current_index
        if idx is not None and idx < len(self._entry_buttons):
            button = self._entry_buttons[idx][0]
            if not button.isHidden():
                self._list_scroll.ensureWidgetVisible(button)

    def _refresh_entry_button(self, idx):
        entry = self._entries[idx]
        for button, i in self._entry_buttons:
            if i == idx:
                button.set_texts(self._title(entry), self._entry_subtitle(entry), title_limit=26, subtitle_limit=30)
                button.setToolTip(self._title(entry) + '\n' + self._entry_subtitle(entry))
                break

    def _update_action_state(self):
        loaded = self._raw_data is not None
        selected = self._current_index is not None and 0 <= self._current_index < len(self._entries)
        self._btn_save.setEnabled(loaded and self._dirty and not self._draft()[1])
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and selected)
        self._btn_del.setEnabled(loaded and selected)
        refresh_file_actions(self, loaded=loaded)
        set_file_label(self._lbl_file, self._filepath, dirty=self._dirty)

    # Forms retain their widgets, focus, incomplete text and undo during reflow.

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

    def _add_field(self, key, caption, entry):
        grid, frames, _ = self._grids[-1]
        frame, layout, _, _ = make_editor_field_shell(caption)
        signature = (key, current_language())
        model = self._choice_models.get(signature)
        options = choices(key, self._entries, self._characters, self._root) if model is None else ()
        if options is not None:
            if model is None:
                model = EditorValueCombo.choice_model(options, self)
                self._choice_models[signature] = model
            edit = EditorValueCombo((), str(entry[key]), model=model)
            edit.currentTextChanged.connect(self._on_field_changed)
            content = edit
        else:
            edit = configure_input(QLineEdit(str(entry[key])))
            edit.textChanged.connect(self._on_field_changed)
            content = IntegerStepper(edit, *INTEGER_RANGES[key]) if key in INTEGER_RANGES else edit
        configure_field(frame, edit)
        edit.setAccessibleName(caption)
        edit.setToolTip(ui_text('title_hint_' + key))
        edit.setProperty('messageReference', key in MESSAGE_KEYS)
        layout.addWidget(content)
        if key in MESSAGE_KEYS:
            # Shared resolver; these are messages, not texture references.
            layout.addWidget(MessagePreview(edit.lineEdit(), message_lookup(self)))
        frames.append(frame)
        grid.addWidget(frame, len(frames) - 1, 0)
        self._fields[key], self._captions[key] = edit, caption

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
        policy = label.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        label.setSizePolicy(policy)
        label.setFont(ui_font(TypeSize.BODY))
        label.setStyleSheet(ss_dim_label())
        return label

    def _build_editor(self, idx):
        self._block_detail = True
        self._image_token += 1
        self._image_signature = None
        _clear_layout(self._editor_layout)
        self._fields, self._captions, self._grids = {}, {}, []
        entry = self._entries[idx]
        self._card(ui_text('title_entry'), 'fa6s.id-card')
        for key, label in (('title_id', 'title_title_id'), ('index', 'title_index'),
                           ('chara_code', 'ui_assist_character'), ('part', 'ui_customcardparam_part')):
            self._add_field(key, ui_text(label), entry)
        self._card(ui_text('title_text'), 'fa6s.font', columns=1,
                   subtitle=ui_text('title_text_scope'))
        for key in MESSAGE_KEYS:
            self._add_field(key, ui_text('title_' + key), entry)
        self._card(ui_text('title_background'), 'fa6s.image', columns=1,
                   subtitle=ui_text('title_preview_scope'))
        self._add_field('anim_id', ui_text('title_anim_id'), entry)
        grid = self._grids[-1][0]
        self._preview, self._preview_status = ImagePreview(), self._label()
        grid.addWidget(self._preview, 1, 0)
        grid.addWidget(self._preview_status, 2, 0)
        self._card(ui_text('gallery_access'), 'fa6s.lock')
        for key, label in (('unlock_cond', 'ui_charviewer_unlock_condition'), ('unk3', 'title_unk3'),
                           ('dlc_id', 'ui_charviewer_dlc_id'), ('patch', 'ui_customcardparam_patch'),
                           ('unk2', 'title_unk2')):
            self._add_field(key, ui_text(label), entry)
        self._card(ui_text('gallery_diagnostics'), 'fa6s.circle-info', columns=1)
        self._diagnostics = self._label()
        self._grids[-1][0].addWidget(self._diagnostics, 0, 0)
        self._editor_layout.addStretch()
        self._block_detail = False
        self._refresh_detail()

    def _draft(self):
        values, errors = {}, []
        for key, edit in self._fields.items():
            try:
                values[key] = parse_field(key, edit.value_text() if isinstance(edit, EditorValueCombo) else edit.text())
                invalid = False
            except (ValueError, OverflowError, UnicodeError):
                errors.append(key)
                invalid = True
            if bool(edit.property('titleInvalid')) != invalid:
                edit.setStyleSheet(ss_input_validation(invalid))
                edit.setProperty('titleInvalid', invalid)
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
        if self._block_detail or self._current_index is None:
            return
        self._apply_current_entry(show_errors=False)
        self._list_dirty = True
        self._update_dirty()
        self._detail_timer.start()

    def _update_dirty(self):
        self._dirty = bool(self._draft()[1]) or [self._public(e) for e in self._entries] != self._snapshot
        self._update_action_state()

    def _refresh_detail(self):
        if self._current_index is None or not self._fields or self._block_detail:
            return
        _, errors = self._draft()
        if errors:
            self._image_token += 1
            self._image_signature = None
            self._preview.set_image(None)
            self._preview_status.clear()
            self._diagnostics.setText(ui_text('gallery_pending'))
        else:
            entry = self._entries[self._current_index]
            if self._list_dirty:
                self._cache_search(entry)
                self._refresh_entry_button(self._current_index)
                self._refresh_filters()
                self._filter_list()
                self._list_dirty = False
            issues = entry_issues(entry, self._entries, entry)
            self._diagnostics.setText('\n'.join([ui_text('title_routing',
                character=character_name(entry['chara_code']), part=part_name(entry['part']),
                access=access_name(entry['unlock_cond']), index=entry['index']), *issues]))
            reference = background_reference(entry['anim_id'])
            signature = (reference, current_language())
            if signature != self._image_signature:
                self._image_signature = signature
                self._image_token += 1
                self._image_pool.clear()
                self._preview.set_image(None)
                if reference is None:
                    self._preview_status.setText(ui_text('title_background_unavailable'))
                elif self._root is None:
                    self._preview_status.setText(ui_text('gallery_resources_missing'))
                else:
                    self._preview_status.setText(ui_text('gallery_loading'))
                    self._image_pool.start(ImageLoadJob(self._signals, self._image_token, 'background',
                        self._root, *reference, current_language(), loader=load_image))
        self._reflow()

    def _image_ready(self, token, kind, image, names, error):
        if token != self._image_token or not self._fields:
            return
        self._preview.set_image(image)
        reference = self._image_signature[0]
        path = resource_path(self._root, reference[0])
        text = error or ui_text('gallery_image_size', width=image.width, height=image.height)
        self._preview_status.setText(text + '\n' + path.as_posix() + '\n' + reference[1])
        self._reflow()

    def closeEvent(self, event):
        self._detail_timer.stop()
        self._image_pool.clear()
        self._image_token += 1
        super().closeEvent(event)

    def _reflow(self):
        width = self._editor_scroll.viewport().width()
        for grid, frames, maximum in self._grids:
            columns = 1 if width < Size.COMPACT_BREAKPOINT else maximum
            for col in range(maximum):
                grid.setColumnStretch(col, int(col < columns))
            for i, frame in enumerate(frames):
                row, col = divmod(i, columns)
                position = grid.indexOf(frame)
                if position < 0 or grid.getItemPosition(position) != (row, col, 1, 1):
                    grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        elif watched is self._list_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._ensure_selected_visible)
        return super().eventFilter(watched, event)

    # Structural operations allocate a fresh native identity without changing links.

    def _insert_entry(self, duplicate=False):
        if self._raw_data is None or not self._apply_current_entry():
            return
        if duplicate and self._current_index is None:
            return
        entry = copy.deepcopy(self._entries[self._current_index]) if duplicate else make_default_entry()
        if not duplicate and self._current_index is not None:
            current = self._entries[self._current_index]
            for key in ('part', 'chara_code', 'anim_id'):
                entry[key] = current[key]
        try:
            entry['index'], entry['title_id'] = next_identity(self._entries)
        except ValueError as exc:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), str(exc))
            return
        index = self._current_index + 1 if duplicate else len(self._entries)
        self._entries.insert(index, entry)
        self._reset_choice_models()
        self._current_index, self._fields = None, {}
        self._search.clear()
        self._refresh_filters(reset=True)
        self._populate_list(index)
        self._update_dirty()

    def _do_add(self):
        self._insert_entry()

    def _do_dup(self):
        self._insert_entry(duplicate=True)

    def _do_del(self):
        if self._current_index is None or not self._apply_current_entry():
            return
        entry = self._entries[self._current_index]
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'),
                ui_text('msg_confirm_delete_item', name=self._title(entry)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = self._current_index
        self._entries.pop(index)
        self._reset_choice_models()
        self._current_index, self._fields = None, {}
        self._search_cache.clear()
        self._refresh_filters()
        self._populate_list(min(index, len(self._entries) - 1) if self._entries else None)
        self._update_dirty()
