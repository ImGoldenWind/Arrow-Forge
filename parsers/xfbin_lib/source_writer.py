"""Save texture and binary edits without re-encoding other NUCC payloads."""

import struct

from .binary_reader import BinaryReader, Endian
from .br_nucc import BrNuccChunkTexture
from .br_xfbin import BrPage
from .iterative_dict import IterativeDict
from .nucc import NuccChunk, NuccChunkBinary, NuccChunkIndex, NuccChunkPage, NuccChunkTexture


class SourceLayout:
    def __init__(self, data, parsed):
        self.data = data
        self.pages_offset = parsed.pages_offset
        table = parsed.chunk_table
        self.strings = (table.chunk_types, table.file_paths, table.chunk_names)
        self.maps = [(m.chunk_type_index, m.file_path_index, m.chunk_name_index) for m in table.chunk_maps]
        self.references = [(r.chunk_name_index, r.chunk_map_index) for r in table.chunk_map_references]
        self.indices = table.chunk_map_indices

        self.string_bytes = []
        offset = 68  # NUCC header and the ten chunk table count/size words
        for size in (table.chunk_type_size, table.file_path_size, table.chunk_name_size):
            self.string_bytes.append(data[offset:offset + size])
            offset += size
        self.string_padding = data[offset:(offset + 3) & ~3]

        offset = self.pages_offset
        self.initial_null = b''
        if parsed.pages:
            size, local = struct.unpack_from('>II', data, offset)
            first_type = self.maps[parsed.pages[0].page_chunk_indices[local]][0]
            if size == 0 and self.strings[0][first_type] == 'nuccChunkNull':
                self.initial_null = data[offset:offset + 12]
                offset += 12
        self.pages = []
        for page in parsed.pages:
            records = []
            while offset < page.end_offset:
                size, local = struct.unpack_from('>II', data, offset)
                end = offset + 12 + size
                records.append((page.page_chunk_indices[local], offset, end))
                offset = end
            self.pages.append((page.page_chunk_indices, records))

    def write(self, pages):
        table = _TableEdit(self)
        payload = bytearray(self.initial_null)
        for page_number, page in enumerate(pages):
            source_page = getattr(page, 'source_page_index', None)
            start = len(payload)
            if source_page is None:
                table.append_page(page, payload)
            else:
                self._write_page(page, source_page, table, payload)
            if page_number == 0 and source_page != 0 and self.initial_null:
                # The file's leading null uses the first surviving page's local map.
                payload[4:8] = payload[start + 4:start + 8]
        result = table.header_and_table()
        result.extend(payload)
        return result

    def _write_page(self, page, source_page, table, payload):
        indices, records = self.pages[source_page]
        table.indices.extend(indices)
        table.add_references(page.chunk_references)
        chunks = {chunk.source_map_index: chunk for chunk in page.chunks}
        for index, offset, end in records:
            chunk = chunks.get(index)
            if chunk is None:
                continue
            table.register(chunk, index)
            original = self.data[offset + 12:end]
            updated = _edited_payload(chunk, original)
            if isinstance(chunk, NuccChunkPage):
                old_count = struct.unpack_from('>I', original, 4)[0]
                if old_count != len(page.chunk_references):
                    updated = original[:4] + struct.pack('>I', len(page.chunk_references)) + original[8:]
            if updated is None:
                payload.extend(self.data[offset:end])
            else:
                payload.extend(struct.pack('>I', len(updated)))
                payload.extend(self.data[offset + 4:offset + 12])
                payload.extend(updated)


def _edited_payload(chunk, original):
    if isinstance(chunk, NuccChunkBinary):
        old_size = struct.unpack_from('>I', chunk.data)[0]
        if chunk.binary_data != chunk.data[4:4 + old_size]:
            size = struct.unpack_from('>I', original)[0]
            return struct.pack('>I', len(chunk.binary_data)) + bytes(chunk.binary_data) + original[4 + size:]
    elif isinstance(chunk, NuccChunkTexture) and chunk.nut.storage_key() != chunk._original_nut_key:
        writer = BrNuccChunkTexture()
        writer.nuccChunk = chunk
        with BinaryReader(endianness=Endian.BIG) as stream:
            stream.write_struct(writer, IterativeDict())
            size = struct.unpack_from('>I', original, 8)[0]
            return bytes(stream.buffer()) + original[12 + size:]
    return None


class _TableEdit:
    def __init__(self, source):
        self.source = source
        self.strings = [list(section) for section in source.strings]
        self.lookup = [dict() for _ in self.strings]
        for strings, lookup in zip(self.strings, self.lookup):
            for index, value in enumerate(strings):
                lookup.setdefault(value, index)
        self.maps = list(source.maps)
        self.map_lookup = {}
        for index, row in enumerate(self.maps):
            self.map_lookup.setdefault(row, index)
        self.indices = []
        self.references = []

    def _string_index(self, section, value, original=None):
        strings, lookup = self.strings[section], self.lookup[section]
        if original is not None and strings[original] == value:
            return original
        if value not in lookup:
            if '\0' in value:
                raise ValueError('XFBIN names and paths cannot contain a null character')
            lookup[value] = len(strings)
            strings.append(value)
        return lookup[value]

    def register(self, chunk, original=None):
        values = (NuccChunk.get_nucc_str_from_type(type(chunk)), chunk.filePath, chunk.name)
        existing = (None, None, None) if original is None else self.source.maps[original]
        row = tuple(self._string_index(section, value, old) for section, (value, old) in enumerate(zip(values, existing)))
        if original is not None:
            # Original local indices retain their global map even when a name changes.
            previous = self.maps[original]
            self.maps[original] = row
            if previous != row and self.map_lookup.get(previous) == original:
                del self.map_lookup[previous]
            self.map_lookup.setdefault(row, original)
            return original
        if row not in self.map_lookup:
            self.map_lookup[row] = len(self.maps)
            self.maps.append(row)
        return self.map_lookup[row]

    def add_references(self, references):
        for ref in references:
            source_index = getattr(ref, 'source_reference_index', None)
            old_name = self.source.references[source_index][0] if source_index is not None else None
            name = self._string_index(2, ref.name, old_name)
            index = self.register(ref.chunk, getattr(ref.chunk, 'source_map_index', None))
            self.references.append((name, index))

    def append_page(self, page, payload):
        with BinaryReader(endianness=Endian.BIG) as stream:
            br_page = BrPage()
            stream.write_struct(br_page, page)
            payload.extend(stream.buffer())
        br_page.chunk_index_dict.get_or_next(NuccChunkIndex())
        self.indices.extend(self.register(chunk) for chunk in br_page.chunk_index_dict)
        self.add_references(page.chunk_references)

    def header_and_table(self):
        source = self.source
        if self.maps == source.maps and self.references == source.references and self.indices == source.indices:
            return bytearray(source.data[:source.pages_offset])

        header = bytearray(source.data[:28])
        table = bytearray()
        sections = bytearray()
        for original, raw, strings in zip(source.strings, source.string_bytes, self.strings):
            added = b''.join(value.encode('cp932') + b'\0' for value in strings[len(original):])
            table.extend(struct.pack('>II', len(strings), len(raw) + len(added)))
            sections.extend(raw)
            sections.extend(added)
        table.extend(struct.pack('>4I', len(self.maps), len(self.maps) * 12, len(self.indices), len(self.references)))
        table.extend(sections)
        padding = -len(table) % 4
        table.extend(source.string_padding[:padding].ljust(padding, b'\0'))
        for row in self.maps:
            table.extend(struct.pack('>III', *row))
        for ref in self.references:
            table.extend(struct.pack('>II', *ref))
        table.extend(struct.pack(f'>{len(self.indices)}I', *self.indices))
        struct.pack_into('>I', header, 16, len(table) - 8 * len(self.references))
        header.extend(table)
        return header
