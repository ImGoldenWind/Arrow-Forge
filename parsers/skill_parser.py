import struct
import math

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
}

_ATTACK_MAP = {
    0x0E:'high', 0x11:'high', 0x14:'high',
    0x0F:'middle', 0x12:'middle', 0x15:'middle',
    0x10:'low',  0x13:'low',  0x16:'low',
}

ANM_SPEED_FUNC_NAMES = {'ME_ANM_SPEED_SET', 'ME_ENEMY_ANM_SPEED_SET'}
ANM_SPEED_MULTIPLIER_OFFSET = 0x4C


def _decode_func(raw, off):
    """Decode function name from bytes at subentry offset +0x34/+0x35."""
    b1 = raw[off+0x34] if off+0x34 < len(raw) else 0
    b2 = raw[off+0x35] if off+0x35 < len(raw) else 0
    name = FUNC_MAP_2B.get((b1, b2)) or FUNC_MAP_1B.get(b1)
    if name:
        return name
    return f"0x{b1:02X}"


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

def _wf32le(buf, off, v):
    struct.pack_into('<f', buf, off, float(v))

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
        yield pos, size, data_off
        pos += 12 + size
        if pos >= len(data):
            break


def _find_chunks(data):
    """Return dict: name -> (chunk_header_offset, chunk_size, data_offset)."""
    # First build name list from chunk table
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
    n = total // SKL_ENTRY_SIZE
    entries = []
    for i in range(n):
        off = SKL_HDR_SIZE + i * SKL_ENTRY_SIZE
        entries.append({
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
        _wstr(out, off,                               e['slot_name'], SKL_SLOT_SZ)
        _wstr(out, off + SKL_SLOT_SZ,                e['xfbin'],     SKL_XFBIN_SZ)
        _wstr(out, off + SKL_SLOT_SZ + SKL_XFBIN_SZ, e['skill_id'],  SKL_SKILL_SZ)
    return out


# load parser
def parse_load(raw):
    """Parse load binary data. raw = bytearray."""
    entries = []
    # Entry 0: no flag field (68 bytes)
    off = 4
    entries.append({
        'type':     _u32le(raw, off),
        'flag':     None,
        'category': _cstr(raw, off+4,  32),
        'code':     _cstr(raw, off+36, 32),
    })
    off += LOAD_ENTRY0_SZ
    # Remaining: 72 bytes each
    while off + LOAD_ENTRY_SZ <= len(raw):
        entries.append({
            'type':     _u32le(raw, off),
            'flag':     _u32le(raw, off+4),
            'category': _cstr(raw, off+8,  32),
            'code':     _cstr(raw, off+40, 32),
        })
        off += LOAD_ENTRY_SZ
    return entries


def write_load(entries):
    """Serialise load entries to bytes."""
    size = LOAD_HDR_SZ + LOAD_ENTRY0_SZ + (len(entries)-1) * LOAD_ENTRY_SZ
    out = bytearray(size)
    data_size = size - LOAD_HDR_SZ
    struct.pack_into('>I', out, 0, data_size)
    off = LOAD_HDR_SZ
    for i, e in enumerate(entries):
        if i == 0:
            _wu32le(out, off, e['type'])
            _wstr(out, off+4,  e['category'], 32)
            _wstr(out, off+36, e['code'],     32)
            off += LOAD_ENTRY0_SZ
        else:
            _wu32le(out, off,   e['type'])
            _wu32le(out, off+4, e['flag'] if e['flag'] is not None else 0)
            _wstr(out, off+8,  e['category'], 32)
            _wstr(out, off+40, e['code'],     32)
            off += LOAD_ENTRY_SZ
    return out


# mot parser
def parse_mot(raw):
    """Parse mot binary data. raw = bytearray.
    Returns list of entry dicts; each has 'subentries' list.
    """
    entries = []
    i = 0
    offsets = []
    while True:
        j = bytes(raw).find(b'PL_ANM', i)
        if j < 0:
            break
        offsets.append(j)
        i = j + 1

    for idx, off in enumerate(offsets):
        next_off = offsets[idx + 1] if idx + 1 < len(offsets) else len(raw)
        ev = _cstr(raw, off,      32)
        an = _cstr(raw, off+0x20, 32)

        # Additional header fields from prm_mot.bt
        enable_face   = _u32le(raw, off+0x44) if off+0x48 <= len(raw) else 0
        no_frame_skip = _u32le(raw, off+0x48) if off+0x4C <= len(raw) else 0
        fix_position  = _u32le(raw, off+0x4C) if off+0x50 <= len(raw) else 0
        frame_skip    = _u32le(raw, off+0x64) if off+0x68 <= len(raw) else 0
        file_id       = _u32le(raw, off+0x98) if off+0x9C <= len(raw) else 0

        # sub_count stored in header at +0x6C
        n_subs = _u32le(raw, off+0x6C) if off+0x70 <= len(raw) else 0

        subs = []
        for s in range(n_subs):
            sub_off = off + MOT_HDR_SIZE + s * MOT_SUB_SIZE
            if sub_off + MOT_SUB_SIZE > len(raw):
                break

            bone      = _cstr(raw, sub_off+0x08, 32)
            dtype     = _u32le(raw, sub_off+0x34) if sub_off+0x38 <= len(raw) else 0
            dname     = DATA_TYPE_MAP.get(dtype, str(dtype))
            func_name = _decode_func(raw, sub_off)
            dmg       = raw[sub_off+0x6C] if sub_off+0x6C < len(raw) else 0
            grd       = raw[sub_off+0x7C] if sub_off+0x7C < len(raw) else 0
            speed_multiplier = 1.0
            if func_name in ANM_SPEED_FUNC_NAMES and sub_off+ANM_SPEED_MULTIPLIER_OFFSET+4 <= len(raw):
                sr = _f32le(raw, sub_off+ANM_SPEED_MULTIPLIER_OFFSET)
                speed_multiplier = 1.0 if not math.isfinite(sr) else sr

            # Frame label: Int16 LE at +0x30
            frame_w = struct.unpack_from('<H', raw, sub_off+0x30)[0] if sub_off+0x32 <= len(raw) else 0
            if frame_w == 0x270E:
                frame_str = 'Start'
            elif frame_w == 0x270F:
                frame_str = 'End'
            else:
                frame_str = str(frame_w)

            # DAMAGE_ID label at +0x18
            dmg_label = ''
            if sub_off+0x28 <= len(raw):
                candidate = raw[sub_off+0x18:sub_off+0x38].split(b'\x00')[0]
                if candidate.startswith(b'DAMAGE_ID'):
                    dmg_label = candidate.decode('ascii', errors='replace')
                elif candidate.startswith(b'DMG_') or candidate.startswith(b'STYLE_') \
                        or candidate.startswith(b'CMN_') or candidate.startswith(b'FACE_') \
                        or candidate.startswith(b'THROW'):
                    dmg_label = candidate.decode('ascii', errors='replace')

            is_dmg_id = dmg_label.startswith('DAMAGE_ID') or dtype == 48

            # X/Y: only for DAMAGE_ID entries; anchor = sub_off+0x18
            # X at anchor+0x48 = sub_off+0x60, Y at anchor+0x4C = sub_off+0x64
            x_val = 0.0
            y_val = 0.0
            if is_dmg_id and sub_off+0x68 <= len(raw):
                xr = _f32le(raw, sub_off+0x60)
                yr = _f32le(raw, sub_off+0x64)
                x_val = 0.0 if not math.isfinite(xr) else xr
                y_val = 0.0 if not math.isfinite(yr) else yr

            # Attack type (only for DAMAGE_ID entries)
            if is_dmg_id:
                b0 = raw[sub_off+0x00] if sub_off < len(raw) else 0
                b8 = raw[sub_off+0x08] if sub_off+0x08 < len(raw) else 0
                b9 = raw[sub_off+0x09] if sub_off+0x09 < len(raw) else 0
                if b8 == 0x02 or b9 == 0x02:
                    attack = 'unblockable'
                else:
                    attack = _ATTACK_MAP.get(b0, '')
            else:
                attack = ''

            # Push: signed int32 at anchor+0x50 = sub_off+0x68, DAMAGE_ID only
            push = 0
            if dmg_label.startswith('DAMAGE_ID') and sub_off+0x6C <= len(raw):
                push = struct.unpack_from('<i', raw, sub_off+0x68)[0]

            subs.append({
                'sub_off':   sub_off,
                'bone':      bone,
                'dtype':     dtype,
                'dname':     dname,
                'func_name': func_name,
                'frame_w':   frame_w,
                'frame_str': frame_str,
                'dmg':       dmg,
                'grd':       grd,
                'x':         x_val,
                'y':         y_val,
                'dmg_label': dmg_label,
                'attack':    attack,
                'push':      push,
                'speed_multiplier': speed_multiplier,
            })

        entries.append({
            'offset':     off,
            'raw_size':   next_off - off,
            'raw_n_subs': n_subs,
            'event_id':   ev,
            'anim_id':    an,
            'enable_face_animation': enable_face,
            'no_frame_skip':         no_frame_skip,
            'fix_position':          fix_position,
            'frame_skip':            frame_skip,
            'file_id':               file_id,
            'n_subs':     n_subs,
            'subentries': subs,
        })

    return entries


def write_mot_entry(raw_buf, entry):
    """Write back event_id, anim_id and header flags for one mot entry (in-place)."""
    off = entry.get('offset')
    if off is None:
        return
    _wstr(raw_buf, off,      entry['event_id'], 32)
    _wstr(raw_buf, off+0x20, entry['anim_id'],  32)
    if off+0x48 <= len(raw_buf):
        _wu32le(raw_buf, off+0x44, int(entry.get('enable_face_animation', 0)))
    if off+0x4C <= len(raw_buf):
        _wu32le(raw_buf, off+0x48, int(entry.get('no_frame_skip', 0)))
    if off+0x50 <= len(raw_buf):
        _wu32le(raw_buf, off+0x4C, int(entry.get('fix_position', 0)))
    if off+0x68 <= len(raw_buf):
        _wu32le(raw_buf, off+0x64, int(entry.get('frame_skip', 0)))
    if off+0x70 <= len(raw_buf):
        _wu32le(raw_buf, off+0x6C, len(entry.get('subentries', [])))
    if off+0x9C <= len(raw_buf):
        _wu32le(raw_buf, off+0x98, int(entry.get('file_id', 0)))


def write_mot_subentry(raw_buf, sub):
    """Write back subentry fields (in-place)."""
    off = sub.get('sub_off')
    if off is None:
        return
    dmg_label = sub.get('dmg_label', '')
    if dmg_label:
        # DAMAGE_ID-style records store flags and the DAMAGE_ID string inside
        # the range that other records use as a 32-byte bone name.
        _wstr_preserve_tail(raw_buf, off+0x18, dmg_label, 32)
    else:
        _wstr(raw_buf, off+0x08, sub['bone'], 32)
    _wu32le(raw_buf, off+0x34, sub['dtype'])
    if sub.get('func_name') in ANM_SPEED_FUNC_NAMES and off+ANM_SPEED_MULTIPLIER_OFFSET+4 <= len(raw_buf):
        _wf32le(raw_buf, off+ANM_SPEED_MULTIPLIER_OFFSET, sub.get('speed_multiplier', 1.0))
    _wu8(raw_buf, off+0x6C, sub['dmg'])
    _wu8(raw_buf, off+0x7C, sub['grd'])
    # frame: Int16 LE at +0x30
    fw = sub.get('frame_w', 0)
    struct.pack_into('<H', raw_buf, off+0x30, int(fw) & 0xFFFF)
    # X/Y/push: DAMAGE_ID only; anchor = off+0x18
    # X at anchor+0x48 = off+0x60, Y at anchor+0x4C = off+0x64, push at anchor+0x50 = off+0x68
    if dmg_label.startswith('DAMAGE_ID'):
        if off+0x68 <= len(raw_buf):
            _wf32le(raw_buf, off+0x60, sub.get('x', 0.0))
            _wf32le(raw_buf, off+0x64, sub.get('y', 0.0))
        if off+0x6C <= len(raw_buf):
            struct.pack_into('<i', raw_buf, off+0x68, int(sub.get('push', 0)))


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
        'bone': '',
        'dtype': 0,
        'dname': DATA_TYPE_MAP.get(0, '0'),
        'func_name': FUNC_MAP_1B.get(0, 'ME_ENEMY_CTRL_ON'),
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
    }


def write_mot(entries, original_raw):
    """Serialise a full prm_mot/prm_gha chunk from entry dicts.

    Existing entry bytes are used as templates so unknown fields survive.
    New entries/subentries are zero-filled and then populated with editable
    fields.
    """
    if original_raw and len(original_raw) >= MOT_GLOBAL_HDR:
        out = bytearray(original_raw[:MOT_GLOBAL_HDR])
    else:
        out = bytearray(MOT_GLOBAL_HDR)

    for entry in entries:
        subs = entry.get('subentries', [])
        old_off = entry.get('offset')
        old_count = int(entry.get('raw_n_subs', entry.get('n_subs', len(subs))) or 0)
        old_sub_len = MOT_HDR_SIZE + old_count * MOT_SUB_SIZE
        old_len = max(int(entry.get('raw_size', old_sub_len) or old_sub_len), old_sub_len)
        new_len = MOT_HDR_SIZE + len(subs) * MOT_SUB_SIZE

        if (
            old_off is not None
            and original_raw
            and 0 <= old_off
            and old_off + old_len <= len(original_raw)
        ):
            old_block = bytearray(original_raw[old_off:old_off + old_len])
            tail = old_block[old_sub_len:]
            block = old_block[:min(len(old_block), old_sub_len)]
        else:
            block = bytearray()
            tail = bytearray()

        if len(block) < new_len:
            block.extend(bytes(new_len - len(block)))
        elif len(block) > new_len:
            block = block[:new_len]
        block.extend(tail)

        new_off = len(out)
        entry['offset'] = new_off
        entry['raw_size'] = len(block)
        entry['raw_n_subs'] = len(subs)
        entry['n_subs'] = len(subs)
        write_mot_entry(block, {**entry, 'offset': 0})

        for i, sub in enumerate(subs):
            sub_off = MOT_HDR_SIZE + i * MOT_SUB_SIZE
            sub['sub_off'] = new_off + sub_off
            if old_off is None or i >= old_count:
                write_mot_subentry(block, {**sub, 'sub_off': sub_off})

        out.extend(block)

    struct.pack_into('>I', out, 0, len(out) - 4)
    if len(out) >= 0x2C:
        _wu32le(out, 0x28, len(entries) + 1)
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


def save_prm_xfbin(filepath, raw, result):
    """Write back modified chunks into raw bytearray and save to disk.

    Rebuild changed binary chunks and update their XFBIN chunk-size fields.
    sklslot/load may grow or shrink when entries are added or removed; mot/gha
    stay fixed-size payloads edited through their raw buffers.
    """
    replacements = []
    for key in ('load', 'sklslot', 'mot', 'gha'):
        if key not in result:
            continue
        info = result[key]
        hdr_off = info.get('hdr_off', info['data_off'] - 12)

        if key in ('mot', 'gha'):
            new_bytes = bytes(info['raw'])

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
        if key in ('mot', 'gha'):
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

    with open(filepath, 'wb') as f:
        f.write(raw)


# Standalone prm_load.bin.xfbin API
# Format (from prm_load.bt): uint32 count (LE) + count × 72-byte entries.
# Each entry: folder[32] + xfbin[32] + uint32 type + uint32 unk2.
# Type meanings: 3=ANIMATIONS, 6=GHA, 9=MODEL, 10=ACCESSORY, 11=EFFECTS, 13=PRM, 14=MISC

PRMLOAD_ENTRY_SIZE = 72


def parse_prmload_chunk(raw):
    """Parse chunk data of a standalone prm_load.bin.xfbin."""
    count = _u32le(raw, 0)
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
    entries = parse_prmload_chunk(chunk_raw)

    return raw, {
        'prmload_standalone': {
            'name':      name,
            'entries':   entries,
            'data_off':  data_off,
            'data_size': size,
        }
    }


def save_prmload_xfbin(filepath, raw, result):
    """Write back modified prm_load entries and save standalone file."""
    info = result['prmload_standalone']
    data_off  = info['data_off']
    data_size = info['data_size']

    new_bytes = bytearray(write_prmload_chunk(info['entries']))
    if len(new_bytes) < data_size:
        new_bytes = new_bytes + bytes(data_size - len(new_bytes))
    if len(new_bytes) != data_size:
        raise ValueError(
            f"prm_load chunk size changed {data_size} → {len(new_bytes)}. "
            "Keep same entry count to avoid XFBIN re-packing."
        )
    raw[data_off:data_off+data_size] = new_bytes
    with open(filepath, 'wb') as f:
        f.write(raw)
