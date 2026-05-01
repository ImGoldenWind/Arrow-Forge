import struct

DEFAULT_ENTRY_SIZE = 136
HEADER_SIZE = 8
FIXED_FIELDS_SIZE = 8


def _find_binary_chunk(raw):
    """Return (bin_chunk_hdr_offset, bin_data_offset, bin_chunk_size)."""
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


def _entry_layout(bin_chunk_size, entry_count):
    """Infer entry and string field sizes from the binary chunk."""
    entry_area_size = bin_chunk_size - HEADER_SIZE
    if entry_count:
        if entry_area_size % entry_count:
            raise ValueError(
                f"Effect entry table size {entry_area_size} is not divisible "
                f"by entry count {entry_count}"
            )
        entry_size = entry_area_size // entry_count
    else:
        entry_size = DEFAULT_ENTRY_SIZE

    string_len_total = entry_size - FIXED_FIELDS_SIZE
    if entry_size < FIXED_FIELDS_SIZE or string_len_total % 2:
        raise ValueError(f"Unsupported effect entry size: {entry_size}")

    return entry_size, string_len_total // 2


def parse_effectprm_xfbin(filepath):
    """Parse effectprm.bin.xfbin.

    Returns (raw_bytearray, result_dict).
    Retail ASBR entries are 136 bytes:
      slot_id u32, xfbins_count u32, path char[64], effect_name char[64].
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    bin_hdr_off, bin_data_off, bin_chunk_size = _find_binary_chunk(raw)
    chunk = raw[bin_data_off:bin_data_off + bin_chunk_size]

    entry_count = struct.unpack('<I', chunk[4:8])[0]
    entry_size, string_len = _entry_layout(bin_chunk_size, entry_count)

    entries = []
    for i in range(entry_count):
        off = HEADER_SIZE + i * entry_size
        e = chunk[off:off + entry_size]
        name_off = 8 + string_len
        entries.append({
            'idx':          i,
            'slot_id':      struct.unpack('<I', e[0:4])[0],
            'xfbins_count': struct.unpack('<I', e[4:8])[0],
            'xfbin_path':   e[8:name_off].rstrip(b'\x00').decode('ascii', errors='replace'),
            'effect_name':  e[name_off:name_off + string_len].rstrip(b'\x00').decode('ascii', errors='replace'),
        })

    return raw, {
        'entries':         entries,
        'entry_count':     entry_count,
        'entry_size':      entry_size,
        'string_len':      string_len,
        'bin_hdr_offset':  bin_hdr_off,
        'bin_data_offset': bin_data_off,
    }


def save_effectprm_xfbin(filepath, raw, result):
    """Serialise entries back into the XFBIN and write to filepath.

    Handles entry additions/removals by rebuilding the binary chunk and
    patching the chunk-size field in the XFBIN header.
    """
    entries = result['entries']
    bin_hdr_off  = result['bin_hdr_offset']
    bin_data_off = result['bin_data_offset']
    entry_size   = result.get('entry_size', DEFAULT_ENTRY_SIZE)
    string_len   = result.get('string_len', (entry_size - FIXED_FIELDS_SIZE) // 2)

    old_chunk_size = struct.unpack('>I', raw[bin_hdr_off:bin_hdr_off + 4])[0]
    old_chunk_end  = bin_data_off + old_chunk_size
    if old_chunk_end % 4:
        old_chunk_end += 4 - (old_chunk_end % 4)

    new_entry_count = len(entries)
    new_payload_size = new_entry_count * entry_size
    new_chunk_size   = HEADER_SIZE + new_payload_size

    payload = bytearray(new_chunk_size)
    struct.pack_into('>I', payload, 0, new_chunk_size - 4)
    struct.pack_into('<I', payload, 4, new_entry_count)

    for i, e in enumerate(entries):
        off = HEADER_SIZE + i * entry_size
        struct.pack_into('<I', payload, off,     int(e['slot_id']))
        struct.pack_into('<I', payload, off + 4, int(e['xfbins_count']))

        pb = e['xfbin_path'].encode('ascii', errors='replace')[:string_len]
        payload[off + 8:off + 8 + string_len] = pb + b'\x00' * (string_len - len(pb))

        nb = e['effect_name'].encode('ascii', errors='replace')[:string_len]
        name_off = off + 8 + string_len
        payload[name_off:name_off + string_len] = nb + b'\x00' * (string_len - len(nb))

    if len(payload) % 4:
        payload += b'\x00' * (4 - (len(payload) % 4))

    new_hdr = bytearray(raw[bin_hdr_off:bin_hdr_off + 12])
    struct.pack_into('>I', new_hdr, 0, new_chunk_size)

    buf = raw[:bin_hdr_off] + new_hdr + payload + raw[old_chunk_end:]

    with open(filepath, 'wb') as f:
        f.write(buf)
