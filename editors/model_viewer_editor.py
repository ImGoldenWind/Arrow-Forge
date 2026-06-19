from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QTextEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H, TOOLBAR_H, ss_accent_sep, ss_badge_missing, ss_bg_dark,
    ss_bg_panel, ss_btn, ss_check, ss_dim_label, ss_field_label,
    ss_input, ss_inspector_group, ss_listwidget,
    ss_main_label, ss_panel_title, ss_placeholder, ss_scrollarea,
    ss_scrollarea_panel_edge, ss_scrollarea_transparent, ss_search,
    ss_tab_widget, ss_toggle_btn, ss_transparent, ss_viewport_panel,
)
from core.themes import P
from core.translations import ui_text
from parsers.model_xfbin_parser import (
    MissingTextureRef, ModelXfbinDocument, RenderScene, ResolvedTextureRef,
    add_texture_xfbin, available_texture_refs, build_render_scene,
    load_model_xfbin, material_texture_refs, save_model_xfbin,
    set_material_texture,
)
from parsers.xfbin_lib import (
    NuccChunkCoord, NuccChunkDynamics, NuccChunkMaterial, NuccChunkModel,
)


class ModelViewerEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self.t = t or ui_text
        self.embedded = embedded
        self._doc: ModelXfbinDocument | None = None
        self._scene: RenderScene | None = None
        self._selected = None
        self._dirty = False
        self._building_inspector = False
        self.setStyleSheet(ss_bg_dark())
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = QFrame()
        toolbar.setFixedHeight(TOOLBAR_H)
        toolbar.setStyleSheet(ss_bg_panel())
        toolbar_lay = QHBoxLayout(toolbar)
        toolbar_lay.setContentsMargins(10, 6, 10, 6)
        toolbar_lay.setSpacing(6)

        self._open_btn = self._tool_btn("ui_model_viewer_open_model", accent=True)
        self._open_btn.clicked.connect(self._open_model_dialog)
        toolbar_lay.addWidget(self._open_btn)

        self._add_tex_btn = self._tool_btn("ui_model_viewer_add_textures")
        self._add_tex_btn.clicked.connect(self._add_texture_dialog)
        self._add_tex_btn.setEnabled(False)
        toolbar_lay.addWidget(self._add_tex_btn)

        self._save_btn = self._tool_btn("ui_model_viewer_save", accent=True)
        self._save_btn.clicked.connect(self._save_file)
        self._save_btn.setEnabled(False)
        toolbar_lay.addWidget(self._save_btn)

        self._snapshot_btn = self._tool_btn("ui_model_viewer_snapshot")
        self._snapshot_btn.clicked.connect(self._export_snapshot)
        self._snapshot_btn.setEnabled(False)
        toolbar_lay.addWidget(self._snapshot_btn)

        self._reset_camera_btn = self._tool_btn("ui_model_viewer_reset_camera")
        self._reset_camera_btn.clicked.connect(self._reset_camera)
        self._reset_camera_btn.setEnabled(False)
        toolbar_lay.addWidget(self._reset_camera_btn)

        toolbar_lay.addStretch()
        self._file_lbl = QLabel()
        self._file_lbl.setFont(QFont("Segoe UI", 10))
        set_file_label_empty(self._file_lbl, self.t("no_file_loaded"))
        toolbar_lay.addWidget(self._file_lbl)
        root.addWidget(toolbar)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        root.addLayout(main, 1)

        self._sidebar = _ModelSidebar(self)
        self._sidebar.selection_changed.connect(self._on_sidebar_selection)
        main.addWidget(self._sidebar, 0)

        center = QWidget()
        center.setStyleSheet(ss_bg_dark())
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(10, 10, 10, 10)
        center_lay.setSpacing(8)

        toggle_bar = QWidget()
        toggle_bar.setStyleSheet(ss_transparent())
        toggle_lay = QHBoxLayout(toggle_bar)
        toggle_lay.setContentsMargins(0, 0, 0, 0)
        toggle_lay.setSpacing(6)
        self._toggle_textured = self._toggle("ui_model_viewer_textured", True)
        self._toggle_wire = self._toggle("ui_model_viewer_wireframe", False)
        self._toggle_bones = self._toggle("ui_model_viewer_bones", False)
        self._toggle_bounds = self._toggle("ui_model_viewer_bounds", True)
        self._toggle_grid = self._toggle("ui_model_viewer_grid", True)
        self._toggle_cull = self._toggle("ui_model_viewer_culling", False)
        for btn in (
            self._toggle_textured, self._toggle_wire, self._toggle_bones,
            self._toggle_bounds, self._toggle_grid, self._toggle_cull,
        ):
            btn.toggled.connect(self._sync_view_toggles)
            toggle_lay.addWidget(btn)
        toggle_lay.addStretch()
        center_lay.addWidget(toggle_bar)

        viewport_frame = QFrame()
        viewport_frame.setStyleSheet(ss_viewport_panel())
        viewport_lay = QVBoxLayout(viewport_frame)
        viewport_lay.setContentsMargins(1, 1, 1, 1)
        self._viewport = _ModelOpenGLViewport()
        viewport_lay.addWidget(self._viewport, 1)
        center_lay.addWidget(viewport_frame, 1)

        self._status_lbl = QLabel(self.t("ui_model_viewer_open_a_model_to_begin"))
        self._status_lbl.setFont(QFont("Segoe UI", 9))
        self._status_lbl.setStyleSheet(ss_dim_label())
        center_lay.addWidget(self._status_lbl)
        main.addWidget(center, 1)

        self._inspector = _InspectorPanel(self)
        self._inspector.value_changed.connect(self._on_value_changed)
        main.addWidget(self._inspector, 0)

    def _tool_btn(self, key: str, accent: bool = False) -> QPushButton:
        btn = QPushButton(self.t(key))
        btn.setFixedHeight(TOOLBAR_BTN_H)
        btn.setFont(QFont("Segoe UI", 10))
        btn.setStyleSheet(ss_btn(accent=accent))
        return btn

    def _toggle(self, key: str, checked: bool) -> QPushButton:
        btn = QPushButton(self.t(key))
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setFixedHeight(28)
        btn.setFont(QFont("Segoe UI", 9))
        btn.setStyleSheet(ss_toggle_btn())
        return btn

    def _open_model_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("ui_model_viewer_open_model"),
            game_files_dialog_dir(target_patterns="*.xfbin"),
            self.t("ui_model_viewer_xfbin_filter"),
        )
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        try:
            create_backup_on_open(path)
            auto_textures = self._auto_texture_paths(path)
            self._doc = load_model_xfbin(path, auto_textures)
            self._dirty = False
            self._selected = None
            self._rebuild_scene()
            self._sidebar.load(self._doc)
            self._inspector.set_context(self._doc, None)
            self._update_file_state()
            self._set_controls_enabled(True)
            self._status_lbl.setText(self._summary_text())
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(exc))

    def _auto_texture_paths(self, model_path: str) -> list[str]:
        base = os.path.basename(model_path)
        candidates = []
        if "bod" in base:
            candidates.append(os.path.join(os.path.dirname(model_path), base.replace("bod", "col", 1)))
        return [p for p in candidates if os.path.exists(p)]

    def _add_texture_dialog(self):
        if not self._doc:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.t("ui_model_viewer_add_textures"),
            os.path.dirname(self._doc.path),
            self.t("ui_model_viewer_xfbin_filter"),
        )
        if not paths:
            return
        try:
            total = 0
            for path in paths:
                total += add_texture_xfbin(self._doc, path)
            self._rebuild_scene()
            self._sidebar.load(self._doc)
            self._inspector.set_context(self._doc, self._selected)
            self._status_lbl.setText(self.t("ui_model_viewer_loaded_textures", p0=total))
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(exc))

    def _save_file(self):
        if not self._doc:
            return
        try:
            save_model_xfbin(self._doc)
            self._dirty = False
            self._update_file_state()
            self._status_lbl.setText(self.t("ui_model_viewer_saved"))
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(exc))

    def _export_snapshot(self):
        if not self._doc:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.t("ui_model_viewer_snapshot"),
            os.path.splitext(self._doc.path)[0] + "_preview.png",
            self.t("ui_model_viewer_png_filter"),
        )
        if not path:
            return
        self._viewport.grabFramebuffer().save(path)
        self._status_lbl.setText(self.t("ui_model_viewer_snapshot_saved", p0=os.path.basename(path)))

    def _reset_camera(self):
        self._viewport.reset_camera()

    def _sync_view_toggles(self):
        self._viewport.set_options(
            textured=self._toggle_textured.isChecked(),
            wireframe=self._toggle_wire.isChecked(),
            bones=self._toggle_bones.isChecked(),
            bounds=self._toggle_bounds.isChecked(),
            grid=self._toggle_grid.isChecked(),
            culling=self._toggle_cull.isChecked(),
        )

    def _on_sidebar_selection(self, obj):
        self._selected = obj
        self._inspector.set_context(self._doc, obj)
        self._viewport.set_selected(obj)

    def _on_value_changed(self):
        if self._building_inspector:
            return
        self._mark_dirty()
        self._rebuild_scene(keep_camera=True)
        self._sidebar.refresh_labels()

    def _mark_dirty(self):
        if self._doc:
            self._doc.dirty = True
        self._dirty = True
        self._update_file_state()

    def _rebuild_scene(self, keep_camera: bool = False):
        if not self._doc:
            return
        self._scene = build_render_scene(self._doc)
        self._viewport.set_scene(self._scene, reset_camera=not keep_camera)
        self._sync_view_toggles()

    def _update_file_state(self):
        if self._doc:
            set_file_label(self._file_lbl, self._doc.path, dirty=self._dirty, empty_text=self.t("no_file_loaded"))
        else:
            set_file_label_empty(self._file_lbl, self.t("no_file_loaded"))

    def _set_controls_enabled(self, enabled: bool):
        self._add_tex_btn.setEnabled(enabled)
        self._save_btn.setEnabled(enabled)
        self._snapshot_btn.setEnabled(enabled)
        self._reset_camera_btn.setEnabled(enabled)

    def _summary_text(self) -> str:
        if not self._doc:
            return self.t("ui_model_viewer_open_a_model_to_begin")
        missing = 0
        for mat in self._doc.material_chunks:
            for _, _, _, resolved in material_texture_refs(mat, self._doc):
                if isinstance(resolved, MissingTextureRef):
                    missing += 1
        return self.t(
            "ui_model_viewer_summary",
            p0=len(self._doc.model_chunks),
            p1=len(self._doc.coord_chunks),
            p2=len(self._doc.material_chunks),
            p3=missing,
        )


class _ModelSidebar(QWidget):
    selection_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self.setFixedWidth(260)
        self.setStyleSheet(ss_bg_panel())
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("search_placeholder"))
        self._search.setFixedHeight(30)
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter)
        root.addWidget(self._search)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setStyleSheet(ss_listwidget())
        self._tree.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self._tree, 1)

    def load(self, doc):
        self._doc = doc
        self._tree.clear()
        if not doc:
            return
        self._add_group("ui_model_viewer_models", doc.model_chunks)
        self._add_group("ui_model_viewer_materials", doc.material_chunks)
        self._add_group("ui_model_viewer_bones", doc.coord_chunks)
        self._add_group("ui_model_viewer_dynamics", doc.dynamics_chunks)
        self._tree.expandToDepth(0)
        self._filter()

    def refresh_labels(self):
        self._filter()

    def _add_group(self, key: str, objects):
        root = QTreeWidgetItem([ui_text(key)])
        root.setData(0, Qt.ItemDataRole.UserRole, None)
        self._tree.addTopLevelItem(root)
        for obj in objects:
            item = QTreeWidgetItem([getattr(obj, "name", getattr(getattr(obj, "node", None), "name", ""))])
            item.setData(0, Qt.ItemDataRole.UserRole, obj)
            root.addChild(item)

    def _selection_changed(self):
        items = self._tree.selectedItems()
        if not items:
            return
        obj = items[0].data(0, Qt.ItemDataRole.UserRole)
        if obj is not None:
            self.selection_changed.emit(obj)

    def _filter(self):
        query = self._search.text().strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(i)
            visible_children = 0
            for j in range(group.childCount()):
                child = group.child(j)
                visible = not query or query in child.text(0).lower()
                child.setHidden(not visible)
                visible_children += int(visible)
            group.setHidden(visible_children == 0 and bool(query))


class _InspectorPanel(QWidget):
    value_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self._obj = None
        self.setFixedWidth(330)
        self.setStyleSheet(ss_bg_panel())
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        title = QLabel(ui_text("ui_model_viewer_inspector"))
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(ss_panel_title())
        root.addWidget(title)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(ss_tab_widget())
        root.addWidget(self._tabs, 1)

    def set_context(self, doc, obj):
        self._doc = doc
        self._obj = obj
        self._tabs.clear()
        if doc is None:
            self._tabs.addTab(self._placeholder(ui_text("ui_model_viewer_no_model_loaded")), ui_text("ui_model_viewer_raw"))
            return
        self._tabs.addTab(self._transform_tab(obj), ui_text("ui_model_viewer_transform"))
        self._tabs.addTab(self._material_tab(obj), ui_text("ui_model_viewer_material"))
        self._tabs.addTab(self._model_tab(obj), ui_text("ui_model_viewer_model"))
        self._tabs.addTab(self._dynamics_tab(obj), ui_text("ui_model_viewer_dynamics"))
        self._tabs.addTab(self._raw_tab(obj), ui_text("ui_model_viewer_raw"))

    def _placeholder(self, text: str):
        wrap = QWidget()
        wrap.setStyleSheet(ss_bg_panel())
        lay = QVBoxLayout(wrap)
        lay.addStretch()
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(ss_placeholder())
        lay.addWidget(label)
        lay.addStretch()
        return wrap

    def _scroll_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_scrollarea_transparent())
        inner = QWidget()
        inner.setStyleSheet(ss_transparent())
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        scroll.setWidget(inner)
        return scroll, lay

    def _transform_tab(self, obj):
        coord = obj if isinstance(obj, NuccChunkCoord) else getattr(obj, "coord_chunk", None)
        if coord is None:
            return self._placeholder(ui_text("ui_model_viewer_select_bone_or_bound_model"))
        scroll, lay = self._scroll_tab()
        self._vector_group(lay, ui_text("ui_model_viewer_position"), coord.node.position, lambda v: self._set_coord(coord, "position", v))
        self._vector_group(lay, ui_text("ui_model_viewer_rotation"), coord.node.rotation, lambda v: self._set_coord(coord, "rotation", v))
        self._vector_group(lay, ui_text("ui_model_viewer_scale"), coord.node.scale, lambda v: self._set_coord(coord, "scale", v), minimum=-1000.0, maximum=1000.0)
        self._number_row(lay, "ui_model_viewer_unk_float", coord.node.unkFloat, lambda v: self._set_coord_scalar(coord, "unkFloat", v), float_value=True)
        self._number_row(lay, "ui_model_viewer_unk_short", coord.node.unkShort, lambda v: self._set_coord_scalar(coord, "unkShort", int(v)), float_value=False, minimum=0, maximum=65535)
        lay.addStretch()
        return scroll

    def _material_tab(self, obj):
        material = obj if isinstance(obj, NuccChunkMaterial) else getattr(obj, "material_chunk", None)
        if material is None:
            return self._placeholder(ui_text("ui_model_viewer_select_material"))
        scroll, lay = self._scroll_tab()
        self._number_row(lay, "ui_model_viewer_field02", material.field02, lambda v: self._set_attr(material, "field02", int(v)), minimum=0, maximum=255)
        self._number_row(lay, "ui_model_viewer_field04", material.field04, lambda v: self._set_attr(material, "field04", float(v)), float_value=True)
        self._number_row(lay, "ui_model_viewer_format", material.format, lambda v: self._set_attr(material, "format", int(v)), minimum=0, maximum=255)
        for idx, value in enumerate(material.floats):
            self._number_row(lay, "ui_model_viewer_material_float", value, lambda v, i=idx: self._set_tuple_value(material, "floats", i, float(v)), float_value=True, suffix=f" {idx}")
        self._texture_slots(lay, material)
        lay.addStretch()
        return scroll

    def _model_tab(self, obj):
        model = obj if isinstance(obj, NuccChunkModel) else getattr(obj, "model_chunk", None)
        if model is None:
            return self._placeholder(ui_text("ui_model_viewer_select_model"))
        scroll, lay = self._scroll_tab()
        self._number_row(lay, "ui_model_viewer_rigging_flag", int(model.rigging_flag), lambda v: self._set_rigging(model, int(v)), minimum=0, maximum=255)
        self._number_row(lay, "ui_model_viewer_coord_index", model.coord_index, lambda v: self._set_attr(model, "coord_index", int(v)), minimum=-1, maximum=9999)
        for idx, value in enumerate(model.material_flags):
            self._number_row(lay, "ui_model_viewer_material_flag", value, lambda v, i=idx: self._set_list_value(model.material_flags, i, int(v)), suffix=f" {idx}", minimum=0, maximum=255)
        if model.flag1_floats:
            for idx, value in enumerate(model.flag1_floats):
                self._number_row(lay, "ui_model_viewer_flag1_float", value, lambda v, i=idx: self._set_tuple_value(model, "flag1_floats", i, float(v)), float_value=True, suffix=f" {idx}")
        if model.nud is not None:
            self._vector4_group(lay, ui_text("ui_model_viewer_bounding_sphere"), model.nud.bounding_sphere, lambda v: self._set_attr(model.nud, "bounding_sphere", tuple(v)))
            for group in model.nud.mesh_groups:
                self._number_row(lay, "ui_model_viewer_bone_flags", group.bone_flags, lambda v, g=group: self._set_attr(g, "bone_flags", int(v)), minimum=0, maximum=65535, suffix=f" {group.name}")
        lay.addStretch()
        return scroll

    def _dynamics_tab(self, obj):
        dyn = obj if isinstance(obj, NuccChunkDynamics) else None
        if dyn is None:
            return self._placeholder(ui_text("ui_model_viewer_select_dynamics"))
        scroll, lay = self._scroll_tab()
        self._info(lay, ui_text("ui_model_viewer_section1_count"), str(len(dyn.section1)))
        self._info(lay, ui_text("ui_model_viewer_section2_count"), str(len(dyn.section2)))
        for sec_idx, sec in enumerate(dyn.section1):
            self._number_row(lay, "ui_model_viewer_coord_index", sec.coord_index, lambda v, s=sec: self._set_attr(s, "coord_index", int(v)), suffix=f" {sec_idx}", minimum=0, maximum=9999)
            self._vector4_group(lay, f"{ui_text('ui_model_viewer_dynamics_floats')} {sec_idx}", sec.floats, lambda v, s=sec: self._set_attr(s, "floats", tuple(v)))
        lay.addStretch()
        return scroll

    def _raw_tab(self, obj):
        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(ss_inspector_group())
        if obj is None:
            text.setText(ui_text("ui_model_viewer_select_item"))
            return text
        lines = [f"{ui_text('ui_model_viewer_name')}: {getattr(obj, 'name', getattr(getattr(obj, 'node', None), 'name', ''))}"]
        lines.append(f"{ui_text('ui_model_viewer_type')}: {type(obj).__name__}")
        data = getattr(obj, "data", None)
        if data is not None:
            lines.append(f"{ui_text('ui_model_viewer_raw_size')}: {len(data)}")
        if isinstance(obj, NuccChunkModel) and obj.nud:
            verts = sum(len(mesh.vertices) for group in obj.nud.mesh_groups for mesh in group.meshes)
            faces = sum(len(mesh.faces) for group in obj.nud.mesh_groups for mesh in group.meshes)
            lines.append(f"{ui_text('ui_model_viewer_vertices')}: {verts}")
            lines.append(f"{ui_text('ui_model_viewer_faces')}: {faces}")
        text.setText("\n".join(lines))
        return text

    def _info(self, lay, label, value):
        row = QWidget()
        row.setStyleSheet(ss_transparent())
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setStyleSheet(ss_field_label())
        row_lay.addWidget(lbl)
        val = QLabel(value)
        val.setStyleSheet(ss_main_label())
        row_lay.addWidget(val)
        lay.addWidget(row)

    def _vector_group(self, lay, label, values, setter, minimum=-10000.0, maximum=10000.0):
        self._vectorn_group(
            lay,
            label,
            values,
            setter,
            (ui_text("ui_model_viewer_axis_x"), ui_text("ui_model_viewer_axis_y"), ui_text("ui_model_viewer_axis_z")),
            minimum,
            maximum,
        )

    def _vector4_group(self, lay, label, values, setter, minimum=-10000.0, maximum=10000.0):
        self._vectorn_group(
            lay,
            label,
            values,
            setter,
            (
                ui_text("ui_model_viewer_axis_x"),
                ui_text("ui_model_viewer_axis_y"),
                ui_text("ui_model_viewer_axis_z"),
                ui_text("ui_model_viewer_axis_r"),
            ),
            minimum,
            maximum,
        )

    def _vectorn_group(self, lay, label, values, setter, axis_labels, minimum, maximum):
        frame = self._group_frame(label)
        grid = QGridLayout(frame)
        grid.setContentsMargins(8, 24, 8, 8)
        spins = []
        for col, axis in enumerate(axis_labels):
            axis_lbl = QLabel(axis)
            axis_lbl.setStyleSheet(ss_dim_label())
            grid.addWidget(axis_lbl, 0, col)
            spin = self._double_spin(values[col], minimum, maximum)
            spins.append(spin)
            grid.addWidget(spin, 1, col)
        def emit():
            setter(tuple(s.value() for s in spins))
            self.value_changed.emit()
        for spin in spins:
            spin.valueChanged.connect(emit)
        lay.addWidget(frame)

    def _number_row(self, lay, key, value, setter, *, float_value=False, suffix="", minimum=-100000, maximum=100000):
        frame = self._group_frame(ui_text(key) + suffix)
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 24, 8, 8)
        if float_value:
            spin = self._double_spin(float(value), float(minimum), float(maximum))
        else:
            spin = QSpinBox()
            spin.setRange(int(minimum), int(maximum))
            spin.setValue(int(value))
            spin.setStyleSheet(ss_input())
        row.addWidget(spin)
        spin.valueChanged.connect(lambda v: (setter(v), self.value_changed.emit()))
        lay.addWidget(frame)

    def _texture_slots(self, lay, material):
        if not self._doc:
            return
        refs = available_texture_refs(self._doc)
        ref_labels = [r.name or r.file_path for r in refs]
        for group_idx, slot_idx, texture_chunk, resolved in material_texture_refs(material, self._doc):
            frame = self._group_frame(f"{ui_text('ui_model_viewer_texture_slot')} {group_idx}:{slot_idx}")
            row = QHBoxLayout(frame)
            row.setContentsMargins(8, 24, 8, 8)
            combo = QComboBox()
            combo.setStyleSheet(ss_input())
            combo.addItems(ref_labels)
            current = getattr(texture_chunk, "name", "")
            if current in ref_labels:
                combo.setCurrentText(current)
            combo.currentIndexChanged.connect(
                lambda idx, g=group_idx, s=slot_idx: self._set_texture_slot(material, g, s, refs[idx])
            )
            row.addWidget(combo, 1)
            if isinstance(resolved, MissingTextureRef):
                badge = QLabel(ui_text("ui_model_viewer_missing"))
                badge.setStyleSheet(ss_badge_missing())
                row.addWidget(badge)
            lay.addWidget(frame)

    def _group_frame(self, title: str):
        frame = QFrame()
        frame.setStyleSheet(ss_inspector_group())
        lbl = QLabel(title, frame)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_panel_title())
        lbl.move(8, 4)
        return frame

    def _double_spin(self, value, minimum=-10000.0, maximum=10000.0):
        spin = QDoubleSpinBox()
        spin.setDecimals(5)
        spin.setRange(minimum, maximum)
        spin.setValue(float(value))
        spin.setSingleStep(0.1)
        spin.setStyleSheet(ss_input())
        return spin

    def _set_coord(self, coord, attr, value):
        setattr(coord.node, attr, tuple(value))

    def _set_coord_scalar(self, coord, attr, value):
        setattr(coord.node, attr, value)

    def _set_attr(self, obj, attr, value):
        setattr(obj, attr, value)

    def _set_tuple_value(self, obj, attr, idx, value):
        values = list(getattr(obj, attr))
        values[idx] = value
        setattr(obj, attr, tuple(values))

    def _set_list_value(self, values, idx, value):
        values[idx] = value

    def _set_rigging(self, model, value):
        from parsers.xfbin_lib import RiggingFlag
        model.rigging_flag = RiggingFlag(value)

    def _set_texture_slot(self, material, group_idx, slot_idx, ref):
        set_material_texture(material, group_idx, slot_idx, ref)
        self.value_changed.emit()


class _ModelOpenGLViewport(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene: RenderScene | None = None
        self._selected = None
        self._textures = {}
        self._last_pos = QPoint()
        self._yaw = 25.0
        self._pitch = 20.0
        self._distance = 250.0
        self._center = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self._options = {
            "textured": True,
            "wireframe": False,
            "bones": False,
            "bounds": True,
            "grid": True,
            "culling": False,
        }
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_scene(self, scene: RenderScene, reset_camera: bool = True):
        self._scene = scene
        self._textures.clear()
        if reset_camera:
            self.reset_camera()
        self.update()

    def set_selected(self, obj):
        self._selected = obj
        self.update()

    def set_options(self, **options):
        self._options.update(options)
        self.update()

    def reset_camera(self):
        if self._scene:
            mn = np.array(self._scene.bounds_min, dtype=np.float32)
            mx = np.array(self._scene.bounds_max, dtype=np.float32)
            self._center = (mn + mx) / 2.0
            radius = max(float(np.linalg.norm(mx - mn)) * 0.75, 50.0)
            self._distance = radius * 1.8
        self._yaw = 25.0
        self._pitch = 20.0
        self.update()

    def initializeGL(self):
        try:
            from OpenGL import GL
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        except Exception:
            pass

    def resizeGL(self, w, h):
        try:
            from OpenGL import GL, GLU
            GL.glViewport(0, 0, max(1, w), max(1, h))
            GL.glMatrixMode(GL.GL_PROJECTION)
            GL.glLoadIdentity()
            GLU.gluPerspective(45.0, max(1.0, w / max(1, h)), 1.0, 20000.0)
            GL.glMatrixMode(GL.GL_MODELVIEW)
        except Exception:
            pass

    def paintGL(self):
        try:
            from OpenGL import GL, GLU
        except Exception:
            return

        bg = QColor(P.get("viewport_bg", P["bg_dark"]))
        GL.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glLoadIdentity()
        GL.glTranslatef(0.0, 0.0, -self._distance)
        GL.glRotatef(self._pitch, 1.0, 0.0, 0.0)
        GL.glRotatef(self._yaw, 0.0, 1.0, 0.0)
        GL.glTranslatef(-float(self._center[0]), -float(self._center[1]), -float(self._center[2]))

        if self._options["culling"]:
            GL.glEnable(GL.GL_CULL_FACE)
        else:
            GL.glDisable(GL.GL_CULL_FACE)

        if self._options["grid"]:
            self._draw_grid(GL)
        if not self._scene:
            return
        for mesh in self._scene.meshes:
            if mesh.visible:
                self._draw_mesh(GL, mesh)
        if self._options["bones"]:
            self._draw_bones(GL)
        if self._options["bounds"]:
            self._draw_bounds(GL)

    def _draw_mesh(self, GL, mesh):
        selected = self._selected is mesh.model_chunk or self._selected is mesh.material_chunk
        textured = self._options["textured"] and isinstance(mesh.texture, ResolvedTextureRef) and mesh.texture.pil_image is not None
        if textured:
            tex_id = self._texture_id(GL, mesh.texture)
            GL.glEnable(GL.GL_TEXTURE_2D)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
            GL.glColor4f(1.0, 1.0, 1.0, 1.0)
        else:
            GL.glDisable(GL.GL_TEXTURE_2D)
            if isinstance(mesh.texture, MissingTextureRef):
                self._gl_color(GL, P.get("warning", P["accent_dim"]))
            elif selected:
                self._gl_color(GL, P["accent"])
            else:
                self._gl_color(GL, P["text_sec"])

        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE if self._options["wireframe"] else GL.GL_FILL)
        GL.glBegin(GL.GL_TRIANGLES)
        for face in mesh.faces:
            for idx in face:
                if mesh.uvs is not None and textured:
                    GL.glTexCoord2f(float(mesh.uvs[idx][0]), float(mesh.uvs[idx][1]))
                if mesh.normals is not None:
                    GL.glNormal3f(float(mesh.normals[idx][0]), float(mesh.normals[idx][1]), float(mesh.normals[idx][2]))
                if mesh.colors is not None and not textured:
                    GL.glColor4f(float(mesh.colors[idx][0]), float(mesh.colors[idx][1]), float(mesh.colors[idx][2]), float(mesh.colors[idx][3]))
                v = mesh.vertices[idx]
                GL.glVertex3f(float(v[0]), float(v[1]), float(v[2]))
        GL.glEnd()
        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
        GL.glDisable(GL.GL_TEXTURE_2D)

    def _texture_id(self, GL, ref: ResolvedTextureRef):
        key = id(ref.pil_image)
        if key in self._textures:
            return self._textures[key]
        img = ref.pil_image.convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        tex_id = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, img.width, img.height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, img.tobytes())
        self._textures[key] = tex_id
        return tex_id

    def _draw_grid(self, GL):
        GL.glDisable(GL.GL_TEXTURE_2D)
        color = QColor(P.get("border", "#30343f"))
        GL.glColor4f(color.redF(), color.greenF(), color.blueF(), 0.45)
        GL.glBegin(GL.GL_LINES)
        size = 200
        step = 20
        for i in range(-size, size + 1, step):
            GL.glVertex3f(i, 0, -size)
            GL.glVertex3f(i, 0, size)
            GL.glVertex3f(-size, 0, i)
            GL.glVertex3f(size, 0, i)
        GL.glEnd()

    def _gl_color(self, GL, color_key: str, alpha: float = 1.0):
        color = QColor(color_key)
        GL.glColor4f(color.redF(), color.greenF(), color.blueF(), alpha)

    def _draw_bones(self, GL):
        if not self._scene:
            return
        color = QColor(P.get("accent", "#d93b35"))
        GL.glColor4f(color.redF(), color.greenF(), color.blueF(), 0.85)
        GL.glBegin(GL.GL_LINES)
        for _, start, end in self._scene.bones:
            GL.glVertex3f(*[float(x) for x in start])
            GL.glVertex3f(*[float(x) for x in end])
        GL.glEnd()

    def _draw_bounds(self, GL):
        if not self._scene:
            return
        mn = self._scene.bounds_min
        mx = self._scene.bounds_max
        corners = [
            (mn[0], mn[1], mn[2]), (mx[0], mn[1], mn[2]), (mx[0], mx[1], mn[2]), (mn[0], mx[1], mn[2]),
            (mn[0], mn[1], mx[2]), (mx[0], mn[1], mx[2]), (mx[0], mx[1], mx[2]), (mn[0], mx[1], mx[2]),
        ]
        edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
        color = QColor(P.get("secondary", "#aaaaaa"))
        GL.glColor4f(color.redF(), color.greenF(), color.blueF(), 0.75)
        GL.glBegin(GL.GL_LINES)
        for a, b in edges:
            GL.glVertex3f(*corners[a])
            GL.glVertex3f(*corners[b])
        GL.glEnd()

    def mousePressEvent(self, event):
        self._last_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        delta = pos - self._last_pos
        self._last_pos = pos
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._yaw += delta.x() * 0.4
            self._pitch += delta.y() * 0.4
            self._pitch = max(-89.0, min(89.0, self._pitch))
        elif event.buttons() & Qt.MouseButton.RightButton:
            self._center[0] -= delta.x() * self._distance * 0.002
            self._center[1] += delta.y() * self._distance * 0.002
        self.update()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self._distance *= math.pow(0.88, steps)
        self._distance = max(5.0, min(20000.0, self._distance))
        self.update()
