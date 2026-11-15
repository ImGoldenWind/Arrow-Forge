from __future__ import annotations

import io
import os
import struct
import tempfile
from dataclasses import dataclass, field

from PIL import Image

from parsers.texture_xfbin_parser import nut_tex_to_pil
from parsers.xfbin_lib import BinaryReader, BrNut, Endian, Nut, NuccChunkBinary, read_xfbin


NFH_HEADER_OFFSET = 8
NFH_FIXED_TABLE_SIZE = 1104
NFH_GLYPH_RECORD_SIZE = 32
ICONFONT_HEADER_SIZE = 12
ICONFONT_RECORD_SIZE = 44


@dataclass
class FontAtlas:
    offset: int
    data: bytearray
    width: int = 0
    height: int = 0
    pixel_format: int = 0
    mipmap_count: int = 0
    texture_data_offset: int = 0
    texture_data_size: int = 0
    pil_image: Image.Image | None = None
    edit_error: str = ""


@dataclass
class FontRecord:
    index: int
    offset: int
    data: bytearray

    @property
    def hex_text(self) -> str:
        return self.data.hex(" ").upper()

    @property
    def words(self) -> list[int]:
        return list(struct.unpack(">8I", bytes(self.data)))

    @property
    def glyph_code(self) -> int:
        if len(self.data) < 24:
            return 0
        return struct.unpack_from(">H", self.data, 22)[0]

    @property
    def glyph_label(self) -> str:
        code = self.glyph_code
        if 32 <= code <= 0x10FFFF and chr(code).isprintable():
            return f"{code:02X} '{chr(code)}'"
        return f"{code:02X}"

    @property
    def glyph_char(self) -> str:
        code = self.glyph_code
        if 32 <= code <= 0x10FFFF and chr(code).isprintable():
            return chr(code)
        return ""

    @property
    def atlas_x(self) -> int:
        return struct.unpack_from(">H", self.data, 4)[0] if len(self.data) >= 6 else 0

    @property
    def atlas_y(self) -> int:
        return struct.unpack_from(">H", self.data, 6)[0] if len(self.data) >= 8 else 0

    @property
    def atlas_width(self) -> int:
        return self.data[20] if len(self.data) >= 21 else 0

    @property
    def atlas_height(self) -> int:
        return self.data[21] if len(self.data) >= 22 else 0

    @property
    def has_atlas_rect(self) -> bool:
        return self.atlas_width > 0 and self.atlas_height > 0


@dataclass
class IconfontRecord:
    index: int
    offset: int
    data: bytearray

    @property
    def hex_text(self) -> str:
        return self.data.hex(" ").upper()

    @property
    def fields(self) -> list[int]:
        return list(struct.unpack(">11I", bytes(self.data)))


@dataclass
class FontDocument:
    path: str
    kind: str
    raw_file: bytearray
    original_payload: bytes
    payload: bytearray
    chunk_name: str
    chunk_file_path: str
    payload_offset: int
    family: str = ""
    style: str = ""
    font_table_size: int = 0
    table_flag: int = 0
    glyph_count: int = 0
    glyph_records: list[FontRecord] = field(default_factory=list)
    atlas: FontAtlas | None = None
    icon_header: list[int] = field(default_factory=list)
    icon_records: list[IconfontRecord] = field(default_factory=list)


def load_font_xfbin(path: str) -> FontDocument:
    raw_file = bytearray(_read_file(path))
    xfbin = read_xfbin(path)

    for page in xfbin.pages:
        for chunk in page.chunks:
            if type(chunk).__name__ == "NuccChunkFont":
                payload = bytearray(chunk.data)
                return _parse_nfh_document(path, raw_file, payload, chunk.filePath, chunk.name)
            if isinstance(chunk, NuccChunkBinary) and os.path.basename(chunk.filePath).lower() == "iconfontparam.bin":
                payload = bytearray(chunk.binary_data)
                return _parse_iconfont_document(path, raw_file, payload, chunk.filePath, chunk.name)

    raise ValueError("Unsupported font XFBIN: no NuccChunkFont or iconfontParam binary payload found")


def save_font_xfbin(document: FontDocument, path: str | None = None) -> None:
    target = path or document.path
    if len(document.payload) != len(document.original_payload):
        raise ValueError("Safe v1 save requires the payload length to stay unchanged")

    raw = bytearray(document.raw_file)
    offset = document.payload_offset
    end = offset + len(document.original_payload)
    if offset < 0 or end > len(raw) or bytes(raw[offset:end]) != document.original_payload:
        offset = bytes(raw).find(document.original_payload)
        if offset < 0:
            raise ValueError("Original payload bytes were not found in the source file")
        end = offset + len(document.original_payload)

    raw[offset:end] = document.payload
    directory = os.path.dirname(os.path.abspath(target))
    fd, temporary = tempfile.mkstemp(prefix='.arrowforge-font-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    document.path = target
    document.raw_file = raw
    document.original_payload = bytes(document.payload)
    document.payload_offset = offset


def set_nfh_record_hex(document: FontDocument, index: int, hex_text: str) -> None:
    record = document.glyph_records[index]
    data = _parse_hex_exact(hex_text, NFH_GLYPH_RECORD_SIZE)
    record.data[:] = data
    document.payload[record.offset:record.offset + NFH_GLYPH_RECORD_SIZE] = data


def set_nfh_metadata(document: FontDocument, family: str, style: str) -> None:
    if document.kind != "nfh_font":
        return
    family_bytes = _encode_fixed_ascii(family, 32)
    style_bytes = _encode_fixed_ascii(style, 32)
    document.payload[24:56] = family_bytes
    document.payload[56:88] = style_bytes
    document.family = family_bytes.split(b"\0", 1)[0].decode("ascii", "replace")
    document.style = style_bytes.split(b"\0", 1)[0].decode("ascii", "replace")


def replace_nfh_atlas_same_size(document: FontDocument, data: bytes) -> None:
    if document.kind != "nfh_font" or document.atlas is None:
        raise ValueError("This file does not contain an editable NFH atlas")
    if len(data) != len(document.atlas.data):
        raise ValueError("Safe v1 atlas replacement requires the exact same NTP3 byte length")
    atlas = _parse_atlas(document.atlas.offset, bytearray(data))
    if atlas.pil_image is None:
        raise ValueError("Replacement NTP3 atlas could not be decoded")
    if (atlas.width, atlas.height) != (document.atlas.width, document.atlas.height):
        raise ValueError("Replacement atlas dimensions must stay unchanged")
    if any(r.has_atlas_rect and (r.atlas_x + r.atlas_width > atlas.width or
                                r.atlas_y + r.atlas_height > atlas.height)
           for r in document.glyph_records):
        raise ValueError("A glyph rectangle exceeds the replacement atlas")
    document.payload[document.atlas.offset:document.atlas.offset + len(data)] = data
    document.atlas = atlas


def crop_nfh_glyph_image(document: FontDocument, index: int) -> Image.Image | None:
    if document.kind != "nfh_font" or document.atlas is None or document.atlas.pil_image is None:
        return None
    record = document.glyph_records[index]
    if not record.has_atlas_rect:
        return None
    if (record.atlas_x + record.atlas_width > document.atlas.width or
            record.atlas_y + record.atlas_height > document.atlas.height):
        return None
    box = (
        record.atlas_x,
        record.atlas_y,
        record.atlas_x + record.atlas_width,
        record.atlas_y + record.atlas_height,
    )
    return document.atlas.pil_image.crop(box)


def replace_nfh_glyph_image(document: FontDocument, index: int, image: Image.Image) -> None:
    if document.kind != "nfh_font" or document.atlas is None or document.atlas.pil_image is None:
        raise ValueError("This file does not contain an editable NFH atlas")
    record = document.glyph_records[index]
    if not record.has_atlas_rect:
        raise ValueError("The selected glyph has no atlas rectangle")
    if document.atlas.edit_error:
        raise ValueError(document.atlas.edit_error)
    if crop_nfh_glyph_image(document, index) is None:
        raise ValueError("Glyph rectangle exceeds atlas dimensions")

    atlas_img = document.atlas.pil_image.copy().convert("RGBA")
    glyph_img = image.convert("RGBA")
    if glyph_img.size != (record.atlas_width, record.atlas_height):
        glyph_img = glyph_img.resize((record.atlas_width, record.atlas_height), Image.Resampling.LANCZOS)

    clear = Image.new("RGBA", (record.atlas_width, record.atlas_height), (0, 0, 0, 0))
    atlas_img.paste(clear, (record.atlas_x, record.atlas_y))
    atlas_img.alpha_composite(glyph_img, (record.atlas_x, record.atlas_y))
    _replace_nfh_atlas_image(
        document,
        atlas_img,
        dirty_rect=(record.atlas_x, record.atlas_y, record.atlas_width, record.atlas_height),
    )


def set_icon_record_hex(document: FontDocument, index: int, hex_text: str) -> None:
    record = document.icon_records[index]
    data = _parse_hex_exact(hex_text, ICONFONT_RECORD_SIZE)
    record.data[:] = data
    document.payload[record.offset:record.offset + ICONFONT_RECORD_SIZE] = data


def set_icon_record_field(document: FontDocument, index: int, field_index: int, value: int) -> None:
    if field_index < 0 or field_index >= 11:
        raise ValueError("Iconfont record field index is out of range")
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("Iconfont record fields must be unsigned 32-bit integers")
    record = document.icon_records[index]
    struct.pack_into(">I", record.data, field_index * 4, value)
    start = record.offset + field_index * 4
    document.payload[start:start + 4] = record.data[field_index * 4:field_index * 4 + 4]


def resolve_icon_string(document: FontDocument, offset: int) -> str:
    if offset <= 0 or offset >= len(document.payload):
        return ""
    end = document.payload.find(0, offset)
    if end < 0 or end == offset:
        return ""
    chunk = bytes(document.payload[offset:end])
    if any(byte < 32 or byte > 126 for byte in chunk):
        return ""
    return chunk.decode("ascii", "replace")


def atlas_png_bytes(document: FontDocument) -> bytes:
    if document.atlas is None or document.atlas.pil_image is None:
        raise ValueError("No atlas image is available")
    buf = io.BytesIO()
    document.atlas.pil_image.save(buf, "PNG")
    return buf.getvalue()


def _parse_nfh_document(path: str, raw_file: bytearray, payload: bytearray, file_path: str, name: str) -> FontDocument:
    if len(payload) < NFH_HEADER_OFFSET + NFH_FIXED_TABLE_SIZE:
        raise ValueError("NFH payload is too small")
    if bytes(payload[8:12]) != b"NFH\0":
        raise ValueError("NFH signature was not found at offset 8")

    font_table_size, table_flag = struct.unpack_from(">II", payload, 0)
    glyph_count = struct.unpack_from(">I", payload, 16)[0]
    expected_table_size = NFH_FIXED_TABLE_SIZE + glyph_count * NFH_GLYPH_RECORD_SIZE
    if font_table_size != expected_table_size:
        raise ValueError(
            f"Unexpected NFH table size: got {font_table_size}, expected {expected_table_size}"
        )

    atlas_offset = NFH_HEADER_OFFSET + font_table_size
    if atlas_offset >= len(payload) or bytes(payload[atlas_offset:atlas_offset + 4]) != b"NTP3":
        raise ValueError("Embedded NTP3 atlas was not found at the expected offset")

    family = _decode_fixed_ascii(payload[24:56])
    style = _decode_fixed_ascii(payload[56:88])
    records = []
    record_base = NFH_HEADER_OFFSET + NFH_FIXED_TABLE_SIZE
    for index in range(glyph_count):
        offset = record_base + index * NFH_GLYPH_RECORD_SIZE
        records.append(FontRecord(index, offset, bytearray(payload[offset:offset + NFH_GLYPH_RECORD_SIZE])))

    return FontDocument(
        path=path,
        kind="nfh_font",
        raw_file=raw_file,
        original_payload=bytes(payload),
        payload=payload,
        payload_offset=_find_payload_offset(raw_file, payload),
        chunk_name=name,
        chunk_file_path=file_path,
        family=family,
        style=style,
        font_table_size=font_table_size,
        table_flag=table_flag,
        glyph_count=glyph_count,
        glyph_records=records,
        atlas=_parse_atlas(atlas_offset, payload[atlas_offset:]),
    )


def _parse_iconfont_document(path: str, raw_file: bytearray, payload: bytearray, file_path: str, name: str) -> FontDocument:
    if len(payload) < ICONFONT_HEADER_SIZE:
        raise ValueError("iconfontParam payload is too small")
    header = list(struct.unpack_from(">3I", payload, 0))
    count = header[1]
    table_start = 8 + header[2]
    expected_end = table_start + count * ICONFONT_RECORD_SIZE
    if (count and table_start < ICONFONT_HEADER_SIZE) or expected_end > len(payload):
        raise ValueError("iconfontParam record table exceeds payload length")

    records = []
    for index in range(count):
        offset = table_start + index * ICONFONT_RECORD_SIZE
        records.append(IconfontRecord(index, offset, bytearray(payload[offset:offset + ICONFONT_RECORD_SIZE])))

    return FontDocument(
        path=path,
        kind="iconfont_param",
        raw_file=raw_file,
        original_payload=bytes(payload),
        payload=payload,
        payload_offset=_find_payload_offset(raw_file, payload),
        chunk_name=name,
        chunk_file_path=file_path,
        icon_header=header,
        icon_records=records,
    )


def _parse_atlas(offset: int, data: bytearray) -> FontAtlas:
    atlas = FontAtlas(offset=offset, data=bytearray(data))
    try:
        with BinaryReader(bytes(data), Endian.BIG) as br:
            br_nut = br.read_struct(BrNut)
        nut = Nut()
        nut.init_data(br_nut)
        if nut.textures:
            tex = nut.textures[0]
            atlas.width = tex.width
            atlas.height = tex.height
            atlas.pixel_format = tex.pixel_format
            atlas.mipmap_count = tex.mipmap_count
            atlas.texture_data_size = len(tex.texture_data)
            # First record starts after the 16-byte NTP3 header. Tails and
            # neighboring records are not texture data.
            atlas.texture_data_offset = 16 + br_nut.textures[0].header_size
            atlas.pil_image = nut_tex_to_pil(tex)
            if len(nut.textures) != 1 or tex.mipmap_count != 1 or tex.is_cube_map:
                atlas.edit_error = "Glyph editing requires one 2D texture with one mip level"
            elif br_nut.version != 0x100 or tex.pixel_format not in (2, 17):
                atlas.edit_error = "Glyph editing supports NTP3 v0x100 DXT5 or RGBA8888 only"
            expected = atlas.width * atlas.height * (4 if atlas.pixel_format == 17 else 1)
            if (atlas.texture_data_size != expected or
                    atlas.texture_data_offset + atlas.texture_data_size > len(data)):
                atlas.edit_error = "Atlas texture data has an unsupported or truncated layout"
    except Exception as exc:
        atlas.pil_image = None
        atlas.edit_error = str(exc)
    return atlas


def _replace_nfh_atlas_image(
    document: FontDocument,
    image: Image.Image,
    dirty_rect: tuple[int, int, int, int] | None = None,
) -> None:
    atlas = document.atlas
    if atlas is None:
        raise ValueError("No atlas is available")
    if atlas.edit_error:
        raise ValueError(atlas.edit_error)
    if image.size != (atlas.width, atlas.height):
        raise ValueError("Atlas image size must stay unchanged")
    if atlas.texture_data_offset <= 0 or atlas.texture_data_size <= 0:
        raise ValueError("Atlas texture data offset is unknown")

    if atlas.pixel_format == 2:
        if dirty_rect is None:
            encoded = _encode_dxt5(image)
        else:
            existing = bytes(atlas.data[atlas.texture_data_offset:atlas.texture_data_offset + atlas.texture_data_size])
            encoded = _encode_dxt5_region(image, existing, dirty_rect)
    elif atlas.pixel_format == 17:
        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        encoded = Image.merge("RGBA", (a, r, g, b)).tobytes()
    else:
        raise ValueError(f"Atlas pixel format PF{atlas.pixel_format} is not supported for glyph conversion")

    if len(encoded) != atlas.texture_data_size:
        raise ValueError("Converted atlas texture size changed unexpectedly")

    atlas.data[atlas.texture_data_offset:atlas.texture_data_offset + atlas.texture_data_size] = encoded
    document.payload[
        atlas.offset + atlas.texture_data_offset:atlas.offset + atlas.texture_data_offset + atlas.texture_data_size
    ] = encoded
    # Preview the pixels actually saved after lossy block compression.
    decoded = _parse_atlas(atlas.offset, atlas.data)
    atlas.pil_image = decoded.pil_image


def _encode_dxt5(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width % 4 != 0 or height % 4 != 0:
        raise ValueError("DXT5 atlases must have dimensions divisible by 4")
    pixels = rgba.load()
    out = bytearray()
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            block = [pixels[min(x + bx, width - 1), min(y + by, height - 1)] for by in range(4) for bx in range(4)]
            out.extend(_encode_dxt5_block(block))
    return bytes(out)


def _encode_dxt5_region(image: Image.Image, existing: bytes, dirty_rect: tuple[int, int, int, int]) -> bytes:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width % 4 != 0 or height % 4 != 0:
        raise ValueError("DXT5 atlases must have dimensions divisible by 4")
    expected_size = (width // 4) * (height // 4) * 16
    if len(existing) != expected_size:
        raise ValueError("Existing DXT5 texture data has an unexpected size")

    x, y, w, h = dirty_rect
    block_x0 = max(0, x // 4)
    block_y0 = max(0, y // 4)
    block_x1 = min(width // 4, (x + w + 3) // 4)
    block_y1 = min(height // 4, (y + h + 3) // 4)
    pixels = rgba.load()
    out = bytearray(existing)
    blocks_per_row = width // 4
    for by in range(block_y0, block_y1):
        for bx in range(block_x0, block_x1):
            px = bx * 4
            py = by * 4
            block = [pixels[px + ox, py + oy] for oy in range(4) for ox in range(4)]
            offset = (by * blocks_per_row + bx) * 16
            out[offset:offset + 16] = _encode_dxt5_block(block)
    return bytes(out)


def _encode_dxt5_block(block: list[tuple[int, int, int, int]]) -> bytes:
    alphas = [px[3] for px in block]
    a0 = max(alphas)
    a1 = min(alphas)
    alpha_palette = _dxt5_alpha_palette(a0, a1)
    alpha_bits = 0
    for i, alpha in enumerate(alphas):
        idx = min(range(8), key=lambda p: abs(alpha_palette[p] - alpha))
        alpha_bits |= idx << (3 * i)

    colors = [px[:3] for px in block]
    c0_rgb, c1_rgb = _choose_color_endpoints(colors)
    c0 = _rgb_to_565(*c0_rgb)
    c1 = _rgb_to_565(*c1_rgb)
    if c0 < c1:
        c0, c1 = c1, c0
        c0_rgb, c1_rgb = c1_rgb, c0_rgb
    palette = _dxt_color_palette(c0, c1)
    color_bits = 0
    for i, color in enumerate(colors):
        idx = min(range(4), key=lambda p: _color_distance(palette[p], color))
        color_bits |= idx << (2 * i)

    return (
        bytes((a0, a1))
        + alpha_bits.to_bytes(6, "little")
        + c0.to_bytes(2, "little")
        + c1.to_bytes(2, "little")
        + color_bits.to_bytes(4, "little")
    )


def _dxt5_alpha_palette(a0: int, a1: int) -> list[int]:
    if a0 > a1:
        return [
            a0,
            a1,
            (6 * a0 + 1 * a1) // 7,
            (5 * a0 + 2 * a1) // 7,
            (4 * a0 + 3 * a1) // 7,
            (3 * a0 + 4 * a1) // 7,
            (2 * a0 + 5 * a1) // 7,
            (1 * a0 + 6 * a1) // 7,
        ]
    return [
        a0,
        a1,
        (4 * a0 + 1 * a1) // 5,
        (3 * a0 + 2 * a1) // 5,
        (2 * a0 + 3 * a1) // 5,
        (1 * a0 + 4 * a1) // 5,
        0,
        255,
    ]


def _choose_color_endpoints(colors: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    best_a = colors[0]
    best_b = colors[0]
    best_dist = -1
    for a in colors:
        for b in colors:
            dist = _color_distance(a, b)
            if dist > best_dist:
                best_dist = dist
                best_a = a
                best_b = b
    return best_a, best_b


def _rgb_to_565(r: int, g: int, b: int) -> int:
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def _rgb_from_565(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def _dxt_color_palette(c0: int, c1: int) -> list[tuple[int, int, int]]:
    p0 = _rgb_from_565(c0)
    p1 = _rgb_from_565(c1)
    return [
        p0,
        p1,
        tuple((2 * p0[i] + p1[i]) // 3 for i in range(3)),
        tuple((p0[i] + 2 * p1[i]) // 3 for i in range(3)),
    ]


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return sum((a[i] - b[i]) * (a[i] - b[i]) for i in range(3))


def _find_payload_offset(raw_file: bytearray, payload: bytearray) -> int:
    raw = bytes(raw_file)
    needle = bytes(payload)
    offset = raw.find(needle)
    if offset < 0:
        raise ValueError("Payload bytes were not found in the source file")
    return offset


def _read_file(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _decode_fixed_ascii(data: bytes | bytearray) -> str:
    return bytes(data).split(b"\0", 1)[0].decode("ascii", "replace")


def _encode_fixed_ascii(text: str, size: int) -> bytes:
    raw = text.encode("ascii")
    if len(raw) >= size:
        raise ValueError(f"Text must be ASCII and shorter than {size} bytes")
    return raw + b"\0" * (size - len(raw))


def _parse_hex_exact(text: str, expected_size: int) -> bytes:
    compact = "".join(ch for ch in text.strip() if not ch.isspace())
    if len(compact) != expected_size * 2:
        raise ValueError(f"Expected exactly {expected_size} bytes of hex")
    try:
        data = bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("Invalid hex bytes") from exc
    if len(data) != expected_size:
        raise ValueError(f"Expected exactly {expected_size} bytes of hex")
    return data
