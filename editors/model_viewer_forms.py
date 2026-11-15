"""Transactional, exact model inspection using Arrow Forge's common controls."""
import math
from PyQt6.QtCore import Qt, QSize, QEvent, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                            QScrollArea, QTabWidget, QTextEdit, QCheckBox,
                            QPushButton, QColorDialog, QComboBox)

from core.design_tokens import LayoutRole, Size
from core.style_helpers import (make_editor_card, add_editor_card_title, ss_dim_label,
                                ss_tab_widget, ss_check, ss_input_validation)
from core.ui.editor_widgets import (EditorSidebar, configure_layout, configure_input,
                                    configure_button, configure_scrollarea, configure_textedit)
from core.ui.editor_widgets import fit_scroll_page
from core.ui.number_input import FloatStepper, IntegerStepper, SliderInput
from core.ui.value_combo import EditorValueCombo
from core.ui.image_preview import ImagePreview
from core.model_viewer_tools import (float_value, integer_value, model_coordinates,
                                     assign_coordinate, material_meshes,
                                     PROPERTY_LABELS, BLEND_FACTORS)
from core.stage_tools import float32_text
from core.translations import ui_text
from parsers.model_xfbin_parser import (available_texture_refs, material_texture_refs,
                                      MissingTextureRef, set_material_texture)
from parsers.xfbin_lib import NuccChunkCoord, NuccChunkMaterial, NuccChunkModel, NuccChunkDynamics


class ModelInspector(EditorSidebar):
    value_changed = pyqtSignal()
    draft_changed = pyqtSignal()
    object_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = self._obj = None
        self._bindings = []
        self._building = False
        self._scroll_pages = []
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_page)
        self.set_panel_width(320)
        configure_layout(self.content_layout, LayoutRole.SIDEBAR_TABS)
        self._title = QLabel(ui_text('ui_model_viewer_inspector'))
        self._title.setWordWrap(True)
        self._title.setStyleSheet(ss_dim_label())
        self.content_layout.addWidget(self._title)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(ss_tab_widget())
        self._tabs.setUsesScrollButtons(True)
        self._tabs.currentChanged.connect(self._schedule_fit)
        self.content_layout.addWidget(self._tabs, 1)
        self.set_context(None, None)

    def set_panel_width(self, width):
        self.setFixedWidth(max(250, width))

    def set_context(self, doc, obj):
        self._building = True
        self._doc, self._obj = doc, obj
        self._bindings = []
        self._scroll_pages = []
        while self._tabs.count():
            page = self._tabs.widget(0)
            self._tabs.removeTab(0)
            page.deleteLater()
        self._title.setText(getattr(obj, 'name', '') or ui_text('ui_model_viewer_inspector'))
        coord = obj if isinstance(obj, NuccChunkCoord) else getattr(obj, 'coord_chunk', None)
        material = obj if isinstance(obj, NuccChunkMaterial) else getattr(obj, 'material_chunk', None)
        if coord is not None:
            self._transform(coord)
        if material is not None:
            self._material(material)
        if isinstance(obj, NuccChunkModel):
            self._model(obj)
        if isinstance(obj, NuccChunkDynamics):
            self._dynamics(obj)
        self._raw(obj)
        self._tabs.setCurrentIndex(0)
        self._building = False
        self._schedule_fit()

    def _schedule_fit(self, *_):
        self._fit_timer.start(0)

    def _fit_page(self):
        page = self._tabs.currentWidget()
        if isinstance(page, QScrollArea):
            fit_scroll_page(page)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self._schedule_fit()
        return super().eventFilter(watched, event)

    def _page(self, key):
        scroll = configure_scrollarea(QScrollArea(), transparent=True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = configure_layout(QVBoxLayout(inner), LayoutRole.FIELD)
        scroll.setWidget(inner)
        scroll.viewport().installEventFilter(self)
        self._scroll_pages.append(scroll)
        self._tabs.addTab(scroll, ui_text(key))
        return lay

    def _card(self, lay, title, hint=''):
        frame, body = make_editor_card()
        frame.setMinimumWidth(0)
        add_editor_card_title(body, title, 'fa6s.sliders', hint)
        lay.addWidget(frame)
        return body

    def _bind(self, edit, value, parser, setter):
        # Unchanged text is never parsed: preserve NaN payloads and all bits
        # outside a field being edited. A complete draft commits atomically.
        edit.setText(str(value))
        edit.setCursorPosition(0)
        binding = [edit, str(value), parser, setter]
        self._bindings.append(binding)
        edit.textChanged.connect(self._draft)
        return edit

    def commit(self, focus=True):
        changes = []
        invalid = []
        for edit, original, parser, setter in self._bindings:
            control = edit.parentWidget() if isinstance(edit.parentWidget(), QComboBox) else edit
            if edit.text() == original:
                if edit.property('modelInvalid'):
                    edit.setProperty('modelInvalid', False)
                    configure_input(control, height=Size.INSPECTOR_CONTROL, compact=True)
                continue
            try:
                value = parser(edit.text())
                changes.append((setter, value))
                bad = False
            except (ValueError, OverflowError, TypeError):
                bad = True
                invalid.append(edit)
            if bool(edit.property('modelInvalid')) != bad:
                edit.setProperty('modelInvalid', bad)
                configure_input(control, height=Size.INSPECTOR_CONTROL, compact=True)
                if bad:
                    control.setStyleSheet(ss_input_validation(True))
        if invalid:
            if focus:
                edit = invalid[0]
                for i in range(self._tabs.count()):
                    if self._tabs.widget(i).isAncestorOf(edit):
                        self._tabs.setCurrentIndex(i)
                        self._tabs.widget(i).ensureWidgetVisible(edit)
                        break
                edit.setFocus()
            return False
        for setter, value in changes:
            setter(value)
        for binding in self._bindings:
            binding[1] = binding[0].text()
        return True

    def _draft(self):
        if self._building:
            return
        self.draft_changed.emit()
        if self.commit(focus=False):
            self.value_changed.emit()

    def _number(self, lay, title, value, setter, *, integer=False, minimum=0, maximum=0xffffffff, hint=''):
        body = self._card(lay, title, hint)
        edit = configure_input(QLineEdit(), height=Size.INSPECTOR_CONTROL, compact=True)
        if integer:
            parser = lambda text: integer_value(text, minimum, maximum)
            self._bind(edit, str(value), parser, setter)
            control = IntegerStepper(edit, minimum, maximum)
        else:
            self._bind(edit, float32_text(value), float_value, setter)
            control = FloatStepper(edit, .1)
        edit.setAccessibleName(title)
        edit.setToolTip(hint or ui_text('model_exact_hint'))
        body.addWidget(control)
        return edit

    def _vector(self, lay, title, obj, attr, axes=('X', 'Y', 'Z'), hint=''):
        values = getattr(obj, attr)
        body = self._card(lay, title, hint)
        edits = []
        for index, value in enumerate(values):
            row = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
            label = QLabel(axes[index] if index < len(axes) else str(index))
            label.setStyleSheet(ss_dim_label())
            row.addWidget(label)
            edit = configure_input(QLineEdit(), height=Size.INSPECTOR_CONTROL, compact=True)
            self._bind(edit, float32_text(value), float_value,
                       lambda v, i=index: self._tuple_value(obj, attr, i, v))
            edit.setAccessibleName(title + ' ' + label.text())
            edit.setToolTip(hint or ui_text('model_exact_hint'))
            row.addWidget(FloatStepper(edit, .1), 1)
            body.addLayout(row)
            edits.append(edit)
        return body, edits

    @staticmethod
    def _tuple_value(obj, attr, index, value):
        values = list(getattr(obj, attr))
        values[index] = value
        setattr(obj, attr, tuple(values))

    def _transform(self, coord):
        lay = self._page('ui_model_viewer_transform')
        for attr, hint in (('position', 'model_position_hint'), ('rotation', 'model_rotation_hint'), ('scale', 'model_scale_hint')):
            self._vector(lay, ui_text('ui_model_viewer_' + attr), coord.node, attr, hint=ui_text(hint))
        self._number(lay, ui_text('ui_model_viewer_unk_float'), coord.node.unkFloat,
                     lambda v: setattr(coord.node, 'unkFloat', v))
        self._number(lay, ui_text('ui_model_viewer_unk_short'), coord.node.unkShort,
                     lambda v: setattr(coord.node, 'unkShort', v), integer=True, maximum=65535)
        lay.addStretch()

    def _combo(self, lay, title, choices, value, setter, *, maximum=65535, minimum=0):
        body = self._card(lay, title)
        combo = EditorValueCombo(choices, str(value))
        configure_input(combo, height=Size.INSPECTOR_CONTROL, compact=True)
        combo.setMinimumWidth(0)
        self._bindings.append([combo.lineEdit(), combo.currentText(),
                              lambda _: integer_value(combo.value_text(), minimum, maximum), setter])
        combo.currentTextChanged.connect(self._draft)
        body.addWidget(combo)
        return combo

    def _model(self, model):
        lay = self._page('ui_model_viewer_model')
        coords = model_coordinates(model, self._doc)
        self._combo(lay, ui_text('model_attached_bone'),
                    [(-1, ui_text('model_unbound'))] + [(i, f'{i}: {c.name}') for i, c in enumerate(coords)],
                    model.coord_index, lambda v: assign_coordinate(model, self._doc, v),
                    minimum=-1, maximum=len(coords)-1)
        # Only the shadow bit has a confirmed render consumer. Preserve every
        # other bit and retain an exact numeric editor for the complete byte.
        body = self._card(lay, ui_text('ui_model_viewer_rigging_flag'))
        shadow = QCheckBox(ui_text('model_casts_shadow'))
        shadow.setStyleSheet(ss_check())
        shadow.setChecked(bool(int(model.rigging_flag) & 0x20))
        body.addWidget(shadow)
        raw = self._number(lay, ui_text('model_rigging_bits'), int(model.rigging_flag),
                           lambda v: setattr(model, 'rigging_flag', type(model.rigging_flag)(v)), integer=True, maximum=65535)
        shadow.toggled.connect(lambda checked: raw.setText(str((int(model.rigging_flag) & ~0x20) | (0x20 if checked else 0))))
        raw.textChanged.connect(lambda _: shadow.setChecked(bool(int(model.rigging_flag) & 0x20)))
        for i, value in enumerate(model.material_flags):
            self._number(lay, f'{ui_text("ui_model_viewer_material_flag")} {i}', value,
                         lambda v, index=i: model.material_flags.__setitem__(index, v), integer=True, maximum=255)
        if model.flag1_floats:
            self._vector(lay, ui_text('ui_model_viewer_flag1_float'), model, 'flag1_floats')
        if model.nud:
            self._vector(lay, ui_text('ui_model_viewer_bounding_sphere'), model.nud, 'bounding_sphere', ('X', 'Y', 'Z', 'R'))
            for group in model.nud.mesh_groups:
                self._number(lay, ui_text('ui_model_viewer_bone_flags') + ' · ' + group.name, group.bone_flags,
                             lambda v, g=group: setattr(g, 'bone_flags', v), integer=True, maximum=65535)
            # Materials are explicit links, not a guessed model-level value.
            for material in dict.fromkeys(model.material_chunks):
                button = configure_button(QPushButton(material.name))
                button.clicked.connect(lambda _, m=material: self._show_material(m))
                lay.addWidget(button)
        lay.addStretch()

    def _show_material(self, material):
        if self.commit():
            self.object_requested.emit(material)

    def _material(self, material):
        lay = self._page('ui_model_viewer_material')
        body = self._card(lay, ui_text('model_alpha_cutoff'), ui_text('model_alpha_hint'))
        alpha = SliderInput('', 0, 255, material.field02)
        def alpha_changed(value):
            if not self._immediate(lambda: setattr(material, 'field02', value)):
                alpha.input.setValue(material.field02)
        alpha.value_changed.connect(alpha_changed)
        body.addWidget(alpha)
        self._number(lay, ui_text('model_glare'), material.field04, lambda v: setattr(material, 'field04', v), hint=ui_text('model_glare_hint'))
        for model, group, index, mesh in material_meshes(self._doc, material):
            for nud in mesh.materials:
                body = self._card(lay, model.name + ' · ' + str(index + 1), f'ASBR 0x{nud.flags:X}')
                label = QLabel(ui_text('model_native_material_hint'))
                label.setStyleSheet(ss_dim_label())
                label.setWordWrap(True)
                body.addWidget(label)
                self._combo(lay, ui_text('model_cull'), [(0, ui_text('model_cull_none')), (1028, ui_text('model_cull_front')), (1029, ui_text('model_cull_back'))], nud.cullMode, lambda v, n=nud: setattr(n, 'cullMode', v))
                choices = [(value, ui_text('model_blend_' + key)) for value, key in BLEND_FACTORS]
                for attr, key in (('sourceFactor', 'model_blend_source'), ('destFactor', 'model_blend_destination')):
                    self._combo(lay, ui_text(key), choices, getattr(nud, attr), lambda v, n=nud, a=attr: setattr(n, a, v))
                for prop in nud.properties:
                    if not prop.name:
                        continue
                    title = ui_text(PROPERTY_LABELS[prop.name]) if prop.name in PROPERTY_LABELS else prop.name
                    body, edits = self._vector(lay, title, prop, 'values', ('X', 'Y', 'Z', 'W'), hint=prop.name + '\n' + ui_text('model_exact_hint'))
                    if prop.name in ('NU_Kd0', 'NU_Ks') and len(prop.values) == 4:
                        button = configure_button(QPushButton(ui_text('model_choose_color')))
                        button.setEnabled(all(math.isfinite(v) and 0 <= v <= 1 for v in prop.values))
                        button.setToolTip(ui_text('model_color_hint'))
                        button.clicked.connect(lambda _, p=prop, e=edits: self._choose_color(p, e))
                        body.addWidget(button)
        textures = self._page('model_textures_tab')
        self._textures(textures, material)
        textures.addStretch()
        details = self._page('model_extra_parameters')
        self._number(details, ui_text('ui_model_viewer_format'), material.format, lambda v: setattr(material, 'format', v), integer=True, maximum=255)
        if material.floats:
            # Optional UV blocks are present in flag order. Show exact values
            # without reordering the remaining undecoded coefficients.
            offset = 0
            for channel, bit in enumerate((1, 2, 4, 8)):
                if material.format & bit:
                    body = self._card(details, ui_text('model_uv_transform', channel=channel), ui_text('model_uv_hint'))
                    for component, key in enumerate(('U', 'V', 'scale U', 'scale V')):
                        index = offset + component
                        if index >= len(material.floats):
                            break
                        row = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
                        row.addWidget(QLabel(key))
                        edit = configure_input(QLineEdit(), height=Size.INSPECTOR_CONTROL, compact=True)
                        self._bind(edit, float32_text(material.floats[index]), float_value,
                                   lambda v, i=index: self._tuple_value(material, 'floats', i, v))
                        row.addWidget(FloatStepper(edit, .1), 1)
                        body.addLayout(row)
                    offset += 4
            for index in range(offset, len(material.floats)):
                self._number(details, f'{ui_text("ui_model_viewer_material_float")} {index}', material.floats[index],
                             lambda v, i=index: self._tuple_value(material, 'floats', i, v))
        details.addStretch()
        lay.addStretch()

    def _choose_color(self, prop, edits):
        if not self.commit():
            return
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in prop.values):
            return  # HDR values remain exact manual inputs.
        initial = QColor.fromRgbF(*prop.values)
        color = QColorDialog.getColor(initial, self, ui_text('model_choose_color'), QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            self._building = True
            for edit, value, old in zip(edits, color.getRgbF(), initial.getRgbF()):
                if value != old:
                    edit.setText(float32_text(value))
            self._building = False
            self._draft()

    def _immediate(self, setter):
        if self.commit():
            setter()
            self.draft_changed.emit()
            self.value_changed.emit()
            return True
        return False

    def _textures(self, lay, material):
        refs = available_texture_refs(self._doc)
        for group, slot, chunk, resolved in material_texture_refs(material, self._doc):
            body = self._card(lay, f'{ui_text("ui_model_viewer_texture_slot")} {group}:{slot}')
            combo = configure_input(QComboBox(), height=Size.INSPECTOR_CONTROL, compact=True)
            combo.setMinimumContentsLength(1)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            current = -1
            for i, ref in enumerate(refs):
                combo.addItem(ref.name or ref.file_path, ref)
                combo.setItemData(i, ref.source_path + '\n' + ref.file_path, Qt.ItemDataRole.ToolTipRole)
                if ref is resolved or ref.chunk is getattr(resolved, 'chunk', None):
                    current = i
                elif current < 0 and (ref.chunk is chunk or ref.name == getattr(chunk, 'name', '')):
                    current = i
            if current < 0:
                combo.insertItem(0, ui_text('ui_model_viewer_missing') + ': ' + getattr(chunk, 'name', ''), None)
                current = 0
            combo.setCurrentIndex(current)
            last_index = [current]
            body.addWidget(combo)
            preview = ImagePreview(minimum_height=128, compact=True)
            preview.set_image(getattr(resolved, 'pil_image', None))
            body.addWidget(preview)
            def changed(index, c=combo, g=group, s=slot, p=preview, previous=last_index):
                ref = c.itemData(index)
                if ref is not None:
                    if self._immediate(lambda: set_material_texture(material, g, s, ref)):
                        previous[0] = index
                        p.set_image(ref.pil_image)
                    else:
                        c.blockSignals(True)
                        c.setCurrentIndex(previous[0])
                        c.blockSignals(False)
            combo.currentIndexChanged.connect(changed)

    def _dynamics(self, dyn):
        lay = self._page('ui_model_viewer_dynamics')
        self._card(lay, ui_text('ui_model_viewer_dynamics'), ui_text('model_dynamics_hint'))
        for i, section in enumerate(dyn.section1):
            self._number(lay, f'{ui_text("ui_model_viewer_coord_index")} {i}', section.coord_index,
                         lambda v, s=section: setattr(s, 'coord_index', v), integer=True, maximum=65535)
            self._vector(lay, f'{ui_text("ui_model_viewer_dynamics_floats")} {i}', section, 'floats', axes=())
        lay.addStretch()

    def _raw(self, obj):
        text = configure_textedit(QTextEdit())
        text.setReadOnly(True)
        text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        lines = []
        if obj is not None:
            lines = [getattr(obj, 'name', ''), type(obj).__name__, getattr(obj, 'filePath', ''),
                     f'{ui_text("ui_model_viewer_raw_size")}: {len(getattr(obj, "data", None) or b"")}',
                     ui_text('model_unknown_hint')]
            if isinstance(obj, NuccChunkModel) and obj.nud:
                meshes = [mesh for group in obj.nud.mesh_groups for mesh in group.meshes]
                lines.extend((f'{ui_text("ui_model_viewer_vertices")}: {sum(len(m.vertices) for m in meshes)}',
                              f'{ui_text("ui_model_viewer_faces")}: {sum(len(m.faces) for m in meshes)}'))
        text.setPlainText('\n'.join(lines) if obj is not None else ui_text('ui_model_viewer_select_item'))
        self._tabs.addTab(text, ui_text('ui_model_viewer_raw'))
