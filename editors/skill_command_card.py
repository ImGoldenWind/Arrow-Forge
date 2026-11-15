"""Contextual Char Skills controls; all byte-level edits use the existing parser."""
from core.design_tokens import (
    LayoutRole,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    ss_dim_label,
    ss_input_validation,
    ss_transparent,
)
from core.ui.editor_widgets import (
    configure_button,
    configure_input,
    configure_layout,
)
import math
import struct
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QPushButton, QComboBox, QLineEdit, QSlider)
from core.translations import ui_text
from core.skill_research import Operand, operands, display_value, RETURN_ONLY
from parsers.skill_parser import (MOT_SUB_SIZE, FUNC_MAP_1B, FUNC_MAP_2B,
    motion_subentry_size, write_mot_subentry, parse_motion_subentry, function_name,
    function_opcode)
from editors.skill_geometry import SkillBoxDiagram


def command_bytes(sub):
    size = motion_subentry_size(sub['dtype'])
    raw = bytearray(sub.get('raw_bytes', b'')[:size].ljust(size, b'\0'))
    write_mot_subentry(raw, {**sub, 'sub_off': 0})
    return raw


def make_command_card(tab, entry, index, sub):
    from editors.skill_editor import _make_field
    from core.style_helpers import make_editor_card
    card, layout = make_editor_card()
    opcode = sub['dtype'] & 0xFFFF
    add_editor_card_title(layout, ui_text('skill_command_title', n=index + 1))
    explanation = QLabel(ui_text('skill_cmd_' + f'{opcode:X}') if
                         ui_text('skill_cmd_' + f'{opcode:X}') != 'skill_cmd_' + f'{opcode:X}'
                         else ui_text('skill_command_generic'))
    explanation.setWordWrap(True)
    explanation.setFont(ui_font(TypeSize.BODY))
    explanation.setStyleSheet(ss_dim_label())
    layout.addWidget(explanation)
    top = configure_layout(QGridLayout(), LayoutRole.GRID)
    frame_shell, frame = _make_field(ui_text('skill_field_frame_num'), sub['frame_str'])
    frame.setObjectName('skill_frame')
    frame.setToolTip(ui_text('skill_frame_hint'))
    top.addWidget(frame_shell, 0, 0)
    function = QComboBox()
    function.setEditable(True)
    function.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    function.setMinimumWidth(0)
    function.setMinimumContentsLength(8)
    function.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    configure_input(function)
    function.addItems(sorted(set(FUNC_MAP_1B.values()) | set(FUNC_MAP_2B.values())))
    function.setCurrentText(sub['func_name'])
    function.setToolTip(ui_text('skill_command_picker_hint'))
    top.addWidget(function, 1, 0, 1, 2)
    layout.addLayout(top)
    actions = configure_layout(QGridLayout(), LayoutRole.GRID)
    definitions = [('ui_skill_insert_subentry_above', lambda: tab._insert_subentry(entry, index)),
                   ('ui_skill_duplicate_subentry_here', lambda: tab._duplicate_subentry(entry, index)),
                   ('skill_command_up', lambda: tab._move_command(entry, index, -1)),
                   ('skill_command_down', lambda: tab._move_command(entry, index, 1)),
                   ('ui_skill_delete_subentry_here', lambda: tab._delete_subentry(entry, index)),
                   ('skill_raw_parameters', lambda: tab._edit_raw_command(entry, sub))]
    for n, (key, callback) in enumerate(definitions):
        button = QPushButton(ui_text(key))
        button.setMinimumWidth(0)
        configure_button(button, danger=n == 4)
        button.clicked.connect(lambda _, call=callback: call() if flush_local() else None)
        if n in (2, 3):
            button.setEnabled(0 <= index + (-1 if n == 2 else 1) < len(entry['subentries']))
        actions.addWidget(button, n // 2, n % 2)
    layout.addLayout(actions)
    grid = configure_layout(QGridLayout(), LayoutRole.GRID)
    layout.addLayout(grid)
    raw = command_bytes(sub)
    damage = len(raw) > MOT_SUB_SIZE and sub.get('dmg_label', '').startswith('DAMAGE_ID')
    specs = operands(opcode, damage)
    flushers = []
    diagram = None
    fields = {}

    def invalid(widget, error=None):
        widget.setProperty('skill_invalid', bool(error))
        widget.setStyleSheet(ss_input_validation(error))
        if error:
            widget.setToolTip(ui_text('skill_operand_invalid'))

    def update_sub(updated):
        parsed = parse_motion_subentry(updated)
        parsed['sub_off'] = sub.get('sub_off')
        sub.update(parsed)
        tab._structural_dirty = True
        if diagram:
            diagram.update()
        tab.changed.emit()

    def add_operand(spec, n, target=grid):
        value = spec.read(raw)
        label_key = 'skill_operand_' + spec.label
        shell, edit = _make_field(ui_text(label_key), display_value(value))
        choices = spec.choices
        if spec.kind == 'text' and not choices:
            cache = getattr(tab, '_operand_suggestions', {})
            tab._operand_suggestions = cache
            key = (opcode, spec.offset)
            if key not in cache:
                values = set()
                for move in tab._entries:
                    for candidate in move.get('subentries', []):
                        if candidate['dtype'] & 0xFFFF == opcode:
                            data = candidate.get('raw_bytes', b'')
                            if len(data) >= spec.offset + 32:
                                name = spec.read(data)
                                if name:
                                    values.add(name)
                cache[key] = tuple((v, None) for v in sorted(values))
            choices = cache[key]
        if choices:
            shell.layout().removeWidget(edit)
            edit.deleteLater()
            edit = QComboBox()
            edit.setEditable(True)
            edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            edit.setMinimumWidth(0)
            edit.setMinimumContentsLength(3)
            edit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            configure_input(edit)
            edit.addItems([])
            for stored, key in choices:
                edit.addItem(ui_text('skill_choice_' + key) if key else str(stored), stored)
            match = next((j for j in range(edit.count()) if edit.itemData(j) == value), -1)
            if match >= 0:
                edit.setCurrentIndex(match)
            else:
                edit.setCurrentIndex(-1)
                edit.setEditText(display_value(value))
            shell.layout().addWidget(edit)
        edit.setObjectName('skill_operand_' + spec.label)
        edit.setProperty('skill_offset', spec.offset)
        edit.setToolTip(ui_text('skill_hint_' + spec.label) if
                        ui_text('skill_hint_' + spec.label) != 'skill_hint_' + spec.label
                        else ui_text('skill_operand_hint'))
        fields[spec.label] = edit
        baseline = [edit.currentText() if isinstance(edit, QComboBox) else edit.text()]

        def current():
            if isinstance(edit, QComboBox):
                j = edit.currentIndex()
                return edit.itemData(j) if j >= 0 and edit.currentText() == edit.itemText(j) else edit.currentText()
            return edit.text()

        def commit():
            entered = edit.currentText() if isinstance(edit, QComboBox) else edit.text()
            if entered == baseline[0]:
                return True
            try:
                encoded = spec.encode(current())
                updated = command_bytes(sub)
                # Rewriting a single operand cannot quantize unrelated floats.
                updated[spec.offset:spec.offset + len(encoded)] = encoded
                update_sub(updated)
                baseline[0] = entered
                invalid(edit)
                return True
            except (ValueError, OverflowError, UnicodeError, struct.error):
                invalid(edit, True)
                return False
        flushers.append(commit)
        if isinstance(edit, QComboBox):
            edit.currentIndexChanged.connect(lambda _: commit())
            edit.lineEdit().editingFinished.connect(commit)
        else:
            edit.editingFinished.connect(commit)
        target.addWidget(shell, n // 2, n % 2)
        if spec.slider:
            slider = QSlider(Qt.Orientation.Horizontal)
            low, high = spec.slider
            slider.setRange(round(low * 100), round(high * 100))
            slider.setValue(max(slider.minimum(), min(slider.maximum(), round(value * 100))) if math.isfinite(value) else 0)
            slider.setToolTip(ui_text('skill_slider_hint'))
            # Initialization and numeric edits never commit a slider's rounded value.
            slider.valueChanged.connect(lambda v: (edit.setText(format(v / 100, '.2f')), commit()))
            def sync_slider():
                try:
                    v = float(edit.text())
                    if math.isfinite(v):
                        slider.blockSignals(True)
                        slider.setValue(max(slider.minimum(), min(slider.maximum(), round(v * 100))))
                        slider.blockSignals(False)
                except ValueError:
                    pass
            edit.editingFinished.connect(sync_slider)
            shell.layout().addWidget(slider)
        return edit

    advanced_specs = tuple(spec for spec in specs if spec.label in ('hit_x', 'hit_y', 'push'))
    visible_specs = tuple(spec for spec in specs if spec not in advanced_specs)
    for n, spec in enumerate(visible_specs):
        add_operand(spec, n)
    if damage:
        attack = QComboBox()
        attack.setObjectName('skill_attack_type')
        configure_input(attack)
        for stored in ('', 'high', 'middle', 'low', 'unblockable'):
            attack.addItem(ui_text('skill_attack_' + (stored or 'custom')), stored)
        attack.setCurrentIndex(max(0, attack.findData(sub.get('attack', ''))))
        attack.setToolTip(ui_text('skill_attack_hint'))
        attack_label = QLabel(ui_text('ui_skill_attack'))
        attack_label.setStyleSheet(ss_dim_label())
        layout.addWidget(attack_label)
        layout.addWidget(attack)
        def commit_attack():
            selected = attack.currentData()
            if selected and selected != sub.get('attack', ''):
                pending = {**sub, 'attack': selected}
                update_sub(command_bytes(pending))
            return True
        attack.currentIndexChanged.connect(lambda _: commit_attack())
        flushers.append(commit_attack)
    if opcode in (0x20, 0x22, 0x24, 0x26, 0x28, 0x5D):
        def box_values():
            data = command_bytes(sub)
            x, z, y = struct.unpack_from('<iii', data, 0x38)
            if opcode == 0x5D and y <= 0:
                y = x
            return x, z, y
        diagram = SkillBoxDiagram(box_values)
        layout.addWidget(diagram)
    if not specs:
        function.setToolTip(ui_text('skill_return_only') if opcode in RETURN_ONLY else ui_text('skill_no_named_operands'))

    more = QWidget()
    more.setStyleSheet(ss_transparent())
    details = QGridLayout(more)
    configure_layout(details, LayoutRole.GRID)
    type_shell, type_edit = _make_field(ui_text('skill_opcode'), sub['dtype'])
    details.addWidget(type_shell, 0, 0)
    type_edit.setObjectName('skill_opcode')
    if not any(spec.offset == 8 for spec in specs):
        add_operand(Operand(8, 'text', 'command_name'), 1, details)
    if len(raw) > MOT_SUB_SIZE:
        add_operand(Operand(MOT_SUB_SIZE + 0x18, 'text', 'descriptor'), 2, details)
    for n, spec in enumerate(advanced_specs, 4):
        add_operand(spec, n, details)
    layout.addWidget(more)

    frame_baseline = [frame.text()]
    def commit_frame():
        if frame.text() == frame_baseline[0]:
            return True
        try:
            text = frame.text().strip()
            value = 9998 if text in ('Start', ui_text('ui_skill_start')) else 9999 if text in ('End', ui_text('ui_skill_end')) else int(text)
            if not 0 <= value <= 65535:
                raise ValueError()
            updated = command_bytes(sub)
            struct.pack_into('<H', updated, 0x30, value)
            update_sub(updated)
            frame_baseline[0] = frame.text()
            invalid(frame)
            return True
        except (ValueError, struct.error):
            invalid(frame, True)
            return False
    frame.editingFinished.connect(commit_frame)
    flushers.append(commit_frame)

    def flush_local():
        # Evaluate every field, so each invalid input gets marked.
        return all([commit() for commit in flushers])
    tab._command_flushers.append(flush_local)
    type_baseline = [type_edit.text()]
    def change_function(numeric=False):
        if numeric and type_edit.text() == type_baseline[0]:
            return
        try:
            code = int(type_edit.text(), 0) if numeric else function_opcode(function.currentText())
            if not 0 <= code <= 0xFFFFFFFF:
                raise ValueError()
            if code == sub['dtype']:
                return
            if not flush_local():
                return
            name = function_name(code)
            old = command_bytes(sub)
            template = tab._subentry_templates.get(name)
            updated = bytearray((template if template is not None else old)[:motion_subentry_size(code)].ljust(motion_subentry_size(code), b'\0'))
            struct.pack_into('<I', updated, 0x34, code)
            updated[0x30:0x32] = old[0x30:0x32]
            update_sub(updated)
            invalid(type_edit)
            invalid(function)
            type_baseline[0] = str(code)
            type_edit.setText(str(code))
            function.blockSignals(True)
            function.setCurrentText(name)
            function.blockSignals(False)
            QTimer.singleShot(0, lambda: tab._show_entry(entry) if tab._cur_entry is entry else None)
        except (ValueError, KeyError, struct.error):
            invalid(type_edit if numeric else function, True)
    type_edit.editingFinished.connect(lambda: change_function(True))
    function.currentTextChanged.connect(lambda _: change_function())
    # Numeric opcode input is normally hidden; still flush it before Save.
    def flush_type():
        if type_edit.text() != type_baseline[0]:
            change_function(True)
        return not type_edit.property('skill_invalid') and not function.property('skill_invalid')
    tab._command_flushers.append(flush_type)
    return card
