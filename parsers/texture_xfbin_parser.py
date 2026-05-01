import io
import copy
import os
import struct
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
def nut_tex_to_pil(tex: NutTexture) -> Image.Image | None:
    """Decode the first mipmap of a NutTexture to a PIL RGBA image."""
    fmt = tex.pixel_format
    w, h = tex.width, tex.height
    if w <= 0 or h <= 0:
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
            return Image.merge('RGBA', (g, b, a, r))

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

    if fmt == 0:
        pitch = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    elif fmt in (1, 2, 21, 22):
        pitch = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    else:
        pitch = w * h * 4

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

    caps1 = 0x8
    if mips > 1:
        caps1 |= 0x400000 | 0x1000
    buf += struct.pack('<IIIII', caps1, 0, 0, 0, 0)

    buf += tex.texture_data
    return bytes(buf)


# DDS file → NutTexture
_DDS_FOURCC_TO_PF = {
    b'DXT1': 0, b'DXT3': 1, b'DXT5': 2,
    b'ATI1': 21, b'BC4U': 21, b'BC4S': 21,
    b'ATI2': 22, b'BC5U': 22, b'BC5S': 22,
}

def dds_to_nut_texture(data: bytes) -> NutTexture:
    if data[:4] != b'DDS ':
        raise ValueError('Not a DDS file')

    h_val   = struct.unpack_from('<I', data, 12)[0]
    w_val   = struct.unpack_from('<I', data, 16)[0]
    mips    = struct.unpack_from('<I', data, 28)[0] or 1
    pf_flags = struct.unpack_from('<I', data, 80)[0]
    fourcc  = data[84:88]
    rgb_bits = struct.unpack_from('<I', data, 88)[0]

    texture_body = data[128:]

    if pf_flags & 0x4:   # DDPF_FOURCC
        pixel_format = _DDS_FOURCC_TO_PF.get(fourcc, 2)
    else:
        # Uncompressed – detect common formats
        r_mask = struct.unpack_from('<I', data, 92)[0]
        a_mask = struct.unpack_from('<I', data, 104)[0]
        if rgb_bits == 32 and a_mask:
            pixel_format = 17   # RGBA8888
            arr = array('l', texture_body[:w_val * h_val * 4])
            arr.byteswap()
            texture_body = arr.tobytes()
        elif rgb_bits == 32:
            pixel_format = 14   # RGB888X
            arr = array('l', texture_body[:w_val * h_val * 4])
            arr.byteswap()
            texture_body = arr.tobytes()
        elif rgb_bits == 16 and r_mask == 0x7c00:
            pixel_format = 6    # RGB5551
            arr = array('H', texture_body[:w_val * h_val * 2])
            arr.byteswap()
            texture_body = arr.tobytes()
        elif rgb_bits == 16 and r_mask == 0x0f00:
            pixel_format = 7    # RGBA4444
            arr = array('H', texture_body[:w_val * h_val * 2])
            arr.byteswap()
            texture_body = arr.tobytes()
        elif rgb_bits == 16:
            pixel_format = 8    # RGB565
            arr = array('H', texture_body[:w_val * h_val * 2])
            arr.byteswap()
            texture_body = arr.tobytes()
        else:
            pixel_format = 17   # fallback

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
        mipmaps.append(chunk)
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
        extra = mips * 4
        combined = 48 + extra
        if combined % 8 != 0:
            combined += 8 - (combined % 8)
        tex.header_size = combined
    tex.header_size += 32   # eXt + GIDX sections
    tex.total_size   = tex.data_size + tex.header_size
    return tex


# PIL Image → NutTexture (RGBA8888)
def pil_to_nut_texture_rgba(img: Image.Image) -> NutTexture:
    """Encode a PIL image as NutTexture RGBA8888 (pixel_format=17)."""
    img = img.convert('RGBA')
    w, h = img.size
    r, g, b, a = img.split()
    # NUT ARGB order: decoding does Image.merge(RGBA, (g,b,a,r)) so storage is ARGB
    encoded = Image.merge('RGBA', (a, r, g, b))
    texture_data = encoded.tobytes()

    tex = NutTexture()
    tex.width        = w
    tex.height       = h
    tex.pixel_format = 17
    tex.mipmap_count = 1
    tex.is_cube_map  = False
    tex.cubemap_format = 0
    tex.mipmaps      = [texture_data]
    tex.texture_data = texture_data
    tex.data_size    = len(texture_data)
    tex.header_size  = 80   # 48 + 32 (eXt+GIDX)
    tex.total_size   = tex.data_size + tex.header_size
    return tex


# TextureEntry data class
class TextureEntry:
    """One texture item extracted from an xfbin."""
    __slots__ = ('name', 'file_path', 'tex_type',
                 'width', 'height', 'pixel_format', 'mipmap_count',
                 'chunk', 'pil_image', '_orig_pil', 'page_idx')

    def __init__(self):
        self.name:          str = ''
        self.file_path:     str = ''
        self.tex_type:      str = 'nut'   # 'nut' | 'dds' | 'png'
        self.width:         int = 0
        self.height:        int = 0
        self.pixel_format:  int = 0
        self.mipmap_count:  int = 1
        self.chunk         = None   # NuccChunkTexture or NuccChunkBinary
        self.pil_image:     Image.Image | None = None
        self._orig_pil:     Image.Image | None = None
        self.page_idx:      int = -1

    @property
    def format_name(self) -> str:
        if self.tex_type in ('dds', 'png'):
            return self.tex_type.upper()
        return PF_NAMES.get(self.pixel_format, f'PF{self.pixel_format}')

    @property
    def size_str(self) -> str:
        return f'{self.width}×{self.height}'


# Load xfbin
def load_xfbin(path: str):
    """Read an xfbin and return (Xfbin, [TextureEntry])."""
    xfbin = _read_xfbin(path)
    entries: list[TextureEntry] = []

    for page_idx, page in enumerate(xfbin.pages):
        for chunk in page.chunks:
            entry = _chunk_to_entry(chunk, page_idx)
            if entry:
                entries.append(entry)

    return xfbin, entries


def _chunk_to_entry(chunk, page_idx: int) -> 'TextureEntry | None':
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
            img = nut_tex_to_pil(t)
            e.pil_image    = img
            e._orig_pil    = img.copy() if img else None
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
            try:
                e.pil_image = Image.open(io.BytesIO(data)).convert('RGBA')
                e._orig_pil = e.pil_image.copy()
            except Exception:
                pass
            return e

        if data[:4] == b'\x89PNG':
            e.tex_type = 'png'
            try:
                img = Image.open(io.BytesIO(data)).convert('RGBA')
                e.width, e.height = img.size
                e.pil_image  = img
                e._orig_pil  = img.copy()
            except Exception:
                pass
            return e

    return None


# Save xfbin
def save_xfbin(xfbin, path: str) -> None:
    _write_path(xfbin, path)


# Replace texture from external file
def replace_texture_from_file(entry: TextureEntry, import_path: str) -> str | None:
    """Replace the texture in-place. Returns an error string or None on success."""
    with open(import_path, 'rb') as f:
        data = f.read()

    ext = os.path.splitext(import_path)[1].lower()

    try:
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
        if raw_data:
            chunk.binary_data = raw_data


# Apply PIL edits back to texture
def apply_pil_edits_to_entry(entry: TextureEntry, edited_img: Image.Image) -> str | None:
    """
    Write an edited PIL Image back to the chunk as RGBA8888.
    The original format may change to RGBA8888 for block-compressed textures.
    Returns an error string or None on success.
    """
    try:
        new_tex = pil_to_nut_texture_rgba(edited_img)
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
    for src in entries_to_port:
        try:
            new_chunk = _clone_chunk(src)
            if new_chunk is None:
                continue
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
    if isinstance(chunk, NuccChunkTexture) and chunk.nut and chunk.nut.textures:
        new_chunk = NuccChunkTexture(chunk.filePath, chunk.name)
        new_chunk.has_props = True
        new_nut   = Nut()
        new_nut.magic = 'NTP3'
        new_nut.version = 0x0100
        new_nut.textures = [copy.deepcopy(t) for t in chunk.nut.textures]
        new_nut.texture_count = len(new_nut.textures)
        new_chunk.nut = new_nut
        return new_chunk

    if isinstance(chunk, NuccChunkBinary) and hasattr(chunk, 'binary_data'):
        new_chunk = NuccChunkBinary(chunk.filePath, chunk.name)
        new_chunk.has_props   = True
        new_chunk.binary_data = copy.copy(chunk.binary_data)
        return new_chunk

    return None
