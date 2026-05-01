"""parsers/damageeff_parser.py  –  Parser for damageeff.bin.xfbin.

Binary layout (XFBIN container):
  [NUCC header, 28 bytes]
  [Chunk table, chunk_table_size bytes]
  [Null chunk,    12 bytes header, size=0]
  [Binary chunk,  12 bytes header, size=1400]
    payload[0:4]  BE u32  =  chunk_data_size - 4  (= 1396)
    payload[4:8]  LE u32  =  entry_count           (= 58)
    payload[8..]  entry_count × ENTRY_SIZE bytes
  [Page chunk,    12 bytes header, size=8]

Each entry is ENTRY_SIZE = 24 bytes (6 × LE u32):
  [0x00:0x04]  entry_id    LE u32  – sequential entry index (0-57, read-only)
  [0x04:0x08]  eff_a       LE u32  – On-hit Effect A  (spark/flash); 0xFFFFFFFF = none
  [0x08:0x0C]  eff_b       LE u32  – On-hit Effect B  (main hit particle)
  [0x0C:0x10]  eff_c       LE u32  – On-hit Effect C  (secondary / screen effect); 0xFFFFFFFF = none
  [0x10:0x14]  eff_d       LE u32  – On-hit Effect D  (hit impact type)
  [0x14:0x18]  eff_e       LE u32  – On-hit Effect E  (flash overlay); 0xFFFFFFFF = none
"""

import struct

ENTRY_SIZE = 24
_NONE_VAL  = 0xFFFFFFFF   # sentinel "no effect"


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


def parse_damageeff_xfbin(filepath):
    """Parse damageeff.bin.xfbin.

    Returns (raw_bytearray, result_dict).
    result_dict keys:
        'entries'          – list of entry dicts (one per damage-effect slot)
        'entry_count'      – original entry count
        'bin_hdr_offset'   – file offset of the 12-byte binary-chunk header
        'bin_data_offset'  – file offset where chunk payload begins
        'trailing_pad'     – bytes after the last entry until end of payload
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    bin_hdr_off, bin_data_off, bin_chunk_size = _find_binary_chunk(raw)
    payload = raw[bin_data_off:bin_data_off + bin_chunk_size]

    entry_count  = struct.unpack('<I', payload[4:8])[0]
    entries_data = payload[8:]

    entries = []
    for i in range(entry_count):
        off = i * ENTRY_SIZE
        e   = entries_data[off:off + ENTRY_SIZE]
        entries.append({
            'idx':      i,
            'entry_id': struct.unpack('<I', e[0x00:0x04])[0],
            'eff_a':    struct.unpack('<I', e[0x04:0x08])[0],
            'eff_b':    struct.unpack('<I', e[0x08:0x0C])[0],
            'eff_c':    struct.unpack('<I', e[0x0C:0x10])[0],
            'eff_d':    struct.unpack('<I', e[0x10:0x14])[0],
            'eff_e':    struct.unpack('<I', e[0x14:0x18])[0],
        })

    used         = entry_count * ENTRY_SIZE
    trailing_pad = bytes(entries_data[used:])

    return raw, {
        'entries':         entries,
        'entry_count':     entry_count,
        'bin_hdr_offset':  bin_hdr_off,
        'bin_data_offset': bin_data_off,
        'trailing_pad':    trailing_pad,
    }


def save_damageeff_xfbin(filepath, raw, result):
    """Serialise entries back into the XFBIN and write to *filepath*.

    Entry count is preserved; the 24-byte per-entry layout is reconstructed
    exactly so the game can parse the file without issues.
    """
    entries      = result['entries']
    bin_hdr_off  = result['bin_hdr_offset']
    bin_data_off = result['bin_data_offset']
    trailing_pad = result.get('trailing_pad', b'')

    old_chunk_size = struct.unpack('>I', raw[bin_hdr_off:bin_hdr_off + 4])[0]
    old_chunk_end  = bin_data_off + old_chunk_size
    if old_chunk_end % 4:
        old_chunk_end += 4 - (old_chunk_end % 4)

    entry_count   = len(entries)
    entries_bytes = bytearray(entry_count * ENTRY_SIZE)

    for i, e in enumerate(entries):
        off = i * ENTRY_SIZE
        struct.pack_into('<I', entries_bytes, off + 0x00, e['entry_id'])
        struct.pack_into('<I', entries_bytes, off + 0x04, e['eff_a'])
        struct.pack_into('<I', entries_bytes, off + 0x08, e['eff_b'])
        struct.pack_into('<I', entries_bytes, off + 0x0C, e['eff_c'])
        struct.pack_into('<I', entries_bytes, off + 0x10, e['eff_d'])
        struct.pack_into('<I', entries_bytes, off + 0x14, e['eff_e'])

    # Rebuild payload: size_be (4) + count_le (4) + entries + trailing padding
    new_chunk_size = 8 + len(entries_bytes) + len(trailing_pad)
    payload = bytearray(new_chunk_size)
    struct.pack_into('>I', payload, 0, new_chunk_size - 4)   # BE size field
    struct.pack_into('<I', payload, 4, entry_count)           # LE entry count
    payload[8:8 + len(entries_bytes)] = entries_bytes
    payload[8 + len(entries_bytes):]  = trailing_pad

    if len(payload) % 4:
        payload += b'\x00' * (4 - (len(payload) % 4))

    new_hdr = bytearray(raw[bin_hdr_off:bin_hdr_off + 12])
    struct.pack_into('>I', new_hdr, 0, new_chunk_size)

    buf = raw[:bin_hdr_off] + new_hdr + payload + raw[old_chunk_end:]

    with open(filepath, 'wb') as f:
        f.write(buf)
