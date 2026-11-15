"""DictionaryParam, native 0xA8 rows; see docs/dictionary-research.md.

The public (raw, version, entries) API is retained. Relative pointers are signed
64-bit. Ordinary edits patch rows and append strings. Notes, null/empty
references, opaque bytes and neighboring contiguous NUCC chunks survive saves.
"""
import os
import struct
import tempfile

from parsers.skill_parser import _find_chunks

ENTRY_SIZE = 168
HEADER_SIZE = 16
STRING_FIELDS = ((0, 'char_id'), (8, 'panel'), (16, 'title'), (24, 'header'),
                 (112, 'dmy'), (144, 'availability_message1'), (152, 'availability_message2'))
NUMERIC_FIELDS = tuple(zip(range(32, 112, 4), (
    'flag1', 'flag2', 'flag3', 'flag4', 'flag5', 'flag6', 'flag7', 'flag8',
    'pad1', 'pad2', 'pad3', 'pad4', 'flag13', 'flag14', 'flag15', 'pad5',
    'pad6', 'pad7', 'flag19', 'pad8'))) + (
    (120, 'dlc_id'), (124, 'patch'), (128, 'no_panel'), (132, 'const1'),
    (136, 'padding'), (140, 'res1'), (160, 'index'), (164, 'index_padding'))


def _encoded(text):
    if not isinstance(text, str) or '\0' in text:
        raise ValueError('Dictionary references must be strings without NUL bytes.')
    return text.encode('utf-8', errors='surrogateescape') + b'\0'


def _parse_payload(payload):
    if len(payload) < 20:
        raise ValueError('Truncated DictionaryParam header.')
    inner_size = struct.unpack_from('>I', payload)[0]
    if not HEADER_SIZE <= inner_size <= len(payload) - 4:
        raise ValueError('Invalid DictionaryParam inner size.')
    body = payload[:4 + inner_size]
    version, count, first = struct.unpack_from('<IIq', body, 4)
    start = 12 + first
    end_table = start + count * ENTRY_SIZE
    if start < 20 or end_table > len(body):
        raise ValueError('Invalid DictionaryParam entry table.')
    entries = []
    for i in range(count):
        base = start + i * ENTRY_SIZE
        entry = {'_offset': base, '_record': bytes(body[base:base + ENTRY_SIZE])}
        nulls = []
        for off, key in STRING_FIELDS:
            pointer = struct.unpack_from('<q', body, base + off)[0]
            if not pointer:
                entry[key] = ''
                nulls.append(key)
                continue
            target = base + off + pointer
            if not 20 <= target < len(body):
                raise ValueError(f'DictionaryParam {key} pointer is outside its payload.')
            end = body.find(b'\0', target)
            if end < 0:
                raise ValueError(f'Unterminated DictionaryParam {key}.')
            entry[key] = bytes(body[target:end]).decode('utf-8', errors='surrogateescape')
        entry['_null_fields'] = tuple(nulls)
        for off, key in NUMERIC_FIELDS:
            entry[key] = struct.unpack_from('<I', body, base + off)[0]
        entries.append(entry)
    return version, entries, bytes(body[20:start]), bytes(body[end_table:]), bytes(payload[4 + inner_size:])


def _find_binary_chunk(data):
    # Reuse the NUCC index: map indices are u32, not type codes. Envelopes
    # are contiguous, including chunks ending at an unaligned address.
    chunks = _find_chunks(data)
    named = [item for name, item in chunks.items() if name.lower() == 'dictionaryparam']
    if len(named) == 1:
        return named[0][:2]
    candidates = []
    for header, size, payload in chunks.values():
        try:
            _parse_payload(data[payload:payload + size])
        except (ValueError, struct.error):
            continue
        candidates.append((header, size))
    if len(candidates) != 1:
        raise ValueError('Could not identify a unique DictionaryParam binary chunk.')
    return candidates[0]


def parse_dictionaryparam_xfbin(filepath):
    with open(filepath, 'rb') as stream:
        data = bytearray(stream.read())
    header, size = _find_binary_chunk(data)
    version, entries, _, _, _ = _parse_payload(data[header + 12:header + 12 + size])
    return data, version, entries


def make_default_entry(index=0):
    entry = {key: 0 for _, key in NUMERIC_FIELDS}
    entry.update({key: '' for _, key in STRING_FIELDS})
    entry.update(char_id=f'DIC_ID_DMY_{index + 1}', title=f'dictionary_t{index + 1:03d}',
                 header=f'dictionary_h{index + 1:03d}', dmy='dmy01', no_panel=4,
                 const1=1, padding=0xFFFFFFFF, index=index)
    return entry


def _validate(version, entries):
    struct.pack('<I', version)
    for entry in entries:
        for _, key in STRING_FIELDS:
            _encoded(entry[key])
        for _, key in NUMERIC_FIELDS:
            struct.pack('<I', entry[key])


def _build_dictionaryparam_binary(version, entries, notes=b'', pool_prefix=b''):
    _validate(version, entries)
    buf = bytearray(struct.pack('<IIq', version, len(entries), 8 + len(notes)))
    buf.extend(notes)
    start = len(buf)
    for entry in entries:
        buf.extend(entry.get('_record', bytes(ENTRY_SIZE)))
    buf.extend(pool_prefix)
    pool = {}
    for i, entry in enumerate(entries):
        base = start + i * ENTRY_SIZE
        for off, key in NUMERIC_FIELDS:
            struct.pack_into('<I', buf, base + off, entry[key])
        for off, key in STRING_FIELDS:
            text = entry[key]
            pointer = 0
            if text or key not in entry.get('_null_fields', tuple(k for _, k in STRING_FIELDS)):
                if text not in pool:
                    pool[text] = len(buf)
                    buf.extend(_encoded(text))
                    buf.extend(bytes(-len(buf) % 8))
                pointer = pool[text] - base - off
            struct.pack_into('<q', buf, base + off, pointer)
    buf.extend(bytes(-len(buf) % 4))
    return bytes(buf)


def save_dictionaryparam_xfbin(filepath, original_data, version, entries):
    _validate(version, entries)
    header, size = _find_binary_chunk(original_data)
    payload_off = header + 12
    old = original_data[payload_off:payload_off + size]
    _, previous, notes, pool, tail = _parse_payload(old)
    if (len(entries) == len(previous) and
            all(e.get('_offset') == p['_offset'] for e, p in zip(entries, previous))):
        inner_size = struct.unpack_from('>I', old)[0]
        payload = bytearray(old[:4 + inner_size])
        struct.pack_into('<I', payload, 4, version)
        for entry, before in zip(entries, previous):
            base = before['_offset']
            for off, key in NUMERIC_FIELDS:
                struct.pack_into('<I', payload, base + off, entry[key])
            for off, key in STRING_FIELDS:
                if entry[key] != before[key]:
                    pointer = len(payload) - base - off if entry[key] else 0
                    struct.pack_into('<q', payload, base + off, pointer)
                    if entry[key]:
                        payload.extend(_encoded(entry[key]))
        if payload != old[:4 + inner_size]:
            struct.pack_into('>I', payload, 0, len(payload) - 4)
        payload.extend(tail)
    else:
        inner = _build_dictionaryparam_binary(version, entries, notes, pool)
        payload = bytearray(struct.pack('>I', len(inner)) + inner + tail)
    chunk_header = bytearray(original_data[header:payload_off])
    struct.pack_into('>I', chunk_header, 0, len(payload))
    output = original_data[:header] + chunk_header + payload + original_data[payload_off + size:]
    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-dictionary-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
