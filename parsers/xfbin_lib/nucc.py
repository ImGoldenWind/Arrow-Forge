from enum import IntFlag
from typing import Iterator, List, Optional, Set


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


class NuccChunkDynamics(NuccChunk):
    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.data = br_chunk.data
        self.has_data = True
        self.has_props = True
        self.clump_chunk = chunk_list[chunk_indices[br_chunk.clumpChunkIndex]]
        sec1_shorts = iter(br_chunk.section1Shorts)
        self.section1 = []
        for sec1 in br_chunk.section1:
            item = Dynamics1()
            item.init_data(sec1, sec1_shorts)
            self.section1.append(item)
        self.section2 = []
        for sec2 in br_chunk.section2:
            item = Dynamics2()
            item.init_data(sec2)
            self.section2.append(item)


class Dynamics1:
    def init_data(self, sec1, sec1_shorts: Iterator[int]):
        self.floats = sec1.floats
        self.coord_index = sec1.coordIndex
        self.shorts = [next(sec1_shorts) for _ in range(sec1.unkCount)]


class Dynamics2:
    def init_data(self, sec2):
        self.floats = sec2.floats
        self.coord_index = sec2.coordIndex
        self.negative_unk = sec2.negativeUnk
        self.unk_short_tuples = list(sec2.unkShortTuples)


class NuccChunkClump(NuccChunk):
    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.data = br_chunk.data
        self.has_data = True
        self.has_props = True
        self.field00 = br_chunk.field00
        self.coord_flag0 = br_chunk.coordFlag0
        self.coord_flag1 = br_chunk.coordFlag1
        self.model_flag0 = br_chunk.modelFlag0
        self.model_flag1 = br_chunk.modelFlag1

        self.coord_chunks = [chunk_list[chunk_indices[i]] for i in br_chunk.coordNodeIndices]
        self.root_nodes = []
        for idx, parent_idx in enumerate(br_chunk.coordNodeParentsIndices):
            node = self.coord_chunks[idx].node
            if parent_idx == -1:
                self.root_nodes.append(node)
            else:
                parent = self.coord_chunks[parent_idx].node
                node.parent = parent
                parent.children.append(node)

        self.model_chunks = []
        for i in br_chunk.modelIndices:
            model = chunk_list[chunk_indices[i]]
            self.model_chunks.append(model)
            if isinstance(model, NuccChunkModel) and model.coord_index != -1:
                model.coord_chunk = self.coord_chunks[model.coord_index]

        self.model_groups = []
        for br_group in br_chunk.modelGroups:
            group = ClumpModelGroup()
            group.init_data(br_group, self.coord_chunks, chunk_list, chunk_indices)
            self.model_groups.append(group)

    def clear_non_model_chunks(self, model_list: bool = True, model_groups: bool = True, none_refs: bool = False) -> int:
        original = len(self.model_chunks) + sum(len(g.model_chunks) for g in self.model_groups)
        if model_list:
            self.model_chunks = [
                c for c in self.model_chunks
                if isinstance(c, NuccChunkModel) or (c is None and not none_refs)
            ]
        if model_groups:
            for group in self.model_groups:
                group.model_chunks = [
                    c for c in group.model_chunks
                    if isinstance(c, NuccChunkModel) or (c is None and not none_refs)
                ]
        return original - (len(self.model_chunks) + sum(len(g.model_chunks) for g in self.model_groups))


class ClumpModelGroup:
    def __init__(self):
        self.model_chunks = []

    def init_data(self, br_group, coord_chunks, chunk_list, chunk_indices):
        self.flag0 = br_group.flag0
        self.flag1 = br_group.flag1
        self.unk = br_group.unk
        self.model_chunks = [
            chunk_list[chunk_indices[i]] if i != -1 else None
            for i in br_group.modelIndices
        ]
        for chunk in self.model_chunks:
            if chunk and getattr(chunk, "coord_index", -1) != -1:
                chunk.coord_chunk = coord_chunks[chunk.coord_index]

    def __iter__(self):
        return iter(self.model_chunks)


class NuccChunkCoord(NuccChunk):
    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.data = br_chunk.data
        self.has_data = True
        self.has_props = True
        self.node = CoordNode(self)
        self.node.init_data(br_chunk)


class CoordNode:
    parent: Optional["CoordNode"]
    children: List["CoordNode"]

    def __init__(self, chunk: NuccChunkCoord):
        self.chunk = chunk
        self.name = chunk.name
        self.parent = None
        self.children = []
        self.position = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.unkFloat = 1.0
        self.unkShort = 0

    def init_data(self, coord):
        self.position = coord.position
        self.rotation = coord.rotation
        self.scale = coord.scale
        self.unkFloat = coord.unkFloat
        self.unkShort = coord.unkShort

    def get_children_recursive(self) -> List["CoordNode"]:
        result = []
        for child in self.children:
            result.append(child)
            result.extend(child.get_children_recursive())
        return result

    def copy_from(self, other: "CoordNode"):
        self.position = other.position
        self.rotation = other.rotation
        self.scale = other.scale
        self.unkFloat = other.unkFloat
        self.unkShort = other.unkShort


class NuccChunkModel(NuccChunk):
    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.extension = ".nud"
        self.data = br_chunk.data
        self.has_data = True
        self.has_props = True
        self.field00 = getattr(br_chunk, "field00", 1)
        self.rigging_flag = RiggingFlag(br_chunk.riggingFlag)
        self.material_flags = list(br_chunk.materialFlags)
        self.flag1_floats = br_chunk.flag1Floats if self.material_flags[1] & 0x04 else tuple()
        self.clump_chunk = chunk_list[chunk_indices[br_chunk.clumpIndex]]
        self.hit_chunk = chunk_list[chunk_indices[br_chunk.hitIndex]]
        self.coord_chunk = None
        self.coord_index = br_chunk.meshBoneIndex
        self.file_data = br_chunk.nud_data
        self.nud = None
        if br_chunk.brNud is not None:
            from .nud import Nud
            self.nud = Nud()
            self.nud.init_data(self.name, br_chunk.brNud)
        self.material_chunks = [chunk_list[chunk_indices[i]] for i in br_chunk.materialIndices]

    def copy_from(self, other: "NuccChunkModel"):
        if hasattr(other, "data"):
            self.data = other.data
        self.extension = other.extension
        self.field00 = other.field00
        self.rigging_flag = other.rigging_flag
        self.material_flags = other.material_flags
        self.flag1_floats = other.flag1_floats
        self.clump_chunk = other.clump_chunk
        if other.hit_chunk and not isinstance(other.hit_chunk, NuccChunkNull):
            self.hit_chunk = other.hit_chunk
        self.coord_chunk = other.coord_chunk
        self.coord_index = other.coord_index
        self.nud = other.nud
        self.material_chunks = other.material_chunks


class RiggingFlag(IntFlag):
    NULL = 0x0
    UNSKINNED = 0x01
    SKINNED = 0x02
    BODY = 0x04
    TEETH = 0x05
    FULL = 0x06
    BLUR = 0x10
    SHADOW = 0x20


class NuccChunkMaterial(NuccChunk):
    def init_data(self, br_chunk, chunk_list, chunk_indices, chunk_refs):
        self.data = br_chunk.data
        self.has_data = True
        self.has_props = True
        self.field02 = br_chunk.field02
        self.field04 = br_chunk.field04
        self.format = br_chunk.format
        self.floats = br_chunk.floats
        self.texture_groups = []
        for br_group in br_chunk.textureGroups:
            group = MaterialTextureGroup()
            group.init_data(br_group, chunk_list, chunk_indices)
            self.texture_groups.append(group)

    @staticmethod
    def float_count(fmt: int) -> int:
        from .br_nucc import BrNuccChunkMaterial
        return BrNuccChunkMaterial.float_count(fmt)

    def __iter__(self):
        textures: Set[NuccChunkTexture] = set()
        for group in self.texture_groups:
            textures.update(group.texture_chunks)
        return iter(textures)


class MaterialTextureGroup:
    def init_data(self, texture_group, chunk_list, chunk_indices):
        self.unk = texture_group.unk
        self.texture_chunks = [chunk_list[chunk_indices[i]] for i in texture_group.textureIndices]

    def __iter__(self):
        return iter(self.texture_chunks)


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
    'NuccChunkDynamics': NuccChunkDynamics,
    'NuccChunkClump': NuccChunkClump,
    'NuccChunkCoord': NuccChunkCoord,
    'NuccChunkModel': NuccChunkModel,
    'NuccChunkMaterial': NuccChunkMaterial,
    'NuccChunkBinary':  NuccChunkBinary,
})
