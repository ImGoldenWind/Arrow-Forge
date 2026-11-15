"""Themed Stage Info forms, preserving pending text during layout changes."""
import copy
import struct

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QColorDialog, QComboBox, QFileDialog, QMessageBox, QSizePolicy, QLabel, QStackedWidget,
)

from core.design_tokens import LayoutRole, Size
from core.style_helpers import (
    make_editor_card, make_editor_grid_card, make_editor_field_shell,
    add_editor_card_title, ss_bg_dark, ss_input_validation,
)
from core.ui.editor_widgets import (
    configure_layout, configure_input, configure_button, configure_field,
    configure_scrollarea, EditorActionRow,
)
from core.stage_tools import (
    COLOR_OFFSETS, COLOR_LABELS, SCALAR_FIELDS, parameter_hint, ascii_text, numeric_value,
    packed_color_rgba, rgba_packed_color, game_path, resolve_resource,
    resource_clumps, new_clump, float32_text,
)
from core.translations import ui_text
from core.settings import game_files_dialog_dir
from editors.stageinfo_preview import ScalarBar, VectorPreview
from editors.stageinfo_scene import StageMapPreview


class StageFieldError(ValueError):
    def __init__(self, field, key):
        super().__init__(ui_text(key))
        self.field = field
        field.setStyleSheet(ss_input_validation(True))


def _text(field):
    return field.currentText() if isinstance(field, QComboBox) else field.text()


def _read(field, reader, *args, **kwargs):
    try:
        value = reader(_text(field), *args, **kwargs)
    except ValueError as error:
        raise StageFieldError(field, str(error)) from None
    field.setStyleSheet(ss_input_validation(False))
    return value


def _hex(text, size):
    try:
        value = bytes.fromhex(text)
        if len(value) != size:
            raise ValueError()
        return value
    except ValueError:
        raise ValueError('stage_invalid_hex') from None


def _field(label, text='', *, combo=False, hint=''):
    frame, layout, _, _ = make_editor_field_shell(label, hint)
    edit = QComboBox() if combo else QLineEdit(str(text))
    if combo:
        edit.setEditable(True)
        edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        edit.setEditText(str(text))
    configure_input(edit, monospace=True)
    configure_field(frame, edit, vertical_policy=QSizePolicy.Policy.Preferred)
    layout.addWidget(edit)
    edit.setProperty('messageReference', False)
    return frame, edit


def _button(text, slot, *, danger=False):
    button = configure_button(QPushButton(ui_text(text)), danger=danger,
                              height=Size.COMPACT_CONTROL)
    button.clicked.connect(slot)
    return button


class _FormTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage = None
        self._building = False
        self.source_path = None
        self._grids = []
        self._scroll = configure_scrollarea(QScrollArea())
        self._scroll.viewport().installEventFilter(self)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._inner = QWidget()
        self._inner.setStyleSheet(ss_bg_dark())
        self._root = configure_layout(QVBoxLayout(self._inner), LayoutRole.PAGE)
        self._scroll.setWidget(self._inner)
        outer = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        outer.addWidget(self._scroll)

    def _on_change(self, *args):
        if not self._building:
            self.changed.emit()

    def _watch(self, edit):
        signal = edit.currentTextChanged if isinstance(edit, QComboBox) else edit.textChanged
        signal.connect(self._on_change)

    def _reflow(self):
        available = self._scroll.viewport().width()
        for grid, fields, maximum in self._grids:
            columns = min(maximum, max(1, available // 310))
            for index, field in enumerate(fields):
                grid.addWidget(field, *divmod(index, columns))
            for col in range(maximum):
                grid.setColumnStretch(col, int(col < columns))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def eventFilter(self, watched, event):
        if watched is self._scroll.viewport() and event.type() == QEvent.Type.Resize:
            # The viewport settles after the tab/sidebar layout has resized.
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _error(self, error):
        error.field.setFocus()
        self._scroll.ensureWidgetVisible(error.field)
        QMessageBox.warning(self, ui_text('stage_invalid_title'), str(error))


class _GeneralTab(_FormTab):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._path_rows = []
        code_card, grid = make_editor_grid_card(title=ui_text('ui_stageinfo_code'), icon_name='fa6s.tag')
        frame, self._code_edit = _field(ui_text('ui_stageinfo_stage_code_max_23_chars'))
        self._watch(self._code_edit)
        grid.addWidget(frame, 0, 0)
        self._root.addWidget(code_card)
        self._paths_card, layout = make_editor_card()
        add_editor_card_title(layout, ui_text('ui_stageinfo_xfbin_paths_asset_files_this_stage_loads'),
                              'fa6s.folder-tree', ui_text('stage_paths_hint'))
        actions = EditorActionRow()
        actions.content_layout.addWidget(_button('ui_stageinfo_add_path', self._add_path))
        actions.content_layout.addWidget(_button('stage_browse_paths', self._browse_paths))
        actions.content_layout.addStretch()
        layout.addWidget(actions)
        self._paths_container = QWidget()
        self._paths_layout = configure_layout(QVBoxLayout(self._paths_container), LayoutRole.FIELD)
        layout.addWidget(self._paths_container)
        self._root.addWidget(self._paths_card)
        self._root.addStretch()

    def _make_path_row(self, text):
        row = QWidget()
        layout = configure_layout(QHBoxLayout(row), LayoutRole.FIELD)
        edit = configure_input(QLineEdit(text), monospace=True)
        edit.setMinimumWidth(0)
        edit.setPlaceholderText('data/stage/example.xfbin')
        edit.setProperty('messageReference', False)
        edit.setAccessibleName(ui_text('ui_effect_xfbin_path'))
        edit.setToolTip(text)
        edit.textChanged.connect(edit.setToolTip)
        self._watch(edit)
        layout.addWidget(edit, 1)
        remove = _button('btn_delete', lambda: self._del_path(row), danger=True)
        remove.setAccessibleName(ui_text('stage_remove_path'))
        remove.setToolTip(ui_text('stage_remove_path') + ': ' + text)
        edit.textChanged.connect(lambda value: remove.setToolTip(ui_text('stage_remove_path') + ': ' + value))
        layout.addWidget(remove)
        self._path_rows.append((row, edit))
        self._paths_layout.addWidget(row)
        return edit

    def _add_path(self):
        if self._stage is None:
            return
        edit = self._make_path_row('')
        edit.setFocus()
        self._scroll.ensureWidgetVisible(edit)
        self._on_change()

    def _del_path(self, row):
        match = next(((r, e) for r, e in self._path_rows if r is row), None)
        if not match:
            return
        value = match[1].text()
        if value and any(c['xfbin_path'] == value for c in self._stage['clumps']):
            if QMessageBox.question(self, ui_text('stage_remove_path'),
                    ui_text('stage_path_in_use', path=value),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        self._path_rows.remove(match)
        self._paths_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._on_change()

    def _browse_paths(self):
        paths, _ = QFileDialog.getOpenFileNames(self, ui_text('stage_browse_paths'),
            str(resolve_resource(self.current_paths()[0], self.source_path).parent)
            if self.current_paths() and resolve_resource(self.current_paths()[0], self.source_path)
            else game_files_dialog_dir(target_patterns='*.xfbin'),
            'XFBIN (*.xfbin)')
        try:
            values = [game_path(path, self.source_path) for path in paths]
        except ValueError as error:
            QMessageBox.warning(self, ui_text('stage_invalid_title'), ui_text(str(error)))
            return
        for value in dict.fromkeys(values):
            if value not in self.current_paths():
                self._make_path_row(value)
                self._on_change()

    def current_paths(self):
        return [edit.text() for _, edit in self._path_rows]

    def ensure_path(self, path):
        if path not in self.current_paths():
            self._make_path_row(path)
            self._on_change()

    def load_stage(self, stage):
        self._stage = stage
        self._building = True
        self._code_edit.setText(stage['code'])
        for row, _ in self._path_rows:
            self._paths_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._path_rows.clear()
        for value in stage['paths']:
            self._make_path_row(value)
        self._building = False

    def collect(self, stage):
        code = _read(self._code_edit, ascii_text, required=True)
        # Existing longer identifiers are supported by the variable-length writer.
        if code != self._stage['code'] and len(code) > 23:
            raise StageFieldError(self._code_edit, 'stage_code_too_long')
        paths = [_read(edit, ascii_text, required=True) for _, edit in self._path_rows]
        stage.update(code=code, paths=paths)


class _ColorWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = configure_layout(QHBoxLayout(self), LayoutRole.FIELD)
        self._preview = configure_button(QPushButton())
        self._preview.setFixedWidth(64)
        self._preview.setToolTip(ui_text('ui_stageinfo_pick_color'))
        self._preview.setAccessibleName(ui_text('ui_stageinfo_pick_color'))
        self._preview.clicked.connect(self._pick_color)
        layout.addWidget(self._preview)
        self._edit = configure_input(QLineEdit(), monospace=True)
        self._edit.setMinimumWidth(0)
        self._edit.setAccessibleName('RGBA')
        self._edit.setToolTip(ui_text('stage_rgba_hint'))
        self._edit.setProperty('messageReference', False)
        self._edit.textChanged.connect(self._on_change)
        layout.addWidget(self._edit, 1)

    def _on_change(self):
        from editors.stageinfo_editor import _color_preview_style
        try:
            rgba = _hex(self._edit.text().removeprefix('#'), 4)
            self._preview.setStyleSheet(_color_preview_style(rgba))
        except ValueError:
            self._preview.setStyleSheet(_color_preview_style(invalid=True))
        self.changed.emit()

    def _pick_color(self):
        try:
            rgba = _hex(self._edit.text().removeprefix('#'), 4)
        except ValueError:
            rgba = (0, 0, 0, 255)
        color = QColorDialog.getColor(QColor(*rgba), self, ui_text('ui_stageinfo_pick_color'),
                                      QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            self._edit.setText(bytes((color.red(), color.green(), color.blue(), color.alpha())).hex().upper())

    def set_bytes(self, data):
        self._edit.setText(bytes(packed_color_rgba(data)).hex().upper())

    def get_bytes(self):
        return rgba_packed_color(_read(self._edit, lambda t: _hex(t.removeprefix('#'), 4)))


class _ParamsTab(_FormTab):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color_widgets = []
        self._scalar_widgets = {}
        self._bars = {}
        self._original_values = {}
        self._reserved_edits = {}
        self._loaded_text = {}
        card, grid = make_editor_grid_card(title=ui_text('stage_colours'), icon_name='fa6s.palette',
                                          subtitle=ui_text('stage_colour_hint'))
        frames = []
        for index, offset in enumerate(COLOR_OFFSETS):
            frame, layout, _, _ = make_editor_field_shell(ui_text(COLOR_LABELS[index]))
            cw = _ColorWidget()
            cw.changed.connect(self._on_change)
            cw.changed.connect(self._update_previews)
            cw._edit.setToolTip(ui_text('stage_colour_tip_' + str(index + 1)))
            layout.addWidget(cw)
            frames.append(frame)
            self._color_widgets.append((offset, cw))
        self._grids.append((grid, frames, 2))
        self._root.addWidget(card)
        card, grid = make_editor_grid_card(title=ui_text('ui_stageinfo_scalar_parameters'),
            icon_name='fa6s.sliders', subtitle=ui_text('stage_scalar_hint'))
        self._preview_mode = configure_input(QComboBox())
        self._preview_mode.addItem(ui_text('stage_preview_diagram'), 'diagram')
        self._preview_mode.addItem(ui_text('stage_preview_map'), 'map')
        self._preview_mode.setAccessibleName(ui_text('stage_preview_mode'))
        card.layout().insertWidget(1, self._preview_mode)
        self._preview_stack = QStackedWidget()
        self._vector = VectorPreview()
        self._preview_stack.addWidget(self._vector)
        self._map_preview = StageMapPreview()
        self._preview_stack.addWidget(self._map_preview)
        self._preview_stack.setFixedHeight(self._vector.height())
        card.layout().insertWidget(2, self._preview_stack)
        self._preview_mode.currentIndexChanged.connect(self._change_preview_mode)
        frames = []
        for offset, key, is_float in SCALAR_FIELDS:
            frame, edit = _field(ui_text(key))
            edit.setToolTip(ui_text(parameter_hint(offset)))
            self._watch(edit)
            edit.textChanged.connect(self._update_previews)
            bar = ScalarBar()
            frame.layout().addWidget(bar)
            self._scalar_widgets[offset] = (edit, is_float)
            self._bars[offset] = bar
            frames.append(frame)
        self._grids.append((grid, frames, 3))
        self._root.addWidget(card)
        self._root.addStretch()
        self._reflow()

    def _change_preview_mode(self):
        is_map = self._preview_mode.currentData() == 'map'
        self._preview_stack.setCurrentIndex(int(is_map))
        self._preview_stack.setFixedHeight(520 if is_map else self._vector.height())
        self._map_preview.set_active(is_map)
        if is_map:
            QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(self._preview_stack))

    def _update_previews(self):
        values = {}
        for offset, (edit, is_float) in self._scalar_widgets.items():
            try:
                value = numeric_value(edit.text(), is_float)
            except ValueError:
                value = None
            values[offset] = value
            self._bars[offset].set_values(value, self._original_values.get(offset, 0))
        self._vector.set_values(tuple(values.get(off) for off in (24, 28, 32)))
        if self._stage is not None and not self._building:
            try:
                pending = copy.deepcopy(self._stage)
                self.collect(pending)
            except StageFieldError:
                return  # Incomplete input retains the last valid preview.
            self._map_preview.set_parameters(pending['params'])

    def load_stage(self, stage):
        self._stage = stage
        self._building = True
        params = stage['params']
        self._original_values.clear()
        for offset, cw in self._color_widgets:
            cw.set_bytes(params[offset:offset + 4])
        for offset, (edit, is_float) in self._scalar_widgets.items():
            value = struct.unpack_from('<f' if is_float else '<I', params, offset)[0]
            self._original_values[offset] = value
            edit.setText(float32_text(value) if is_float else str(value))
            self._loaded_text[offset] = edit.text()
        for offset, (edit, size) in self._reserved_edits.items():
            edit.setText(bytes(params[offset:offset + size]).hex().upper())
        self._building = False
        self._update_previews()
        self._map_preview.set_context(stage, self.source_path)
        self._reflow()

    def collect(self, stage):
        params = bytearray(stage['params'])
        for offset, cw in self._color_widgets:
            params[offset:offset + 4] = cw.get_bytes()
        for offset, (edit, is_float) in self._scalar_widgets.items():
            if edit.text() == self._loaded_text[offset]:
                continue  # Preserve even non-finite original bit patterns.
            value = _read(edit, numeric_value, is_float)
            struct.pack_into('<f' if is_float else '<I', params, offset, value)
        for offset, (edit, size) in self._reserved_edits.items():
            params[offset:offset + size] = _read(edit, _hex, size)
        stage['params'] = params


class _ClumpsTab(_FormTab):
    path_added = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = []
        self._catalog_cache = {}
        self._suggested_path = None
        card, grid = make_editor_grid_card(title=ui_text('stage_add_clump'), icon_name='fa6s.cubes',
                                          subtitle=ui_text('stage_add_clump_hint'))
        path_frame, self._draft_path = _field(ui_text('ui_effect_xfbin_path'), combo=True)
        name_frame, self._draft_name = _field(ui_text('ui_stageinfo_clump_name'), combo=True)
        self._grids.append((grid, [path_frame, name_frame], 2))
        self._draft_path.currentTextChanged.connect(self._suggest_names)
        actions = EditorActionRow()
        actions.content_layout.addWidget(_button('stage_browse_clump', self._browse_clump))
        self._btn_add = _button('stage_add_clump', self._add_clump)
        actions.content_layout.addWidget(self._btn_add)
        actions.content_layout.addStretch()
        card.layout().addWidget(actions)
        self._root.addWidget(card)
        self._cards_container = QWidget()
        self._cards_layout = configure_layout(QVBoxLayout(self._cards_container), LayoutRole.LIST)
        self._root.addWidget(self._cards_container)
        self._root.addStretch()

    def refresh_choices(self, paths):
        text = self._draft_path.currentText()
        self._draft_path.blockSignals(True)
        self._draft_path.clear()
        self._draft_path.addItems(list(dict.fromkeys(p for p in paths if p)))
        if text:
            self._draft_path.setEditText(text)
        self._draft_path.blockSignals(False)
        self._suggest_names()

    def _suggest_names(self, *args):
        value = self._draft_path.currentText()
        resource = resolve_resource(value, self.source_path)
        names = []
        hint = ui_text('stage_custom_clump_hint')
        if resource:
            try:
                stat = resource.stat()
                key = (str(resource), stat.st_mtime_ns, stat.st_size)
                if key not in self._catalog_cache:
                    self._catalog_cache[key] = resource_clumps(resource)
                names = self._catalog_cache[key]
                hint = ui_text('stage_clumps_from_file' if names else 'stage_no_clumps')
            except (OSError, ValueError, IndexError, struct.error, UnicodeError):
                hint = ui_text('stage_clump_read_error')
        if resource is None and self._stage:
            names = list(dict.fromkeys(c['clump_name'] for c in self._stage['clumps']
                         if c['xfbin_path'] == value))
            if names:
                hint = ui_text('stage_clumps_from_stage')
        current = self._draft_name.currentText() if value == self._suggested_path else ''
        self._suggested_path = value
        self._draft_name.clear()
        self._draft_name.addItems(names)
        if current:
            self._draft_name.setEditText(current)
        self._draft_name.setToolTip(hint)

    def _browse_clump(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('stage_browse_clump'),
            game_files_dialog_dir(target_patterns='*.xfbin'), 'XFBIN (*.xfbin)')
        if not path:
            return
        try:
            value = game_path(path, self.source_path)
        except ValueError as error:
            QMessageBox.warning(self, ui_text('stage_invalid_title'), ui_text(str(error)))
            return
        self._draft_name.clearEditText()
        self._draft_path.setEditText(value)
        self._suggest_names()

    def load_stage(self, stage):
        self._stage = stage
        self._building = True
        for card, _, _, _, _ in self._cards:
            self._cards_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards.clear()
        self._grids = self._grids[:1]
        self._draft_path.clear()
        self._draft_name.clear()
        self._suggested_path = None
        self.refresh_choices(stage['paths'])
        for clump in stage['clumps']:
            self._append_card(clump)
        self._building = False
        self._reflow()

    def _append_card(self, clump):
        card, grid = make_editor_grid_card(title=clump['clump_name'] or ui_text('stage_unnamed_clump'),
                                          icon_name='fa6s.cube')
        title = next(label for label in card.findChildren(QLabel) if label.text())
        fields, frames, original = {}, [], {}
        values = (
            ('xfbin_path', ui_text('ui_effect_xfbin_path'), clump['xfbin_path']),
            ('clump_name', ui_text('ui_stageinfo_clump_name'), clump['clump_name']),
            ('unk_name', ui_text('stage_unknown_name', index=1), clump['unk_name']),
            ('unk2_name', ui_text('stage_unknown_name', index=2), clump['unk2_name']),
            ('flag', ui_text('stage_clump_parameter', index=1), str(struct.unpack_from('<I', clump['skip_data'])[0])),
            ('float', ui_text('stage_clump_parameter', index=2), float32_text(struct.unpack_from('<f', clump['skip_data'], 4)[0])),
            ('val1', ui_text('stage_clump_hex_parameter', index=3), f"{clump['val1']:X}"),
            ('val2', ui_text('stage_clump_hex_parameter', index=4), f"{clump['val2']:X}"),
        )
        for key, label, value in values:
            frame, edit = _field(label, value, combo=key == 'xfbin_path')
            if key == 'xfbin_path':
                edit.addItems(list(dict.fromkeys(self._stage['paths'])))
                edit.setEditText(value)
            elif key == 'clump_name':
                edit.textChanged.connect(lambda text: title.setText(text or ui_text('stage_unnamed_clump')))
            self._watch(edit)
            if key not in ('xfbin_path', 'clump_name'):
                edit.setToolTip(ui_text('stage_clump_unknown_hint'))
            fields[key], original[key] = edit, str(value)
            frames.append(frame)
        actions = EditorActionRow()
        actions.content_layout.addStretch()
        actions.content_layout.addWidget(_button('btn_duplicate', lambda: self._dup_clump(clump)))
        actions.content_layout.addWidget(_button('btn_delete', lambda: self._del_clump(clump), danger=True))
        card.layout().addWidget(actions)
        self._grids.append((grid, frames, 2))
        self._cards.append((card, clump, fields, original, grid))
        self._cards_layout.addWidget(card)
        self._reflow()
        return card

    def collect(self, stage):
        clumps = []
        for _, clump, fields, original, _ in self._cards:
            pending = copy.deepcopy(clump)
            for key in ('xfbin_path', 'clump_name', 'unk_name', 'unk2_name'):
                pending[key] = _read(fields[key], ascii_text, required=key in ('xfbin_path', 'clump_name'))
            skip = bytearray(clump['skip_data'])
            for key, offset, is_float in (('flag', 0, False), ('float', 4, True)):
                if fields[key].text() != original[key]:
                    value = _read(fields[key], numeric_value, is_float)
                    struct.pack_into('<f' if is_float else '<I', skip, offset, value)
            pending['skip_data'] = bytes(skip)
            for key in ('val1', 'val2'):
                pending[key] = _read(fields[key], numeric_value, False, hexadecimal=True)
            clumps.append(pending)
        # Keep identity stable: card actions refer to the corresponding dictionary.
        stage['clumps'] = clumps

    def _commit(self):
        try:
            pending = dict(self._stage)
            self.collect(pending)
        except StageFieldError as error:
            self._error(error)
            return False
        for (_, clump, _, _, _), updated in zip(self._cards, pending['clumps']):
            clump.update(updated)
        return True

    def _add_clump(self):
        if self._stage is None:
            return
        try:
            path = _read(self._draft_path, ascii_text, required=True)
            name = _read(self._draft_name, ascii_text, required=True)
        except StageFieldError as error:
            self._error(error)
            return
        if not self._commit():
            return
        clump = new_clump(path, name)
        self._stage['clumps'].append(clump)
        card = self._append_card(clump)
        self.path_added.emit(path)
        self.changed.emit()
        QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(card))

    def _dup_clump(self, clump):
        if not self._commit():
            return
        new = copy.deepcopy(clump)
        self._stage['clumps'].append(new)
        card = self._append_card(new)
        self.changed.emit()
        QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(card))

    def _del_clump(self, clump):
        item = next((item for item in self._cards if item[1] is clump), None)
        if item is None:
            return
        name = item[2]['clump_name'].text()
        if QMessageBox.question(self, ui_text('btn_delete'), ui_text('stage_delete_clump', name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = next(i for i, value in enumerate(self._stage['clumps']) if value is clump)
        del self._stage['clumps'][index]
        self._cards.remove(item)
        self._grids = [g for g in self._grids if g[0] is not item[4]]
        self._cards_layout.removeWidget(item[0])
        item[0].hide()
        item[0].deleteLater()
        self.changed.emit()
