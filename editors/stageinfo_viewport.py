"""Stage preview driven by the original ASBR SM4 material programs."""
import math
import re
import struct
from pathlib import Path

import numpy as np
from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

from editors.model_viewer_editor import _ModelOpenGLViewport
from core.runtime_paths import app_path
from core.stage_tools import packed_color_rgba
from core.stage_shaders import read_shader_package, disassemble, translate_shader
from parsers.model_xfbin_parser import ResolvedTextureRef
from core.stage_materials import native_uv_coordinates, texture_mip_images
from core.stage_shadows import (ShadowFitter, SHADOW_SIZE, CASCADE_SPLITS,
                                CASCADE_TILES, CAMERA_NEAR, CAMERA_FAR, atlas_matrix)


_NATIVE_TO_VIEW = np.array([[1., 0., 0., 0.], [0., 0., 1., 0.],
                            [0., -1., 0., 0.], [0., 0., 0., 1.]], np.float32)


class StageViewport(_ModelOpenGLViewport):
    rendering_issue = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage_params = None
        self._native_programs = {}
        self._native_errors = {}
        self._packages = None
        self._target = None
        self._actor = None
        self._alternate = 0.
        self._light_group = 1
        self._shadow_texture = 0
        self._shadow_fbo = 0
        self._shadow_matrices = [np.eye(4, dtype=np.float32) for _ in range(4)]
        self._shadow_fitter = None
        self._last_shadow = None
        self._samplers = {}
        from editors.stageinfo_postprocess import StagePostprocess
        self._post = StagePostprocess(self)

    def set_stage_parameters(self, params):
        self._stage_params = bytes(params) if params is not None else None
        self.update()

    def set_lighting_reference(self, alternate=0., group=1):
        self._alternate, self._light_group = alternate, group
        self.update()

    def set_actor(self, actor):
        self._actor = actor
        self.set_additional_scenes([(actor, None)])
        self.reset_camera()

    def reset_camera(self):
        if self._actor:
            low, high = np.asarray(self._actor.bounds_min), np.asarray(self._actor.bounds_max)
            self._center = (low + high) / 2
            self._distance = max(450., float(high[1] - low[1]) * 3.1)
            self._yaw, self._pitch = 25., 10.
            self.update()
        else:
            super().reset_camera()

    def frame_map(self):
        super().reset_camera()

    def set_scene(self, scene, reset_camera=True):
        self._release_assets()
        self._actor = None
        self._last_shadow = None
        self._native_errors.clear()
        super().set_scene(scene, reset_camera=reset_camera)

    def initializeGL(self):
        super().initializeGL()
        if self.context():
            self.context().aboutToBeDestroyed.connect(self._release_context_assets)

    @pyqtSlot()
    def _release_context_assets(self):
        self._release_assets(destroy_context=True)

    def _release_assets(self, destroy_context=False):
        if not self.isValid():
            return
        from OpenGL import GL
        self.makeCurrent()
        try:
            if self._textures:
                GL.glDeleteTextures(list(self._textures.values()))
            for display_list in self._mesh_lists.values():
                GL.glDeleteLists(display_list, 1)
            self._textures.clear()
            self._mesh_lists.clear()
            # Programs and the viewport render target belong to the context,
            # not to a stage. Reuse them while browsing maps.
            # Explicit ownership avoids QObject.sender() traversing a worker
            # signal whose QRunnable has already been auto-deleted by Qt.
            if destroy_context:
                for program, _, _ in self._native_programs.values():
                    GL.glDeleteProgram(program)
                self._native_programs.clear()
                self._uniform_locations.clear()
                self._attribute_locations.clear()
                self._post.release(GL)
                if self._samplers:
                    GL.glDeleteSamplers(len(self._samplers), list(self._samplers.values()))
                    self._samplers.clear()
                self._target = None
                if self._shadow_texture:
                    GL.glDeleteTextures([self._shadow_texture])
                    GL.glDeleteFramebuffers(1, [self._shadow_fbo])
                self._shadow_texture = self._shadow_fbo = 0
        finally:
            self.doneCurrent()

    def _load_packages(self):
        if self._packages is None:
            self._packages = read_shader_package(Path(app_path('resources', 'stage_preview', 'materials.nsh')).read_bytes())
        return self._packages

    def _program(self, GL, shader_id):
        if shader_id in self._native_errors:
            return None
        if shader_id not in self._native_programs:
            try:
                from OpenGL.GL.shaders import compileShader, compileProgram
                vs, ps = self._load_packages()[shader_id]
                vt = translate_shader(disassemble(vs), True, native_framebuffer=True)
                pt = translate_shader(disassemble(ps), False, output_targets=2)
                program = compileProgram(compileShader(vt.source, GL.GL_VERTEX_SHADER),
                                         compileShader(pt.source, GL.GL_FRAGMENT_SHADER), validate=False)
                self._native_programs[shader_id] = program, vt, pt
            except Exception as error:
                self._native_errors[shader_id] = str(error)
                self.rendering_issue.emit(str(error))
                return None
        return self._native_programs[shader_id]

    def _create_asbr_shader(self, GL):
        result = self._program(GL, 0x1f003)
        return result[0] if result else 0

    def _prepare_gpu_skinning(self, GL):
        # Stage geometry and the bundled neutral pose have already been baked.
        self._gpu_skinning_ready = False

    def _clear_viewport(self, GL):
        GL.glDrawBuffers(2, [GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1])
        GL.glClearBufferfv(GL.GL_COLOR, 0, [0., 0., 0., 1.])
        GL.glClearBufferfv(GL.GL_COLOR, 1, [0., 0., 0., 0.])
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)

    def _material_sampler(self, GL, mesh, unit):
        settings = getattr(mesh, 'native_state', {}).get('samplers', [])
        state = settings[unit] if unit < len(settings) else dict(wrap_s=1, wrap_t=1, min_filter=4, mag_filter=2, mip_detail=8)
        key = tuple(sorted(state.items()))
        if key not in self._samplers:
            sampler = GL.glGenSamplers(1)
            wrapping = {1: GL.GL_REPEAT, 2: GL.GL_MIRRORED_REPEAT, 3: GL.GL_CLAMP_TO_EDGE,
                        4: GL.GL_CLAMP_TO_BORDER, 5: GL.GL_MIRROR_CLAMP_TO_EDGE}
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_WRAP_S, wrapping.get(state['wrap_s'], GL.GL_REPEAT))
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_WRAP_T, wrapping.get(state['wrap_t'], GL.GL_REPEAT))
            filtering = {0: GL.GL_NEAREST, 1: GL.GL_NEAREST, 2: GL.GL_LINEAR,
                         3: GL.GL_NEAREST_MIPMAP_NEAREST, 4: GL.GL_LINEAR_MIPMAP_LINEAR}
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_MIN_FILTER, filtering.get(state['min_filter'], GL.GL_LINEAR_MIPMAP_LINEAR))
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST if state['mag_filter'] == 1 else GL.GL_LINEAR)
            GL.glSamplerParameterf(sampler, GL.GL_TEXTURE_LOD_BIAS, (state['mip_detail'] - 8) * .5)
            self._samplers[key] = sampler
        return self._samplers[key]

    def _texture_id(self, GL, ref):
        # DirectX UVs address the first decoded image row at v=0. The shared
        # viewer flips images for its own GLSL; original shaders must not.
        key = id(ref.pil_image)
        if key not in self._textures:
            tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            images = texture_mip_images(ref)
            for level, image in enumerate(images):
                image = image.convert('RGBA')
                GL.glTexImage2D(GL.GL_TEXTURE_2D, level, GL.GL_RGBA8, image.width, image.height,
                                0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, image.tobytes())
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAX_LEVEL, len(images) - 1)
            self._textures[key] = tex
        return self._textures[key]

    def _rgba(self, offset):
        return np.asarray(packed_color_rgba(self._stage_params[offset:offset + 4]), np.float32) / 255.

    def _cube_texture_id(self, GL, ref):
        import copy
        from parsers.texture_xfbin_parser import nut_tex_to_pil
        key = ('cube', id(ref.chunk))
        if key not in self._textures:
            nut = getattr(ref.chunk, 'nut', None)
            texture = nut.textures[0] if nut and nut.textures else None
            faces = getattr(texture, 'cubemap_faces', None)
            if not faces or len(faces) != 6:
                raise ValueError('Missing cubemap faces: ' + ref.name)
            tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_CUBE_MAP, tex)
            for i, face in enumerate(faces):
                plane = copy.copy(texture)
                plane.is_cube_map = False
                plane.mipmap_count = 1
                plane.mipmaps = [face]
                plane.texture_data = face
                image = nut_tex_to_pil(plane)
                if image is None:
                    GL.glDeleteTextures([tex])
                    raise ValueError('Unable to decode cubemap: ' + ref.name)
                image = image.convert('RGBA')
                GL.glTexImage2D(GL.GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, GL.GL_RGBA8,
                    image.width, image.height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, image.tobytes())
            GL.glTexParameteri(GL.GL_TEXTURE_CUBE_MAP, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_CUBE_MAP, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            for axis in (GL.GL_TEXTURE_WRAP_S, GL.GL_TEXTURE_WRAP_T, GL.GL_TEXTURE_WRAP_R):
                GL.glTexParameteri(GL.GL_TEXTURE_CUBE_MAP, axis, GL.GL_CLAMP_TO_EDGE)
            GL.glGenerateMipmap(GL.GL_TEXTURE_CUBE_MAP)
            self._textures[key] = tex
        return self._textures[key]

    def _view_constants(self, GL):
        params = self._stage_params
        valid = params is not None and len(params) == 136
        modelview = np.asarray(GL.glGetFloatv(GL.GL_MODELVIEW_MATRIX)).T
        projection = np.asarray(GL.glGetFloatv(GL.GL_PROJECTION_MATRIX)).T.copy()
        projection[2] = (projection[2] + projection[3]) * .5
        identity = np.eye(4, dtype=np.float32)
        eye = _NATIVE_TO_VIEW.T @ np.linalg.inv(modelview) @ [0., 0., 0., 1.]
        actor = self._scene is self._actor
        ambient, light = np.ones(4), np.ones(4)
        if valid and actor:
            ambient = self._rgba(8) if self._light_group == 2 else self._rgba(0) * (1 - self._alternate) + self._rgba(4) * self._alternate
            light = self._rgba(16) * (1 - self._alternate) + self._rgba(20) * self._alternate
            ambient[:3] = np.clip(2 * ambient[3] * ambient[:3], 0, 1)
            light[:3] = np.clip(2 * light[3] * light[:3], 0, 1)
        fog = struct.unpack_from('<3f', params, 48) if valid else (0., 1., 0.)
        if actor:
            fog = (1., 1.001, 0.)
        if not all(math.isfinite(v) for v in fog) or fog[0] == fog[1]:
            fog = (0., 1., 0.)
        x, y, z = struct.unpack_from('<3f', params, 24) if valid else (0., 0., -1.)
        light_direction = (x, y, z, 0.)
        if not all(math.isfinite(v) for v in light_direction) or not any(light_direction):
            light_direction = (0., 0., -1., 0.)
        values = dict(g_matWorldViewProj=(projection @ modelview @ _NATIVE_TO_VIEW).T,
            g_matWorld=identity, g_matWorldInvTrans=identity, g_eyePos=eye,
            g_commonParam=(0., 1., 1., 0.), g_ambientColor=ambient,
            g_lightColor=light, g_lightDirection=light_direction,
            g_fogColor=self._rgba(60) if valid and not actor else (0., 0., 0., 1.),
            g_fogParam=(*fog, 1.), g_multColor=(1., 1., 1., 1.),
            g_uvOffset0=(0., 0., 1., 1.), g_uvOffset1=(0., 0., 1., 1.),
            g_Kd0=(1., 1., 1., 1.), g_Ks=(1., 1., 1., 1.), g_Kparam0=(0., 1., 0., 16.),
            g_ScreenToUV=(1. / max(1, round(self.width() * self.devicePixelRatioF())),
                          1. / max(1, round(self.height() * self.devicePixelRatioF())), 0., 0.),
            g_outlineParam=(0., 0., 0., 4.8 / max(1, round(self.width() * self.devicePixelRatioF()))),
            g_cparaColor1=(1., 1., 1., 1. / max(1, round(self.width() * self.devicePixelRatioF()))),
            g_shadowParam=CASCADE_SPLITS,
            g_shadowColor=self._rgba(40) if valid else (0., 0., 0., 1.))
        for i in range(4):
            values['g_matShadowProj' + str(i)] = (self._shadow_matrices[i] @ _NATIVE_TO_VIEW).T
            values['g_pointLightPos' + str(i)] = (0., 0., 100000.)
        return values

    def _constant_values(self, GL, mesh):
        values = self._view_constants(GL).copy()
        state = getattr(mesh, 'native_state', {})
        uv = state.get('uv_transforms', ((0., 0., 1., 1.),) * 4)
        values.update(g_commonParam=(state.get('alpha_reference', 0.), 1., 1., state.get('glare', 0.)),
                      g_uvOffset0=uv[0], g_uvOffset1=uv[1])
        for key, value in mesh.material_params.items():
            if key.startswith('NU_'):
                values['g_' + key[3:]] = value
        return values

    def _upload_constants(self, GL, program, translation, prefix, values):
        match = re.search(r'uniform vec4 ' + prefix + r'cb0\[(\d+)\]', translation.source)
        if not match:
            return
        data = np.zeros((int(match[1]), 4), np.float32)
        flat = data.ravel()
        for name, (offset, size) in translation.constants.items():
            value = values.get(name)
            if value is not None:
                a = np.asarray(value, np.float32).ravel()[:size // 4]
                start = offset // 4
                if start + len(a) <= len(flat):
                    flat[start:start + len(a)] = a
        location = self._uniform_location(GL, program, prefix + 'cb0[0]')
        if location >= 0:
            GL.glUniform4fv(location, len(data), data)

    def _draw_mesh_shaded(self, GL, mesh, textured, selected):
        shader_id = mesh.shader_id
        # NUCC selects the shadow-receiving variant for the stage floor. Its
        # texture layout and shading remain those of the original material.
        if self._scene is not self._actor and '_flo' in mesh.name.casefold():
            receiver = shader_id | 0x40000
            if receiver in self._load_packages():
                shader_id = receiver
        native = self._program(GL, shader_id)
        if native is None:
            return  # An unsupported shader is reported, never replaced silently.
        program, vt, pt = native
        GL.glUseProgram(program)
        values = self._constant_values(GL, mesh)
        self._upload_constants(GL, program, vt, 'v', values)
        self._upload_constants(GL, program, pt, 'p', values)
        enabled, arrays = [], []
        defaults = dict(POSITION=(0., 0., 0., 1.), NORMAL=(0., 0., 1., 0.),
                        COLOR=(1., 1., 1., 1.), TEXCOORD=(0., 0., 0., 1.),
                        TANGENT=(1., 0., 0., 0.), BINORMAL=(0., 1., 0., 0.))
        for reg, (semantic, index) in vt.inputs.items():
            location = self._attribute_location(GL, program, 'a' + str(reg))
            if location < 0:
                continue
            array = dict(POSITION=mesh.vertices, NORMAL=mesh.normals, COLOR=mesh.colors,
                         TEXCOORD=mesh.uvs2 if index == 1 and mesh.uvs2 is not None else mesh.uvs,
                         TANGENT=getattr(mesh, 'tangent', None), BINORMAL=getattr(mesh, 'bitangent', None)).get(semantic)
            if array is not None:
                if semantic == 'TEXCOORD':
                    cache = getattr(mesh, '_native_uvs', None)
                    if cache is None:
                        cache = mesh._native_uvs = {}
                    if index not in cache:
                        cache[index] = native_uv_coordinates(array)
                    array = cache[index]
                if semantic in ('POSITION', 'NORMAL', 'TANGENT', 'BINORMAL'):
                    # Keep the game's native Z-up shader inputs. Rotating only
                    # the final WVP also preserves water/cubemap shader axes.
                    cache = getattr(mesh, '_native_arrays', None)
                    if cache is None:
                        cache = mesh._native_arrays = {}
                    if semantic not in cache:
                        cache[semantic] = np.ascontiguousarray(array @ _NATIVE_TO_VIEW[:3, :3], np.float32)
                    array = cache[semantic]
                array = np.ascontiguousarray(array, np.float32)
                arrays.append(array)  # retain client storage through glDrawElements
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location, array.shape[1], GL.GL_FLOAT, False, 0, array)
                enabled.append(location)
            else:
                GL.glVertexAttrib4f(location, *defaults.get(semantic, (0., 0., 0., 1.)))
        for unit, kind in pt.textures.items():
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            if kind == 'sampler2DShadow':
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._shadow_texture)
                GL.glBindSampler(unit, 0)
            else:
                ref = mesh.texture_slots.get('slot_' + str(unit))
                if kind == 'samplerCube' and isinstance(ref, ResolvedTextureRef):
                    GL.glBindTexture(GL.GL_TEXTURE_CUBE_MAP, self._cube_texture_id(GL, ref))
                elif isinstance(ref, ResolvedTextureRef) and ref.pil_image is not None:
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture_id(GL, ref))
                else:
                    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
                GL.glBindSampler(unit, self._material_sampler(GL, mesh, unit))
            self._uniform_i(GL, program, 'tex' + str(unit), unit)
        state = getattr(mesh, 'native_state', {})
        cull = self._material_cull_mode(mesh)
        if cull in (1028, 1029):
            GL.glEnable(GL.GL_CULL_FACE)
            GL.glFrontFace(GL.GL_CW)
            GL.glCullFace(GL.GL_FRONT if cull == 1028 else GL.GL_BACK)
        else:
            GL.glDisable(GL.GL_CULL_FACE)
        source, destination = state.get('source', 2), state.get('destination', 0)
        if (source, destination) == (2, 0):
            GL.glDisable(GL.GL_BLEND)
        else:
            factors = {0: GL.GL_ZERO, 1: GL.GL_ZERO, 2: GL.GL_ONE,
                       3: GL.GL_SRC_COLOR, 4: GL.GL_ONE_MINUS_SRC_COLOR,
                       5: GL.GL_SRC_ALPHA, 6: GL.GL_ONE_MINUS_SRC_ALPHA,
                       7: GL.GL_DST_ALPHA, 8: GL.GL_ONE_MINUS_DST_ALPHA,
                       9: GL.GL_DST_COLOR, 10: GL.GL_ONE_MINUS_DST_COLOR}
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(factors.get(source, GL.GL_ONE), factors.get(destination, GL.GL_ZERO))
        self._draw_mesh_arrays(GL, mesh)
        for location in enabled:
            GL.glDisableVertexAttribArray(location)
        for unit in pt.textures:
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glBindTexture(GL.GL_TEXTURE_CUBE_MAP, 0)
            GL.glBindSampler(unit, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glUseProgram(0)

    def _material_cull_mode(self, mesh):
        return getattr(mesh, 'native_state', {}).get('cull', mesh.cull_mode)

    def _draw_mesh(self, GL, mesh):
        # Avoid the shared viewer's fixed-function fallback: inability to run
        # an original shader is a reported error, not approximate shading.
        self._draw_mesh_shaded(GL, mesh, True, False)

    def _draw_shadow(self, GL, width, height):
        key = (id(self._scene), id(self._actor), self._distance, self._yaw, self._pitch,
               tuple(self._center), width, height, self._stage_params[24:40] if self._stage_params else None)
        if key == self._last_shadow and self._shadow_texture:
            return
        if self._shadow_fitter is None:
            self._shadow_fitter = ShadowFitter()
        if not self._shadow_texture:
            self._shadow_texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._shadow_texture)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_DEPTH_COMPONENT32F, *SHADOW_SIZE,
                            0, GL.GL_DEPTH_COMPONENT, GL.GL_FLOAT, None)
            for parameter, value in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST),
                                     (GL.GL_TEXTURE_COMPARE_MODE, GL.GL_COMPARE_REF_TO_TEXTURE),
                                     (GL.GL_TEXTURE_COMPARE_FUNC, GL.GL_LEQUAL),
                                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_BORDER), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_BORDER)):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, parameter, value)
            GL.glTexParameterfv(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_BORDER_COLOR, [1., 1., 1., 1.])
            self._shadow_fbo = GL.glGenFramebuffers(1)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._shadow_fbo)
            GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT, GL.GL_TEXTURE_2D, self._shadow_texture, 0)
            GL.glDrawBuffer(GL.GL_NONE)
            GL.glReadBuffer(GL.GL_NONE)
            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('Unable to allocate stage shadow atlas')
        params = self._stage_params
        direction = np.array(struct.unpack_from('<3f', params, 24) if params else (0., 0., -1.), np.float64)
        if not np.isfinite(direction).all() or np.linalg.norm(direction) < 1e-6:
            direction = np.array([.3, .5, -1.])
        direction /= np.linalg.norm(direction)
        # Let fixed-function matrix construction match the shared orbit camera
        # exactly; fitting and the original shader inputs remain native Z-up.
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glTranslatef(0., 0., -self._distance)
        GL.glRotatef(self._pitch, 1., 0., 0.)
        GL.glRotatef(self._yaw, 0., 1., 0.)
        GL.glTranslatef(*(-np.asarray(self._center)))
        view = np.asarray(GL.glGetFloatv(GL.GL_MODELVIEW_MATRIX)).T @ _NATIVE_TO_VIEW
        projection = np.asarray(GL.glGetFloatv(GL.GL_PROJECTION_MATRIX)).T.copy()
        cascades = self._shadow_fitter.cascades(view, projection, direction)
        self._shadow_matrices = [atlas_matrix(i) @ matrix @ _NATIVE_TO_VIEW.T for i, matrix in enumerate(cascades)]
        native = self._program(GL, 0xe001)
        if native is None:
            raise RuntimeError('Original stage shadow program is unavailable')
        program, vt, _ = native
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._shadow_fbo)
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glDepthMask(True)
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)
        GL.glUseProgram(program)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
        location = GL.glGetAttribLocation(program, 'a0')
        GL.glEnableVertexAttribArray(location)
        casters = [mesh for scene in (self._scene, self._actor) if scene is not None
                   for mesh in scene.meshes if mesh.visible and getattr(mesh, 'casts_shadow', False)]
        for matrix, (x, y, tile_width, tile_height) in zip(cascades, CASCADE_TILES):
            # Row zero is the native atlas top throughout the original passes.
            GL.glViewport(x, y, tile_width, tile_height)
            self._upload_constants(GL, program, vt, 'v', {'g_matWorldViewProj': matrix.T})
            for mesh in casters:
                cache = getattr(mesh, '_native_arrays', None)
                if cache is None:
                    cache = mesh._native_arrays = {}
                if 'POSITION' not in cache:
                    cache['POSITION'] = np.ascontiguousarray(mesh.vertices @ _NATIVE_TO_VIEW[:3, :3], np.float32)
                GL.glVertexAttribPointer(location, 3, GL.GL_FLOAT, False, 0, cache['POSITION'])
                self._draw_mesh_arrays(GL, mesh)
        GL.glDisableVertexAttribArray(location)
        GL.glUseProgram(0)
        self._last_shadow = key

    def paintGL(self):
        try:
            self._paint_stage()
        except Exception as error:
            # An OpenGL callback must never unwind into Qt's native event loop.
            # Retain the editor and provide a visible failure instead.
            from OpenGL import GL
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            if 'frame' not in self._native_errors:
                self._native_errors['frame'] = str(error)
                self.rendering_issue.emit(str(error))

    def _paint_stage(self):
        from OpenGL import GL, GLU
        width, height = max(1, round(self.width()*self.devicePixelRatioF())), max(1, round(self.height()*self.devicePixelRatioF()))
        if self._target is None or self._target.width() != width or self._target.height() != height:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setInternalTextureFormat(GL.GL_RGBA8)
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            self._target = QOpenGLFramebufferObject(width, height, fmt)
            self._target.addColorAttachment(width, height, GL.GL_RGBA8)
        self._target.bind()
        GL.glViewport(0,0,width,height)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glMatrixMode(GL.GL_PROJECTION);GL.glLoadIdentity()
        GLU.gluPerspective(45., width / height, CAMERA_NEAR, CAMERA_FAR)
        self._draw_shadow(GL, width, height)
        self._target.bind()
        GL.glViewport(0, 0, width, height)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        super().paintGL()
        composed = self._post.process(GL, self._target, self._stage_params)
        target = self.defaultFramebufferObject()
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER,composed.handle())
        GL.glReadBuffer(GL.GL_COLOR_ATTACHMENT0)
        GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER,target)
        GL.glBlitFramebuffer(0,height,width,0,0,0,width,height,GL.GL_COLOR_BUFFER_BIT,GL.GL_NEAREST)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER,target)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def wheelEvent(self, event):
        self._distance = max(5., min(20000000., self._distance * math.pow(.88, event.angleDelta().y()/120.)))
        self.update()
