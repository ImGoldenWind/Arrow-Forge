"""Animated model inspection through the same original programs as Stage Info."""
import numpy as np
import math
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from core.themes import P
from editors.model_viewer_editor import _ModelOpenGLViewport
from editors.stageinfo_viewport import StageViewport
from core.stage_shadows import CAMERA_NEAR, CAMERA_FAR


class ModelViewport(StageViewport):
    object_picked = pyqtSignal(object)
    bone_picked = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._geometry_revision = 0
        self._frame_view_constants = None

    def uses_gpu_skinning(self):
        # Original SM4 material inputs are post-skinning. CPU skinning keeps
        # position, normal AND the authored tangent frame in the same pose.
        return False

    def reset_camera(self):
        _ModelOpenGLViewport.reset_camera(self)
        bounds = self.displayed_bounds()
        if bounds is not None:
            low, high = bounds
            radius = max(float(np.linalg.norm(high-low)) / 2, 1.)
            aspect = max(1, self.width()) / max(1, self.height())
            limiting_angle = math.atan(math.tan(math.radians(45.)/2) * min(1., aspect))
            self._distance = max(5., radius / math.sin(limiting_angle) * 1.08)
            self.update()

    def set_scene(self, scene, reset_camera=True):
        if scene:
            for mesh in scene.meshes:
                mesh.__dict__.pop('_native_arrays', None)
        super().set_scene(scene, reset_camera)
        self._actor = scene  # character lighting/fog contract, no extra actor

    def geometry_changed(self):
        if self._scene:
            for mesh in self._scene.meshes:
                # UVs are static; native positions and tangent frames aren't.
                mesh.__dict__.pop('_native_arrays', None)
        self._geometry_revision += 1
        super().geometry_changed()

    def _draw_shadow(self, GL, width, height):
        # There is no authored arena/floor in a standalone model. Do not
        # invent a receiver or pay for four empty 2048px shadow cascades.
        pass

    def _clear_viewport(self, GL):
        bg = QColor(P.get('viewport_bg', P['bg_dark']))
        GL.glDrawBuffers(2, [GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1])
        GL.glClearBufferfv(GL.GL_COLOR, 0, [bg.redF(), bg.greenF(), bg.blueF(), 1.])
        GL.glClearBufferfv(GL.GL_COLOR, 1, [0., 0., 0., 0.])
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)

    def _draw_mesh(self, GL, mesh):
        if not self._options['textured']:
            GL.glUseProgram(0)
            GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
            GL.glVertexPointer(3, GL.GL_FLOAT, 0, mesh.vertices)
            self._gl_color(GL, P['accent'] if self._selected in (mesh.model_chunk, mesh.material_chunk) else P['text_sec'])
            # The target is presented with a vertical flip, as are the original
            # vertex programs. Apply it to this diagnostic geometry pass too.
            GL.glMatrixMode(GL.GL_PROJECTION)
            GL.glPushMatrix()
            projection = np.asarray(GL.glGetFloatv(GL.GL_PROJECTION_MATRIX)).T.copy()
            projection[1] *= -1
            GL.glLoadMatrixf(projection.T.copy())
            if self._options['culling']:
                GL.glEnable(GL.GL_CULL_FACE)
                GL.glFrontFace(GL.GL_CW)
                GL.glCullFace(GL.GL_BACK)
            else:
                GL.glDisable(GL.GL_CULL_FACE)
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE if self._options['wireframe'] else GL.GL_FILL)
            try:
                self._draw_mesh_arrays(GL, mesh)
            finally:
                GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
                GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
                GL.glPopMatrix()
                GL.glMatrixMode(GL.GL_MODELVIEW)
            return
        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE if self._options['wireframe'] else GL.GL_FILL)
        try:
            self._draw_mesh_shaded(GL, mesh, self._options['textured'], False)
        finally:
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)

    def _material_cull_mode(self, mesh):
        return 1029 if self._options['culling'] else super()._material_cull_mode(mesh)

    def _view_constants(self, GL):
        # All meshes in this model share the same camera and environment.
        # glGetFloatv can synchronize with the GPU: do it once per frame.
        if self._frame_view_constants is None:
            self._frame_view_constants = super()._view_constants(GL)
        return self._frame_view_constants

    def _draw_mesh_arrays(self, GL, mesh):
        faces = getattr(mesh, '_gl_faces', None)
        if faces is None:
            faces = mesh._gl_faces = np.ascontiguousarray(mesh.faces, np.uint32)
        if faces.size:
            GL.glDrawElements(GL.GL_TRIANGLES, int(faces.size), GL.GL_UNSIGNED_INT, faces)

    def _paint_stage(self):
        from OpenGL import GL, GLU
        # Original programs flip their internal framebuffer. Editor guides
        # are drawn after presentation, in ordinary viewport coordinates.
        guides = {key: self._options[key] for key in ('grid', 'bones', 'bounds')}
        self._options.update(dict.fromkeys(guides, False))
        self._frame_view_constants = None
        try:
            super()._paint_stage()
        finally:
            self._options.update(guides)
            self._frame_view_constants = None
        width, height = max(1, round(self.width()*self.devicePixelRatioF())), max(1, round(self.height()*self.devicePixelRatioF()))
        GL.glViewport(0, 0, width, height)
        GL.glUseProgram(0)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glFrontFace(GL.GL_CCW)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GLU.gluPerspective(45., width / height, CAMERA_NEAR, CAMERA_FAR)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glTranslatef(0., 0., -self._distance)
        GL.glRotatef(self._pitch, 1., 0., 0.)
        GL.glRotatef(self._yaw, 0., 1., 0.)
        GL.glTranslatef(*(-np.asarray(self._center)))
        if guides['grid']:
            self._draw_grid(GL)
        if self._scene:
            if guides['bones']:
                self._draw_bones(GL)
            if guides['bounds']:
                self._draw_bounds(GL)
            if self._selected is not None:
                self._gl_color(GL, P['accent'])
                selected = []
                for mesh in self._scene.meshes:
                    if mesh.visible and self._selected in (mesh.model_chunk, mesh.material_chunk):
                        selected.append(mesh.vertices)
                if selected:
                    points = np.concatenate(selected)
                    low, high = points.min(axis=0), points.max(axis=0)
                    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
                    GL.glBegin(GL.GL_LINES)
                    for i, a in enumerate(corners):
                        for j in range(i + 1, 8):
                            if (i ^ j) in (1, 2, 4):
                                GL.glVertex3f(*a)
                                GL.glVertex3f(*corners[j])
                    GL.glEnd()
        GL.glEnable(GL.GL_DEPTH_TEST)

    def mousePressEvent(self, event):
        self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not event.buttons() and not self._options['bones']:
            return  # Hovering the viewport does not change a rendered frame.
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and
                (event.position().toPoint() - getattr(self, '_press_position', event.position().toPoint())).manhattanLength() < 5):
            bone = self._bone_at_position(event.position()) if self._options['bones'] else ''
            if bone:
                self.bone_picked.emit(bone)
                super().mouseReleaseEvent(event)
                return
            from core.model_viewer_tools import pick_mesh
            mesh = pick_mesh(self._scene, event.position().x(), event.position().y(), self.width(), self.height(),
                             self._yaw, self._pitch, self._distance, self._center)
            if mesh is not None:
                obj = mesh.material_chunk if event.modifiers() & Qt.KeyboardModifier.ControlModifier else mesh.model_chunk
                if obj is not None:
                    self.object_picked.emit(obj)
        super().mouseReleaseEvent(event)
