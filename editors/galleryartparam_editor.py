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

from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QThreadPool

from core.editor_file_state import set_file_label
from parsers.galleryartparam_parser import (
    parse_galleryartparam_xfbin,
    save_galleryartparam_xfbin,
    make_default_entry,
)
from core.translations import current_language, ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.ui.editor_widgets import EditorFilterCombo, fit_scroll_page
from core.ui.editor_actions import refresh_file_actions
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper
from core.ui.image_preview import ImagePreview, ImageLoadSignals as _ImageSignals, ImageLoadJob as _ImageJob
from core.ui.message_preview import message_lookup
from core.style_helpers import ss_dim_label, ss_input_validation
from core.gallery_tools import (INTEGER_RANGES, MESSAGE_KEYS, parse_field, part_name,
    unlock_choices, next_identity, entry_issues, data_root, load_image, path_choices, resource_path)


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


class GalleryArtParamEditor(QWidget):
    """Embedded editor for GalleryArtParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._dirty = False
        self._current_index: int | None = None
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._fields: dict[str, QWidget] = {}
        self._loading_detail = False

        self._root = None
        self._snapshot = []
        self._search_cache = {}
        self._grids = []
        self._image_token = 0
        self._image_signature = None
        self._signals = _ImageSignals()
        self._signals.finished.connect(self._image_ready)
        self._image_pool = QThreadPool(self)
        self._image_pool.setMaxThreadCount(1)
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(180)
        self._detail_timer.timeout.connect(self._refresh_detail)
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
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
        self._btn_open.clicked.connect(self._do_open)
        self._btn_open.setProperty("designAction", 'open')
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(lambda: self._do_save())
        tl.addWidget(self._btn_save)

        self._lbl_file = QLabel(self._tr("no_file_loaded", ui_text("cpk_no_file")))

        configure_file_label(self._lbl_file)
        self._lbl_file.setMinimumWidth(0)
        self._lbl_file.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tl.addWidget(self._lbl_file, 1)
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main_l = QHBoxLayout(main)
        configure_layout(main_l, LayoutRole.ROOT)

        sidebar = EditorSidebar()


        sl = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._on_filter_changed)
        sl.addWidget(self._search)
        self._part_filter = EditorFilterCombo()
        self._part_filter.addItem(ui_text('ui_customcardparam_part'), None)
        self._part_filter.currentIndexChanged.connect(self._on_filter_changed)
        sl.addWidget(self._part_filter)
        self._unlock_filter = EditorFilterCombo()
        self._unlock_filter.addItem(ui_text('ui_charviewer_unlock_condition'), None)
        self._unlock_filter.currentIndexChanged.connect(self._on_filter_changed)
        sl.addWidget(self._unlock_filter)

        actions = EditorActionRow()

        al = actions.content_layout


        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        al.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.setEnabled(False)
        self._btn_dup.clicked.connect(self._do_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        al.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._do_del)
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
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_scroll.setWidget(self._editor_widget)
        main_l.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_galleryartparam_open_a_galleryartparam_xfbin_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text):
        self._image_token += 1
        self._image_signature = None
        self._fields, self._grids = {}, []
        _clear_layout(self._editor_layout)
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _clear_entry_list(self):
        _clear_layout(self._list_layout)
        self._list_layout.addStretch()

    @staticmethod
    def _public(entry):
        return {k: v for k, v in entry.items() if not k.startswith('_')}

    def _title(self, entry):
        reference = message_lookup(self).resolve(entry['art_string1'])
        return reference.text if reference and reference.text else entry['art_id'] or ui_text('gallery_empty_id')

    def _cache_search(self, entry):
        text = [str(v) for v in self._public(entry).values()]
        text.extend((self._title(entry), part_name(entry['part']), ui_text('char_' + entry['chara_code'])))
        for key in MESSAGE_KEYS:
            result = message_lookup(self).resolve(entry[key])
            if result and result.text:
                text.append(result.text)
        self._search_cache[id(entry)] = ' '.join(text).casefold()

    def _visible_indices(self):
        query = self._search.text().casefold().strip()
        part, unlock = self._part_filter.currentData(), self._unlock_filter.currentData()
        return [i for i, e in enumerate(self._entries)
                if (not query or query in self._search_cache.get(id(e), ''))
                and (part is None or e['part'] == part)
                and (unlock is None or e['unlock_cond'] == unlock)]

    def _refresh_filters(self):
        for combo, key, values in (
            (self._part_filter, 'ui_customcardparam_part', [(v, part_name(v)) for v in sorted({e['part'] for e in self._entries})]),
            (self._unlock_filter, 'ui_charviewer_unlock_condition', unlock_choices(self._entries))):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(ui_text(key), None)
            for value, caption in values:
                if any(e['part' if combo is self._part_filter else 'unlock_cond'] == value for e in self._entries):
                    combo.addItem(caption, value)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)

    def _populate_list(self, preserve_selection=None):
        self._clear_entry_list()
        self._entry_buttons = []
        for i, entry in enumerate(self._entries):
            self._cache_search(entry)
            button = EditorListRow()
            button.set_texts(self._title(entry), entry['art_id'] + ' · ' + part_name(entry['part']))
            button.setToolTip(self._title(entry))
            button.clicked.connect(lambda checked=False, index=i: self._select_entry(index))
            self._list_layout.insertWidget(self._list_layout.count() - 1, button)
            self._entry_buttons.append((button, i))
        self._refresh_filters()
        self._on_filter_changed()
        if preserve_selection is not None:
            self._select_entry(preserve_selection)
        elif self._entries:
            self._select_entry(0)
        else:
            self._current_index = None
            self._set_detail_buttons(False)
            self._show_placeholder(ui_text('ui_galleryartparam_select_a_gallery_entry_to_edit'))

    def _on_filter_changed(self):
        visible = set(self._visible_indices())
        for button, i in self._entry_buttons:
            button.setVisible(i in visible)

    def _set_detail_buttons(self, selected):
        self._btn_dup.setEnabled(selected)
        self._btn_del.setEnabled(selected)

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries):
            return False
        if self._current_index == idx and self._fields:
            return True
        if not self._apply_fields():
            return False
        self._detail_timer.stop()
        self._current_index = idx
        self._set_detail_buttons(True)
        for button, i in self._entry_buttons:
            button.setStyleSheet(ss_sidebar_btn(selected=i == idx))
        self._build_editor(idx)
        self._editor_scroll.verticalScrollBar().setValue(0)
        return True

    def _card(self, title, icon='fa6s.sliders', columns=2, subtitle=None):
        card, grid = make_editor_grid_card(self._editor_widget, title=title,
                                          icon_name=icon, subtitle=subtitle)
        configure_card(card)
        self._editor_layout.addWidget(card)
        self._grids.append((grid, [], columns))
        return grid

    def _choices(self, key, entry):
        if key == 'part':
            return [(v, f'{v} — {part_name(v)}') for v in sorted({*range(9), *(e[key] for e in self._entries)})]
        if key == 'unlock_cond':
            return unlock_choices(self._entries)
        if key == 'menu_index':
            return [(0, ui_text('gallery_precheck_off')), (1, ui_text('gallery_precheck_on'))]
        if key in ('art_path', 'icon_path'):
            return path_choices(self._root, self._entries, key)
        if key in ('chara_code', 'dlc_id', 'patch', 'art_name', 'icon_name'):
            values = {e[key] for e in self._entries}
            if key == 'chara_code':
                from core.dictionary_tools import character_catalog
                characters, _ = character_catalog(self._filepath, load_settings().get('game_files_dir', ''))
                values.update(characters)
            return [(v, f'{v} — {ui_text("char_" + v)}' if key == 'chara_code' and
                     ui_text('char_' + v) != 'char_' + v else str(v)) for v in sorted(values)]
        return None

    def _add_field(self, key, caption, entry):
        grid, frames, _ = self._grids[-1]
        frame, layout, _, _ = make_editor_field_shell(caption)
        choices = self._choices(key, entry)
        value = str(entry[key])
        if choices is not None:
            edit = EditorValueCombo(choices, value)
            edit.currentTextChanged.connect(self._changed)
            content = edit
        else:
            edit = configure_input(QLineEdit(value))
            edit.textChanged.connect(self._changed)
            content = IntegerStepper(edit, *INTEGER_RANGES[key]) if key in INTEGER_RANGES else edit
        configure_field(frame, edit)
        edit.setAccessibleName(caption)
        edit.setToolTip(ui_text('gallery_hint_' + key))
        edit.setProperty('messageReference', key in MESSAGE_KEYS)
        edit.setProperty('messageTextOnly', key in MESSAGE_KEYS)
        layout.addWidget(content)
        frames.append(frame)
        self._fields[key] = edit
        self._captions[key] = caption
        grid.addWidget(frame, len(frames) - 1, 0)

    def _build_editor(self, idx):
        self._loading_detail = True
        self._image_token += 1
        self._image_signature = None
        _clear_layout(self._editor_layout)
        self._fields, self._captions, self._grids = {}, {}, []
        entry = self._entries[idx]
        self._card(self._title(entry), 'fa6s.images', columns=2)
        for key, caption in (('art_id', 'gallery_art_id'), ('chara_code', 'ui_galleryartparam_chara_code'),
                             ('part', 'ui_customcardparam_part'), ('index', 'gallery_index')):
            self._add_field(key, ui_text(caption), entry)
        self._card(ui_text('gallery_images'), 'fa6s.image', columns=1,
                   subtitle=ui_text('gallery_image_scope'))
        self._preview_kind = EditorValueCombo([('art', ui_text('gallery_full_image')),
                                               ('icon', ui_text('gallery_icon_image'))], 'art')
        self._preview_kind.setEditable(False)
        self._preview_kind.currentIndexChanged.connect(self._refresh_detail)
        grid = self._grids[-1][0]
        self._preview = ImagePreview()
        self._preview_status = QLabel()
        self._preview_status.setTextFormat(Qt.TextFormat.PlainText)
        self._preview_status.setWordWrap(True)
        self._preview_status.setMinimumWidth(0)
        self._preview_status.setFont(ui_font(TypeSize.BODY))
        self._preview_status.setStyleSheet(ss_dim_label())
        grid.addWidget(self._preview_kind, 0, 0)
        grid.addWidget(self._preview, 1, 0)
        grid.addWidget(self._preview_status, 2, 0)
        self._card(ui_text('ui_galleryartparam_text'), 'fa6s.font')
        for key, caption in (('art_string1', 'gallery_name_message'), ('art_string2', 'gallery_description_message')):
            self._add_field(key, ui_text(caption), entry)
        self._card(ui_text('ui_galleryartparam_asset_paths'), 'fa6s.link', columns=1)
        for key in ('art_path', 'art_name', 'icon_path', 'icon_name'):
            self._add_field(key, ui_text('ui_galleryartparam_' + key), entry)
        self._card(ui_text('gallery_access'), 'fa6s.lock')
        for key, caption in (('unlock_cond', 'ui_charviewer_unlock_condition'), ('price', 'gallery_price'),
                             ('dlc_id', 'ui_charviewer_dlc_id'), ('patch', 'ui_customcardparam_patch'),
                             ('menu_index', 'gallery_precheck')):
            self._add_field(key, ui_text(caption), entry)
        self._card(ui_text('gallery_diagnostics'), 'fa6s.circle-info', columns=1)
        self._diagnostics = QLabel()
        self._diagnostics.setWordWrap(True)
        self._diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self._diagnostics.setMinimumWidth(0)
        self._diagnostics.setFont(ui_font(TypeSize.BODY))
        self._diagnostics.setStyleSheet(ss_dim_label())
        self._grids[-1][0].addWidget(self._diagnostics, 0, 0)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._reflow()
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
            if bool(edit.property('galleryInvalid')) != invalid:
                edit.setStyleSheet(ss_input_validation(invalid))
                edit.setProperty('galleryInvalid', invalid)
        return values, errors

    def _apply_fields(self, show_errors=True):
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
        entry = self._entries[self._current_index]
        if any(entry[k] != v for k, v in values.items()):
            entry.update(values)
            self._cache_search(entry)
            self._refresh_current_button()
            self._refresh_filters()
            self._on_filter_changed()
        return True

    def _changed(self, *args):
        if self._loading_detail:
            return
        self._apply_fields(show_errors=False)
        self._update_dirty()
        self._detail_timer.start()

    def _update_dirty(self):
        _, errors = self._draft()
        self._dirty = bool(errors) or [self._public(e) for e in self._entries] != self._snapshot
        self._btn_save.setEnabled(self._raw_data is not None and self._dirty and not errors)
        set_file_label(self._lbl_file, self._filepath, dirty=self._dirty)
        refresh_file_actions(self, loaded=self._raw_data is not None)

    def _refresh_current_button(self):
        if self._current_index is None:
            return
        entry = self._entries[self._current_index]
        for button, idx in self._entry_buttons:
            if idx == self._current_index:
                button.set_texts(self._title(entry), entry['art_id'] + ' · ' + part_name(entry['part']))
                button.setToolTip(self._title(entry))
                break

    def _refresh_detail(self, *args):
        if self._current_index is None or not self._fields or self._loading_detail:
            return
        values, errors = self._draft()
        if errors:
            self._diagnostics.setText(ui_text('gallery_pending'))
            # Never leave an old image presented as the result of invalid text.
            self._image_token += 1
            self._image_signature = None
            self._preview.set_image(None)
            self._preview_status.setText(ui_text('gallery_pending'))
            self._reflow()
            return
        entry = dict(self._entries[self._current_index], **values)
        issues = entry_issues(entry, self._entries, self._entries[self._current_index])
        self._diagnostics.setText('\n'.join(issues) if issues else ui_text('gallery_no_issues'))
        kind = self._preview_kind.currentData()
        signature = (kind, entry[kind + '_path'], entry[kind + '_name'], self._root, current_language())
        if signature != self._image_signature:
            self._image_signature = signature
            self._image_token += 1
            self._preview.set_image(None)
            self._preview_status.setText(ui_text('gallery_loading'))
            job = _ImageJob(self._signals, self._image_token, kind, self._root,
                            entry[kind + '_path'], entry[kind + '_name'], signature[-1], loader=load_image)
            self._image_pool.clear()
            self._image_pool.start(job)
        self._reflow()

    def _image_ready(self, token, kind, image, names, error):
        if token != self._image_token or not self._fields:
            return
        self._preview.set_image(image)
        self._preview_status.setText(error if error else ui_text('gallery_image_size', width=image.width, height=image.height))
        if image is not None and self._image_signature is not None:
            try:
                path = resource_path(self._root, self._image_signature[1], self._image_signature[-1])
                self._preview_status.setText(self._preview_status.text() + '\n' +
                                            'data/' + path.relative_to(self._root).as_posix())
            except (OSError, ValueError, AttributeError):
                pass  # An already decoded image may outlive a removed resource.
        edit = self._fields[kind + '_name']
        value = edit.value_text()
        edit.blockSignals(True)
        # Suggestions never replace custom or unfinished input.
        for name in names:
            if edit.findData(name) < 0:
                edit.addItem(name, name)
        index = edit.findData(value)
        edit.setCurrentIndex(index)
        if index < 0:
            edit.setEditText(value)
        edit.blockSignals(False)
        self._reflow()

    def _reflow(self):
        width = self._editor_scroll.viewport().width()
        for grid, frames, maximum in self._grids:
            columns = 1 if width < 760 else maximum
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
        return super().eventFilter(watched, event)

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_galleryartparam_open_galleryartparam'),
            game_files_dialog_dir(target_patterns=('GalleryArtParam.xfbin', 'GalleryArtParam.bin.xfbin')),
            'XFBIN files (*.xfbin);;All files (*)')
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            raw, version, entries = parse_galleryartparam_xfbin(path)
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
        self._image_pool.clear()
        self._image_token += 1
        self._current_index = None
        self._fields = {}
        self._filepath, self._raw_data, self._version, self._entries = str(path), raw, version, entries
        self._root = data_root(path, load_settings().get('game_files_dir', ''))
        self._snapshot = [self._public(e) for e in entries]
        self._dirty = False
        self._search_cache.clear()
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        for combo in (self._part_filter, self._unlock_filter):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._populate_list()
        self._btn_add.setEnabled(True)
        self._update_dirty()
        return True

    def _do_save(self, target_path=None):
        path = target_path or editor_path(self)
        if not path or self._raw_data is None or not self._apply_fields():
            return False
        try:
            save_galleryartparam_xfbin(path, self._raw_data, self._version, self._entries)
            raw, _, saved = parse_galleryartparam_xfbin(path)
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

    def _new_identity(self):
        try:
            return next_identity(self._entries)
        except ValueError as exc:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), str(exc))
            return None

    def _do_add(self):
        if self._raw_data is None or not self._apply_fields():
            return
        identity = self._new_identity()
        if identity is None:
            return
        index, name = identity
        entry = make_default_entry(index)
        entry['art_id'] = name
        self._entries.append(entry)
        self._current_index, self._fields = None, {}
        self._populate_list(len(self._entries) - 1)
        self._update_dirty()

    def _do_dup(self):
        if self._current_index is None or not self._apply_fields():
            return
        identity = self._new_identity()
        if identity is None:
            return
        index = self._current_index + 1
        entry = copy.deepcopy(self._entries[self._current_index])
        entry['index'], entry['art_id'] = identity
        self._entries.insert(index, entry)
        self._current_index, self._fields = None, {}
        self._populate_list(index)
        self._update_dirty()

    def _do_del(self):
        if self._current_index is None or not self._apply_fields():
            return
        entry = self._entries[self._current_index]
        if QMessageBox.question(self, ui_text('ui_customizedefaultparam_delete_entry'),
                ui_text('ui_dlcinfoparam_delete_entry_value_value_value', p0=self._current_index,
                        p1=entry['art_id'], p2=self._title(entry)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = self._current_index
        self._entries.pop(index)
        self._current_index, self._fields = None, {}
        self._populate_list(min(index, len(self._entries) - 1) if self._entries else None)
        self._update_dirty()
