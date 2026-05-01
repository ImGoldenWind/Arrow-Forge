from typing import List
from .nucc import NuccChunk, NuccChunkNull, NuccChunkPage


class ChunkReference:
    def __init__(self, name: str, chunk: NuccChunk):
        self.name  = name
        self.chunk = chunk


class Page:
    """One XFBIN page: an ordered list of NuccChunks with optional references."""

    def __init__(self):
        self.chunks:           List[NuccChunk]      = []
        self.chunk_references: List[ChunkReference] = []

    def __iter__(self):
        return iter(self.chunks)

    def add_chunk(self, chunk: NuccChunk):
        if chunk in self.chunks:
            self.chunks[self.chunks.index(chunk)] = chunk
        else:
            self.chunks.append(chunk)

    def cleanup(self):
        self.chunks = [c for c in self.chunks
                       if not isinstance(c, (NuccChunkNull, NuccChunkPage))]

    def clear(self):
        self.chunks.clear()


class Xfbin:
    """Top-level XFBIN object: a sequence of Pages."""

    def __init__(self):
        self.pages: List[Page] = []

    def __iter__(self):
        return iter(self.pages)
