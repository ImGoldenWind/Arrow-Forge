"""Font authoring semantics established from ASBR's native loaders.

See docs/font-research.md. No menu layout or text shaping is simulated here.
"""
import math
import struct
from pathlib import Path, PurePosixPath
from decimal import Decimal

from parsers.font_xfbin_parser import resolve_icon_string


def icon_string(document, index, field):
    """The three string pointers are relative to their own u32 slot.

    Null path/chunk references inherit the last non-null value in file order.
    """
    if field not in (0, 1, 2):
        raise ValueError('Not an icon string reference')
    for record in reversed(document.icon_records[:index + 1]):
        relative = struct.unpack_from('>I', record.data, field * 4)[0]
        if relative:
            return resolve_icon_string(document, record.offset + field * 4 + relative)
        if field == 0:
            return ''
    return ''


def icon_reference_choices(document, index, field):
    """Existing file-backed targets, rebased for the selected pointer slot."""
    slot = document.icon_records[index].offset + field * 4
    targets = {}
    for record in document.icon_records:
        relative = struct.unpack_from('>I', record.data, field * 4)[0]
        if relative:
            target = record.offset + field * 4 + relative
            name = resolve_icon_string(document, target)
            if name:
                targets[target] = name
    return [(target - slot, name) for target, name in sorted(targets.items(), key=lambda x: x[1])]


def uint_text(text, maximum=0xffffffff):
    text = text.strip()
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    if not 0 <= value <= maximum:
        raise ValueError(f'Expected an integer in 0…{maximum}')
    return value


def finite_float32(text):
    value = float(text.strip())
    if not math.isfinite(value):
        raise ValueError('Expected a finite float32')
    return struct.pack('>f', value)


def glyph_advance_bytes(text):
    """Signed horizontal advance in 1/64 px (6500D4, constant 1210D54)."""
    units = Decimal(text.strip()) * 64
    if not units.is_finite() or units != units.to_integral_value():
        raise ValueError('Horizontal advance must be a multiple of 1/64 px')
    if not -32768 <= units <= 32767:
        raise ValueError('Horizontal advance must fit signed 16-bit 1/64 px storage')
    return struct.pack('>h', int(units))


def glyph_control_values(record):
    return dict(x=record.atlas_x, y=record.atlas_y,
                w=record.atlas_width, h=record.atlas_height,
                advance=format(struct.unpack_from('>h', record.data, 12)[0] / 64, '.9g'))


def glyph_record_data(document, index, values):
    rectangle = [uint_text(values[key], limit) for key, limit in
                 (('x', 65535), ('y', 65535), ('w', 255), ('h', 255))]
    data = glyph_rect_data(document.glyph_records[index], *rectangle, document.atlas)
    data[12:14] = glyph_advance_bytes(values['advance'])
    return data


def icon_control_values(record):
    values = {}
    for field in range(11):
        if field in (7, 8):
            value = format(struct.unpack_from('>f', record.data, field*4)[0], '.9g')
        else:
            value = struct.unpack_from('>i' if field in (3, 4, 5, 6) else '>I', record.data, field*4)[0]
        values[f'field_{field}'] = value
    return values


def icon_record_data(record, values):
    original = icon_control_values(record)
    data = bytearray(record.data)
    for field in range(11):
        key = f'field_{field}'
        value = values[key]
        if field in (9, 10) and isinstance(value, bool):
            word = original[key] if value == bool(original[key]) else int(value)
            struct.pack_into('>I', data, field*4, word)
        elif field in (7, 8):
            # Preserve untouched float bits, even non-finite/NaN payloads in
            # unusual files. Explicit replacement requires finite float32.
            if value != original[key]:
                data[field*4:field*4+4] = finite_float32(value)
        elif field in (3, 4, 5, 6):
            text = value.strip()
            struct.pack_into('>i', data, field*4, int(text, 16 if text.lower().startswith('0x') else 10))
        else:
            struct.pack_into('>I', data, field*4, uint_text(value))
    return data


def glyph_rect_data(record, x, y, width, height, atlas):
    """Only the verified bitmap rectangle; lookup/search bytes stay untouched."""
    for value, limit in ((x, 65535), (y, 65535), (width, 255), (height, 255)):
        if not 0 <= value <= limit:
            raise ValueError('Glyph rectangle exceeds its storage range')
    if width and height and (x + width > atlas.width or y + height > atlas.height):
        raise ValueError('Glyph rectangle exceeds atlas dimensions')
    data = bytearray(record.data)
    struct.pack_into('>HH', data, 4, x, y)
    data[20:22] = bytes((width, height))
    return data


def glyph_at(document, x, y):
    """Stable file-order hit selection, excluding empty/invalid rectangles."""
    if (document.atlas is None or not 0 <= x < document.atlas.width
            or not 0 <= y < document.atlas.height):
        return None
    for record in document.glyph_records:
        if (record.has_atlas_rect
                and record.atlas_x + record.atlas_width <= document.atlas.width
                and record.atlas_y + record.atlas_height <= document.atlas.height
                and record.atlas_x <= x < record.atlas_x + record.atlas_width
                and record.atlas_y <= y < record.atlas_y + record.atlas_height):
            return record.index
    return None


def icon_resource_variants(root, reference, language='eng'):
    """Discover concrete PLAT/LANG files, without guessing a platform mapping."""
    if root is None or not reference:
        return []
    parts = PurePosixPath(reference.replace('\\', '/')).parts
    if '..' in parts or ':' in reference or reference.startswith(('/', '\\')):
        raise ValueError('Unsafe resource path')
    parts = parts[1:] if parts and parts[0].lower() == 'data' else parts
    candidates = [Path(root)]
    for part in parts:
        if part in ('PLAT', 'LANG', '_SPEC'):
            candidates = [child for parent in candidates if parent.is_dir()
                          for child in parent.iterdir() if child.is_dir()]
        else:
            candidates = [parent / part for parent in candidates]
    return sorted((str(p.relative_to(root)).replace('\\', '/') for p in candidates
                   if p.is_file() and p.resolve().is_relative_to(Path(root).resolve())),
                  key=lambda name: ('WIN64' not in PurePosixPath(name).parts,
                                    language not in PurePosixPath(name).parts,
                                    'eng' not in PurePosixPath(name).parts, name))


def icon_crop(image, data):
    """Exact source rectangle. Invalid/out-of-image bounds are reported."""
    x, y, w, h = struct.unpack_from('>4i', data, 12)
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x+w > image.width or y+h > image.height:
        raise ValueError('Source rectangle is empty or outside the texture')
    return image.crop((x, y, x+w, y+h))
