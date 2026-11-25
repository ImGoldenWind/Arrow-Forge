from .binary_reader import BinaryReader, Endian
from .br_xfbin import BrXfbin
from .nucc import NuccChunk
from .xfbin_types import Page, Xfbin, ChunkReference


def read_xfbin(path: str, *, preserve_source: bool = False) -> Xfbin:
    """Read an XFBIN file from disk and return an Xfbin object."""
    with open(path, 'rb') as fh:
        data = fh.read()

    with BinaryReader(data, Endian.BIG, 'cp932') as br:
        br_xfbin = br.read_struct(BrXfbin)

    table = br_xfbin.chunk_table

    # Build the flat chunk list in global-index order
    chunks = [
        NuccChunk.create_from_nucc_type(*table.get_props_from_chunk_map(m))
        for m in table.chunk_maps
    ]

    xfbin = Xfbin()
    xfbin.nucc_header = br_xfbin.header
    xfbin.initial_null_header = getattr(br_xfbin, 'initial_null_header', None)
    if preserve_source:
        from .source_writer import SourceLayout
        xfbin.source_layout = SourceLayout(data, br_xfbin)
        for index, chunk in enumerate(chunks):
            chunk.source_map_index = index
    reference_index = 0
    for page_index, br_page in enumerate(br_xfbin.pages):
        page = Page()
        if preserve_source:
            page.source_page_index = page_index
        page.nucc_envelopes = []

        # Populate initial_page_chunks (used by writer for page metadata)
        page.initial_page_chunks = [chunks[i] for i in br_page.page_chunk_indices]

        # Reconstruct ChunkReferences
        page.chunk_references = [
            ChunkReference(
                table.chunk_names[ref.chunk_name_index],
                chunks[ref.chunk_map_index],
            )
            for ref in br_page.page_chunk_references
        ]
        if preserve_source:
            for ref in page.chunk_references:
                ref.source_reference_index = reference_index
                reference_index += 1

        # Initialise each chunk with its parsed binary data
        for local_idx, br_nucc in br_page.chunks_dict.items():
            global_idx = br_page.page_chunk_indices[local_idx]
            chunk = chunks[global_idx]
            chunk.nucc_version = br_nucc.version
            chunk.nucc_unk = br_nucc.anmvalue
            # Null/Page objects can be shared across pages. Their envelope
            # metadata belongs to the individual occurrence, not that object.
            page.nucc_envelopes.append((chunk, br_nucc.version, br_nucc.anmvalue))
            chunk.init_data(br_nucc, chunks,
                            br_page.page_chunk_indices,
                            page.chunk_references)
            page.chunks.append(chunk)

        xfbin.pages.append(page)

    return xfbin
