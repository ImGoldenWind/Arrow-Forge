"""Lossless Sound CMN tables, including inactive storage and page-local maps.

Counts are signed i16 in native loaders. CRI names are 64/64/32 bytes,
not five independent 32-byte strings. Semantics live in soundparam_tools.
"""
import math
import os
import struct
import tempfile

from parsers.xfbin_lib.binary_reader import BinaryReader, Endian
from parsers.xfbin_lib.br_xfbin import BrChunkTable, BrNuccHeader

SNDCMN_ENTRY_SIZE, PLDATA_ENTRY_SIZE, CRIDATA_ENTRY_SIZE = 32, 212, 178
SCHEMAS = {
    'sndcmnparam': (32, ((0, 'audio_id', 32),), ()),
    'pldata': (212, tuple((i * 32, key, 32) for i, key in enumerate(
        ('char_id', 'pl', 'null1', 'spl', 'spl_interaction', 'ev'))),
        tuple((192 + i * 4, key, 'f') for i, key in enumerate(
            ('stand_index', 'unk2', 'unk3', 'entity', 'char_index')))),
    'cridata': (178, ((16, 'str0', 64), (80, 'str2', 64), (144, 'str4', 32)),
        (*tuple((i * 4, f'float{i}', 'f') for i in range(4)), (176, 'flag', 'H'))),
}


def _decode(data):
    return bytes(data).split(b'\0', 1)[0].decode('latin1')


def encode_string(value, width):
    if not isinstance(value, str) or '\0' in value:
        raise ValueError('Sound references must be strings without NUL bytes.')
    data = value.encode('ascii')
    if len(data) >= width:
        raise ValueError(f'Sound reference must fit {width - 1} ASCII bytes plus NUL.')
    return data.ljust(width, b'\0')


def _scan_chunks(raw):
    if len(raw) < 68 or raw[:4] != b'NUCC':
        raise ValueError('Not a NUCC/XFBIN container.')
    counts = struct.unpack_from('>10I', raw, 28)
    end = (68 + counts[1] + counts[3] + counts[5] + 3) & ~3
    end += counts[6] * 12 + counts[9] * 8 + counts[8] * 4
    if end > len(raw) or any(counts[i] > end for i in (0, 2, 4, 6, 8, 9)):
        raise ValueError('Invalid XFBIN chunk table.')
    try:
        with BinaryReader(raw[:end], Endian.BIG, 'cp932') as reader:
            reader.read_struct(BrNuccHeader)
            table = reader.read_struct(BrChunkTable)
    except Exception as exc:
        raise ValueError('Invalid XFBIN chunk table.') from exc
    offset, page_start, chunks = end, 0, []
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError('Truncated XFBIN chunk header.')
        size, index = struct.unpack_from('>II', raw, offset)
        if size > len(raw) - offset - 12:
            raise ValueError('Truncated XFBIN chunk payload.')
        try:
            mapping = table.chunk_map_indices[page_start + index]
            kind, path, name = table.get_props_from_chunk_map(table.chunk_maps[mapping])
        except IndexError as exc:
            raise ValueError('Invalid page-local XFBIN chunk mapping.') from exc
        chunks.append(dict(hdr_offset=offset, data_offset=offset + 12, chunk_size=size,
                           name=name, kind=kind, path=path))
        if kind == 'nuccChunkPage':
            if size < 8:
                raise ValueError('Truncated XFBIN page.')
            page_start += struct.unpack_from('>I', raw, offset + 12)[0]
        offset += 12 + size
    return chunks


def _parse_section(raw, chunk):
    kind = chunk['name'].lower()
    kind = kind if kind in ('pldata', 'cridata') else 'sndcmnparam'
    stride, strings, numbers = SCHEMAS[kind]
    offset, size = chunk['data_offset'], chunk['chunk_size']
    if size < 6:
        raise ValueError(f'Truncated sound section {chunk["name"]}.')
    inner = struct.unpack_from('>I', raw, offset)[0] + 4
    count = struct.unpack_from('<h', raw, offset + 4)[0]
    if not 6 <= inner <= size or count < 0 or count > (inner - 6) // stride:
        raise ValueError(f'Invalid sound row count/length in {chunk["name"]}.')
    entries = []
    for i in range(count):
        base = offset + 6 + i * stride
        record = bytes(raw[base:base + stride])
        entry = dict(idx=i, _record=record)
        for start, key, width in strings:
            entry[key] = _decode(record[start:start + width])
        for start, key, fmt in numbers:
            entry[key] = struct.unpack_from('<' + fmt, record, start)[0]
        entries.append(entry)
    return dict(chunk, type=kind, entries=entries,
                _suffix=bytes(raw[offset + 6 + count * stride:offset + inner]),
                _tail=bytes(raw[offset + inner:offset + size]))


def parse_sndcmnparam_xfbin(filepath):
    with open(filepath, 'rb') as stream:
        raw = bytearray(stream.read())
    sections = [_parse_section(raw, chunk) for chunk in _scan_chunks(raw)
                if chunk['kind'] == 'nuccChunkBinary']
    if not sections:
        raise ValueError('No sound parameter tables found.')
    return raw, sections


def _build_payload(section):
    stride, strings, numbers = SCHEMAS[section['type']]
    entries = section['entries']
    if len(entries) > 32767:
        raise ValueError('Sound tables support at most 32767 active rows (signed i16).')
    records = bytearray()
    for entry in entries:
        record = bytearray(entry.get('_record', bytes(stride)))
        if len(record) != stride:
            raise ValueError('Incompatible sound record size.')
        for start, key, width in strings:
            if entry[key] != _decode(record[start:start + width]):
                record[start:start + width] = encode_string(entry[key], width)
        for start, key, fmt in numbers:
            before = struct.unpack_from('<' + fmt, record, start)[0]
            value = entry[key]
            # Keep untouched NaN payloads, signed zero and all string padding.
            if value == before or fmt == 'f' and math.isnan(value) and math.isnan(before):
                continue
            if fmt == 'f' and not math.isfinite(value):
                raise ValueError('Edited sound values must be finite float32 numbers.')
            if fmt == 'H' and (not isinstance(value, int) or not 0 <= value <= 65535):
                raise ValueError('Expected an unsigned 16-bit sound value.')
            struct.pack_into('<' + fmt, record, start, value)
        records.extend(record)
    body = struct.pack('<h', len(entries)) + records + section.get('_suffix', b'')
    return struct.pack('>I', len(body)) + body + section.get('_tail', b'')


def build_sndcmnparam_xfbin(raw, sections):
    chunks = _scan_chunks(raw)
    originals = {c['hdr_offset']: c for c in chunks if c['kind'] == 'nuccChunkBinary'}
    if len(sections) != len(originals) or {s['hdr_offset'] for s in sections} != set(originals):
        raise ValueError('Sound section identities do not match the source container.')
    replacements = {}
    for section in sections:
        original = originals[section['hdr_offset']]
        expected = original['name'].lower()
        expected = expected if expected in ('pldata', 'cridata') else 'sndcmnparam'
        if section['name'] != original['name'] or section['type'] != expected:
            raise ValueError('Sound section identity changed.')
        payload = _build_payload(section)
        header = bytearray(raw[section['hdr_offset']:section['hdr_offset'] + 12])
        struct.pack_into('>I', header, 0, len(payload))
        replacements[section['hdr_offset']] = header + payload
    output, cursor = bytearray(), 0
    for chunk in chunks:
        start = chunk['hdr_offset']
        if start not in replacements:
            continue
        output.extend(raw[cursor:start])
        output.extend(replacements[start])
        cursor = start + 12 + chunk['chunk_size']
    output.extend(raw[cursor:])
    return bytes(output)


def save_sndcmnparam_xfbin(filepath, raw, sections):
    output = build_sndcmnparam_xfbin(raw, sections)
    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-sound-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
