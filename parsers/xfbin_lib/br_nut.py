import struct
from .binary_reader import BrStruct, BinaryReader, Endian, Whence


class BrNut(BrStruct):
    """Read/write the NTP3 NUT texture container."""

    def __br_read__(self, br: BinaryReader):
        self.magic = br.read_str(4)
        if self.magic != 'NTP3':
            raise ValueError(f'Invalid NUT magic: {self.magic!r}')
        self.version = br.read_uint16()
        self.texture_count = br.read_uint16()
        br.read_uint32(2)   # 8 bytes padding
        self.header_template = bytes(br.buffer()[:16])
        self.textures = list(br.read_struct(BrNutTexture, self.texture_count, self))

    def __br_write__(self, br: BinaryReader, nut):
        header = bytearray(getattr(nut, 'header_template', b'NTP3\x01\x00\x00\x00' + bytes(8)))
        struct.pack_into('>H', header, 6, len(nut.textures))
        br.write_bytes(bytes(header))
        for tex in nut.textures:
            br.write_struct(BrNutTexture(), tex)


class BrNutTexture(BrStruct):
    """Read/write one NUT texture entry (header + mipmap data)."""

    def __br_read__(self, br: BinaryReader, nut: BrNut):
        start = br.pos()
        self.total_size  = br.read_uint32()
        br.read_uint32()                        # padding
        self.data_size   = br.read_uint32()
        self.header_size = br.read_uint16()
        br.read_uint16()                        # padding
        br.read_uint8()
        self.mipmap_count  = br.read_uint8()
        br.read_uint8()
        self.pixel_format  = br.read_uint8()
        self.width         = br.read_uint16()
        self.height        = br.read_uint16()
        br.read_uint32()
        self.cubemap_format = br.read_uint32()
        self.is_cube_map    = bool(self.cubemap_format & 0x200)

        if nut.version < 0x200:
            self.data_offset = 0x10 + self.header_size
            br.read_uint32(4)
        else:
            self.data_offset = br.read_uint32(4)[0]

        if self.is_cube_map:
            sizes = br.read_uint32(4)
            self.cubemap_size1 = sizes[0]
            self.cubemap_size2 = sizes[1]

        if self.mipmap_count > 1:
            self.mipmap_sizes = br.read_uint32(self.mipmap_count)
            br.align_pos(16)

        # Skip eXt + GIDX sections (0x18 = 24 bytes)
        br.seek(0x18, Whence.CUR)
        self.hash_id = br.read_uint32()
        br.read_uint32()

        # Read texture data
        if self.is_cube_map:
            self.cubemap_faces = [br.read_bytes(self.cubemap_size1) for _ in range(6)]
            self.texture_data = b''.join(self.cubemap_faces)
            self.mipmaps = self.texture_data
        elif self.mipmap_count > 1:
            if sum(self.mipmap_sizes) != self.data_size:
                # Corrupted mipmap count – fall back to single mip
                self.texture_data = br.read_bytes(self.mipmap_sizes[0])
                self.mipmaps = self.texture_data
                self.data_size    = self.mipmap_sizes[0]
                self.mipmap_count = 1
                self.header_size  = 80
                self.total_size   = self.header_size + self.data_size
            else:
                self.mipmaps = [br.read_bytes(self.mipmap_sizes[i])
                                for i in range(self.mipmap_count)]
                self.texture_data = b''.join(self.mipmaps)
        else:
            self.mipmaps      = [br.read_bytes(self.data_size)]
            self.texture_data = self.mipmaps[0]
        self._raw_record = bytes(br.buffer()[start:start + self.total_size])

    def __br_write__(self, br: BinaryReader, nut_tex):
        if getattr(nut_tex, '_raw_record', None) is not None and nut_tex.storage_key() == nut_tex._original_key:
            br.write_bytes(nut_tex._raw_record)
            return
        start = br.pos()
        header = bytearray(getattr(nut_tex, '_header_template', None) or bytes(48))
        struct.pack_into('>I', header, 0, nut_tex.total_size)
        struct.pack_into('>I', header, 8, nut_tex.data_size)
        struct.pack_into('>H', header, 12, nut_tex.header_size)
        header[17], header[19] = nut_tex.mipmap_count, nut_tex.pixel_format
        struct.pack_into('>HH', header, 20, nut_tex.width, nut_tex.height)
        struct.pack_into('>I', header, 28, nut_tex.cubemap_format)
        br.write_bytes(bytes(header))

        if nut_tex.cubemap_format & 0x200:
            br.write_uint32(nut_tex.cubemap_size)
            br.write_uint32(nut_tex.cubemap_size)
            br.write_uint32(0)
            br.write_uint32(0)

        if nut_tex.mipmap_count > 1:
            for mip in nut_tex.mipmaps:
                br.write_uint32(len(mip))
            used = br.pos() - start
            if used % 0x10:
                br.write_bytes(b'\x00' * (0x10 - (used % 0x10)))

        extension = bytearray(getattr(nut_tex, '_extension_template', None) or (
            b'eXt\0' + struct.pack('>III', 0x20, 0x10, 0) + b'GIDX' + struct.pack('>III', 0x10, 0, 0)))
        struct.pack_into('>I', extension, 24, getattr(nut_tex, 'hash_id', 0))
        br.write_bytes(bytes(extension))

        # Texture data
        if nut_tex.is_cube_map:
            for face in nut_tex.cubemap_faces:
                br.write_bytes(face)
        elif nut_tex.mipmap_count > 1:
            for mip in nut_tex.mipmaps:
                br.write_bytes(mip)
        else:
            br.write_bytes(nut_tex.texture_data)
