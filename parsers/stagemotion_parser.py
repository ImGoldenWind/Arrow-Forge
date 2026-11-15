"""Lossless Xcmnsfprm reader/writer; native layout at RVA 22F1F0.

44-byte prelude (global stage count +40), 156-byte headers, 200-byte commands.
Unknown bytes are retained. See docs/stage-motion-research.md.
"""
import math
import os
import struct
import tempfile

STAGE_HEADER_SIZE = 156
ENTRY_SIZE = 200
PAYLOAD_PRELUDE = 44
ENTRY_FIELDS = {'frame': 0x30, 'type_code': 0x34, 'val3': 0x38}


def _find_binary_chunk(raw):
    if len(raw) < 28 or raw[:4] != b'NUCC':
        raise ValueError('Invalid or truncated NUCC header')
    offset = 28 + struct.unpack_from('>I', raw, 16)[0]
    while offset + 12 <= len(raw):
        size, index = struct.unpack_from('>II', raw, offset)
        if offset + 12 + size > len(raw):
            raise ValueError('Truncated XFBIN chunk')
        if index == 1 and size:
            return offset, offset + 12, size
        offset += 12 + size + (-size % 4)
    raise ValueError('Binary chunk not found in XFBIN')


def _read_str(buf, offset):
    return bytes(buf[offset:offset + 32]).split(b'\0', 1)[0].decode('ascii', errors='surrogateescape')


def _write_str(buf, offset, value):
    if '\0' in value:
        raise ValueError('Names cannot contain NUL')
    encoded = value.encode('ascii')
    if len(encoded) > 31:
        raise ValueError('Names must fit in 31 ASCII bytes plus NUL')
    buf[offset:offset + 32] = encoded.ljust(32, b'\0')


def _uint(value):
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError('Integer must be between 0 and 4294967295')
    return value


def _parse_entry(raw):
    result = {key: struct.unpack_from('<I', raw, off)[0] for key, off in ENTRY_FIELDS.items()}
    result.update(name=_read_str(raw, 8), float_val=struct.unpack_from('<f', raw, 0x4c)[0], _raw=bytes(raw))
    result['_original'] = {key: result[key] for key in ('name', *ENTRY_FIELDS, 'float_val')}
    return result


def _pack_entry(entry):
    buf = bytearray(entry.get('_raw', bytes(ENTRY_SIZE)))
    if len(buf) != ENTRY_SIZE:
        raise ValueError('Invalid command size')
    original = entry.get('_original', {})
    name = entry.get('name', '')
    if name != original.get('name'):
        _write_str(buf, 8, name)
    for key, off in ENTRY_FIELDS.items():
        struct.pack_into('<I', buf, off, _uint(entry.get(key, 0)))
    value = entry.get('float_val', 0.)
    previous = original.get('float_val')
    # Keep untouched signaling NaNs and signed zero bit-for-bit.
    if 'float_val' not in original or not (value is previous or
            (value == previous and math.copysign(1, value) == math.copysign(1, previous))):
        if not math.isfinite(value):
            raise ValueError('New float values must be finite')
        struct.pack_into('<f', buf, 0x4c, value)
    return buf


def _parse_stage(raw):
    count = struct.unpack_from('<I', raw, 0x6c)[0]
    result = dict(nut_type=_read_str(raw, 0), stage_id=_read_str(raw, 32),
                  entry_count=count, sub_count=struct.unpack_from('<I', raw, 0x70)[0],
                  _raw=bytes(raw[:STAGE_HEADER_SIZE]))
    result['_original'] = {key: result[key] for key in ('nut_type', 'stage_id')}
    result['entries'] = [_parse_entry(raw[off:off + ENTRY_SIZE])
                         for off in range(STAGE_HEADER_SIZE, len(raw), ENTRY_SIZE)]
    return result


def _pack_stage(stage):
    buf = bytearray(stage.get('_raw', bytes(STAGE_HEADER_SIZE)))
    if len(buf) != STAGE_HEADER_SIZE:
        raise ValueError('Invalid stage header size')
    if '_raw' not in stage:
        struct.pack_into('<Q', buf, 0x5c, 0xFFFFFFFFFFFFFFFF)
    for key, off, default in (('nut_type', 0, 'PL_ANM_NUT'), ('stage_id', 32, '')):
        value = stage.get(key, default)
        if value != stage.get('_original', {}).get(key):
            _write_str(buf, off, value)
    entries = stage.get('entries', [])
    struct.pack_into('<II', buf, 0x6c, len(entries), _uint(stage.get('sub_count', 2)))
    return buf + b''.join(_pack_entry(entry) for entry in entries)


def parse_stagemotion_xfbin(filepath):
    with open(filepath, 'rb') as source:
        raw = bytearray(source.read())
    hdr, data, size = _find_binary_chunk(raw)
    payload = raw[data:data + size]
    if len(payload) < PAYLOAD_PRELUDE or struct.unpack_from('>I', payload)[0] != size - 4:
        raise ValueError('Invalid Stage Motion payload size')
    count = struct.unpack_from('<I', payload, 40)[0]
    if count > (size - PAYLOAD_PRELUDE) // STAGE_HEADER_SIZE:
        raise ValueError('Stage count exceeds payload')
    stages, offset = [], PAYLOAD_PRELUDE
    for index in range(count):
        if offset + STAGE_HEADER_SIZE > size:
            raise ValueError(f'Truncated stage {index}')
        entries = struct.unpack_from('<I', payload, offset + 0x6c)[0]
        end = offset + STAGE_HEADER_SIZE + entries * ENTRY_SIZE
        if end > size:
            raise ValueError(f'Truncated commands in stage {index}')
        stages.append(_parse_stage(payload[offset:end]))
        offset = end
    return raw, dict(stages=stages, file_magic=struct.unpack_from('<I', payload, 4)[0],
                     bin_hdr_offset=hdr, bin_data_offset=data,
                     _prelude=bytes(payload[:PAYLOAD_PRELUDE]), _tail=bytes(payload[offset:]),
                     _padding=bytes(raw[data + size:data + size + (-size % 4)]))


def save_stagemotion_xfbin(filepath, raw, result):
    hdr, data = result['bin_hdr_offset'], result['bin_data_offset']
    old_size = struct.unpack_from('>I', raw, hdr)[0]
    prelude = bytearray(result.get('_prelude', bytes(PAYLOAD_PRELUDE)))
    struct.pack_into('<I', prelude, 4, _uint(result.get('file_magic', 1001)))
    struct.pack_into('<I', prelude, 40, len(result['stages']))
    payload = prelude + b''.join(_pack_stage(s) for s in result['stages']) + result.get('_tail', b'')
    struct.pack_into('>I', payload, 0, len(payload) - 4)
    header = bytearray(raw[hdr:hdr + 12])
    struct.pack_into('>I', header, 0, len(payload))
    padding = result.get('_padding', b'')
    if len(padding) != -len(payload) % 4:
        padding = bytes(-len(payload) % 4)
    output = raw[:hdr] + header + payload + padding + raw[data + old_size + (-old_size % 4):]
    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-motion-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(output)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
