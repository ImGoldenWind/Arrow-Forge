"""Lossless SupportCharaParam reader/writer (native versions 1000 and 1001).

Entries: a 64-bit self-relative name pointer followed by 34 signed ints.
Version 1001 inserts a second stock count at +0C, shifting subsequent fields.
Field keys retain their physical offset / 4. See docs/assist-research.md.
"""
import os
import struct
import tempfile
from collections import Counter

BINARY_HDR_LEN = 16
ENTRY_SIZE = 144
CHAR_SLOT_SIZE = 8  # alignment, NOT a string-length limit
_EDITABLE = tuple(range(2, 36))


def _find_binary_chunk(data):
    if len(data) < 28 or data[:4] != b'NUCC':
        raise ValueError('Not a valid NUCC XFBIN file')
    offset = (28 + struct.unpack_from('>I', data, 16)[0] + 3) & ~3
    candidates = []
    while offset + 12 <= len(data):
        size = struct.unpack_from('>I', data, offset)[0]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError('Truncated XFBIN chunk')
        if size >= 20:
            version = struct.unpack_from('<I', data, offset + 16)[0]
            if version in (1000, 1001):
                candidates.append((offset, size))
        offset = (end + 3) & ~3
    if len(candidates) != 1:
        raise ValueError('Expected one SupportCharaParam binary (version 1000 or 1001)')
    return candidates[0]


def _layout(data):
    chunk, size = _find_binary_chunk(data)
    start, end = chunk + 16, chunk + 12 + size
    inner_size = struct.unpack_from('>I', data, chunk + 12)[0]
    if inner_size != size - 4:
        raise ValueError('Invalid SupportCharaParam payload length')
    version, count, relative = struct.unpack_from('<IIQ', data, start)
    first = start + 8 + relative
    if count > 10000 or first < start + 16 or first + count * ENTRY_SIZE > end:
        raise ValueError('Invalid SupportCharaParam entry table')
    return chunk, start, end, version, count, first


def _parse_bytes(data):
    _chunk, _start, end, version, count, first = _layout(data)
    entries = []
    for i in range(count):
        base = first + i * ENTRY_SIZE
        target = base + struct.unpack_from('<Q', data, base)[0]
        if target < first + count * ENTRY_SIZE or target >= end:
            raise ValueError(f'Invalid character pointer in entry {i + 1}')
        stop = data.find(b'\0', target, end)
        if stop < 0:
            raise ValueError(f'Unterminated character ID in entry {i + 1}')
        char_id = bytes(data[target:stop]).decode('ascii')
        entry = dict(char_id=char_id, _version=version, _base=base,
                     _raw=bytes(data[base:base + ENTRY_SIZE]), _name_end=stop + 1)
        entry.update((f'f{fi}', struct.unpack_from('<i', data, base + fi * 4)[0])
                     for fi in _EDITABLE)
        entries.append(entry)
    return entries


def parse_assist_xfbin(filepath):
    with open(filepath, 'rb') as fh:
        data = bytearray(fh.read())
    return data, _parse_bytes(data)


def make_default_entry(char_id='', version=1000):
    entry = dict(char_id=char_id, _version=version)
    entry.update((f'f{fi}', 0) for fi in _EDITABLE)
    entry['f2'] = 1
    if version == 1001:
        entry['f3'] = 1
    return entry


def validate_entries(entries, originals=()):
    if len(entries) > 10000:
        raise ValueError('Too many Assist entries')
    previous = Counter(e['char_id'] for e in originals)
    counts = Counter(e['char_id'] for e in entries)
    for cid, n in counts.items():
        if not cid or '\0' in cid or len(cid.encode('ascii')) > 128:
            raise ValueError('Character ID must contain 1–128 ASCII characters without NUL')
        if n > max(1, previous[cid]):
            raise ValueError(f'Duplicate character ID: {cid}')
    for entry in entries:
        for fi in _EDITABLE:
            value = entry[f'f{fi}']
            if not isinstance(value, int) or not -0x80000000 <= value <= 0x7fffffff:
                raise ValueError(f'{entry["char_id"]}: +0x{fi * 4:02X} must be a signed 32-bit integer')


def save_assist_xfbin(filepath, original_data, entries):
    original_data = bytearray(original_data)
    originals = _parse_bytes(original_data)
    validate_entries(entries, originals)
    chunk, start, end, version, count, first = _layout(original_data)
    if any(e.get('_version', version) != version for e in entries):
        raise ValueError('Cannot mix Assist parameter versions')
    same_layout = len(entries) == count and all(
        e.get('_base') == old['_base'] and e['char_id'] == old['char_id']
        for e, old in zip(entries, originals))
    if same_layout:
        out = bytearray(original_data)
        for entry, old in zip(entries, originals):
            for fi in _EDITABLE:
                struct.pack_into('<i', out, old['_base'] + fi * 4, entry[f'f{fi}'])
    else:
        # There is no 20-byte footer inside the binary string table.
        inner = bytearray(original_data[start:first])
        struct.pack_into('<I', inner, 4, len(entries))
        names = bytearray()
        name_start = len(inner) + len(entries) * ENTRY_SIZE
        for entry in entries:
            base = len(inner)
            row = bytearray(entry.get('_raw', bytes(ENTRY_SIZE)))
            struct.pack_into('<Q', row, 0, name_start + len(names) - base)
            for fi in _EDITABLE:
                struct.pack_into('<i', row, fi * 4, entry[f'f{fi}'])
            inner.extend(row)
            names.extend(entry['char_id'].encode('ascii') + b'\0')
            names.extend(b'\0' * (-len(names) % 8))
        inner.extend(names)
        names_end = max((e['_name_end'] for e in originals), default=first)
        table_end = first + count * ENTRY_SIZE
        names_end = min(end, table_end + ((names_end - table_end + 7) & ~7))
        inner.extend(original_data[names_end:end])
        payload = struct.pack('>I', len(inner)) + inner
        header = bytearray(original_data[chunk:chunk + 12])
        struct.pack_into('>I', header, 0, len(payload))
        out = original_data[:chunk] + header + payload + b'\0' * (-len(payload) % 4)
        out.extend(original_data[(end + 3) & ~3:])
    _parse_bytes(out)  # Validate finished bytes before replacing the destination.
    path = os.path.abspath(filepath)
    fd, temp = tempfile.mkstemp(prefix='.assist-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(out)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
