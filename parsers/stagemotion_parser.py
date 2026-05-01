"""parsers/stagemotion_parser.py – Parser for Xcmnsfprm.bin.xfbin.

Binary layout (XFBIN container, big-endian sizes):
  [NUCC header]
  [Chunk table, chunk_table_size bytes]
  [Null chunk,   12-byte header, size=0]
  [Binary chunk, 12-byte header, size=N]
    payload[0:4]  BE u32  = chunk_size - 4   (= N-4)
    payload[4:8]  LE u32  = file_magic_count  (preserved as-is = 1001)
    payload[8:36] zeros   (28 bytes padding)
    payload[36:]  stage blocks
  [trailing zeros in payload]
  [Page + Index chunks]

Stage Block layout (156 + n_entries * 200 bytes):
  Header (156 bytes):
    [0x00:0x04]  zeros
    [0x04:0x08]  id_flag    LE u32   (0x13 only for SF_1; 0 elsewhere)
    [0x08:0x28]  nut_type   char[32] (e.g. "PL_ANM_NUT")
    [0x28:0x48]  stage_id   char[32] (e.g. "SF_1_DIOCASTLE")
    [0x48:0x64]  zeros      (28 bytes)
    [0x64:0x6C]  0xFFFFFFFF 0xFFFFFFFF  (8-byte -1 sentinel)
    [0x6C:0x74]  zeros      (8 bytes)
    [0x74:0x78]  entry_count LE u32
    [0x78:0x7C]  sub_count   LE u32  (preserved as-is)
    [0x7C:0x9C]  zeros      (32 bytes)
  Entry (200 bytes):
    [0x00:0x10]  zeros      (16 bytes)
    [0x10:0x30]  name       char[32]  action name (may be empty)
    [0x30:0x38]  zeros      (8 bytes)
    [0x38:0x3C]  frame      LE u32    keyframe where this applies
    [0x3C:0x40]  type_code  LE u32    0x44=anim-scale, 0xEE=face-expr, 0x84=speaking,
                                       0x111=sync-marker, 0x70/0x6F=unknown
    [0x40:0x44]  val3       LE u32    duration for speaking (0x84) entries
    [0x44:0x54]  zeros      (16 bytes)
    [0x54:0x58]  float_val  LE f32    speed/scale for 0x44 entries
    [0x58:0xC8]  zeros      (112 bytes)

Type codes:
  0x0044 (68)  – Animation speed/scale modifier. float_val = multiplier.
  0x00EE (238) – Face/expression trigger. No float.
  0x0084 (132) – Speaking/voice trigger. val3 = duration in frames.
  0x0111 (273) – Synchronisation timing marker. No other data.
  0x0070 (112) – Unknown (rare). No data.
  0x006F (111) – Unknown (rare). No data.
"""

import struct

STAGE_HEADER_SIZE = 156   # 0x9C
ENTRY_SIZE        = 200   # 0xC8
PAYLOAD_PRELUDE   = 36    # 8-byte XFBIN prefix + 28 zero bytes before stage blocks
TRAILING_ZEROS    = 8     # padding after last stage block, inside binary chunk


# Low-level chunk finder (shared with other parsers)

def _find_binary_chunk(raw):
    """Return (hdr_offset, data_offset, chunk_size) for the nuccChunkBinary."""
    chunk_table_size = struct.unpack('>I', raw[16:20])[0]
    chunk_data_start = 28 + chunk_table_size
    offset = chunk_data_start
    while offset + 12 <= len(raw):
        chunk_size = struct.unpack('>I', raw[offset:offset + 4])[0]
        map_idx    = struct.unpack('>I', raw[offset + 4:offset + 8])[0]
        if map_idx == 1 and chunk_size > 0:
            return offset, offset + 12, chunk_size
        offset += 12 if chunk_size == 0 else (12 + chunk_size + (4 - (chunk_size % 4)) % 4)
    raise ValueError("Binary chunk not found in XFBIN")


# Stage / Entry helpers

def _read_str(buf, off, length=32):
    return buf[off:off + length].rstrip(b'\x00').decode('ascii', errors='replace')


def _write_str(buf, off, text, length=32):
    enc = text.encode('ascii', errors='replace')[:length]
    buf[off:off + length] = enc + b'\x00' * (length - len(enc))


def _parse_entry(raw_entry):
    """Parse one 200-byte entry dict."""
    return {
        'name':      _read_str(raw_entry, 0x10),
        'frame':     struct.unpack_from('<I', raw_entry, 0x38)[0],
        'type_code': struct.unpack_from('<I', raw_entry, 0x3C)[0],
        'val3':      struct.unpack_from('<I', raw_entry, 0x40)[0],
        'float_val': struct.unpack_from('<f', raw_entry, 0x54)[0],
    }


def _pack_entry(entry):
    """Serialise one entry dict → 200-byte bytearray."""
    buf = bytearray(ENTRY_SIZE)
    _write_str(buf, 0x10, entry.get('name', ''))
    struct.pack_into('<I', buf, 0x38, int(entry.get('frame', 0)))
    struct.pack_into('<I', buf, 0x3C, int(entry.get('type_code', 0x44)))
    struct.pack_into('<I', buf, 0x40, int(entry.get('val3', 0)))
    struct.pack_into('<f', buf, 0x54, float(entry.get('float_val', 0.0)))
    return buf


def _parse_stage(raw_block):
    """Parse one stage block (variable length) → dict."""
    h = raw_block
    id_flag    = struct.unpack_from('<I', h, 0x04)[0]
    nut_type   = _read_str(h, 0x08)
    stage_id   = _read_str(h, 0x28)
    entry_count= struct.unpack_from('<I', h, 0x74)[0]
    sub_count  = struct.unpack_from('<I', h, 0x78)[0]

    entries = []
    for i in range(entry_count):
        off = STAGE_HEADER_SIZE + i * ENTRY_SIZE
        entries.append(_parse_entry(raw_block[off:off + ENTRY_SIZE]))

    return {
        'id_flag':    id_flag,
        'nut_type':   nut_type,
        'stage_id':   stage_id,
        'entry_count':entry_count,
        'sub_count':  sub_count,
        'entries':    entries,
    }


def _pack_stage(stage):
    """Serialise one stage dict → bytearray of correct length."""
    entries = stage.get('entries', [])
    n = len(entries)
    total = STAGE_HEADER_SIZE + n * ENTRY_SIZE
    buf = bytearray(total)

    struct.pack_into('<I', buf, 0x04, int(stage.get('id_flag', 0)))
    _write_str(buf, 0x08, stage.get('nut_type', 'PL_ANM_NUT'))
    _write_str(buf, 0x28, stage.get('stage_id', ''))
    # sentinel -1 at 0x64
    struct.pack_into('<Q', buf, 0x64, 0xFFFFFFFFFFFFFFFF)
    struct.pack_into('<I', buf, 0x74, n)
    struct.pack_into('<I', buf, 0x78, int(stage.get('sub_count', 2)))

    for i, e in enumerate(entries):
        off = STAGE_HEADER_SIZE + i * ENTRY_SIZE
        buf[off:off + ENTRY_SIZE] = _pack_entry(e)

    return buf


# Public API

def parse_stagemotion_xfbin(filepath):
    """Parse Xcmnsfprm.bin.xfbin.

    Returns (raw_bytearray, result_dict).
    result_dict keys:
        'stages'          – list of stage dicts
        'file_magic'      – LE u32 at payload[4:8] (preserved verbatim)
        'bin_hdr_offset'  – file offset of 12-byte binary-chunk header
        'bin_data_offset' – file offset where chunk payload begins
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    hdr_off, data_off, chunk_size = _find_binary_chunk(raw)
    payload = raw[data_off:data_off + chunk_size]

    file_magic = struct.unpack_from('<I', payload, 4)[0]

    # Stage blocks start at payload offset 36
    stages_data = payload[PAYLOAD_PRELUDE:]

    stages = []
    offset = 0
    while offset + STAGE_HEADER_SIZE <= len(stages_data):
        # Detect start of next block: must have valid PL_ANM_NUT marker
        # Read entry_count from header
        entry_count = struct.unpack_from('<I', stages_data, offset + 0x74)[0]
        if entry_count == 0 and stages_data[offset + 0x08:offset + 0x10] == b'\x00' * 8:
            break  # trailing zeros
        block_size = STAGE_HEADER_SIZE + entry_count * ENTRY_SIZE
        if offset + block_size > len(stages_data):
            break
        stages.append(_parse_stage(stages_data[offset:offset + block_size]))
        offset += block_size

    return raw, {
        'stages':         stages,
        'file_magic':     file_magic,
        'bin_hdr_offset': hdr_off,
        'bin_data_offset':data_off,
    }


def save_stagemotion_xfbin(filepath, raw, result):
    """Serialise stages back into the XFBIN and write to filepath."""
    stages       = result['stages']
    file_magic   = result.get('file_magic', 1001)
    bin_hdr_off  = result['bin_hdr_offset']
    bin_data_off = result['bin_data_offset']

    old_chunk_size = struct.unpack('>I', raw[bin_hdr_off:bin_hdr_off + 4])[0]
    old_chunk_end  = bin_data_off + old_chunk_size
    # align to 4 bytes
    if old_chunk_end % 4:
        old_chunk_end += 4 - (old_chunk_end % 4)

    # Build stage blocks
    stage_bytes = bytearray()
    for s in stages:
        stage_bytes += _pack_stage(s)

    # Build payload: [size_be:4][magic_le:4][zeros:28][stage_blocks][trailing_zeros:8]
    new_data_size = PAYLOAD_PRELUDE + len(stage_bytes) + TRAILING_ZEROS
    payload = bytearray(new_data_size)
    struct.pack_into('>I', payload, 0, new_data_size - 4)  # size_be
    struct.pack_into('<I', payload, 4, file_magic)          # magic LE
    payload[PAYLOAD_PRELUDE:PAYLOAD_PRELUDE + len(stage_bytes)] = stage_bytes
    # last 8 bytes stay zero (trailing zeros)

    # Align payload to 4 bytes
    if len(payload) % 4:
        payload += b'\x00' * (4 - len(payload) % 4)

    new_chunk_size = len(payload)

    # Update chunk header size
    new_hdr = bytearray(raw[bin_hdr_off:bin_hdr_off + 12])
    struct.pack_into('>I', new_hdr, 0, new_chunk_size)

    buf = raw[:bin_hdr_off] + new_hdr + payload + raw[old_chunk_end:]

    with open(filepath, 'wb') as f:
        f.write(buf)
