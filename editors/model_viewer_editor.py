from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import math
import os
import re

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QTextEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.icons import _themed_icon
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.style_helpers import (
    TOOLBAR_BTN_H, TOOLBAR_H, ss_accent_sep, ss_badge_missing, ss_bg_dark,
    ss_bg_panel, ss_btn, ss_dim_label, ss_field_label,
    ss_dialog,
    ss_inspector_group, ss_inspector_input,
    ss_input, ss_main_label, ss_panel_title, ss_placeholder,
    ss_scrollarea_transparent, ss_search, ss_sep, ss_sidebar_frame,
    ss_sidebar_treewidget,
    ss_tab_widget, ss_toggle_btn, ss_transparent,
    ss_viewport_panel, make_editor_card, add_editor_card_title,
)
from core.themes import P
from core.translations import ui_text
from parsers.model_xfbin_parser import (
    MissingTextureRef, ModelXfbinDocument, RenderScene, ResolvedTextureRef,
    add_texture_xfbin, available_texture_refs,
    build_render_scene, load_model_xfbin, material_texture_refs,
    save_model_xfbin, set_material_texture,
)
from parsers.xfbin_lib import (
    NuccChunkCoord, NuccChunkDynamics, NuccChunkMaterial, NuccChunkModel,
)


@dataclass
class _CharacterModelVariant:
    path: str
    code: str
    body_name: str
    label: str
    palette_paths: list[str]


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
        self._building_model_controls = False
        self._model_variants: list[_CharacterModelVariant] = []
        self._current_variant_index = -1
        self._current_palette_index = -1
        self._compact_layout = None
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
        self._toolbar_buttons = []

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

        self._model_lbl = QLabel(self.t("ui_model_viewer_model_variant"))
        self._model_lbl.setStyleSheet(ss_dim_label())
        toolbar_lay.addWidget(self._model_lbl)
        self._model_combo = QComboBox()
        self._model_combo.setFixedHeight(32)
        self._model_combo.setMinimumWidth(150)
        self._model_combo.setMaximumWidth(220)
        self._model_combo.setEnabled(False)
        self._model_combo.setStyleSheet(ss_input())
        self._model_combo.currentIndexChanged.connect(self._on_model_variant_changed)
        toolbar_lay.addWidget(self._model_combo)

        self._palette_lbl = QLabel(self.t("ui_model_viewer_color_scheme"))
        self._palette_lbl.setStyleSheet(ss_dim_label())
        toolbar_lay.addWidget(self._palette_lbl)
        self._palette_combo = QComboBox()
        self._palette_combo.setFixedHeight(32)
        self._palette_combo.setMinimumWidth(110)
        self._palette_combo.setMaximumWidth(150)
        self._palette_combo.setEnabled(False)
        self._palette_combo.setStyleSheet(ss_input())
        self._palette_combo.currentIndexChanged.connect(self._on_palette_changed)
        toolbar_lay.addWidget(self._palette_combo)

        self._file_lbl = QLabel()
        self._file_lbl.setFont(QFont("Segoe UI", 10))
        set_file_label_empty(self._file_lbl, self.t("no_file_loaded"))
        self._file_lbl.hide()
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

        left_divider = QFrame()
        left_divider.setFixedWidth(1)
        left_divider.setStyleSheet(ss_sep())
        main.addWidget(left_divider)

        center = QWidget()
        self._center_panel = center
        center.setStyleSheet(ss_bg_dark())
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 8)
        center_lay.setSpacing(8)

        self._viewport_frame = _ViewportPanel()
        self._viewport = _ModelOpenGLViewport()
        self._viewport_frame.set_viewport(self._viewport)

        self._view_controls = _ViewportControls()
        self._toggle_textured = self._view_controls.add_toggle(self.t("ui_model_viewer_textured"), True, "fa6s.image")
        self._toggle_wire = self._view_controls.add_toggle(self.t("ui_model_viewer_wireframe"), False, "fa6s.border-all")
        self._toggle_bones = self._view_controls.add_toggle(self.t("ui_model_viewer_bones"), False, "fa6s.bone")
        self._toggle_bounds = self._view_controls.add_toggle(self.t("ui_model_viewer_bounds"), True, "fa6s.cube")
        self._toggle_grid = self._view_controls.add_toggle(self.t("ui_model_viewer_grid"), True, "fa6s.table-cells")
        self._toggle_cull = self._view_controls.add_toggle(self.t("ui_model_viewer_culling"), False, "fa6s.eye-slash")
        for btn in (
            self._toggle_textured, self._toggle_wire, self._toggle_bones,
            self._toggle_bounds, self._toggle_grid, self._toggle_cull,
        ):
            btn.toggled.connect(self._sync_view_toggles)
        self._viewport_frame.set_controls(self._view_controls)

        view_cube = _ViewCubeWidget()
        view_cube.view_requested.connect(self._viewport.set_camera_view)
        self._viewport_frame.set_view_cube(view_cube)

        axis_gizmo = _AxisGizmoWidget()
        self._viewport.camera_changed.connect(axis_gizmo.set_camera)
        self._viewport_frame.set_axis_gizmo(axis_gizmo)
        center_lay.addWidget(self._viewport_frame, 1)

        self._empty_hint_card, empty_hint_lay = make_editor_card(center, margins=(14, 12, 14, 12), spacing=8)
        add_editor_card_title(
            empty_hint_lay,
            self.t("ui_model_viewer_no_model_loaded"),
            "fa6s.cube",
            self.t("ui_model_viewer_open_a_model_to_begin"),
            icon_size=18,
        )
        center_lay.addWidget(self._empty_hint_card)

        self._status_lbl = QLabel(self.t("ui_model_viewer_open_a_model_to_begin"))
        self._status_lbl.setFont(QFont("Segoe UI", 9))
        self._status_lbl.setStyleSheet(ss_dim_label())
        self._status_lbl.hide()
        center_lay.addWidget(self._status_lbl)
        main.addWidget(center, 1)

        right_divider = QFrame()
        right_divider.setFixedWidth(1)
        right_divider.setStyleSheet(ss_sep())
        main.addWidget(right_divider)

        self._inspector = _InspectorPanel(self)
        self._inspector.value_changed.connect(self._on_value_changed)
        main.addWidget(self._inspector, 0)
        self._apply_responsive_layout()

    def _tool_btn(self, key: str, accent: bool = False) -> QPushButton:
        text = self.t(key)
        btn = QPushButton(text)
        btn.setFixedHeight(TOOLBAR_BTN_H)
        btn.setFont(QFont("Segoe UI", 10))
        icon_name = {
            "ui_model_viewer_open_model": "fa6s.folder-open",
            "ui_model_viewer_add_textures": "fa6s.images",
            "ui_model_viewer_save": "fa6s.floppy-disk",
            "ui_model_viewer_snapshot": "fa6s.camera",
            "ui_model_viewer_reset_camera": "fa6s.rotate-left",
        }.get(key, "fa6s.cube")
        btn.setIcon(_themed_icon(icon_name, color=P.get("button_text", P["text_main"]), size=14))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(text)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(ss_btn(accent=accent))
        btn._model_viewer_text = text
        self._toolbar_buttons.append(btn)
        return btn

    def _apply_responsive_layout(self):
        if not hasattr(self, "_sidebar"):
            return
        compact = self.width() < 1040
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        for btn in self._toolbar_buttons:
            btn.setText("" if compact else btn._model_viewer_text)
            btn.setFixedWidth(38 if compact else btn.sizeHint().width())
        self._model_lbl.setVisible(not compact)
        self._palette_lbl.setVisible(not compact)
        self._model_combo.setMinimumWidth(128 if compact else 150)
        self._model_combo.setMaximumWidth(156 if compact else 220)
        self._palette_combo.setMinimumWidth(118 if compact else 110)
        self._palette_combo.setMaximumWidth(128 if compact else 150)
        self._sidebar.set_panel_width(220 if compact else 260)
        self._inspector.set_panel_width(270 if compact else 320)
        self._center_panel.setMinimumWidth(220 if compact else 300)
        self._viewport.setMinimumSize(220 if compact else 320, 220)
        self._viewport_frame.setMinimumSize(220 if compact else 260, 220)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _open_model_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("ui_model_viewer_open_model"),
            self._model_open_dir(),
            self.t("ui_model_viewer_xfbin_filter"),
        )
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        if self._dirty and not self._confirm_switch_from_dirty():
            return
        self._model_variants = self._discover_model_variants(path)
        self._current_variant_index = self._variant_index_for_path(path)
        if self._current_variant_index < 0:
            self._current_variant_index = 0
        self._current_palette_index = self._preferred_palette_index(
            self._model_variants[self._current_variant_index],
            preferred_palette_number=0,
        )
        self._populate_model_controls()
        self._load_current_variant()

    def _load_current_variant(self, keep_camera: bool = False):
        if not (0 <= self._current_variant_index < len(self._model_variants)):
            return
        variant = self._model_variants[self._current_variant_index]
        try:
            create_backup_on_open(variant.path)
            _, texture_paths = self._current_variant_paths()
            self._set_controls_enabled(False)
            self._doc = load_model_xfbin(variant.path, texture_paths, palette_alias_index=0)
            self._dirty = False
            self._selected = None
            self._rebuild_scene(keep_camera=keep_camera)
            self._sidebar.load(self._doc)
            self._inspector.set_context(self._doc, None)
            self._update_file_state()
            self._set_controls_enabled(True)
            self._set_status(self._summary_text())
        except Exception as exc:
            self._set_controls_enabled(self._doc is not None)
            QMessageBox.critical(self, self.t("dlg_title_error"), str(exc))

    def _discover_model_variants(self, selected_path: str) -> list[_CharacterModelVariant]:
        selected_info = self._model_file_info(selected_path)
        if not selected_info:
            return [self._variant_from_path(selected_path)]
        selected_family = selected_info["family_key"]
        folder = os.path.dirname(selected_path)
        variants = []
        try:
            filenames = sorted(os.listdir(folder))
        except OSError:
            filenames = [os.path.basename(selected_path)]
        for filename in filenames:
            path = os.path.join(folder, filename)
            info = self._model_file_info(path)
            if not info or info["family_key"] != selected_family:
                continue
            variants.append(self._variant_from_info(path, info))
        if not variants:
            variants.append(self._variant_from_path(selected_path))
        variants.sort(key=lambda v: (self._model_sort_key(v.code), v.body_name.lower()))
        return variants

    def _variant_from_path(self, path: str) -> _CharacterModelVariant:
        info = self._model_file_info(path) or {}
        return self._variant_from_info(path, info)

    def _variant_from_info(self, path: str, info: dict) -> _CharacterModelVariant:
        code = info.get("code") or os.path.basename(path).split("bod", 1)[0]
        body_name = info.get("body_name") or os.path.splitext(os.path.basename(path))[0].replace(code, "", 1)
        palette_paths = self._palette_paths_for_code(path, code)
        return _CharacterModelVariant(
            path=path,
            code=code,
            body_name=body_name,
            label=f"{code} {body_name}",
            palette_paths=palette_paths,
        )

    def _model_file_info(self, path: str) -> dict | None:
        filename = os.path.basename(path)
        if "_backup" in filename.lower():
            return None
        match = re.match(r"^(?P<code>.+?)(?P<body>bod[^.]*)\.xfbin$", filename, re.IGNORECASE)
        if not match:
            return None
        code = match.group("code")
        body_name = match.group("body")
        code_match = re.match(r"^(?P<base>.*?)(?P<variant>\d)(?P<slot>\d)$", code)
        if code_match:
            family_key = f"{code_match.group('base')}?{code_match.group('slot')}"
        else:
            family_key = code
        return {"code": code, "body_name": body_name, "family_key": family_key}

    def _model_sort_key(self, code: str):
        match = re.match(r"^(?P<base>.*?)(?P<variant>\d)(?P<slot>\d)$", code)
        if not match:
            return (code, 0, 0)
        return (match.group("base"), int(match.group("variant")), int(match.group("slot")))

    def _palette_paths_for_code(self, model_path: str, code: str) -> list[str]:
        pattern = re.compile(rf"^{re.escape(code)}col(?P<index>\d+)\.xfbin$", re.IGNORECASE)
        model_dir = os.path.dirname(os.path.abspath(model_path))
        folders = [model_dir]
        folders.extend(self._texture_search_dirs(model_path))
        paths = []
        seen = set()
        for folder in folders:
            folder_key = os.path.abspath(folder).lower() if folder else ""
            if not folder_key or folder_key in seen or not os.path.isdir(folder):
                continue
            seen.add(folder_key)
            try:
                filenames = sorted(os.listdir(folder))
            except OSError:
                continue
            for filename in filenames:
                match = pattern.match(filename)
                if match:
                    paths.append(os.path.join(folder, filename))
        paths = self._unique_existing_paths(paths, exclude=model_path)
        paths.sort(key=lambda p: self._palette_number(p))
        return paths

    def _variant_index_for_path(self, path: str) -> int:
        target = os.path.abspath(path).lower()
        for idx, variant in enumerate(self._model_variants):
            if os.path.abspath(variant.path).lower() == target:
                return idx
        return -1

    def _preferred_palette_index(self, variant: _CharacterModelVariant, preferred_palette_number: int = 0) -> int:
        if not variant.palette_paths:
            return -1
        for idx, path in enumerate(variant.palette_paths):
            if self._palette_number(path) == preferred_palette_number:
                return idx
        return 0

    def _palette_number(self, path: str) -> int:
        match = re.search(r"col(\d+)\.xfbin$", os.path.basename(path), re.IGNORECASE)
        return int(match.group(1)) if match else -1

    def _populate_model_controls(self):
        self._building_model_controls = True
        try:
            self._model_combo.clear()
            for variant in self._model_variants:
                self._model_combo.addItem(variant.label)
            self._model_combo.setCurrentIndex(self._current_variant_index)
            self._populate_palette_controls()
        finally:
            self._building_model_controls = False

    def _populate_palette_controls(self):
        self._palette_combo.clear()
        variant = self._model_variants[self._current_variant_index] if 0 <= self._current_variant_index < len(self._model_variants) else None
        if not variant or not variant.palette_paths:
            self._palette_combo.addItem(self.t("ui_model_viewer_embedded_textures"))
            self._current_palette_index = -1
        else:
            for path in variant.palette_paths:
                self._palette_combo.addItem(self.t("ui_model_viewer_palette_label", p0=self._palette_number(path)))
            self._current_palette_index = max(0, min(self._current_palette_index, len(variant.palette_paths) - 1))
            self._palette_combo.setCurrentIndex(self._current_palette_index)
        self._model_combo.setEnabled(len(self._model_variants) > 1)
        self._palette_combo.setEnabled(bool(variant and len(variant.palette_paths) > 1))

    def _on_model_variant_changed(self, index: int):
        if self._building_model_controls or index < 0 or index == self._current_variant_index:
            return
        old_index = self._current_variant_index
        if self._dirty and not self._confirm_switch_from_dirty():
            self._building_model_controls = True
            try:
                self._model_combo.setCurrentIndex(old_index)
            finally:
                self._building_model_controls = False
            return
        previous_palette_number = -1
        if 0 <= self._current_variant_index < len(self._model_variants):
            previous = self._model_variants[self._current_variant_index]
            if 0 <= self._current_palette_index < len(previous.palette_paths):
                previous_palette_number = self._palette_number(previous.palette_paths[self._current_palette_index])
        self._current_variant_index = index
        self._current_palette_index = self._preferred_palette_index(
            self._model_variants[index],
            preferred_palette_number=max(previous_palette_number, 0),
        )
        self._building_model_controls = True
        try:
            self._populate_palette_controls()
        finally:
            self._building_model_controls = False
        self._load_current_variant()

    def _on_palette_changed(self, index: int):
        if self._building_model_controls or index < 0:
            return
        old_index = self._current_palette_index
        if self._dirty and not self._confirm_switch_from_dirty():
            self._building_model_controls = True
            try:
                self._palette_combo.setCurrentIndex(old_index)
            finally:
                self._building_model_controls = False
            return
        self._current_palette_index = index
        self._load_current_variant(keep_camera=True)

    def _confirm_switch_from_dirty(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(self.t("unsaved_changes_title"))
        box.setStyleSheet(ss_dialog())
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(self.t("unsaved_changes_message"))
        box.setInformativeText(self.t("unsaved_changes_detail"))
        save_btn = box.addButton(self.t("unsaved_changes_save"), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton(self.t("unsaved_changes_discard"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(self.t("unsaved_changes_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked == cancel_btn:
            return False
        if clicked == discard_btn:
            return True
        if clicked == save_btn:
            self._save_file()
            if self._dirty:
                QMessageBox.warning(
                    self,
                    self.t("unsaved_changes_title"),
                    self.t("unsaved_changes_save_cancelled_or_failed"),
                )
                return False
            return True
        return False

    def _auto_texture_paths(self, model_path: str) -> list[str]:
        base = os.path.basename(model_path)
        lowered = base.lower()
        model_dir = os.path.dirname(model_path)
        prefix = lowered.split("bod", 1)[0] if "bod" in lowered else os.path.splitext(lowered)[0]
        candidates: list[str] = []
        if "bod" in lowered:
            candidates.append(os.path.join(model_dir, base.replace("bod", "col", 1)))
            candidates.append(os.path.join(model_dir, base.replace("bod1", "col0", 1)))

        for folder in self._texture_search_dirs(model_path):
            if not os.path.isdir(folder):
                continue
            try:
                filenames = sorted(os.listdir(folder))
            except OSError:
                continue
            for filename in filenames:
                name = filename.lower()
                path = os.path.join(folder, filename)
                if not name.endswith(".xfbin") or os.path.abspath(path) == os.path.abspath(model_path):
                    continue
                if "col" in name and (not prefix or name.startswith(prefix)):
                    candidates.append(path)

        seen_paths = set()
        seen_names = set()
        result = []
        for path in candidates:
            path_key = os.path.abspath(path).lower()
            name_key = os.path.basename(path).lower()
            if path_key in seen_paths or name_key in seen_names or not os.path.isfile(path):
                continue
            seen_paths.add(path_key)
            seen_names.add(name_key)
            result.append(path)
        return result[:12]

    def _unique_existing_paths(self, paths: list[str], *, exclude: str = "") -> list[str]:
        seen = set()
        seen_names = set()
        result = []
        exclude_key = os.path.abspath(exclude).lower() if exclude else ""
        for path in paths:
            if not path:
                continue
            key = os.path.abspath(path).lower()
            name_key = os.path.basename(path).lower()
            if key == exclude_key or key in seen or name_key in seen_names or not os.path.isfile(path):
                continue
            seen.add(key)
            seen_names.add(name_key)
            result.append(path)
        return result

    def _model_open_dir(self) -> str:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_spc = os.path.join(project_root, "spc")
        if os.path.isdir(local_spc):
            try:
                if any(fnmatch.fnmatchcase(name.lower(), "*bod*.xfbin") for name in os.listdir(local_spc)):
                    return local_spc
            except OSError:
                pass
        game_dir = load_settings().get("game_files_dir", "")
        if game_dir and os.path.isdir(game_dir):
            spc_dir = self._find_named_child_dir(game_dir, "spc", ("*bod*.xfbin",))
            if spc_dir:
                return spc_dir
        return game_files_dialog_dir(target_patterns=("*bod*.xfbin",))

    def _texture_search_dirs(self, model_path: str) -> list[str]:
        model_dir = os.path.dirname(model_path)
        parent = os.path.dirname(model_dir)
        dirs = [
            model_dir,
            parent,
            os.path.join(parent, "spc"),
            os.path.join(parent, "col"),
            os.path.join(parent, "tex"),
            os.path.join(parent, "texture"),
            os.path.join(parent, "textures"),
        ]
        game_dir = load_settings().get("game_files_dir", "")
        if game_dir and os.path.isdir(game_dir):
            for name in ("spc", "col", "tex", "texture", "textures"):
                found = self._find_named_child_dir(game_dir, name, ("*col*.xfbin",))
                if found:
                    dirs.append(found)
        result = []
        seen = set()
        for folder in dirs:
            if not folder:
                continue
            key = os.path.abspath(folder).lower()
            if key not in seen:
                seen.add(key)
                result.append(folder)
        return result

    def _find_named_child_dir(self, root: str, dirname: str, patterns: tuple[str, ...]) -> str:
        target = dirname.lower()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            if os.path.basename(dirpath).lower() != target:
                continue
            lowered = [name.lower() for name in filenames]
            if not patterns:
                return dirpath
            for pattern in patterns:
                pattern_lower = pattern.lower()
                if any(fnmatch.fnmatchcase(name, pattern_lower) for name in lowered):
                    return dirpath
        return ""

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
            self._set_status(self.t("ui_model_viewer_loaded_textures", p0=total))
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(exc))

    def _save_file(self):
        if not self._doc:
            return
        try:
            save_model_xfbin(self._doc)
            self._dirty = False
            self._update_file_state()
            self._set_status(self.t("ui_model_viewer_saved"))
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
        self._set_status(self.t("ui_model_viewer_snapshot_saved", p0=os.path.basename(path)))

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

    def _set_status(self, text: str):
        self._status_lbl.setText(text)
        self._status_lbl.show()

    def _rebuild_scene(self, keep_camera: bool = False):
        if not self._doc:
            return
        self._scene = build_render_scene(self._doc)
        self._viewport.set_scene(self._scene, reset_camera=not keep_camera)
        self._empty_hint_card.hide()
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
        variant = self._model_variants[self._current_variant_index] if 0 <= self._current_variant_index < len(self._model_variants) else None
        self._model_combo.setEnabled(enabled and len(self._model_variants) > 1)
        self._palette_combo.setEnabled(enabled and bool(variant and len(variant.palette_paths) > 1))

    def _current_variant_paths(self) -> tuple[str, list[str]]:
        if not (0 <= self._current_variant_index < len(self._model_variants)):
            return "", []
        variant = self._model_variants[self._current_variant_index]
        texture_paths = []
        selected_palette_number = 0
        if 0 <= self._current_palette_index < len(variant.palette_paths):
            selected_palette = variant.palette_paths[self._current_palette_index]
            selected_palette_number = self._palette_number(selected_palette)
            texture_paths.append(selected_palette)
        for path in self._auto_texture_paths(variant.path):
            if self._is_palette_path_for_code(path, variant.code) and self._palette_number(path) != selected_palette_number:
                continue
            texture_paths.append(path)
        return variant.path, self._unique_existing_paths(texture_paths, exclude=variant.path)

    def _is_palette_path_for_code(self, path: str, code: str) -> bool:
        return re.match(rf"^{re.escape(code)}col\d+\.xfbin$", os.path.basename(path), re.IGNORECASE) is not None

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

class _ModelSidebar(QFrame):
    selection_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.set_panel_width(260)
        self.setStyleSheet(ss_sidebar_frame())
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(4)

        search_row = QWidget()
        search_row.setStyleSheet(ss_transparent())
        search_lay = QHBoxLayout(search_row)
        search_lay.setContentsMargins(0, 0, 0, 0)
        search_lay.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("search_placeholder"))
        self._search.setFixedHeight(30)
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter)
        search_lay.addWidget(self._search, 1)
        root.addWidget(search_row)

        self._tree = QTreeWidget()
        self._tree.setFrameShape(QFrame.Shape.NoFrame)
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tree.setIconSize(QSize(14, 14))
        self._tree.setIndentation(10)
        self._tree.setRootIsDecorated(False)
        self._tree.setStyleSheet(ss_sidebar_treewidget())
        self._tree.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self._tree, 1)

    def set_panel_width(self, width: int):
        width = max(200, width)
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)

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
        root.setIcon(0, self._group_icon(key))
        root.setData(0, Qt.ItemDataRole.UserRole, None)
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._tree.addTopLevelItem(root)
        for obj in objects:
            item = QTreeWidgetItem([getattr(obj, "name", getattr(getattr(obj, "node", None), "name", ""))])
            item.setIcon(0, self._dot_icon())
            item.setData(0, Qt.ItemDataRole.UserRole, obj)
            root.addChild(item)

    def _group_icon(self, key: str) -> QIcon:
        icons = {
            "ui_model_viewer_models": "fa6s.cube",
            "ui_model_viewer_materials": "fa6s.layer-group",
            "ui_model_viewer_bones": "fa6s.bone",
            "ui_model_viewer_dynamics": "fa6s.circle-nodes",
        }
        return _themed_icon(icons.get(key, "fa6s.folder"), color=P.get("icon_color", P["accent"]), size=14)

    def _dot_icon(self) -> QIcon:
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(P.get("text_dim", P["text_sec"]))))
        painter.drawEllipse(QRectF(5, 5, 4, 4))
        painter.end()
        return QIcon(pix)

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


class _InspectorPanel(QFrame):
    value_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self._obj = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.set_panel_width(320)
        self.setStyleSheet(ss_sidebar_frame())
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(ss_transparent())
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(4, 0, 4, 0)
        header_lay.setSpacing(6)
        title = QLabel(ui_text("ui_model_viewer_inspector"))
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(ss_panel_title())
        header_lay.addWidget(title)
        header_lay.addStretch()
        root.addWidget(header)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(ss_tab_widget())
        root.addWidget(self._tabs, 1)

    def set_panel_width(self, width: int):
        width = max(250, width)
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)

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
        self._tabs.setCurrentIndex(self._preferred_tab_index(obj))

    def _preferred_tab_index(self, obj) -> int:
        if isinstance(obj, NuccChunkMaterial):
            return 1
        if isinstance(obj, NuccChunkModel):
            return 2
        if isinstance(obj, NuccChunkDynamics):
            return 3
        if isinstance(obj, NuccChunkCoord):
            return 0
        if getattr(obj, "material_chunk", None) is not None:
            return 1
        if getattr(obj, "model_chunk", None) is not None:
            return 2
        if getattr(obj, "coord_chunk", None) is not None:
            return 0
        return 4

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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(ss_scrollarea_transparent())
        inner = QWidget()
        inner.setStyleSheet(ss_transparent())
        inner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
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
        text.setObjectName("ModelInspectorRaw")
        text.setReadOnly(True)
        text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        frame, body = self._group_frame(label)
        grid_wrap = QWidget()
        grid_wrap.setStyleSheet(ss_transparent())
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(3)
        spins = []
        for col, axis in enumerate(axis_labels):
            axis_lbl = QLabel(axis)
            axis_lbl.setStyleSheet(ss_dim_label())
            grid.addWidget(axis_lbl, 0, col)
            spin = self._double_spin(values[col], minimum, maximum)
            spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            spins.append(spin)
            grid.addWidget(spin, 1, col)
        body.addWidget(grid_wrap)
        def emit():
            setter(tuple(s.value() for s in spins))
            self.value_changed.emit()
        for spin in spins:
            spin.valueChanged.connect(emit)
        lay.addWidget(frame)

    def _number_row(self, lay, key, value, setter, *, float_value=False, suffix="", minimum=-100000, maximum=100000):
        frame, body = self._group_frame(ui_text(key) + suffix)
        row = QWidget()
        row.setStyleSheet(ss_transparent())
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        if float_value:
            spin = self._double_spin(float(value), float(minimum), float(maximum))
        else:
            spin = QSpinBox()
            spin.setRange(int(minimum), int(maximum))
            spin.setValue(int(value))
            spin.setStyleSheet(ss_inspector_input())
            spin.setFixedHeight(26)
        row_lay.addWidget(spin)
        body.addWidget(row)
        spin.valueChanged.connect(lambda v: (setter(v), self.value_changed.emit()))
        lay.addWidget(frame)

    def _texture_slots(self, lay, material):
        if not self._doc:
            return
        refs = available_texture_refs(self._doc)
        ref_labels = [r.name or r.file_path for r in refs]
        for group_idx, slot_idx, texture_chunk, resolved in material_texture_refs(material, self._doc):
            frame, body = self._group_frame(f"{ui_text('ui_model_viewer_texture_slot')} {group_idx}:{slot_idx}")
            row = QWidget()
            row.setStyleSheet(ss_transparent())
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(6)
            combo = QComboBox()
            combo.setStyleSheet(ss_inspector_input())
            combo.setFixedHeight(26)
            combo.setMinimumContentsLength(0)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            combo.addItems(ref_labels)
            current = getattr(texture_chunk, "name", "")
            if current in ref_labels:
                combo.setCurrentText(current)
            combo.currentIndexChanged.connect(
                lambda idx, g=group_idx, s=slot_idx: self._set_texture_slot(material, g, s, refs[idx])
            )
            row_lay.addWidget(combo, 1)
            if isinstance(resolved, MissingTextureRef):
                badge = QLabel(ui_text("ui_model_viewer_missing"))
                badge.setFixedHeight(22)
                badge.setStyleSheet(ss_badge_missing())
                row_lay.addWidget(badge)
            body.addWidget(row)
            lay.addWidget(frame)

    def _group_frame(self, title: str):
        frame = QFrame()
        frame.setObjectName("ModelInspectorCard")
        frame.setStyleSheet(ss_inspector_group())
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_panel_title())
        lbl.setWordWrap(True)
        outer.addWidget(lbl)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        outer.addLayout(body)
        return frame, body

    def _double_spin(self, value, minimum=-10000.0, maximum=10000.0):
        spin = QDoubleSpinBox()
        spin.setDecimals(5)
        spin.setRange(minimum, maximum)
        spin.setValue(float(value))
        spin.setSingleStep(0.1)
        spin.setFixedHeight(26)
        spin.setStyleSheet(ss_inspector_input())
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


class _ViewportPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._viewport = None
        self._controls = None
        self._cube = None
        self._axis = None
        self.setStyleSheet(ss_viewport_panel())
        self.setMinimumSize(260, 220)

    def set_viewport(self, widget: QWidget):
        self._viewport = widget
        widget.setParent(self)
        widget.lower()
        self._relayout()

    def set_controls(self, widget: QWidget):
        self._controls = widget
        widget.setParent(self)
        widget.raise_()
        self._relayout()

    def set_view_cube(self, widget: QWidget):
        self._cube = widget
        widget.setParent(self)
        widget.raise_()
        self._relayout()

    def set_axis_gizmo(self, widget: QWidget):
        self._axis = widget
        widget.setParent(self)
        widget.raise_()
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        w = self.width()
        h = self.height()
        if self._viewport:
            self._viewport.setGeometry(1, 1, max(1, w - 2), max(1, h - 2))
        margin = 12
        cube_visible = bool(self._cube and w >= 360 and h >= 230)
        axis_visible = bool(self._axis and w >= 280 and h >= 230)
        if self._cube:
            self._cube.setVisible(cube_visible)
            if cube_visible:
                self._cube.move(w - self._cube.width() - margin, margin)
                self._cube.raise_()
        if self._controls:
            reserved = (self._cube.width() + margin) if cube_visible and self._cube else 0
            available = max(96, w - reserved - margin * 2)
            self._controls.set_available_width(available)
            self._controls.move(margin, margin)
            self._controls.raise_()
        if self._axis:
            self._axis.setVisible(axis_visible)
            if axis_visible:
                self._axis.move(margin, h - self._axis.height() - margin)
                self._axis.raise_()


class _ViewportControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._labels: dict[QPushButton, str] = {}
        self._icons: dict[QPushButton, str] = {}
        self._compact = False
        self._columns = 1
        self._lay = QGridLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setHorizontalSpacing(6)
        self._lay.setVerticalSpacing(6)
        self.setStyleSheet(ss_transparent())

    def add_toggle(self, text: str, checked: bool, icon_name: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setFont(QFont("Segoe UI", 9))
        btn.setIcon(_themed_icon(icon_name, color=P.get("button_text", P["text_main"]), size=14))
        btn.setIconSize(QSize(14, 14))
        btn.setStyleSheet(ss_toggle_btn())
        btn.setToolTip(text)
        self._buttons.append(btn)
        self._labels[btn] = text
        self._icons[btn] = icon_name
        self._relayout_buttons()
        return btn

    def set_available_width(self, width: int):
        compact = width < 450
        button_w = 38 if compact else 96
        columns = max(1, min(len(self._buttons), width // (button_w + 6)))
        if compact != self._compact or columns != self._columns:
            self._compact = compact
            self._columns = columns
            for btn in self._buttons:
                btn.setText("" if compact else self._labels[btn])
                btn.setFixedSize(button_w, 32)
                btn.setIcon(_themed_icon(self._icons[btn], color=P.get("button_text", P["text_main"]), size=14))
            self._relayout_buttons()
        rows = math.ceil(max(1, len(self._buttons)) / max(1, self._columns))
        self.setFixedSize(min(width, self._columns * button_w + max(0, self._columns - 1) * 6), rows * 32 + max(0, rows - 1) * 6)

    def _relayout_buttons(self):
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().setParent(self)
        for idx, btn in enumerate(self._buttons):
            row = idx // max(1, self._columns)
            col = idx % max(1, self._columns)
            self._lay.addWidget(btn, row, col)


class _ViewCubeWidget(QWidget):
    view_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = ""
        self._faces = {}
        self.setFixedSize(94, 94)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        panel = QColor(P.get("panel_card_bg", P["bg_panel"]))
        panel.setAlpha(190)
        border = QColor(P.get("panel_card_border", P["border"]))
        painter.setPen(QPen(border, 1))
        painter.setBrush(QBrush(panel))
        painter.drawRoundedRect(QRectF(7, 7, 80, 80), 6, 6)

        top = QPolygonF([QPointF(24, 34), QPointF(46, 20), QPointF(70, 32), QPointF(46, 45)])
        front = QPolygonF([QPointF(24, 34), QPointF(46, 45), QPointF(46, 72), QPointF(24, 58)])
        right = QPolygonF([QPointF(46, 45), QPointF(70, 32), QPointF(70, 58), QPointF(46, 72)])
        self._faces = {"top": top, "front": front, "right": right}
        fill_a = QColor(P.get("bg_card_hov", P["mid"]))
        fill_b = QColor(P.get("mid", P["bg_panel"]))
        fill_c = QColor(P.get("input_bg", P["bg_card"]))
        for name, poly, color in (("top", top, fill_a), ("right", right, fill_b), ("front", front, fill_c)):
            if self._hover == name:
                color = QColor(P.get("selection_bg", P["accent"]))
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(border, 1))
            painter.drawPolygon(poly)

        painter.setPen(QColor(P["text_main"]))
        font = QFont("Segoe UI", 6, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(QRectF(32, 28, 28, 12), Qt.AlignmentFlag.AlignCenter, ui_text("ui_model_viewer_view_top"))
        painter.drawText(QRectF(22, 48, 25, 12), Qt.AlignmentFlag.AlignCenter, ui_text("ui_model_viewer_view_front"))
        painter.drawText(QRectF(47, 46, 26, 12), Qt.AlignmentFlag.AlignCenter, ui_text("ui_model_viewer_view_right"))
        painter.end()

    def mousePressEvent(self, event):
        self.view_requested.emit(self._face_at(event.position()) or "iso")

    def mouseDoubleClickEvent(self, event):
        self.view_requested.emit("iso")

    def mouseMoveEvent(self, event):
        face = self._face_at(event.position())
        if face != self._hover:
            self._hover = face
            self.update()

    def leaveEvent(self, event):
        self._hover = ""
        self.update()

    def _face_at(self, point: QPointF) -> str:
        for name, poly in self._faces.items():
            if poly.containsPoint(point, Qt.FillRule.OddEvenFill):
                return name
        return ""


class _AxisGizmoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._yaw = 25.0
        self._pitch = 20.0
        self.setFixedSize(92, 76)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_camera(self, yaw: float, pitch: float):
        self._yaw = yaw
        self._pitch = pitch
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        origin = QPointF(self.width() * 0.42, self.height() * 0.62)
        axes = [
            ("z", (0.0, 0.0, 1.0), P.get("info", P["text_sec"]), ui_text("ui_model_viewer_axis_z")),
            ("x", (1.0, 0.0, 0.0), P["accent"], ui_text("ui_model_viewer_axis_x")),
            ("y", (0.0, 1.0, 0.0), P.get("success", P["secondary"]), ui_text("ui_model_viewer_axis_y")),
        ]
        projected = [(self._project_axis(axis), color, label) for _, axis, color, label in axes]
        for end, color, label in projected:
            self._arrow(painter, origin, end, color, label)
        painter.end()

    def _project_axis(self, axis: tuple[float, float, float]) -> QPointF:
        yaw = math.radians(self._yaw)
        pitch = math.radians(self._pitch)
        x, y, z = axis
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        vx = cy * x + sy * z
        vz = -sy * x + cy * z
        vy = cp * y - sp * vz
        scale = 28.0
        origin = QPointF(self.width() * 0.42, self.height() * 0.62)
        return QPointF(origin.x() + vx * scale, origin.y() - vy * scale)

    def _arrow(self, painter: QPainter, start: QPointF, end: QPointF, color_value: str, label: str):
        color = QColor(color_value)
        painter.setPen(QPen(color, 2))
        painter.drawLine(start, end)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        left = QPointF(end.x() - ux * 8 - uy * 4, end.y() - uy * 8 + ux * 4)
        right = QPointF(end.x() - ux * 8 + uy * 4, end.y() - uy * 8 - ux * 4)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([end, left, right]))
        painter.setPen(color)
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(end.x() - 6, end.y() - 18, 18, 14), Qt.AlignmentFlag.AlignCenter, label)


class _ModelOpenGLViewport(QOpenGLWidget):
    camera_changed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene: RenderScene | None = None
        self._selected = None
        self._textures = {}
        self._mesh_lists = {}
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
        self._mesh_lists.clear()
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
        self.camera_changed.emit(self._yaw, self._pitch)

    def set_camera_view(self, view: str):
        presets = {
            "iso": (25.0, 20.0),
            "front": (0.0, 0.0),
            "right": (90.0, 0.0),
            "top": (0.0, 89.0),
        }
        self._yaw, self._pitch = presets.get(view, presets["iso"])
        self.update()
        self.camera_changed.emit(self._yaw, self._pitch)

    def initializeGL(self):
        try:
            from OpenGL import GL
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glShadeModel(GL.GL_SMOOTH)
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
        GL.glUseProgram(0)
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
        use_vertex_colors = mesh.colors is not None and not textured and not selected and not isinstance(mesh.texture, MissingTextureRef)
        GL.glCallList(self._mesh_list(GL, mesh, use_texcoords=textured, use_vertex_colors=use_vertex_colors))
        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
        GL.glDisable(GL.GL_TEXTURE_2D)

    def _mesh_list(self, GL, mesh, *, use_texcoords: bool, use_vertex_colors: bool):
        key = (id(mesh), use_texcoords, use_vertex_colors)
        list_id = self._mesh_lists.get(key)
        if list_id:
            return list_id
        list_id = GL.glGenLists(1)
        GL.glNewList(list_id, GL.GL_COMPILE)
        GL.glBegin(GL.GL_TRIANGLES)
        for face in mesh.faces:
            for idx in face:
                if use_texcoords and mesh.uvs is not None:
                    GL.glTexCoord2f(float(mesh.uvs[idx][0]), float(mesh.uvs[idx][1]))
                if mesh.normals is not None:
                    GL.glNormal3f(float(mesh.normals[idx][0]), float(mesh.normals[idx][1]), float(mesh.normals[idx][2]))
                if use_vertex_colors:
                    GL.glColor4f(float(mesh.colors[idx][0]), float(mesh.colors[idx][1]), float(mesh.colors[idx][2]), float(mesh.colors[idx][3]))
                v = mesh.vertices[idx]
                GL.glVertex3f(float(v[0]), float(v[1]), float(v[2]))
        GL.glEnd()
        GL.glEndList()
        self._mesh_lists[key] = list_id
        return list_id

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
        color = QColor(P.get("border", P["mid"]))
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
        color = QColor(P["accent"])
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
        color = QColor(P.get("secondary", P["text_sec"]))
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
            self.camera_changed.emit(self._yaw, self._pitch)
        elif event.buttons() & Qt.MouseButton.RightButton:
            self._center[0] -= delta.x() * self._distance * 0.002
            self._center[1] += delta.y() * self._distance * 0.002
        self.update()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self._distance *= math.pow(0.88, steps)
        self._distance = max(5.0, min(20000.0, self._distance))
        self.update()
