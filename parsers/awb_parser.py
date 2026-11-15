import struct
import os
import tempfile

from parsers.cpk_parser import crypt_jojo_asbr

# AFS2 / AWB audio bank parser
# AWB files use CriWare's AFS2 container format for storing
# multiple audio streams (typically HCA-encoded).
# File layout:
#   Header (16 bytes):
#     [0:4]   char[4]  magic ("AFS2")
#     [4]     u8       version (1)
#     [5]     u8       offset_size (2, 4 or 8 bytes)
#     [6:8]   LE u16   id_size (bytes per entry ID, typically 2)
#     [8:12]  LE u32   entry_count
#     [12:14] LE u16   alignment (byte boundary for audio data)
#     [14:16] LE u16   stream encryption subkey
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
    """AFS2 stores a byte width, not bit flags."""
    if type_flags not in (2, 4, 8):
        raise ValueError('Unsupported AWB offset width')
    return type_flags


def _decrypt_asbr_slice(raw, start, size, total_size=None):
    """Decrypt one absolute slice from an ASBR-encrypted AWB."""
    if size <= 0:
        return b''
    return crypt_jojo_asbr(
        raw[start:start + size],
        total_size=len(raw) if total_size is None else total_size,
        start_offset=start,
    )


def _detect_awb_encryption(raw):
    """Return (header bytes, encryption marker)."""
    if raw[:4] == AFS2_MAGIC:
        return raw[:HEADER_SIZE], None

    probe = crypt_jojo_asbr(raw[:HEADER_SIZE], total_size=len(raw))
    if probe[:4] != AFS2_MAGIC:
        return raw[:HEADER_SIZE], None

    return probe, 'asbr_cpk'


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
                'encryption':   str or None,
            }
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    if len(raw) < HEADER_SIZE:
        raise ValueError("File too small to be a valid AWB")

    header, encryption = _detect_awb_encryption(raw)

    magic = header[0:4]
    if magic != AFS2_MAGIC:
        raise ValueError(f"Invalid AWB magic: expected 'AFS2', got {magic!r}")

    version = header[4]
    type_flags = header[5]
    id_size = struct.unpack_from('<H', header, 6)[0]
    if id_size not in (2, 4):
        raise ValueError('Unsupported AWB ID width')
    entry_count = struct.unpack_from('<I', header, 8)[0]
    alignment, subkey = struct.unpack_from('<HH', header, 12)
    if not alignment:
        raise ValueError('AWB alignment must be positive')
    offset_size = _detect_offset_size(type_flags)
    table_size = HEADER_SIZE + entry_count * id_size + (entry_count + 1) * offset_size
    if len(raw) < table_size:
        raise ValueError("AWB header tables exceed file size")

    header_raw = raw
    if encryption == 'asbr_cpk':
        header_raw = bytearray(crypt_jojo_asbr(raw[:table_size], total_size=len(raw)))

    meta = {
        'version': version,
        'type_flags': type_flags,
        'id_size': id_size,
        'offset_size': offset_size,
        'alignment': alignment,
        'subkey': subkey,
        'entry_count': entry_count,
        'encryption': encryption,
        'file_size': len(raw),
    }

    # Parse ID table
    id_table_start = HEADER_SIZE
    ids = []
    id_fmt = '<H' if id_size == 2 else '<I'
    for i in range(entry_count):
        pos = id_table_start + i * id_size
        ids.append(struct.unpack_from(id_fmt, header_raw, pos)[0])

    # Parse offset table
    offset_table_start = id_table_start + entry_count * id_size
    off_fmt = '<H' if offset_size == 2 else ('<I' if offset_size == 4 else '<Q')
    offsets = []
    for i in range(entry_count + 1):
        pos = offset_table_start + i * offset_size
        offsets.append(struct.unpack_from(off_fmt, header_raw, pos)[0])

    # Build entries
    if offsets[0] < table_size or offsets[-1] > len(raw):
        raise ValueError('AWB offsets exceed data area')
    entries = []
    for i in range(entry_count):
        data_start = _align_up(offsets[i], alignment)
        data_end = offsets[i + 1]
        if offsets[i] > data_end or (data_start > data_end and offsets[i] != data_end):
            raise ValueError('Invalid AWB entry boundaries')
        size = max(0, data_end - data_start)

        # Detect audio format from first bytes
        fmt = 'unknown'
        if size > 0 and data_start + 4 <= len(raw):
            if encryption == 'asbr_cpk':
                # Exact format is resolved lazily when the stream is inspected.
                # Do not label every encrypted payload HCA without reading it.
                head = None
            else:
                head = raw[data_start:data_start + 4]
            if head is not None:
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
            'encryption': encryption,
            'container_size': len(raw),
        })

    return raw, entries, meta


def extract_entry(raw_data, entry):
    """Extract raw audio bytes for a single entry."""
    offset = entry['offset']
    size = entry['size']
    if entry.get('encryption') == 'asbr_cpk':
        return _decrypt_asbr_slice(raw_data, offset, size, entry.get('container_size'))
    return bytes(raw_data[offset:offset + size])


def replace_entry_data(raw_data, entries, meta, index, new_audio_bytes):
    """Replace audio data for entry at given index and rebuild the AWB file.

    Returns new (raw_data, entries, meta).
    """
    entries[index]['_new_data'] = new_audio_bytes
    return rebuild_awb(entries, meta, raw_data)


def add_entry(entries, meta, new_id=None, audio_bytes=b''):
    """Add a new entry. If new_id is None, uses max(existing IDs) + 1."""
    if new_id is None:
        new_id = max((e['id'] for e in entries), default=-1) + 1
    if not 0 <= new_id < 1 << (8 * meta.get('id_size', 2)):
        raise ValueError('AWB ID exceeds the stored ID width')
    if any(e['id'] == new_id for e in entries):
        raise ValueError('Duplicate AWB ID')
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
    meta = dict(meta)
    entry_count = len(entries)
    id_size = meta.get('id_size', 2)
    offset_size = meta.get('offset_size', 4)
    alignment = meta.get('alignment', 32)
    if id_size not in (2, 4) or offset_size not in (2, 4, 8) or not 0 < alignment <= 65535:
        raise ValueError('Unsupported AWB header widths or alignment')

    # Calculate header size
    id_table_size = entry_count * id_size
    offset_table_size = (entry_count + 1) * offset_size
    header_total = HEADER_SIZE + id_table_size + offset_table_size

    # One linear decryption for an encrypted source. Decrypting each absolute
    # slice separately would replay the XOR state from zero for every stream.
    source_raw = original_raw
    source_decrypted = False
    if original_raw is not None and any(e.get('encryption') == 'asbr_cpk' and
            '_new_data' not in e and '_prepared_data' not in e for e in entries):
        source_raw = crypt_jojo_asbr(original_raw)
        source_decrypted = True
    # Collect audio data blobs
    blobs = []
    for entry in entries:
        if '_new_data' in entry:
            blobs.append(entry['_new_data'])
        elif '_prepared_data' in entry:
            blobs.append(entry['_prepared_data'])
        elif original_raw is not None:
            if source_decrypted and entry.get('encryption') == 'asbr_cpk':
                blobs.append(bytes(source_raw[entry['offset']:entry['offset'] + entry['size']]))
            else:
                blobs.append(extract_entry(original_raw, entry))
        else:
            raise ValueError('Original audio bytes are required to rebuild this AWB')

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

    if new_offsets[-1] >= 1 << (offset_size * 8):
        raise ValueError('Rebuilt AWB exceeds the stored offset width')

    # Build file
    buf = bytearray(new_offsets[-1])

    # Header
    buf[0:4] = AFS2_MAGIC
    buf[4] = meta.get('version', 1)
    buf[5] = offset_size
    buf[6] = id_size
    buf[7] = 0
    struct.pack_into('<I', buf, 8, entry_count)
    struct.pack_into('<HH', buf, 12, alignment, meta.get('subkey', 0))

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
            'encryption': None,
            'container_size': len(buf),
        })

    meta['entry_count'] = entry_count
    meta['file_size'] = len(buf)
    return bytes(buf), new_entries, meta


def save_awb(filepath, raw_data, meta=None):
    """Write raw AWB data to file."""
    if meta and meta.get('encryption') == 'asbr_cpk':
        raw_data = crypt_jojo_asbr(raw_data)
    path = os.path.abspath(filepath)
    descriptor, temporary = tempfile.mkstemp(prefix='.awb-', dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, 'wb') as f:
            f.write(raw_data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return bytes(raw_data)


def get_entry_label(entry_id):
    """Return a label for an AWB entry based on its numeric ID."""
    return f"Track {entry_id}"
