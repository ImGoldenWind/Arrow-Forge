"""Runtime-derived Anmofs key selection and local transform for previews."""
from __future__ import annotations

import numpy as np
import re
from pathlib import Path


def is_situation_finish_offsets(path):
    """22EAA8 loads the shared Xcmnsf bank into each receiver's offset list."""
    return Path(path or '').name.lower() == 'xcmnsf_anmofs.xfbin'


def key_tick(frame, rate=30):
    """33A230: SSE f32(frame * engine_rate * (1/30)), truncated to i32."""
    value = np.float32(np.float32(np.float32(frame) * np.float32(rate)) * np.float32(1 / 30))
    return int(value) if -2147483648 <= value < 2147483648 else -2147483648


def active_offset(entries, frame, rate=30):
    """Native 33A230: greatest eligible *stored* frame; first tie wins."""
    best = None
    for index, entry in enumerate(entries):
        if entry.frame >= 0 and key_tick(entry.frame, rate) <= frame and (best is None or entry.frame > entries[best].frame):
            best = index
    return best


def receiver_code(chunk):
    """Stock naming convention used by loader's '*_<receiver>*' filter.

    Header +40 is copied but does not select the receiving character. Some
    stock headers disagree with the name. Unknown names fall back to +40.
    """
    suffix = chunk.chunk_name.rsplit('_', 1)[-1]
    return suffix if re.fullmatch(r'[0-9][A-Za-z0-9]{5}d?', suffix) else chunk.characode


def receiver_model_code(chunk):
    code = receiver_code(chunk)
    return code[:-1] if len(code) == 7 and code.endswith('d') else code


def key_states(entries):
    """Disabled and shadowed keys, without changing stored order or values."""
    seen = set()
    result = []
    for entry in entries:
        state = 'disabled' if entry.frame < 0 else 'duplicate' if entry.frame in seen else 'hold'
        result.append(state)
        if entry.frame >= 0:
            seen.add(entry.frame)
    return result


def offset_matrix(entry, mirrored=False):
    """Display an offset in the model viewer's (X,Z,-Y) coordinate system."""
    from parsers.model_xfbin_parser import _rotation_matrix_x, _rotation_matrix_y, _rotation_matrix_z
    if entry is None:
        return np.identity(4, dtype=np.float32)
    x, y, z = entry.value_1, entry.value_2, entry.value_3
    rx, ry, rz = entry.value_4, entry.value_5, entry.value_6
    if mirrored:
        x, rx, rz = -x, -rx, -rz
    # Native 215850 (yaw, pitch, roll) -> 6C93F0: Y * X * Z.
    # This differs from the model coordinate node's own Euler convention.
    game = _rotation_matrix_y(ry) @ _rotation_matrix_x(rx) @ _rotation_matrix_z(rz)
    game[:3, 3] = (x, y, z)
    basis = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=np.float32)
    return basis @ game @ basis.T


def receiver_scene_matrix(entry, mirrored=False):
    """Place the receiver opposite the attacker in the local paired preview.

    Clip skeletons share a canonical forward direction. Facing belongs to the
    scene, not the stored offset: rotate the receiver about its own vertical
    axis before applying the key. Keep the translated anchor unchanged.
    """
    facing = np.diag([-1, 1, -1, 1]).astype(np.float32)
    return offset_matrix(entry, mirrored) @ facing
