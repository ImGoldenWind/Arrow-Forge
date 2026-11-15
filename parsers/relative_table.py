"""Lossless fixed-row NUCC tables with signed self-relative string pointers.

Format owners supply the exact row width and field schema. No gameplay meaning
or UI behavior belongs here. Unchanged rows patch in place; structural edits
rebuild pointers while retaining opaque records, notes and the original pool.
"""
import os
import struct
import tempfile

from parsers.skill_parser import _find_chunks


class RelativeTable:
    def __init__(self, name, stride, strings, numbers):
        self.name, self.stride = name, stride
        self.strings, self.numbers = tuple(strings), tuple(numbers)
        self.string_keys = tuple(key for _, key in strings)

    @staticmethod
    def encoded(text):
        if not isinstance(text, str) or '\0' in text:
            raise ValueError('References must be strings without NUL bytes.')
        return text.encode('utf-8', errors='surrogateescape') + b'\0'

    def parse_payload(self, payload):
        if len(payload) < 20:
            raise ValueError(f'Truncated {self.name} header.')
        size = struct.unpack_from('>I', payload)[0]
        if not 16 <= size <= len(payload) - 4:
            raise ValueError(f'Invalid {self.name} inner length.')
        body = payload[:4 + size]
        version, count, first = struct.unpack_from('<IIq', body, 4)
        start = 12 + first
        end = start + count * self.stride
        if start < 20 or end > len(body):
            raise ValueError(f'Invalid {self.name} row table.')
        entries = []
        for i in range(count):
            base = start + i * self.stride
            entry = {'_offset': base, '_record': bytes(body[base:base + self.stride])}
            nulls = []
            for off, key in self.strings:
                pointer = struct.unpack_from('<q', body, base + off)[0]
                if pointer == 0:
                    entry[key] = ''
                    nulls.append(key)
                else:
                    target = base + off + pointer
                    if not 20 <= target < len(body):
                        raise ValueError(f'{self.name} {key} pointer is outside the payload.')
                    terminator = body.find(b'\0', target)
                    if terminator < 0:
                        raise ValueError(f'Unterminated {self.name} {key}.')
                    entry[key] = bytes(body[target:terminator]).decode('utf-8', errors='surrogateescape')
            entry['_null_fields'] = tuple(nulls)
            for off, key, fmt in self.numbers:
                entry[key] = struct.unpack_from('<' + fmt, body, base + off)[0]
            entries.append(entry)
        return version, entries, bytes(body[20:start]), bytes(body[end:]), bytes(payload[4 + size:])

    def find_chunk(self, data):
        chunks = _find_chunks(data)
        named = [item for name, item in chunks.items() if name.lower() == self.name.lower()]
        if len(named) == 1:
            return named[0][:2]
        candidates = []
        for header, size, payload in chunks.values():
            try:
                self.parse_payload(data[payload:payload + size])
            except (ValueError, struct.error):
                continue
            candidates.append((header, size))
        if len(candidates) != 1:
            raise ValueError(f'Could not identify a unique {self.name} chunk.')
        return candidates[0]

    def parse(self, filepath):
        with open(filepath, 'rb') as stream:
            data = bytearray(stream.read())
        header, size = self.find_chunk(data)
        version, entries, _, _, _ = self.parse_payload(data[header + 12:header + 12 + size])
        return data, version, entries

    def validate(self, version, entries):
        struct.pack('<I', version)
        for entry in entries:
            for key in self.string_keys:
                self.encoded(entry[key])
            for _, key, fmt in self.numbers:
                struct.pack('<' + fmt, entry.get(key, 0))

    def build(self, version, entries, notes=b'', pool_prefix=b''):
        self.validate(version, entries)
        body = bytearray(struct.pack('<IIq', version, len(entries), 8 + len(notes)) + notes)
        start = len(body)
        for entry in entries:
            body.extend(entry.get('_record', bytes(self.stride)))
        body.extend(pool_prefix)
        pool = {}
        for i, entry in enumerate(entries):
            base = start + i * self.stride
            for off, key, fmt in self.numbers:
                struct.pack_into('<' + fmt, body, base + off, entry.get(key, 0))
            for off, key in self.strings:
                text, pointer = entry[key], 0
                if text or key not in entry.get('_null_fields', self.string_keys):
                    if text not in pool:
                        pool[text] = len(body)
                        body.extend(self.encoded(text))
                        body.extend(bytes(-len(body) % 8))
                    pointer = pool[text] - base - off
                struct.pack_into('<q', body, base + off, pointer)
        return bytes(body)

    def save(self, filepath, original_data, version, entries):
        self.validate(version, entries)
        header, size = self.find_chunk(original_data)
        offset = header + 12
        old = original_data[offset:offset + size]
        _, previous, notes, pool, tail = self.parse_payload(old)
        if len(entries) == len(previous) and all(
                e.get('_offset') == p['_offset'] for e, p in zip(entries, previous)):
            inner_size = struct.unpack_from('>I', old)[0]
            payload = bytearray(old[:4 + inner_size])
            struct.pack_into('<I', payload, 4, version)
            for entry, before in zip(entries, previous):
                base = before['_offset']
                for off, key, fmt in self.numbers:
                    struct.pack_into('<' + fmt, payload, base + off, entry.get(key, 0))
                for off, key in self.strings:
                    if entry[key] != before[key]:
                        pointer = len(payload) - base - off if entry[key] else 0
                        struct.pack_into('<q', payload, base + off, pointer)
                        if entry[key]:
                            payload.extend(self.encoded(entry[key]))
            struct.pack_into('>I', payload, 0, len(payload) - 4)
            payload.extend(tail)
        else:
            body = self.build(version, entries, notes, pool)
            payload = struct.pack('>I', len(body)) + body + tail
        chunk_header = bytearray(original_data[header:offset])
        struct.pack_into('>I', chunk_header, 0, len(payload))
        output = original_data[:header] + chunk_header + payload + original_data[offset + size:]
        destination = os.path.abspath(filepath)
        fd, temporary = tempfile.mkstemp(prefix='.arrow-table-', dir=os.path.dirname(destination))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(output)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
