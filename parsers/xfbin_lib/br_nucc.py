from .binary_reader import BrStruct, BinaryReader, Endian, Whence
from .iterative_dict import IterativeDict

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
        br.write_uint16(0)
        br.write_uint16(nut.textures[0].width  if nut and nut.textures else 0)
        br.write_uint16(nut.textures[0].height if nut and nut.textures else 0)
        br.write_uint16(0)
        with BinaryReader(endianness=Endian.BIG) as br_inner:
            br_inner.write_struct(BrNut(), nut)
            br.write_uint32(br_inner.size())
            br.extend(br_inner.buffer())
            br.seek(br_inner.size(), Whence.CUR)


class BrNuccChunkBinary(BrNuccChunk):
    def init_data(self, br: BinaryReader):
        super().init_data(br)
        self.data_size   = br.read_uint32()
        self.binary_data = br.read_bytes(self.data_size)

    def __br_write__(self, br: BinaryReader, chunk_index_dict: IterativeDict):
        br.write_uint32(len(self.nuccChunk.binary_data))
        br.write_bytes(self.nuccChunk.binary_data)


# Populate registry
_BR_REGISTRY.update({
    'BrNuccChunkNull':    BrNuccChunkNull,
    'BrNuccChunkPage':    BrNuccChunkPage,
    'BrNuccChunkIndex':   BrNuccChunkIndex,
    'BrNuccChunkTexture': BrNuccChunkTexture,
    'BrNuccChunkBinary':  BrNuccChunkBinary,
})
