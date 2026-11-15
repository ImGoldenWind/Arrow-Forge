import io
import copy
import os
import struct
import tempfile
from array import array
from PIL import Image

from .xfbin_lib import (
    read_xfbin as _read_xfbin,
    write_xfbin_to_path as _write_path,
    NuccChunkTexture, NuccChunkBinary, NuccChunkNull, NuccChunkPage,
    NutTexture, Nut,
    BrNut, BinaryReader, Endian,
)
from .xfbin_lib.xfbin_types import Page

# Pixel format constants
PF_NAMES = {
    0:  'DXT1',  1:  'DXT3',  2:  'DXT5',
    5:  'R8',    6:  'RGB5551', 7: 'RGBA4444', 8: 'RGB565',
    9:  'R8G8', 14:  'RGB888', 17: 'RGBA8888',
    21: 'BC4',  22:  'BC5',
}

# bytes-per-block / bytes-per-pixel helpers
_FOURCC_PF = {0, 1, 2, 21, 22}           # block-compressed
_BLOCK_BYTES = {0: 8, 1: 16, 2: 16, 21: 8, 22: 16}
_UNCOMPRESSED_BPP = {5: 1, 6: 2, 7: 2, 8: 2, 9: 2, 14: 4, 17: 4}


# NutTexture → PIL Image
def nut_tex_to_pil(tex: NutTexture, level: int = 0, face: int = 0) -> Image.Image | None:
    """Decode the first mipmap of a NutTexture to a PIL RGBA image."""
    if level or getattr(tex, 'is_cube_map', False):
        plane = copy.copy(tex)
        plane.width, plane.height = max(1, tex.width >> level), max(1, tex.height >> level)
        if not 0 <= level < (tex.mipmap_count or 1):
            return None
        if getattr(tex, 'is_cube_map', False):
            faces = getattr(tex, 'cubemap_faces', None)
            if not faces or not 0 <= face < len(faces):
                return None
            offset = sum(mip_byte_size(tex.pixel_format, max(1, tex.width >> n), max(1, tex.height >> n))
                         for n in range(level))
            data = faces[face][offset:offset + mip_byte_size(tex.pixel_format, plane.width, plane.height)]
        else:
            if not isinstance(tex.mipmaps, (tuple, list)) or level >= len(tex.mipmaps):
                return None
            data = tex.mipmaps[level]
        plane.is_cube_map = False
        plane.mipmap_count, plane.mipmaps, plane.texture_data = 1, [data], data
        return nut_tex_to_pil(plane)
    fmt = tex.pixel_format
    w, h = tex.width, tex.height
    if w <= 0 or h <= 0 or w * h > Image.MAX_IMAGE_PIXELS:
        return None
    data = tex.mipmaps[0] if tex.mipmaps else tex.texture_data
    try:
        if fmt in _FOURCC_PF:
            dds_bytes = _nut_tex_to_dds_bytes(tex)
            img = Image.open(io.BytesIO(dds_bytes))
            return img.convert('RGBA')

        if fmt == 6:   # RGB5551
            arr = array('H', data); arr.byteswap()
            return Image.frombytes('RGBA', (w, h), arr.tobytes(), 'raw', 'BGRA;15')

        if fmt == 7:   # RGBA4444
            arr = array('H', data); arr.byteswap()
            img = Image.frombytes('RGBA', (w, h), arr.tobytes(), 'raw', 'RGBA;4B')
            r, g, b, a = img.split()
            return Image.merge('RGBA', (b, g, r, a))

        if fmt == 8:   # RGB565
            arr = array('H', data); arr.byteswap()
            return Image.frombytes('RGB', (w, h), arr.tobytes(), 'raw', 'BGR;16').convert('RGBA')

        if fmt in (14, 17):  # XRGB / RGBA8888 (NUT stores as ARGB)
            needed = w * h * 4
            chunk = data[:needed]
            img = Image.frombytes('RGBA', (w, h), chunk, 'raw')
            r, g, b, a = img.split()
            return Image.merge('RGBA', (g, b, a, Image.new('L', (w, h), 255) if fmt == 14 else r))

        if fmt == 9:   # R8G8
            needed = w * h * 2
            arr = array('H', data[:needed])
            return Image.frombytes('LA', (w, h), arr.tobytes(), 'raw', 'LA').convert('RGBA')

        if fmt == 5:   # R8
            return Image.frombytes('L', (w, h), data[:w * h], 'raw', 'L').convert('RGBA')

    except Exception:
        pass
    return None


# NutTexture → raw DDS bytes
_FOURCC_STR = {0: b'DXT1', 1: b'DXT3', 2: b'DXT5', 21: b'ATI1', 22: b'ATI2'}

def _nut_tex_to_dds_bytes(tex: NutTexture) -> bytes:
    fmt = tex.pixel_format
    w, h = tex.width, tex.height
    mips = tex.mipmap_count or 1

    if getattr(tex, 'is_cube_map', False):
        raise ValueError('DDS export of cubemaps is not supported; the original NUT is retained.')
    if fmt not in _FOURCC_PF:
        images = [nut_tex_to_pil(tex, n) for n in range(mips)]
        if any(img is None for img in images):
            raise ValueError('Cannot decode this pixel format for DDS export.')
        return rgba_to_dds(images)
    pitch = mip_byte_size(fmt, w, h)

    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000      # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
    if mips > 1:
        flags |= 0x20000                              # MIPMAPCOUNT

    buf = bytearray()
    buf += b'DDS '
    buf += struct.pack('<IIIIIII', 124, flags, h, w, pitch, 1, mips)
    buf += b'\x00' * 44                              # reserved[11]

    # DDSPF
    fourcc_bytes = _FOURCC_STR.get(fmt, b'DXT5')
    buf += struct.pack('<II4sIIIII', 32, 0x4, fourcc_bytes, 0, 0, 0, 0, 0)

    caps1 = 0x1000
    if mips > 1:
        caps1 |= 0x400000 | 0x8
    buf += struct.pack('<IIIII', caps1, 0, 0, 0, 0)

    levels = tex.mipmaps if isinstance(tex.mipmaps, (list, tuple)) else [tex.texture_data]
    if len(levels) < mips:
        raise ValueError('Missing NUT mip data')
    for level in range(mips):
        size = mip_byte_size(fmt, max(1, w >> level), max(1, h >> level))
        if len(levels[level]) < size:
            raise ValueError('NUT mip is smaller than a complete DDS block grid')
        buf += levels[level][:size]
    return bytes(buf)


# DDS file → NutTexture
_DDS_FOURCC_TO_PF = {
    b'DXT1': 0, b'DXT3': 1, b'DXT5': 2,
    b'ATI1': 21, b'BC4U': 21,
    b'ATI2': 22, b'BC5U': 22,
}


def mip_byte_size(fmt, width, height):
    if fmt in _BLOCK_BYTES:
        return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * _BLOCK_BYTES[fmt]
    if fmt not in _UNCOMPRESSED_BPP:
        raise ValueError(f'Unsupported pixel format: {fmt}')
    return width * height * _UNCOMPRESSED_BPP[fmt]


def rgba_to_dds(images):
    """Standard uncompressed little-endian RGBA DDS, with the supplied mip chain."""
    w, h = images[0].size
    count = len(images)
    flags = 0x100F | (0x20000 if count > 1 else 0)
    header = struct.pack('<7I', 124, flags, h, w, w * 4, 0, count) + bytes(44)
    header += struct.pack('<8I', 32, 0x41, 0, 32, 0xff, 0xff00, 0xff0000, 0xff000000)
    header += struct.pack('<5I', 0x1000 | (0x400008 if count > 1 else 0), 0, 0, 0, 0)
    return b'DDS ' + header + b''.join(image.convert('RGBA').tobytes() for image in images)

def dds_to_nut_texture(data: bytes) -> NutTexture:
    data = bytes(data)
    if len(data) < 128 or data[:4] != b'DDS ' or struct.unpack_from('<I', data, 4)[0] != 124:
        raise ValueError('Not a DDS file')

    h_val   = struct.unpack_from('<I', data, 12)[0]
    w_val   = struct.unpack_from('<I', data, 16)[0]
    mips    = struct.unpack_from('<I', data, 28)[0] or 1
    pf_flags = struct.unpack_from('<I', data, 80)[0]
    fourcc  = data[84:88]
    rgb_bits = struct.unpack_from('<I', data, 88)[0]
    if struct.unpack_from('<I', data, 76)[0] != 32:
        raise ValueError('Invalid DDS pixel format header')

    if not (0 < w_val <= 65535 and 0 < h_val <= 65535) or w_val * h_val > Image.MAX_IMAGE_PIXELS:
        raise ValueError('Invalid or excessively large DDS dimensions')
    if mips > max(w_val, h_val).bit_length():
        raise ValueError('DDS mip count exceeds its dimensions')
    if struct.unpack_from('<I', data, 112)[0] & 0x20FE00 or struct.unpack_from('<I', data, 24)[0] > 1:
        raise ValueError('DDS cubemaps and volume textures cannot replace a 2D texture')

    texture_body = data[128:]

    if pf_flags & 0x4:   # DDPF_FOURCC
        if fourcc not in _DDS_FOURCC_TO_PF:
            raise ValueError(f'Unsupported DDS compression: {fourcc!r}')
        pixel_format = _DDS_FOURCC_TO_PF[fourcc]
    else:
        # Decode the actual channel masks, including every mip, into NUT ARGB.
        import numpy as np
        masks = struct.unpack_from('<4I', data, 92)
        if not pf_flags & 1:
            masks = (*masks[:3], 0)
        if not pf_flags & 0x40 or rgb_bits not in (16, 24, 32) or not all(masks[:3]):
            raise ValueError('Unsupported DDS pixel layout')
        used = 0
        for mask in masks:
            if mask & used or mask >> rgb_bits:
                raise ValueError('Overlapping or invalid DDS channel masks')
            used |= mask
            if mask:
                shifted = mask >> ((mask & -mask).bit_length() - 1)
                if shifted & (shifted + 1):
                    raise ValueError('Non-contiguous DDS channel mask')
        converted, offset = [], 0
        for level in range(mips):
            mw, mh = max(1, w_val >> level), max(1, h_val >> level)
            row_size = mw * (rgb_bits // 8)
            pitch = struct.unpack_from('<I', data, 20)[0] if level == 0 and struct.unpack_from('<I', data, 8)[0] & 8 else row_size
            if pitch < row_size or offset + pitch * mh > len(texture_body):
                raise ValueError('Truncated DDS pixel data')
            raw = np.frombuffer(texture_body[offset:offset + pitch * mh], dtype=np.uint8).reshape(mh, pitch)[:, :row_size]
            octets = raw.reshape(mh, mw, rgb_bits // 8).astype(np.uint32)
            values = sum(octets[:, :, n] << (8 * n) for n in range(rgb_bits // 8))
            channels = []
            for mask in masks:
                if not mask:
                    channels.append(np.full((mh, mw), 255, dtype=np.uint8))
                else:
                    shift = (mask & -mask).bit_length() - 1
                    channels.append((((values & mask) >> shift).astype(np.uint64) * 255 // (mask >> shift)).astype(np.uint8))
            converted.append(np.stack([channels[3], *channels[:3]], axis=2).tobytes())
            offset += pitch * mh
        texture_body = b''.join(converted)
        pixel_format = 17

    # Split into mipmaps
    mipmaps = []
    offset = 0
    mw, mh = w_val, h_val
    for _ in range(mips):
        if pixel_format in _FOURCC_PF:
            bsz = _BLOCK_BYTES[pixel_format]
            sz = max(1, (mw + 3) // 4) * max(1, (mh + 3) // 4) * bsz
        else:
            bpp = _UNCOMPRESSED_BPP.get(pixel_format, 4)
            sz = mw * mh * bpp
        chunk = texture_body[offset: offset + sz]
        if len(chunk) != sz:
            raise ValueError('Truncated DDS mip data')
        mipmaps.append(chunk + bytes((-len(chunk)) % 16))
        offset += sz
        mw = max(1, mw // 2)
        mh = max(1, mh // 2)

    tex = NutTexture()
    tex.width        = w_val
    tex.height       = h_val
    tex.pixel_format = pixel_format
    tex.mipmap_count = mips
    tex.is_cube_map  = False
    tex.cubemap_format = 0
    tex.mipmaps      = mipmaps
    tex.texture_data = b''.join(mipmaps)
    tex.data_size    = len(tex.texture_data)
    tex.header_size  = 48
    if mips > 1:
        tex.header_size = 48 + ((mips * 4 + 15) // 16) * 16
    tex.header_size += 32   # eXt + GIDX sections
    tex.total_size   = tex.data_size + tex.header_size
    return tex


# PIL Image → NutTexture (RGBA8888)
def pil_to_nut_texture_rgba(img: Image.Image, mip_count: int = 1) -> NutTexture:
    """Encode a PIL image as NutTexture RGBA8888 (pixel_format=17)."""
    img = img.convert('RGBA')
    w, h = img.size
    if not (0 < w <= 65535 and 0 < h <= 65535):
        raise ValueError('NUT dimensions must fit unsigned 16-bit fields')
    mip_count = max(1, min(mip_count, max(w, h).bit_length()))
    images = [img]
    for level in range(1, mip_count):
        images.append(img.resize((max(1, w >> level), max(1, h >> level)), Image.Resampling.LANCZOS))
    mipmaps = []
    for image in images:
        r, g, b, a = image.split()
        encoded = Image.merge('RGBA', (a, r, g, b)).tobytes()
        mipmaps.append(encoded + bytes((-len(encoded)) % 16))
    # NUT ARGB order: decoding does Image.merge(RGBA, (g,b,a,r)) so storage is ARGB
    texture_data = b''.join(mipmaps)

    tex = NutTexture()
    tex.width        = w
    tex.height       = h
    tex.pixel_format = 17
    tex.mipmap_count = mip_count
    tex.is_cube_map  = False
    tex.cubemap_format = 0
    tex.mipmaps      = mipmaps
    tex.texture_data = texture_data
    tex.data_size    = len(texture_data)
    tex.header_size  = 80 + (((mip_count * 4 + 15) // 16) * 16 if mip_count > 1 else 0)
    tex.total_size   = tex.data_size + tex.header_size
    return tex


# TextureEntry data class
class TextureEntry:
    """One texture item extracted from an xfbin."""
    __slots__ = ('name', 'file_path', 'tex_type',
                 'width', 'height', 'pixel_format', 'mipmap_count',
                 'chunk', '_pil_image', '_decoded', '_orig_pil', 'page_idx')

    def __init__(self):
        self.name:          str = ''
        self.file_path:     str = ''
        self.tex_type:      str = 'nut'   # 'nut' | 'dds' | 'png'
        self.width:         int = 0
        self.height:        int = 0
        self.pixel_format:  int = 0
        self.mipmap_count:  int = 1
        self.chunk         = None   # NuccChunkTexture or NuccChunkBinary
        self._pil_image:    Image.Image | None = None
        self._decoded = True
        self._orig_pil:     Image.Image | None = None
        self.page_idx:      int = -1

    @property
    def pil_image(self):
        if not self._decoded:
            self._decoded = True
            if self.tex_type == 'nut':
                textures = getattr(getattr(self.chunk, 'nut', None), 'textures', ())
                self._pil_image = nut_tex_to_pil(textures[0]) if textures else None
            else:
                try:
                    self._pil_image = Image.open(io.BytesIO(self.chunk.binary_data)).convert('RGBA')
                except Exception:
                    self._pil_image = None
        return self._pil_image

    @pil_image.setter
    def pil_image(self, image):
        self._pil_image, self._decoded = image, True

    @property
    def format_name(self) -> str:
        if self.tex_type in ('dds', 'png'):
            return self.tex_type.upper()
        return PF_NAMES.get(self.pixel_format, f'PF{self.pixel_format}')

    @property
    def size_str(self) -> str:
        return f'{self.width}×{self.height}'


def entry_image(entry, level=0, face=0):
    """Decode an authored level; missing/corrupt levels are never synthesized."""
    if level == 0 and face == 0:
        return entry.pil_image
    if entry.tex_type == 'nut':
        textures = getattr(getattr(entry.chunk, 'nut', None), 'textures', ())
        return nut_tex_to_pil(textures[0], level, face) if textures else None
    if entry.tex_type == 'dds' and level:
        try:
            return nut_tex_to_pil(dds_to_nut_texture(entry.chunk.binary_data), level)
        except ValueError:
            return None
    return entry.pil_image if level == 0 else None


def entry_editable(entry):
    textures = getattr(getattr(entry.chunk, 'nut', None), 'textures', ())
    nut = getattr(entry.chunk, 'nut', None)
    return entry.pil_image is not None and not (textures and getattr(textures[0], 'is_cube_map', False)) and (
        nut is None or nut.version == 0x100)


# Load xfbin
def load_xfbin(path: str, *, decode_images=True):
    """Read an xfbin and return (Xfbin, [TextureEntry])."""
    xfbin = _read_xfbin(path)
    entries: list[TextureEntry] = []

    for page_idx, page in enumerate(xfbin.pages):
        for chunk in page.chunks:
            entry = _chunk_to_entry(chunk, page_idx, decode_images=decode_images)
            if entry:
                entries.append(entry)

    return xfbin, entries


def _chunk_to_entry(chunk, page_idx: int, *, decode_images=True) -> 'TextureEntry | None':
    if isinstance(chunk, NuccChunkTexture) and chunk.nut:
        e = TextureEntry()
        e.name      = chunk.name
        e.file_path = chunk.filePath
        e.tex_type  = 'nut'
        e.chunk     = chunk
        e.page_idx  = page_idx
        nut = chunk.nut
        if nut.textures:
            t = nut.textures[0]
            e.width        = t.width
            e.height       = t.height
            e.pixel_format = t.pixel_format
            e.mipmap_count = t.mipmap_count
            e._decoded = False
            if decode_images:
                e.pil_image  # Decode on demand, sharing the same decoder.
        return e

    if isinstance(chunk, NuccChunkBinary) and hasattr(chunk, 'binary_data'):
        data = chunk.binary_data
        if not data or len(data) < 4:
            return None
        e = TextureEntry()
        e.name      = chunk.name
        e.file_path = chunk.filePath
        e.chunk     = chunk
        e.page_idx  = page_idx

        if data[:4] == b'DDS ':
            e.tex_type = 'dds'
            if len(data) >= 128:
                e.height = struct.unpack_from('<I', data, 12)[0]
                e.width  = struct.unpack_from('<I', data, 16)[0]
                e.mipmap_count = struct.unpack_from('<I', data, 28)[0] or 1
                pf_flags = struct.unpack_from('<I', data, 80)[0]
                fourcc   = data[84:88]
                if pf_flags & 0x4:
                    e.pixel_format = _DDS_FOURCC_TO_PF.get(fourcc, 2)
            e._decoded = False
            if decode_images:
                e.pil_image
            return e

        if data[:4] == b'\x89PNG':
            e.tex_type = 'png'
            try:
                img = Image.open(io.BytesIO(data))
                e.width, e.height = img.size
                e._decoded = False
                if decode_images:
                    e.pil_image
            except Exception:
                pass
            return e

    return None


# Save xfbin
def save_xfbin(xfbin, path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix='.arrowforge-texture-', dir=directory)
    os.close(fd)
    try:
        _write_path(xfbin, temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh_texture_entries(xfbin, *, decode_images=True) -> list[TextureEntry]:
    """Rebuild TextureEntry wrappers from the current XFBIN object."""
    entries: list[TextureEntry] = []
    for page_idx, page in enumerate(xfbin.pages):
        for chunk in page.chunks:
            entry = _chunk_to_entry(chunk, page_idx, decode_images=decode_images)
            if entry:
                entries.append(entry)
    return entries


def add_texture_from_file(xfbin, import_path: str, template_entry: TextureEntry | None = None) -> TextureEntry:
    """Import an external image/DDS/NUT as a new NuccChunkTexture page."""
    new_tex = _texture_from_file(import_path)
    base_name = os.path.splitext(os.path.basename(import_path))[0] or 'new_texture'
    name = _unique_texture_name(refresh_texture_entries(xfbin, decode_images=False), base_name)
    file_path = _make_texture_file_path(name, template_entry)

    new_chunk = NuccChunkTexture(file_path, name)
    new_chunk.has_props = True
    new_chunk.extension = '.nut'

    nut = Nut()
    nut.magic = 'NTP3'
    nut.version = 0x0100
    nut.textures = [new_tex]
    nut.texture_count = 1
    new_chunk.nut = nut

    page = Page()
    page.chunks.append(new_chunk)
    xfbin.pages.append(page)

    entry = _chunk_to_entry(new_chunk, len(xfbin.pages) - 1)
    if entry is None:
        raise ValueError('Imported file did not produce a valid texture entry')
    return entry


def duplicate_texture_entry(xfbin, entry: TextureEntry) -> TextureEntry:
    """Clone an existing texture entry into a new page and return its wrapper."""
    new_chunk = _clone_chunk(entry)
    if new_chunk is None:
        raise ValueError('Could not duplicate this texture')

    entries = refresh_texture_entries(xfbin, decode_images=False)
    new_name = _unique_texture_name(entries, f"{entry.name}_copy")
    new_chunk.name = new_name
    new_chunk.filePath = _make_texture_file_path(new_name, entry)

    page = Page()
    page.chunks.append(new_chunk)
    xfbin.pages.append(page)

    new_entry = _chunk_to_entry(new_chunk, len(xfbin.pages) - 1)
    if new_entry is None:
        raise ValueError('Duplicated chunk did not produce a valid texture entry')
    return new_entry


def delete_texture_entry(xfbin, entry: TextureEntry) -> bool:
    """Remove a texture chunk from the XFBIN. Returns True if removed."""
    chunk = entry.chunk
    if chunk is None:
        return False

    for page in xfbin.pages:
        page.chunk_references = [
            ref for ref in page.chunk_references
            if getattr(ref, 'chunk', None) is not chunk
        ]

    for page in list(xfbin.pages):
        if chunk not in page.chunks:
            continue
        page.chunks.remove(chunk)
        if len(xfbin.pages) > 1 and not _page_has_data_chunks(page):
            xfbin.pages.remove(page)
        return True
    return False


def _texture_from_file(import_path: str) -> NutTexture:
    with open(import_path, 'rb') as f:
        data = f.read()

    ext = os.path.splitext(import_path)[1].lower()

    if ext == '.dds' or data[:4] == b'DDS ':
        tex = dds_to_nut_texture(data)
        if tex.pixel_format in (21, 22):
            raise ValueError('BC4/BC5 import into PC NTP3 is not supported')
        return tex

    if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.tga') or data[:4] == b'\x89PNG':
        img = Image.open(io.BytesIO(data)).convert('RGBA')
        return pil_to_nut_texture_rgba(img)

    if ext == '.nut':
        with BinaryReader(data, Endian.BIG) as br:
            br_nut = br.read_struct(BrNut)
        nut = Nut()
        nut.init_data(br_nut)
        if not nut.textures:
            raise ValueError('NUT file contains no textures')
        if nut.version != 0x100 or len(nut.textures) != 1 or nut.textures[0].is_cube_map:
            raise ValueError('Import requires a version 0x100 NUT containing one 2D texture')
        return copy.deepcopy(nut.textures[0])

    raise ValueError(f'Unsupported format: {ext}')


def _unique_texture_name(entries: list[TextureEntry], base_name: str) -> str:
    existing = {e.name.lower() for e in entries}
    candidate = base_name
    counter = 1
    while candidate.lower() in existing:
        candidate = f"{base_name}_{counter}"
        counter += 1
    return candidate


def _make_texture_file_path(name: str, template_entry: TextureEntry | None) -> str:
    if template_entry and template_entry.file_path:
        directory = os.path.dirname(template_entry.file_path).replace('\\', '/')
        ext = os.path.splitext(template_entry.file_path)[1] or '.nut'
        return f"{directory}/{name}{ext}" if directory else f"{name}{ext}"
    return f"{name}.nut"


def _page_has_data_chunks(page: Page) -> bool:
    return any(not isinstance(c, (NuccChunkNull, NuccChunkPage)) for c in page.chunks)


# Replace texture from external file
def replace_texture_from_file(entry: TextureEntry, import_path: str) -> str | None:
    """Replace the texture in-place. Returns an error string or None on success."""
    try:
        with open(import_path, 'rb') as f:
            data = f.read()
        ext = os.path.splitext(import_path)[1].lower()
        if ext == '.dds' or data[:4] == b'DDS ':
            new_tex = dds_to_nut_texture(data)
            _apply_nut_texture_to_entry(entry, new_tex, data)
            return None

        elif ext in ('.png', '.jpg', '.jpeg', '.bmp', '.tga') or data[:4] == b'\x89PNG':
            img = Image.open(io.BytesIO(data)).convert('RGBA')
            new_tex = pil_to_nut_texture_rgba(img)
            _apply_nut_texture_to_entry(entry, new_tex, None)
            entry.pil_image = img.copy()
            entry._orig_pil  = img.copy()
            return None

        elif ext == '.nut':
            with BinaryReader(data, Endian.BIG) as br:
                br_nut = br.read_struct(BrNut)
            nut = Nut()
            nut.init_data(br_nut)
            if not nut.textures:
                return 'NUT file contains no textures'
            if nut.version != 0x100 or len(nut.textures) != 1 or nut.textures[0].is_cube_map:
                return 'Replacement requires a version 0x100 NUT containing one 2D texture'
            new_tex = nut.textures[0]
            _apply_nut_texture_to_entry(entry, new_tex, None)
            return None

        else:
            return f'Unsupported format: {ext}'

    except Exception as exc:
        return str(exc)


def _apply_nut_texture_to_entry(entry: TextureEntry, new_tex: NutTexture, raw_data):
    """Write new_tex back into the chunk and refresh the entry's metadata."""
    chunk = entry.chunk
    if isinstance(chunk, NuccChunkTexture):
        if chunk.nut and chunk.nut.version != 0x100:
            raise ValueError('Editing this NUT version is not supported; original data is retained.')
        if chunk.nut and chunk.nut.textures and getattr(chunk.nut.textures[0], 'is_cube_map', False):
            raise ValueError('A cubemap cannot be replaced by a 2D image.')
        if getattr(new_tex, 'is_cube_map', False):
            raise ValueError('Importing a cubemap as a 2D texture is not supported.')
        if new_tex.pixel_format in (21, 22):
            raise ValueError('BC4/BC5 are not established NTP3 formats in this PC build. Import a PNG or DXT1/3/5 DDS.')
        if chunk.nut and chunk.nut.textures:
            old = chunk.nut.textures[0]
            new_tex.hash_id = getattr(old, 'hash_id', 0)
            raw = getattr(old, '_raw_record', None)
            new_tex._header_template = raw[:48] if raw else getattr(old, '_header_template', None)
            new_tex._extension_template = raw[old.header_size - 32:old.header_size] if raw else getattr(old, '_extension_template', None)
            new_tex.cubemap_format = old.cubemap_format
        if chunk.nut and chunk.nut.textures:
            chunk.nut.textures[0] = new_tex
        else:
            nut = Nut()
            nut.textures = [new_tex]
            nut.magic = 'NTP3'
            nut.version = 0x0100
            nut.texture_count = 1
            chunk.nut = nut
        entry.tex_type     = 'nut'
        entry.width        = new_tex.width
        entry.height       = new_tex.height
        entry.pixel_format = new_tex.pixel_format
        entry.mipmap_count = new_tex.mipmap_count
        img = nut_tex_to_pil(new_tex)
        entry.pil_image    = img
        entry._orig_pil    = img.copy() if img else None

    elif isinstance(chunk, NuccChunkBinary):
        img = nut_tex_to_pil(new_tex)
        if img is None:
            raise ValueError('Cannot decode replacement texture')
        if entry.tex_type == 'png':
            buffer = io.BytesIO()
            img.save(buffer, 'PNG')
            chunk.binary_data = buffer.getvalue()
        else:
            chunk.binary_data = raw_data if raw_data and raw_data[:4] == b'DDS ' else _nut_tex_to_dds_bytes(new_tex)
        entry.width, entry.height = new_tex.width, new_tex.height
        entry.pixel_format = new_tex.pixel_format
        entry.mipmap_count = new_tex.mipmap_count if entry.tex_type == 'dds' else 1
        entry.pil_image, entry._orig_pil = img, img.copy()
    else:
        raise ValueError('Unsupported texture chunk')


# Apply PIL edits back to texture
def apply_pil_edits_to_entry(entry: TextureEntry, edited_img: Image.Image, *, rebuild_mips=True) -> str | None:
    """
    Write an edited PIL Image back to the chunk as RGBA8888.
    The original format may change to RGBA8888 for block-compressed textures.
    Returns an error string or None on success.
    """
    try:
        new_tex = pil_to_nut_texture_rgba(edited_img, entry.mipmap_count if rebuild_mips else 1)
        _apply_nut_texture_to_entry(entry, new_tex, None)
        entry.pil_image = edited_img.copy()
        entry._orig_pil = edited_img.copy()
        return None
    except Exception as exc:
        return str(exc)


# Export helpers
def export_entry_dds(entry: TextureEntry) -> bytes | None:
    """Return raw DDS bytes for the entry, or None if unavailable."""
    chunk = entry.chunk
    if isinstance(chunk, NuccChunkBinary):
        data = chunk.binary_data
        if data[:4] == b'DDS ':
            return bytes(data)
        # PNG binary – encode through PIL
        try:
            img = Image.open(io.BytesIO(data)).convert('RGBA')
            nt  = pil_to_nut_texture_rgba(img)
            return _nut_tex_to_dds_bytes(nt)
        except Exception:
            return None

    if isinstance(chunk, NuccChunkTexture) and chunk.nut and chunk.nut.textures:
        return _nut_tex_to_dds_bytes(chunk.nut.textures[0])
    return None


def export_entry_png(entry: TextureEntry) -> bytes | None:
    """Return raw PNG bytes for the entry, or None if unavailable."""
    if entry.pil_image is None:
        return None
    try:
        buf = io.BytesIO()
        entry.pil_image.save(buf, 'PNG')
        return buf.getvalue()
    except Exception:
        return None


# Port textures from another xfbin
def load_xfbin_for_port(path: str) -> list[TextureEntry]:
    """Load a second xfbin and return its texture entries (no modifications)."""
    _, entries = load_xfbin(path)
    return entries


def port_entries_into_xfbin(xfbin, entries_to_port: list[TextureEntry]) -> int:
    """
    Copy selected TextureEntry objects from another xfbin into xfbin.
    Returns the number of textures actually added.
    """
    count = 0
    names = {entry.name.casefold() for entry in refresh_texture_entries(xfbin, decode_images=False)}
    for src in entries_to_port:
        try:
            new_chunk = _clone_chunk(src)
            if new_chunk is None:
                continue
            if new_chunk.name.casefold() in names:
                stem, number = new_chunk.name, 1
                while f'{stem}_{number}'.casefold() in names:
                    number += 1
                new_chunk.name = f'{stem}_{number}'
                new_chunk.filePath = _make_texture_file_path(new_chunk.name, src)
            names.add(new_chunk.name.casefold())
            page = Page()
            page.chunks.append(new_chunk)
            xfbin.pages.append(page)
            count += 1
        except Exception:
            continue
    return count


def _clone_chunk(src: TextureEntry):
    """Deep-copy the chunk from a TextureEntry."""
    chunk = src.chunk
    if isinstance(chunk, (NuccChunkTexture, NuccChunkBinary)):
        new_chunk = copy.deepcopy(chunk)
        if hasattr(new_chunk, '_texture_identity'):
            del new_chunk._texture_identity
        return new_chunk

    return None
