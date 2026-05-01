from typing import List


# Dynamic type registry
_NUCC_REGISTRY: dict = {}
_NUCC_DYNAMIC: dict = {}


def _dynamic_nucc_type(name: str) -> type:
    if name not in _NUCC_DYNAMIC:
        _NUCC_DYNAMIC[name] = type(name, (NuccChunk,), {})
    return _NUCC_DYNAMIC[name]


# Base NuccChunk
class NuccChunk:
    filePath: str
    name: str
    extension: str
    has_data: bool
    has_props: bool
    chunks: list
    data: bytearray

    def __init__(self, file_path: str = '', name: str = ''):
        self.filePath = file_path
        self.name = name
        self.extension = ''
        self.has_data = False
        self.has_props = False
        self.chunks = []
        self.data = None

    def set_data(self, data: bytearray, chunks):
        self.data = data
        self.has_data = True
        self.chunks = [c for c in chunks
                       if not isinstance(c, (NuccChunkPage, NuccChunkIndex))]

    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.data = br_chunk.data
        self.has_data = True
        self.chunks = [chunk_list[x] for x in chunk_indices
                       if not isinstance(chunk_list[x], (NuccChunkPage, NuccChunkIndex))]

    def get_data(self, file_data_only: bool = False):
        if file_data_only and hasattr(self, 'file_data'):
            return self.file_data
        return self.data

    @classmethod
    def get_nucc_type_from_str(cls, type_str: str) -> type:
        name = type_str[0].upper() + type_str[1:]
        return _NUCC_REGISTRY.get(name) or _dynamic_nucc_type(name)

    @classmethod
    def get_nucc_str_from_type(cls, nucc_type: type) -> str:
        return nucc_type.__name__[0].lower() + nucc_type.__name__[1:]

    @classmethod
    def create_from_nucc_type(cls, type_str: str, file_path: str, name: str) -> 'NuccChunk':
        return cls.get_nucc_type_from_str(type_str)(file_path, name)

    def __eq__(self, other) -> bool:
        return (isinstance(other, type(self))
                and self.filePath == other.filePath
                and self.name == other.name)

    def __hash__(self) -> int:
        return hash(type(self).__qualname__) ^ hash(self.filePath) ^ hash(self.name)


# Structural / metadata chunk types
class NuccChunkNull(NuccChunk):
    def __init__(self, file_path: str = '', name: str = ''):
        super().__init__(file_path, name)
        self.has_props = True


class NuccChunkPage(NuccChunk):
    def __init__(self, file_path: str = '', name: str = 'Page0'):
        super().__init__(file_path, name)
        self.has_props = True


class NuccChunkIndex(NuccChunk):
    def __init__(self, file_path: str = '', name: str = 'index'):
        super().__init__(file_path, name)
        self.has_props = True


# Data chunk types
class NuccChunkTexture(NuccChunk):
    def __init__(self, file_path: str = '', name: str = ''):
        super().__init__(file_path, name)
        self.data = None
        self.nut = None

    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.extension = '.nut'
        self.data = br_chunk.data
        self.has_data = True
        self.has_props = True
        self.width = br_chunk.width
        self.height = br_chunk.height
        from .nut import Nut
        self.nut = Nut()
        self.nut.init_data(br_chunk.brNut)


class NuccChunkBinary(NuccChunk):
    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.data = br_chunk.data
        self.has_data = True
        self.has_props = True
        self.extension = '.binary'
        self.binary_data = br_chunk.binary_data


# Populate registry
_NUCC_REGISTRY.update({
    'NuccChunkNull':    NuccChunkNull,
    'NuccChunkPage':    NuccChunkPage,
    'NuccChunkIndex':   NuccChunkIndex,
    'NuccChunkTexture': NuccChunkTexture,
    'NuccChunkBinary':  NuccChunkBinary,
})
