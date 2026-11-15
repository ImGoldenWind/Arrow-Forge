"""Isolated execution of ASBR's perspective shadow fitting (RVA 0x707980).

Only the bundled math pages execute, inside Unicorn's virtual address space.
No game process, game installation, OS imports or native executable allocation
are involved. The four cascade results are cached by the viewport camera.
"""
import ctypes
import json
import struct

import numpy as np
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_GS_BASE, UC_X86_REG_RSP,
    UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9,
    UC_X86_REG_XMM0, UC_X86_REG_XMM1, UC_X86_REG_RIP)

from core.runtime_paths import app_path


SHADOW_SIZE = (2048, 5120)
CASCADE_SPLITS = (1000., 3000., 5000., 10000.)
CASCADE_TILES = ((0, 0, 2048, 2048), (0, 2048, 2048, 2048),
                 (0, 4096, 1024, 1024), (1024, 4096, 1024, 1024))
CAMERA_NEAR, CAMERA_FAR = 4., 524288.


class ShadowFitter:
    def __init__(self):
        self._uc = uc = Uc(UC_ARCH_X86, UC_MODE_64)
        with np.load(app_path('resources', 'stage_preview', 'shadow_math.npz'), allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata']))
            self._base, self._entry = metadata['base'], metadata['entry']
            mapped = set()
            for rva, page in zip(data['pages'], data['data']):
                address = self._base + int(rva)
                uc.mem_map(address, 4096)
                uc.mem_write(address, page.tobytes())
                mapped.add(address)
        self._object, self._stack, self._stop = 0x3000000, 0x4080008, 0x4000000
        uc.mem_map(self._object, 0x20000)
        uc.mem_map(self._stop, 0x100000)
        uc.mem_write(self._base + 0x1ab7f28, struct.pack('<Q', self._object + 0x7000))
        identity = np.eye(4, dtype=np.float32).tobytes()
        uc.mem_write(self._object + 0x7010, identity)
        uc.mem_write(self._base + 0x1ddd0b0, identity)
        # The SDK matrix setters mark a thread-local dirty flag. Give that flag
        # isolated scratch storage; no Windows TLS or running game is consulted.
        uc.reg_write(UC_X86_REG_GS_BASE, self._object + 0x10000)
        for offset, target in ((0x10058, 0x11000), (0x11000, 0x12000), (0x12090, 0x13000)):
            uc.mem_write(self._object + offset, struct.pack('<Q', self._object + target))
        self._imports = {}
        self._crt = ctypes.CDLL('ucrtbase.dll')
        for item in metadata['imports']:
            address, name = item['address'], item['name']
            page = address & ~4095
            if page not in mapped:
                uc.mem_map(page, 4096)
                mapped.add(page)
            uc.mem_write(address, b'\xc3')
            function = getattr(self._crt, name)
            scalar = ctypes.c_float if name.endswith('f') else ctypes.c_double
            count = 2 if name.startswith('atan2') else 1
            function.argtypes, function.restype = [scalar] * count, scalar
            self._imports[address] = function, count, 'f' if name.endswith('f') else 'd'
            uc.hook_add(UC_HOOK_CODE, self._call_math, begin=address, end=address)

    def _call_math(self, uc, address, size, context):
        function, count, fmt = self._imports[address]
        arguments = [struct.unpack_from('<' + fmt, uc.reg_read(reg).to_bytes(16, 'little'))[0]
                     for reg in (UC_X86_REG_XMM0, UC_X86_REG_XMM1)[:count]]
        uc.reg_write(UC_X86_REG_XMM0, int.from_bytes(struct.pack('<' + fmt, function(*arguments)), 'little'))

    def fit(self, view, projection, direction, near, far):
        uc, obj = self._uc, self._object
        uc.mem_write(obj, b'\0' * 0x6000)
        uc.mem_write(obj + 0x38, struct.pack('<Q', obj + 0x2000))
        uc.mem_write(obj + 0x224c, struct.pack('<2f', CAMERA_NEAR, CAMERA_FAR))
        uc.mem_write(obj + 0xc0, np.asarray(projection, np.float32).tobytes())
        uc.mem_write(obj + 0x80, np.asarray(np.linalg.inv(view), np.float32).tobytes())
        uc.mem_write(obj + 0x100, struct.pack('<4f', *direction, 1000.))
        uc.mem_write(obj + 0x4000, struct.pack('<2f', near, far))
        for offset, target in ((0, self._stop), (0x28, obj + 0x4004), (0x30, obj + 0x5000)):
            uc.mem_write(self._stack + offset, struct.pack('<Q', target))
        for register, value in ((UC_X86_REG_RSP, self._stack), (UC_X86_REG_RCX, obj),
                                (UC_X86_REG_RDX, obj + 0x4100), (UC_X86_REG_R8, obj + 0x4200),
                                (UC_X86_REG_R9, obj + 0x4000)):
            uc.reg_write(register, value)
        uc.emu_start(self._base + self._entry, self._stop, count=200000)
        if uc.reg_read(UC_X86_REG_RIP) != self._stop:
            raise RuntimeError('Native shadow math exceeded its instruction limit')
        light_view, light_projection = [np.frombuffer(bytes(uc.mem_read(obj + offset, 64)), np.float32).reshape(4, 4)
                                       for offset in (0x4100, 0x4200)]
        result = light_projection @ light_view
        if not np.isfinite(result).all():
            raise ValueError('Nonfinite native shadow projection')
        return result

    def cascades(self, view, projection, direction):
        near = (0., 900., 2900., 4900.)
        return [self.fit(view, projection, direction, start, end + 100.)
                for start, end in zip(near, CASCADE_SPLITS)]


def atlas_matrix(index):
    """Native clip-to-texture transform, including D3D's top-down atlas Y."""
    x, y, width, height = CASCADE_TILES[index]
    full_width, full_height = SHADOW_SIZE
    return np.array([[width / full_width * .5, 0, 0, (x + width * .5) / full_width],
                     [0, -height / full_height * .5, 0, (y + height * .5) / full_height],
                     [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
