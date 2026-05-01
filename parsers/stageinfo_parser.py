"""
StageInfo.bin.xfbin  –  parser + round-trip writer

Binary layout (inside the XFBIN binary chunk):
  Offset 0  : uint32 BE  – file_size (size of LE section that follows)
  Offset 4  : int32  LE  – version  (e.g. 1003)
  Offset 8  : int32  LE  – count    (number of stages, 19 in retail)
  Offset 12 : uint64 LE  – offset_to_first (relative ptr → first stage at d+20)
  Offset 20 : stage blocks × count  (176 bytes each = 40 hdr + 136 params)
  Pointer tables area    (path ptrs + clump structs, one set per stage)
  String data area       (stage codes, path strings, clump strings)

Stage block (176 bytes):
  +0   uint64 LE  code_offset      → relative ptr to 24-char stage code
  +8   uint64 LE  path_count
  +16  uint64 LE  path_ptrs_off    → relative ptr to path pointer table
  +24  uint64 LE  clump_count
  +32  uint64 LE  clump_ptrs_off   → relative ptr to clump struct table
  +40  136 bytes  stage_params     (colours, floats – see PARAM_* constants)

Clump struct (56 bytes, repeated clump_count times):
  +0   uint64 LE  xfbin_path_off   → relative ptr to xfbin path string
  +8   uint64 LE  clump_name_off   → relative ptr to clump name string
  +16  uint64 LE  unk_name_off     → relative ptr to unk string (often empty)
  +24  uint64 LE  unk2_name_off    → relative ptr to unk2 string (often empty)
  +32  16 bytes   skip_data        (uint32 flag, float, 8 zero bytes)
  +48  uint32 LE  val1
  +52  uint32 LE  val2

All strings are null-terminated and padded to the next 8-byte boundary
using  pad = (8 − (sizeof_incl_null % 8)) % 8  (standard 8-byte alignment).
Stage codes use variable-length aligned strings (same _str_padded formula as all other strings).
"""

import struct

# Constants
STAGE_HDR_SIZE   = 40     # 5 × uint64
STAGE_PARAM_SIZE = 136    # 17 × uint32 of stage environment parameters
STAGE_BLOCK_SIZE = 176    # STAGE_HDR_SIZE + STAGE_PARAM_SIZE
STAGE_CODE_SIZE  = 24     # fixed char[24] field
CLUMP_STRUCT_SIZE = 56    # 4 ptr × 8 + 16 skip + 2 × uint32

# Stage params field layout (offsets relative to start of the 136-byte block)
# Layout:  6 × 4-byte colour  |  3 × float32  |  uint32 flag1
#          4-byte colour7     |  8 zero bytes  |  float1  |  float2
#          4-byte colour8     |  uint32 flag2  |  7 × float32  |  40 zero bytes

PARAM_COLORS       = [(i*4, f"Color {i+1}") for i in range(6)]          # bytes 0-23
PARAM_POS_X        = (24,  "Pos X (float)")
PARAM_POS_Y        = (28,  "Pos Y (float)")
PARAM_POS_Z        = (32,  "Pos Z (float)")
PARAM_FLAG1        = (36,  "Flag 1 (uint32)")
PARAM_COLOR7       = (40,  "Color 7")
PARAM_ZEROS1       = (44,  "Reserved 1 (8 bytes)")
PARAM_FLOAT1       = (52,  "Float 1")
PARAM_FLOAT2       = (56,  "Float 2")
PARAM_COLOR8       = (60,  "Color 8")
PARAM_FLAG2        = (64,  "Flag 2 (uint32)")
PARAM_FLOAT3       = (68,  "Float 3")
PARAM_FLOAT4       = (72,  "Float 4")
PARAM_FLOAT5       = (76,  "Float 5")
PARAM_FLOAT6       = (80,  "Float 6")
PARAM_FLOAT7       = (84,  "Float 7")
PARAM_FLOAT8       = (88,  "Float 8")
PARAM_FLOAT9       = (92,  "Float 9")
PARAM_ZEROS2       = (96,  "Reserved 2 (40 bytes)")


# Helpers

def _find_binary_chunk(raw):
    """Return (bin_hdr_offset, bin_data_offset, chunk_size)."""
    chunk_table_size = struct.unpack('>I', raw[16:20])[0]
    chunk_data_start = 28 + chunk_table_size
    offset = chunk_data_start
    while offset + 12 <= len(raw):
        chunk_size = struct.unpack('>I', raw[offset:offset + 4])[0]
        map_idx    = struct.unpack('>I', raw[offset + 4:offset + 8])[0]
        if chunk_size > 0 and map_idx == 1:
            return offset, offset + 12, chunk_size
        if chunk_size == 0:
            offset += 12
        else:
            offset += 12 + chunk_size
            if offset % 4:
                offset += 4 - (offset % 4)
    raise ValueError("Binary chunk not found in XFBIN")


def _read_cstr(buf, addr):
    end = addr
    while end < len(buf) and buf[end] != 0:
        end += 1
    return buf[addr:end].decode('ascii', errors='replace')


def _str_padded(s):
    """Encode string to bytes: null-terminated, padded to 8-byte boundary.

    Standard alignment: pad = (8 - (n % 8)) % 8  (0..7, can be 0).
    """
    encoded = s.encode('ascii', errors='replace')
    n       = len(encoded) + 1          # including null terminator
    pad     = (8 - (n % 8)) % 8        # 0..7
    return encoded + b'\x00' * (1 + pad)


# Parser

def parse_stageinfo_xfbin(filepath):
    """Parse StageInfo.bin.xfbin.

    Returns (raw_bytearray, result_dict).
    result_dict:
        'version'          – int
        'stages'           – list of stage dicts (see below)
        'bin_hdr_offset'   – XFBIN chunk header offset
        'bin_data_offset'  – start of binary payload in file

    Stage dict:
        'code'    – str (stage code, variable-aligned string)
        'paths'   – list of str  (XfbinPaths)
        'clumps'  – list of clump dicts
        'params'  – bytearray (136 bytes of stage environment parameters)

    Clump dict:
        'xfbin_path'  – str
        'clump_name'  – str
        'unk_name'    – str (usually '')
        'unk2_name'   – str (usually '')
        'skip_data'   – bytes (16 bytes: flag u32, param f32, 8 zeros)
        'val1'        – int
        'val2'        – int
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    bin_hdr_off, bin_data_off, bin_chunk_size = _find_binary_chunk(raw)
    d = raw[bin_data_off: bin_data_off + bin_chunk_size]

    version = struct.unpack('<i', d[4:8])[0]
    count   = struct.unpack('<i', d[8:12])[0]

    stages = []
    for i in range(count):
        base = 20 + i * STAGE_BLOCK_SIZE   # stage block starts at d+20 (=0x14)

        # Header fields (5 × uint64)
        code_off      = struct.unpack('<Q', d[base     : base + 8])[0]
        path_count    = struct.unpack('<Q', d[base +  8: base +16])[0]
        path_ptr_off  = struct.unpack('<Q', d[base + 16: base +24])[0]
        clump_count   = struct.unpack('<Q', d[base + 24: base +32])[0]
        clump_ptr_off = struct.unpack('<Q', d[base + 32: base +40])[0]

        # Stage code: variable-aligned string (same formula as all others)
        stage_code = _read_cstr(d, base + code_off)

        # Path pointer table: target = (base+16) + path_ptr_off
        path_table = base + 16 + path_ptr_off
        paths = []
        for j in range(path_count):
            ptr_addr = path_table + j * 8
            ptr_val  = struct.unpack('<Q', d[ptr_addr: ptr_addr + 8])[0]
            paths.append(_read_cstr(d, ptr_addr + ptr_val))

        # Clump struct table: target = (base+32) + clump_ptr_off
        clump_table = base + 32 + clump_ptr_off
        clumps = []
        cur = clump_table
        for j in range(clump_count):
            p0 = struct.unpack('<Q', d[cur     : cur +  8])[0]
            p1 = struct.unpack('<Q', d[cur +  8: cur + 16])[0]
            p2 = struct.unpack('<Q', d[cur + 16: cur + 24])[0]
            p3 = struct.unpack('<Q', d[cur + 24: cur + 32])[0]
            clumps.append({
                'xfbin_path': _read_cstr(d, cur      + p0),
                'clump_name': _read_cstr(d, cur +  8 + p1),
                'unk_name':   _read_cstr(d, cur + 16 + p2),
                'unk2_name':  _read_cstr(d, cur + 24 + p3),
                'skip_data':  bytes(d[cur + 32: cur + 48]),
                'val1':       struct.unpack('<I', d[cur + 48: cur + 52])[0],
                'val2':       struct.unpack('<I', d[cur + 52: cur + 56])[0],
            })
            cur += CLUMP_STRUCT_SIZE

        # Stage environment params (136 bytes, immediately after header)
        params_off = base + STAGE_HDR_SIZE
        stages.append({
            'code':   stage_code,
            'paths':  paths,
            'clumps': clumps,
            'params': bytearray(d[params_off: params_off + STAGE_PARAM_SIZE]),
        })

    return raw, {
        'version':         version,
        'stages':          stages,
        'bin_hdr_offset':  bin_hdr_off,
        'bin_data_offset': bin_data_off,
    }


# Writer

def save_stageinfo_xfbin(filepath, raw, result):
    """Rebuild StageInfo.bin.xfbin from result dict and write to filepath.

    Handles additions/removals of paths and clumps by fully rebuilding
    the binary payload and recalculating all relative pointers.
    """
    stages       = result['stages']
    version      = result['version']
    bin_hdr_off  = result['bin_hdr_offset']
    bin_data_off = result['bin_data_offset']

    count = len(stages)

    # 1. Compute section sizes

    # Section A: binary header
    HDR_BYTES = 20   # FileSize(4 BE) + Version(4 LE) + Count(4 LE) + OffToFirst(8 LE)

    # Section B: stage blocks
    BLOCKS_BYTES = count * STAGE_BLOCK_SIZE   # 19 × 176 = 3344

    # Section C: pointer tables (paths + clump structs for each stage, sequential)
    ptr_table_bytes = sum(
        len(s['paths']) * 8 + len(s['clumps']) * CLUMP_STRUCT_SIZE
        for s in stages
    )

    # Section D: string data (computed below)
    STRING_START = HDR_BYTES + BLOCKS_BYTES + ptr_table_bytes

    # 2. Build string data, tracking where each string lives
    # Per stage (in order 0..N):
    #   stage code (fixed STAGE_CODE_SIZE = 24 bytes)
    #   path strings (padded)
    #   clump strings: xfbin_path, clump_name, unk_name, unk2_name (padded each)

    string_blob = bytearray()

    # str_addrs[stage_idx] = {
    #    'code': int, 'paths': [int,...], 'clumps': [{'xfbin_path':int,...}, ...]
    # }
    str_addrs = []

    def _alloc(encoded_padded):
        off = STRING_START + len(string_blob)
        string_blob.extend(encoded_padded)
        return off

    def _alloc_str(s):
        return _alloc(_str_padded(s))

    for s in stages:
        addrs = {'code': _alloc_str(s['code']), 'paths': [], 'clumps': []}
        for p in s['paths']:
            addrs['paths'].append(_alloc_str(p))
        for c in s['clumps']:
            addrs['clumps'].append({
                'xfbin_path': _alloc_str(c['xfbin_path']),
                'clump_name': _alloc_str(c['clump_name']),
                'unk_name':   _alloc_str(c['unk_name']),
                'unk2_name':  _alloc_str(c['unk2_name']),
            })
        str_addrs.append(addrs)

    # 3. Build output buffer

    total_bin = STRING_START + len(string_blob)
    out = bytearray(total_bin)

    # Section A: binary header
    struct.pack_into('>I', out,  0, total_bin - 4)    # FileSize BE  (LE section size)
    struct.pack_into('<i', out,  4, version)
    struct.pack_into('<i', out,  8, count)
    # OffsetToFirstEntry at d+12 (uint64 LE): stages start at d+20
    # Formula: target = ptr_addr + value → 12 + value = 20 → value = 8
    struct.pack_into('<Q', out, 12, 8)

    # Compute path/clump table start for each stage
    ptr_cursor = HDR_BYTES + BLOCKS_BYTES
    stage_ptr_starts = []
    for s in stages:
        path_tbl  = ptr_cursor
        ptr_cursor += len(s['paths']) * 8
        clump_tbl = ptr_cursor
        ptr_cursor += len(s['clumps']) * CLUMP_STRUCT_SIZE
        stage_ptr_starts.append((path_tbl, clump_tbl))

    # Section B + C: stage blocks and pointer tables
    for i, (s, (path_tbl, clump_tbl)) in enumerate(zip(stages, stage_ptr_starts)):
        base = HDR_BYTES + i * STAGE_BLOCK_SIZE    # = 20 + i*176

        addrs = str_addrs[i]

        # CodeOffset: target = addrs['code'], stored at base
        #   target = base + code_offset  →  code_offset = target - base
        struct.pack_into('<Q', out, base,      addrs['code'] - base)

        # PathCount
        struct.pack_into('<Q', out, base +  8, len(s['paths']))

        # PathPointersOffset: path_tbl address stored at base+16
        #   target = (base+16) + path_ptrs_off  →  off = path_tbl - (base+16)
        struct.pack_into('<Q', out, base + 16, path_tbl - (base + 16))

        # ClumpsCount
        struct.pack_into('<Q', out, base + 24, len(s['clumps']))

        # ClumpsPointersOffset: clump_tbl at base+32
        #   target = (base+32) + clump_ptrs_off  →  off = clump_tbl - (base+32)
        struct.pack_into('<Q', out, base + 32, clump_tbl - (base + 32))

        # Stage params (136 bytes)
        p = bytes(s['params'])[:STAGE_PARAM_SIZE]
        p += b'\x00' * (STAGE_PARAM_SIZE - len(p))
        out[base + STAGE_HDR_SIZE: base + STAGE_HDR_SIZE + STAGE_PARAM_SIZE] = p

        # Path pointer table
        for j, (path_addr, pth) in enumerate(zip(addrs['paths'], s['paths'])):
            ptr_addr = path_tbl + j * 8
            struct.pack_into('<Q', out, ptr_addr, path_addr - ptr_addr)

        # Clump struct table
        cur = clump_tbl
        for c, ca in zip(s['clumps'], addrs['clumps']):
            struct.pack_into('<Q', out, cur,      ca['xfbin_path'] - cur)
            struct.pack_into('<Q', out, cur +  8, ca['clump_name'] - (cur +  8))
            struct.pack_into('<Q', out, cur + 16, ca['unk_name']   - (cur + 16))
            struct.pack_into('<Q', out, cur + 24, ca['unk2_name']  - (cur + 24))
            # skip_data (16 bytes)
            sd = bytes(c['skip_data'])[:16]
            sd += b'\x00' * (16 - len(sd))
            out[cur + 32: cur + 48] = sd
            struct.pack_into('<I', out, cur + 48, c['val1'])
            struct.pack_into('<I', out, cur + 52, c['val2'])
            cur += CLUMP_STRUCT_SIZE

    # Section D: string data
    out[STRING_START: STRING_START + len(string_blob)] = string_blob

    # 4. Rebuild XFBIN

    old_chunk_size = struct.unpack('>I', raw[bin_hdr_off: bin_hdr_off + 4])[0]
    old_chunk_end  = bin_data_off + old_chunk_size
    if old_chunk_end % 4:
        old_chunk_end += 4 - (old_chunk_end % 4)

    # Patch chunk size header (keep map_idx etc. unchanged)
    new_hdr = bytearray(raw[bin_hdr_off: bin_hdr_off + 12])
    struct.pack_into('>I', new_hdr, 0, total_bin)

    buf = raw[:bin_hdr_off] + new_hdr + out + raw[old_chunk_end:]

    with open(filepath, 'wb') as f:
        f.write(buf)


# Stage params helpers (for the editor)

def params_get_color(params, byte_offset):
    """Return 4-byte colour tuple (b0, b1, b2, b3) from params."""
    return tuple(params[byte_offset: byte_offset + 4])

def params_set_color(params, byte_offset, rgba):
    params[byte_offset: byte_offset + 4] = bytes(rgba[:4])

def params_get_float(params, byte_offset):
    return struct.unpack_from('<f', params, byte_offset)[0]

def params_set_float(params, byte_offset, value):
    struct.pack_into('<f', params, byte_offset, value)

def params_get_uint32(params, byte_offset):
    return struct.unpack_from('<I', params, byte_offset)[0]

def params_set_uint32(params, byte_offset, value):
    struct.pack_into('<I', params, byte_offset, int(value))

def params_get_bytes(params, byte_offset, length):
    return bytes(params[byte_offset: byte_offset + length])

def params_set_bytes(params, byte_offset, data):
    params[byte_offset: byte_offset + len(data)] = data

def clump_get_skip_flag(skip_data):
    """uint32 at skip_data[0]."""
    return struct.unpack_from('<I', skip_data, 0)[0]

def clump_set_skip_flag(skip_data, value):
    b = bytearray(skip_data)
    struct.pack_into('<I', b, 0, int(value))
    return bytes(b)

def clump_get_skip_float(skip_data):
    """float32 at skip_data[4]."""
    return struct.unpack_from('<f', skip_data, 4)[0]

def clump_set_skip_float(skip_data, value):
    b = bytearray(skip_data)
    struct.pack_into('<f', b, 4, float(value))
    return bytes(b)
