"""Qt-independent CharViewer field validation and local resource catalogs.

Storage ranges are not game limits. Resource names come from the opened table
and from the selected viewer's NUCC index, without decoding models/animations.
"""
from functools import lru_cache
import math
from pathlib import Path
import struct

from parsers.charviewer_parser import _INT_FIELDS, _FLOAT_KEYS, _STR_KEYS

INTEGER_RANGES = {key: (-(1 << 31), (1 << 31) - 1) if fmt == 'i' else
                  (0, (1 << (32 if fmt == 'I' else 64)) - 1)
                  for _, key, fmt in _INT_FIELDS}
ANIMATION_KEYS = ('face_anim', 'idle_anim1', 'idle_anim2', *(
    f'pose{i}_{phase}' for i in range(1, 6) for phase in ('st', 'lp', 'ed')))
LIST_KEYS = ('object1', 'object2', 'object3', 'anim21', 'anim22_char_id',
             'anim23_char_tints', 'anim24_char_ids', 'anim25_model_ids', 'anim26', 'anim27')
MESSAGE_KEYS = ('custom_list_title', 'extra_costume', 'card_detail')


def parse_field(key, text):
    if key in _STR_KEYS:
        if '\0' in text:
            raise ValueError('NUL')
        text.encode('utf-8', errors='surrogateescape')
        return text
    if key in _FLOAT_KEYS:
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('finite float32 required')
        return struct.unpack('<f', struct.pack('<f', value))[0]
    low, high = INTEGER_RANGES[key]
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    if not low <= value <= high:
        raise ValueError('outside storage range')
    return value


def data_root(filepath, configured=''):
    if filepath:
        for parent in Path(filepath).resolve().parents:
            if (parent / 'spc_viewer').is_dir():
                return parent
    if configured:
        for candidate in (Path(configured), Path(configured) / 'data'):
            if (candidate / 'spc_viewer').is_dir():
                return candidate
    return None


@lru_cache(maxsize=32)
def _viewer_index(path, stamp, size):
    from parsers.xfbin_lib.binary_reader import BinaryReader, Endian
    from parsers.xfbin_lib.br_xfbin import BrNuccHeader, BrChunkTable
    with open(path, 'rb') as stream:
        header = stream.read(68)
        if len(header) < 68 or header[:4] != b'NUCC':
            raise ValueError('Invalid viewer XFBIN header')
        length = 28 + struct.unpack_from('>I', header, 16)[0]
        length += 8 * struct.unpack_from('>I', header, 64)[0]
        if not 68 <= length <= min(size, 64 * 1024 * 1024):
            raise ValueError('Invalid viewer index size')
        stream.seek(0)
        data = stream.read(length)
    reader = BinaryReader(data, endianness=Endian.BIG)
    reader.read_struct(BrNuccHeader)
    table = reader.read_struct(BrChunkTable)
    # BrChunkTable uses counts as loop bounds; reject malformed oversized arrays.
    result = {}
    for item in table.chunk_maps:
        kind, _, name = table.get_props_from_chunk_map(item)
        if name:
            result.setdefault(kind, set()).add(name)
    return {key: tuple(sorted(values)) for key, values in result.items()}


def viewer_index(root, viewer_id):
    if root is None or not viewer_id:
        return {}, ''
    # Names are identifiers, not filesystem paths supplied by a document.
    if Path(viewer_id).name != viewer_id or '/' in viewer_id or '\\' in viewer_id or ':' in viewer_id:
        return {}, ''
    path = root / 'spc_viewer' / (viewer_id + '.xfbin')
    try:
        stat = path.stat()
        return _viewer_index(str(path), stat.st_mtime_ns, stat.st_size), str(path)
    except (OSError, ValueError, IndexError, struct.error, UnicodeError):
        return {}, str(path)


def field_choices(entries, key, index=None):
    index = index or {}
    if key in ANIMATION_KEYS:
        # Animation names are shared only within the same asset bundle.
        values = set(index.get('nuccChunkAnm', ()))
        values.update(e.get(key, '') for e in entries)
    else:
        values = {e.get(key, '') for e in entries}
        if key == 'resource_138':
            values.update(index.get('nuccChunkClump', ()))
    return tuple((value, value) for value in sorted(values) if value)


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def clamp_fov(value, lower, upper):
    """Original sequential COMISS clamps at RVA 0x4AB92C, in float32."""
    value, lower, upper = map(f32, (value, lower, upper))
    if not value >= lower:
        value = lower
    if value > upper:
        value = upper
    return value


def camera_offset(entry):
    """Camera minus look-at point in the native local Y/Z plane, in float32."""
    return (f32(entry['cam_zoom'] - entry['cam_unk']),
            f32(entry['cam_pos_z'] - entry['cam_y']))
