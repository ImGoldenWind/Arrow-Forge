import struct

# PlayerColorParam.bin XFBIN parser
# Binary data layout (inside nuccChunkBinary):
#   [0:4]    BE u32  total_data_size (chunk payload length - 4)
#   Header (PlayerColorParam struct):
#     [4:8]   LE u32  version (1000)
#     [8:12]  LE u32  entry_count
#     [12:20] LE u64  first_pointer  (= 8 + len(notes); points to first entry)
#     [20:20+notes_size]  char[]  notes  (optional, usually empty)
#   Entries (entry_count × 24 bytes, starting at offset 20 + notes_size):
#     [0:8]   LE u64  pointer    (offset from this field to its char_id string)
#     [8:12]  LE u32  costume_slot
#     [12:16] LE u32  R (0-255)
#     [16:20] LE u32  G (0-255)
#     [20:24] LE u32  B (0-255)
#   Strings (entry_count × 8 bytes):
#     Each: 8-byte null-terminated ASCII char_id

ENTRY_SIZE = 24
STRING_SIZE = 8


def parse_costume_xfbin(filepath):
    """Parse PlayerColorParam.bin.xfbin and return (raw_data, characters, binary_offset, notes).

    characters is a list of dicts:
      {
        'char_id': str,
        'name': str,
        'costumes': [
          {
            'slot': int,
            'colors': [
              {'r': int, 'g': int, 'b': int},  # tint A
              {'r': int, 'g': int, 'b': int},  # tint B
              ...
            ]
          },
          ...
        ]
      }
    notes is the raw bytes of the optional notes area (usually b'').
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    # Find binary chunk (nuccChunkBinary) — walk XFBIN chunk table
    chunk_table_size = struct.unpack('>I', raw[16:20])[0]
    chunk_data_start = 28 + chunk_table_size
    if chunk_data_start % 4:
        chunk_data_start += 4 - (chunk_data_start % 4)

    binary_offset = None
    binary_size = 0
    offset = chunk_data_start
    while offset < len(raw) - 12:
        size = struct.unpack('>I', raw[offset:offset + 4])[0]
        if size >= 20:
            cd_start = offset + 12
            version = struct.unpack('<I', raw[cd_start + 4:cd_start + 8])[0]
            if version == 1000:
                binary_offset = cd_start
                binary_size = size
                break
        offset += 12 + size
        if offset % 4:
            offset += 4 - (offset % 4)

    if binary_offset is None:
        raise ValueError("Could not find PlayerColorParam binary chunk")

    cd = raw[binary_offset:binary_offset + binary_size]

    # Parse header
    entry_count = struct.unpack('<I', cd[8:12])[0]
    first_pointer = struct.unpack('<Q', cd[12:20])[0]  # u64
    notes_size = max(0, first_pointer - 8)
    notes = bytes(cd[20:20 + notes_size])
    entries_start = 20 + notes_size
    strings_start = entries_start + entry_count * ENTRY_SIZE

    # Parse all entries
    raw_entries = []
    for i in range(entry_count):
        eoff = entries_start + i * ENTRY_SIZE
        pointer, slot, r, g, b = struct.unpack('<QIIII', cd[eoff:eoff + ENTRY_SIZE])
        soff = strings_start + i * STRING_SIZE
        char_id = cd[soff:soff + STRING_SIZE].rstrip(b'\x00').decode('ascii', errors='replace')
        raw_entries.append({
            'char_id': char_id,
            'slot': slot,
            'r': r, 'g': g, 'b': b,
        })

    # Group entries by character, preserving order
    characters = []
    char_index = {}
    for entry in raw_entries:
        cid = entry['char_id']
        if cid not in char_index:
            char_data = {
                'char_id': cid,
                'name': cid,
                'costumes': [],
            }
            char_index[cid] = char_data
            characters.append(char_data)

        char_data = char_index[cid]
        slot = entry['slot']
        color = {'r': entry['r'], 'g': entry['g'], 'b': entry['b']}

        costume = None
        for c in char_data['costumes']:
            if c['slot'] == slot:
                costume = c
                break
        if costume is None:
            costume = {'slot': slot, 'colors': []}
            char_data['costumes'].append(costume)
        costume['colors'].append(color)

    return raw, characters, binary_offset, notes


def save_costume_xfbin(filepath, raw_data, characters, binary_offset, notes=b''):
    """Rebuild binary data from characters and write to file."""
    buf = bytearray(raw_data)

    # Flatten characters back to entry list (preserve order)
    entries = []
    for char in characters:
        for costume in char['costumes']:
            for color in costume['colors']:
                entries.append({
                    'char_id': char['char_id'],
                    'slot': costume['slot'],
                    'r': color['r'],
                    'g': color['g'],
                    'b': color['b'],
                })

    entry_count = len(entries)
    notes_size = len(notes)
    first_pointer = 8 + notes_size
    entries_start = 20 + notes_size
    strings_start = entries_start + entry_count * ENTRY_SIZE
    total_size = strings_start + entry_count * STRING_SIZE

    # Build new binary chunk
    cd = bytearray(total_size)

    # Header
    struct.pack_into('>I', cd, 0, total_size - 4)   # data_size (BE)
    struct.pack_into('<I', cd, 4, 1000)              # version
    struct.pack_into('<I', cd, 8, entry_count)
    struct.pack_into('<Q', cd, 12, first_pointer)    # u64

    # Notes (preserved as-is)
    if notes:
        cd[20:20 + notes_size] = notes

    # Entries + strings
    for i, entry in enumerate(entries):
        eoff = entries_start + i * ENTRY_SIZE
        soff = strings_start + i * STRING_SIZE

        pointer = soff - eoff   # offset from pointer field to its string
        struct.pack_into('<Q', cd, eoff, pointer)           # u64 pointer
        struct.pack_into('<I', cd, eoff + 8, entry['slot'])
        struct.pack_into('<I', cd, eoff + 12, entry['r'])
        struct.pack_into('<I', cd, eoff + 16, entry['g'])
        struct.pack_into('<I', cd, eoff + 20, entry['b'])

        # String
        cid_bytes = entry['char_id'].encode('ascii')[:STRING_SIZE - 1]
        cd[soff:soff + STRING_SIZE] = cid_bytes + b'\x00' * (STRING_SIZE - len(cid_bytes))

    # Update chunk header size and replace chunk data in buffer
    chunk_header_off = binary_offset - 12
    struct.pack_into('>I', buf, chunk_header_off, total_size)

    old_size = struct.unpack('>I', raw_data[chunk_header_off:chunk_header_off + 4])[0]
    buf[binary_offset:binary_offset + old_size] = cd

    with open(filepath, 'wb') as f:
        f.write(buf)
