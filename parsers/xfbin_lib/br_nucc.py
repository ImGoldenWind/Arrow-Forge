from .binary_reader import BrStruct, BinaryReader, Endian, Whence
from .iterative_dict import IterativeDict
from .br_anm import BrAnmClump, BrAnmCoordParent, BrAnmEntry

# Dynamic Br type registry
_BR_REGISTRY: dict = {}
_BR_DYNAMIC:  dict = {}


def _dynamic_br_type(name: str) -> type:
    if name not in _BR_DYNAMIC:
        _BR_DYNAMIC[name] = type(name, (BrNuccChunk,), {})
    return _BR_DYNAMIC[name]


# Base BrNuccChunk
class BrNuccChunk(BrStruct):
    """Binary representation of a NuccChunk; subclasses handle specific types."""

    # nuccChunk is set on the instance before write
    nuccChunk: object

    def __br_read__(self, br: BinaryReader, file_path, name, version, anmvalue):
        self.filePath  = file_path
        self.name      = name
        self.version   = version
        self.anmvalue  = anmvalue
        self.init_data(br)

    def init_data(self, br: BinaryReader):
        """Default: store the raw buffer (used for unknown chunk types)."""
        self.data = br.buffer()
        br.seek(0)

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        """Default: write raw data back unchanged."""
        br.extend(self.nuccChunk.data)
        br.seek(len(self.nuccChunk.data), Whence.CUR)
        chunk_index_dict.update_or_next(self.nuccChunk.chunks)

    @classmethod
    def get_br_nucc_type_from_str(cls, type_str: str) -> type:
        name = 'Br' + type_str[0].upper() + type_str[1:]
        return _BR_REGISTRY.get(name) or _dynamic_br_type(name)

    @classmethod
    def create_from_nucc_type(cls, type_str, file_path, name, data, version, anmvalue):
        br_type = cls.get_br_nucc_type_from_str(type_str)
        return BinaryReader(data, Endian.BIG).read_struct(
            br_type, None, file_path, name, version, anmvalue
        )


# Structural chunk types
class BrNuccChunkNull(BrNuccChunk):
    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        pass  # null chunk carries no data


class BrNuccChunkPage(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.pageSize      = br.read_uint32()
        self.referenceSize = br.read_uint32()

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict, chunk_references: list):
        br.write_uint32(len(chunk_index_dict) + 1)  # +1 for NuccChunkIndex
        br.write_uint32(len(chunk_references))


class BrNuccChunkIndex(BrNuccChunk):
    pass


# Data chunk types
class BrNuccChunkTexture(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.field00 = br.read_uint16()
        self.width   = br.read_uint16()
        self.height  = br.read_uint16()
        self.field06 = br.read_uint16()
        self.nutSize = br.read_uint32()
        try:
            from .br_nut import BrNut
            nut_data  = br.buffer()[br.pos(): br.pos() + self.nutSize]
            self.brNut = BinaryReader(nut_data, Endian.BIG).read_struct(BrNut)
        except Exception as exc:
            print(f'[xfbin_lib] Failed to parse NUT in chunk "{self.name}": {exc}')
            self.brNut = None

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        from .br_nut import BrNut
        nut = self.nuccChunk.nut
        chunk = self.nuccChunk
        if chunk.data is not None and getattr(chunk, '_original_nut_key', None) == nut.storage_key():
            br.write_bytes(bytes(chunk.data))
            return
        br.write_uint16(getattr(chunk, 'field00', 0))
        br.write_uint16(nut.textures[0].width  if nut and nut.textures else 0)
        br.write_uint16(nut.textures[0].height if nut and nut.textures else 0)
        br.write_uint16(getattr(chunk, 'field06', 0))
        with BinaryReader(endianness=Endian.BIG) as br_inner:
            br_inner.write_struct(BrNut(), nut)
            br.write_uint32(br_inner.size())
            br.extend(br_inner.buffer())
            br.seek(br_inner.size(), Whence.CUR)


class BrNuccChunkDynamics(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.section1Count = br.read_uint16()
        self.section2Count = br.read_uint16()
        self.clumpChunkIndex = br.read_uint32()
        self.section1 = br.read_struct(BrDynamics1, self.section1Count)
        self.section2 = br.read_struct(BrDynamics2, self.section2Count)
        self.section1Shorts = br.read_uint16(sum(sec.unkCount for sec in self.section1))

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        chunk = self.nuccChunk
        br.write_uint16(len(chunk.section1))
        br.write_uint16(len(chunk.section2))
        br.write_uint32(chunk_index_dict.get_or_next(chunk.clump_chunk))

        short_buf = BinaryReader(endianness=Endian.BIG)
        for sec1 in chunk.section1:
            br.write_struct(BrDynamics1(), sec1)
            short_buf.write_uint16(sec1.shorts)
        for sec2 in chunk.section2:
            br.write_struct(BrDynamics2(), sec2)
        br.extend(short_buf.buffer())
        br.seek(short_buf.size(), Whence.CUR)


class BrDynamics1(BrStruct):
    def __br_read__(self, br: BinaryReader):
        self.floats = br.read_float(4)
        self.coordIndex = br.read_uint16()
        self.unkCount = br.read_uint16()

    def __br_write__(self, br: BinaryReader, sec1):
        br.write_float(sec1.floats)
        br.write_uint16(sec1.coord_index)
        br.write_uint16(len(sec1.shorts))


class BrDynamics2(BrStruct):
    def __br_read__(self, br: BinaryReader):
        self.floats = br.read_float(6)
        self.coordIndex = br.read_uint16()
        self.unkCount = br.read_uint16()
        self.negativeUnk = br.read_int16()
        br.read_uint16()
        self.unkShortTuples = []
        for _ in range(self.unkCount):
            self.unkShortTuples.append(br.read_uint16(br.read_uint16()))

    def __br_write__(self, br: BinaryReader, sec2):
        br.write_float(sec2.floats)
        br.write_uint16(sec2.coord_index)
        br.write_uint16(len(sec2.unk_short_tuples))
        br.write_int16(sec2.negative_unk)
        br.write_uint16(0)
        for values in sec2.unk_short_tuples:
            br.write_uint16(len(values))
            br.write_uint16(values)


class BrNuccChunkClump(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.field00 = br.read_uint32()
        self.coordCount = br.read_uint16()
        self.coordFlag0 = br.read_uint8()
        self.coordFlag1 = br.read_uint8()
        self.coordNodeParentsIndices = br.read_int16(self.coordCount)
        self.coordNodeIndices = br.read_uint32(self.coordCount)
        self.modelCount = br.read_uint16()
        self.modelFlag0 = br.read_uint8()
        self.modelFlag1 = br.read_uint8()
        br.read_uint32()
        self.modelIndices = br.read_uint32(self.modelCount)
        self.modelGroups = []
        while True:
            model_group = br.read_struct(BrClumpModelGroup)
            if model_group.modelCount == -1 or br.eof():
                break
            self.modelGroups.append(model_group)

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        chunk = self.nuccChunk
        br.write_uint32(chunk.field00)
        br.write_uint16(len(chunk.coord_chunks))
        br.write_uint8(chunk.coord_flag0)
        br.write_uint8(chunk.coord_flag1)

        coord_dict = IterativeDict()
        coord_dict.update_or_next(chunk.coord_chunks)
        for coord in chunk.coord_chunks:
            br.write_int16(coord_dict[coord.node.parent.chunk] if coord.node.parent else -1)
        br.write_uint32(tuple(chunk_index_dict.get_or_next(c) for c in chunk.coord_chunks))

        br.write_uint16(len(chunk.model_chunks))
        br.write_uint8(chunk.model_flag0)
        br.write_uint8(chunk.model_flag1)
        br.write_uint32(0)
        br.write_uint32(tuple(chunk_index_dict.get_or_next(c) for c in chunk.model_chunks))
        for group in chunk.model_groups:
            br.write_struct(BrClumpModelGroup(), group, chunk_index_dict)
        br.write_int16(-1)


class BrClumpModelGroup(BrStruct):
    def __br_read__(self, br: BinaryReader) -> None:
        self.modelCount = br.read_int16()
        if self.modelCount != -1 and not br.eof():
            self.flag0 = br.read_uint8()
            self.flag1 = br.read_uint8()
            self.unk = br.read_int32()
            self.modelIndices = [br.read_int32() for _ in range(self.modelCount)]

    def __br_write__(self, br: BinaryReader, model_group, chunk_index_dict: IterativeDict):
        br.write_int16(len(model_group.model_chunks))
        br.write_uint8(model_group.flag0)
        br.write_uint8(model_group.flag1)
        br.write_int32(model_group.unk)
        br.write_int32(tuple(chunk_index_dict.get_or_next(c) if c else -1 for c in model_group.model_chunks))


class BrNuccChunkModel(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.field00 = br.read_uint16()
        self.riggingFlag = br.read_uint16()
        self.materialFlags = br.read_uint8(4)
        br.read_uint32()
        self.clumpIndex = br.read_uint32()
        self.hitIndex = br.read_uint32()

        nud_start = br.buffer().find(b"NDP3")
        if nud_start == -1:
            raise ValueError(f"Could not find NDP3 magic in model chunk: {self.name}")
        with br.seek_to(nud_start + 4):
            self.nudSize = br.read_uint32()

        self.meshBoneIndex = br.read_uint32()
        if self.meshBoneIndex != self.nudSize:
            br.read_uint32()
        else:
            self.meshBoneIndex = -1

        self.flag1Floats = tuple()
        if self.materialFlags[1] & 0x04:
            self.flag1Floats = br.read_float(6)

        br.seek(nud_start)
        self.nud_data = br.buffer()[br.pos(): br.pos() + self.nudSize]
        try:
            from .br_nud import BrNud
            self.brNud = BinaryReader(self.nud_data, Endian.BIG).read_struct(BrNud)
        except Exception as exc:
            print(f'[xfbin_lib] Failed to parse NUD in model "{self.name}": {exc}')
            self.brNud = None
        br.seek(self.nudSize, Whence.CUR)
        self.materialCount = br.read_uint16()
        self.materialIndices = br.read_uint32(self.materialCount)

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        from .br_nud import BrNud

        chunk = self.nuccChunk
        br.write_uint16(getattr(chunk, "field00", 1))
        br.write_uint16(int(chunk.rigging_flag))
        br.write_uint8(chunk.material_flags or (0, 0, 8, 3))
        br.write_uint32(0)
        br.write_uint32(chunk_index_dict.get_or_next(chunk.clump_chunk))
        br.write_uint32(chunk_index_dict.get_or_next(chunk.hit_chunk))
        # Unbound models omit the coordinate word: the reader recognizes
        # NUD size in this position. Writing zero silently attaches bone 0.
        if chunk.coord_index != -1:
            br.write_uint32(chunk.coord_index)

        with BinaryReader(endianness=Endian.BIG) as inner:
            inner.write_struct(BrNud(), chunk.nud)
            br.write_uint32(inner.size())
            if chunk.material_flags[1] & 0x04:
                br.write_float(chunk.flag1_floats)
            br.extend(inner.buffer())
            br.seek(inner.size(), Whence.CUR)

        br.write_uint16(len(chunk.material_chunks))
        br.write_uint32(tuple(chunk_index_dict.get_or_next(m) for m in chunk.material_chunks))


class BrNuccChunkMaterial(BrNuccChunk):
    @staticmethod
    def float_count(fmt: int) -> int:
        count = 0
        if fmt & 0x40:
            count += 1
        if fmt & 0x20:
            count += 1
        if fmt & 0x10:
            count += 2
        if fmt & 0x08:
            count += 4
        if fmt & 0x04:
            count += 4
        if fmt & 0x02:
            count += 4
        if fmt & 0x01:
            count += 4
        return count

    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.groupCount = br.read_uint16()
        self.field02 = br.read_uint8()
        br.read_uint8()
        self.field04 = br.read_float()
        br.read_uint8(3)
        self.format = br.read_uint8()
        self.floats = br.read_float(self.float_count(self.format))
        self.textureGroups = br.read_struct(BrMaterialTextureGroup, self.groupCount)

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        chunk = self.nuccChunk
        br.write_uint16(len(chunk.texture_groups))
        br.write_uint8(chunk.field02)
        br.write_uint8(0)
        br.write_float(chunk.field04)
        br.write_uint8([0] * 3)
        br.write_uint8(chunk.format if chunk.floats else 0)
        br.write_float(chunk.floats[: self.float_count(chunk.format)])
        for group in chunk.texture_groups:
            br.write_struct(BrMaterialTextureGroup(), group, chunk_index_dict)


class BrMaterialTextureGroup(BrStruct):
    def __br_read__(self, br: BinaryReader):
        self.textureCount = br.read_int16()
        br.read_uint16()
        self.unk = br.read_int32()
        self.textureIndices = br.read_uint32(self.textureCount)

    def __br_write__(self, br: BinaryReader, texture_group, chunk_index_dict: IterativeDict):
        br.write_uint16(len(texture_group.texture_chunks))
        br.write_uint16(0)
        br.write_int32(texture_group.unk)
        br.write_uint32(tuple(chunk_index_dict.get_or_next(t) for t in texture_group.texture_chunks))


class BrNuccChunkCoord(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.position = br.read_float(3)
        self.rotation = br.read_float(3)
        self.scale = br.read_float(3)
        self.unkFloat = br.read_float()
        self.unkShort = br.read_uint16()

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        node = self.nuccChunk.node
        br.write_float(node.position)
        br.write_float(node.rotation)
        br.write_float(node.scale)
        br.write_float(node.unkFloat)
        br.write_uint16(node.unkShort)


class BrNuccChunkBinary(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.data_size   = br.read_uint32()
        self.binary_data = br.read_bytes(self.data_size)

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        br.write_uint32(len(self.nuccChunk.binary_data))
        br.write_bytes(self.nuccChunk.binary_data)


class BrNuccChunkAnm(BrNuccChunk):
    """Animation chunk reader (frame units are hundredths of a frame)."""

    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.frame_count = br.read_uint32()
        self.frame_size = br.read_uint32() if self.version > 101 else 100
        self.entry_count = br.read_uint16()
        self.loop_flag = br.read_uint16()
        self.clump_count = br.read_uint16()
        self.other_entry_count = br.read_uint16()
        self.other_index_count = br.read_uint16()
        self.coord_count = br.read_uint16()
        self.clumps = br.read_struct(BrAnmClump, self.clump_count)
        self.other_entry_indices = br.read_uint32(self.other_entry_count + self.other_index_count)
        self.coord_parents = br.read_struct(BrAnmCoordParent, self.coord_count)
        self.entries = br.read_struct(BrAnmEntry, self.entry_count)


# Populate registry
_BR_REGISTRY.update({
    'BrNuccChunkNull':    BrNuccChunkNull,
    'BrNuccChunkPage':    BrNuccChunkPage,
    'BrNuccChunkIndex':   BrNuccChunkIndex,
    'BrNuccChunkTexture': BrNuccChunkTexture,
    'BrNuccChunkDynamics': BrNuccChunkDynamics,
    'BrNuccChunkClump': BrNuccChunkClump,
    'BrNuccChunkModel': BrNuccChunkModel,
    'BrNuccChunkMaterial': BrNuccChunkMaterial,
    'BrNuccChunkCoord': BrNuccChunkCoord,
    'BrNuccChunkBinary':  BrNuccChunkBinary,
    'BrNuccChunkAnm': BrNuccChunkAnm,
})
