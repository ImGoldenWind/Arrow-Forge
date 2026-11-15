"""Validated, adaptive command inspector using Arrow Forge field shells."""
import struct

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QGridLayout, QLineEdit, QComboBox

from core.design_tokens import LayoutRole, Size
from core.stage_tools import float32_text, numeric_value
from core.stagemotion_tools import command_operands, command_bytes, apply_command_bytes
from core.style_helpers import make_editor_field_shell, ss_input_validation
from core.translations import ui_text
from core.ui.editor_widgets import configure_layout, configure_input, configure_field
from core.ui.number_input import IntegerStepper


class MotionFieldError(ValueError):
    def __init__(self, widget, message):
        super().__init__(message)
        self.widget = widget


def text_of(widget):
    return widget.currentText() if isinstance(widget, QComboBox) else widget.text()


class MotionForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = configure_layout(QGridLayout(self), LayoutRole.GRID)
        self._fields = {}
        self._shells = []
        self._initial = {}
        self._readers = {}
        self._columns = 0

    def add(self, key, label, value, hint='', choices=None, reader=None, integer_range=None):
        shell, layout, _, _ = make_editor_field_shell(label)
        if choices is None:
            edit = QLineEdit(str(value))
        else:
            edit = QComboBox()
            edit.setEditable(True)
            edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            edit.addItems(list(dict.fromkeys([str(value), *map(str, choices)])))
            edit.setCurrentText(str(value))
            edit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            edit.setMinimumContentsLength(1)
        configure_input(edit)
        configure_field(shell, edit)
        edit.setObjectName('motion_' + str(key))
        edit.setProperty('messageReference', False)
        edit.setToolTip(hint)
        layout.addWidget(IntegerStepper(edit, *integer_range) if integer_range is not None else edit)
        self._shells.append(shell)
        self._fields[key] = edit
        self._initial[key] = str(value)
        self._readers[key] = reader
        self._columns = 0
        self.reflow()
        return edit

    def reflow(self):
        columns = 1 if self.width() < Size.COMPACT_BREAKPOINT else 2
        if columns == self._columns:
            return
        self._columns = columns
        for shell in self._shells:
            self.grid.removeWidget(shell)
        for col in range(2):
            self.grid.setColumnStretch(col, int(col < columns))
        for index, shell in enumerate(self._shells):
            self.grid.addWidget(shell, index // columns, index % columns)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def collect(self):
        result = {}
        for key, widget in self._fields.items():
            value = text_of(widget)
            try:
                result[key] = (self._readers[key](value) if self._readers[key] and
                               (value != self._initial[key] or self._readers[key] is not name_value)
                               else value)
            except (ValueError, UnicodeError, OverflowError, struct.error):
                widget.setStyleSheet(ss_input_validation(True))
                raise MotionFieldError(widget, ui_text('motion_invalid_field')) from None
            widget.setStyleSheet(ss_input_validation(False))
        return result


def name_value(text):
    if '\0' in text or len(text.encode('ascii')) > 31:
        raise ValueError()
    return text


def uint_value(text):
    return numeric_value(text, False, hexadecimal=text.lower().startswith('0x'))


class CommandForm(MotionForm):
    def __init__(self, entry, stages, changed, parent=None, *, lookup=None):
        super().__init__(parent)
        self.entry = entry
        self.original_data = command_bytes(entry)
        self.specs = command_operands(entry['type_code'])
        self.add('frame', ui_text('motion_frame'), entry['frame'], ui_text('motion_frame_hint'), reader=uint_value,
                 integer_range=(0, 0xFFFFFFFF))
        for spec in self.specs:
            value = spec.read(self.original_data)
            display = float32_text(value) if spec.kind == 'f' else str(value)
            if spec.label.startswith('motion_'):
                label = ui_text(spec.label)
            else:
                label = ui_text('skill_operand_' + spec.label)
            if spec.label == 'caption':
                label = ui_text('ui_messageinfo_string_id')
            choices = None
            if spec.kind == 'text':
                choices = sorted({e['name'] for s in stages for e in s['entries']
                                  if e['type_code'] == entry['type_code'] and e['name']})
            integer_range = ((-0x80000000, 0x7FFFFFFF) if spec.kind == 'i' else
                             (0, 0xFFFFFFFF) if spec.kind == 'I' else None)
            edit = self.add(spec.offset, label, display, ui_text('motion_operand_hint'), choices=choices,
                            integer_range=integer_range)
            if spec.label == 'caption':
                edit.setProperty('messageReference', True)
                edit.lineEdit().setProperty('messageReference', True)
                if lookup is not None:
                    from core.ui.message_preview import MessagePreview
                    self._shells[-1].layout().addWidget(MessagePreview(edit.lineEdit(), lookup))
            if spec.label in ('duration', 'start_frame', 'end_frame'):
                edit.setToolTip(ui_text('motion_' + spec.label + '_hint'))
            if spec.label == 'speed':
                edit.setToolTip(ui_text('motion_speed_hint'))
            if spec.label in ('motion_face_option', 'motion_bg_option'):
                edit.setToolTip(ui_text(spec.label + '_hint'))
        for widget in self._fields.values():
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(changed)
            else:
                widget.textChanged.connect(changed)

    def collect_entry(self):
        values = self.collect()
        data = bytearray(self.original_data)
        struct.pack_into('<I', data, 0x30, values['frame'])
        for spec in self.specs:
            value = values[spec.offset]
            if value == self._initial[spec.offset]:
                continue
            try:
                if spec.kind == 'text':
                    name_value(value)
                encoded = spec.encode(value)
                data[spec.offset:spec.offset + len(encoded)] = encoded
            except (ValueError, UnicodeError, struct.error, OverflowError):
                widget = self._fields[spec.offset]
                widget.setStyleSheet(ss_input_validation(True))
                raise MotionFieldError(widget, ui_text('motion_invalid_field')) from None
        candidate = dict(self.entry)
        apply_command_bytes(candidate, data)
        return candidate
