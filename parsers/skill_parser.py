import struct
import math
import copy
import os
import tempfile

# Constants
MOT_GLOBAL_HDR  = 0x2C   # bytes before first PL_ANM entry
MOT_HDR_SIZE    = 0x9C   # bytes per PL_ANM entry header
MOT_SUB_SIZE    = 0xC8   # bytes per subentry (command/hitbox)
MOT_DMGID_SIZE  = 0x1F0  # bytes for standalone DAMAGE_ID block

SKL_ENTRY_SIZE  = 0x81   # 129 bytes per skill slot entry
SKL_HDR_SIZE    = 4
SKL_SLOT_SZ     = 64     # slot_name field
SKL_XFBIN_SZ    = 32     # xfbin_file field
SKL_SKILL_SZ    = 33     # skill_id field

LOAD_ENTRY0_SZ  = 68     # first load entry (no flag)
LOAD_ENTRY_SZ   = 72     # regular load entries
LOAD_HDR_SZ     = 4

DATA_TYPE_MAP = {
    32:  "BONE",
    48:  "DAMAGE_ID",
    68:  "DMG",
    132: "SUBTITLE",
    180: "FACE",
    238: "FACE2",
    241: "MODEL",
}

# Type names for standalone prm_load.bin.xfbin entries (from prm_load.bt)
PRMLOAD_TYPE_NAMES = {
    3:  'ANIMATIONS',
    6:  'GHA',
    9:  'MODEL',
    10: 'ACCESSORY',
    11: 'EFFECTS',
    13: 'PRM',
    14: 'MISC',
}

# Full ME_* function map from prm_love_deluxe (byte at subentry +0x34)
FUNC_MAP_1B = {
    0x00:"ME_ENEMY_CTRL_ON",       0x01:"ME_ENEMY_CTRL_OFF",
    0x02:"ME_FLOATING_ON",         0x03:"ME_FLOATING_OFF",
    0x04:"ME_JUMPVEL_SET",         0x05:"ME_SET_VERTICAL_SPEED",
    0x06:"ME_FWDVELOCITY_SET",     0x07:"ME_FWDVELOCITY_SET_INTERP",
    0x08:"ME_BRAKE_SET",           0x09:"ME_BRAKE_RESET",
    0x0A:"ME_WARP_AROUND_ENEMY",   0x0B:"ME_GRAVITY_SET",
    0x0C:"ME_VELOCITY_RESET",      0x0D:"ME_GRAVITY_RESET",
    0x0E:"ME_VERTICAL_VELOCITY_RESET", 0x0F:"ME_FLIGHT_BEGIN",
    0x10:"ME_FLIGHT_END",          0x11:"ME_HOMING_SET",
    0x12:"ME_WARP_AROUND_ENEMY_RESERVE", 0x13:"ME_WARP_AROUND_ENEMY_EXEC",
    0x14:"ME_ATK_AIR_HOMING_ON",   0x15:"ME_ATK_AIR_HOMING_OFF",
    0x16:"ME_HOMING_MOVE_BEGIN",   0x17:"ME_HOMING_AIR",
    0x18:"ME_MOVE_DISTANCE",       0x19:"ME_MOVE_DISTANCE_ENEMY",
    0x1A:"ME_DAMAGEDIRC_SET",      0x1B:"ME_DAMAGEDIRC_SET_COORD",
    0x1C:"ME_DAMAGEDIRC_SET_COORD_REV", 0x1D:"ME_DISPDIRC_REVERSE",
    0x1E:"ME_LOOK_ENEMY",          0x1F:"ME_ENEMY_DISPDIRC_REVERSE",
    0x20:"ME_ATKHIT_ON",           0x21:"ME_ATKHIT_OFF",
    0x22:"ME_ATKHIT2_ON",          0x23:"ME_ATKHIT2_OFF",
    0x24:"ME_ATKHIT3_ON",          0x25:"ME_ATKHIT3_OFF",
    0x26:"ME_ATKHIT4_ON",          0x27:"ME_ATKHIT4_OFF",
    0x28:"ME_ATKHIT5_ON",          0x29:"ME_ATKHIT5_OFF",
    0x2A:"ME_ATK_HIT_SIZE",        0x2B:"ME_ATK_HIT_HEIGHT",
    0x2C:"ME_DAMAGE_VALUE_SET",    0x2D:"ME_ATK_HOMING_ON",
    0x2E:"ME_ATK_HOMING_OFF",      0x2F:"ME_ATK_HOMING_ALLRANGE",
    0x30:"ME_DAMAGE_SET_DIRECT",   0x31:"ME_DAMAGE_SET_DIRECT_ME",
    0x32:"ME_DAMAGE_SET_DIRECT_BOTH", 0x33:"ME_DAMAGE_INFO",
    0x34:"ME_ADD_COMBO_COUNTER",   0x35:"ME_ENTRY_PROJECTILE",
    0x36:"ME_ENTRY_SKILL_ANY",     0x37:"ME_ENTRY_SKILL_ANY_COORD_TO_ENEMY3D",
    0x38:"ME_ENTRY_SKILL_ANY_ENEMY_TO_ENEMY3D", 0x39:"ME_DOWN_ENEMY_AT_FOOTPOS",
    0x3A:"ME_ENEMY_DISP_ON",       0x3B:"ME_ENEMY_DISP_OFF",
    0x3C:"ME_ENEMY_MOVE_SELF",     0x3D:"ME_ENEMY_MOVE_ENEMY_FOOTPOS",
    0x3E:"ME_MOVE_CORRECT_T0_POS", 0x3F:"ME_SET_ENEMY_POS_DIRC_BY_ANM",
    0x40:"ME_FORCE_MOVE_TO_CENTER",0x41:"ME_DOWN_LOOP_ENEMY",
    0x42:"ME_ACT_FALL",            0x43:"ME_ENEMY_SET_ACTION",
    0x44:"ME_ENEMY_SET_ANIMATION", 0x45:"ME_DRAWOBJ_DISABLE",
    0x46:"ME_DRAWOBJ_ENABLE",      0x47:"ME_SCALE_CHANGE",
    0x48:"ME_ANM_SPEED_SET",       0x49:"ME_ENEMY_ANM_SPEED_SET",
    0x4A:"ME_ANMCAMERA_ON",        0x4B:"ME_ANMCAMERA_OFF",
    0x4C:"ME_ANMCAMERA_REVERSE_ON",0x4D:"ME_ANMCAMERA_REVERSE_OFF",
    0x4E:"ME_SMASHCAMERA_ON",      0x4F:"ME_SMASHCAMERA_OFF",
    0x50:"ME_SHAKE_CAMERA",        0x51:"ME_SHAKE_CAMERA_VERTICAL",
    0x52:"ME_SHAKE_CAMERA_HORIZONTAL", 0x53:"ME_SHAKE_CAMERA_STOP",
    0x54:"ME_COMBOCAMERA_ON",      0x55:"ME_COMBOCAMERA_OFF",
    0x56:"ME_RESET_CAMERA",        0x57:"ME_BODHIT_ON",
    0x58:"ME_BODHIT_OFF",          0x59:"ME_BODHIT_SET_SIZE",
    0x5A:"ME_BODHIT_RESET_SIZE",   0x5B:"ME_DMGHIT_ON",
    0x5C:"ME_DMGHIT_OFF",          0x5D:"ME_DMGHIT_SET_SIZE",
    0x5E:"ME_DMGHIT_RESET_SIZE",   0x5F:"ME_DMGHIT_SET_OFFSET",
    0x60:"ME_DMGHIT_RESET_OFFSET", 0x61:"ME_ATEMI_ON",
    0x62:"ME_ATEMI_OFF",           0x63:"ME_LANDHIT_BEGIN",
    0x64:"ME_LANDHIT_END",         0x65:"ME_GUARDPOINTHIT_ON",
    0x66:"ME_GUARDPOINTHIT_OFF",   0x67:"ME_INVINCIBLE_ON",
    0x68:"ME_INVINCIBLE_OFF",      0x69:"ME_GLARE_NORMAL",
    0x6A:"ME_GLARE_NEAR",          0x6B:"ME_GLARE_ANIM",
    0x6C:"ME_FOG_CHANGE_BEGIN",    0x6D:"ME_FOG_CHANGE_COLOR",
    0x6E:"ME_FOG_CHANGE_RESET",    0x6F:"ME_BG_DRAW_ON",
    0x70:"ME_BG_DRAW_OFF",         0x71:"ME_BG_BRIGHT_SET",
    0x72:"ME_BG_BRIGHT_RESET",     0x73:"ME_ENTRY_EFF_IMPACTLAND",
    0x74:"ME_ENTRY_EFF_CTG",       0x75:"ME_ENTRY_EFF_CTG_SYNC",
    0x76:"ME_ENTRY_EFF_CTG_GROUND",0x77:"ME_ENABLE_DRAW_BODYEFF",
    0x78:"ME_DISABLE_DRAW_BODYEFF",0x79:"ME_DESTROY_EFF",
    0x7A:"ME_ENTRY_EFF_CTG_ADD_1", 0x7B:"ME_ENTRY_EFF_CTG_SYNC_ADD_1",
    0x7C:"ME_DESTROY_EFF_ADD_1",   0x7D:"ME_SE_ON_CTG",
    0x7E:"ME_SE_ON_ID",            0x7F:"ME_THROW_VOICE1",
    0x80:"ME_VOICE",               0x81:"ME_VOICE_ON_ID",
    0x82:"ME_DISABLE_ATTACK_VOICE",0x83:"ME_DISABLE_COMBO_LAST_SE",
    0x84:"ME_SET_CAPTION",         0x85:"ME_PAD_VIBRATION",
    0x86:"ME_ENABLE_ATTACK_PRIORITY",  0x87:"ME_DISABLE_ATTACK_PRIORITY",
    0x88:"ME_ENABLE_ATTACK_PRIORITY_COMMON", 0x89:"ME_DISABLE_ATTACK_PRIORITY_COMMON",
    0x8A:"ME_SKILL_DAMAGE_RATE",   0x8B:"ME_CANCEL_OP_ADD",
    0x8C:"ME_CANCEL_OP_SUB",       0x8D:"ME_CANCEL_OP_SET",
    0x8E:"ME_MOTION_LOOP_COUNT_SET",0x8F:"ME_STAND_DRAW_ON",
    0x90:"ME_STAND_DRAW_OFF",      0x91:"ME_STAND_FOLLOW_ON",
    0x92:"ME_STAND_FOLLOW_OFF",    0x93:"ME_STAND_MOT_FOLLOW_ON",
    0x94:"ME_STAND_MOT_FOLLOW_OFF",0x95:"ME_STAND_ATTACK_START",
    0x96:"ME_STAND_ATTACK_END",    0x97:"ME_STAND_APPEARANCE",
    0x98:"ME_STAND_DISAPPEARANCE", 0x99:"ME_STAND_GOBACK",
    0x9A:"ME_STAND_ACTION_ON",     0x9B:"ME_STAND_ACTION_OFF",
    0x9C:"ME_STAND_OFFSET_SET",    0x9D:"ME_STAND_OFFSET_RESET",
    0x9E:"ME_STAND_RESET_POS",     0x9F:"ME_STAND_BODYHIT_SEPARATE_ON",
    0xA0:"ME_STAND_BODYHIT_SEPARATE_OFF", 0xA1:"ME_GION_BEGIN",
    0xA2:"ME_GION_BEGIN_2D",       0xA3:"ME_GION_END",
    0xA4:"ME_PROVOKE_GION",        0xA5:"ME_BTLWIN_GION",
    0xA6:"ME_PROVOKE_SUCCESS",     0xA7:"ME_GAME_SPEED_CHANGE",
    0xA8:"ME_GAME_SPEED_RESET",    0xA9:"ME_CAMERA_INTERP_ON",
    0xAA:"ME_CAMERA_INTERP_OFF",   0xAB:"ME_OPACITY_SET",
    0xAC:"ME_OPACITY_RESET",       0xAD:"ME_CTRL_STOP_ON",
    0xAE:"ME_CTRL_STOP_OFF",       0xAF:"ME_SUPERARMOR_ON",
    0xB0:"ME_SUPERARMOR_OFF",      0xB1:"ME_PARTICLE_GENERATOR_ON",
    0xB2:"ME_PARTICLE_GENERATOR_OFF", 0xB3:"ME_MOVE_TO_OPPONENT",
    0xB4:"ME_FACE_ANM_SET",        0xB5:"ME_PUT_FEET_STIRRUP_L_ON",
    0xB6:"ME_PUT_FEET_STIRRUP_L_OFF", 0xB7:"ME_PUT_FEET_STIRRUP_R_ON",
    0xB8:"ME_PUT_FEET_STIRRUP_R_OFF", 0xB9:"ME_HOLD_REINS_ON",
    0xBA:"ME_HOLD_REINS_OFF",      0xBB:"ME_PICKUP_CORPSE",
    0xBC:"ME_RELEASE_CORPSE",      0xBD:"ME_ADD_LIFE",
    0xBE:"ME_ADD_GAUGE",           0xBF:"ME_ADD_ENEMY_LIFE",
    0xC0:"ME_ADD_ENEMY_GAUGE",     0xC1:"ME_GENERIC_TIMING",
    0xC2:"ME_STARE_FACE_ON",       0xC3:"ME_STARE_FACE_OFF",
    0xC4:"ME_STARE_FACE_V",        0xC5:"ME_STARE_FACE_H",
    0xC6:"ME_STARE_FACE_R",        0xC7:"ME_STARE_EYE_ON",
    0xC8:"ME_STARE_EYE_OFF",       0xC9:"ME_STARE_EYE_V",
    0xCA:"ME_STARE_EYE_H",         0xCB:"ME_STARE_TARGET_ON",
    0xCC:"ME_STARE_TARGET_OFF",    0xCD:"ME_MIRROR_ON",
    0xCE:"ME_MIRROR_OFF",          0xCF:"ME_ENEMY_MIRROR_ON",
    0xD0:"ME_ENEMY_MIRROR_OFF",    0xD1:"ME_FOLLOW_ENEMY_MIRROR_ON",
    0xD2:"ME_FOLLOW_ENEMY_MIRROR_OFF", 0xD3:"ME_DIRECTION_VICTIM_OFFSET_POS",
    0xD4:"ME_DIRECTION_VICTIM_OFFSET_ROT", 0xD5:"ME_VOICE_ON_ID_VICTIM",
    0xD6:"ME_SET_CAPTION_BTL_BEGIN",0xD7:"ME_SET_CAPTION_BTL_END",
    0xD8:"ME_SET_CAPTION_PROVOKE", 0xD9:"ME_SET_CAPTION_ROUND_END",
    0xDA:"ME_SHADOW_ON",           0xDB:"ME_SHADOW_OFF",
    0xDC:"ME_DIRECTION_VICTIM_OFFSET_POS_REVERSE", 0xDD:"ME_CHECK_CONDITION",
    0xDE:"ME_PROC_ACTION",         0xDF:"ME_DISP_ON",
    0xE0:"ME_DISP_OFF",            0xE1:"ME_TIMESTOP_START",
    0xE2:"ME_TIMESTOP_END",        0xE3:"ME_TIMESTOP_FILTER_ON",
    0xE4:"ME_TIMESTOP_FILTER_OFF", 0xE5:"ME_TIMESTOP_CTRL",
    0xE6:"ME_ANM_PARTICLE_TEXTUREOFFSET_BY_STAGE", 0xE7:"ME_ANM_OBJECT_TEXTUREOFFSET_BY_STAGE",
    0xE8:"ME_SCALE_CHANGE_RESET",  0xE9:"ME_SET_HORSEBACK_ATTACH_OBJ",
    0xEA:"ME_RESET_HORSEBACK_ATTACH_OBJ", 0xEB:"ME_ENEMY_FOG_CHANGE_BEGIN",
    0xEC:"ME_ENEMY_FOG_CHANGE_COLOR", 0xED:"ME_ENEMY_FOG_CHANGE_RESET",
    0xEE:"ME_ENEMY_FACE_ANM_SET",  0xEF:"ME_MOVEDIRC_RESET",
    0xF0:"ME_ENEMY_MOVEDIRC_RESET",0xF1:"ME_GUARDRESPONSEHIT_ON",
    0xF2:"ME_GUARDRESPONSEHIT_OFF",0xF3:"ME_MODELSHAKE",
    0xF4:"ME_MODELSHAKE_ENEMY",    0xF5:"ME_ENEMY_DOUBLE_SET_ANIMATION",
    0xF6:"ME_ENEMY_DOUBLE_BEGIN",  0xF7:"ME_ENEMY_DOUBLE_END",
    0xF8:"ME_LAND_STIFF_SET",      0xF9:"ME_RESET_ENEMY_DYNAMICS",
    0xFA:"ME_MOTION_START_FRAME_SET", 0xFB:"ME_MOTION_END_FRAME_SET",
    0xFC:"ME_ENEMY_CLUMP_COLOR_CHANGE_MINE", 0xFD:"ME_SECRET_MISSION_TAG_ON",
    0xFE:"ME_MOTION_EVENT_SHADER_ANIMATION_ON", 0xFF:"ME_MOTION_EVENT_SHADER_ANIMATION_OFF",
}
FUNC_MAP_2B = {
    (0x00,0x01):"ME_ANM_PARTICLE_SPEED_SET",
    (0x01,0x01):"ME_ENEMY_ANM_PARTICLE_SPEED_SET",
    (0x02,0x01):"ME_ANM_PARTICLE_TEXTUREOFFSET_BY_STAGE_EXCEPT",
    (0x03,0x01):"ME_MOTION_BLUR_ENABLE",
    (0x04,0x01):"ME_MOTION_BLUR_DISABLE",
    (0x05,0x01):"ME_MOTION_BLUR_DISABLE_IF_ANMCAMERA",
    (0x06,0x01):"ME_DYNAMICS_RESET",
    (0x07,0x01):"ME_FOOT_SE_AUTO_OFF",
    (0x08,0x01):"ME_FOOT_SE_AUTO_ON",
    (0x09,0x01):"ME_FOOT_SE_ON",
    (0x0A,0x01):"ME_LIP_SYNC_ENABLE",
    (0x0B,0x01):"ME_LIP_SYNC_DISABLE",
    (0x0C,0x01):"ME_SHADOW_OFF_IF_ANMCAMERA",
    (0x0D,0x01):"ME_TIMER_COUNT_STOP",
    (0x0E,0x01):"ME_TIMER_COUNT_START",
    (0x0F,0x01):"ME_SHOW_COMMANDLIST_NAME",
    (0x10,0x01):"ME_MOVE_DISTANCE_OUT_SIDE",
    (0x11,0x01):"ME_SKIP_ODD_FRAME",
    (0x12,0x01):"ME_FORCE_MOVE_TO_CENTER_KEEP_STAND_DIST",
    (0x13,0x01):"ME_ENTRY_SKILL_ANY_COORD_ATTACH",
    (0x14,0x01):"ME_LIP_ANM_SET",
    (0x15,0x01):"ME_ENEMY_LIP_ANM_SET",
    (0x16,0x01):"ME_ENEMY_DYNAMICS_CTRL_ON",
    # Confirmed in the live ASBR build 13123765 command dispatch/name table.
    (0x17,0x01):"ME_ENEMY_DYNAMICS_CTRL_OFF",
    (0x18,0x01):"ME_ANOMALOUS_OFF",
    (0x19,0x01):"ME_DMG_EXPRESSION_DISP_ON",
    (0x1A,0x01):"ME_DMG_EXPRESSION_DISP_OFF",
}

_ATTACK_MAP = {
    0x0E:'high', 0x11:'high', 0x14:'high',
    0x0F:'middle', 0x12:'middle', 0x15:'middle',
    0x10:'low',  0x13:'low',  0x16:'low',
}

ANM_SPEED_FUNC_NAMES = {'ME_ANM_SPEED_SET', 'ME_ENEMY_ANM_SPEED_SET'}
ANM_SPEED_MULTIPLIER_OFFSET = 0x4C
FWD_VELOCITY_FUNC_NAMES = {'ME_FWDVELOCITY_SET', 'ME_FWDVELOCITY_SET_INTERP'}
FWD_VELOCITY_VALUE_OFFSET = 0x38
FWD_VELOCITY_DURATION_OFFSET = 0x3C
GION_FUNC_NAMES = {'ME_GION_BEGIN', 'ME_GION_BEGIN_2D', 'ME_PROVOKE_GION', 'ME_BTLWIN_GION'}
GION_SCALE_OFFSET = 0x4C
GION_ID_OFFSET = 0x54
GION_ID_SIZE = 32
ATKHIT_FUNC_NAMES = {
    'ME_ATKHIT_ON', 'ME_ATKHIT2_ON', 'ME_ATKHIT3_ON',
    'ME_ATKHIT4_ON', 'ME_ATKHIT5_ON',
}
ATKHIT_PARAM_OFFSETS = (0x38, 0x3C, 0x40, 0x44, 0x48)
FUNC_FIELD_OFFSET = 0x34


# These opcodes carry a 0x1F0-byte descriptor after the 0xC8-byte command.
# Verified by walking all 218 motion chunks in the local ASBR corpus.
EXTENDED_PAYLOAD_OPCODES = frozenset((
    0x20, 0x22, 0x24, 0x26, 0x28, 0x30, 0x31, 0x32, 0x33, 0x61, 0xC1,
))


def function_name(opcode):
    opcode = int(opcode) & 0xFFFF
    return (FUNC_MAP_1B.get(opcode) if opcode < 0x100 else
            FUNC_MAP_2B.get((opcode & 0xFF, opcode >> 8))) or f"0x{opcode:04X}"


def function_opcode(name):
    reverse = {v: k for k, v in FUNC_MAP_1B.items()}
    reverse.update({v: a | (b << 8) for (a, b), v in FUNC_MAP_2B.items()})
    return reverse[name] if name in reverse else int(name, 0)


def _decode_func(raw, off):
    return function_name(struct.unpack_from('<H', raw, off + FUNC_FIELD_OFFSET)[0])


def motion_subentry_size(opcode):
    return MOT_SUB_SIZE + (MOT_DMGID_SIZE if (int(opcode) & 0xFFFF) in EXTENDED_PAYLOAD_OPCODES else 0)


def _motion_layout(raw):
    """Bounded structural walk. Includes unnamed/sentinel entries, never scans labels."""
    if len(raw) < MOT_GLOBAL_HDR:
        raise ValueError("Truncated motion header")
    if _u32be(raw, 0) != len(raw) - 4:
        raise ValueError("Motion payload byte length does not match its header")
    declared = _u32le(raw, 0x28)
    legacy = bytes(raw[4:7]) == b'ver' and declared == 0
    if legacy:
        raise ValueError("Legacy ver0.000 motion layout is not supported; file left unchanged")
    if not legacy and declared > (len(raw) - MOT_GLOBAL_HDR) // MOT_HDR_SIZE:
        raise ValueError("Motion entry count exceeds payload size")
    pos = MOT_GLOBAL_HDR
    layout = []
    while pos < len(raw) and (legacy or len(layout) < declared):
        off = pos
        if off + MOT_HDR_SIZE > len(raw):
            raise ValueError(f"Truncated motion entry at 0x{off:X}")
        if not all(_is_ascii_cstr_field(raw, off + rel, 32, allow_empty=True) for rel in (0, 32)):
            raise ValueError(f"Invalid motion names at 0x{off:X}")
        n = _u32le(raw, off + 0x6C)
        pos += MOT_HDR_SIZE
        if n > (len(raw) - pos) // MOT_SUB_SIZE:
            raise ValueError(f"Motion command count exceeds payload at 0x{off:X}")
        subs = []
        for _ in range(n):
            if pos + MOT_SUB_SIZE > len(raw):
                raise ValueError(f"Truncated command at 0x{pos:X}")
            size = motion_subentry_size(_u32le(raw, pos + FUNC_FIELD_OFFSET))
            if pos + size > len(raw):
                raise ValueError(f"Truncated command descriptor at 0x{pos:X}")
            subs.append((pos, size))
            pos += size
        layout.append((off, pos - off, subs))
    if pos != len(raw):
        raise ValueError(f"Unconsumed motion data at 0x{pos:X} (declared {declared} entries)")
    return layout


def _is_ascii_cstr_field(raw, off, size, allow_empty=False):
    if off < 0 or off + size > len(raw):
        return False
    field = bytes(raw[off:off+size])
    text = field.split(b'\x00', 1)[0]
    if not text:
        return allow_empty
    return all(32 <= ch <= 126 for ch in text)


# Low-level helpers
def _u32be(b, off):
    return struct.unpack_from('>I', b, off)[0]

def _u32le(b, off):
    return struct.unpack_from('<I', b, off)[0]

def _f32le(b, off):
    return struct.unpack_from('<f', b, off)[0]

def _cstr(b, off, size):
    raw = b[off:off+size]
    return raw.split(b'\x00')[0].decode('ascii', errors='replace')

def _wstr(buf, off, s, size):
    enc = s.encode('ascii', errors='replace')[:size]
    buf[off:off+size] = enc + b'\x00' * (size - len(enc))

def _wstr_preserve_tail(buf, off, s, size):
    enc = s.encode('ascii', errors='replace')[:size]
    buf[off:off+len(enc)] = enc
    if len(enc) < size:
        buf[off+len(enc)] = 0

def _wu32le(buf, off, v):
    struct.pack_into('<I', buf, off, int(v))

def _wi32le(buf, off, v):
    struct.pack_into('<i', buf, off, int(v))

def _wf32le(buf, off, v):
    value = float(v)
    current = _f32le(buf, off)
    # Unchanged signalling NaNs and signed zero must retain their original bits.
    if (math.isnan(current) and math.isnan(value) or current == value and
            (value != 0 or math.copysign(1, current) == math.copysign(1, value))):
        return
    struct.pack_into('<f', buf, off, value)

def _wu8(buf, off, v):
    buf[off] = int(v) & 0xFF


# XFBIN container parser
def _parse_xfbin_header(data):
    """Parse XFBIN header; return chunk_data_start offset."""
    pos = 0
    pos += 4   # magic NUCC
    pos += 4   # FileID
    pos += 8   # skip
    chunk_table_size = _u32be(data, pos); pos += 4
    pos += 4   # MinPageSize
    pos += 2   # FileVersion
    pos += 2   # FileVersionAttr

    chunk_type_count = _u32be(data, pos); pos += 4
    chunk_type_size  = _u32be(data, pos); pos += 4
    file_path_count  = _u32be(data, pos); pos += 4
    file_path_size   = _u32be(data, pos); pos += 4
    chunk_name_count = _u32be(data, pos); pos += 4
    chunk_name_size  = _u32be(data, pos); pos += 4
    chunk_map_count  = _u32be(data, pos); pos += 4
    chunk_map_size   = _u32be(data, pos); pos += 4
    chunk_map_idx_cnt = _u32be(data, pos); pos += 4
    extra_idx_count  = _u32be(data, pos); pos += 4

    # ChunkTypes
    pos += chunk_type_size - 1; pos += 1
    # FilePaths
    pos += file_path_size - 1; pos += 1
    # ChunkNames
    pos += chunk_name_size
    # 4-byte align
    if pos % 4: pos += 4 - (pos % 4)
    # ChunkMaps
    pos += chunk_map_size
    # ExtraMappings
    pos += extra_idx_count * 8
    # ChunkMapIndices
    pos += chunk_map_idx_cnt * 4

    return pos   # chunk data start


def _iter_chunks(data, chunk_data_start):
    """Yield (offset, size, data_offset) for each chunk in the XFBIN."""
    pos = chunk_data_start
    while pos + 12 <= len(data):
        size      = _u32be(data, pos)
        map_idx   = _u32be(data, pos+4)
        # version / versionAttr at +8, +10 — not needed
        data_off  = pos + 12
        if data_off + size > len(data):
            raise ValueError(f"Truncated XFBIN chunk at 0x{pos:X}")
        yield pos, size, data_off
        pos += 12 + size
        if pos >= len(data):
            break


def _find_chunks(data):
    """Return dict: name -> (chunk_header_offset, chunk_size, data_offset)."""
    # First build name list from chunk table
    if len(data) < 68 or bytes(data[:4]) != b'NUCC':
        raise ValueError("Not a valid NUCC/XFBIN container")
    pos = 0
    pos += 4   # magic
    pos += 4   # FileID
    pos += 8
    _u32be(data, pos); pos += 4   # ChunkTableSize
    pos += 4   # MinPageSize
    pos += 2   # FileVersion
    pos += 2   # FileVersionAttr

    pos += 4   # ChunkTypeCount
    chunk_type_size = _u32be(data, pos); pos += 4
    pos += 4   # FilePathCount
    file_path_size  = _u32be(data, pos); pos += 4
    pos += 4   # ChunkNameCount
    chunk_name_size = _u32be(data, pos); pos += 4
    chunk_map_count = _u32be(data, pos); pos += 4
    chunk_map_size  = _u32be(data, pos); pos += 4
    chunk_map_idx_cnt = _u32be(data, pos); pos += 4
    extra_idx_count   = _u32be(data, pos); pos += 4

    # ChunkTypes
    type_bytes = data[pos:pos+chunk_type_size-1]; pos += chunk_type_size-1; pos += 1
    chunk_types = type_bytes.decode('utf-8', errors='replace').split('\x00')

    # FilePaths
    pos += file_path_size-1; pos += 1

    # ChunkNames
    name_bytes = data[pos:pos+chunk_name_size-1]; pos += chunk_name_size
    chunk_names = name_bytes.decode('utf-8', errors='replace').split('\x00')

    if pos % 4: pos += 4 - (pos % 4)

    # ChunkMaps: each is 12 bytes (type_idx, path_idx, name_idx)
    chunk_maps = []
    for i in range(chunk_map_count):
        ti = _u32be(data, pos);     pos += 4
        pi = _u32be(data, pos);     pos += 4
        ni = _u32be(data, pos);     pos += 4
        ctype = chunk_types[ti] if ti < len(chunk_types) else ''
        cname = chunk_names[ni] if ni < len(chunk_names) else ''
        chunk_maps.append((ctype, cname))

    # ExtraMappings
    pos += extra_idx_count * 8

    # ChunkMapIndices
    chunk_map_indices = []
    for i in range(chunk_map_idx_cnt):
        chunk_map_indices.append(_u32be(data, pos)); pos += 4

    chunk_data_start = pos
    result = {}
    for hdr_off, size, data_off in _iter_chunks(data, chunk_data_start):
        # find chunk_map_index from the 4 bytes at hdr_off+4
        cmi = _u32be(data, hdr_off+4)
        if cmi < len(chunk_map_indices):
            cm_idx = chunk_map_indices[cmi]
            if cm_idx < len(chunk_maps):
                ctype, cname = chunk_maps[cm_idx]
                if ctype == 'nuccChunkBinary' and cname:
                    result[cname] = (hdr_off, size, data_off)
    return result


# sklslot parser
def parse_sklslot(raw):
    """Parse sklslot binary data. raw = bytearray."""
    total = _u32be(raw, 0)
    if total % SKL_ENTRY_SIZE or total > len(raw) - 4:
        raise ValueError("Invalid skill-slot byte length")
    n = total // SKL_ENTRY_SIZE
    entries = []
    for i in range(n):
        off = SKL_HDR_SIZE + i * SKL_ENTRY_SIZE
        entries.append({
            '_raw_bytes': bytes(raw[off:off + SKL_ENTRY_SIZE]),
            'slot_name': _cstr(raw, off,                  SKL_SLOT_SZ),
            'xfbin':     _cstr(raw, off + SKL_SLOT_SZ,    SKL_XFBIN_SZ),
            'skill_id':  _cstr(raw, off + SKL_SLOT_SZ + SKL_XFBIN_SZ, SKL_SKILL_SZ),
        })
    return entries


def write_sklslot(entries):
    """Serialise sklslot entries to bytes."""
    total = len(entries) * SKL_ENTRY_SIZE
    out = bytearray(SKL_HDR_SIZE + total)
    struct.pack_into('>I', out, 0, total)
    for i, e in enumerate(entries):
        off = SKL_HDR_SIZE + i * SKL_ENTRY_SIZE
        out[off:off + SKL_ENTRY_SIZE] = e.get('_raw_bytes', bytes(SKL_ENTRY_SIZE))
        _patch_string(out, off, e['slot_name'], SKL_SLOT_SZ)
        _patch_string(out, off + SKL_SLOT_SZ, e['xfbin'], SKL_XFBIN_SZ)
        _patch_string(out, off + SKL_SLOT_SZ + SKL_XFBIN_SZ, e['skill_id'], SKL_SKILL_SZ)
    return out


# load parser
def parse_load(raw):
    """Parse load binary data. raw = bytearray."""
    if len(raw) < 72 or _u32be(raw, 0) > len(raw) - 4:
        raise ValueError("Invalid load configuration length")
    entries = []
    # Entry 0: no flag field (68 bytes)
    off = 4
    entries.append({
        '_raw_bytes': bytes(raw[off:off + LOAD_ENTRY0_SZ]),
        'type':     _u32le(raw, off),
        'flag':     None,
        'category': _cstr(raw, off+4,  32),
        'code':     _cstr(raw, off+36, 32),
    })
    off += LOAD_ENTRY0_SZ
    # Remaining: 72 bytes each
    while off + LOAD_ENTRY_SZ <= len(raw):
        entries.append({
            '_raw_bytes': bytes(raw[off:off + LOAD_ENTRY_SZ]),
            'type':     _u32le(raw, off),
            'flag':     _u32le(raw, off+4),
            'category': _cstr(raw, off+8,  32),
            'code':     _cstr(raw, off+40, 32),
        })
        off += LOAD_ENTRY_SZ
    return entries


def write_load(entries):
    """Serialise load entries to bytes."""
    if not entries:
        raise ValueError("Load configuration requires its initial entry")
    size = LOAD_HDR_SZ + LOAD_ENTRY0_SZ + (len(entries)-1) * LOAD_ENTRY_SZ
    out = bytearray(size)
    data_size = size - LOAD_HDR_SZ
    struct.pack_into('>I', out, 0, data_size)
    off = LOAD_HDR_SZ
    for i, e in enumerate(entries):
        record_size = LOAD_ENTRY0_SZ if i == 0 else LOAD_ENTRY_SZ
        source = e.get('_raw_bytes', bytes(record_size))
        out[off:off + record_size] = source[:record_size].ljust(record_size, b'\0')
        if i == 0:
            _wu32le(out, off, e['type'])
            _patch_string(out, off+4,  e['category'], 32)
            _patch_string(out, off+36, e['code'],     32)
            off += LOAD_ENTRY0_SZ
        else:
            _wu32le(out, off,   e['type'])
            _wu32le(out, off+4, e['flag'] if e['flag'] is not None else 0)
            _patch_string(out, off+8,  e['category'], 32)
            _patch_string(out, off+40, e['code'],     32)
            off += LOAD_ENTRY_SZ
    return out


# mot parser
def parse_motion_subentry(raw, off=0, size=None):
    dtype = _u32le(raw, off + FUNC_FIELD_OFFSET)
    size = size or motion_subentry_size(dtype)
    if off + size > len(raw):
        raise ValueError("Truncated motion command")
    name = function_name(dtype)
    frame = struct.unpack_from('<H', raw, off + 0x30)[0]
    sub = {
        'sub_off': off, 'raw_size': size, 'raw_bytes': bytes(raw[off:off + size]),
        'bone': _cstr(raw, off + 8, 32), 'dtype': dtype,
        'dname': name, 'func_name': name, 'raw_func_name': name,
        'func_param_bytes': list(raw[off + 0x35:off + 0x38]),
        'frame_w': frame, 'frame_str': {9998: 'Start', 9999: 'End'}.get(frame, str(frame)),
        'dmg': 0, 'grd': 0, 'x': 0.0, 'y': 0.0, 'push': 0,
        'attack': '', 'dmg_label': '', 'speed_multiplier': _f32le(raw, off + 0x4C),
        'fwd_velocity': struct.unpack_from('<i', raw, off + 0x38)[0],
        'fwd_velocity_duration': struct.unpack_from('<i', raw, off + 0x3C)[0],
        'gion_scale': _f32le(raw, off + 0x4C), 'gion_id': _cstr(raw, off + 0x54, 32),
        'atkhit_params': [struct.unpack_from('<i', raw, off + r)[0] for r in ATKHIT_PARAM_OFFSETS],
    }
    if size > MOT_SUB_SIZE:
        d = off + MOT_SUB_SIZE
        sub.update({
            'dmg_label': _cstr(raw, d + 0x18, 32),
            'dmg': _u32le(raw, d + 0x6C), 'grd': _u32le(raw, d + 0x70),
            'x': _f32le(raw, d + 0x60), 'y': _f32le(raw, d + 0x64),
            'push': struct.unpack_from('<i', raw, d + 0x68)[0],
            'attack': 'unblockable' if raw[d + 8] == 2 or raw[d + 9] == 2 else
                      _ATTACK_MAP.get(_u32le(raw, d), ''),
        })
    return sub


def parse_mot(raw):
    entries = []
    for off, size, subs in _motion_layout(raw):
        entry = {
            'offset': off, 'raw_size': size, 'raw_n_subs': len(subs),
            'header_bytes': bytes(raw[off:off + MOT_HDR_SIZE]),
            'event_id': _cstr(raw, off, 32), 'anim_id': _cstr(raw, off + 0x20, 32),
            'n_subs': len(subs),
            'subentries': [parse_motion_subentry(raw, pos, n) for pos, n in subs],
        }
        for key, rel in MOT_HEADER_FIELDS.items():
            entry[key] = _u32le(raw, off + rel)
        entries.append(entry)
    return entries


MOT_HEADER_FIELDS = {
    'enable_face_animation': 0x44, 'no_frame_skip': 0x48,
    'fix_position': 0x4C, 'frame_skip': 0x64, 'file_id': 0x98,
}


def _patch_string(buf, off, value, size):
    # Never normalise padding in unchanged fields.
    if _cstr(buf, off, size) != value:
        _wstr(buf, off, value, size)


def write_mot_entry(raw_buf, entry):
    off = entry.get('offset')
    if off is None:
        return
    _patch_string(raw_buf, off, entry['event_id'], 32)
    _patch_string(raw_buf, off + 0x20, entry['anim_id'], 32)
    for key, rel in MOT_HEADER_FIELDS.items():
        _wu32le(raw_buf, off + rel, entry.get(key, 0))
    _wu32le(raw_buf, off + 0x6C, len(entry.get('subentries', [])))


def write_mot_subentry(raw_buf, sub):
    off = sub.get('sub_off')
    if off is None:
        return
    dtype = int(sub.get('dtype', 0))
    size = motion_subentry_size(dtype)
    if off + size > len(raw_buf):
        raise ValueError("Command size changed; rebuild the motion before writing")
    _patch_string(raw_buf, off + 8, sub.get('bone', ''), 32)
    _wu32le(raw_buf, off + FUNC_FIELD_OFFSET, dtype)
    struct.pack_into('<H', raw_buf, off + 0x30, int(sub.get('frame_w', 0)))
    name = function_name(dtype)
    if name in ANM_SPEED_FUNC_NAMES:
        _wf32le(raw_buf, off + 0x4C, sub.get('speed_multiplier', 1.0))
    if name in FWD_VELOCITY_FUNC_NAMES:
        _wi32le(raw_buf, off + 0x38, sub.get('fwd_velocity', 0))
        _wi32le(raw_buf, off + 0x3C, sub.get('fwd_velocity_duration', 0))
    if name in GION_FUNC_NAMES:
        _wf32le(raw_buf, off + 0x4C, sub.get('gion_scale', 1.0))
        _patch_string(raw_buf, off + 0x54, sub.get('gion_id', ''), 32)
    if name in ATKHIT_FUNC_NAMES:
        for rel, value in zip(ATKHIT_PARAM_OFFSETS, sub.get('atkhit_params', [])):
            _wi32le(raw_buf, off + rel, value)
    if size > MOT_SUB_SIZE:
        d = off + MOT_SUB_SIZE
        _patch_string(raw_buf, d + 0x18, sub.get('dmg_label', ''), 32)
        if sub.get('dmg_label', '').startswith('DAMAGE_ID'):
            for rel, key in ((0x60, 'x'), (0x64, 'y')):
                _wf32le(raw_buf, d + rel, sub.get(key, 0.0))
            _wi32le(raw_buf, d + 0x68, sub.get('push', 0))
            _wu32le(raw_buf, d + 0x6C, sub.get('dmg', 0))
            _wu32le(raw_buf, d + 0x70, sub.get('grd', 0))
            current = 'unblockable' if raw_buf[d + 8] == 2 or raw_buf[d + 9] == 2 else _ATTACK_MAP.get(_u32le(raw_buf, d), '')
            attack = sub.get('attack', '')
            if attack != current and attack:
                if attack == 'unblockable':
                    raw_buf[d + 8] = 2
                else:
                    if raw_buf[d + 8] == 2: raw_buf[d + 8] = 0
                    if raw_buf[d + 9] == 2: raw_buf[d + 9] = 0
                    previous = _u32le(raw_buf, d)
                    family = 0x0E + ((previous - 0x0E) // 3) * 3 if 0x0E <= previous <= 0x16 else 0x0E
                    _wu32le(raw_buf, d, family + {'high': 0, 'middle': 1, 'low': 2}[attack])


def make_default_mot_entry(index=0):
    """Return a safe blank PL_ANM entry dict for prm_mot/prm_gha."""
    return {
        'offset': None,
        'event_id': f'PL_ANM_NEW_{index:03d}',
        'anim_id': f'new_anim_{index:03d}',
        'enable_face_animation': 0,
        'no_frame_skip': 0,
        'fix_position': 0,
        'frame_skip': 0,
        'file_id': 0,
        'n_subs': 0,
        'subentries': [],
    }


def make_default_mot_subentry(index=0):
    """Return a safe blank prm_mot subentry dict."""
    return {
        'sub_off': None,
        'raw_bytes': bytes(MOT_SUB_SIZE),
        'bone': '',
        'dtype': 0,
        'dname': DATA_TYPE_MAP.get(0, '0'),
        'func_name': FUNC_MAP_1B.get(0, 'ME_ENEMY_CTRL_ON'),
        'raw_func_name': FUNC_MAP_1B.get(0, 'ME_ENEMY_CTRL_ON'),
        'func_param_bytes': [0, 0, 0],
        'frame_w': 0,
        'frame_str': '0',
        'dmg': 0,
        'grd': 0,
        'x': 0.0,
        'y': 0.0,
        'dmg_label': '',
        'attack': '',
        'push': 0,
        'speed_multiplier': 1.0,
        'fwd_velocity': 0,
        'fwd_velocity_duration': 0,
        'gion_scale': 1.0,
        'gion_id': '',
        'atkhit_params': [0, 0, 0, 0, 0],
    }


def write_mot(entries, original_raw):
    """Rebuild variable-sized commands without changing opaque bytes."""
    out = bytearray(original_raw[:MOT_GLOBAL_HDR]) if original_raw else bytearray(MOT_GLOBAL_HDR)
    if len(out) < MOT_GLOBAL_HDR:
        raise ValueError("Truncated motion header")
    for entry in entries:
        header = entry.get('header_bytes')
        if header is None:
            old_off = entry.get('offset')
            if old_off is None: old_off = entry.get('template_offset')
            header = original_raw[old_off:old_off + MOT_HDR_SIZE] if original_raw and old_off is not None else bytes(MOT_HDR_SIZE)
        block = bytearray(header)
        if len(block) != MOT_HDR_SIZE:
            raise ValueError("Invalid motion entry header")
        offsets = []
        for sub in entry.get('subentries', []):
            size = motion_subentry_size(sub['dtype'])
            source = bytes(sub.get('raw_bytes', b''))
            source = source[:size].ljust(size, b'\0')
            rel = len(block)
            block.extend(source)
            write_mot_subentry(block, {**sub, 'sub_off': rel})
            offsets.append((sub, rel, size))
        write_mot_entry(block, {**entry, 'offset': 0})
        start = len(out)
        entry.update(offset=start, raw_size=len(block), raw_n_subs=len(offsets), n_subs=len(offsets), header_bytes=bytes(block[:MOT_HDR_SIZE]))
        entry.pop('template_offset', None)
        for sub, rel, size in offsets:
            sub.update(sub_off=start + rel, raw_size=size, raw_bytes=bytes(block[rel:rel + size]))
        out.extend(block)
    struct.pack_into('>I', out, 0, len(out) - 4)
    # Legacy ver0.000 stores no count; retain that variant.
    legacy = original_raw and bytes(original_raw[4:7]) == b'ver' and _u32le(original_raw, 0x28) == 0
    _wu32le(out, 0x28, 0 if legacy else len(entries))
    return out


# Top-level XFBIN API
def parse_prm_xfbin(filepath):
    """Open a *prm.bin.xfbin file and parse all three chunks.

    Returns
    raw : bytearray
        Full file contents (mutable).
    result : dict with keys:
        'load'    -> {'entries': [...], 'data_off': int, 'data_size': int}
        'mot'     -> {'entries': [...], 'data_off': int, 'data_size': int}
        'sklslot' -> {'entries': [...], 'data_off': int, 'data_size': int}
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    chunks = _find_chunks(raw)

    result = {}

    # Detect chunk names flexibly (character code varies)
    def _find(suffix):
        for k in chunks:
            if k.endswith(suffix):
                return k
        return None

    for suffix, key in [('prm_load', 'load'), ('prm_mot', 'mot'), ('prm_sklslot', 'sklslot')]:
        name = _find(suffix)
        if name is None:
            continue
        hdr_off, size, data_off = chunks[name]
        chunk_raw = raw[data_off:data_off+size]

        if key == 'load':
            entries = parse_load(chunk_raw)
        elif key == 'mot':
            entries = parse_mot(chunk_raw)
        else:
            entries = parse_sklslot(chunk_raw)

        result[key] = {
            'name':      name,
            'entries':   entries,
            'hdr_off':   hdr_off,
            'data_off':  data_off,
            'data_size': size,
            'raw':       bytearray(chunk_raw),
        }

    # Also detect prm_gha chunk (GHA motion data — same PL_ANM format as prm_mot)
    name = _find('prm_gha')
    if name is not None:
        hdr_off, size, data_off = chunks[name]
        chunk_raw = raw[data_off:data_off+size]
        entries = parse_mot(chunk_raw)
        result['gha'] = {
            'name':      name,
            'entries':   entries,
            'hdr_off':   hdr_off,
            'data_off':  data_off,
            'data_size': size,
            'raw':       bytearray(chunk_raw),
        }

    if not result:
        raise ValueError("No supported Char Skills chunks found")
    return raw, result


def _align4(n):
    return n + ((4 - (n % 4)) % 4)


def _replace_chunk(raw, hdr_off, old_size, new_bytes):
    """Replace one XFBIN chunk payload and update its chunk-size field."""
    old_end = hdr_off + 12 + old_size
    new_size = len(new_bytes)

    chunk = bytearray(raw[hdr_off:hdr_off + 12])
    struct.pack_into('>I', chunk, 0, new_size)
    chunk += new_bytes

    old_len = old_end - hdr_off
    raw[hdr_off:old_end] = chunk
    return len(chunk) - old_len


def _save_prm_xfbin_staged(filepath, raw, result):
    """Write back modified chunks into raw bytearray and save to disk.

    Rebuild changed binary chunks and update their XFBIN chunk-size fields.
    sklslot/load/mot/gha may grow or shrink when entries are added or removed.
    """
    replacements = []
    for key in ('load', 'sklslot', 'mot', 'gha'):
        if key not in result:
            continue
        info = result[key]
        hdr_off = info.get('hdr_off', info['data_off'] - 12)

        if key in ('mot', 'gha'):
            new_bytes = bytes(write_mot(info['entries'], info.get('raw')))
            _motion_layout(new_bytes)

        elif key == 'load':
            new_bytes = write_load(info['entries'])
            # Trailing zeros are normal padding — pad to original size if needed

        elif key == 'sklslot':
            new_bytes = write_sklslot(info['entries'])
            # Trailing zeros are normal padding — pad to original size if needed

        old_size = info['data_size']
        entry_size = (
            LOAD_ENTRY_SZ if key == 'load'
            else SKL_ENTRY_SIZE if key == 'sklslot'
            else None
        )
        if entry_size is not None and 0 < old_size - len(new_bytes) < entry_size:
            tail = bytes(info.get('raw', b''))[len(new_bytes):old_size]
            pad_len = old_size - len(new_bytes)
            new_bytes += tail if len(tail) == pad_len else bytes(pad_len)
            if key == 'load':
                struct.pack_into('>I', new_bytes, 0, old_size - LOAD_HDR_SZ)

        replacements.append((hdr_off, key, new_bytes))

    for hdr_off, key, new_bytes in sorted(replacements, reverse=True):
        info = result[key]
        old_size = info['data_size']
        delta = _replace_chunk(raw, hdr_off, old_size, new_bytes)

        info['hdr_off'] = hdr_off
        info['data_off'] = hdr_off + 12
        info['data_size'] = len(new_bytes)
        info['raw'] = bytearray(new_bytes)

        if delta:
            for other_key, other_info in result.items():
                if other_key == key or not isinstance(other_info, dict):
                    continue
                other_hdr = other_info.get(
                    'hdr_off',
                    other_info.get('data_off', 12) - 12,
                )
                if other_hdr > hdr_off:
                    other_info['hdr_off'] = other_hdr + delta
                    other_info['data_off'] = other_info.get('data_off', other_hdr + 12) + delta

    _atomic_write(filepath, raw)


def _atomic_write(filepath, data):
    directory = os.path.dirname(os.path.abspath(filepath))
    fd, temporary = tempfile.mkstemp(prefix='.arrow-skills-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filepath)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_prm_xfbin(filepath, raw, result):
    from parsers.skill_tools import validate_skills
    errors = [issue for issue in validate_skills(result) if issue['severity'] == 'error']
    if errors:
        raise ValueError('\n'.join(issue['message'] for issue in errors[:20]))
    staged_raw, staged_result = bytearray(raw), copy.deepcopy(result)
    _save_prm_xfbin_staged(filepath, staged_raw, staged_result)
    raw[:] = staged_raw
    # Retain entry identities used by the editor's signals. Rebuilt offsets and
    # raw templates are synchronised from the same deterministic serialization.
    for key in ('mot', 'gha'):
        if key in result:
            write_mot(result[key]['entries'], result[key]['raw'])
    for key, value in staged_result.items():
        result[key].update({k: v for k, v in value.items() if k != 'entries'})


# Standalone prm_load.bin.xfbin API
# Format (from prm_load.bt): uint32 count (LE) + count × 72-byte entries.
# Each entry: folder[32] + xfbin[32] + uint32 type + uint32 unk2.
# Type meanings: 3=ANIMATIONS, 6=GHA, 9=MODEL, 10=ACCESSORY, 11=EFFECTS, 13=PRM, 14=MISC

PRMLOAD_ENTRY_SIZE = 72


def parse_prmload_chunk(raw):
    """Parse chunk data of a standalone prm_load.bin.xfbin."""
    count = _u32le(raw, 0)
    if count > (len(raw) - 4) // PRMLOAD_ENTRY_SIZE:
        raise ValueError("Standalone prm_load entry count exceeds payload")
    entries = []
    off = 4
    for _ in range(count):
        if off + PRMLOAD_ENTRY_SIZE > len(raw):
            break
        entries.append({
            'folder': _cstr(raw, off,    32),
            'xfbin':  _cstr(raw, off+32, 32),
            'type':   _u32le(raw, off+64),
            'unk2':   _u32le(raw, off+68),
        })
        off += PRMLOAD_ENTRY_SIZE
    return entries


def write_prmload_chunk(entries):
    """Serialise standalone prm_load entries to bytes."""
    count = len(entries)
    out = bytearray(4 + count * PRMLOAD_ENTRY_SIZE)
    _wu32le(out, 0, count)
    off = 4
    for e in entries:
        _wstr(out, off,    e['folder'], 32)
        _wstr(out, off+32, e['xfbin'],  32)
        _wu32le(out, off+64, e['type'])
        _wu32le(out, off+68, e['unk2'])
        off += PRMLOAD_ENTRY_SIZE
    return out


def parse_prmload_xfbin(filepath):
    """Open a standalone *prm_load.bin.xfbin and parse its load entries."""
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    chunks = _find_chunks(raw)

    def _find(suffix):
        for k in chunks:
            if k.endswith(suffix):
                return k
        return None

    name = _find('prm_load')
    if name is None:
        raise ValueError("No prm_load chunk found in file")

    hdr_off, size, data_off = chunks[name]
    chunk_raw = raw[data_off:data_off+size]
    if len(chunk_raw) >= 72 and _u32be(chunk_raw, 0) == len(chunk_raw) - 4:
        return raw, {'load': {'name': name, 'entries': parse_load(chunk_raw),
            'hdr_off': hdr_off, 'data_off': data_off, 'data_size': size, 'raw': bytearray(chunk_raw)}}
    entries = parse_prmload_chunk(chunk_raw)

    return raw, {
        'prmload_standalone': {
            'name':      name,
            'entries':   entries,
            'hdr_off':   hdr_off,
            'data_off':  data_off,
            'data_size': size,
            'raw':       bytearray(chunk_raw),
        }
    }


def save_prmload_xfbin(filepath, raw, result):
    """Write back modified prm_load entries and save standalone file."""
    if 'load' in result:
        return save_prm_xfbin(filepath, raw, result)
    info = result['prmload_standalone']
    hdr_off = info.get('hdr_off', info['data_off'] - 12)
    data_size = info['data_size']

    for entry in info['entries']:
        for key in ('folder', 'xfbin'):
            encoded = entry[key].encode('ascii')
            if len(encoded) > 32 or b'\0' in encoded:
                raise ValueError(f'{key}: requires ASCII, no NUL, at most 32 bytes')
    new_bytes = bytearray(write_prmload_chunk(info['entries']))
    staged = bytearray(raw)
    _replace_chunk(staged, hdr_off, data_size, new_bytes)
    _atomic_write(filepath, staged)
    raw[:] = staged
    info['hdr_off'] = hdr_off
    info['data_off'] = hdr_off + 12
    info['data_size'] = len(new_bytes)
    info['raw'] = bytearray(new_bytes)
