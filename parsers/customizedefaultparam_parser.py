"""CustomizeDefaultParam: bounded, lossless 32-byte records in contiguous NUCC.

Public (raw, version, entries) API and historical field keys are retained.
See docs/customize-default-research.md for native consumers and scope.
"""
import math
import os
import struct
import tempfile

from parsers.skill_parser import _find_chunks

ENTRY_SIZE = 32
HEADER_SIZE = 16
FLOAT_FIELDS = ((12, 'pos_x'), (16, 'pos_y'), (20, 'unk'),
                (24, 'scale'), (28, 'unk2'))
SLOT_NAMES = {0: 'Normal A', 1: 'Normal B', 2: 'Zoom'}


def _encoded(text):
    if not isinstance(text, str) or '\0' in text:
        raise ValueError('Character code must be a string without NUL bytes.')
    return text.encode('utf-8', errors='surrogateescape') + b'\0'


def _parse_payload(payload):
    if len(payload) < 20:
        raise ValueError('Truncated CustomizeDefaultParam header.')
    inner_size = struct.unpack_from('>I', payload)[0]
    if not HEADER_SIZE <= inner_size <= len(payload) - 4:
        raise ValueError('Invalid CustomizeDefaultParam inner size.')
    body = payload[:4 + inner_size]
    version, count, first = struct.unpack_from('<IIq', body, 4)
    start = 12 + first
    end_table = start + count * ENTRY_SIZE
    if start < 20 or end_table > len(body):
        raise ValueError('Invalid CustomizeDefaultParam entry table.')
    entries = []
    for i in range(count):
        base = start + i * ENTRY_SIZE
        record = bytes(body[base:base + ENTRY_SIZE])
        entry = {'_offset': base, '_record': record}
        pointer = struct.unpack_from('<q', body, base)[0]
        entry['_null_string'] = not pointer
        if pointer:
            target = base + pointer
            if not 20 <= target < len(body):
                raise ValueError('Character reference is outside its payload.')
            end = body.find(b'\0', target)
            if end < 0:
                raise ValueError('Unterminated character reference.')
            entry['char_code'] = bytes(body[target:end]).decode('utf-8', errors='surrogateescape')
        else:
            entry['char_code'] = ''
        entry['slot'] = struct.unpack_from('<I', body, base + 8)[0]
        for off, key in FLOAT_FIELDS:
            entry[key] = struct.unpack_from('<f', body, base + off)[0]
        entries.append(entry)
    return version, entries, bytes(body[20:start]), bytes(body[end_table:]), bytes(payload[4 + inner_size:])


def _find_binary_chunk(data):
    chunks = _find_chunks(data)
    named = [v for k, v in chunks.items() if k.lower() == 'customizedefaultparam']
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
        raise ValueError('Could not identify a unique CustomizeDefaultParam chunk.')
    return candidates[0]


def parse_customizedefaultparam_xfbin(filepath):
    with open(filepath, 'rb') as stream:
        data = bytearray(stream.read())
    header, size = _find_binary_chunk(data)
    version, entries, _, _, _ = _parse_payload(data[header + 12:header + 12 + size])
    return data, version, entries


def make_default_entry(char_code='1jnt01', slot=0):
    # Legacy API defaults. The editor uses a file-backed donor when available.
    return dict(char_code=char_code, slot=slot, pos_x=980. if slot == 2 else 480.,
                pos_y=320. if slot == 2 else 576., unk=0.,
                scale=1.8 if slot == 2 else 1., unk2=0.)


def _same_float(value, raw):
    before = struct.unpack('<f', raw)[0]
    return (math.isnan(value) and math.isnan(before)) or struct.pack('<f', value) == raw


def _write_numbers(buf, base, entry):
    struct.pack_into('<I', buf, base + 8, entry['slot'])
    record = entry.get('_record', b'')
    for off, key in FLOAT_FIELDS:
        raw = record[off:off + 4]
        if len(raw) == 4 and _same_float(entry[key], raw):
            buf[base + off:base + off + 4] = raw
        else:
            struct.pack_into('<f', buf, base + off, entry[key])


def _validate(version, entries):
    struct.pack('<I', version)
    for entry in entries:
        _encoded(entry['char_code'])
        _write_numbers(bytearray(ENTRY_SIZE), 0, entry)


def _build_binary(version, entries, notes=b'', pool_prefix=b''):
    _validate(version, entries)
    buf = bytearray(struct.pack('<IIq', version, len(entries), 8 + len(notes)))
    buf.extend(notes)
    start = len(buf)
    buf.extend(bytes(len(entries) * ENTRY_SIZE))
    buf.extend(pool_prefix)
    pool = {}
    for i, entry in enumerate(entries):
        base = start + i * ENTRY_SIZE
        _write_numbers(buf, base, entry)
        text = entry['char_code']
        pointer = 0
        if text or not entry.get('_null_string', True):
            if text not in pool:
                pool[text] = len(buf)
                buf.extend(_encoded(text))
                buf.extend(bytes(-len(buf) % 8))
            pointer = pool[text] - base
        struct.pack_into('<q', buf, base, pointer)
    buf.extend(bytes(-len(buf) % 4))
    return bytes(buf)


def save_customizedefaultparam_xfbin(filepath, original_data, version, entries):
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
            _write_numbers(payload, base, entry)
            if entry['char_code'] != before['char_code']:
                pointer = len(payload) - base if entry['char_code'] else 0
                struct.pack_into('<q', payload, base, pointer)
                if entry['char_code']:
                    payload.extend(_encoded(entry['char_code']))
        if payload != old[:4 + inner_size]:
            struct.pack_into('>I', payload, 0, len(payload) - 4)
        payload.extend(tail)
    else:
        inner = _build_binary(version, entries, notes, pool)
        payload = bytearray(struct.pack('>I', len(inner)) + inner + tail)
    envelope = bytearray(original_data[header:payload_off])
    struct.pack_into('>I', envelope, 0, len(payload))
    output = original_data[:header] + envelope + payload + original_data[payload_off + size:]
    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-customize-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
