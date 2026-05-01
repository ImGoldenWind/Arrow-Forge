import struct

# duelPlayerParam XFBIN parser

CHUNK_SIZE = 592
VARIANT_SLOTS = 19

BONE_ENTRIES = [
    (0xac, "Bone 1"),
    (0xd4, "Bone 2"),
    (0xfc, "Bone 3"),
    (0x124, "Bone 4"),
]

# Correct HurtSphere[n].HorizontalSize, HurtSphere[n].VerticalSize offsets
BONE_VALUE_OFFSETS = [
    (0xcc, 0xd0),    # HurtSphere[0]
    (0xf4, 0xf8),    # HurtSphere[1]
    (0x11c, 0x120),  # HurtSphere[2]
    (0x144, 0x148),  # HurtSphere[3]
]


def _read_le_u32(d, off):
    return struct.unpack('<I', d[off:off+4])[0]

def _read_le_i32(d, off):
    return struct.unpack('<i', d[off:off+4])[0]

def _read_le_f32(d, off):
    return struct.unpack('<f', d[off:off+4])[0]

def _read_le_u64(d, off):
    return struct.unpack('<Q', d[off:off+8])[0]

def _write_le_u32(d, off, val):
    struct.pack_into('<I', d, off, int(val))

def _write_le_i32(d, off, val):
    struct.pack_into('<i', d, off, int(val))

def _write_le_f32(d, off, val):
    struct.pack_into('<f', d, off, float(val))

def _write_le_u64(d, off, val):
    struct.pack_into('<Q', d, off, int(val))

def _read_str(d, off, length=8):
    return d[off:off+length].rstrip(b'\x00').decode('ascii', errors='replace')

def _write_str(d, off, s, length=8):
    encoded = s.encode('ascii')[:length]
    d[off:off+length] = encoded + b'\x00' * (length - len(encoded))


def parse_xfbin(filepath):
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    chunk_table_size = struct.unpack('>I', data[16:20])[0]
    chunk_data_start = 28 + chunk_table_size
    if chunk_data_start % 4:
        chunk_data_start += 4 - (chunk_data_start % 4)

    offset = chunk_data_start
    characters = []
    while offset < len(data) - 12:
        size = struct.unpack('>I', data[offset:offset+4])[0]
        if size == CHUNK_SIZE:
            chunk_offset = offset + 12
            cd = data[chunk_offset:chunk_offset+size]
            char_id = _read_str(cd, 8)
            char_data = {
                'chunk_offset': chunk_offset,
                'char_id': char_id,
                'name': char_id,
                'param_id': _read_le_u32(cd, 4),
                'variants': [],
                # HurtSpheres global collision fields (0xa0–0xab)
                'collision_threshold': _read_le_u32(cd, 0xa0),
                'camera_height': _read_le_i32(cd, 0xa4),
                'collision_size': _read_le_i32(cd, 0xa8),
                'bones': [],
                # Combat stats (0x14c–0x168)
                'hp': _read_le_u32(cd, 0x14c),
                'gha_damage': _read_le_u32(cd, 0x150),
                'max_gauge': _read_le_u32(cd, 0x154),
                'guard_gauge': _read_le_u32(cd, 0x158),
                'guard_break_recovery': _read_le_u32(cd, 0x15c),
                'dmg_scaling_1': _read_le_f32(cd, 0x160),  # Fire
                'dmg_scaling_2': _read_le_f32(cd, 0x164),  # Lightning
                'dmg_scaling_3': _read_le_f32(cd, 0x168),  # Hamon
                # 7 unknown floats (0x16c–0x187)
                'unk_floats': [_read_le_f32(cd, 0x16c + i * 4) for i in range(7)],
                'movement_blocks': [],
                # Post-physics fields
                'dlc_code': _read_le_u32(cd, 0x1f8),
                'icon_code': _read_le_u32(cd, 0x1fc),
                'corpse_parts': cd[0x200:0x220].rstrip(b'\x00').decode('ascii', errors='replace'),
                'style': _read_le_u32(cd, 0x220),
                'roster_position': _read_le_u32(cd, 0x224),
            }

            for i in range(VARIANT_SLOTS):
                s_off = 8 + i * 8
                if s_off + 8 > 0xa0:
                    break
                char_data['variants'].append(_read_str(cd, s_off))

            for (bone_off, bone_label), (v1_off, v2_off) in zip(BONE_ENTRIES, BONE_VALUE_OFFSETS):
                bone_name = cd[bone_off:bone_off+32].rstrip(b'\x00').decode('ascii', errors='replace')
                char_data['bones'].append({
                    'label': bone_label,
                    'name': bone_name,
                    'size_1': _read_le_u32(cd, v1_off),
                    'size_2': _read_le_u32(cd, v2_off),
                })

            block_names = ["Stand ON", "Stand OFF", "Alternate"]
            for bi, block_start in enumerate([0x188, 0x1ac, 0x1d0]):
                char_data['movement_blocks'].append({
                    'label': block_names[bi],
                    'fwd_walk':         _read_le_u32(cd, block_start),
                    'bwd_walk':         _read_le_u32(cd, block_start + 4),
                    'fwd_run':          _read_le_u32(cd, block_start + 8),
                    'bwd_run':          _read_le_u32(cd, block_start + 12),
                    'gravity_strength': _read_le_f32(cd, block_start + 16),
                    'jump_upward_vel':  _read_le_f32(cd, block_start + 20),
                    'jump_forward_vel': _read_le_f32(cd, block_start + 24),
                    'dash_jump_height': _read_le_f32(cd, block_start + 28),
                    'dash_jump_dist':   _read_le_f32(cd, block_start + 32),
                })

            characters.append(char_data)
        offset += 12 + size
        if offset % 4:
            offset += 4 - (offset % 4)

    return data, characters


def save_xfbin(filepath, data, characters):
    buf = bytearray(data)
    for char in characters:
        co = char['chunk_offset']
        cd = buf[co:co+CHUNK_SIZE]

        _write_le_u32(cd, 4, char['param_id'])
        _write_str(cd, 8, char['char_id'])

        for i, v in enumerate(char['variants']):
            s_off = 8 + i * 8
            if s_off + 8 > 0xa0:
                break
            _write_str(cd, s_off, v)

        _write_le_u32(cd, 0xa0, char['collision_threshold'])
        _write_le_i32(cd, 0xa4, char['camera_height'])
        _write_le_i32(cd, 0xa8, char['collision_size'])

        for bi, ((bone_off, _), (v1_off, v2_off)) in enumerate(zip(BONE_ENTRIES, BONE_VALUE_OFFSETS)):
            bone = char['bones'][bi]
            bone_name_bytes = bone['name'].encode('ascii')[:32]
            cd[bone_off:bone_off+32] = bone_name_bytes + b'\x00' * (32 - len(bone_name_bytes))
            _write_le_u32(cd, v1_off, bone['size_1'])
            _write_le_u32(cd, v2_off, bone['size_2'])

        _write_le_u32(cd, 0x14c, char['hp'])
        _write_le_u32(cd, 0x150, char['gha_damage'])
        _write_le_u32(cd, 0x154, char['max_gauge'])
        _write_le_u32(cd, 0x158, char['guard_gauge'])
        _write_le_u32(cd, 0x15c, char['guard_break_recovery'])
        _write_le_f32(cd, 0x160, char['dmg_scaling_1'])
        _write_le_f32(cd, 0x164, char['dmg_scaling_2'])
        _write_le_f32(cd, 0x168, char['dmg_scaling_3'])

        for i, val in enumerate(char['unk_floats']):
            _write_le_f32(cd, 0x16c + i * 4, val)

        for bi, block_start in enumerate([0x188, 0x1ac, 0x1d0]):
            block = char['movement_blocks'][bi]
            _write_le_u32(cd, block_start,      block['fwd_walk'])
            _write_le_u32(cd, block_start + 4,  block['bwd_walk'])
            _write_le_u32(cd, block_start + 8,  block['fwd_run'])
            _write_le_u32(cd, block_start + 12, block['bwd_run'])
            _write_le_f32(cd, block_start + 16, block['gravity_strength'])
            _write_le_f32(cd, block_start + 20, block['jump_upward_vel'])
            _write_le_f32(cd, block_start + 24, block['jump_forward_vel'])
            _write_le_f32(cd, block_start + 28, block['dash_jump_height'])
            _write_le_f32(cd, block_start + 32, block['dash_jump_dist'])

        _write_le_u32(cd, 0x1f8, char['dlc_code'])
        _write_le_u32(cd, 0x1fc, char['icon_code'])

        corpse_bytes = char['corpse_parts'].encode('ascii')[:32]
        cd[0x200:0x220] = corpse_bytes + b'\x00' * (32 - len(corpse_bytes))

        _write_le_u32(cd, 0x220, char['style'])
        _write_le_u32(cd, 0x224, char['roster_position'])

        buf[co:co+CHUNK_SIZE] = cd

    with open(filepath, 'wb') as f:
        f.write(buf)
