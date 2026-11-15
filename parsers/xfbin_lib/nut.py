from .br_nut import BrNut


class Nut:
    """High-level wrapper for a NTP3 NUT texture container."""

    def init_data(self, br_nut):
        if br_nut is None:
            self.magic         = 'NTP3'
            self.version       = 0x0100
            self.texture_count = 0
            self.textures      = []
            return
        self.magic         = br_nut.magic
        self.version       = br_nut.version
        self.header_template = br_nut.header_template
        self.texture_count = br_nut.texture_count
        self.textures      = []
        for br_tex in br_nut.textures:
            tex = NutTexture()
            tex.init_data(br_tex)
            self.textures.append(tex)

    def storage_key(self):
        return (self.magic, self.version, tuple(texture.storage_key() for texture in self.textures))


class NutTexture:
    """One texture entry inside a NUT container."""

    def init_data(self, br_tex):
        self.data_size      = br_tex.data_size
        self.header_size    = br_tex.header_size
        self.total_size     = self.data_size + self.header_size
        self.mipmap_count   = br_tex.mipmap_count
        self.pixel_format   = br_tex.pixel_format
        self.width          = br_tex.width
        self.height         = br_tex.height
        self.is_cube_map    = br_tex.is_cube_map
        self.cubemap_format = br_tex.cubemap_format
        if self.is_cube_map:
            self.cubemap_size  = br_tex.cubemap_size1
            self.cubemap_faces = br_tex.cubemap_faces
        else:
            self.cubemap_faces = None
        self.mipmaps      = br_tex.mipmaps
        self.texture_data = br_tex.texture_data
        self.hash_id = br_tex.hash_id
        self._raw_record = getattr(br_tex, '_raw_record', None)
        self._original_key = self.storage_key()

    def storage_key(self):
        return (self.width, self.height, self.pixel_format, self.mipmap_count,
                self.cubemap_format, getattr(self, 'hash_id', 0),
                self.texture_data, tuple(self.mipmaps) if isinstance(self.mipmaps, (tuple, list)) else self.mipmaps,
                tuple(getattr(self, 'cubemap_faces', None) or ()))
