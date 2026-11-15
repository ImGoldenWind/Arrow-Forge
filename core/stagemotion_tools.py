"""Stage-finish command semantics, independent of Qt and file I/O.

Commands share the player command ABI researched for Char Skills. These six
names come from ASBR's own dispatch table, not guesses from stock values.
"""
import struct

from core.skill_research import SCHEMAS, Operand
from parsers.stagemotion_parser import _pack_entry

COMMANDS = {
    0x44: ('skill_operand_enemy_animation', 'motion_animation_hint'),
    0xEE: ('motion_face', 'motion_face_hint'),
    0x84: ('motion_caption', 'motion_caption_hint'),
    0x111: ('motion_skip', 'motion_skip_hint'),
    0x6F: ('motion_bg_on', 'motion_bg_hint'),
    0x70: ('motion_bg_off', 'motion_bg_hint'),
}
FRAME_RATE = 30
EVENT_LIMIT = 256


def command_operands(code):
    if code in (0x44, 0x84, 0xEE):
        return SCHEMAS[code] + ((Operand(0x48, 'i', 'motion_face_option'),) if code == 0xEE else ())
    if code == 0x70:
        return (Operand(0x38, 'i', 'motion_bg_option'),)
    if code in COMMANDS:
        return ()
    # Unknown commands keep the original editor's editable operands, explicitly
    # unnamed. Do not apply the Char Skills low-16-bit masking to an arbitrary u32.
    return (Operand(8, 'text', 'motion_raw_name'), Operand(0x38, 'I', 'motion_raw_integer'),
            Operand(0x4c, 'f', 'motion_raw_float'))


def command_bytes(entry):
    return bytes(_pack_entry(entry))


def apply_command_bytes(entry, data):
    """Refresh the public fields after changing ABI operands, retaining all else."""
    from parsers.stagemotion_parser import _parse_entry
    entry.update(_parse_entry(data))


def timeline_extent(entries):
    return max((e['frame'] + (e['val3'] if e['type_code'] == 0x84 and e['val3'] < 0x80000000 else 0)
                for e in entries), default=FRAME_RATE) or FRAME_RATE


def schedule_ticks(frame, ticks_per_second=3000):
    """22E8A8: unsigned 32-bit multiply then /30. No float approximation."""
    return ((frame * ticks_per_second) & 0xFFFFFFFF) // FRAME_RATE


def unique_stage_id(stages, base):
    names = {s['stage_id'] for s in stages}
    for index in range(len(names) + 2):
        suffix = '' if index == 0 else f'_{index}'
        candidate = base[:31 - len(suffix)] + suffix
        if candidate not in names:
            return candidate
