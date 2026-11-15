"""One model load at a time; Qt objects and OpenGL stay on the GUI thread."""
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from parsers.model_xfbin_parser import load_model_xfbin, build_render_scene, load_animation_clips


class ModelLoadSignals(QObject):
    finished = pyqtSignal(int, object, str)


class ModelLoadJob(QRunnable):
    def __init__(self, generation, path, textures, animations):
        super().__init__()
        self.generation, self.path = generation, path
        self.textures, self.animations = textures, animations
        # Unparented: a job may finish after the editor has been destroyed.
        # Qt disconnects the deleted receiver, while the job retains signals.
        self.signals = ModelLoadSignals()

    def run(self):
        try:
            doc = load_model_xfbin(self.path, self.textures, palette_alias_index=0)
            scene = build_render_scene(doc)
            if not scene.meshes:
                raise ValueError('model_no_geometry')
            warning = ''
            from core.model_viewer_tools import model_lighting
            try:
                doc.preview_lighting = model_lighting(self.path)
            except Exception as error:
                doc.preview_lighting = []
                warning = str(error)
            try:
                clips = load_animation_clips(self.animations)
            except Exception as error:
                clips, warning = [], str(error)
            result = doc, scene, clips, warning
            error = ''
        except Exception as exc:
            result, error = None, str(exc)
        self.signals.finished.emit(self.generation, result, error)
