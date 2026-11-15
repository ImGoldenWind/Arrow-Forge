"""Lossless effectprm codec. The second word selects a native factory.

Native ASBR rows have two u32 and two char[32]. Legacy extracted catalogs
with char[64] are supported. Original string padding and opaque bytes survive.
"""
import os
import struct
import tempfile

from parsers.skill_parser import _find_chunks

DEFAULT_ENTRY_SIZE = 72
HEADER_SIZE = 8
FIXED_FIELDS_SIZE = 8
FIELDS = ('slot_id', 'xfbins_count', 'xfbin_path', 'effect_name')


def _find_binary_chunk(raw):
    chunks = _find_chunks(raw)
    matches = [v for k, v in chunks.items() if k.lower() == 'effectprm']
    if not matches:
        matches = [v for v in chunks.values() if v[1] >= HEADER_SIZE]
    if len(matches) != 1:
        raise ValueError('Expected one effectprm binary chunk')
    header, size, offset = matches[0]
    return header, offset, size


def _entry_layout(size, count):
    area = size - HEADER_SIZE
    if count == 0:
        return DEFAULT_ENTRY_SIZE, 32
    if count > area // FIXED_FIELDS_SIZE or area % count:
        raise ValueError('Effect entry count does not match the binary size')
    entry_size = area // count
    if entry_size < 10 or (entry_size - FIXED_FIELDS_SIZE) % 2:
        raise ValueError(f'Unsupported effect entry size: {entry_size}')
    return entry_size, (entry_size - FIXED_FIELDS_SIZE) // 2


def _decode(data):
    # Latin-1 retains unfamiliar bytes; modified strings require ASCII.
    return bytes(data).split(b'\0', 1)[0].decode('latin1')


def encode_string(value, width):
    if not isinstance(value, str) or '\0' in value:
        raise ValueError('Effect strings cannot contain NUL')
    encoded = value.encode('ascii')
    if len(encoded) >= width:
        raise ValueError(f'Effect strings must fit {width - 1} ASCII bytes plus NUL')
    return encoded.ljust(width, b'\0')


def uint32(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xffffffff:
        raise ValueError('Expected an unsigned 32-bit integer')
    return value


def parse_effectprm_xfbin(filepath):
    with open(filepath, 'rb') as stream:
        raw = bytearray(stream.read())
    header, offset, size = _find_binary_chunk(raw)
    inner_size = struct.unpack_from('>I', raw, offset)[0] + 4
    if not HEADER_SIZE <= inner_size <= size:
        raise ValueError('Invalid effectprm inner size')
    count = struct.unpack_from('<I', raw, offset + 4)[0]
    entry_size, width = _entry_layout(inner_size, count)
    entries = []
    for i in range(count):
        start = offset + HEADER_SIZE + i * entry_size
        record = bytes(raw[start:start + entry_size])
        slot, factory = struct.unpack_from('<II', record)
        entries.append(dict(idx=i, slot_id=slot, xfbins_count=factory,
                            xfbin_path=_decode(record[8:8 + width]),
                            effect_name=_decode(record[8 + width:]), _raw_bytes=record))
    return raw, dict(entries=entries, entry_count=count, entry_size=entry_size,
                     string_len=width, bin_hdr_offset=header, bin_data_offset=offset,
                     suffix=bytes(raw[offset + HEADER_SIZE + count * entry_size:offset + size]))


def build_effectprm_xfbin(raw, result):
    header, offset, size = _find_binary_chunk(raw)
    entries = result['entries']
    entry_size, width = result['entry_size'], result['string_len']
    if entry_size != 8 + 2 * width or width < 1:
        raise ValueError('Invalid effectprm record layout')
    records = bytearray()
    for entry in entries:
        record = bytearray(entry.get('_raw_bytes', bytes(entry_size)))
        if len(record) != entry_size:
            raise ValueError('Effect record has an incompatible size')
        struct.pack_into('<II', record, 0, uint32(entry['slot_id']), uint32(entry['xfbins_count']))
        for key, start in (('xfbin_path', 8), ('effect_name', 8 + width)):
            if entry[key] != _decode(record[start:start + width]):
                record[start:start + width] = encode_string(entry[key], width)
        records.extend(record)
    inner_tail = b''
    suffix = result.get('suffix', b'')
    if result['entry_count'] == 0:
        old_inner = struct.unpack_from('>I', raw, offset)[0] + 4
        inner_tail = bytes(raw[offset + HEADER_SIZE:offset + old_inner])
        suffix = bytes(raw[offset + old_inner:offset + size])
        if entries and inner_tail:
            raise ValueError('Cannot extend an opaque empty effect table')
    payload = struct.pack('>I', 4 + len(records) + len(inner_tail)) + struct.pack('<I', len(entries)) + records + inner_tail + suffix
    chunk_header = bytearray(raw[header:offset])
    struct.pack_into('>I', chunk_header, 0, len(payload))
    return bytes(raw[:header]) + chunk_header + payload + bytes(raw[offset + size:])


def save_effectprm_xfbin(filepath, raw, result):
    output = build_effectprm_xfbin(raw, result)
    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-effect-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
