"""Visual customization defaults with exact input and native-backed diagnostics."""
import copy
import os
import struct

from PyQt6.QtCore import QEvent, QSignalBlocker, QTimer, Qt
from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout,
    QHBoxLayout, QFileDialog, QMessageBox, QScrollArea, QSizePolicy)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.style_helpers import (make_editor_field_shell, make_editor_grid_card,
    make_empty_state, ss_bg_dark, ss_transparent, ss_dim_label, ss_input_validation)
from core.ui.editor_widgets import (EditorActionRow, EditorListRow, EditorSeparator,
    EditorSidebar, EditorToolbar, EditorFilterCombo, configure_button, configure_card,
    configure_field, configure_file_label, configure_input, configure_layout,
    configure_scrollarea, configure_search, fit_scroll_page)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import (commit_save_path, editor_path,
    install_file_actions, refresh_file_actions)
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import FloatStepper
from core.ui.transform_comparison import TransformComparison
from core.customize_tools import (FLOAT_KEYS, TRANSFORM_KEYS,
    parse_field, slot_name, character_choices, transform, effective_scale,
    edit_rotation, entry_issues)
from core.dictionary_tools import character_catalog
from core.story_tools import character_name
from core.editor_file_state import set_file_label
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from parsers.customizedefaultparam_parser import (parse_customizedefaultparam_xfbin,
    save_customizedefaultparam_xfbin, make_default_entry)


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


class CustomizeDefaultParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key)
        self._embedded = embedded
        self._filepath = self._raw_data = None
        self._version = 1000
        self._entries = []
        self._references = {}
        self._characters = frozenset()
        self._catalog_error = ''
        self._current_index = None
        self._dirty = False
        self._filter_text = ''
        self._entry_buttons = []
        self._fields, self._captions, self._grids = {}, {}, []
        self._loading_detail = False
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
        self._btn_save.clicked.connect(self._do_save)
        tl.addWidget(self._btn_save)

        self._lbl_file = QLabel(self._tr("no_file_loaded", ui_text("cpk_no_file")))

        configure_file_label(self._lbl_file)
        self._lbl_file.setMinimumWidth(0)
        self._lbl_file.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
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
        self._slot_filter = EditorFilterCombo()
        self._slot_filter.addItem(ui_text('customize_mode'), None)
        for slot in (0, 1, 2):
            self._slot_filter.addItem(slot_name(slot), slot)
        self._slot_filter.currentIndexChanged.connect(self._on_filter_changed)
        sl.addWidget(self._slot_filter)

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
        margins = sl.contentsMargins()
        sidebar.setFixedWidth(max(Size.SIDEBAR_DEFAULT,
            actions.sizeHint().width() + margins.left() + margins.right()))

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
        self._editor_scroll.setWidget(self._editor_widget)
        self._editor_scroll.viewport().installEventFilter(self)
        main_l.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_customizedefaultparam_open_a_customizedefaultparam_xfbin_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        self._fields, self._grids = {}, []
        card = make_empty_state(self._editor_widget, title=ui_text('customize_title'),
                               text=text, icon_name='fa6s.user-gear')
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _visible_indices(self):
        text = self._filter_text.casefold().strip()
        mode = self._slot_filter.currentData()
        return [i for i, e in enumerate(self._entries)
                if (mode is None or e['slot'] == mode) and
                (not text or text in f"{e['char_code']} {character_name(e['char_code'])} {e['slot']} {slot_name(e['slot'])}".casefold())]

    def _populate_list(self, preserve_selection=None):
        _clear_layout(self._list_layout)
        self._entry_buttons = []
        visible = self._visible_indices()
        for i in visible:
            btn = EditorListRow()
            e = self._entries[i]
            btn.set_texts(character_name(e['char_code']), f"{e['char_code']} · {slot_name(e['slot'])}",
                          title_limit=26, subtitle_limit=30)
            btn.clicked.connect(lambda _, index=i: self._select_entry(index))
            self._list_layout.addWidget(btn)
            self._entry_buttons.append((btn, i))
        self._list_layout.addStretch()
        selected = preserve_selection if preserve_selection in visible else (visible[0] if visible else None)
        if selected == self._current_index and self._fields:
            for btn, i in self._entry_buttons:
                btn.set_selected(i == selected)
        elif selected is not None:
            self._select_entry(selected)
        else:
            self._current_index = None
            self._show_placeholder(ui_text('ui_dictionaryparam_select_an_entry_to_edit'))
        self._set_detail_buttons(self._current_index is not None)

    def _set_detail_buttons(self, selected):
        self._btn_dup.setEnabled(selected)
        self._btn_del.setEnabled(selected)

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries) or not self._apply_fields():
            return False
        self._current_index = idx
        self._set_detail_buttons(True)
        for btn, i in self._entry_buttons:
            btn.set_selected(i == idx)
        self._build_editor(idx)
        return True

    def _card(self, title, columns=2, subtitle=None):
        card, grid = make_editor_grid_card(self._editor_widget, title=title,
            icon_name='fa6s.sliders', subtitle=subtitle)
        configure_card(card)
        self._editor_layout.addWidget(card)
        self._grids.append((grid, [], columns))
        return grid

    def _field(self, grid, key, caption, hint, choices=None, step=None):
        value = self._entries[self._current_index][key]
        frame, layout, _, _ = make_editor_field_shell(caption)
        if choices is not None:
            widget = EditorValueCombo(choices, value)
            widget.editTextChanged.connect(self._on_field_changed)
            widget.lineEdit().setCursorPosition(0)
        else:
            widget = configure_input(QLineEdit(str(value)))
            widget.textChanged.connect(self._on_field_changed)
            widget.setCursorPosition(0)
        widget.setProperty('messageReference', False)
        widget.setToolTip(hint)
        widget.setAccessibleName(caption)
        layout.addWidget(FloatStepper(widget, step) if step else widget)
        configure_field(frame, widget)
        self._fields[key], self._captions[key] = widget, caption
        next(frames for g, frames, _ in self._grids if g is grid).append(frame)

    def _build_editor(self, idx):
        self._loading_detail = True
        _clear_layout(self._editor_layout)
        self._fields, self._captions, self._grids = {}, {}, []
        entry = self._entries[idx]
        self._references.setdefault(id(entry), copy.deepcopy(entry))
        grid = self._card(ui_text('customize_target'))
        self._field(grid, 'char_code', ui_text('ui_customizedefaultparam_char_code'),
            ui_text('customize_character_hint'), choices=character_choices(self._entries, self._characters))
        slots = sorted({0, 1, 2, *(e['slot'] for e in self._entries)})
        self._field(grid, 'slot', ui_text('customize_mode'), ui_text('customize_mode_hint'),
                    choices=[(i, f'{i} — {slot_name(i)}') for i in slots])
        grid = self._card(ui_text('customize_transform'), 2)
        for key, caption, hint, step in (
            ('pos_x', 'ui_customizedefaultparam_pos_x', 'customize_position_hint', 1),
            ('pos_y', 'ui_customizedefaultparam_pos_y', 'customize_position_hint', 1),
            ('unk', 'customize_rotation', 'customize_rotation_hint', 1),
            ('scale', 'ui_customizedefaultparam_scale', 'customize_scale_hint', '.01')):
            self._field(grid, key, ui_text(caption), ui_text(hint), step=step)
        grid = self._card(ui_text('customize_diagram'), 1, ui_text('customize_diagram_caption'))
        self._preview = TransformComparison(ui_text('customize_original'), ui_text('customize_current'))
        self._preview.setToolTip(ui_text('customize_diagram_hint') + '\n' + ui_text('customize_drag_hint'))
        self._preview.setAccessibleName(ui_text('customize_diagram'))
        self._preview.positionEdited.connect(self._set_position)
        grid.addWidget(self._preview, 0, 0)
        self._summary = self._label()
        grid.addWidget(self._summary, 1, 0)
        self._restore_btn = configure_button(QPushButton(ui_text('customize_restore')))
        self._restore_btn.hide()
        self._restore_btn.setMinimumWidth(0)
        self._restore_btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._restore_btn.clicked.connect(self._restore_transform)
        grid.addWidget(self._restore_btn, 2, 0)
        grid = self._card(ui_text('customize_connections'), 1)
        self._diagnostics = self._label()
        grid.addWidget(self._diagnostics)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._reflow()
        self._refresh_detail()
        self._editor_scroll.verticalScrollBar().setValue(0)

    def _label(self):
        label = QLabel()
        label.setFont(ui_font(TypeSize.BODY))
        label.setStyleSheet(ss_dim_label())
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _reflow(self):
        width = self._editor_scroll.viewport().width()
        for grid, frames, maximum in self._grids:
            if not frames:
                continue
            columns = 1 if width < Size.COMPACT_BREAKPOINT else maximum
            for col in range(maximum):
                grid.setColumnStretch(col, int(col < columns))
            for i, frame in enumerate(frames):
                row, col = divmod(i, columns)
                if grid.indexOf(frame) < 0 or grid.getItemPosition(grid.indexOf(frame)) != (row, col, 1, 1):
                    grid.addWidget(frame, row, col, Qt.AlignmentFlag.AlignTop)
            grid.invalidate()
            grid.parentWidget().updateGeometry()
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _draft(self):
        values, errors = {}, []
        for key, widget in self._fields.items():
            text = widget.value_text() if isinstance(widget, EditorValueCombo) else widget.text()
            try:
                entry = self._entries[self._current_index]
                # Preserve untouched nonfinite source words, including NaN payloads.
                if key in FLOAT_KEYS and text == str(entry[key]):
                    values[key] = entry[key]
                else:
                    values[key] = parse_field(key, text)
                invalid = False
            except (ValueError, OverflowError, UnicodeError, struct.error):
                errors.append(key)
                invalid = True
            if bool(widget.property('customizeInvalid')) != invalid:
                widget.setStyleSheet(ss_input_validation(invalid))
                widget.setProperty('customizeInvalid', invalid)
        return values, errors

    def _apply_fields(self):
        if not self._fields or self._current_index is None:
            return True
        values, errors = self._draft()
        if errors:
            widget = self._fields[errors[0]]
            widget.setFocus()
            return False
        self._entries[self._current_index].update(values)
        return True

    def _on_field_changed(self, *_):
        if self._loading_detail:
            return
        self._mark_dirty()
        self._refresh_detail()

    def _refresh_detail(self):
        values, errors = self._draft()
        entry = self._entries[self._current_index]
        original = self._references.get(id(entry))
        self._restore_btn.setEnabled(original is not None)
        if errors:
            self._diagnostics.setText(ui_text('customize_invalid', fields=', '.join(self._captions[k] for k in errors)))
            self._preview.set_transforms(transform(original) if original else None, None)
            self._preview.setEnabled(False)
            self._summary.setText('')
        else:
            draft = dict(entry, **values)
            for button, index in self._entry_buttons:
                if index == self._current_index:
                    button.set_texts(character_name(draft['char_code']),
                        f"{draft['char_code']} · {slot_name(draft['slot'])}", title_limit=26, subtitle_limit=30)
                    break
            current = transform(draft)
            self._preview.setEnabled(current is not None)
            self._preview.set_transforms(transform(original) if original else None, current)
            self._summary.setText(ui_text('customize_native_values',
                scale=str(effective_scale(draft['scale'])), rotation=str(edit_rotation(draft['unk']))) if current else ui_text('customize_nonfinite'))
            rows = [draft if e is entry else e for e in self._entries]
            issues = entry_issues(draft, rows, self._characters) if current else [ui_text('customize_nonfinite')]
            if self._catalog_error:
                issues.append(ui_text('customize_catalog_error', error=self._catalog_error))
            self._diagnostics.setText('\n'.join(issues) if issues else ui_text('customize_lookup_hint'))
        fit_scroll_page(self._editor_scroll)

    def _set_position(self, x, y):
        if not self._apply_fields():
            return
        try:
            positions = [(key, str(parse_field(key, str(value))))
                         for key, value in (('pos_x', x), ('pos_y', y))]
        except (ValueError, OverflowError, struct.error):
            return
        self._loading_detail = True
        try:
            for key, text in positions:
                self._fields[key].setText(text)
        finally:
            self._loading_detail = False
        self._on_field_changed()

    def _restore_transform(self):
        if self._current_index is None:
            return
        original = self._references.get(id(self._entries[self._current_index]))
        if original is None:
            return
        self._loading_detail = True
        for key in TRANSFORM_KEYS:
            self._fields[key].setText(str(original[key]))
        self._loading_detail = False
        self._on_field_changed()

    def _on_filter_changed(self, *_):
        if not self._apply_fields():
            with QSignalBlocker(self._search), QSignalBlocker(self._slot_filter):
                self._search.setText(self._filter_text)
                self._slot_filter.setCurrentIndex(getattr(self, '_accepted_filter', 0))
            return
        self._filter_text = self._search.text()
        self._accepted_filter = self._slot_filter.currentIndex()
        self._populate_list(self._current_index)

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(self._filepath is not None)
        set_file_label(self._lbl_file, self._filepath, dirty=True)

    def _load_file(self, path):
        raw, version, entries = parse_customizedefaultparam_xfbin(path)
        self._filepath, self._raw_data, self._version, self._entries = path, raw, version, entries
        self._references = {id(e): copy.deepcopy(e) for e in entries}
        self._characters, self._catalog_error = character_catalog(path, load_settings().get('game_files_dir', ''))
        self._current_index = None
        self._fields = {}
        self._dirty = False
        self._filter_text = ''
        self._accepted_filter = 0
        with QSignalBlocker(self._search), QSignalBlocker(self._slot_filter):
            self._search.clear()
            self._slot_filter.clear()
            self._slot_filter.addItem(ui_text('customize_mode'), None)
            for slot in sorted({0, 1, 2, *(e['slot'] for e in entries)}):
                self._slot_filter.addItem(slot_name(slot), slot)
        self._btn_add.setEnabled(True)
        self._btn_save.setEnabled(False)
        set_file_label(self._lbl_file, path)
        refresh_file_actions(self, loaded=True)
        self._populate_list()

    def _do_open(self):
        if not self._apply_fields():
            return
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_customizedefaultparam_open_customizedefaultparam'),
            game_files_dialog_dir(os.path.expanduser('~'), ('CustomizeDefaultParam.bin.xfbin',)),
            'XFBIN files (*.xfbin);;All files (*)')
        if not path:
            return
        try:
            create_backup_on_open(path)
            self._load_file(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), str(exc))

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or not self._apply_fields():
            return False
        try:
            save_customizedefaultparam_xfbin(save_path, self._raw_data, self._version, self._entries)
            # Keep object identity and the opened-file comparison, but refresh writer offsets.
            raw, _, saved = parse_customizedefaultparam_xfbin(save_path)
            for entry, disk in zip(self._entries, saved):
                entry.update({key: value for key, value in disk.items() if key.startswith('_')})
            self._raw_data = raw
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._lbl_file, save_path)
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text('ui_customizedefaultparam_save_failed'), str(exc))
            return False

    def _do_add(self):
        if self._raw_data is None or not self._apply_fields():
            return
        # Fill an absent native mode before making a duplicate lookup identity.
        selected = self._entries[self._current_index] if self._current_index is not None else None
        codes = [selected['char_code']] if selected else []
        codes += [c for c, _ in character_choices(self._entries, self._characters) if c not in codes]
        pair = next(((code, slot) for code in codes for slot in (0, 1, 2)
                     if not any(e['char_code'] == code and e['slot'] == slot for e in self._entries)), None)
        if pair is None:
            pair = (selected['char_code'] if selected else '', selected['slot'] if selected else 0)
        donor = next((e for e in self._entries if e['slot'] == pair[1]), selected)
        entry = copy.deepcopy(donor) if donor else make_default_entry(*pair)
        entry.update(char_code=pair[0], slot=pair[1])
        entry.pop('_offset', None)
        self._entries.append(entry)
        self._references[id(entry)] = copy.deepcopy(entry)
        self._mark_dirty()
        self._reveal_entry(len(self._entries) - 1)

    def _reveal_entry(self, idx):
        with QSignalBlocker(self._search), QSignalBlocker(self._slot_filter):
            self._search.clear()
            self._slot_filter.setCurrentIndex(0)
        self._filter_text, self._accepted_filter = '', 0
        self._populate_list(idx)

    def _do_dup(self):
        if self._current_index is None or not self._apply_fields():
            return
        index = self._current_index + 1
        entry = copy.deepcopy(self._entries[self._current_index])
        entry.pop('_offset', None)
        self._entries.insert(index, entry)
        self._references[id(entry)] = copy.deepcopy(entry)
        self._mark_dirty()
        # Clear the old form before insertion changes index ownership.
        self._fields = {}
        self._current_index = None
        self._reveal_entry(index)

    def _do_del(self):
        if self._current_index is None or not self._apply_fields():
            return
        entry = self._entries[self._current_index]
        if QMessageBox.question(self, ui_text('ui_customizedefaultparam_delete_entry'),
            ui_text('ui_customizedefaultparam_delete_entry_value_value_slot_value', p0=self._current_index,
                    p1=entry['char_code'], p2=entry['slot']),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = self._current_index
        self._entries.pop(index)
        self._references.pop(id(entry), None)
        self._fields = {}
        self._current_index = None
        self._mark_dirty()
        self._populate_list(min(index, len(self._entries) - 1) if self._entries else None)
