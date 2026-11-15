"""Read-only asset preview and command timeline for Char Skills."""
from __future__ import annotations

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    ss_bg_dark,
    ss_bg_panel,
    ss_check,
    ss_dim_label,
    ss_panel_title,
    ss_slider,
    ss_splitter,
)
from core.ui.editor_widgets import (
    configure_button,
    configure_input,
    configure_layout,
    configure_table,
)
from pathlib import Path
import time

from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSlider, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QSizePolicy,
)

from core.settings import load_settings
from core.icons import _themed_icon
from core.themes import P
from core.translations import ui_text
from parsers.skill_tools import frame_label, resource_roots, resolve_resource, related_resources, timeline_frame


class _CommandTimeline(QWidget):
    """Small themed frame ruler; shares the player's playhead and seek action."""
    seek_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setMaximumHeight(64)
        self.setMinimumWidth(0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.maximum, self.frame, self.commands = 1, 0.0, []
        self.setToolTip(ui_text('skill_timeline_hint'))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(P['bg_panel']))
        left, width = 12, max(1, self.width() - 24)
        painter.setFont(ui_font(TypeSize.CAPTION))
        ticks = max(2, min(8, width // 64))
        for i in range(ticks + 1):
            x = left + width * i / ticks
            painter.setPen(QColor(P['border']))
            painter.drawLine(int(x), 22, int(x), 58)
            painter.setPen(QColor(P['text_dim']))
            painter.drawText(QRectF(x - 18, 2, 36, 18), Qt.AlignmentFlag.AlignCenter, str(round(self.maximum * i / ticks)))
        literal_frames = getattr(self, 'literal_frames', None)
        frames = literal_frames if literal_frames is not None else [timeline_frame(sub, self.maximum) for sub in self.commands if sub['frame_w'] <= 9999]
        for frame in frames:
            x = left + width * frame / max(1, self.maximum)
            painter.setPen(QPen(QColor(P['accent_dim']), 3))
            painter.drawLine(int(x), 34, int(x), 46)
        for frame in getattr(self, 'reaction_frames', []):
            x = left + width * frame / max(1, self.maximum)
            painter.setPen(QPen(QColor(P.get('warning', P['text_dim'])), 3))
            painter.drawLine(int(x), 49, int(x), 58)
        x = left + width * self.frame / max(1, self.maximum)
        painter.setPen(QPen(QColor(P['accent']), 2))
        painter.drawLine(int(x), 21, int(x), 60)
        painter.setBrush(QColor(P['accent']))
        painter.drawEllipse(QRectF(x - 3, 22, 6, 6))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._seek_at(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_at(event.position().x())

    def _seek_at(self, x):
        self.seek_requested.emit(round(max(0.0, min(1.0, (x - 12) / max(1, self.width() - 24))) * self.maximum))


class SkillPreviewPanel(QWidget):
    command_selected = pyqtSignal(object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.setStyleSheet(ss_bg_dark())
        self._entries, self._clips = [], []
        self._scene = self._entry = self._clip = None
        self._path = ''
        self._matched_anim_id = None
        self._frame = self._last_tick = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 8)
        layout.setSpacing(6)

        header = QFrame()
        header.setStyleSheet(ss_bg_panel())
        top = QHBoxLayout(header)
        top.setContentsMargins(10, 8, 10, 8)
        top.setSpacing(Size.GAP)
        self._entry_label = QLabel(ui_text('skill_preview'))
        self._entry_label.setStyleSheet(ss_panel_title())
        self._entry_label.setMinimumWidth(0)
        self._entry_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self._entry_label, 1)
        self._model_open = self._icon_button('fa6s.cube', 'skill_load_model', self._choose_model)
        top.addWidget(self._model_open)
        layout.addWidget(header)

        from editors.model_viewer_editor import (
            _ModelOpenGLViewport, _ViewportPanel, _ViewportControls,
            _ViewCubeWidget, _AxisGizmoWidget,
        )
        self._vertical_split = QSplitter(Qt.Orientation.Vertical)
        self._vertical_split.setStyleSheet(ss_splitter())
        self._vertical_split.setChildrenCollapsible(False)
        player = QWidget()
        player_layout = QVBoxLayout(player)
        player_layout.setContentsMargins(*Insets.NONE)
        player_layout.setSpacing(6)
        self._viewport_frame = _ViewportPanel()
        self._viewport_frame.setMinimumHeight(180)
        self._viewport = _ModelOpenGLViewport()
        self._viewport.setMinimumSize(0, 0)
        self._viewport_frame.set_viewport(self._viewport)
        view_controls = _ViewportControls()
        for key, option, icon, checked in (
            ('ui_model_viewer_textured', 'textured', 'fa6s.image', True),
            ('ui_model_viewer_bones', 'bones', 'fa6s.bone', False),
            ('ui_model_viewer_grid', 'grid', 'fa6s.table-cells', True),
        ):
            toggle = view_controls.add_toggle(ui_text(key), checked, icon)
            toggle.toggled.connect(lambda value, opt=option: self._viewport.set_options(**{opt: value}))
        self._viewport_frame.set_controls(view_controls)
        cube = _ViewCubeWidget()
        cube.view_requested.connect(self._viewport.set_camera_view)
        self._viewport_frame.set_view_cube(cube)
        axis = _AxisGizmoWidget()
        self._viewport.camera_changed.connect(axis.set_camera)
        self._viewport_frame.set_axis_gizmo(axis)
        reset = self._icon_button('fa6s.rotate-left', 'skill_reset_camera', self._viewport.reset_camera)
        self._viewport_frame.set_reset_button(reset)
        player_layout.addWidget(self._viewport_frame, 1)

        bar = QFrame()
        bar.setStyleSheet(ss_bg_panel())
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(10, 6, 10, 6)
        bar_layout.setSpacing(6)
        animation_row = QHBoxLayout()
        animation_row.setSpacing(7)
        self._clip_combo = QComboBox()
        self._clip_combo.setMinimumWidth(0)
        self._clip_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        configure_input(self._clip_combo)
        self._clip_combo.setToolTip(ui_text('skill_animation'))
        self._clip_combo.currentIndexChanged.connect(self._select_clip)
        animation_row.addWidget(self._clip_combo, 1)
        animation_row.addWidget(self._icon_button('fa6s.folder-open', 'skill_load_animation', self._choose_animation))
        bar_layout.addLayout(animation_row)
        controls = QHBoxLayout()
        controls.setSpacing(7)
        controls.addWidget(self._icon_button('fa6s.backward-step', 'skill_previous_frame', lambda: self._step(-1)))
        self._play = self._icon_button('fa6s.play', 'skill_play', None, toggle=True)
        self._play.toggled.connect(self._set_playing)
        controls.addWidget(self._play)
        controls.addWidget(self._icon_button('fa6s.stop', 'usm_preview_stop', self._reset_playback))
        controls.addWidget(self._icon_button('fa6s.forward-step', 'skill_next_frame', lambda: self._step(1)))
        controls.addStretch()
        self._loop = QCheckBox(ui_text('ui_model_viewer_loop_animation'))
        self._loop.setStyleSheet(ss_check())
        self._loop.setChecked(True)
        controls.addWidget(self._loop)
        self._frame_label = QLabel('0 / 0')
        self._frame_label.setMinimumWidth(68)
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._frame_label.setStyleSheet(ss_dim_label())
        controls.addWidget(self._frame_label)
        bar_layout.addLayout(controls)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.setStyleSheet(ss_slider())
        self._slider.sliderPressed.connect(self._stop)
        self._slider.valueChanged.connect(self._seek)
        bar_layout.addWidget(self._slider)
        player_layout.addWidget(bar)
        self._vertical_split.addWidget(player)

        commands = QWidget()
        commands_layout = QVBoxLayout(commands)
        configure_layout(commands_layout, LayoutRole.ROOT)
        heading = QFrame()
        heading.setStyleSheet(ss_bg_panel())
        heading_layout = QHBoxLayout(heading)
        heading_layout.setContentsMargins(10, 6, 10, 6)
        self._commands_label = QLabel(ui_text('skill_timeline'))
        self._commands_label.setStyleSheet(ss_dim_label())
        heading_layout.addWidget(self._commands_label, 1)
        self._speed_events = QCheckBox(ui_text('skill_speed_commands'))
        self._speed_events.setStyleSheet(ss_check())
        self._speed_events.setToolTip(ui_text('skill_preview_speed'))
        self._speed_events.setChecked(True)
        heading_layout.addWidget(self._speed_events)
        commands_layout.addWidget(heading)
        self._timeline = _CommandTimeline()
        self._timeline.seek_requested.connect(self._scrub_timeline)
        commands_layout.addWidget(self._timeline)
        self._table = QTableWidget(0, 3)
        configure_table(self._table)
        self._table.verticalHeader().hide()
        self._table.verticalHeader().setDefaultSectionSize(Size.TABLE_ROW)
        self._table.setHorizontalHeaderLabels([ui_text('skill_field_frame_num'), ui_text('skill_field_function'), ui_text('skill_target')])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 52)
        self._table.setColumnWidth(1, 215)
        self._table.setMinimumHeight(85)
        self._table.cellClicked.connect(self._seek_command)
        commands_layout.addWidget(self._table, 1)
        self._vertical_split.addWidget(commands)
        self._vertical_split.setStretchFactor(0, 3)
        self._vertical_split.setStretchFactor(1, 2)
        self._vertical_split.setSizes([420, 240])
        layout.addWidget(self._vertical_split, 1)
        self._status = QLabel()
        self._status.setStyleSheet(ss_dim_label())
        self._status.setMinimumWidth(0)
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._status.setToolTip(ui_text('skill_preview_hint'))
        layout.addWidget(self._status)

    def _icon_button(self, icon, tooltip, callback, *, toggle=False):
        button = QPushButton()
        button.setFixedSize(34, 30)
        button.setCheckable(toggle)
        configure_button(button, toggle=toggle)
        button.setIcon(_themed_icon(icon, color=P.get('button_text', P['text_main']), size=14))
        button.setToolTip(ui_text(tooltip))
        if callback is not None:
            button.clicked.connect(callback)
        return button

    def _reset_playback(self):
        self._stop()
        self._seek(0)

    def _scrub_timeline(self, frame):
        self._stop()
        self._seek(frame)

    def set_document(self, path, result, entries, selected=None):
        changed = path != self._path
        self._path, self._result, self._entries = path, result, list(entries)
        self.select_entry(selected or next((e for _, e in entries if e.get('anim_id')), None), load_assets=changed)

    def select_entry(self, entry, *, load_assets=False):
        changed = entry is not self._entry
        if changed or load_assets:
            self._stop()
            self._entry = entry
            if load_assets:
                self._auto_load()
            self._match_clip()
        else:
            # Re-evaluate an edited animation ID without resetting the playhead.
            if self._entry and self._matched_anim_id != self._entry.get('anim_id'):
                self._match_clip()
        title = entry.get('event_id') or entry.get('anim_id') if entry else ui_text('skill_preview')
        self._entry_label.setText(title)
        self._entry_label.setToolTip(title or ui_text('skill_preview'))
        self.refresh_entry()

    def _auto_load(self):
        self._stop()
        self._scene = None
        self._viewport.set_scene(None)
        self._clips = []
        configured = load_settings().get('game_files_dir', '')
        roots = resource_roots(self._path, configured)
        code = Path(self._path).name.split('prm', 1)[0]
        model = resolve_resource(roots, 'spc', code + 'bod1', code)
        palette = resolve_resource(roots, 'spc', code + 'col0', code)
        self._asset_errors = []
        if model:
            try:
                self._load_model(model, [palette] if palette else [])
            except Exception as exc:
                self._asset_errors.append(str(exc))
        paths = [resolve_resource(roots, 'spc', code + suffix, code) for suffix in ('mot1', 'ghh1')]
        paths.extend(r['path'] for r in related_resources(self._path, self._result, configured)
                     if r['kind'] in (3, 11) and r['path'])
        self._load_clips(list(dict.fromkeys(p for p in paths if p)))
        if self._scene is None:
            self._status.setText(ui_text('skill_preview_missing_model') + ' ' + '; '.join(self._asset_errors))

    def _load_model(self, path, palettes=()):
        from parsers.model_xfbin_parser import load_model_xfbin, build_render_scene
        self._stop()
        doc = load_model_xfbin(path, palettes, palette_alias_index=0)
        if not doc.model_chunks:
            raise ValueError(ui_text('skill_preview_missing_model'))
        self._scene = build_render_scene(doc)
        self._viewport.set_scene(self._scene)
        self._model_path = path
        self._render()

    def _load_clips(self, paths):
        from parsers.model_xfbin_parser import load_animation_clips
        self._stop()
        clips = []
        for path in paths:
            try:
                clips.extend(load_animation_clips([path]))
            except Exception as exc:
                self._asset_errors.append(f'{Path(path).name}: {exc}')
        self._clips = clips
        self._clip_combo.blockSignals(True)
        self._clip_combo.clear()
        self._clip_combo.addItem(ui_text('skill_no_animation'))
        for clip in clips:
            self._clip_combo.addItem(f'{clip.name} ({Path(clip.source_path).name})')
        self._clip_combo.blockSignals(False)

    def _choose_model(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('skill_load_model'), str(Path(self._path).parent), 'XFBIN (*.xfbin)')
        if path:
            try:
                self._load_model(path)
                self._update_status()
            except Exception as exc:
                self._status.setText(str(exc))

    def _choose_animation(self):
        paths, _ = QFileDialog.getOpenFileNames(self, ui_text('skill_load_animation'), str(Path(self._path).parent), 'XFBIN (*.xfbin)')
        if paths:
            self._load_clips(paths)
            self._match_clip()

    def _match_clip(self):
        name = self._entry.get('anim_id', '') if self._entry else ''
        self._matched_anim_id = name
        index = next((i + 1 for i, clip in enumerate(self._clips) if clip.name == name), 0)
        self._clip_combo.blockSignals(True)
        self._clip_combo.setCurrentIndex(index)
        self._clip_combo.blockSignals(False)
        self._select_clip(index)

    def _select_clip(self, index):
        self._stop()
        self._clip = self._clips[index - 1] if 1 <= index <= len(self._clips) else None
        self._frame = 0.0
        self.refresh_entry()

    def refresh_entry(self):
        subs = self._entry.get('subentries', []) if self._entry else []
        numbered = [s['frame_w'] for s in subs if s['frame_w'] < 9998]
        maximum = max([self._clip.frame_count if self._clip else 0, *numbered, 1])
        self._slider.blockSignals(True)
        self._slider.setRange(0, maximum)
        self._slider.blockSignals(False)
        self._timeline.commands = subs
        self._timeline.maximum = maximum
        self._commands_label.setText(f"{ui_text('skill_timeline')} ({len(subs)})")
        self._table.setRowCount(len(subs))
        for i, sub in enumerate(subs):
            values = (frame_label(sub['frame_w']), sub['func_name'], sub['dmg_label'] or sub['bone'])
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                self._table.setItem(i, j, item)
        self._update_status()
        self._seek(min(self._frame, maximum))

    def _update_status(self):
        if self._scene is None:
            status = ui_text('skill_preview_missing_model')
        elif self._clip is None:
            status = ui_text('skill_preview_missing_animation', name=self._entry.get('anim_id', '') if self._entry else '')
        else:
            status = f"{Path(self._model_path).name} | {self._clip.name} | {self._clip.frame_count} frames"
        if getattr(self, '_asset_errors', []):
            status += ' | ' + '; '.join(self._asset_errors)
        self._status.setText(status)
        self._status.setToolTip(status + '\n\n' + ui_text('skill_preview_hint'))

    def _seek_command(self, row, _column):
        if self._entry and self._entry['subentries'][row]['frame_w'] <= 9999:
            self._stop()
            self._seek(timeline_frame(self._entry['subentries'][row], self._slider.maximum()))
            self.command_selected.emit(self._entry, row)

    def _step(self, delta):
        self._stop()
        self._seek(round(self._frame) + delta)

    def _seek(self, frame):
        self._frame = max(0.0, min(float(frame), float(self._slider.maximum())))
        self._slider.blockSignals(True)
        self._slider.setValue(round(self._frame))
        self._slider.blockSignals(False)
        self._render()

    def _render(self):
        self._frame_label.setText(f'{self._frame:.1f} / {self._slider.maximum()}')
        self._timeline.frame = self._frame
        self._timeline.update()
        if self._scene:
            from parsers.model_xfbin_parser import apply_animation
            apply_animation(self._scene, self._clip, self._frame, skin_meshes=not self._viewport.uses_gpu_skinning())
            self._viewport.geometry_changed()
        if self._entry:
            for i, sub in enumerate(self._entry['subentries']):
                active = abs(timeline_frame(sub, self._slider.maximum()) - self._frame) < 0.6
                for j in range(3):
                    item = self._table.item(i, j)
                    if item:
                        item.setBackground(QColor(P.get('selection_bg', P['accent_dim'])) if active else QColor('transparent'))

    def _set_playing(self, playing):
        self._play.setIcon(_themed_icon('fa6s.pause' if playing else 'fa6s.play', color=P.get('button_text', P['text_main']), size=14))
        self._play.setToolTip(ui_text('skill_pause' if playing else 'skill_play'))
        if playing:
            if self._frame >= self._slider.maximum():
                self._seek(0)
            self._last_tick = time.perf_counter()
            self._timer.start()
        else:
            self._timer.stop()

    def _stop(self):
        self._timer.stop()
        self._play.setChecked(False)

    def _tick(self):
        now = time.perf_counter()
        elapsed = min(0.1, now - self._last_tick)
        self._last_tick = now
        speed = 1.0
        if self._speed_events.isChecked() and self._entry:
            events = [s for s in self._entry['subentries']
                      if s['func_name'] == 'ME_ANM_SPEED_SET' and s['frame_w'] != 9999
                      and timeline_frame(s, self._slider.maximum()) <= self._frame]
            if events:
                event = max(enumerate(events), key=lambda pair: (timeline_frame(pair[1], self._slider.maximum()), pair[0]))[1]
                speed = max(0.0, min(20.0, event.get('speed_multiplier', 1.0)))
        frame = self._frame + elapsed * 60 * speed
        if frame > self._slider.maximum():
            if self._loop.isChecked():
                frame %= self._slider.maximum()
            else:
                frame = self._slider.maximum()
                self._stop()
        self._seek(frame)

    def closeEvent(self, event):
        self._stop()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._stop()
        super().hideEvent(event)
