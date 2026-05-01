"""parsers/damageprm_parser.py  –  Parser for damageprm.bin.xfbin.

Binary layout (XFBIN container):
  [NUCC header, 28 bytes]
  [Chunk table, chunk_table_size bytes]
  [Null chunk,    12 bytes header, size=0]
  [Binary chunk,  12 bytes header, size=6840]
    payload[0:4]  BE u32  =  chunk_data_size - 4  (= 6836)
    payload[4:8]  LE u32  =  entry_count           (= 31)
    payload[8..]  entry_count × ENTRY_SIZE bytes
  [Page chunk,    12 bytes header, size=8]

Each entry is ENTRY_SIZE = 204 bytes:
  [0x00:0x40]  name       char[64]   null-padded ASCII damage ID string
  [0x40:0x44]  launch_x   LE f32     horizontal launch force / scale
  [0x44:0x48]  launch_y   LE f32     vertical launch force / scale
  [0x48:0x4C]  flag       LE u32     misc flag (non-zero only for RUSHSPEEDCOMPARE_LOSE)
  [0x4C:0x50]  reaction   LE u32     hit-reaction animation type ID
  [0x50:0x54]  hitstun    LE u32     hitstun duration
  [0x54:0x58]  recovery   LE u32     recovery duration
  [0x58:0x7C]  (reserved zeros, 36 bytes)
  [0x7C:0x80]  sub_react  LE u32     sub-reaction type (BIND variants only)
  [0x80:0xCC]  (reserved zeros, 76 bytes)
"""

import struct

ENTRY_SIZE = 204
_NAME_LEN  = 64


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
        if chunk_size == 0:
            offset += 12
        else:
            offset += 12 + chunk_size
            if offset % 4:
                offset += 4 - (offset % 4)

    raise ValueError("Binary chunk not found in XFBIN")


def parse_damageprm_xfbin(filepath):
    """Parse damageprm.bin.xfbin.

    Returns (raw_bytearray, result_dict).
    result_dict keys:
        'entries'         – list of entry dicts (one per DAMAGE_ID)
        'entry_count'     – original entry count
        'bin_hdr_offset'  – file offset of the 12-byte binary-chunk header
        'bin_data_offset' – file offset where chunk payload begins
        'trailing_pad'    – bytes after the last entry until end of payload
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    bin_hdr_off, bin_data_off, bin_chunk_size = _find_binary_chunk(raw)
    payload = raw[bin_data_off:bin_data_off + bin_chunk_size]

    entry_count = struct.unpack('<I', payload[4:8])[0]
    entries_data = payload[8:]

    entries = []
    for i in range(entry_count):
        off = i * ENTRY_SIZE
        e = entries_data[off:off + ENTRY_SIZE]
        entries.append({
            'idx':       i,
            'name':      e[0x00:_NAME_LEN].rstrip(b'\x00').decode('ascii', errors='replace'),
            'launch_x':  struct.unpack('<f', e[0x40:0x44])[0],
            'launch_y':  struct.unpack('<f', e[0x44:0x48])[0],
            'flag':      struct.unpack('<I', e[0x48:0x4C])[0],
            'reaction':  struct.unpack('<I', e[0x4C:0x50])[0],
            'hitstun':   struct.unpack('<I', e[0x50:0x54])[0],
            'recovery':  struct.unpack('<I', e[0x54:0x58])[0],
            'sub_react': struct.unpack('<I', e[0x7C:0x80])[0],
        })

    used = entry_count * ENTRY_SIZE
    trailing_pad = bytes(entries_data[used:])

    return raw, {
        'entries':        entries,
        'entry_count':    entry_count,
        'bin_hdr_offset': bin_hdr_off,
        'bin_data_offset':bin_data_off,
        'trailing_pad':   trailing_pad,
    }


def save_damageprm_xfbin(filepath, raw, result):
    """Serialise entries back into the XFBIN and write to *filepath*.

    The number of entries is preserved (no add/remove) and the full
    204-byte per-entry layout (including reserved zero regions) is
    reconstructed exactly so the game can parse the file without issues.
    """
    entries      = result['entries']
    bin_hdr_off  = result['bin_hdr_offset']
    bin_data_off = result['bin_data_offset']
    trailing_pad = result.get('trailing_pad', b'')

    old_chunk_size = struct.unpack('>I', raw[bin_hdr_off:bin_hdr_off + 4])[0]
    old_chunk_end  = bin_data_off + old_chunk_size
    if old_chunk_end % 4:
        old_chunk_end += 4 - (old_chunk_end % 4)

    entry_count = len(entries)
    entries_bytes = bytearray(entry_count * ENTRY_SIZE)

    for i, e in enumerate(entries):
        off = i * ENTRY_SIZE
        # name (64 bytes, null-padded)
        nb = e['name'].encode('ascii', errors='replace')[:_NAME_LEN]
        entries_bytes[off:off + _NAME_LEN] = nb + b'\x00' * (_NAME_LEN - len(nb))
        # numeric fields
        struct.pack_into('<f', entries_bytes, off + 0x40, e['launch_x'])
        struct.pack_into('<f', entries_bytes, off + 0x44, e['launch_y'])
        struct.pack_into('<I', entries_bytes, off + 0x48, e['flag'])
        struct.pack_into('<I', entries_bytes, off + 0x4C, e['reaction'])
        struct.pack_into('<I', entries_bytes, off + 0x50, e['hitstun'])
        struct.pack_into('<I', entries_bytes, off + 0x54, e['recovery'])
        # bytes 0x58-0x7B are zeroes (already zero in bytearray)
        struct.pack_into('<I', entries_bytes, off + 0x7C, e['sub_react'])
        # bytes 0x80-0xCB are zeroes (already zero in bytearray)

    # Rebuild payload: size_be (4) + count (4) + entries + trailing padding
    new_chunk_size = 8 + len(entries_bytes) + len(trailing_pad)
    payload = bytearray(new_chunk_size)
    struct.pack_into('>I', payload, 0, new_chunk_size - 4)  # size_be
    struct.pack_into('<I', payload, 4, entry_count)          # entry_count LE
    payload[8:8 + len(entries_bytes)] = entries_bytes
    payload[8 + len(entries_bytes):]  = trailing_pad

    # Pad payload to 4-byte boundary (if needed)
    if len(payload) % 4:
        payload += b'\x00' * (4 - (len(payload) % 4))

    # Rebuild chunk header with updated size
    new_hdr = bytearray(raw[bin_hdr_off:bin_hdr_off + 12])
    struct.pack_into('>I', new_hdr, 0, new_chunk_size)

    buf = raw[:bin_hdr_off] + new_hdr + payload + raw[old_chunk_end:]

    with open(filepath, 'wb') as f:
        f.write(buf)
