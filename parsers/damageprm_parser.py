"""Lossless damageprm reader/writer. Native loader RVA 3C035C reads up to
128 counted groups of 0xCC-byte rows. See docs/hit-reactions-research.md.
"""
import math
import os
import struct
import tempfile

ENTRY_SIZE = 0xCC
FIELD_LAYOUT = {
    'launch_x': (0x40, 'f'), 'launch_y': (0x44, 'f'),
    'flag': (0x48, 'i'), 'reaction': (0x4C, 'I'),
    'hitstun': (0x50, 'i'), 'recovery': (0x54, 'i'),
    'extra_58': (0x58, 'I'), 'sub_react': (0x7C, 'i'),
}


def _find_binary_chunk(raw):
    if len(raw) < 28 or raw[:4] != b'NUCC':
        raise ValueError('Not an XFBIN file')
    offset = 28 + struct.unpack_from('>I', raw, 16)[0]
    while offset + 12 <= len(raw):
        size, map_idx = struct.unpack_from('>II', raw, offset)
        if offset + 12 + size > len(raw):
            raise ValueError('Truncated XFBIN chunk')
        if map_idx == 1 and size > 0:
            return offset, offset + 12, size
        offset = (offset + 12 + size + 3) & ~3
    raise ValueError('Binary chunk not found in XFBIN')


def parse_damageprm_xfbin(filepath):
    with open(filepath, 'rb') as stream:
        raw = bytearray(stream.read())
    header, data, size = _find_binary_chunk(raw)
    if size < 8:
        raise ValueError('Truncated damage parameter header')
    end = data + size
    cursor = data + 4
    entries = []
    groups = []
    for group in range(128):
        if cursor + 4 > end:
            raise ValueError('Truncated damage parameter group')
        count = struct.unpack_from('<i', raw, cursor)[0]
        cursor += 4
        if count <= 0:
            break
        if cursor + count * ENTRY_SIZE > end:
            raise ValueError('Damage parameter count exceeds chunk size')
        groups.append(count)
        for _ in range(count):
            row = raw[cursor:cursor + ENTRY_SIZE]
            entry = dict(idx=len(entries), group=group, _offset=cursor,
                         name=bytes(row[:64]).split(b'\0', 1)[0].decode('ascii', errors='replace'),
                         extra_name=bytes(row[0x5C:0x7C]).split(b'\0', 1)[0].decode('ascii', errors='replace'))
            for key, (offset, fmt) in FIELD_LAYOUT.items():
                entry[key] = struct.unpack_from('<' + fmt, row, offset)[0]
            entries.append(entry)
            cursor += ENTRY_SIZE
    return raw, dict(entries=entries, entry_count=len(entries), groups=groups,
                     bin_hdr_offset=header, bin_data_offset=data,
                     trailing_pad=bytes(raw[cursor:end]))


def _same_float(left, right):
    return (left == right and (left != 0 or math.copysign(1, left) == math.copysign(1, right))
            or math.isnan(left) and math.isnan(right))


def save_damageprm_xfbin(filepath, raw, result):
    """Patch edited fields only; retain unexposed bytes and write atomically."""
    entries = result['entries']
    if len(entries) != result['entry_count']:
        raise ValueError('Adding/removing damage parameter rows is not supported')
    buf = bytearray(raw)
    for entry in entries:
        base = entry['_offset']
        if not result['bin_data_offset'] + 8 <= base <= len(raw) - ENTRY_SIZE:
            raise ValueError('Invalid damage parameter row offset')
        for key, (offset, fmt) in FIELD_LAYOUT.items():
            value = entry[key]
            old = struct.unpack_from('<' + fmt, raw, base + offset)[0]
            if fmt == 'f':
                value = float(value)
                if _same_float(value, old):
                    continue
                if not math.isfinite(value):
                    raise ValueError(f'{key}: enter a finite float32')
            else:
                low, high = (-0x80000000, 0x7FFFFFFF) if fmt == 'i' else (0, 0xFFFFFFFF)
                if not isinstance(value, int) or not low <= value <= high:
                    raise ValueError(f'{key}: enter a valid 32-bit integer')
            struct.pack_into('<' + fmt, buf, base + offset, value)
        # Names are identifiers, not editable captions; retain their exact bytes.
    target = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-hit-reactions-', dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(buf)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
