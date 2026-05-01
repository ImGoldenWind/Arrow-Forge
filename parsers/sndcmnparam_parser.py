import struct

# Entry sizes per section type
SNDCMN_ENTRY_SIZE  = 32   # audio ID string, null-padded
PLDATA_ENTRY_SIZE  = 212  # char_id(32)+pl(32)+null1(32)+spl(32)+spl_int(32)+ev(32)+5f(20)
CRIDATA_ENTRY_SIZE = 178  # 4f(16)+5str×32(160)+u16(2)


# XFBIN helpers

def _extract_name_strings(raw):
    """Return list of chunk name strings from the XFBIN chunk table."""
    chunk_table_start = 28
    ct = raw[chunk_table_start:]
    # Chunk-table meta header layout (10 × BE uint32 = 40 bytes):
    #  [0] unk4, [1] type_str_size, [2] unk, [3] path_str_size, [4] path_cnt,
    #  [5] name_str_size, [6] name_cnt, [7] map_size, [8] unk, [9] unk
    type_sz = struct.unpack('>I', ct[4:8])[0]
    path_sz = struct.unpack('>I', ct[12:16])[0]
    name_sz = struct.unpack('>I', ct[20:24])[0]

    type_off = chunk_table_start + 40
    path_off = type_off + type_sz
    name_off = path_off + path_sz

    name_data = raw[name_off:name_off + name_sz]
    return [n.decode('ascii', errors='replace') for n in name_data.split(b'\x00') if n]


def _scan_chunks(raw):
    """Scan all XFBIN chunk headers. No 4-byte alignment between chunks."""
    chunk_table_size = struct.unpack('>I', raw[16:20])[0]
    offset = 28 + chunk_table_size
    chunks = []
    while offset + 12 <= len(raw):
        chunk_size = struct.unpack('>I', raw[offset:offset + 4])[0]
        map_idx    = struct.unpack('>I', raw[offset + 4:offset + 8])[0]
        chunks.append({
            'hdr_offset':  offset,
            'data_offset': offset + 12,
            'chunk_size':  chunk_size,
            'map_idx':     map_idx,
        })
        offset += 12 if chunk_size == 0 else 12 + chunk_size
        if offset >= len(raw):
            break
    return chunks


# Per-type parsers

def _parse_sndcmnparam(raw, data_off):
    count = struct.unpack('<H', raw[data_off + 4:data_off + 6])[0]
    entries = []
    for i in range(count):
        off = data_off + 6 + i * SNDCMN_ENTRY_SIZE
        s = raw[off:off + 32].rstrip(b'\x00').decode('ascii', errors='replace')
        entries.append({'idx': i, 'audio_id': s})
    return entries


def _parse_pldata(raw, data_off):
    count = struct.unpack('<H', raw[data_off + 4:data_off + 6])[0]
    entries = []
    for i in range(count):
        off = data_off + 6 + i * PLDATA_ENTRY_SIZE
        e = raw[off:off + PLDATA_ENTRY_SIZE]
        fields = [e[j * 32:(j + 1) * 32].rstrip(b'\x00').decode('ascii', errors='replace')
                  for j in range(6)]
        f = struct.unpack('<5f', e[192:212])
        entries.append({
            'idx': i,
            'char_id':          fields[0],
            'pl':               fields[1],
            'null1':            fields[2],
            'spl':              fields[3],
            'spl_interaction':  fields[4],
            'ev':               fields[5],
            'stand_index':      f[0],
            'unk2':             f[1],
            'unk3':             f[2],
            'entity':           f[3],
            'char_index':       f[4],
        })
    return entries


def _parse_cridata(raw, data_off):
    count = struct.unpack('<H', raw[data_off + 4:data_off + 6])[0]
    entries = []
    for i in range(count):
        off = data_off + 6 + i * CRIDATA_ENTRY_SIZE
        e = raw[off:off + CRIDATA_ENTRY_SIZE]
        f0, f1, f2, f3 = struct.unpack('<4f', e[0:16])
        strs = [e[16 + j * 32:16 + (j + 1) * 32].rstrip(b'\x00').decode('ascii', errors='replace')
                for j in range(5)]
        u16 = struct.unpack('<H', e[176:178])[0]
        entries.append({
            'idx':    i,
            'float0': f0, 'float1': f1, 'float2': f2, 'float3': f3,
            'str0':   strs[0], 'str1': strs[1], 'str2': strs[2],
            'str3':   strs[3], 'str4': strs[4],
            'flag':   u16,
        })
    return entries


# Public parse entry point

def parse_sndcmnparam_xfbin(filepath):
    """Parse sndcmnparam.xfbin.

    Returns (raw_bytearray, sections) where sections is a list of dicts:
        name        – "battle", "pldata", etc.
        type        – "sndcmnparam" | "pldata" | "cridata"
        entries     – list of entry dicts
        hdr_offset  – file offset of the 12-byte chunk header
        chunk_size  – original chunk payload size
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    names = _extract_name_strings(raw)
    # Keep only data names (strip 'Page0', 'index', empty strings)
    data_names = [n for n in names if n not in ('', 'Page0', 'index')]

    all_chunks  = _scan_chunks(raw)
    bin_chunks  = [c for c in all_chunks if c['map_idx'] == 1]

    sections = []
    for i, chunk in enumerate(bin_chunks):
        name     = data_names[i] if i < len(data_names) else f'section_{i}'
        data_off = chunk['data_offset']
        sz       = chunk['chunk_size']

        # Determine entry size to classify the section type
        if sz >= 6:
            count = struct.unpack('<H', raw[data_off + 4:data_off + 6])[0]
            entry_sz = ((sz - 6) // count) if count else 32
        else:
            count, entry_sz = 0, 32

        if entry_sz == PLDATA_ENTRY_SIZE:
            sec_type = 'pldata'
            entries  = _parse_pldata(raw, data_off)
        elif entry_sz == CRIDATA_ENTRY_SIZE:
            sec_type = 'cridata'
            entries  = _parse_cridata(raw, data_off)
        else:
            sec_type = 'sndcmnparam'
            entries  = _parse_sndcmnparam(raw, data_off)

        sections.append({
            'name':       name,
            'type':       sec_type,
            'entries':    entries,
            'hdr_offset': chunk['hdr_offset'],
            'chunk_size': sz,
        })

    return raw, sections


# Per-type payload builders

def _build_sndcmnparam_payload(entries):
    count = len(entries)
    data_sz = 2 + count * SNDCMN_ENTRY_SIZE
    payload = bytearray(4 + data_sz)
    struct.pack_into('>I', payload, 0, data_sz)          # BE payload_data_size
    struct.pack_into('<H', payload, 4, count)             # LE count
    for i, e in enumerate(entries):
        off = 6 + i * SNDCMN_ENTRY_SIZE
        b = e['audio_id'].encode('ascii', errors='replace')[:32]
        payload[off:off + 32] = b + b'\x00' * (32 - len(b))
    return payload


def _build_pldata_payload(entries):
    count = len(entries)
    data_sz = 2 + count * PLDATA_ENTRY_SIZE
    payload = bytearray(4 + data_sz)
    struct.pack_into('>I', payload, 0, data_sz)
    struct.pack_into('<H', payload, 4, count)
    str_fields = ['char_id', 'pl', 'null1', 'spl', 'spl_interaction', 'ev']
    for i, e in enumerate(entries):
        off = 6 + i * PLDATA_ENTRY_SIZE
        for j, field in enumerate(str_fields):
            b = e[field].encode('ascii', errors='replace')[:32]
            payload[off + j * 32:off + j * 32 + 32] = b + b'\x00' * (32 - len(b))
        struct.pack_into('<5f', payload, off + 192,
                         e['stand_index'], e['unk2'], e['unk3'],
                         e['entity'], e['char_index'])
    return payload


def _build_cridata_payload(entries):
    count = len(entries)
    data_sz = 2 + count * CRIDATA_ENTRY_SIZE
    payload = bytearray(4 + data_sz)
    struct.pack_into('>I', payload, 0, data_sz)
    struct.pack_into('<H', payload, 4, count)
    for i, e in enumerate(entries):
        off = 6 + i * CRIDATA_ENTRY_SIZE
        struct.pack_into('<4f', payload, off,
                         e['float0'], e['float1'], e['float2'], e['float3'])
        for j, field in enumerate(['str0', 'str1', 'str2', 'str3', 'str4']):
            b = e[field].encode('ascii', errors='replace')[:32]
            payload[off + 16 + j * 32:off + 16 + j * 32 + 32] = b + b'\x00' * (32 - len(b))
        struct.pack_into('<H', payload, off + 176, e['flag'])
    return payload


# Public save entry point

def save_sndcmnparam_xfbin(filepath, raw, sections):
    """Rebuild the XFBIN with updated sections and write to filepath."""
    chunk_table_size = struct.unpack('>I', raw[16:20])[0]
    header_end = 28 + chunk_table_size

    # Build a mapping hdr_offset → new_payload for binary chunks
    all_chunks = _scan_chunks(raw)
    bin_order  = [c for c in all_chunks if c['map_idx'] == 1]
    binary_map = {}
    for i, chunk in enumerate(bin_order):
        if i >= len(sections):
            break
        sec = sections[i]
        if sec['type'] == 'pldata':
            payload = _build_pldata_payload(sec['entries'])
        elif sec['type'] == 'cridata':
            payload = _build_cridata_payload(sec['entries'])
        else:
            payload = _build_sndcmnparam_payload(sec['entries'])
        binary_map[chunk['hdr_offset']] = payload

    # Rebuild the file: keep XFBIN header+table, then walk chunks
    buf = bytearray(raw[:header_end])
    for chunk in all_chunks:
        hdr_off   = chunk['hdr_offset']
        chunk_sz  = chunk['chunk_size']
        if chunk['map_idx'] == 1 and hdr_off in binary_map:
            new_payload = binary_map[hdr_off]
            new_sz = len(new_payload)
            new_hdr = bytearray(12)
            struct.pack_into('>I', new_hdr, 0, new_sz)
            new_hdr[4:12] = raw[hdr_off + 4:hdr_off + 12]  # preserve map_idx + ver
            buf += new_hdr + new_payload
        else:
            if chunk_sz == 0:
                buf += raw[hdr_off:hdr_off + 12]
            else:
                buf += raw[hdr_off:hdr_off + 12 + chunk_sz]

    with open(filepath, 'wb') as f:
        f.write(buf)
