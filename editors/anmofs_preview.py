"""Embedded offset preview, using the same player and viewport as Char Skills."""
from core.design_tokens import (
    Insets,
    Size,
)
from core.style_helpers import (
    ss_bg_panel,
    ss_check,
    ss_dim_label,
)
from core.ui.editor_widgets import (
    configure_button,
    configure_input,
)
from pathlib import Path
import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFrame, QVBoxLayout, QGridLayout, QToolButton, QLabel, QWidget, QPushButton
from PyQt6.QtGui import QColor
import numpy as np

from core.settings import load_settings
from core.themes import P
from core.translations import ui_text
from editors.skill_preview import SkillPreviewPanel
from parsers.anmofs_tools import active_offset, receiver_scene_matrix, key_tick, receiver_model_code, is_situation_finish_offsets
from parsers.skill_tools import resource_roots, resolve_resource
from parsers.anmofs_animation import (
    motion_catalog, attacking_motion, clip_for_event, attack_clip, build_cues, reaction_pose, file_duration,
)


class AnmofsPreviewPanel(SkillPreviewPanel):
    key_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        self._offset_chunk = None
        self._asset_key = None
        self._context_key = None
        self._idle_clip = None
        self._cues = []
        self._cue_errors = []
        self._attack_duration = None
        self._timeline_engaged = False
        self._idle_frame = 0.0
        self._idle_last_tick = time.perf_counter()
        self._attacker_scene = self._attacker_clip = self._attacker_idle_clip = None
        self._attacker_asset_key = None
        self._attacker_errors = []
        self._attacker_bank = ''
        self._needs_camera_fit = False
        super().__init__(parent)
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(33)
        self._idle_timer.timeout.connect(self._tick_idle)
        self._speed_events.setChecked(False)
        self._speed_events.hide()
        options = QFrame(self)
        options.setStyleSheet(ss_bg_panel())
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(10, 4, 10, 4)
        self._view_mode = QComboBox(options)
        configure_input(self._view_mode)
        for key, value in [('anmofs_view_together', 'together'), ('anmofs_view_apart', 'apart'), ('anmofs_view_receiver', 'receiver')]:
            self._view_mode.addItem(ui_text(key), value)
        self._view_mode.setToolTip(ui_text('anmofs_view_hint'))
        self._view_mode.currentIndexChanged.connect(self._view_changed)
        options_layout.addWidget(self._view_mode)
        self._actor_info = QLabel(options)
        self._actor_info.setWordWrap(True)
        self._actor_info.setStyleSheet(ss_dim_label())
        options_layout.addWidget(self._actor_info)
        advanced = QWidget(options)
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.setContentsMargins(*Insets.NONE)
        self._mirror = QCheckBox(ui_text('anmofs_mirrored'), advanced)
        self._mirror.setStyleSheet(ss_check())
        self._mirror.toggled.connect(self._render)
        advanced_layout.addWidget(self._mirror)
        self._automatic = QCheckBox(ui_text('anmofs_auto_animation'), options)
        self._automatic.setStyleSheet(ss_check())
        self._automatic.setChecked(True)
        self._automatic.setToolTip(ui_text('anmofs_auto_animation_hint'))
        self._automatic.toggled.connect(self._animation_mode_changed)
        options_layout.addWidget(self._automatic)
        self._clip_combo.activated.connect(self._manual_clip_activated)
        self._rate = QComboBox(advanced)
        configure_input(self._rate)
        self._rate.addItem(ui_text('anmofs_rate_file'), 30)
        self._rate.addItem(ui_text('anmofs_rate_game'), 60)
        self._rate.setToolTip(ui_text('anmofs_rate_hint'))
        self._rate.currentIndexChanged.connect(self._change_rate)
        advanced_layout.addWidget(self._rate)
        reload_assets = QPushButton(ui_text('anmofs_reload_assets'), advanced)
        configure_button(reload_assets)
        reload_assets.setToolTip(ui_text('anmofs_reload_assets_hint'))
        reload_assets.clicked.connect(self._reload_assets)
        advanced_layout.addWidget(reload_assets)
        options_layout.addWidget(advanced)
        self.layout().insertWidget(1, options)
        self._status.setWordWrap(True)
        self._timeline.setToolTip(ui_text('anmofs_step_hint'))
        self._table.setHorizontalHeaderLabels([ui_text('ui_anmofs_col_frame'), ui_text('anmofs_translation'), ui_text('anmofs_rotation')])
        self._table.setColumnWidth(0, 100)
        self._configure_transport()
        self._viewport.set_options(bounds=False)
        self._set_manual_controls_visible()

    def _configure_transport(self):
        bar = self._clip_combo.parentWidget()
        layout = bar.layout()
        old = layout.takeAt(1).layout()
        widgets = []
        while old.count():
            item = old.takeAt(0)
            if item.widget() is not None:
                widgets.append(item.widget())
        previous, play, reset, following, loop, label = widgets
        for button in (play, reset):
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
        play.setText(ui_text('anmofs_play'))
        reset.setText(ui_text('anmofs_restart'))
        reset.setToolTip(ui_text('anmofs_restart_hint'))
        grid = QGridLayout()
        grid.setContentsMargins(*Insets.NONE)
        grid.setSpacing(6)
        grid.addWidget(play, 0, 0, 1, 3)
        grid.addWidget(reset, 0, 3, 1, 3)
        grid.addWidget(previous, 1, 0)
        grid.addWidget(following, 1, 1)
        grid.addWidget(loop, 1, 2, 1, 2)
        grid.addWidget(label, 1, 4, 1, 2)
        self._reaction_previous = QPushButton(ui_text('anmofs_previous_reaction'), bar)
        self._reaction_next = QPushButton(ui_text('anmofs_next_reaction'), bar)
        for button, delta in ((self._reaction_previous, -1), (self._reaction_next, 1)):
            configure_button(button, height=Size.COMPACT_CONTROL)
            button.clicked.connect(lambda _checked=False, direction=delta: self._jump_reaction(direction))
        grid.addWidget(self._reaction_previous, 2, 0, 1, 3)
        grid.addWidget(self._reaction_next, 2, 3, 1, 3)
        layout.insertLayout(1, grid)
        old.deleteLater()
        animation_row = layout.itemAt(0).layout()
        self._animation_open = animation_row.itemAt(1).widget()
        self._clip_combo.setToolTip(ui_text('anmofs_manual_clip_hint'))

    def _set_manual_controls_visible(self):
        manual = not self._automatic.isChecked()
        self._clip_combo.setVisible(manual)
        if hasattr(self, '_animation_open'):
            self._animation_open.setVisible(manual)

    def _reload_assets(self):
        self._asset_key = self._attacker_asset_key = self._context_key = None
        self.set_chunk(self._path, self._offset_chunk)
        self._viewport.reset_camera()

    def _jump_reaction(self, direction):
        current = self._frame * 30 / self.view_rate
        candidates = [cue.frame for cue in self._cues if cue.kind == 'clip'
                      and (cue.frame > current + 1e-6 if direction > 0 else cue.frame < current - 1e-6)]
        if candidates:
            self._scrub_timeline((min(candidates) if direction > 0 else max(candidates)) * self.view_rate / 30)

    def _view_changed(self):
        self._render()
        self._update_status()
        self._viewport.reset_camera()

    def _character_name(self, code):
        key = 'char_' + code
        name = ui_text(key)
        return code if name == key else name

    def set_chunk(self, path, chunk):
        self._stop()
        changed = chunk is not self._offset_chunk
        self._path, self._offset_chunk = str(path or ''), chunk
        common_finish = is_situation_finish_offsets(self._path)
        if common_finish != getattr(self, '_common_finish', False):
            self._common_finish = common_finish
            if common_finish:
                self._character_automatic = self._automatic.isChecked()
                self._automatic.setChecked(False)
            else:
                self._automatic.setChecked(getattr(self, '_character_automatic', True))
        self._automatic.setVisible(not common_finish)
        self._view_mode.setVisible(not common_finish)
        self._play.setText(ui_text('anmofs_play_offsets' if common_finish else 'anmofs_play'))
        if changed:
            self._frame = 0.0
            self._timeline_engaged = False
            self._idle_frame = 0.0
            self._needs_camera_fit = True
        self._entry = {'anim_id': '', 'subentries': []} if chunk else None
        self._entry_label.setText(ui_text('anmofs_finish_preview' if common_finish else 'anmofs_attack_preview') if chunk else ui_text('skill_preview'))
        self._entry_label.setToolTip(chunk.anm_name if chunk else '')
        key = (self._path, receiver_model_code(chunk) if chunk else '')
        if key != self._asset_key:
            self._asset_key = key
            self._auto_load()
        context_key = (self._path, chunk.anm_name if chunk else '', key, tuple(id(c) for c in self._clips))
        if context_key != self._context_key:
            self._context_key = context_key
            self._load_animation_context()
        self.refresh_entry()
        if self._needs_camera_fit:
            self._viewport.reset_camera()
            self._needs_camera_fit = False

    def _auto_load(self):
        self._scene = self._clip = None
        self._viewport.set_scene(None)
        self._asset_errors = []
        self._clips = []
        self._idle_clip = None
        self._cues = []
        code = receiver_model_code(self._offset_chunk) if self._offset_chunk else ''
        roots = resource_roots(self._path, load_settings().get('game_files_dir', ''))
        model = resolve_resource(roots, 'spc', code + 'bod1', code) if code else None
        palette = resolve_resource(roots, 'spc', code + 'col0', code) if code else None
        if model:
            try:
                self._load_model(model, [palette] if palette else [])
            except Exception as exc:
                self._asset_errors.append(str(exc))
        paths = [resolve_resource(roots, 'spc', code + suffix, code) for suffix in ('mot1', 'ghh1')] if code else []
        self._load_clips([p for p in paths if p])
        # The table names the attacker's motion, not the receiver's animation.
        # Do not apply the attacker's skeleton to the receiving model.
        self._clip_combo.setCurrentIndex(0)

    def _load_animation_context(self):
        self._idle_clip, self._cues, self._cue_errors = None, [], []
        self._attack_duration = None
        self._attacker_clip = self._attacker_idle_clip = None
        self._motion_found = False
        self._motion_sources = []
        chunk = self._offset_chunk
        if chunk is None:
            self._attacker_scene = None
            self._attacker_asset_key = None
            self._viewport.set_additional_scenes([])
            return
        roots = resource_roots(self._path, load_settings().get('game_files_dir', ''))
        receiver = receiver_model_code(chunk)
        receiving, _, errors = motion_catalog(roots, receiver)
        self._cue_errors.extend(errors)
        self._idle_clip = clip_for_event('PL_ANM_BAS_NUT', receiving, self._clips, receiver)
        if self._idle_clip is None:
            self._idle_clip = next((c for c in self._clips if c.name == receiver + '_bas_nut'), None)
        if self._idle_clip is None:
            self._cue_errors.append('PL_ANM_BAS_NUT')
        if is_situation_finish_offsets(self._path):
            # The common bank has no attacking character. Its SF_* events are
            # driven by ccSituationFinish, not a character PRM animation list.
            self._attacker_bank = ''
            self._attacker_scene = None
            self._attacker_asset_key = None
            self._attacker_errors = []
            self._viewport.set_additional_scenes([])
            return
        attacker = Path(self._path).name.removesuffix('_anmofs.xfbin')
        motion, sources, errors, bank = attacking_motion(roots, attacker, chunk.anm_name)
        self._attacker_bank = bank
        self._cue_errors.extend(errors)
        try:
            self._attacker_clip = attack_clip(roots, bank, chunk.anm_name)
            self._attack_duration = file_duration(self._attacker_clip) if self._attacker_clip else None
            catalog, _, _ = motion_catalog(roots, bank)
            idle_name = next((e['anim_id'] for e in catalog if e['event_id'] == 'PL_ANM_BAS_NUT'), bank + '_bas_nut')
            self._attacker_idle_clip = attack_clip(roots, bank, idle_name)
        except Exception as exc:
            self._cue_errors.append(str(exc))
        self._load_attacker(roots, bank)
        self._cues, errors = build_cues(motion, receiving, self._clips, receiver, self._attack_duration)
        self._cue_errors.extend(errors)
        self._motion_found = motion is not None
        self._motion_sources = sources

    def _load_attacker(self, roots, bank):
        model = resolve_resource(roots, 'spc', bank + 'bod1', bank)
        palette = resolve_resource(roots, 'spc', bank + 'col0', bank)
        key = (bank, model, palette)
        if key == self._attacker_asset_key:
            return
        self._attacker_asset_key = key
        self._attacker_scene = None
        self._attacker_errors = []
        if not model:
            self._attacker_errors.append(ui_text('anmofs_attacker_model_missing', code=bank))
            return
        try:
            from parsers.model_xfbin_parser import load_model_xfbin, build_render_scene
            doc = load_model_xfbin(model, [palette] if palette else [], palette_alias_index=0)
            if not doc.model_chunks:
                raise ValueError(ui_text('skill_preview_missing_model'))
            self._attacker_scene = build_render_scene(doc)
            self._needs_camera_fit = True
        except Exception as exc:
            self._attacker_errors.append(str(exc))

    def _animation_mode_changed(self):
        self._stop()
        self._set_manual_controls_visible()
        self.refresh_entry()

    def _manual_clip_activated(self, _index):
        self._automatic.setChecked(False)

    def _select_clip(self, index):
        if hasattr(self, '_automatic'):
            self._automatic.blockSignals(True)
            self._automatic.setChecked(False)
            self._automatic.blockSignals(False)
            self._set_manual_controls_visible()
        super()._select_clip(index)

    def _choose_animation(self):
        super()._choose_animation()
        self._context_key = None
        self._load_animation_context()
        self.refresh_entry()

    def refresh_entry(self):
        entries = self._offset_chunk.entries if self._offset_chunk else []
        rate = self.view_rate
        subs = [{'frame_w': key_tick(e.frame, rate), 'func_name': '', 'dmg_label': '', 'bone': ''} for e in entries if e.frame >= 0]
        automatic = self._automatic.isChecked()
        duration = self._attack_duration if automatic and self._attack_duration is not None else 0
        clip_duration = file_duration(self._clip) if self._clip and (not automatic or self._attack_duration is None) else 0
        maximum = max([round(duration * rate / 30),
                       round(clip_duration * rate / 30),
                       *(round(cue.frame * rate / 30) for cue in self._cues if automatic),
                       *(s['frame_w'] for s in subs), 1])
        self._slider.blockSignals(True)
        self._slider.setRange(0, min(maximum, 0x7FFFFFFF))
        self._slider.blockSignals(False)
        self._timeline.commands, self._timeline.maximum = subs, maximum
        self._timeline.literal_frames = [s['frame_w'] for s in subs if s['frame_w'] >= 0]
        self._timeline.reaction_frames = [cue.frame * rate / 30 for cue in self._cues if cue.kind == 'clip'] if self._automatic.isChecked() else []
        self._commands_label.setText(ui_text('anmofs_keyframes_title'))
        self._table.setRowCount(len(entries))
        from PyQt6.QtWidgets import QTableWidgetItem
        for row, entry in enumerate(entries):
            values = (str(entry.frame), ', '.join(f'{getattr(entry, "value_" + str(i)):.4g}' for i in (1, 2, 3)), ', '.join(f'{getattr(entry, "value_" + str(i)):.4g}' for i in (4, 5, 6)))
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(ui_text('anmofs_step_hint'))
                self._table.setItem(row, col, cell)
        self._update_status()
        self._seek(min(self._frame, maximum))

    def _update_status(self):
        issues = []
        common_finish = is_situation_finish_offsets(self._path)
        if self._scene is None:
            issues.append(ui_text('anmofs_receiver_model_missing'))
        if self._view_mode.currentData() != 'receiver' and not common_finish:
            if self._attacker_scene is None:
                issues.append(ui_text('anmofs_attacker_model_missing', code=self._attacker_bank))
            elif self._attacker_clip is None:
                issues.append(ui_text('anmofs_attack_clip_missing'))
        if self._automatic.isChecked() and not common_finish:
            if not getattr(self, '_motion_found', False):
                issues.append(ui_text('anmofs_no_motion_commands'))
            if self._cue_errors:
                issues.append(ui_text('anmofs_some_reactions_missing', count=len(self._cue_errors)))
        status = '\n'.join(issues[:2]) if issues else ui_text('anmofs_ready')
        status += '\n' + ui_text('anmofs_finish_scope' if common_finish else 'anmofs_pair_scope')
        self._status.setText(status)
        detail = '\n'.join([*self._cue_errors, *self._attacker_errors, *getattr(self, '_asset_errors', [])])
        self._status.setToolTip(status + '\n' + ui_text('anmofs_auto_source', count=sum(c.kind == 'clip' for c in self._cues)) + ('\n' + detail if detail else ''))

    def _seek_command(self, row, _column):
        if self._offset_chunk and 0 <= row < len(self._offset_chunk.entries):
            self._stop()
            self.seek_key(row)
            self.key_selected.emit(row)

    @property
    def view_rate(self):
        return self._rate.currentData() if hasattr(self, '_rate') else 30

    def seek_key(self, row):
        self._scrub_timeline(key_tick(self._offset_chunk.entries[row].frame, self.view_rate))

    def _change_rate(self):
        self._stop()
        old_rate = getattr(self, '_previous_rate', 30)
        self._frame *= self.view_rate / old_rate
        self._previous_rate = self.view_rate
        self.refresh_entry()

    def _seek(self, frame):
        if frame > 0:
            self._timeline_engaged = True
        super()._seek(frame)

    def _scrub_timeline(self, frame):
        self._timeline_engaged = True
        super()._scrub_timeline(frame)

    def _reset_playback(self):
        self._timeline_engaged = False
        self._idle_frame = 0.0
        super()._reset_playback()

    def _set_playing(self, playing):
        if playing:
            self._timeline_engaged = True
        super()._set_playing(playing)
        self._play.setText(ui_text('anmofs_pause' if playing else
                                  'anmofs_play_offsets' if is_situation_finish_offsets(self._path) else 'anmofs_play'))
        self._render()

    def _tick_idle(self):
        now = time.perf_counter()
        self._idle_frame += min(.1, now - self._idle_last_tick) * 30
        self._idle_last_tick = now
        self._render()

    def showEvent(self, event):
        super().showEvent(event)
        self._render()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._idle_timer.stop()

    def _animation_pose(self):
        file_frame = self._frame * 30 / self.view_rate
        if not self._automatic.isChecked():
            return self._clip, file_frame, False
        clip, sample, cue = reaction_pose(self._cues, file_frame) if self._timeline_engaged else (None, 0, None)
        if cue is not None and clip is not None:
            return clip, sample, False
        if self._idle_clip is not None:
            frame = file_frame if self._play.isChecked() else self._idle_frame
            sample = (frame % max(1, file_duration(self._idle_clip))) * 100 / max(1, self._idle_clip.chunk.frame_size)
            return self._idle_clip, sample, True
        return None, 0, False

    def _tick(self):
        now = time.perf_counter()
        frame = self._frame + min(0.1, now - self._last_tick) * self.view_rate
        self._last_tick = now
        if frame > self._slider.maximum():
            if self._loop.isChecked():
                frame %= self._slider.maximum()
            else:
                frame = self._slider.maximum()
                self._stop()
        self._seek(frame)

    def _render(self):
        self._frame_label.setText(f'{self._frame:.1f} / {self._slider.maximum()}')
        self._timeline.frame = self._frame
        self._timeline.update()
        if hasattr(self, '_reaction_previous'):
            current = self._frame * 30 / self.view_rate
            self._reaction_previous.setEnabled(any(c.kind == 'clip' and c.frame < current - 1e-6 for c in self._cues))
            self._reaction_next.setEnabled(any(c.kind == 'clip' and c.frame > current + 1e-6 for c in self._cues))
        clip, sample, idle = self._animation_pose()
        if self._automatic.isChecked():
            self._clip = clip
            selected = next((i + 1 for i, c in enumerate(self._clips) if c is clip), 0)
            self._clip_combo.blockSignals(True)
            self._clip_combo.setCurrentIndex(selected)
            self._clip_combo.blockSignals(False)
        attacker_idle = not self._timeline_engaged and self._attacker_idle_clip is not None
        show_attacker = hasattr(self, '_view_mode') and self._view_mode.currentData() != 'receiver'
        if hasattr(self, '_idle_timer'):
            has_idle = (idle and self._scene is not None) or (attacker_idle and self._attacker_scene is not None and show_attacker)
            if has_idle and self.isVisible() and not self._play.isChecked():
                if not self._idle_timer.isActive():
                    self._idle_last_tick = time.perf_counter()
                    self._idle_timer.start()
            else:
                self._idle_timer.stop()
        if self._scene:
            from parsers.model_xfbin_parser import apply_animation
            apply_animation(self._scene, clip, sample,
                            skin_meshes=not self._viewport.uses_gpu_skinning())
            self._viewport.geometry_changed()
        if self._attacker_scene is not None and show_attacker:
            from parsers.model_xfbin_parser import apply_animation
            attack = self._attacker_idle_clip if attacker_idle else self._attacker_clip
            frame = self._idle_frame if attacker_idle else self._frame * 30 / self.view_rate
            if attack is not None:
                if attacker_idle:
                    frame %= max(1, file_duration(attack))
                frame = frame * 100 / max(1, attack.chunk.frame_size)
            apply_animation(self._attacker_scene, attack, frame,
                            skin_meshes=not self._viewport.uses_gpu_skinning())
            self._viewport.geometry_changed()
        entries = self._offset_chunk.entries if self._offset_chunk else []
        index = active_offset(entries, self._frame, self.view_rate)
        entry = entries[index] if index is not None else None
        mirrored = hasattr(self, '_mirror') and self._mirror.isChecked()
        transform = receiver_scene_matrix(entry, mirrored)
        attacker_transform = np.identity(4, dtype=np.float32)
        if show_attacker and self._attacker_scene is not None and self._view_mode.currentData() == 'apart':
            # Presentation spacing only; stored offsets remain untouched.
            receiver_width = self._scene.bounds_max[0] - self._scene.bounds_min[0] if self._scene else 0
            width = max(8, receiver_width, self._attacker_scene.bounds_max[0] - self._attacker_scene.bounds_min[0])
            attacker_transform[0, 3] = -width * .7
            transform = transform.copy()
            transform[0, 3] += width * .7
        self._viewport.set_scene_transform(transform)
        self._viewport.set_additional_scenes([(self._attacker_scene, attacker_transform)] if show_attacker else [])
        if hasattr(self, '_actor_info') and self._offset_chunk:
            attacker = self._character_name(self._attacker_bank) if self._attacker_bank else '—'
            receiver = self._character_name(receiver_model_code(self._offset_chunk))
            self._actor_info.setText(ui_text('anmofs_finish_receiver', receiver=receiver) if is_situation_finish_offsets(self._path)
                                     else ui_text('anmofs_actor_roles', attacker=attacker, receiver=receiver))
            self._actor_info.setToolTip(ui_text('anmofs_actor_details', attack=self._attacker_clip.name if self._attacker_clip else '—',
                                               reaction=getattr(clip, 'name', '—')))
        for row in range(self._table.rowCount()):
            for col in range(3):
                cell = self._table.item(row, col)
                if cell:
                    cell.setBackground(QColor(P.get('selection_bg', P['accent_dim'])) if row == index else QColor('transparent'))
