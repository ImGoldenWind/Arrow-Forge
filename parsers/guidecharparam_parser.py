"""GuideCharParam reader/writer. Native layout: docs/guide-character-research.md.

Each 0x60-byte row has ten relative string pointers (event, UI asset, four
speaker/message pairs), three u32 parameters and one preserved u32 at +5C.
The former fifth message pair was a format error, not a reserved text slot.
"""
import os
import struct
import tempfile

ENTRY_SIZE = 96
HEADER_SIZE = 16
_INNER_SZ_FLD = 4
_STR_FIELDS = [(0, 'event'), (8, 'character')]
for _i in range(4):
    _STR_FIELDS.extend(((16 + _i * 16, f'msg{_i}_name'),
                        (24 + _i * 16, f'msg{_i}_string')))
_STR_KEYS = [key for _, key in _STR_FIELDS]
_RAW_FIELDS = [(0x50 + i * 4, f'raw_{0x50 + i * 4:02x}') for i in range(4)]

KNOWN_CHARACTERS = [
    'guide_chara_speedwagon', 'guide_chara_polnareff', 'guide_chara_messina',
    'guide_chara_melone', 'guide_chara_abbacchio', 'guide_chara_emporio',
    'guide_chara_wangchen', 'guide_chara_boingo', 'guide_chara_derbyd',
    'guide_chara_derbyt', 'guide_chara_giatcho', 'guide_chara_ringo',
]


def _read_cstr(data, off):
    if not 0 <= off < len(data):
        raise ValueError('GuideCharParam string pointer is outside its chunk.')
    end = data.find(b'\0', off)
    if end < 0:
        raise ValueError('Unterminated GuideCharParam string.')
    return bytes(data[off:end]).decode('utf-8', errors='surrogateescape')


def _find_binary_chunk(data):
    if len(data) < 28 or data[:4] != b'NUCC':
        raise ValueError('Not an XFBIN file.')
    offset = (28 + struct.unpack_from('>I', data, 16)[0] + 3) & ~3
    while offset + 12 <= len(data):
        size, type_idx = struct.unpack_from('>II', data, offset)
        if offset + 12 + size > len(data):
            raise ValueError('Truncated XFBIN chunk.')
        if size > 0 and (type_idx == 1 or size > 512):
            return offset, size
        offset = (offset + 12 + size + 3) & ~3
    raise ValueError('Could not locate nuccChunkBinary in XFBIN file.')


def _parse_payload(payload):
    if len(payload) < 20:
        raise ValueError('Truncated GuideCharParam header.')
    inner_size = struct.unpack_from('>I', payload)[0]
    if inner_size < HEADER_SIZE or inner_size + 4 > len(payload):
        raise ValueError('Truncated GuideCharParam payload.')
    payload = payload[:inner_size + 4]
    version, count, first_ptr = struct.unpack_from('<IIQ', payload, 4)
    start = 12 + first_ptr
    if start < 20 or start + count * ENTRY_SIZE > len(payload):
        raise ValueError('Invalid GuideCharParam entry table.')
    entries = []
    for i in range(count):
        base = start + i * ENTRY_SIZE
        entry = {'_offset': base}
        nulls = []
        for off, key in _STR_FIELDS:
            field = base + off
            ptr = struct.unpack_from('<q', payload, field)[0]
            entry[key] = _read_cstr(payload, field + ptr) if ptr else ''
            if not ptr:
                nulls.append(key)
        entry['_null_fields'] = tuple(sorted(nulls))
        for off, key in _RAW_FIELDS:
            entry[key] = struct.unpack_from('<I', payload, base + off)[0]
        entries.append(entry)
    return version, entries, bytes(payload[20:start])


def parse_guidecharparam_xfbin(filepath):
    with open(filepath, 'rb') as stream:
        data = bytearray(stream.read())
    header, size = _find_binary_chunk(data)
    version, entries, _notes = _parse_payload(data[header + 12:header + 12 + size])
    return data, version, entries


def make_default_entry(index=0):
    entry = dict.fromkeys(_STR_KEYS, '')
    entry.update(event=f'GUIDE_NEW_EVENT_{index:03d}', character='guide_chara_speedwagon')
    entry.update({key: 0 for _, key in _RAW_FIELDS})
    return entry


def _encoded(value):
    if not isinstance(value, str) or '\0' in value:
        raise ValueError('Guide identifiers must be strings without NUL bytes.')
    return value.encode('utf-8', errors='surrogateescape') + b'\0'


def _build_guidecharparam_binary(version, entries, notes=b''):
    """Build the inner binary, retaining opaque notes and all four tail words."""
    buf = bytearray(struct.pack('<IIQ', version, len(entries), 8 + len(notes)))
    buf.extend(notes)
    start = len(buf)
    buf.extend(bytes(len(entries) * ENTRY_SIZE))
    pool = {}
    for i, entry in enumerate(entries):
        base = start + i * ENTRY_SIZE
        for off, key in _STR_FIELDS:
            value = entry.get(key, '')
            encoded = _encoded(value)
            if not value and key in entry.get('_null_fields', _STR_KEYS):
                continue  # Native variant selection stops at a null message pointer.
            if value not in pool:
                pool[value] = len(buf)
                buf.extend(encoded)
                buf.extend(bytes((-len(buf)) % 8))
            struct.pack_into('<q', buf, base + off, pool[value] - base - off)
        for off, key in _RAW_FIELDS:
            struct.pack_into('<I', buf, base + off, entry.get(key, 0))
    buf.extend(bytes((-len(buf)) % 4))
    return bytes(buf)


def save_guidecharparam_xfbin(filepath, original_data, version, entries):
    """Keep untouched bytes/pointers; append edited strings; atomically replace."""
    header, size = _find_binary_chunk(original_data)
    payload_off = header + 12
    old = original_data[payload_off:payload_off + size]
    _version, old_entries, notes = _parse_payload(old)
    for entry in entries:
        for key in _STR_KEYS:
            _encoded(entry.get(key, ''))
        for _, key in _RAW_FIELDS:
            struct.pack('<I', entry.get(key, 0))
    if (len(entries) == len(old_entries)
            and all(e.get('_offset') == o['_offset'] for e, o in zip(entries, old_entries))):
        payload = bytearray(old)
        struct.pack_into('<I', payload, 4, version)
        for entry, previous in zip(entries, old_entries):
            base = previous['_offset']
            for off, key in _STR_FIELDS:
                value = entry.get(key, '')
                if value != previous[key]:
                    struct.pack_into('<q', payload, base + off, len(payload) - base - off if value else 0)
                    if value:
                        payload.extend(_encoded(value))
            for off, key in _RAW_FIELDS:
                struct.pack_into('<I', payload, base + off, entry.get(key, 0))
        if payload != old:
            struct.pack_into('>I', payload, 0, len(payload) - 4)
    else:
        inner = _build_guidecharparam_binary(version, entries, notes)
        payload = bytearray(struct.pack('>I', len(inner)) + inner)
    if len(payload) == size:
        output = bytearray(original_data)
        output[payload_off:payload_off + size] = payload
    else:
        old_end = min((payload_off + size + 3) & ~3, len(original_data))
        suffix = original_data[old_end:]
        chunk_header = bytearray(original_data[header:payload_off])
        struct.pack_into('>I', chunk_header, 0, len(payload))
        output = original_data[:header] + chunk_header + payload
        if suffix:
            output += bytes((-len(output)) % 4)
        output += suffix
    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-guide-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
