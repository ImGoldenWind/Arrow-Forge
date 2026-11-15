"""Focused, custom-value-preserving projectile XML forms."""

from core.design_tokens import (
    LayoutRole,
    Size,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    ss_dim_label,
    ss_field_label,
    ss_input_validation,
    ss_tab_widget,
    ss_transparent,
)
from core.ui.editor_widgets import (
    configure_button,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_textedit,
)
import copy
import re
import xml.etree.ElementTree as ET

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QVBoxLayout,
    QHBoxLayout, QGridLayout, QScrollArea, QFrame, QTabWidget, QPlainTextEdit,
    QMessageBox, QSizePolicy,
)

from core.translations import ui_text
from core.projectile_tools import (
    ACTION_TYPES, EVENT_TYPES, EVENT_COMMANDS, parse_skill, skill_xml,
    actions, next_action_id, sync_counts, finite_number, skill_issues,
)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class _SkillTable(QWidget):
    xml_changed = pyqtSignal(str)
    skill_id_changed = pyqtSignal(str)
    validity_changed = pyqtSignal(bool)

    def __init__(self, parent=None, lang_func=None):
        super().__init__(parent)
        self._root_el = None
        self._texts = {}
        self._selected = None
        self._blocked = False
        self._invalid = set()
        self._grids = []
        self._cols = 0
        self._raw_pending = False
        self.id_validator = lambda value: True
        self._build_ui()

    @property
    def has_invalid(self):
        return bool(self._invalid) or self._raw_pending

    def _label(self, key):
        return self._text('proj_' + key)

    def _text(self, key):
        if key not in self._texts:
            self._texts[key] = ui_text(key)
        return self._texts[key]

    def _button(self, key, callback, danger=False):
        button = QPushButton(self._label(key))
        configure_button(button, danger=danger, height=Size.COMPACT_CONTROL)
        button.clicked.connect(callback)
        return button

    def _build_ui(self):
        layout = QVBoxLayout(self)
        configure_layout(layout, LayoutRole.PAGE)
        self._title = QLabel(self._label('intro'))
        self._title.setStyleSheet(ss_dim_label())
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        header, body = make_editor_card(self)
        self._id_fld = self._line(header, 'id', '', lambda v: self._header('id', v), 'skill_id')
        self._det_fld = self._line(header, 'description', '', lambda v: self._header('text', v))
        body.addWidget(self._id_fld.parentWidget())
        body.addWidget(self._det_fld.parentWidget())
        row = QHBoxLayout()
        first_label = QLabel(self._label('first'))
        first_label.setStyleSheet(ss_field_label())
        row.addWidget(first_label)
        self._first = QComboBox()
        configure_input(self._first)
        self._first.currentIndexChanged.connect(self._first_changed)
        row.addWidget(self._first, 1)
        body.addLayout(row)
        layout.addWidget(header)

        row = QHBoxLayout()
        self._action_picker = QComboBox()
        self._action_picker.setMinimumWidth(0)
        self._action_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        configure_input(self._action_picker)
        self._action_picker.currentIndexChanged.connect(self._select_action)
        row.addWidget(self._action_picker, 1)
        self._add_btn = self._button('add_action', self._add_action)
        self._dup_btn = self._button('duplicate', self._duplicate_selected)
        self._del_btn = self._button('delete', self._delete_selected, True)
        for button in (self._add_btn, self._dup_btn, self._del_btn):
            row.addWidget(button)
        layout.addLayout(row)

        self._status = QLabel()
        self._status.setStyleSheet(ss_dim_label())
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(ss_tab_widget())
        self._tabs.setUsesScrollButtons(True)
        self._pages = []
        for key in ('movement', 'collision', 'damage', 'events', 'resources'):
            scroll = QScrollArea()


            configure_scrollarea(scroll, transparent=True)
            page = QWidget()
            page.setMinimumWidth(0)
            page.setStyleSheet(ss_transparent())
            body = QVBoxLayout(page)
            body.setContentsMargins(0, 8, 0, 0)
            scroll.setWidget(page)
            self._pages.append(body)
            self._tabs.addTab(scroll, self._label(key))
        raw_page = QWidget()
        raw_layout = QVBoxLayout(raw_page)
        hint = QLabel(self._label('xml_hint'))
        hint.setStyleSheet(ss_dim_label())
        hint.setWordWrap(True)
        raw_layout.addWidget(hint)
        self._xml = QPlainTextEdit()
        configure_textedit(self._xml, monospace=True)
        self._xml.textChanged.connect(self._raw_changed)
        raw_layout.addWidget(self._xml)
        row = QHBoxLayout()
        row.addWidget(self._button('apply_xml', self._apply_xml))
        row.addStretch()
        raw_layout.addLayout(row)
        self._tabs.addTab(raw_page, self._label('xml'))
        self._tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self._tabs, 1)

    def _line(self, parent, key, value, update, kind='text', path=''):
        shell, body, _, _ = make_editor_field_shell(self._label(key))
        shell.setParent(parent)
        field = QLineEdit(str(value))
        field.setMinimumWidth(0)
        field.setMinimumHeight(30)
        configure_input(field, monospace=True)
        field.setPlaceholderText(self._label('unset'))
        hint = self._label(key + '_hint')
        if hint == 'proj_' + key + '_hint':
            hint = ''
        field.setToolTip('\n'.join(part for part in (hint, path) if part))
        field.setObjectName(path or key)
        body.addWidget(field)

        def changed(text):
            if self._blocked:
                return
            valid = (not text or finite_number(text)) if kind == 'number' else True
            if kind == 'integer':
                valid = not text or bool(re.fullmatch(r'-?[0-9]+', text))
            if kind == 'skill_id':
                valid = bool(re.fullmatch(r'[A-Za-z0-9_]{1,31}', text)) and self.id_validator(text)
            if kind in ('number', 'integer') and valid and text:
                valid = abs(float(text)) <= 3.4028234663852886e38
                if kind == 'integer':
                    valid = -2147483648 <= int(text) <= 2147483647
            if valid:
                try:
                    text.encode('shift_jis')
                except UnicodeError:
                    valid = False
            field.setProperty('projectile_invalid', not valid)
            field.setStyleSheet(ss_input_validation(not valid))
            if valid:
                self._invalid.discard(field)
                update(text)
            else:
                self._invalid.add(field)
            self._update_status()
        field.textChanged.connect(changed)
        return field

    def _choice(self, parent, key, value, options, update, path=''):
        shell, body, _, _ = make_editor_field_shell(self._label(key))
        shell.setParent(parent)
        field = QComboBox()
        field.setMinimumWidth(0)
        field.setMinimumHeight(30)
        configure_input(field)
        field.setObjectName(path)
        field.setToolTip(path)
        field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        field.setEditable(True)
        field.addItem(self._label('unset'), '')
        for text, data in options:
            field.addItem(text, data)
        idx = field.findData(value)
        if idx < 0:
            field.addItem(value, value)
            idx = field.count() - 1
        field.setCurrentIndex(idx)
        body.addWidget(field)

        def changed(text):
            if self._blocked:
                return
            idx = field.currentIndex()
            value = field.itemData(idx) if idx >= 0 and text == field.itemText(idx) else text
            field.setToolTip(path + '\n' + value)
            update(value)
        field.currentTextChanged.connect(changed)
        if path == 'Event/@command':
            field.activated.connect(lambda: QTimer.singleShot(0, self._refresh_event_controls))
        return field

    def _refresh_event_controls(self):
        if not self.has_invalid:
            self._rebuild_cards()

    def _action_caption(self, group, el):
        kind = el.get('type', '').removeprefix('SKILL_ACTION_TYPE_')
        names = {value: label for label, value in self._enum_options(ACTION_TYPES, '', 'action')}
        return ui_text('proj_action_row', id=el.get('id', '?'),
                       group=self._label('shared' if group.tag == 'GenActions' else 'normal'),
                       kind=names.get(kind, kind))

    def _enum_options(self, values, prefix, category):
        result = []
        for value in values:
            key = 'proj_' + category + '_' + value.lower()
            label = self._text(key)
            if label == key:
                label = value.replace('_', ' ').title()
            result.append((label, prefix + value))
        return result

    def _field(self, parent, owner, tag, attr, key, kind='text', options=None):
        child = owner if tag is None else owner.find(tag)
        value = child.get(attr, '') if child is not None else ''
        path = f'{owner.tag}/{tag + "/" if tag else ""}@{attr}'

        def update(text):
            node = owner if tag is None else owner.find(tag)
            if node is None and text:
                node = ET.SubElement(owner, tag)
            if node is not None:
                if text:
                    node.set(attr, text)
                else:
                    node.attrib.pop(attr, None)
                    if tag is not None and not node.attrib and not len(node):
                        owner.remove(node)
            self._emit_xml()
        if options is not None:
            return self._choice(parent, key, value, options, update, path)
        return self._line(parent, key, value, update, kind, path)

    def _card(self, page, title, hint=''):
        card, body = make_editor_card()
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        add_editor_card_title(body, title, 'fa6s.sliders', hint or None)
        page.addWidget(card)
        return card, body

    def _fields(self, page, title, specs, owner=None, hint=''):
        if self._tabs.currentIndex() >= len(self._pages) or page is not self._pages[self._tabs.currentIndex()]:
            return
        if owner is None:
            owner = self._selected
        card, body = self._card(page, self._label(title), hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(Size.CARD_GAP)
        shells = []
        for spec in specs:
            tag, attr, key, *rest = spec
            kind = rest[0] if rest else 'number'
            options = rest[1] if len(rest) > 1 else None
            field = self._field(card, owner, tag, attr, key, kind, options)
            shells.append(field.parentWidget())
        self._grids.append((grid, shells))
        body.addLayout(grid)

    def _reflow(self):
        cols = 1 if self._tabs.width() < 540 else (2 if self._tabs.width() < 940 else 3)
        for grid, shells in self._grids:
            while grid.count():
                grid.takeAt(0)
            for col in range(3):
                grid.setColumnStretch(col, int(col < cols))
            for i, shell in enumerate(shells):
                grid.addWidget(shell, i // cols, i % cols)
        self._cols = cols

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Move the existing controls: resizing must not destroy focus or edits.
        self._reflow()

    def load(self, text):
        self._blocked = True
        try:
            self._root_el = parse_skill(text)
            self._id_fld.setText(self._root_el.get('id', ''))
            details = self._root_el.find('Details')
            self._det_fld.setText(details.get('text', '') if details is not None else '')
            configure_input(self._id_fld)
            self._invalid.clear()
            self._raw_pending = False
            self._selected = None
        finally:
            self._blocked = False
        self._refresh_actions()
        self._reset_xml()

    def _header(self, attr, value):
        if self._root_el is None:
            return
        if attr == 'id':
            self._root_el.set('id', value)
            self.skill_id_changed.emit(value)
        else:
            details = self._root_el.find('Details')
            if details is None and value:
                details = ET.SubElement(self._root_el, 'Details')
            if details is not None:
                details.set('text', value)
        self._emit_xml()

    def _refresh_actions(self, selected=None):
        pairs = actions(self._root_el)
        self._action_picker.blockSignals(True)
        self._action_picker.clear()
        self._first.blockSignals(True)
        self._first.clear()
        for group, el in pairs:
            label = self._action_caption(group, el)
            self._action_picker.addItem(label, el)
            if group.tag == 'Actions':
                self._first.addItem(label, el.get('id'))
        first = self._root_el.find('Actions')
        value = first.get('FirstActionId', '') if first is not None else ''
        idx = self._first.findData(value)
        if idx < 0:
            self._first.addItem(value or self._label('unset'), value)
            idx = self._first.count() - 1
        self._first.setCurrentIndex(idx)
        self._first.blockSignals(False)
        idx = next((i for i, (_, el) in enumerate(pairs) if el is selected),
                   next((i for i, (_, el) in enumerate(pairs) if el.get('id') == value), 0))
        self._action_picker.setCurrentIndex(idx)
        self._action_picker.blockSignals(False)
        self._selected = pairs[idx][1] if pairs else None
        self._add_btn.setEnabled(next_action_id(self._root_el) is not None)
        self._add_btn.setToolTip(self._label('slots_hint'))
        self._dup_btn.setEnabled(self._selected is not None and next_action_id(self._root_el) is not None)
        self._del_btn.setEnabled(self._selected is not None)
        self._rebuild_cards()

    def _select_action(self, index):
        target = self._action_picker.itemData(index)
        if self.has_invalid:
            self._action_picker.blockSignals(True)
            for i in range(self._action_picker.count()):
                if self._action_picker.itemData(i) is self._selected:
                    self._action_picker.setCurrentIndex(i)
                    break
            self._action_picker.blockSignals(False)
            self._update_status()
            return
        self._selected = target
        self._rebuild_cards()

    def _first_changed(self, index):
        group = self._root_el.find('Actions') if self._root_el is not None else None
        if group is not None and index >= 0:
            group.set('FirstActionId', self._first.itemData(index))
            self._emit_xml()

    def _rebuild_cards(self):
        self._grids = []
        self._invalid = {w for w in self._invalid if w is self._id_fld}
        for page in self._pages:
            clear_layout(page)
        if self._selected is None:
            self._pages[0].addWidget(QLabel(self._label('empty_actions')))
            self._update_status()
            return
        motion, hit, damage, events, resources = self._pages
        enums = self._enum_options(ACTION_TYPES, 'SKILL_ACTION_TYPE_', 'action')
        self._fields(motion, 'movement', [(None, 'type', 'action_type', 'text', enums),
            ('Velocity', 'value', 'speed'), ('Gravity', 'value', 'gravity'),
            ('Friction', 'value', 'friction'), ('Restitution', 'value', 'restitution'),
            ('Animation', 'chunk', 'animation', 'text')])
        self._fields(hit, 'collision', [('Hit', 'Shape', 'shape', 'text',
             [(self._label('sphere'), 'sphere'), (self._label('box'), 'obb')]),
            ('Hit', 'hitRadius', 'radius'), ('Hit', 'hitRadiusWorld', 'radius_world'),
            ('Hit', 'hitRadiusSkill', 'radius_skill'), ('Hit', 'ObbHitRadX', 'box_x'),
            ('Hit', 'ObbHitRadY', 'box_y'), ('Hit', 'ObbHitRadZ', 'box_z'),
            ('Hit', 'HitOffsetX', 'offset_x'), ('Hit', 'HitOffsetY', 'offset_y'),
            ('Hit', 'HitOffsetZ', 'offset_z')], hint=self._label('shape_hint'))
        bools = [(self._label('yes'), 'true'), (self._label('no'), 'false')]
        self._fields(hit, 'hit_rules', [(tag, 'value', key, 'text', bools) for tag, key in (
            ('CharacterHitDisable', 'disable_character'), ('WorldHitDisable', 'disable_world'),
            ('SkillHitDisable', 'disable_skill'), ('NoDamage', 'no_damage'))])
        attacks = self._selected.findall('SkillAttack')
        if not attacks and self._tabs.currentIndex() == 2:
            damage.addWidget(QLabel(self._label('no_attack')))
        levels = [(self._label(v.lower()), v) for v in ('Low', 'Middle', 'High')]
        for attack in attacks:
            damage_ids = list(dict.fromkeys(el.get('dmgId') for el in self._root_el.iter('SkillAttack') if el.get('dmgId')))
            self._fields(damage, 'attack', [(None, attr, key, 'number') for attr, key in (
                ('Amount', 'damage_amount'), ('GuardDamage', 'guard_damage'), ('HHGauge', 'hh'),
                ('KnockBack', 'knockback'), ('ReacXY', 'reaction_xy'), ('ReacZ', 'reaction_z'))] + [
                (None, 'Place', 'place', 'text', levels), (None, 'Strength', 'strength', 'text', levels),
                (None, 'HitStop', 'hit_stop', 'integer'), (None, 'GuardStop', 'guard_stop', 'integer'),
                (None, 'dmgId', 'damage_id', 'text', [(ident.removeprefix('DAMAGE_ID_').replace('_', ' '), ident)
                                                    for ident in damage_ids])], owner=attack,
                hint=ui_text('proj_attack_hint', index=attack.get('Index', '0')))
        if not attacks and self._tabs.currentIndex() == 2:
            damage.addWidget(self._button('add_attack', self._add_attack))
        self._build_events(events)
        self._fields(resources, 'resources', [(None, 'type', 'skill_type', 'text')], owner=self._root_el)
        for file_el in self._root_el.findall('./Files/File'):
            self._fields(resources, 'resource_file', [(None, 'path', 'path', 'text')], owner=file_el)
        self._fields(resources, 'global_hit', [('Hit', 'priorityCategory', 'priority', 'text'),
            ('Hit', 'hitPoint', 'hit_points', 'integer'), ('Reflect', 'Enable', 'reflect', 'text', bools)],
            owner=self._root_el)
        for page in self._pages:
            page.addStretch()
        self._reflow()
        self._update_status()

    def _build_events(self, page):
        if self._tabs.currentIndex() != 3:
            return
        add = self._button('add_event', self._add_event)
        page.addWidget(add)
        if not self._selected.findall('Event'):
            page.addWidget(QLabel(self._label('empty_events')))
        for i, event in enumerate(self._selected.findall('Event')):
            targets = [(self._action_caption(group, el), el.get('id', ''))
                       for group, el in actions(self._root_el)]
            parameter = (None, 'commandParameter', 'target', 'text', targets) if event.get('command') == 'SKILL_EVENT_COMMAND_CHANGE_ACTION' else (
                None, 'commandParameter', 'target', 'number')
            self._fields(page, 'event', [(None, 'type', 'condition', 'text',
                self._enum_options(EVENT_TYPES, 'SKILL_EVENT_TYPE_', 'event')),
                (None, 'command', 'command', 'text', self._enum_options(EVENT_COMMANDS, 'SKILL_EVENT_COMMAND_', 'command')),
                parameter,
                (None, 'arg', 'argument', 'number'),
                (None, 'DisableAttackHit', 'disable_hit', 'text', [(self._label('yes'), 'true'), (self._label('no'), 'false')]),
                (None, 'EnableAttackHit', 'enable_hit', 'text', [(self._label('yes'), 'true'), (self._label('no'), 'false')])],
                owner=event, hint=self._label('event_hint'))
            page.addWidget(self._button('delete_event', lambda checked=False, el=event: self._delete_event(el), True))

    def _update_status(self):
        keys = ['proj_invalid'] if self._invalid else (['proj_xml_pending'] if self._raw_pending else [])
        if self._root_el is not None:
            keys += skill_issues(self._root_el)
        self._status.setText('  '.join(ui_text(key) for key in keys))
        self._status.setVisible(bool(keys))
        self.validity_changed.emit(not self.has_invalid)

    def _emit_xml(self):
        if self._blocked or self._root_el is None:
            return
        self.xml_changed.emit(skill_xml(self._root_el))
        for index, (group, el) in enumerate(actions(self._root_el)):
            self._action_picker.setItemText(index, self._action_caption(group, el))
            first_index = self._first.findData(el.get('id'))
            if first_index >= 0:
                self._first.setItemText(first_index, self._action_caption(group, el))
        self._update_status()

    def _reset_xml(self):
        self._xml.blockSignals(True)
        self._xml.setPlainText(skill_xml(self._root_el) if self._root_el is not None else '')
        self._xml.blockSignals(False)
        self._raw_pending = False
        self._lock_forms_for_xml()
        self._update_status()

    def _tab_changed(self, index):
        if index == self._tabs.count() - 1 and not self._raw_pending:
            self._reset_xml()
        elif index < len(self._pages) and self._selected is not None:
            if self._invalid:
                self._tabs.blockSignals(True)
                self._tabs.setCurrentIndex(getattr(self, '_last_tab', 0))
                self._tabs.blockSignals(False)
                return
            self._rebuild_cards()
        self._last_tab = index

    def _raw_changed(self):
        self._raw_pending = True
        self._lock_forms_for_xml()
        self._update_status()

    def _lock_forms_for_xml(self):
        for i in range(len(self._pages)):
            self._tabs.setTabEnabled(i, not self._raw_pending)
        self._id_fld.setEnabled(not self._raw_pending)
        self._det_fld.setEnabled(not self._raw_pending)
        self._first.setEnabled(not self._raw_pending)

    def _apply_xml(self):
        try:
            root = parse_skill(self._xml.toPlainText())
            skill_xml(root).encode('shift_jis')
        except (ValueError, ET.ParseError, UnicodeError) as exc:
            QMessageBox.warning(self, self._label('xml'), str(exc))
            return
        self.load(skill_xml(root))
        self.skill_id_changed.emit(root.get('id', ''))
        self._emit_xml()

    def _add_action(self):
        if self.has_invalid or self._root_el is None:
            return
        new_id = next_action_id(self._root_el)
        if new_id is None:
            return
        container = self._root_el.find('Actions')
        if container is None:
            container = ET.SubElement(self._root_el, 'Actions', FirstActionId=new_id, num='0')
        new = ET.SubElement(container, 'Action', id=new_id, type='SKILL_ACTION_TYPE_ARROW')
        sync_counts(self._root_el)
        if len(container.findall('Action')) == 1:
            container.set('FirstActionId', new_id)
        self._refresh_actions(new)
        self._emit_xml()

    def _duplicate_selected(self):
        self._dup_action_el(self._selected)

    def _dup_action_el(self, action):
        if self.has_invalid or action is None:
            return
        new_id = next_action_id(self._root_el)
        if new_id is None:
            return
        container = self._root_el.find('Actions')
        if container is None:
            container = ET.SubElement(self._root_el, 'Actions', FirstActionId=new_id)
        new = copy.deepcopy(action)
        new.set('id', new_id)
        # Self-transitions follow the duplicate; external transitions keep their target.
        for event in new.findall('Event'):
            if (event.get('command') == 'SKILL_EVENT_COMMAND_CHANGE_ACTION'
                    and event.get('commandParameter') == action.get('id')):
                event.set('commandParameter', new_id)
        container.append(new)
        if len(container.findall('Action')) == 1:
            container.set('FirstActionId', new_id)
        sync_counts(self._root_el)
        self._refresh_actions(new)
        self._emit_xml()

    def _delete_selected(self):
        self._del_action_el(self._selected)

    def _del_action_el(self, action):
        if self.has_invalid or action is None:
            return
        target = action.get('id')
        group = next(g for g, el in actions(self._root_el) if el is action)
        first = self._root_el.find('Actions')
        referenced = ((first is not None and first.get('FirstActionId') == target)
            or any(e.get('command') == 'SKILL_EVENT_COMMAND_CHANGE_ACTION'
                   and e.get('commandParameter') == target
                   for _, el in actions(self._root_el) if el is not action for e in el.findall('Event')))
        if referenced or group.tag == 'GenActions':
            QMessageBox.warning(self, self._label('delete'), self._label('referenced'))
            return
        if QMessageBox.question(self, self._label('delete'), self._label('delete_confirm')) != QMessageBox.StandardButton.Yes:
            return
        group.remove(action)
        sync_counts(self._root_el)
        self._refresh_actions()
        self._emit_xml()

    def _add_attack(self):
        if self.has_invalid:
            return
        ET.SubElement(self._selected, 'SkillAttack', Index='0', Amount='0', dmgId='DAMAGE_ID_SMALL_UC')
        self._rebuild_cards()
        self._emit_xml()

    def _add_event(self):
        if self.has_invalid:
            return
        ET.SubElement(self._selected, 'Event', type='SKILL_EVENT_TYPE_ANIMATION_END',
                      command='SKILL_EVENT_COMMAND_KILL', commandParameter='0')
        self._rebuild_cards()
        self._emit_xml()

    def _delete_event(self, event):
        if self.has_invalid:
            return
        self._selected.remove(event)
        self._rebuild_cards()
        self._emit_xml()
