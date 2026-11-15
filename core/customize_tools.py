"""Qt-independent CustomizeDefault field validation and native semantics."""
import math
import struct

from core.story_tools import character_name
from core.translations import ui_text
from parsers.customizedefaultparam_parser import FLOAT_FIELDS, _encoded

FLOAT_KEYS = tuple(key for _, key in FLOAT_FIELDS)
TRANSFORM_KEYS = ('pos_x', 'pos_y', 'unk', 'scale')
FIELD_KEYS = ('char_code', 'slot', *FLOAT_KEYS)
SCALE_MIN = struct.unpack('<f', struct.pack('<f', 1e-6))[0]
SCALE_MAX = struct.unpack('<f', bytes.fromhex('ffff7f7f'))[0]


def f32(value):
    try:
        return struct.unpack('<f', struct.pack('<f', value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def parse_field(key, text):
    if key == 'char_code':
        _encoded(text)
        return text
    if key == 'slot':
        value = int(text, 16 if text.lower().startswith('0x') else 10)
        if not 0 <= value <= 0xffffffff:
            raise ValueError('uint32 required')
        return value
    value = f32(float(text))
    if not math.isfinite(value):
        raise ValueError('finite float32 required')
    return value


def slot_name(value):
    return ui_text(f'customize_slot_{value}') if value in (0, 1, 2) else ui_text('customize_slot_custom', value=value)


def character_choices(entries, catalog=()):
    return [(code, f'{code} — {character_name(code)}')
            for code in sorted(set(catalog) | {e['char_code'] for e in entries}) if code]


def effective_scale(value):
    """Sequential COMISS clamps used by RVA 5F9888 / 5F9A68 (finite input)."""
    value = f32(value)
    if value <= SCALE_MIN:
        value = SCALE_MIN
    if SCALE_MAX <= value:
        value = SCALE_MAX
    return value


def rotation_tick(degrees):
    """Native degree -> signed 32-bit editing tick, RVA 5F15E0 / 5F071C."""
    value = f32(f32(degrees) * f32(65536 / 360))
    value = f32(value + (.5 if degrees >= 0 else -.5))
    # CVTTSS2SI returns the integer-indefinite word for out-of-range input.
    return int(value) if math.isfinite(value) and -(1 << 31) <= value < (1 << 31) else -(1 << 31)


def edit_rotation(degrees):
    """Rotation stored back by the edit screen, in degrees (RVA 5F071C)."""
    return f32(f32(rotation_tick(degrees)) * f32(360 / 65536))


def transform(entry):
    values = tuple(entry[key] for key in TRANSFORM_KEYS)
    return values if all(math.isfinite(v) for v in values) else None


def entry_issues(entry, entries, catalog=()):
    issues = []
    if not entry['char_code']:
        issues.append(ui_text('customize_missing_character'))
    elif catalog and entry['char_code'] not in catalog:
        issues.append(ui_text('customize_unknown_character'))
    if sum(e['char_code'] == entry['char_code'] and e['slot'] == entry['slot'] for e in entries) > 1:
        issues.append(ui_text('customize_duplicate_pair'))
    slots = {e['slot'] for e in entries if e['char_code'] == entry['char_code']}
    missing = set((0, 1, 2)) - slots
    if missing:
        issues.append(ui_text('customize_missing_slots', slots=', '.join(slot_name(i) for i in sorted(missing))))
    if entry['slot'] not in (0, 1, 2):
        issues.append(ui_text('customize_unknown_slot'))
    if effective_scale(entry['scale']) != entry['scale']:
        issues.append(ui_text('customize_clamped', value=str(effective_scale(entry['scale']))))
    return issues
