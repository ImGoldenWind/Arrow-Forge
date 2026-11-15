from __future__ import annotations

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    ss_badge_missing,
    ss_bg_dark,
    ss_bg_panel,
    ss_dialog,
    ss_dim_label,
    ss_field_label,
    ss_inspector_group,
    ss_main_label,
    ss_panel_title,
    ss_placeholder,
    ss_sidebar_treewidget,
    ss_tab_widget,
    ss_transparent,
    ss_viewport_panel,
)
from core.ui.editor_widgets import (
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
from editors.model_viewer_forms import ModelInspector as _InspectorPanel
from dataclasses import dataclass
import fnmatch
import math
import os
import re
import time

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, QSize, QTimer, QThreadPool, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTabWidget, QTextEdit,
    QToolTip, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.icons import _themed_icon
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.themes import P
from core.translations import ui_text
from parsers.model_xfbin_parser import (
    AnimationClip, MissingTextureRef, ModelXfbinDocument, RenderScene, ResolvedTextureRef,
    add_texture_xfbin, available_texture_refs,
    apply_animation, build_render_scene, load_animation_clips, load_model_xfbin, material_texture_refs,
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
        self.disable_file_compare = True
        self._doc: ModelXfbinDocument | None = None
        self._scene: RenderScene | None = None
        self._original_scene = None
        self._load_generation = 0
        self._load_job = None
        self._pending_load = None
        self._load_keep_camera = False
        self._busy = False
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(100)
        self._rebuild_timer.timeout.connect(lambda: self._rebuild_scene(keep_camera=True))
        self._selected = None
        self._dirty = False
        self._building_inspector = False
        self._building_model_controls = False
        self._model_variants: list[_CharacterModelVariant] = []
        self._current_variant_index = -1
        self._current_palette_index = -1
        self._compact_layout = None
        self._animation_clips: list[AnimationClip] = []
        self._animation_playhead = 0.0
        self._last_animation_tick = 0.0
        self._animation_timer = QTimer(self)
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        # One evaluation per display frame; the wall-clock playhead below keeps
        # the clip at 60 FPS without evaluating CPU skinning twice per refresh.
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._advance_animation)
        self.setStyleSheet(ss_bg_dark())
        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        toolbar = EditorToolbar()


        toolbar_lay = toolbar.content_layout


        self._toolbar_buttons = []

        self._open_btn = self._tool_btn("ui_model_viewer_open_model", accent=True)
        self._open_btn.clicked.connect(self._open_model_dialog)
        self._open_btn.setProperty("designAction", 'open')
        toolbar_lay.addWidget(self._open_btn)

        self._save_btn = self._tool_btn("ui_model_viewer_save", accent=True)
        self._save_btn.clicked.connect(self._save_file)
        self._save_btn.setEnabled(False)
        toolbar_lay.addWidget(self._save_btn)

        self._add_tex_btn = self._tool_btn("ui_model_viewer_add_textures")
        self._add_tex_btn.clicked.connect(self._add_texture_dialog)
        self._add_tex_btn.setProperty("designAction", 'new')
        self._add_tex_btn.setEnabled(False)
        toolbar_lay.addWidget(self._add_tex_btn)

        self._model_lbl = QLabel(self.t("ui_model_viewer_model_variant"))
        self._model_lbl.setStyleSheet(ss_dim_label())
        toolbar_lay.addWidget(self._model_lbl)
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(150)
        self._model_combo.setMaximumWidth(220)
        self._model_combo.setEnabled(False)
        configure_input(self._model_combo)
        self._model_combo.currentIndexChanged.connect(self._on_model_variant_changed)
        toolbar_lay.addWidget(self._model_combo)

        self._palette_lbl = QLabel(self.t("ui_model_viewer_color_scheme"))
        self._palette_lbl.setStyleSheet(ss_dim_label())
        toolbar_lay.addWidget(self._palette_lbl)
        self._palette_combo = QComboBox()
        self._palette_combo.setMinimumWidth(110)
        self._palette_combo.setMaximumWidth(150)
        self._palette_combo.setEnabled(False)
        configure_input(self._palette_combo)
        self._palette_combo.currentIndexChanged.connect(self._on_palette_changed)
        toolbar_lay.addWidget(self._palette_combo)

        toolbar_lay.addStretch()

        self._compare_btn = QPushButton(self.t("model_show_original"))
        configure_button(self._compare_btn, toggle=True)
        self._compare_btn.setCheckable(True)
        self._compare_btn.setEnabled(False)
        self._compare_btn.setToolTip(self.t("model_original_hint"))
        self._compare_btn.toggled.connect(self._show_comparison)
        toolbar_lay.addWidget(self._compare_btn)

        self._snapshot_btn = self._tool_btn("ui_model_viewer_snapshot")
        self._snapshot_btn.clicked.connect(self._export_snapshot)
        self._snapshot_btn.setEnabled(False)
        toolbar_lay.addWidget(self._snapshot_btn)

        self._file_lbl = QLabel()
        self._file_lbl.setFont(ui_font(TypeSize.BODY))
        set_file_label_empty(self._file_lbl, self.t("no_file_loaded"))
        self._file_lbl.hide()
        root.addWidget(toolbar)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QHBoxLayout()
        configure_layout(main, LayoutRole.ROOT)
        root.addLayout(main, 1)

        self._sidebar = _ModelSidebar(self)
        self._sidebar.selection_changed.connect(self._on_sidebar_selection)
        main.addWidget(self._sidebar, 0)

        left_divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main.addWidget(left_divider)

        center = QWidget()
        self._center_panel = center
        center.setStyleSheet(ss_bg_dark())
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 8)
        center_lay.setSpacing(Size.GAP)

        self._viewport_frame = _ViewportPanel()
        from editors.model_viewer_viewport import ModelViewport
        self._viewport = ModelViewport()
        self._viewport.rendering_issue.connect(self._rendering_issue)
        self._viewport.object_picked.connect(self._select_object)
        self._viewport.bone_picked.connect(self._select_bone)
        self._viewport.setToolTip(self.t('model_navigation_hint'))
        self._viewport_frame.set_viewport(self._viewport)

        self._reset_camera_btn = self._tool_btn("ui_model_viewer_reset_camera")
        self._reset_camera_btn.clicked.connect(self._reset_camera)
        self._reset_camera_btn.setEnabled(False)
        self._viewport_frame.set_reset_button(self._reset_camera_btn)

        self._view_controls = _ViewportControls()
        self._toggle_textured = self._view_controls.add_toggle(self.t("ui_model_viewer_textured"), True, "fa6s.image")
        self._toggle_wire = self._view_controls.add_toggle(self.t("ui_model_viewer_wireframe"), False, "fa6s.border-all")
        self._toggle_bones = self._view_controls.add_toggle(self.t("ui_model_viewer_bones"), False, "fa6s.bone")
        self._toggle_bounds = self._view_controls.add_toggle(self.t("ui_model_viewer_bounds"), True, "fa6s.cube")
        self._toggle_grid = self._view_controls.add_toggle(self.t("ui_model_viewer_grid"), True, "fa6s.table-cells")
        self._toggle_cull = self._view_controls.add_toggle(self.t("ui_model_viewer_culling"), False, "fa6s.eye-slash")
        self._toggle_cull.setToolTip(self.t('model_force_culling_hint'))
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

        self._animation_bar = self._build_animation_bar(center)
        self._animation_bar.hide()
        center_lay.addWidget(self._animation_bar)

        self._empty_hint_card, empty_hint_lay = make_editor_card(center)
        add_editor_card_title(empty_hint_lay, self.t('ui_model_viewer_no_model_loaded'), 'fa6s.cube', self.t('ui_model_viewer_open_a_model_to_begin'))
        center_lay.addWidget(self._empty_hint_card)

        self._status_lbl = QLabel(self.t("ui_model_viewer_open_a_model_to_begin"))
        self._status_lbl.setFont(ui_font(TypeSize.HINT))
        self._status_lbl.setStyleSheet(ss_dim_label())
        self._status_lbl.hide()
        center_lay.addWidget(self._status_lbl)
        main.addWidget(center, 1)

        right_divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main.addWidget(right_divider)

        self._inspector = _InspectorPanel(self)
        self._inspector.value_changed.connect(self._on_value_changed)
        self._inspector.draft_changed.connect(self._mark_dirty)
        self._inspector.object_requested.connect(self._select_object)
        main.addWidget(self._inspector, 0)
        self._apply_responsive_layout()

    def _build_animation_bar(self, parent):
        bar = QFrame(parent)
        bar.setStyleSheet(ss_bg_panel())
        outer = configure_layout(QVBoxLayout(bar), LayoutRole.PAGE)
        lighting = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        outer.addLayout(lighting)
        self._lighting_combo = configure_input(QComboBox())
        self._lighting_combo.setMinimumContentsLength(3)
        self._lighting_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._lighting_combo.addItem(self.t('model_neutral_light'), None)
        self._lighting_combo.setToolTip(self.t('model_lighting_hint'))
        self._lighting_combo.currentIndexChanged.connect(self._update_lighting)
        lighting.addWidget(self._lighting_combo, 1)
        self._lighting_mode = configure_input(QComboBox())
        self._lighting_mode.setMinimumContentsLength(2)
        self._lighting_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for key, value in (('stage_preview_light_normal', (0., 1)), ('stage_preview_light_alternate', (1., 1)), ('stage_preview_light_group2', (0., 2))):
            self._lighting_mode.addItem(self.t(key), value)
        self._lighting_mode.currentIndexChanged.connect(self._update_lighting)
        self._lighting_mode.setToolTip(self.t('stage_preview_lighting'))
        lighting.addWidget(self._lighting_mode, 1)
        light_open = configure_button(QPushButton())
        light_open.setIcon(_themed_icon('fa6s.lightbulb', color=P.get('button_text', P['text_main']), size=14))
        light_open.setFixedWidth(34)
        light_open.setToolTip(self.t('model_open_lighting'))
        light_open.clicked.connect(self._open_lighting)
        lighting.addWidget(light_open)
        layout = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        outer.addLayout(layout)
        label = QLabel(self.t("ui_model_viewer_animation"))
        label.setStyleSheet(ss_dim_label())
        self._animation_combo = QComboBox()
        self._animation_combo.setToolTip(self.t("ui_model_viewer_animation"))
        self._animation_combo.setMinimumWidth(80)
        self._animation_combo.setEditable(True)
        self._animation_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        configure_input(self._animation_combo)
        self._animation_combo.currentIndexChanged.connect(self._on_animation_changed)
        layout.addWidget(self._animation_combo, 1)
        self._animation_open_btn = QPushButton()
        self._animation_open_btn.setIcon(_themed_icon("fa6s.folder-open", color=P.get("button_text", P["text_main"]), size=14))
        self._animation_open_btn.setToolTip(self.t("ui_model_viewer_open_animation"))
        self._animation_open_btn.setFixedSize(34, 30)
        configure_button(self._animation_open_btn)
        self._animation_open_btn.clicked.connect(self._open_animation_dialog)
        layout.addWidget(self._animation_open_btn)
        layout = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        outer.addLayout(layout)
        self._animation_play_btn = QPushButton()
        self._animation_play_btn.setCheckable(True)
        self._animation_play_btn.setIcon(_themed_icon("fa6s.play", color=P.get("button_text", P["text_main"]), size=14))
        self._animation_play_btn.setToolTip(self.t("ui_model_viewer_play_animation"))
        self._animation_play_btn.setFixedSize(34, 30)
        configure_button(self._animation_play_btn, toggle=True)
        self._animation_play_btn.toggled.connect(self._toggle_animation_playback)
        layout.addWidget(self._animation_play_btn)
        self._animation_loop = QCheckBox(self.t("ui_model_viewer_loop_animation"))
        self._animation_loop.setToolTip(self.t("ui_model_viewer_loop_animation_tooltip"))
        layout.addWidget(self._animation_loop)
        layout.addStretch()
        self._animation_frame = configure_input(QSpinBox())
        self._animation_frame.setKeyboardTracking(False)
        self._animation_frame.setMaximumWidth(100)
        self._animation_frame.valueChanged.connect(self._on_animation_frame_changed)
        layout.addWidget(self._animation_frame)
        layout = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        outer.addLayout(layout)
        self._animation_slider = QSlider(Qt.Orientation.Horizontal)
        from core.style_helpers import ss_slider
        self._animation_slider.setStyleSheet(ss_slider())
        self._animation_slider.setRange(0, 0)
        self._animation_slider.valueChanged.connect(self._on_animation_frame_changed)
        layout.addWidget(self._animation_slider, 1)
        self._animation_frame_lbl = QLabel("0 / 0")
        self._animation_frame_lbl.setMinimumWidth(72)
        self._animation_frame_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._animation_frame_lbl.setStyleSheet(ss_dim_label())
        layout.addWidget(self._animation_frame_lbl)
        return bar

    def _tool_btn(self, key: str, accent: bool = False) -> QPushButton:
        text = self.t(key)
        btn = QPushButton(text)
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
        configure_button(btn, accent=accent)
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

    def hideEvent(self, event):
        self._stop_animation()
        super().hideEvent(event)

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
        self._stop_animation()
        self._rebuild_timer.stop()
        variant = self._model_variants[self._current_variant_index]
        _, texture_paths = self._current_variant_paths()
        self._load_generation += 1
        self._pending_load = (self._load_generation, variant.path, texture_paths,
                              self._animation_paths_for_variant(variant), keep_camera)
        self._set_status(self.t('model_loading'))
        self._busy = True
        self._set_controls_enabled(False)
        self._sidebar.setEnabled(False)
        self._inspector.setEnabled(False)
        self._start_pending_load()

    def _start_pending_load(self):
        if self._load_job is not None or self._pending_load is None:
            return
        from editors.model_viewer_loader import ModelLoadJob
        generation, path, textures, animations, keep_camera = self._pending_load
        self._pending_load = None
        create_backup_on_open(path)
        job = ModelLoadJob(generation, path, textures, animations)
        self._load_keep_camera = keep_camera
        job.signals.finished.connect(self._load_finished)
        self._load_job = job
        QThreadPool.globalInstance().start(job)

    def _load_finished(self, generation, result, error):
        self._load_job = None
        if generation != self._load_generation:
            self._start_pending_load()
            return
        self._busy = False
        self._sidebar.setEnabled(True)
        self._inspector.setEnabled(True)
        if error:
            self._set_controls_enabled(self._doc is not None)
            self._set_status(self.t('model_load_failed', error=self.t(error)))
            # The preceding document and its scene remain usable.
            if self._doc:
                self._model_variants = self._discover_model_variants(self._doc.path)
                self._current_variant_index = self._variant_index_for_path(self._doc.path)
                self._populate_model_controls()
            return
        self._doc, self._scene, clips, warning = result
        self._original_scene = self._scene
        self._dirty = False
        self._selected = None
        self._compare_btn.setChecked(False)
        self._set_animation_clips(clips)
        self._populate_lighting(getattr(self._doc, 'preview_lighting', []))
        self._viewport.set_scene(self._scene, reset_camera=not self._load_keep_camera)
        self._empty_hint_card.hide()
        self._sidebar.load(self._doc)
        self._inspector.set_context(self._doc, None)
        self._update_file_state()
        self._set_controls_enabled(True)
        self._sync_view_toggles()
        self._set_status(self.t('ui_model_viewer_animation_load_failed', p0=warning) if warning else self._summary_text())
        if not self._load_keep_camera:
            QTimer.singleShot(0, self._viewport.reset_camera)

    def _rendering_issue(self, error):
        self._set_status(self.t('model_render_failed'))
        self._status_lbl.setToolTip(error)
        self._stop_animation()

    def _populate_lighting(self, choices):
        previous = self._lighting_combo.currentText()
        self._lighting_combo.blockSignals(True)
        self._lighting_combo.clear()
        self._lighting_combo.addItem(self.t('model_neutral_light'), None)
        for code, params, path in choices:
            self._lighting_combo.addItem(code, params)
            self._lighting_combo.setItemData(self._lighting_combo.count()-1, path, Qt.ItemDataRole.ToolTipRole)
        index = self._lighting_combo.findText(previous)
        # Prefer an actual authored environment when one is available.
        self._lighting_combo.setCurrentIndex(index if index > 0 else (1 if choices else 0))
        self._lighting_combo.blockSignals(False)
        self._update_lighting()

    def _update_lighting(self, _index=0):
        self._viewport.set_stage_parameters(self._lighting_combo.currentData())
        self._viewport.set_lighting_reference(*self._lighting_mode.currentData())
        self._lighting_mode.setEnabled(self._lighting_combo.currentData() is not None)

    def _open_lighting(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t('model_open_lighting'), self._model_open_dir(), 'StageInfo (*.xfbin)')
        if path:
            try:
                from core.model_viewer_tools import model_lighting
                choices = model_lighting(path)
                if not choices:
                    raise ValueError(self.t('model_no_lighting'))
                self._populate_lighting(choices)
            except Exception as error:
                self._set_status(self.t('model_load_failed', error=str(error)))

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
        from core.stage_tools import data_root
        root = data_root(model_path)
        if root is not None:
            candidates.append(str(root / 'spc' / '0cmn01bod1.xfbin'))
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

    def _save_file(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not self._doc or self._busy or not self._inspector.commit():
            return
        try:
            save_model_xfbin(self._doc, save_path)
            commit_save_path(self, save_path)
            self._dirty = False
            self._update_file_state()
            self._set_status(self.t('ui_model_viewer_saved'))
        except Exception as exc:
            QMessageBox.critical(self, self.t('dlg_title_error'), self.t(str(exc)))

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
        if not self._viewport.grabFramebuffer().save(path):
            self._set_status(self.t("model_snapshot_failed"))
            return
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
        if obj is self._selected:
            return
        if not self._inspector.commit():
            self._sidebar.select_object(self._selected)
            return
        self._selected = obj
        self._inspector.set_context(self._doc, obj)
        self._viewport.set_selected(obj)

    def _select_object(self, obj):
        self._sidebar.select_object(obj)

    def _select_bone(self, name):
        if self._doc:
            coord = next((coord for coord in self._doc.coord_chunks if coord.node.name == name), None)
            if coord is not None:
                self._select_object(coord)

    def _show_comparison(self, checked=False, reset_camera=False):
        scene = self._original_scene if self._compare_btn.isChecked() else self._scene
        if scene is not None:
            apply_animation(scene, self._current_animation(), self._animation_playhead, skin_meshes=True)
            self._viewport.set_scene(scene, reset_camera=reset_camera)

    def _on_value_changed(self):
        if self._building_inspector:
            return
        self._mark_dirty()
        self._rebuild_timer.start()
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
        try:
            self._scene = build_render_scene(self._doc)
        except (ValueError, IndexError, np.linalg.LinAlgError) as error:
            self._set_status(self.t('model_preview_failed', error=str(error)))
            return
        self._show_comparison(reset_camera=not keep_camera)
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
        self._compare_btn.setEnabled(enabled)
        self._reset_camera_btn.setEnabled(enabled)
        self._animation_bar.setEnabled(enabled)
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

    def _animation_paths_for_variant(self, variant: _CharacterModelVariant) -> list[str]:
        folder = os.path.dirname(variant.path)
        candidates = []
        animation_code = self._animation_owner_code(variant)
        try:
            filenames = sorted(os.listdir(folder))
        except OSError:
            return []
        for filename in filenames:
            lowered = filename.lower()
            if lowered.startswith(animation_code.lower()) and "mot" in lowered and lowered.endswith(".xfbin"):
                candidates.append(os.path.join(folder, filename))
        return self._unique_existing_paths(candidates)

    def _animation_owner_code(self, variant: _CharacterModelVariant) -> str:
        match = re.match(r"^(?P<base>.*?)(?P<variant>\d)(?P<slot>\d)$", variant.code)
        if not match:
            return variant.code
        canonical = f"{match.group('base')}0{match.group('slot')}"
        canonical_model = os.path.join(os.path.dirname(variant.path), f"{canonical}bod1.xfbin")
        return canonical if os.path.isfile(canonical_model) else variant.code

    def _set_animation_clips(self, clips: list[AnimationClip]):
        previous_name = self._current_animation().name if self._current_animation() else ""
        self._animation_clips = list(clips)
        self._animation_combo.blockSignals(True)
        self._animation_combo.clear()
        self._animation_combo.addItem(self.t("ui_model_viewer_bind_pose"))
        for clip in self._animation_clips:
            self._animation_combo.addItem(clip.name)
        index = next((i + 1 for i, clip in enumerate(self._animation_clips) if clip.name == previous_name), 0)
        self._animation_combo.setCurrentIndex(index)
        self._animation_combo.blockSignals(False)
        self._animation_bar.setVisible(bool(self._doc))
        self._animation_combo.setEnabled(bool(self._animation_clips))
        self._configure_animation_range()

    def _open_animation_dialog(self):
        if not self._doc:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.t("ui_model_viewer_open_animation"),
            os.path.dirname(self._doc.path),
            self.t("ui_model_viewer_xfbin_filter"),
        )
        if not paths:
            return
        try:
            clips = load_animation_clips(paths)
            self._set_animation_clips(clips)
            if clips:
                self._animation_combo.setCurrentIndex(1)
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(exc))

    def _current_animation(self) -> AnimationClip | None:
        index = self._animation_combo.currentIndex() if hasattr(self, "_animation_combo") else -1
        return self._animation_clips[index - 1] if 1 <= index <= len(self._animation_clips) else None

    def _configure_animation_range(self):
        clip = self._current_animation()
        maximum = clip.frame_count if clip else 0
        self._animation_slider.blockSignals(True)
        self._animation_slider.setRange(0, maximum)
        self._animation_frame.blockSignals(True)
        self._animation_frame.setRange(0, maximum)
        self._animation_frame.setValue(0)
        self._animation_frame.blockSignals(False)
        self._animation_slider.setValue(0)
        self._animation_slider.blockSignals(False)
        self._animation_frame_lbl.setText(f"0 / {maximum}")
        self._animation_play_btn.setEnabled(clip is not None)
        self._animation_playhead = 0.0
        self._animation_loop.blockSignals(True)
        self._animation_loop.setChecked(bool(clip and (clip.looped or clip.name.lower().endswith("_lp"))))
        self._animation_loop.blockSignals(False)

    def _on_animation_changed(self, _index: int):
        self._stop_animation()
        self._configure_animation_range()
        self._on_animation_frame_changed(0)

    def _on_animation_frame_changed(self, frame: int):
        self._set_animation_playhead(float(frame))

    def _render_animation_frame(self, frame: float):
        clip = self._current_animation()
        maximum = clip.frame_count if clip else 0
        frame_text = f"{frame:.1f}" if abs(frame - round(frame)) > 0.01 else str(int(round(frame)))
        self._animation_frame_lbl.setText(f"{frame_text} / {maximum}")
        scene = self._original_scene if self._compare_btn.isChecked() else self._scene
        if scene:
            apply_animation(
                scene,
                clip,
                frame,
                skin_meshes=not self._viewport.uses_gpu_skinning(),
            )
            self._viewport.geometry_changed()

    def _toggle_animation_playback(self, playing: bool):
        clip = self._current_animation()
        if playing and clip:
            if self._animation_playhead >= clip.frame_count - 1e-6:
                self._set_animation_playhead(0.0)
            self._animation_play_btn.setIcon(_themed_icon("fa6s.pause", color=P.get("button_text", P["text_main"]), size=14))
            self._last_animation_tick = time.perf_counter()
            self._animation_timer.start()
        else:
            self._animation_play_btn.setIcon(_themed_icon("fa6s.play", color=P.get("button_text", P["text_main"]), size=14))
            self._animation_timer.stop()

    def _stop_animation(self):
        self._animation_timer.stop()
        self._last_animation_tick = 0.0
        if hasattr(self, "_animation_play_btn"):
            self._animation_play_btn.blockSignals(True)
            self._animation_play_btn.setChecked(False)
            self._animation_play_btn.blockSignals(False)
            self._animation_play_btn.setIcon(_themed_icon("fa6s.play", color=P.get("button_text", P["text_main"]), size=14))

    def _advance_animation(self):
        clip = self._current_animation()
        if not clip:
            self._stop_animation()
            return
        now = time.perf_counter()
        elapsed = max(0.0, min(0.1, now - self._last_animation_tick)) if self._last_animation_tick else (1.0 / 60.0)
        self._last_animation_tick = now
        value = self._animation_playhead + elapsed * 60.0
        maximum = float(self._animation_slider.maximum())
        if value > maximum:
            if self._animation_loop.isChecked() and maximum > 0.0:
                value %= maximum
            else:
                self._set_animation_playhead(maximum)
                self._stop_animation()
                return
        self._set_animation_playhead(value)

    def _set_animation_playhead(self, value: float):
        self._animation_playhead = max(0.0, min(float(self._animation_slider.maximum()), float(value)))
        self._animation_slider.blockSignals(True)
        self._animation_slider.setValue(int(round(self._animation_playhead)))
        self._animation_slider.blockSignals(False)
        self._animation_frame.blockSignals(True)
        self._animation_frame.setValue(int(round(self._animation_playhead)))
        self._animation_frame.blockSignals(False)
        self._render_animation_frame(self._animation_playhead)

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

class _ModelSidebar(EditorSidebar):
    selection_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.set_panel_width(260)
        root = self.content_layout
        configure_layout(root, LayoutRole.SIDEBAR)

        search_row = QWidget()
        search_row.setStyleSheet(ss_transparent())
        search_lay = QHBoxLayout(search_row)
        search_lay.setContentsMargins(*Insets.NONE)
        search_lay.setSpacing(6)
        self._search = QLineEdit()
        configure_search(self._search)
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

    def select_object(self, obj):
        for i in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) is obj:
                    group.setExpanded(True)
                    self._tree.setCurrentItem(child)
                    self._tree.scrollToItem(child)
                    return

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


class _ViewportPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._viewport = None
        self._controls = None
        self._cube = None
        self._axis = None
        self._reset = None
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

    def set_reset_button(self, widget: QWidget):
        self._reset = widget
        widget.setParent(self)
        widget.setFixedWidth(widget.sizeHint().width())
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
        if self._reset:
            self._reset.move(
                w - self._reset.sizeHint().width() - margin,
                h - self._reset.height() - margin,
            )
            self._reset.raise_()


class _ViewportControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._labels: dict[QPushButton, str] = {}
        self._icons: dict[QPushButton, str] = {}
        self._compact = False
        self._columns = 1
        self._lay = QGridLayout(self)
        self._lay.setContentsMargins(*Insets.NONE)
        self._lay.setHorizontalSpacing(6)
        self._lay.setVerticalSpacing(6)
        self.setStyleSheet(ss_transparent())

    def add_toggle(self, text: str, checked: bool, icon_name: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setIcon(_themed_icon(icon_name, color=P.get("button_text", P["text_main"]), size=14))
        btn.setIconSize(QSize(14, 14))
        configure_button(btn, toggle=True)
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
                btn.setFixedSize(button_w, Size.CONTROL)
                btn.setIcon(_themed_icon(self._icons[btn], color=P.get("button_text", P["text_main"]), size=14))
            self._relayout_buttons()
        rows = math.ceil(max(1, len(self._buttons)) / max(1, self._columns))
        self.setFixedSize(min(width, self._columns * button_w + max(0, self._columns - 1) * 6), rows * Size.CONTROL + max(0, rows - 1) * 6)

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
        font = ui_font(TypeSize.MICRO, QFont.Weight.Bold)
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
        painter.setFont(ui_font(TypeSize.CAPTION, QFont.Weight.Bold))
        painter.drawText(QRectF(end.x() - 6, end.y() - 18, 18, 14), Qt.AlignmentFlag.AlignCenter, label)


class _ModelOpenGLViewport(QOpenGLWidget):
    camera_changed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene: RenderScene | None = None
        self._additional_scenes = []
        self._scene_transform = None
        self._selected = None
        self._textures = {}
        self._mesh_lists = {}
        self._shader_program = 0
        self._uniform_locations: dict[tuple[int, str], int] = {}
        self._attribute_locations: dict[tuple[int, str], int] = {}
        self._bone_matrix_texture = 0
        self._bone_texture_height = 0
        self._gpu_skinning_supported = False
        self._gpu_skinning_ready = False
        self._hovered_bone = ""
        self._bone_screen_segments: list[tuple[str, QPointF, QPointF]] = []
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
        self.setMouseTracking(True)

    def set_scene(self, scene: RenderScene, reset_camera: bool = True):
        self._scene = scene
        self._additional_scenes = []
        self._textures.clear()
        self._mesh_lists.clear()
        self._bone_texture_height = 0
        if reset_camera:
            self.reset_camera()
        self.update()

    def geometry_changed(self):
        # Geometry is submitted through client arrays, so animation updates do
        # not require rebuilding OpenGL display lists or GPU objects.
        self._mesh_lists.clear()
        self.update()

    def uses_gpu_skinning(self) -> bool:
        return bool(self._shader_program and self._gpu_skinning_supported)

    def set_scene_transform(self, matrix=None):
        """Transform the displayed model, bones and bounds while keeping the grid fixed."""
        self._scene_transform = matrix
        self.update()

    def set_additional_scenes(self, scenes):
        """Draw independent skeletons in the same viewport and camera."""
        self._additional_scenes = [(scene, matrix) for scene, matrix in scenes if scene is not None]
        self.update()

    def displayed_bounds(self):
        corners = []
        actors = [(self._scene, getattr(self, '_scene_transform', None)), *self._additional_scenes]
        for scene, matrix in actors:
            if scene is None:
                continue
            mn, mx = scene.bounds_min, scene.bounds_max
            points = np.array([[x, y, z, 1] for x in (mn[0], mx[0])
                               for y in (mn[1], mx[1]) for z in (mn[2], mx[2])], dtype=np.float64)
            if matrix is not None:
                points = points @ np.asarray(matrix).T
            if np.isfinite(points).all():
                corners.extend(points[:, :3])
        if not corners:
            return None
        points = np.array(corners)
        return points.min(axis=0), points.max(axis=0)

    def set_selected(self, obj):
        self._selected = obj
        self.update()

    def set_options(self, **options):
        self._options.update(options)
        if not self._options.get("bones"):
            self._hovered_bone = ""
            self._bone_screen_segments = []
            QToolTip.hideText()
        self.update()

    def reset_camera(self):
        bounds = self.displayed_bounds()
        if bounds is not None:
            mn, mx = bounds
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
            self._shader_program = self._create_asbr_shader(GL)
            self._gpu_skinning_supported = int(GL.glGetIntegerv(GL.GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS)) > 0
        except Exception:
            self._shader_program = 0
            self._gpu_skinning_supported = False

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

        self._clear_viewport(GL)
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
        primary = self._scene
        actors = [(primary, getattr(self, '_scene_transform', None)), *self._additional_scenes]
        try:
            for scene, transform in actors:
                if scene is None:
                    continue
                self._scene = scene
                GL.glPushMatrix()
                try:
                    if transform is not None:
                        GL.glMultMatrixf(np.asarray(transform, dtype=np.float32).T.copy())
                    # Upload this actor's palette before drawing its meshes.
                    self._prepare_gpu_skinning(GL)
                    for mesh in scene.meshes:
                        if mesh.visible:
                            self._draw_mesh(GL, mesh)
                    GL.glUseProgram(0)
                    if self._options['bones']:
                        self._draw_bones(GL)
                    if self._options['bounds']:
                        self._draw_bounds(GL)
                finally:
                    GL.glPopMatrix()
        finally:
            self._scene = primary

    def _clear_viewport(self, GL):
        bg = QColor(P.get("viewport_bg", P["bg_dark"]))
        GL.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

    def _draw_mesh(self, GL, mesh):
        selected = self._selected is mesh.model_chunk or self._selected is mesh.material_chunk
        textured = self._options["textured"] and isinstance(mesh.texture, ResolvedTextureRef) and mesh.texture.pil_image is not None
        if self._shader_program:
            self._draw_mesh_shaded(GL, mesh, textured, selected)
            return
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

    def _draw_mesh_shaded(self, GL, mesh, textured: bool, selected: bool):
        program = self._shader_program
        GL.glUseProgram(program)
        self._uniform_i(GL, program, "uTextured", int(textured))
        self._uniform_i(GL, program, "uSelected", int(selected))
        self._uniform_i(GL, program, "uWireframe", int(self._options["wireframe"]))
        self._uniform_i(GL, program, "uUseSkinning", int(self._gpu_skinning_ready))
        self._uniform_i(GL, program, "uBoneMatrices", 4)
        self._uniform_f(GL, program, "uBoneTextureHeight", float(max(1, len(self._scene.pose_world_matrices) if self._scene else 1)))

        detail = mesh.texture_slots.get("detail")
        normal = mesh.texture_slots.get("normal")
        secondary = detail if isinstance(detail, ResolvedTextureRef) else normal
        secondary_mode = 1 if isinstance(detail, ResolvedTextureRef) else (2 if isinstance(normal, ResolvedTextureRef) else 0)
        hatching = mesh.texture_slots.get("hatching")
        specular = mesh.texture_slots.get("specular") or mesh.texture_slots.get("mask")
        self._bind_shader_texture(GL, program, "uTex0", 0, mesh.texture if textured else None)
        self._bind_shader_texture(GL, program, "uTex1", 1, secondary if textured else None)
        self._bind_shader_texture(GL, program, "uHatching", 2, hatching if textured else None)
        self._bind_shader_texture(GL, program, "uSpecular", 3, specular if textured else None)
        self._uniform_i(GL, program, "uSecondaryMode", secondary_mode)
        hatching_mode = 1 if isinstance(hatching, ResolvedTextureRef) and textured else (2 if "NU_hatchingParam" in mesh.material_params else 0)
        self._uniform_i(GL, program, "uHasHatching", hatching_mode)
        self._uniform_i(GL, program, "uHasSpecular", int(isinstance(specular, ResolvedTextureRef) and textured))

        lighting = mesh.material_params.get("NU_lightingParam", (0.10,))
        hatching_param = mesh.material_params.get("NU_hatchingParam", (1.0,))
        specular_param = mesh.material_params.get("NU_specularParam", (1.0, 2.0))
        outline_param = mesh.material_params.get("NU_outline0Param", (0.15,))
        self._uniform_f(GL, program, "uToneOffset", float(lighting[0]) if lighting else 0.1)
        self._uniform_f(GL, program, "uHatchingStrength", min(1.0, max(0.0, float(hatching_param[0]) / 3.0)) if hatching_param else 0.35)
        self._uniform_f(GL, program, "uSpecularStrength", min(2.0, max(0.0, float(specular_param[0]) / 3.0)) if specular_param else 0.35)
        self._uniform_f(GL, program, "uSpecularPower", 10.0 + (float(specular_param[1]) * 7.0 if len(specular_param) > 1 else 14.0))

        self._enable_mesh_arrays(GL, mesh)
        outline_width = 0.06 + min(0.45, max(0.0, float(outline_param[0]) * 0.22 if outline_param else 0.08))
        if not self._options["wireframe"] and self._options.get('outlines', True):
            self._uniform_i(GL, program, "uOutlinePass", 1)
            self._uniform_f(GL, program, "uOutlineWidth", outline_width)
            GL.glEnable(GL.GL_CULL_FACE)
            GL.glCullFace(GL.GL_FRONT)
            self._draw_mesh_arrays(GL, mesh)

        self._uniform_i(GL, program, "uOutlinePass", 0)
        self._uniform_f(GL, program, "uOutlineWidth", 0.0)
        if self._options["culling"] or mesh.cull_mode in (1028, 1029):
            GL.glEnable(GL.GL_CULL_FACE)
            GL.glCullFace(GL.GL_BACK)
        else:
            GL.glDisable(GL.GL_CULL_FACE)
        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE if self._options["wireframe"] else GL.GL_FILL)
        self._draw_mesh_arrays(GL, mesh)
        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
        self._disable_mesh_arrays(GL)
        for unit in range(4):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glUseProgram(0)

    def _enable_mesh_arrays(self, GL, mesh):
        GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
        vertices = mesh.gpu_bind_vertices if self._gpu_skinning_ready else mesh.vertices
        normals = mesh.gpu_bind_normals if self._gpu_skinning_ready else mesh.normals
        GL.glVertexPointer(3, GL.GL_FLOAT, 0, np.ascontiguousarray(vertices, dtype=np.float32))
        if normals is not None:
            GL.glEnableClientState(GL.GL_NORMAL_ARRAY)
            GL.glNormalPointer(GL.GL_FLOAT, 0, np.ascontiguousarray(normals, dtype=np.float32))
        if mesh.uvs is not None:
            GL.glClientActiveTexture(GL.GL_TEXTURE0)
            GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
            GL.glTexCoordPointer(2, GL.GL_FLOAT, 0, np.ascontiguousarray(mesh.uvs, dtype=np.float32))
            GL.glClientActiveTexture(GL.GL_TEXTURE1)
            GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
            detail_uvs = mesh.uvs2 if mesh.uvs2 is not None else mesh.uvs
            GL.glTexCoordPointer(2, GL.GL_FLOAT, 0, np.ascontiguousarray(detail_uvs, dtype=np.float32))
        if mesh.colors is not None and mesh.colors.shape[1] >= 4:
            GL.glEnableClientState(GL.GL_COLOR_ARRAY)
            GL.glColorPointer(4, GL.GL_FLOAT, 0, np.ascontiguousarray(mesh.colors[:, :4], dtype=np.float32))
        else:
            GL.glColor4f(1.0, 1.0, 1.0, 1.0)
        if self._gpu_skinning_ready:
            for name, values in (
                ("aBoneIds", mesh.gpu_bone_ids),
                ("aBoneWeights", mesh.gpu_bone_weights),
            ):
                location = self._attribute_location(GL, self._shader_program, name)
                if location >= 0:
                    GL.glEnableVertexAttribArray(location)
                    GL.glVertexAttribPointer(location, 4, GL.GL_FLOAT, False, 0, values)

    def _disable_mesh_arrays(self, GL):
        GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
        GL.glDisableClientState(GL.GL_NORMAL_ARRAY)
        GL.glDisableClientState(GL.GL_COLOR_ARRAY)
        GL.glClientActiveTexture(GL.GL_TEXTURE1)
        GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
        GL.glClientActiveTexture(GL.GL_TEXTURE0)
        GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
        for name in ("aBoneIds", "aBoneWeights"):
            location = self._attribute_location(GL, self._shader_program, name) if self._shader_program else -1
            if location >= 0:
                GL.glDisableVertexAttribArray(location)

    def _draw_mesh_arrays(self, GL, mesh):
        faces = np.ascontiguousarray(mesh.faces, dtype=np.uint32)
        if faces.size:
            GL.glDrawElements(GL.GL_TRIANGLES, int(faces.size), GL.GL_UNSIGNED_INT, faces)

    def _bind_shader_texture(self, GL, program, uniform, unit, ref):
        GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
        if isinstance(ref, ResolvedTextureRef) and ref.pil_image is not None:
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture_id(GL, ref))
        else:
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        self._uniform_i(GL, program, uniform, unit)

    def _prepare_gpu_skinning(self, GL):
        self._gpu_skinning_ready = False
        if not (self._scene and self.uses_gpu_skinning() and self._scene.pose_world_matrices):
            return
        try:
            pose = np.stack(self._scene.pose_world_matrices).astype(np.float32, copy=False)
            inverse_bind = np.stack(self._scene.inverse_bind_matrices).astype(np.float32, copy=False)
            skin = np.matmul(pose, inverse_bind)
            conversion = np.array([
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, -1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ], dtype=np.float32)
            inverse_conversion = np.array([
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, -1.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ], dtype=np.float32)
            view_skin = np.matmul(np.matmul(conversion[None, :, :], skin), inverse_conversion[None, :, :])
            data = np.ascontiguousarray(view_skin, dtype=np.float32)
            if not self._bone_matrix_texture:
                self._bone_matrix_texture = GL.glGenTextures(1)
            GL.glActiveTexture(GL.GL_TEXTURE4)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._bone_matrix_texture)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            if self._bone_texture_height != len(data):
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA32F, 4, len(data), 0, GL.GL_RGBA, GL.GL_FLOAT, data)
                self._bone_texture_height = len(data)
            else:
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, 4, len(data), GL.GL_RGBA, GL.GL_FLOAT, data)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            self._gpu_skinning_ready = True
        except Exception:
            self._gpu_skinning_supported = False
            self._gpu_skinning_ready = False

    def _uniform_i(self, GL, program, name, value):
        location = self._uniform_location(GL, program, name)
        if location >= 0:
            GL.glUniform1i(location, int(value))

    def _uniform_f(self, GL, program, name, value):
        location = self._uniform_location(GL, program, name)
        if location >= 0:
            GL.glUniform1f(location, float(value))

    def _uniform_location(self, GL, program: int, name: str) -> int:
        key = (int(program), name)
        if key not in self._uniform_locations:
            self._uniform_locations[key] = int(GL.glGetUniformLocation(program, name))
        return self._uniform_locations[key]

    def _attribute_location(self, GL, program: int, name: str) -> int:
        key = (int(program), name)
        if key not in self._attribute_locations:
            self._attribute_locations[key] = int(GL.glGetAttribLocation(program, name))
        return self._attribute_locations[key]

    def _create_asbr_shader(self, GL):
        from OpenGL.GL import shaders
        vertex_source = r"""
            #version 120
            attribute vec4 aBoneIds;
            attribute vec4 aBoneWeights;
            uniform sampler2D uBoneMatrices;
            uniform float uBoneTextureHeight;
            uniform int uUseSkinning;
            uniform int uOutlinePass;
            uniform float uOutlineWidth;
            varying vec2 vUv;
            varying vec2 vUv1;
            varying vec4 vColor;
            varying vec3 vNormal;
            varying vec3 vView;
            varying vec3 vEyePos;
            mat4 boneMatrix(float boneIndex) {
                float y = (boneIndex + 0.5) / uBoneTextureHeight;
                vec4 r0 = texture2D(uBoneMatrices, vec2(0.125, y));
                vec4 r1 = texture2D(uBoneMatrices, vec2(0.375, y));
                vec4 r2 = texture2D(uBoneMatrices, vec2(0.625, y));
                vec4 r3 = texture2D(uBoneMatrices, vec2(0.875, y));
                return mat4(
                    r0.x, r1.x, r2.x, r3.x,
                    r0.y, r1.y, r2.y, r3.y,
                    r0.z, r1.z, r2.z, r3.z,
                    r0.w, r1.w, r2.w, r3.w
                );
            }
            void main() {
                mat4 skin = mat4(1.0);
                float totalWeight = dot(aBoneWeights, vec4(1.0));
                if (uUseSkinning == 1 && totalWeight > 0.0001) {
                    skin = boneMatrix(aBoneIds.x) * aBoneWeights.x
                         + boneMatrix(aBoneIds.y) * aBoneWeights.y
                         + boneMatrix(aBoneIds.z) * aBoneWeights.z
                         + boneMatrix(aBoneIds.w) * aBoneWeights.w;
                }
                vec4 position = skin * gl_Vertex;
                vec3 skinnedNormal = normalize(mat3(skin) * gl_Normal);
                if (uOutlinePass == 1) position.xyz += skinnedNormal * uOutlineWidth;
                vec4 eyePosition = gl_ModelViewMatrix * position;
                gl_Position = gl_ProjectionMatrix * eyePosition;
                vUv = gl_MultiTexCoord0.xy;
                vUv1 = gl_MultiTexCoord1.xy;
                vColor = gl_Color;
                vNormal = normalize(gl_NormalMatrix * skinnedNormal);
                vView = normalize(-eyePosition.xyz);
                vEyePos = eyePosition.xyz;
            }
        """
        fragment_source = r"""
            #version 120
            // Scene-specific uniforms
            uniform sampler2D uTex0;
            uniform sampler2D uTex1;
            uniform sampler2D uHatching;
            uniform sampler2D uSpecular;
            uniform int uTextured;
            uniform int uSelected;
            uniform int uOutlinePass;
            uniform int uSecondaryMode;
            uniform int uHasHatching;
            uniform int uHasSpecular;
            uniform float uToneOffset;
            uniform float uHatchingStrength;
            uniform float uSpecularStrength;
            uniform float uSpecularPower;
            varying vec2 vUv;
            varying vec2 vUv1;
            varying vec4 vColor;
            varying vec3 vNormal;
            varying vec3 vView;
            varying vec3 vEyePos;
            void main() {
                if (uOutlinePass == 1) {
                    gl_FragColor = vec4(0.018, 0.014, 0.025, 1.0);
                    return;
                }
                vec4 base = uTextured == 1 ? texture2D(uTex0, vUv) : vec4(0.62, 0.65, 0.72, 1.0);
                base *= vColor;
                if (uSecondaryMode == 1) {
                    vec4 detail = texture2D(uTex1, vUv1);
                    base.rgb = mix(base.rgb, detail.rgb, detail.a);
                }
                if (base.a < 0.035) discard;
                vec3 normal = normalize(vNormal);
                if (uSecondaryMode == 2) {
                    vec3 mapNormal = texture2D(uTex1, vUv).xyz * 2.0 - 1.0;
                    vec3 dp1 = dFdx(vEyePos);
                    vec3 dp2 = dFdy(vEyePos);
                    vec2 duv1 = dFdx(vUv);
                    vec2 duv2 = dFdy(vUv);
                    vec3 tangent = normalize(dp1 * duv2.y - dp2 * duv1.y);
                    vec3 bitangent = normalize(-dp1 * duv2.x + dp2 * duv1.x);
                    normal = normalize(mat3(tangent, bitangent, normal) * mapNormal);
                }
                vec3 lightDir = normalize(vec3(-0.38, 0.62, 0.69));
                float diffuse = dot(normal, lightDir) + uToneOffset;
                float midBand = smoothstep(-0.16, 0.02, diffuse);
                float lightBand = smoothstep(0.38, 0.52, diffuse);
                float toon = mix(0.42, 0.72, midBand) + 0.28 * lightBand;
                if (uHasHatching != 0) {
                    float hatch = texture2D(uHatching, vUv * 2.0).r;
                    if (uHasHatching == 2) {
                        vec2 pixel = gl_FragCoord.xy;
                        float phaseA = fract(dot(pixel, normalize(vec2(0.86, 0.52))) / 5.2);
                        float phaseB = fract(dot(pixel, normalize(vec2(-0.68, 0.73))) / 7.4);
                        float distanceA = min(phaseA, 1.0 - phaseA);
                        float distanceB = min(phaseB, 1.0 - phaseB);
                        float lineA = 1.0 - smoothstep(0.025, 0.085, distanceA);
                        float lineB = 1.0 - smoothstep(0.018, 0.068, distanceB);
                        float deepShadow = 1.0 - smoothstep(-0.18, 0.12, diffuse);
                        float ink = clamp(lineA * 0.72 + lineB * 0.48 * deepShadow, 0.0, 1.0);
                        hatch = 1.0 - ink;
                    }
                    toon *= mix(1.0, 0.58 + hatch * 0.42, uHatchingStrength * (1.0 - lightBand));
                }
                vec3 halfVector = normalize(lightDir + normalize(vView));
                float spec = pow(max(dot(normal, halfVector), 0.0), uSpecularPower) * uSpecularStrength;
                if (uHasSpecular == 1) spec *= texture2D(uSpecular, vUv).r;
                vec3 color = base.rgb * toon + vec3(spec);
                float rim = pow(1.0 - abs(dot(normal, normalize(vView))), 3.0);
                color *= 1.0 - rim * 0.22;
                // Scene-specific postprocess
                if (uSelected == 1) color = mix(color, vec3(0.36, 0.62, 1.0), 0.28);
                gl_FragColor = vec4(color, base.a);
            }
        """
        fragment_source = fragment_source.replace('// Scene-specific uniforms', self._scene_shader_uniforms())
        fragment_source = fragment_source.replace('// Scene-specific postprocess', self._scene_shader_postprocess())
        return shaders.compileProgram(
            shaders.compileShader(vertex_source, GL.GL_VERTEX_SHADER),
            shaders.compileShader(fragment_source, GL.GL_FRAGMENT_SHADER),
        )

    def _scene_shader_uniforms(self):
        """Optional scene effects; the ordinary model viewer keeps its shader."""
        return ''

    def _scene_shader_postprocess(self):
        return ''

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
        self._update_bone_screen_segments(GL)
        depth_enabled = bool(GL.glIsEnabled(GL.GL_DEPTH_TEST))
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_TEXTURE_2D)
        color = QColor(P["accent"])
        GL.glColor4f(color.redF(), color.greenF(), color.blueF(), 0.85)
        GL.glLineWidth(3.0)
        GL.glBegin(GL.GL_LINES)
        for name, start, end in self._scene.bones:
            if name == self._hovered_bone:
                continue
            GL.glVertex3f(*[float(x) for x in start])
            GL.glVertex3f(*[float(x) for x in end])
        GL.glEnd()
        GL.glPointSize(6.0)
        GL.glBegin(GL.GL_POINTS)
        for _, _, end in self._scene.bones:
            GL.glVertex3f(*[float(x) for x in end])
        GL.glEnd()
        if self._hovered_bone:
            highlight = QColor(P.get("warning", "#ffd166"))
            GL.glColor4f(highlight.redF(), highlight.greenF(), highlight.blueF(), 1.0)
            GL.glLineWidth(5.0)
            GL.glBegin(GL.GL_LINES)
            for name, start, end in self._scene.bones:
                if name == self._hovered_bone:
                    GL.glVertex3f(*[float(x) for x in start])
                    GL.glVertex3f(*[float(x) for x in end])
            GL.glEnd()
        GL.glLineWidth(1.0)
        GL.glPointSize(1.0)
        if depth_enabled:
            GL.glEnable(GL.GL_DEPTH_TEST)

    def _update_bone_screen_segments(self, GL):
        try:
            from OpenGL import GLU
            model = GL.glGetDoublev(GL.GL_MODELVIEW_MATRIX)
            projection = GL.glGetDoublev(GL.GL_PROJECTION_MATRIX)
            viewport = GL.glGetIntegerv(GL.GL_VIEWPORT)
            scale_x = float(viewport[2]) / max(1.0, float(self.width()))
            scale_y = float(viewport[3]) / max(1.0, float(self.height()))
            segments = []
            for name, start, end in self._scene.bones:
                sx, sy, _ = GLU.gluProject(*start, model, projection, viewport)
                ex, ey, _ = GLU.gluProject(*end, model, projection, viewport)
                segments.append((
                    name,
                    QPointF(float(sx) / scale_x, self.height() - float(sy) / scale_y),
                    QPointF(float(ex) / scale_x, self.height() - float(ey) / scale_y),
                ))
            self._bone_screen_segments = segments
        except Exception:
            self._bone_screen_segments = []

    def _bone_at_position(self, position: QPointF) -> str:
        best_name = ""
        best_distance = 9.0
        px, py = position.x(), position.y()
        for name, start, end in self._bone_screen_segments:
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length_sq = dx * dx + dy * dy
            amount = 0.0 if length_sq <= 1e-8 else max(0.0, min(1.0, ((px - start.x()) * dx + (py - start.y()) * dy) / length_sq))
            closest_x = start.x() + dx * amount
            closest_y = start.y() + dy * amount
            distance = math.hypot(px - closest_x, py - closest_y)
            if distance < best_distance:
                best_distance = distance
                best_name = name
        return best_name

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
        elif self._options["bones"]:
            bone = self._bone_at_position(event.position())
            if bone != self._hovered_bone:
                self._hovered_bone = bone
                if bone:
                    QToolTip.showText(event.globalPosition().toPoint(), bone, self)
                else:
                    QToolTip.hideText()
        self.update()

    def leaveEvent(self, event):
        self._hovered_bone = ""
        QToolTip.hideText()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self._distance *= math.pow(0.88, steps)
        self._distance = max(5.0, min(20000.0, self._distance))
        self.update()
