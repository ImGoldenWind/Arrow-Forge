from typing import Dict, List

from .binary_reader import BrStruct, BinaryReader, Endian, Whence
from .iterative_dict import IterativeDict
from .nucc import NuccChunk, NuccChunkNull, NuccChunkPage, NuccChunkIndex
from .xfbin_types import Page, Xfbin, ChunkReference
from .br_nucc import BrNuccChunk, BrNuccChunkNull, BrNuccChunkPage, BrNuccChunkIndex


# Top-level XFBIN binary structure
class BrXfbin(BrStruct):

    def __br_read__(self, br: BinaryReader):
        self.header      = br.read_struct(BrNuccHeader)
        self.chunk_table = br.read_struct(BrChunkTable)

        self.pages               = []
        self.cur_page_start      = 0
        self.cur_reference_start = 0

        while not br.eof():
            br_page = br.read_struct(BrPage, None, self)
            self.cur_page_start      += br_page.page_chunk.pageSize
            self.cur_reference_start += br_page.page_chunk.referenceSize
            self.pages.append(br_page)

    def __br_write__(self, br: BinaryReader, xfbin: Xfbin):
        # Stage 1: write all page data into a side buffer
        br_pages = BinaryReader(endianness=Endian.BIG)

        # The first chunk across the whole file is always a null chunk
        initial_null            = BrNuccChunkNull()
        initial_null.nuccChunk  = NuccChunkNull()
        br_pages.write_struct(BrChunk(), initial_null, IterativeDict())

        chunk_map_dict   = IterativeDict()
        all_references:  List[ChunkReference] = []
        all_indices:     List[NuccChunk]       = []

        for page in xfbin:
            br_page = BrPage()
            br_pages.write_struct(br_page, page)

            # Register the implicit NuccChunkIndex that follows each page chunk
            br_page.chunk_index_dict.get_or_next(NuccChunkIndex())

            chunk_map_dict.update_or_next(br_page.chunk_index_dict)
            all_references.extend(br_page.chunk_references)
            all_indices.extend(br_page.chunk_index_dict.keys())

        # Stage 2: build chunk table
        br_table = BrChunkTable()
        br_table.chunk_map_dict          = chunk_map_dict
        br_table.chunk_references        = all_references
        br_table.chunk_map_indices       = all_indices

        with BinaryReader(endianness=Endian.BIG) as br_table_buf:
            br_table_buf.write_struct(br_table)

            # Stage 3: write header + table + pages
            hdr = BrNuccHeader()
            hdr.chunk_table_size = br_table_buf.size() - br_table.chunk_map_references_size

            br.write_struct(hdr)
            br.extend(br_table_buf.buffer())
            br.seek(br_table_buf.size(), Whence.CUR)

        br.extend(br_pages.buffer())
        br.seek(br_pages.size(), Whence.CUR)


# NUCC file header
class BrNuccHeader(BrStruct):
    chunk_table_size: int

    def __br_read__(self, br: BinaryReader):
        self.magic = br.read_str(4)
        if self.magic == 'CPK ':
            raise ValueError('File is CPK-compressed, not an XFBIN')
        if self.magic != 'NUCC':
            raise ValueError(f'Invalid XFBIN magic: {self.magic!r}')
        self.nucc_id        = br.read_uint32()
        br.seek(8, Whence.CUR)          # 8 padding bytes
        self.chunk_table_size = br.read_uint32()
        self.min_page_size  = br.read_uint32()
        self.nucc_id2       = br.read_uint16()
        self.unk            = br.read_uint16()

    def __br_write__(self, br: BinaryReader):
        br.write_str('NUCC')
        br.write_uint32(0x79)
        br.write_uint64(0)              # padding
        br.write_uint32(self.chunk_table_size)
        br.write_uint32(3)
        br.write_uint16(0x79)
        br.write_uint16(0)


# Chunk-table structures
class BrChunkMap(BrStruct):
    def __br_read__(self, br: BinaryReader):
        self.chunk_type_index = br.read_uint32()
        self.file_path_index  = br.read_uint32()
        self.chunk_name_index = br.read_uint32()

    def __br_write__(self, br: BinaryReader, chunk_tuple: tuple, dict_tuple: tuple):
        for val, d in zip(chunk_tuple, dict_tuple):
            br.write_uint32(d.get_or_next(val))


class BrChunkReference(BrStruct):
    def __br_read__(self, br: BinaryReader):
        self.chunk_name_index = br.read_uint32()
        self.chunk_map_index  = br.read_uint32()

    def __br_write__(self, br: BinaryReader, ref: ChunkReference,
                     name_indices: IterativeDict, chunk_map_dict: IterativeDict):
        br.write_uint32(name_indices[ref.name])
        br.write_uint32(chunk_map_dict[ref.chunk])


class BrChunkTable(BrStruct):
    # Set before write
    chunk_map_dict:    IterativeDict
    chunk_references:  list
    chunk_map_indices: list
    # Populated during write; consumed by BrXfbin to compute header field
    chunk_map_references_size: int

    def __br_read__(self, br: BinaryReader):
        self.chunk_type_count         = br.read_uint32()
        self.chunk_type_size          = br.read_uint32()
        self.file_path_count          = br.read_uint32()
        self.file_path_size           = br.read_uint32()
        self.chunk_name_count         = br.read_uint32()
        self.chunk_name_size          = br.read_uint32()
        self.chunk_map_count          = br.read_uint32()
        self.chunk_map_size           = br.read_uint32()
        self.chunk_map_indices_count  = br.read_uint32()
        self.chunk_map_references_count = br.read_uint32()

        self.chunk_types = [br.read_str() for _ in range(self.chunk_type_count)]
        self.file_paths  = [br.read_str() for _ in range(self.file_path_count)]
        self.chunk_names = [br.read_str() for _ in range(self.chunk_name_count)]
        br.align_pos(4)

        self.chunk_maps = list(br.read_struct(BrChunkMap, self.chunk_map_count))
        self.chunk_map_references = list(
            br.read_struct(BrChunkReference, self.chunk_map_references_count)
        )
        self.chunk_map_indices = list(
            br.read_uint32(self.chunk_map_indices_count)
            if self.chunk_map_indices_count else []
        )

    def get_props_from_chunk_map(self, chunk_map: BrChunkMap):
        return (
            self.chunk_types[chunk_map.chunk_type_index],
            self.file_paths[chunk_map.file_path_index],
            self.chunk_names[chunk_map.chunk_name_index],
        )

    def get_br_nucc_chunk(self, br_chunk: 'BrChunk', page_start: int) -> BrNuccChunk:
        global_idx = self.chunk_map_indices[page_start + br_chunk.chunk_map_index]
        type_str, fp, name = self.get_props_from_chunk_map(self.chunk_maps[global_idx])
        return BrNuccChunk.create_from_nucc_type(
            type_str, fp, name, br_chunk.data, br_chunk.nucc_id, br_chunk.unk
        )

    def __br_write__(self, br: BinaryReader):
        type_idx = IterativeDict()
        path_idx = IterativeDict()
        name_idx = IterativeDict()
        dict_tuple = (type_idx, path_idx, name_idx)

        with BinaryReader(endianness=Endian.BIG) as br_maps:
            # Write chunk maps
            for chunk in self.chunk_map_dict.keys():
                br_maps.write_struct(BrChunkMap(), (
                    NuccChunk.get_nucc_str_from_type(type(chunk)),
                    chunk.filePath,
                    chunk.name,
                ), dict_tuple)

            # Pre-register reference names so their indices are stable
            for ref in self.chunk_references:
                name_idx.get_or_next(ref.name)

            ref_start = br_maps.pos()
            for ref in self.chunk_references:
                br_maps.write_struct(BrChunkReference(), ref, name_idx, self.chunk_map_dict)
            self.chunk_map_references_size = br_maps.pos() - ref_start

            # Write global chunk-map index table
            br_maps.write_uint32(
                [self.chunk_map_dict[c] for c in self.chunk_map_indices]
            )
            maps_buf = br_maps.buffer()

        # Build string sections
        string_sizes = []
        with BinaryReader(endianness=Endian.BIG, encoding='cp932') as br_str:
            for d in dict_tuple:
                for s in d.keys():
                    br_str.write_str(s, null=True)
                string_sizes.append(br_str.size() - sum(string_sizes))
            br_str.align(4)
            str_buf = br_str.buffer()

        # Write counts/sizes header
        for i, d in enumerate(dict_tuple):
            br.write_uint32(len(d))
            br.write_uint32(string_sizes[i])
        br.write_uint32(len(self.chunk_map_dict))
        br.write_uint32(len(self.chunk_map_dict) * 3 * 4)
        br.write_uint32(len(self.chunk_map_indices))
        br.write_uint32(len(self.chunk_references))

        br.extend(str_buf)
        br.seek(len(str_buf), Whence.CUR)
        br.extend(maps_buf)
        br.seek(len(maps_buf), Whence.CUR)


# BrChunk (the envelope around each NuccChunk's binary data)
class BrChunk(BrStruct):
    def __br_read__(self, br: BinaryReader):
        self.size           = br.read_uint32()
        self.chunk_map_index = br.read_uint32()
        self.nucc_id        = br.read_uint16()
        self.unk            = br.read_uint16()
        self.data           = br.read_bytes(self.size)

    def __br_write__(self, br: BinaryReader, br_nucc: BrNuccChunk,
                     chunk_index_dict: IterativeDict, *args):
        with BinaryReader(endianness=Endian.BIG) as br_inner:
            chunk_idx = chunk_index_dict.get_or_next(br_nucc.nuccChunk)
            br_inner.write_struct(br_nucc, chunk_index_dict, *args)

            br.write_uint32(br_inner.size())
            br.write_uint32(chunk_idx)

            if hasattr(br_nucc.nuccChunk, 'nucc_version'):
                br.write_uint16(br_nucc.nuccChunk.nucc_version)
                br.write_uint16(0)
            else:
                br.write_uint16(0x79)
                br.write_uint16(0)

            br.extend(br_inner.buffer())
            br.seek(br_inner.size(), Whence.CUR)


# BrPage
class BrPage(BrStruct):
    chunk_index_dict: IterativeDict

    def __br_read__(self, br: BinaryReader, br_xfbin: BrXfbin):
        self.chunks_dict: Dict[int, BrNuccChunk] = {}

        while True:
            br_chunk = br.read_struct(BrChunk)
            chunk    = br_xfbin.chunk_table.get_br_nucc_chunk(
                br_chunk, br_xfbin.cur_page_start
            )
            self.chunks_dict[br_chunk.chunk_map_index] = chunk

            if isinstance(chunk, BrNuccChunkPage):
                self.page_chunk = chunk
                ps = br_xfbin.cur_page_start
                rs = br_xfbin.cur_reference_start
                self.page_chunk_indices = (
                    br_xfbin.chunk_table.chunk_map_indices[ps: ps + chunk.pageSize]
                )
                self.page_chunk_references = (
                    br_xfbin.chunk_table.chunk_map_references[rs: rs + chunk.referenceSize]
                )
                break

    def __br_write__(self, br: BinaryReader, page: Page):
        self.chunk_index_dict = IterativeDict()

        # Pre-populate index dict with chunks from no-props chunks' dependency list
        no_props = [c for c in page if not c.has_props]
        if no_props:
            self.chunk_index_dict.update_or_next(no_props[0].chunks)

        # Every page starts with a null chunk
        null           = BrNuccChunkNull()
        null.nuccChunk = NuccChunkNull()
        br.write_struct(BrChunk(), null, self.chunk_index_dict)

        for nucc_chunk in page:
            if isinstance(nucc_chunk, (NuccChunkNull, NuccChunkPage)):
                continue
            br_nucc: BrNuccChunk = (
                BrNuccChunk.get_br_nucc_type_from_str(type(nucc_chunk).__qualname__)()
                if nucc_chunk.has_props
                else BrNuccChunk()
            )
            br_nucc.nuccChunk = nucc_chunk
            br.write_struct(BrChunk(), br_nucc, self.chunk_index_dict)

        self.chunk_references: List[ChunkReference] = list(page.chunk_references)

        page_chunk           = BrNuccChunkPage()
        page_chunk.nuccChunk = NuccChunkPage()
        br.write_struct(BrChunk(), page_chunk,
                        self.chunk_index_dict, self.chunk_references)
