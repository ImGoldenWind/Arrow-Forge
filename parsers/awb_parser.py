import struct

# AFS2 / AWB audio bank parser
# AWB files use CriWare's AFS2 container format for storing
# multiple audio streams (typically HCA-encoded).
# File layout:
#   Header (16 bytes):
#     [0:4]   char[4]  magic ("AFS2")
#     [4]     u8       version (1)
#     [5]     u8       type flags (bit2 → 4-byte offsets, bit3 → 8-byte offsets)
#     [6]     u8       id_size (bytes per entry ID, typically 2)
#     [7]     u8       reserved (0)
#     [8:12]  LE u32   entry_count
#     [12:16] LE u32   alignment (byte boundary for audio data)
#   ID table (entry_count * id_size bytes):
#     Sequential entry IDs (LE u16 or u32)
#   Offset table ((entry_count + 1) * offset_size bytes):
#     offset[0..N-1] = start boundary of each entry's data area
# offset[N]      = end of last entry (== file size)
#     Actual audio data starts at align_up(offset[i], alignment).
#     Audio data for entry i spans from align_up(offset[i], alignment) to offset[i+1].

AFS2_MAGIC = b"AFS2"
HEADER_SIZE = 16


def _align_up(value, alignment):
    """Round value up to the nearest multiple of alignment."""
    if alignment <= 0:
        return value
    remainder = value % alignment
    return value if remainder == 0 else value + (alignment - remainder)


def _detect_offset_size(type_flags):
    """Determine bytes per offset entry from type flags byte."""
    if type_flags & 8:
        return 8
    if type_flags & 4:
        return 4
    return 2


def parse_awb(filepath):
    """Parse an AFS2/AWB file and return structured data.

    Returns:
        (raw_data, entries, meta)

        raw_data: bytearray of entire file
        entries: list of dicts:
            {
                'id':     int,    # entry ID
                'offset': int,    # actual byte offset of audio data in file
                'size':   int,    # audio data size in bytes
                'format': str,    # detected format hint ('HCA', 'ADX', or 'unknown')
            }
        meta: dict with container metadata:
            {
                'version':      int,
                'type_flags':   int,
                'id_size':      int,
                'offset_size':  int,
                'alignment':    int,
                'entry_count':  int,
            }
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    if len(raw) < HEADER_SIZE:
        raise ValueError("File too small to be a valid AWB")

    magic = raw[0:4]
    if magic != AFS2_MAGIC:
        raise ValueError(f"Invalid AWB magic: expected 'AFS2', got {magic!r}")

    version = raw[4]
    type_flags = raw[5]
    id_size = raw[6] if raw[6] in (2, 4) else 2
    entry_count = struct.unpack_from('<I', raw, 8)[0]
    alignment = struct.unpack_from('<I', raw, 12)[0]
    offset_size = _detect_offset_size(type_flags)

    meta = {
        'version': version,
        'type_flags': type_flags,
        'id_size': id_size,
        'offset_size': offset_size,
        'alignment': alignment,
        'entry_count': entry_count,
    }

    # Parse ID table
    id_table_start = HEADER_SIZE
    ids = []
    id_fmt = '<H' if id_size == 2 else '<I'
    for i in range(entry_count):
        pos = id_table_start + i * id_size
        ids.append(struct.unpack_from(id_fmt, raw, pos)[0])

    # Parse offset table
    offset_table_start = id_table_start + entry_count * id_size
    off_fmt = '<H' if offset_size == 2 else ('<I' if offset_size == 4 else '<Q')
    offsets = []
    for i in range(entry_count + 1):
        pos = offset_table_start + i * offset_size
        offsets.append(struct.unpack_from(off_fmt, raw, pos)[0])

    # Build entries
    entries = []
    for i in range(entry_count):
        data_start = _align_up(offsets[i], alignment)
        data_end = offsets[i + 1]
        size = max(0, data_end - data_start)

        # Detect audio format from first bytes
        fmt = 'unknown'
        if data_start + 4 <= len(raw):
            head = raw[data_start:data_start + 4]
            # HCA: plain "HCA\0" or masked (high bit set on first 3 bytes)
            if head[:3] == b'HCA' or head[:3] == bytes([0xC8, 0xC3, 0xC1]):
                fmt = 'HCA'
            elif head[:2] == b'\x80\x00':
                fmt = 'ADX'

        entries.append({
            'id': ids[i],
            'offset': data_start,
            'size': size,
            'format': fmt,
        })

    return raw, entries, meta


def extract_entry(raw_data, entry):
    """Extract raw audio bytes for a single entry."""
    return bytes(raw_data[entry['offset']:entry['offset'] + entry['size']])


def replace_entry_data(raw_data, entries, meta, index, new_audio_bytes):
    """Replace audio data for entry at given index and rebuild the AWB file.

    Returns new (raw_data, entries, meta).
    """
    entries[index]['_new_data'] = new_audio_bytes
    return rebuild_awb(entries, meta)


def add_entry(entries, meta, new_id=None, audio_bytes=b''):
    """Add a new entry. If new_id is None, uses max(existing IDs) + 1."""
    if new_id is None:
        new_id = max((e['id'] for e in entries), default=-1) + 1
    entries.append({
        'id': new_id,
        'offset': 0,
        'size': len(audio_bytes),
        'format': _detect_format(audio_bytes),
        '_new_data': audio_bytes,
    })
    meta['entry_count'] = len(entries)
    return entries, meta


def delete_entry(entries, meta, index):
    """Delete entry at given index."""
    entries.pop(index)
    meta['entry_count'] = len(entries)
    return entries, meta


def _detect_format(data):
    """Detect audio format from raw bytes."""
    if len(data) < 4:
        return 'unknown'
    if data[:3] == b'HCA' or data[:3] == bytes([0xC8, 0xC3, 0xC1]):
        return 'HCA'
    if data[:2] == b'\x80\x00':
        return 'ADX'
    return 'unknown'


def rebuild_awb(entries, meta, original_raw=None):
    """Rebuild a complete AWB file from entries.

    Each entry must either have '_new_data' (replacement bytes)
    or we read from original_raw using offset/size.

    Returns (new_raw_data, new_entries, meta).
    """
    entry_count = len(entries)
    id_size = meta.get('id_size', 2)
    offset_size = meta.get('offset_size', 4)
    alignment = meta.get('alignment', 32)

    # Calculate header size
    id_table_size = entry_count * id_size
    offset_table_size = (entry_count + 1) * offset_size
    header_total = HEADER_SIZE + id_table_size + offset_table_size

    # Collect audio data blobs
    blobs = []
    for entry in entries:
        if '_new_data' in entry:
            blobs.append(entry['_new_data'])
        elif original_raw is not None:
            blobs.append(bytes(original_raw[entry['offset']:entry['offset'] + entry['size']]))
        else:
            blobs.append(b'')

    # Calculate offsets and total file size
    new_offsets = []
    current_pos = header_total
    new_offsets.append(current_pos)  # offset[0] = header end boundary

    for i, blob in enumerate(blobs):
        aligned_start = _align_up(current_pos, alignment)
        end = aligned_start + len(blob)
        if i < len(blobs) - 1:
            new_offsets.append(end)
        else:
            new_offsets.append(end)  # last: file end
        current_pos = end

    file_size = _align_up(current_pos, alignment) if current_pos > 0 else current_pos

    # Build file
    buf = bytearray(new_offsets[-1])

    # Header
    buf[0:4] = AFS2_MAGIC
    buf[4] = meta.get('version', 1)
    buf[5] = meta.get('type_flags', 4)
    buf[6] = id_size
    buf[7] = 0
    struct.pack_into('<I', buf, 8, entry_count)
    struct.pack_into('<I', buf, 12, alignment)

    # ID table
    id_fmt = '<H' if id_size == 2 else '<I'
    for i, entry in enumerate(entries):
        struct.pack_into(id_fmt, buf, HEADER_SIZE + i * id_size, entry['id'])

    # Offset table
    off_fmt = '<H' if offset_size == 2 else ('<I' if offset_size == 4 else '<Q')
    offset_table_start = HEADER_SIZE + id_table_size
    for i, off in enumerate(new_offsets):
        struct.pack_into(off_fmt, buf, offset_table_start + i * offset_size, off)

    # Audio data
    new_entries = []
    for i, blob in enumerate(blobs):
        data_start = _align_up(new_offsets[i], alignment)
        # Zero-fill padding area (already zeros in bytearray)
        buf[data_start:data_start + len(blob)] = blob
        new_entries.append({
            'id': entries[i]['id'],
            'offset': data_start,
            'size': len(blob),
            'format': _detect_format(blob),
        })

    meta['entry_count'] = entry_count
    return bytes(buf), new_entries, meta


def save_awb(filepath, raw_data):
    """Write raw AWB data to file."""
    with open(filepath, 'wb') as f:
        f.write(raw_data)


def get_entry_label(entry_id):
    """Return a label for an AWB entry based on its numeric ID."""
    return f"Track {entry_id}"
