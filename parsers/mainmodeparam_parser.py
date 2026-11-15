import copy
import os
import struct
import tempfile

# MainModeParam.bin.xfbin parser
# Binary layout inside the nuccChunkBinary payload:
#   [0:4]   BE u32  – payload_size  (= total chunk bytes − 4)
#   [4:8]   LE u32  – version       (usually 1000)
#   [8:12]  LE u32  – count         (number of panels)
#   [12:20] LE u64  – first_ptr     (= 8 → notes_len = first_ptr − 8 = 0)
#   [20:]   count × PANEL_SIZE bytes of panel structs
#   [after panels:] string pool (null-terminated ASCII strings)
# Every string field in a panel is stored as a LE u64 relative pointer:
#   string_absolute_chunk_offset = ptr_field_chunk_offset + pointer_value
# Native loader 4E0F2C reads 32-bit scalars and the pointer at +28. Unmapped
# alignment bytes remain in each panel's _record. See story-mode-research.md.
# Ordinary saves retain the original pool. Structural edits rebuild pointers.

PANEL_SIZE  = 328
ENTRIES_OFF = 20      # fixed: 4(BE_size)+4(version)+4(count)+8(first_ptr)

# Field table
# key → (byte offset within panel, type)
# types: 'ptr' = relative-pointer string, 'u64', 'u32', 'i32'
_F = {
    'part':           (0,   'u32'),
    'ptr_panel_id':   (8,   'ptr'),
    'page':           (16,  'u32'),
    'ptr_boss_id':    (24,  'ptr'),
    'unk1':           (32,  'u32'),
    'ptr_str05':      (40,  'ptr'),
    'gold_reward':    (48,  'u32'),
    'type':           (52,  'u32'),
    'ptr_up':         (56,  'ptr'),
    'ptr_down':       (64,  'ptr'),
    'ptr_left':       (72,  'ptr'),
    'ptr_right':      (80,  'ptr'),
    'disp_diff':      (88,  'u32'),
    'cpu_level':      (92,  'u32'),
    'ptr_stage_id':   (96,  'ptr'),
    'unk3':           (104, 'u32'),
    'first_speak':    (112, 'u32'),
    'ptr_player_id':  (120, 'ptr'),
    'ptr_plyr_asst':  (128, 'ptr'),
    'ptr_plyr_btlst': (136, 'ptr'),
    'ptr_str14':      (144, 'ptr'),
    'ptr_plyr_win':   (152, 'ptr'),
    'ptr_enemy_id':   (160, 'ptr'),
    'ptr_enmy_asst':  (168, 'ptr'),
    'ptr_enmy_btlst': (176, 'ptr'),
    'ptr_str19':      (184, 'ptr'),
    'ptr_enmy_win':   (192, 'ptr'),
    'spec_rule_1':    (200, 'i32'),
    'spec_rule_2':    (204, 'i32'),
    'spec_rule_3':    (208, 'i32'),
    'spec_rule_4':    (212, 'i32'),  # legacy key: padding, NOT a fourth rule
    'm1_cond':        (216, 'i32'),
    'm1_unk':         (220, 'u32'),
    'ptr_m1_reward':  (224, 'ptr'),
    'm1_gold':        (232, 'u32'),
    'm2_cond':        (240, 'i32'),
    'm2_unk':         (244, 'u32'),
    'ptr_m2_reward':  (248, 'ptr'),
    'm2_gold':        (256, 'u32'),
    'm3_cond':        (264, 'i32'),
    'm3_unk':         (268, 'u32'),
    'ptr_m3_reward':  (272, 'ptr'),
    'm3_gold':        (280, 'u32'),
    'm4_cond':        (288, 'i32'),
    'm4_unk':         (292, 'u32'),
    'ptr_m4_reward':  (296, 'ptr'),
    'm4_gold':        (304, 'u32'),
    'extra_unk1':     (312, 'u32'),
    'extra_unk2':     (316, 'u32'),
    'extra_unk3':     (320, 'u32'),
    'total_idx':      (324, 'u32'),
}

PANEL_TYPE_NAMES = {0: 'Normal', 1: 'Extra', 2: 'Boss'}

# Pre-built list of ptr field names (used in pool construction)
_PTR_KEYS = [k for k, (_, t) in _F.items() if t == 'ptr']


# XFBIN helpers

def _find_binary_chunk(raw):
    """Locate the nuccChunkBinary (map_idx == 1).
    Returns (hdr_offset, data_offset, chunk_size).
    """
    chunk_table_size = struct.unpack('>I', raw[16:20])[0]
    offset = 28 + chunk_table_size
    while offset + 12 <= len(raw):
        sz = struct.unpack('>I', raw[offset:offset + 4])[0]
        mi = struct.unpack('>I', raw[offset + 4:offset + 8])[0]
        if sz > 0 and mi == 1:
            return offset, offset + 12, sz
        if sz == 0:
            offset += 12
        else:
            offset += 12 + sz
            if offset % 4:
                offset += 4 - offset % 4
    raise ValueError("nuccChunkBinary not found in XFBIN")


# Parse helpers

def _read_cstr(chunk, off):
    """Null-terminated ASCII string at chunk offset off. Returns (str, byte_len)."""
    end = off
    while end < len(chunk) and chunk[end] != 0:
        end += 1
    return chunk[off:end].decode('ascii', errors='replace'), end - off


def _follow_ptr(chunk, ptr_field_off):
    """Return (string, string_chunk_off, string_len)."""
    ptr_val = struct.unpack('<Q', chunk[ptr_field_off:ptr_field_off + 8])[0]
    if not ptr_val:
        return '', ptr_field_off, 0
    str_off = ptr_field_off + ptr_val
    if str_off >= len(chunk):
        return '', str_off, 0
    s, l = _read_cstr(chunk, str_off)
    return s, str_off, l


def _parse_panel(chunk, panel_chunk_off):
    p = {'_chunk_off': panel_chunk_off,
         '_record': bytes(chunk[panel_chunk_off:panel_chunk_off + PANEL_SIZE])}
    d = chunk[panel_chunk_off:panel_chunk_off + PANEL_SIZE]
    for name, (rel, kind) in _F.items():
        abs_off = panel_chunk_off + rel
        if kind == 'ptr':
            val, str_off, str_len = _follow_ptr(chunk, abs_off)
            p[name]              = val
            p[name + '_str_off'] = str_off
            p[name + '_str_len'] = str_len
        elif kind == 'u64':
            p[name] = struct.unpack('<Q', d[rel:rel + 8])[0]
        elif kind == 'i32':
            p[name] = struct.unpack('<i', d[rel:rel + 4])[0]
        elif kind == 'u32':
            p[name] = struct.unpack('<I', d[rel:rel + 4])[0]
    return p


# Public: parse

def parse_mainmodeparam(filepath):
    """Parse MainModeParam.bin.xfbin.

    Returns (raw_bytearray, result_dict).
    result_dict keys:
        'panels'           – list of panel dicts
        'version'          – uint32
        'count'            – original panel count
        'bin_hdr_offset'   – XFBIN chunk-header file offset
        'bin_data_offset'  – chunk-payload file offset
        'bin_chunk_size'   – original chunk payload size (bytes)
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    if len(raw) < 28 or raw[:4] != b'NUCC':
        raise ValueError('Not a NUCC/XFBIN file.')

    bin_hdr, bin_data, bin_sz = _find_binary_chunk(raw)
    chunk = raw[bin_data:bin_data + bin_sz]

    version   = struct.unpack('<I', chunk[4:8])[0]
    count     = struct.unpack('<I', chunk[8:12])[0]
    first_ptr = struct.unpack('<Q', chunk[12:20])[0]
    notes_len = first_ptr - 8
    ent_off   = ENTRIES_OFF + notes_len
    if notes_len < 0 or ent_off + count * PANEL_SIZE > len(chunk):
        raise ValueError('MainModeParam panel table exceeds chunk size.')

    panels = [_parse_panel(chunk, ent_off + i * PANEL_SIZE) for i in range(count)]

    return raw, {
        'panels':          panels,
        'version':         version,
        'count':           count,
        'notes':           bytes(chunk[ENTRIES_OFF:ent_off]),
        'bin_hdr_offset':  bin_hdr,
        'bin_data_offset': bin_data,
        'bin_chunk_size':  bin_sz,
    }


# Chunk builder (full rebuild, recalculates all pointers)

def _build_chunk(version, panels, notes=b''):
    """Serialise *panels* into a fresh chunk bytearray.

    String pool is laid out immediately after the panel array.
    All relative pointer values are computed from scratch.
    Returns the complete chunk payload (including the 4-byte BE size prefix).
    """
    count = len(panels)

    # 1. Build de-duplicated string pool
    pool      = bytearray()
    pool_map  = {}          # str → byte offset within pool

    def intern(s):
        s = str(s) if s is not None else ''
        if s not in pool_map:
            pool_map[s] = len(pool)
            if '\x00' in s:
                raise ValueError('Identifiers cannot contain NUL bytes.')
            pool.extend(s.encode('ascii') + b'\x00')
        return pool_map[s]

    for panel in panels:
        for key in _PTR_KEYS:
            intern(panel.get(key, ''))

    # String pool starts immediately after all panel structs
    pool_start = ENTRIES_OFF + len(notes) + count * PANEL_SIZE

    # 2. Serialise panel structs
    panels_buf = bytearray(count * PANEL_SIZE)

    for pi, panel in enumerate(panels):
        buf_off   = pi * PANEL_SIZE                  # offset within panels_buf
        chunk_off = ENTRIES_OFF + len(notes) + pi * PANEL_SIZE
        panels_buf[buf_off:buf_off + PANEL_SIZE] = panel.get('_record', bytes(PANEL_SIZE))

        for name, (rel, kind) in _F.items():
            field_chunk_off = chunk_off + rel
            dst             = buf_off + rel

            if kind == 'ptr':
                s       = str(panel.get(name, ''))
                ptr_val = (pool_start + pool_map[s]) - field_chunk_off
                struct.pack_into('<Q', panels_buf, dst, ptr_val)

            elif kind == 'u64':
                v = int(panel.get(name, 0)) & 0xFFFFFFFFFFFFFFFF
                struct.pack_into('<Q', panels_buf, dst, v)

            elif kind == 'i32':
                v = int(panel.get(name, 0))
                struct.pack_into('<i', panels_buf, dst, v)

            elif kind == 'u32':
                v = int(panel.get(name, 0))
                struct.pack_into('<I', panels_buf, dst, v)

    # 3. Assemble
    chunk = bytearray()
    chunk += b'\x00\x00\x00\x00'           # BE payload size – filled below
    chunk += struct.pack('<I', version)     # version
    chunk += struct.pack('<I', count)       # count
    chunk += struct.pack('<Q', 8 + len(notes))
    chunk += notes
    chunk += panels_buf
    chunk += pool

    struct.pack_into('>I', chunk, 0, len(chunk) - 4)
    return chunk


# Public: save (patch scalars / append changed strings; rebuild on CRUD)

def save_mainmodeparam(filepath, raw, result):
    """Serialise *result['panels']* and atomically write to *filepath*.

    Supports any number of panels (add / remove freely).
    Structural edits recompute pointers; unchanged records retain the pool,
    zero pointers, alignment bytes and unrelated XFBIN chunks.
    """
    panels   = result['panels']
    version  = result['version']
    bin_hdr  = result['bin_hdr_offset']
    bin_data = result['bin_data_offset']
    old_sz   = result['bin_chunk_size']

    notes = result.get('notes', b'')
    old_chunk = raw[bin_data:bin_data + old_sz]
    old_count = struct.unpack_from('<I', old_chunk, 8)[0]
    old_start = 12 + struct.unpack_from('<Q', old_chunk, 12)[0]
    # Retain the original pool (including zero pointers, aliases and padding).
    # Only changed strings are appended. Reordering/CRUD rebuilds all pointers.
    if (len(panels) == old_count and notes == old_chunk[20:old_start]
            and all(p.get('_chunk_off') == old_start + i * PANEL_SIZE for i, p in enumerate(panels))):
        new_chunk = bytearray(old_chunk)
        struct.pack_into('<I', new_chunk, 4, version)
        for panel in panels:
            base = panel['_chunk_off']
            for key, (rel, kind) in _F.items():
                value = panel.get(key, '' if kind == 'ptr' else 0)
                if kind == 'ptr':
                    value = str(value)
                    if value != _follow_ptr(old_chunk, base + rel)[0]:
                        if '\x00' in value:
                            raise ValueError('Identifiers cannot contain NUL bytes.')
                        encoded = value.encode('ascii') + b'\x00'
                        struct.pack_into('<Q', new_chunk, base + rel, len(new_chunk) - base - rel)
                        new_chunk.extend(encoded)
                else:
                    struct.pack_into('<' + {'u32': 'I', 'i32': 'i', 'u64': 'Q'}[kind], new_chunk, base + rel, int(value))
        struct.pack_into('>I', new_chunk, 0, len(new_chunk) - 4)
    else:
        new_chunk = _build_chunk(version, panels, notes)
    new_sz    = len(new_chunk)

    if new_sz == old_sz:
        # Preserve original alignment bytes, including unpadded final chunks.
        buf = bytearray(raw)
        buf[bin_data:bin_data + old_sz] = new_chunk
    else:
        old_end = min((bin_data + old_sz + 3) & ~3, len(raw))
        suffix = raw[old_end:]
        padded = bytearray(new_chunk)
        if suffix:
            padded += bytes((-len(padded)) % 4)
        new_hdr = bytearray(raw[bin_hdr:bin_hdr + 12])
        struct.pack_into('>I', new_hdr, 0, new_sz)
        buf = raw[:bin_hdr] + new_hdr + padded + suffix

    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-story-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(buf)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# Public: make_default_panel

def make_default_panel(reference=None):
    """Return a fresh panel dict with sensible defaults.

    If *reference* is given, all field values are copied from it and only
    the panel-identity fields (ptr_panel_id, total_idx) are cleared so the
    caller can set unique values.
    """
    if reference is not None:
        p = copy.deepcopy(reference)
        p['_chunk_off']  = -1
        p['ptr_panel_id'] = ''
        # strip cached parse metadata; not needed for the rebuild save
        for key in list(p.keys()):
            if key.endswith('_str_off') or key.endswith('_str_len'):
                p[key] = 0
        return p

    # brand-new panel
    p = {'_chunk_off': -1}
    for name, (_, kind) in _F.items():
        if kind == 'ptr':
            p[name]              = ''
            p[name + '_str_off'] = 0
            p[name + '_str_len'] = 0
        elif kind in ('u64', 'u32'):
            p[name] = 0
        else:  # i32
            p[name] = -1

    # sensible game defaults
    p.update({
        'part':         1,
        'page':         1,
        'gold_reward':  1000,
        'type':         0,
        'disp_diff':    2,
        'cpu_level':    2,
        'first_speak':  0,
        'unk3':         1,
        'spec_rule_1': -1,
        'spec_rule_2': -1,
        'spec_rule_3': -1,
        'spec_rule_4': -1,
        'm1_cond':     -1,
        'm2_cond':     -1,
        'm3_cond':     -1,
        'm4_cond':     -1,
    })
    return p
