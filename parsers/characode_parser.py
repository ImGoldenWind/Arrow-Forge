import struct

# characode.bin.xfbin parser
# File structure (XFBIN container):
#   [XFBIN Header 28 bytes] [Chunk Map] [Chunk Data Area]
# Chunk Data Area contains:
#   1. nuccChunkNull (12-byte header, 0 data)
#   2. nuccChunkBinary (12-byte header + binary payload)
#   3. nuccChunkPage (12-byte header + 8 bytes data)
# Binary payload structure:
#   [payload_size: u32 BE] [entry_count: u32 LE] [entries...]
# Each entry (12 bytes):
#   [slot_index: u32 LE] [char_code: 8 bytes null-padded ASCII]
# Slot indices are NOT sequential — gaps exist (e.g. 43, 67-68, 79-80).
# These likely correspond to unused/reserved slots in the game's roster.
# The game .exe probably has a hardcoded max slot count and CSS layout
# that references these indices.

ENTRY_SIZE = 12


def parse_characode_xfbin(filepath):
    """Parse a characode.bin.xfbin file.

    Returns (raw_data, entries, meta):
      - raw_data: bytearray of the entire file
      - entries: list of dicts with slot_index, char_code, name
      - meta: dict with offsets needed for saving
    """
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    if data[:4] != b'NUCC':
        raise ValueError("Not a valid XFBIN file (missing NUCC magic)")

    chunk_table_size = struct.unpack('>I', data[16:20])[0]
    chunk_data_start = 28 + chunk_table_size
    if chunk_data_start % 4:
        chunk_data_start += 4 - (chunk_data_start % 4)

    # Scan chunks in the data area to find all of them
    chunks = []
    binary_chunk_idx = None
    offset = chunk_data_start

    while offset < len(data) - 11:
        size = struct.unpack('>I', data[offset:offset + 4])[0]
        header = bytes(data[offset:offset + 12])
        chunk_data = bytes(data[offset + 12:offset + 12 + size])
        chunks.append({'header': header, 'data': chunk_data, 'offset': offset})

        # The binary chunk is the one with substantial data (> 16 bytes)
        if size > 16 and binary_chunk_idx is None:
            binary_chunk_idx = len(chunks) - 1

        offset += 12 + size
        if offset % 4:
            offset += 4 - (offset % 4)

    if binary_chunk_idx is None:
        raise ValueError("Could not find binary chunk in XFBIN")

    # Parse binary payload
    bd = bytearray(chunks[binary_chunk_idx]['data'])

    # First 4 bytes: payload size (BE), next 4: entry count (LE)
    payload_size = struct.unpack('>I', bd[0:4])[0]
    entry_count = struct.unpack('<I', bd[4:8])[0]

    entries = []
    for i in range(entry_count):
        eoff = 8 + i * ENTRY_SIZE
        if eoff + ENTRY_SIZE > len(bd):
            break
        slot_index = struct.unpack('<I', bd[eoff:eoff + 4])[0]
        char_code = bd[eoff + 4:eoff + 12].rstrip(b'\x00').decode('ascii', errors='replace')
        entries.append({
            'slot_index': slot_index,
            'char_code': char_code,
            'name': char_code,
        })

    meta = {
        'chunk_data_start': chunk_data_start,
        'chunks': chunks,
        'binary_chunk_idx': binary_chunk_idx,
        'header_bytes': bytes(data[:chunk_data_start]),
    }

    return data, entries, meta


def build_binary_payload(entries):
    """Build the binary chunk data from entries."""
    entry_count = len(entries)
    payload_size = 4 + entry_count * ENTRY_SIZE  # count field + entries

    buf = bytearray()
    buf += struct.pack('>I', payload_size)       # payload size (BE)
    buf += struct.pack('<I', entry_count)         # entry count (LE)

    for entry in entries:
        buf += struct.pack('<I', entry['slot_index'])
        code = entry['char_code'].encode('ascii')[:7]
        buf += code + b'\x00' * (8 - len(code))

    return buf


def save_characode_xfbin(filepath, data, entries, meta):
    """Save entries back to an XFBIN file.

    Rebuilds the chunk data area so size changes are handled correctly.
    """
    result = bytearray(meta['header_bytes'])

    for i, chunk in enumerate(meta['chunks']):
        if i == meta['binary_chunk_idx']:
            # Rebuild binary chunk with updated entries
            new_data = build_binary_payload(entries)
            # Rewrite chunk header with new size
            new_header = bytearray(chunk['header'])
            struct.pack_into('>I', new_header, 0, len(new_data))
            result += new_header
            result += new_data
        else:
            result += chunk['header']
            result += chunk['data']

        # Align to 4 bytes
        while len(result) % 4:
            result.append(0)

    with open(filepath, 'wb') as f:
        f.write(result)


def find_slot_gaps(entries):
    """Analyze slot indices to find gaps and the max used slot.

    Returns (gaps, max_slot, used_slots).
    """
    if not entries:
        return [], 0, set()
    used = {e['slot_index'] for e in entries}
    max_slot = max(used)
    gaps = sorted(set(range(1, max_slot + 1)) - used)
    return gaps, max_slot, used


def suggest_next_slot(entries):
    """Suggest the next available slot index for a new character."""
    if not entries:
        return 1
    used = {e['slot_index'] for e in entries}
    max_slot = max(used)
    # First try to fill gaps
    for s in range(1, max_slot + 1):
        if s not in used:
            return s
    return max_slot + 1
