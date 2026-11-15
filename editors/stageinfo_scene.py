"""Lazy, read-only 3D map preview using Arrow Forge's existing OpenGL viewer."""
import copy
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog, QComboBox

from core.design_tokens import LayoutRole, TypeSize, ui_font
from core.style_helpers import ss_dim_label
from core.ui.editor_widgets import configure_layout, configure_button, configure_input, EditorActionRow
from core.settings import load_settings, game_files_dialog_dir
from core.translations import ui_text
from core.stage_scene import stage_resources, load_stage_scene


class _LoadSignals(QObject):
    finished = pyqtSignal(int, object)


class _LoadMap(QRunnable):
    def __init__(self, generation, paths, stage, cancelled):
        super().__init__()
        self.generation, self.paths, self.stage = generation, paths, stage
        self.cancelled = cancelled
        self.signals = _LoadSignals()

    def run(self):
        errors = []
        for path in self.paths:
            if self.cancelled.is_set():
                break
            try:
                scene = load_stage_scene(path, self.stage)
                from core.stage_actor import load_stage_actor, place_stage_actor
                scene.preview_actor = place_stage_actor(load_stage_actor(), scene)
                if self.cancelled.is_set():
                    break
                self.signals.finished.emit(self.generation, (path, scene, ''))
                return
            except Exception as error:
                errors.append(f'{Path(path).name}: {error}')
        self.signals.finished.emit(self.generation, ('', None, '\n'.join(errors)))


class StageMapPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage = None
        self._source = None
        self._context = None
        self._generation = 0
        self._requested = False
        self._active = False
        self._viewport = None
        self._manual_paths = {}
        self._parameters = None
        self._worker_active = False
        self._next_request = None
        self._cancel_load = None
        layout = configure_layout(QVBoxLayout(self), LayoutRole.FIELD)
        actions = EditorActionRow()
        self._open = configure_button(QPushButton(ui_text('stage_preview_open')))
        self._open.clicked.connect(self._choose_file)
        actions.content_layout.addWidget(self._open)
        self._auto = configure_button(QPushButton(ui_text('stage_preview_auto')))
        self._auto.clicked.connect(self._automatic)
        actions.content_layout.addWidget(self._auto)
        actions.content_layout.addStretch()
        layout.addWidget(actions)
        camera = EditorActionRow()
        self._reset = configure_button(QPushButton(ui_text('skill_reset_camera')))
        self._reset.setEnabled(False)
        self._reset.clicked.connect(self._reset_camera)
        camera.content_layout.addWidget(self._reset)
        self._frame_map = configure_button(QPushButton(ui_text('stage_preview_frame_map')))
        self._frame_map.setEnabled(False)
        self._frame_map.clicked.connect(lambda: self._viewport.frame_map() if self._viewport else None)
        camera.content_layout.addWidget(self._frame_map)
        camera.content_layout.addStretch()
        layout.addWidget(camera)
        lighting = EditorActionRow()
        lighting_label = QLabel(ui_text('stage_preview_lighting'))
        lighting_label.setFont(ui_font(TypeSize.BODY))
        lighting_label.setStyleSheet(ss_dim_label())
        lighting.content_layout.addWidget(lighting_label)
        self._lighting = configure_input(QComboBox())
        self._lighting.setAccessibleName(ui_text('stage_preview_lighting'))
        self._lighting.addItem(ui_text('stage_preview_light_normal'), (0., 1))
        self._lighting.addItem(ui_text('stage_preview_light_alternate'), (1., 1))
        self._lighting.addItem(ui_text('stage_preview_light_group2'), (0., 2))
        self._lighting.currentIndexChanged.connect(self._update_lighting)
        lighting.content_layout.addWidget(self._lighting)
        lighting.content_layout.addStretch()
        layout.addWidget(lighting)
        self._status = QLabel(ui_text('stage_preview_lazy'))
        self._status.setFont(ui_font(TypeSize.HINT))
        self._status.setStyleSheet(ss_dim_label())
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setMinimumWidth(0)
        layout.addWidget(self._status)
        self._surface = QWidget()
        self._surface.setMinimumHeight(360)
        configure_layout(QVBoxLayout(self._surface), LayoutRole.ROOT)
        layout.addWidget(self._surface)

    def set_context(self, stage, source):
        key = (str(source or ''), stage.get('code', ''), tuple(stage.get('paths', [])),
               tuple((c['xfbin_path'], c['clump_name']) for c in stage.get('clumps', [])))
        self._stage = copy.deepcopy(stage)
        self._source = source
        if key != self._context:
            self._context = key
            self._generation += 1
            self._requested = False
            self._next_request = None
            if self._cancel_load:
                self._cancel_load.set()
            self._reset.setEnabled(False)
            self._frame_map.setEnabled(False)
            if self._viewport:
                self._viewport.set_scene(None)
            self._status.setText(ui_text('stage_preview_lazy'))
            self._status.setToolTip('')
        if self._active and self.isVisible():
            self.ensure_loaded()

    def set_active(self, active):
        self._active = active
        if active and self.isVisible():
            self.ensure_loaded()

    def showEvent(self, event):
        super().showEvent(event)
        if self._active:
            self.ensure_loaded()

    def ensure_loaded(self):
        if not self._stage or self._requested:
            return
        manual = self._manual_paths.get(self._context[:2])
        paths = [manual] if manual else stage_resources(
            self._stage, self._source, load_settings().get('game_files_dir', ''))
        self._requested = True
        if not paths:
            self._status.setText(ui_text('stage_preview_missing'))
            return
        self._start_load(paths)

    def _start_load(self, paths):
        self._generation += 1
        self._requested = True
        if self._viewport:
            self._viewport.set_scene(None)
        self._reset.setEnabled(False)
        self._frame_map.setEnabled(False)
        self._status.setText(ui_text('stage_preview_loading'))
        self._status.setToolTip('')
        request = (self._generation, list(paths), copy.deepcopy(self._stage))
        if self._worker_active:
            self._cancel_load.set()
            self._next_request = request
            return
        self._launch(request)

    def _launch(self, request):
        self._cancel_load = Event()
        self._worker_active = True
        worker = _LoadMap(*request, self._cancel_load)
        worker.signals.finished.connect(self._loaded)
        QThreadPool.globalInstance().start(worker)

    @pyqtSlot(int, object)
    def _loaded(self, generation, result):
        self._worker_active = False
        self._cancel_load = None
        if self._next_request:
            request, self._next_request = self._next_request, None
            if request[0] == self._generation:
                self._launch(request)
            return
        if generation != self._generation:
            return
        path, scene, error = result
        if scene is None:
            self._status.setText(ui_text('stage_preview_failed'))
            self._status.setToolTip(error)
            return
        if self._viewport is None:
            from editors.stageinfo_viewport import StageViewport
            self._viewport = StageViewport()
            self._viewport.setMinimumSize(0, 320)
            self._viewport.set_options(grid=False, bones=False, bounds=False, outlines=False)
            self._viewport.rendering_issue.connect(self._rendering_issue)
            self._surface.layout().addWidget(self._viewport)
        self._viewport.set_scene(scene)
        self._viewport.set_actor(getattr(scene, 'preview_actor', None))
        self._viewport.set_stage_parameters(self._parameters)
        self._update_lighting()
        self._reset.setEnabled(True)
        self._frame_map.setEnabled(True)
        self._status.setText(ui_text('stage_preview_loaded', name=Path(path).name))
        self._status.setToolTip(ui_text('stage_preview_limits') + '\n' + path)

    def _update_lighting(self):
        if self._viewport:
            self._viewport.set_lighting_reference(*self._lighting.currentData())

    def _rendering_issue(self, error):
        self._status.setText(ui_text('stage_preview_shader_failed'))
        self._status.setToolTip(error)

    def set_parameters(self, params):
        self._parameters = params
        if self._viewport:
            self._viewport.set_stage_parameters(params)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('stage_preview_open'),
            game_files_dialog_dir(fallback=self._source or '', target_patterns='*.xfbin'), 'XFBIN (*.xfbin)')
        if path and self._stage:
            self._manual_paths[self._context[:2]] = path
            self._start_load([path])

    def _automatic(self):
        if self._context:
            self._manual_paths.pop(self._context[:2], None)
        self._generation += 1
        self._requested = False
        self.ensure_loaded()

    def _reset_camera(self):
        if self._viewport:
            self._viewport.reset_camera()
