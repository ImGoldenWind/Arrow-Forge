"""User-facing command operands established from the pinned ASBR executable.

Offsets are command-relative, including the 0xC8-byte base. Evidence and limits:
docs/char-skills-research.md. Unlisted bytes are never inferred from stock zeros.
"""
from dataclasses import dataclass
import math
import struct


@dataclass(frozen=True)
class Operand:
    offset: int
    kind: str
    label: str
    choices: tuple = ()
    slider: tuple | None = None

    def read(self, raw):
        if self.kind == 'text':
            return raw[self.offset:self.offset + 32].split(b'\0')[0].decode('ascii', 'replace')
        return struct.unpack_from('<' + self.kind, raw, self.offset)[0]

    def encode(self, value):
        if self.kind == 'text':
            data = str(value).encode('ascii')
            if len(data) > 32 or b'\0' in data:
                raise ValueError('ASCII, 32 characters maximum')
            return data.ljust(32, b'\0')
        value = float(value) if self.kind == 'f' else int(value, 0) if isinstance(value, str) else int(value)
        if self.kind == 'f' and not math.isfinite(value):
            raise ValueError('A finite number is required')
        return struct.pack('<' + self.kind, value)


def i(offset, label, choices=()):
    return Operand(offset, 'i', label, tuple(choices))


def f(offset, label, slider=None):
    return Operand(offset, 'f', label, slider=slider)


def text(offset, label, choices=()):
    return Operand(offset, 'text', label, tuple(choices))


DURATION = i(0x38, 'duration')
SPEED = f(0x4C, 'speed', (0, 4))
SCALE = f(0x4C, 'scale', (0, 4))
# Three stored sizes are X, Z, Y at the native box setter; they are half extents.
BOX = (i(0x38, 'half_x'), i(0x3C, 'half_z'), i(0x40, 'half_y'))
SCHEMAS = {
    0x04: (i(0x38, 'jump_speed'),),
    0x05: (i(0x38, 'vertical_speed'),),
    0x06: (i(0x38, 'forward_speed'), i(0x3C, 'duration')),
    0x07: (i(0x38, 'forward_speed'), i(0x3C, 'duration'), f(0x4C, 'interpolation')),
    0x0B: (f(0x4C, 'gravity'),),
    0x0F: (i(0x38, 'vertical_speed'), f(0x4C, 'gravity')),
    0x1A: (i(0x38, 'damage_direction', ((0, 'facing'), (1, 'from_enemy'))),),
    0x2A: BOX + (i(0x44, 'duration'),),
    0x44: (text(8, 'enemy_animation'), i(0x38, 'start_frame'), i(0x3C, 'end_frame'), SPEED),
    0x45: (text(8, 'object'),),
    0x46: (text(8, 'object'),),
    0x47: (DURATION, SCALE),
    0x48: (SPEED,), 0x49: (SPEED,),
    0x59: (i(0x38, 'body_radius'),),
    0x5B: (text(8, 'hurtbox'),),
    0x5C: (text(8, 'hurtbox'),),
    0x5D: (text(8, 'hurtbox'),) + BOX,
    0x5E: (text(8, 'hurtbox'),),
    0x5F: (text(8, 'hurtbox'), i(0x38, 'offset_x'), i(0x3C, 'offset_y'), i(0x40, 'offset_z')),
    0x60: (text(8, 'hurtbox'),),
    0x67: (text(8, 'invulnerability', (('', 'all'), ('THROW', 'throws'), ('BLOW', 'blows'), ('SKILL', 'skills'))),),
    0x68: (text(8, 'invulnerability', (('', 'all'), ('THROW', 'throws'), ('BLOW', 'blows'), ('SKILL', 'skills'))),),
    0x6C: (DURATION,),
    0x6D: (i(0x38, 'color_r'), i(0x3C, 'color_g'), i(0x40, 'color_b'), f(0x4C, 'fog_strength')),
    0x6E: (DURATION,),
    0x71: (i(0x38, 'duration'), f(0x4C, 'brightness', (0, 2))),
    0x72: (DURATION,),
    0x7E: (text(0x54, 'sound_id'),),
    0x80: (i(0x38, 'voice_id'),),
    0x81: (text(0x54, 'voice_name'),),
    0x84: (text(8, 'caption'), DURATION),
    0x85: (i(0x38, 'vibration', ((0, 'level_0'), (1, 'level_1'), (2, 'level_2'), (3, 'level_3'))),),
    0x8E: (i(0x38, 'loop_count'),),
    0x9C: (text(8, 'stand_mode', (('STAND_MODE', 'stand_on'), ('NO_STAND_MODE', 'stand_off'))),
           i(0x38, 'offset_x'), i(0x3C, 'offset_y'), i(0x40, 'offset_z'), i(0x48, 'duration')),
    0x9D: (text(8, 'stand_mode', (('STAND_MODE', 'stand_on'), ('NO_STAND_MODE', 'stand_off'))), i(0x48, 'duration')),
    0xA1: (text(8, 'bone'), i(0x38, 'gion_number'), i(0x3C, 'offset_x'), i(0x40, 'offset_y'), SCALE, text(0x54, 'gion_name')),
    0xA2: (i(0x38, 'gion_number'), i(0x3C, 'screen_x'), i(0x40, 'screen_y'), SCALE, text(0x54, 'gion_name')),
    0xA3: (text(0x54, 'gion_name'),),
    0xA9: (f(0x4C, 'interpolation'),),
    0xAB: (f(0x4C, 'opacity', (0, 1)),),
    0xAD: (DURATION,),
    0xB1: (i(0x38, 'particle_id'),), 0xB2: (i(0x38, 'particle_id'),),
    0xB4: (text(8, 'face_animation'), i(0x38, 'start_frame')),
    0xBD: (f(0x4C, 'life_change'),), 0xBE: (f(0x4C, 'gauge_change'),),
    0xBF: (f(0x4C, 'life_change'),), 0xC0: (f(0x4C, 'gauge_change'),),
    0xC1: (text(8, 'event_name'),),
    0xD5: (text(0x54, 'voice_name'), f(0x4C, 'volume', (0, 1))),
    0xD6: (DURATION,),
    0xD9: (text(8, 'caption'), DURATION),
    0xED: (DURATION,),
    0xEB: (DURATION,),
    0xEC: (i(0x38, 'color_r'), i(0x3C, 'color_g'), i(0x40, 'color_b'), f(0x4C, 'fog_strength')),
    0xEE: (text(8, 'face_animation'), i(0x38, 'start_frame')),
    0xF3: (text(8, 'shake_size', (('SMALL', 'small'), ('MIDDLE', 'medium'), ('LARGE', 'large'))), DURATION, f(0x4C, 'shake_strength')),
    0xF4: (text(8, 'shake_size', (('SMALL', 'small'), ('MIDDLE', 'medium'), ('LARGE', 'large'))), DURATION, f(0x4C, 'shake_strength')),
    0xF5: (text(8, 'enemy_animation'), i(0x38, 'start_frame'), i(0x3C, 'end_frame'), SPEED),
    0xFA: (i(0x38, 'start_frame'),), 0xFB: (i(0x38, 'end_frame'),),
    0xFC: (text(8, 'clump'),),
    0xFD: (text(8, 'mission_tag'), i(0x38, 'side', ((0, 'player_1'), (1, 'player_2'), (2, 'both')))),
    0x100: (SPEED,), 0x101: (SPEED,),
    0x114: (text(8, 'lip_animation'), i(0x38, 'start_frame')),
    0x115: (text(8, 'lip_animation'), i(0x38, 'start_frame')),
}
for opcode in (0x20, 0x22, 0x24, 0x26, 0x28):
    SCHEMAS[opcode] = BOX + (text(0x54, 'hit_coordinate'),)
for opcode in (0x18, 0x19, 0x110):
    SCHEMAS[opcode] = (text(8, 'move_direction', (('', 'facing'), ('PULL', 'pull'), ('PUSH', 'push'))),
        i(0x38, 'move_distance'), i(0x3C, 'vertical_distance'), i(0x40, 'duration'),
        i(0x44, 'stop_at_enemy'), f(0x4C, 'stage_collision'))
for opcode in (0x1B, 0x1C):
    SCHEMAS[opcode] = (text(8, 'bone'),)
for opcode in (0xC4, 0xC5, 0xC6, 0xC9, 0xCA):
    SCHEMAS[opcode] = (i(0x38, 'negative_limit'), i(0x3C, 'positive_limit'))
for opcode in (0x74, 0x75, 0x76, 0x7A, 0x7B):
    SCHEMAS[opcode] = (text(8, 'effect_anchor'), i(0x38, 'effect_category'), SCALE)

# Directly observed return-one dispatches in all 110 sampled player vtables.
# Other command processors/plugins are deliberately not ruled out.
RETURN_ONLY = frozenset((0x08, 0x09, 0x14, 0x15, 0x2D, 0x2E, 0x2F,
    0x35, 0x37, 0x38, 0x43, 0x51, 0x52, 0x69, 0x6A, 0x6B, 0x6D, 0x7D,
    0x82, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B, 0x8C, 0x8D,
    0xA5, 0xA6, 0xA7, 0xA8, 0xB3, 0xD3, 0xD4, 0xD7, 0xD8, 0xDC, 0xEC, 0x113))


def operands(opcode, damage=False):
    result = SCHEMAS.get(int(opcode) & 0xFFFF, ())
    if damage:
        result += (Operand(0xC8 + 0x6C, 'I', 'damage'), Operand(0xC8 + 0x70, 'I', 'guard_damage'),
                   f(0xC8 + 0x60, 'hit_x'), f(0xC8 + 0x64, 'hit_y'), i(0xC8 + 0x68, 'push'))
    return result


def display_value(value):
    return format(value, '.9g') if isinstance(value, float) else str(value)
