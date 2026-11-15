"""Stage Info resource choices and lossless field conversions.

Native layout evidence is recorded in docs/stage-info-research.md.
"""
from pathlib import Path
from decimal import Decimal
import math
import struct


COLOR_OFFSETS = (0, 4, 8, 12, 16, 20, 40, 60)
SCALAR_FIELDS = (
    (24, 'stage_shadow_x', True), (28, 'stage_shadow_y', True),
    (32, 'stage_shadow_z', True), (36, 'stage_shadow_mode', False),
    (44, 'stage_fog_option', False), (48, 'stage_fog_near', True),
    (52, 'stage_fog_far', True), (56, 'stage_fog_strength', True),
    (64, 'stage_screen_filter', False), (68, 'stage_filter_x', True),
    (72, 'stage_filter_y', True), (76, 'stage_filter_strength', True),
    (80, 'stage_bloom_mode_stored', False), (84, 'stage_bloom_value_1', True),
    (88, 'stage_bloom_value_stored', True), (92, 'stage_bloom_value_3', True),
)

COLOR_LABELS = (
    'stage_ambient_normal', 'stage_ambient_alternate', 'stage_ambient_group_2',
    'stage_colour_slot_4', 'stage_light_normal', 'stage_light_alternate',
    'stage_shadow_colour', 'stage_fog_colour',
)


def parameter_hint(offset):
    if offset in (24, 28, 32):
        return 'stage_shadow_direction_hint'
    if offset in (36, 40):
        return 'stage_shadow_effect_hint'
    if offset in (44, 48, 52, 56, 60):
        return 'stage_fog_effect_hint'
    if offset in (64, 68, 72, 76):
        return 'stage_filter_effect_hint'
    if offset in (80, 84, 88, 92):
        return 'stage_runtime_override_hint'
    if offset == 12:
        return 'stage_colour_unresolved_hint'
    return 'stage_character_light_hint'


def packed_color_rgba(data):
    """Native 6DCC90 expands MSB first; disk order is A, B, G, R."""
    return tuple(reversed(data[:4]))


def rgba_packed_color(rgba):
    return bytes(reversed(rgba))


def ascii_text(value, *, required=False):
    if (required and not value.strip()) or '\0' in value:
        raise ValueError('stage_invalid_string')
    try:
        value.encode('ascii')
    except UnicodeEncodeError:
        raise ValueError('stage_invalid_string') from None
    return value


def numeric_value(text, is_float, *, hexadecimal=False):
    try:
        value = float(text) if is_float else int(text, 16 if hexadecimal else 10)
        if is_float:
            if not math.isfinite(value):
                raise ValueError()
            struct.pack('<f', value)
        elif not 0 <= value <= 0xFFFFFFFF:
            raise ValueError()
        return value
    except (ValueError, OverflowError, struct.error):
        raise ValueError('stage_invalid_float' if is_float else 'stage_invalid_uint') from None


def float32_text(value):
    """Shortest readable decimal that retains the original float32 bits."""
    if not math.isfinite(value):
        return str(value)
    raw = struct.pack('<f', value)
    for precision in range(1, 10):
        text = format(value, f'.{precision}g')
        try:
            matches = struct.pack('<f', float(text)) == raw
        except OverflowError:
            continue
        if matches:
            if 'e' in text and 1e-6 <= abs(value) < 1e9:
                text = format(Decimal(text), 'f')
            return text
    return format(value, '.9g')


def data_root(source):
    if not source:
        return None
    return next((p for p in Path(source).resolve().parents if p.name.casefold() == 'data'), None)


def game_path(path, source=None):
    """Convert an extracted resource to its data/... path, never to a drive path."""
    path = Path(path).resolve()
    root = data_root(source) or data_root(path)
    if root is None:
        raise ValueError('stage_outside_data')
    try:
        return 'data/' + path.relative_to(root).as_posix()
    except ValueError:
        raise ValueError('stage_outside_data') from None


def resolve_resource(path, source):
    value = path.replace('\\', '/')
    root = data_root(source)
    if root is None or not value.casefold().startswith('data/'):
        return None
    target = (root / value[5:]).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def resource_clumps(path):
    """Read only the NUCC chunk table, without decoding meshes or textures."""
    from parsers.xfbin_lib.binary_reader import BinaryReader, Endian
    from parsers.xfbin_lib.br_xfbin import BrNuccHeader, BrChunkTable
    with open(path, 'rb') as stream:
        header = stream.read(28)
        if len(header) != 28 or header[:4] != b'NUCC':
            raise ValueError('Invalid NUCC header')
        table_size = struct.unpack_from('>I', header, 16)[0]
        counts = stream.read(40)
        if len(counts) != 40:
            raise ValueError('Truncated NUCC table')
        indices, references = struct.unpack_from('>II', counts, 32)
        table_data = counts + stream.read(max(0, table_size - 40) + indices * 4 + references * 8)
    with BinaryReader(header + table_data, Endian.BIG, 'cp932') as reader:
        reader.read_struct(BrNuccHeader)
        table = reader.read_struct(BrChunkTable)
    return list(dict.fromkeys(name for kind, _, name in (
        table.get_props_from_chunk_map(m) for m in table.chunk_maps
    ) if kind == 'nuccChunkClump'))


def new_clump(path, name):
    return dict(xfbin_path=path, clump_name=name, unk_name='', unk2_name='',
                skip_data=b'\0' * 16, val1=0x3C, val2=0x78)
