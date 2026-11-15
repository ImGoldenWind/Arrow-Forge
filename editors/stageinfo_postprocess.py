"""ASBR's original glare, colour-conversion and FXAA programs.

Internal render targets use native top-left image coordinates. The viewport
flips once on presentation; intermediate passes retain the game's sampling
and pixel-position conventions throughout.
"""
from pathlib import Path
import struct

import numpy as np
from PyQt6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

from core.runtime_paths import app_path
from core.stage_shaders import read_shader_package, disassemble, translate_shader


def glare_levels(width, height):
    return [(max(1, width // (4 << i)), max(1, height // (4 << i))) for i in range(4)]


class StagePostprocess:
    def __init__(self, viewport):
        self.viewport = viewport
        self.programs = {}
        self.targets = {}
        self.packages = None
        self.samplers = {}
        self.last_passes = []

    def release(self, GL):
        for program, _, _ in self.programs.values():
            GL.glDeleteProgram(program)
        if self.samplers:
            GL.glDeleteSamplers(len(self.samplers), list(self.samplers.values()))
        self.programs.clear()
        self.samplers.clear()
        self.targets.clear()

    def target(self, GL, name, width, height, floating=False):
        key = (width, height, floating)
        current = self.targets.get(name)
        if current is None or current[0] != key:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setInternalTextureFormat(GL.GL_RGBA16F if floating else GL.GL_RGBA8)
            current = key, QOpenGLFramebufferObject(width, height, fmt)
            self.targets[name] = current
        return current[1]

    def program(self, GL, shader_id):
        if shader_id not in self.programs:
            from OpenGL.GL.shaders import compileProgram, compileShader
            if self.packages is None:
                self.packages = read_shader_package(Path(app_path('resources', 'stage_preview', 'post_effects.nsh')).read_bytes())
            vs, ps = self.packages[shader_id]
            vertex = translate_shader(disassemble(vs), True, native_framebuffer=True)
            pixel = translate_shader(disassemble(ps), False)
            program = compileProgram(compileShader(vertex.source, GL.GL_VERTEX_SHADER),
                                     compileShader(pixel.source, GL.GL_FRAGMENT_SHADER), validate=False)
            self.programs[shader_id] = program, vertex, pixel
        return self.programs[shader_id]

    def sampler(self, GL, point=False, border=False):
        key = point, border
        if key not in self.samplers:
            sampler = GL.glGenSamplers(1)
            filtering = GL.GL_NEAREST if point else GL.GL_LINEAR
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_MIN_FILTER, filtering)
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_MAG_FILTER, filtering)
            wrapping = GL.GL_CLAMP_TO_BORDER if border else GL.GL_CLAMP_TO_EDGE
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_WRAP_S, wrapping)
            GL.glSamplerParameteri(sampler, GL.GL_TEXTURE_WRAP_T, wrapping)
            GL.glSamplerParameterfv(sampler, GL.GL_TEXTURE_BORDER_COLOR, [0., 0., 0., 0.])
            self.samplers[key] = sampler
        return self.samplers[key]

    def draw(self, GL, shader_id, destination, sources, values, *, rect=None, point=False, border_units=(), blend=False):
        program, vertex, pixel = self.program(GL, shader_id)
        width, height = destination.width(), destination.height()
        x, y, w, h = rect or (0, 0, width, height)
        transform = np.array([[2. / width, 0., 0., -1.], [0., -2. / height, 0., 1.],
                              [0., 0., 1., 0.], [0., 0., 0., 1.]], np.float32)
        params = dict(transform=transform.T, textureSize=(sources[0][1], sources[0][2]),
                      color=(1., 1., 1., 1.), renderSize=(width, height, 0., 0.))
        params.update(values)
        destination.bind()
        GL.glDrawBuffer(GL.GL_COLOR_ATTACHMENT0)
        GL.glViewport(0, 0, width, height)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        if blend:
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        else:
            GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(program)
        self.viewport._upload_constants(GL, program, vertex, 'v', params)
        self.viewport._upload_constants(GL, program, pixel, 'p', params)
        for unit, (texture, _, _) in enumerate(sources):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            GL.glBindSampler(unit, self.sampler(GL, point, unit in border_units))
            self.viewport._uniform_i(GL, program, 'tex' + str(unit), unit)
        # The game's 2D vertex routine supplies positions and texture extents
        # in pixels. Each original vertex program applies its own size/offset.
        position = self.viewport._attribute_location(GL, program, 'a0')
        texcoord = self.viewport._attribute_location(GL, program, 'a1')
        positions = np.asarray([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float32)
        coords = np.asarray([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
        for location, array in ((position, positions), (texcoord, coords)):
            if location >= 0:
                GL.glEnableVertexAttribArray(location)
                GL.glVertexAttribPointer(location, 2, GL.GL_FLOAT, False, 0, array)
        GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, 4)
        for location in (position, texcoord):
            if location >= 0:
                GL.glDisableVertexAttribArray(location)
        for unit in range(len(sources)):
            GL.glBindSampler(unit, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glUseProgram(0)
        self.last_passes.append(shader_id)

    @staticmethod
    def source(target, attachment=0):
        return target.textures()[attachment], target.width(), target.height()

    def process(self, GL, scene, parameters):
        self.last_passes = []
        width, height = scene.width(), scene.height()
        quarter_w, quarter_h = glare_levels(width, height)[0]
        atlas = self.target(GL, 'atlas', quarter_w, quarter_h * 2)
        # Native colour and glare-mask downsampling (0x11000004), followed by
        # extraction (0x11000000). The compact atlas preserves both UV regions.
        scale = (width / quarter_w, height / quarter_h, 0., 0.)
        self.draw(GL, 0x11000004, atlas, [self.source(scene)],
                  dict(size=scale, param=(1., 0., 0., 0.)), rect=(0, 0, quarter_w, quarter_h), point=True)
        self.draw(GL, 0x11000004, atlas, [self.source(scene, 1)],
                  dict(size=scale, param=(1., 0., 0., 0.)), rect=(0, quarter_h, quarter_w, quarter_h), point=True)
        extracted = self.target(GL, 'extract', quarter_w, quarter_h)
        self.draw(GL, 0x11000000, extracted, [self.source(atlas)],
                  dict(size=(1., 1., 0., 0.), glareArea=(1., 1., 0., quarter_h),
                       param=(.5, .5, 0., 1.)), point=True)
        levels = []
        previous = extracted
        for i, (w, h) in enumerate(glare_levels(width, height)):
            level = self.target(GL, 'level' + str(i), w, h, floating=i >= 2)
            scratch = self.target(GL, 'blur' + str(i), w, h, floating=i >= 2)
            self.blit(GL, previous, level)
            self.draw(GL, 0x11000001, scratch, [self.source(level)],
                      dict(size=(1., 1., 0., 0.), blur=(1., 0., 0., 0.)))
            self.draw(GL, 0x11000001, level, [self.source(scratch)],
                      dict(size=(1., 1., 0., 0.), blur=(0., 1., 0., 0.)))
            levels.append(level)
            previous = level
        combined = self.target(GL, 'combined', quarter_w, quarter_h)
        # Native retained runtime glare state: strength 3, weights 2/2/6/6,
        # multiplied by 1/4 in 73E470. Stored StageInfo glare is overridden.
        mappings = {f'size{i}': (1., 1., 0., 0.) for i in range(4)}
        self.draw(GL, 0x11000002, combined, [self.source(level) for level in levels],
                  dict(mappings, param=(1.5, 1.5, 4.5, 4.5)), border_units=(1, 2, 3))
        composed = self.target(GL, 'composed', width, height)
        self.draw(GL, 0x11000005, composed, [self.source(scene), self.source(combined)],
                  dict(size0=(1., 1., 0., 0.), size1=(1., 1., 0., 0.)), border_units=(1,))
        current = composed
        if parameters and struct.unpack_from('<I', parameters, 64)[0]:
            x, y, strength = struct.unpack_from('<3f', parameters, 68)
            filtered = self.target(GL, 'filtered', width, height)
            self.blit(GL, current, filtered)
            self.draw(GL, 0x11000025, filtered, [self.source(current)],
                      dict(g_ScreenToUV=(1. / width, 1. / height, 0., 0.), param=(x, y, 0., 0.),
                           color=(1., 1., 1., max(0., min(1., strength)))), blend=True)
            current = filtered
        final = self.target(GL, 'antialias', width, height)
        self.draw(GL, 0x11000032, final, [self.source(current)],
                  dict(size0=(1., 1., 0., 0.), renderSize=(width, height, 0., 0.)))
        return final

    @staticmethod
    def blit(GL, source, destination):
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, source.handle())
        GL.glReadBuffer(GL.GL_COLOR_ATTACHMENT0)
        GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, destination.handle())
        GL.glDrawBuffer(GL.GL_COLOR_ATTACHMENT0)
        GL.glBlitFramebuffer(0, 0, source.width(), source.height(), 0, 0,
                             destination.width(), destination.height(), GL.GL_COLOR_BUFFER_BIT, GL.GL_LINEAR)
