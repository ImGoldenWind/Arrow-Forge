"""Parser / writer for ASBR *_anmofs.xfbin animation offset files.

Confirmed from 0bao01_anmofs.xfbin:

    0x00 char[64]  animation name
    0x40 char[8]   character code
    0x48 u32       reserved / unknown, observed 0
    0x4C u32       entry count
    entry_count * 28-byte records:
        0x00 u32   frame
        0x04 f32   value 1, likely positional X offset
        0x08 f32   value 2, likely positional Y offset
        0x0C f32   value 3, likely positional Z offset
        0x10 f32   value 4, unknown / likely angle or rotation-related
        0x14 f32   value 5, unknown / likely angle or rotation-related
        0x18 f32   value 6, unknown / likely angle or rotation-related
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import struct

from parsers.xfbin_lib import NuccChunkBinary, Page, read_xfbin, write_xfbin_to_path


HEADER_SIZE = 0x50
ENTRY_SIZE = 0x1C
ANM_NAME_SIZE = 64
CHAR_CODE_SIZE = 8


@dataclass
class AnmofsEntry:
    frame: int = 0
    value_1: float = 0.0
    value_2: float = 0.0
    value_3: float = 0.0
    value_4: float = 0.0
    value_5: float = 0.0
    value_6: float = 0.0


@dataclass
class AnmofsChunk:
    page_index: int
    chunk: NuccChunkBinary
    chunk_name: str
    file_path: str
    anm_name: str
    characode: str
    reserved: int = 0
    entries: list[AnmofsEntry] = field(default_factory=list)

    @property
    def expected_chunk_name(self) -> str:
        if not self.anm_name or not self.characode:
            return ""
        return f"{self.anm_name}_{self.characode}"


def _read_fixed_ascii(data: bytes | bytearray, off: int, length: int) -> str:
    return data[off:off + length].split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _validate_fixed_ascii(text: str, length: int, field_name: str) -> None:
    try:
        encoded = str(text).encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be ASCII.") from exc
    if len(encoded) > length - 1:
        raise ValueError(f"{field_name} is too long; maximum is {length - 1} ASCII bytes.")


def _write_fixed_ascii(buf: bytearray, off: int, text: str, length: int, field_name: str) -> None:
    _validate_fixed_ascii(text, length, field_name)
    encoded = str(text).encode("ascii")
    buf[off:off + length] = encoded + b"\x00" * (length - len(encoded))


def _looks_like_anmofs_binary(data: bytes | bytearray) -> bool:
    if len(data) < HEADER_SIZE:
        return False
    count = struct.unpack_from("<I", data, 0x4C)[0]
    if count > 0xFFFF:
        return False
    return len(data) == HEADER_SIZE + count * ENTRY_SIZE


def _parse_chunk(page_index: int, chunk: NuccChunkBinary) -> AnmofsChunk:
    data = getattr(chunk, "binary_data", None)
    if data is None or not _looks_like_anmofs_binary(data):
        raise ValueError(f"Binary chunk {chunk.name!r} does not match the ASBR Anmofs layout.")

    count = struct.unpack_from("<I", data, 0x4C)[0]
    entries: list[AnmofsEntry] = []
    for idx in range(count):
        off = HEADER_SIZE + idx * ENTRY_SIZE
        values = struct.unpack_from("<I6f", data, off)
        entries.append(AnmofsEntry(*values))

    return AnmofsChunk(
        page_index=page_index,
        chunk=chunk,
        chunk_name=chunk.name,
        file_path=chunk.filePath,
        anm_name=_read_fixed_ascii(data, 0x00, ANM_NAME_SIZE),
        characode=_read_fixed_ascii(data, 0x40, CHAR_CODE_SIZE),
        reserved=struct.unpack_from("<I", data, 0x48)[0],
        entries=entries,
    )


def _pack_chunk(item: AnmofsChunk) -> bytes:
    if len(item.entries) > 0xFFFFFFFF:
        raise ValueError("An Anmofs chunk has too many entries.")
    if not (0 <= int(item.reserved) <= 0xFFFFFFFF):
        raise ValueError("Reserved value must fit in u32.")

    buf = bytearray(HEADER_SIZE + len(item.entries) * ENTRY_SIZE)
    _write_fixed_ascii(buf, 0x00, item.anm_name, ANM_NAME_SIZE, "Animation name")
    _write_fixed_ascii(buf, 0x40, item.characode, CHAR_CODE_SIZE, "Character code")
    struct.pack_into("<I", buf, 0x48, int(item.reserved))
    struct.pack_into("<I", buf, 0x4C, len(item.entries))

    for idx, entry in enumerate(item.entries):
        if not (0 <= int(entry.frame) <= 0xFFFFFFFF):
            raise ValueError("Frame value must fit in u32.")
        off = HEADER_SIZE + idx * ENTRY_SIZE
        struct.pack_into(
            "<I6f",
            buf,
            off,
            int(entry.frame),
            float(entry.value_1),
            float(entry.value_2),
            float(entry.value_3),
            float(entry.value_4),
            float(entry.value_5),
            float(entry.value_6),
        )
    return bytes(buf)


def load_anmofs_xfbin(path: str):
    xfbin = read_xfbin(path)
    chunks: list[AnmofsChunk] = []
    for page_index, page in enumerate(xfbin.pages):
        for chunk in page.chunks:
            if not isinstance(chunk, NuccChunkBinary):
                continue
            data = getattr(chunk, "binary_data", None)
            if data is None or not _looks_like_anmofs_binary(data):
                continue
            chunks.append(_parse_chunk(page_index, chunk))
    if not chunks:
        raise ValueError("No Anmofs binary chunks were found in this XFBIN.")
    return xfbin, chunks


def save_anmofs_xfbin(xfbin, path: str, chunks: list[AnmofsChunk]) -> None:
    for item in chunks:
        _validate_fixed_ascii(item.chunk_name, 255, "Chunk name")
        _validate_fixed_ascii(item.file_path, 255, "Chunk file path")
        item.chunk.name = item.chunk_name
        item.chunk.filePath = item.file_path
        item.chunk.binary_data = _pack_chunk(item)
        item.chunk.has_props = True
        item.chunk.extension = ".binary"
    write_xfbin_to_path(xfbin, path)


def make_default_chunk(name: str = "anmofs_entry") -> AnmofsChunk:
    chunk = NuccChunkBinary(f"{name}.bin", name)
    chunk.has_props = True
    chunk.extension = ".binary"
    item = AnmofsChunk(
        page_index=-1,
        chunk=chunk,
        chunk_name=name,
        file_path=f"{name}.bin",
        anm_name=name,
        characode="0bao01",
        reserved=0,
        entries=[AnmofsEntry()],
    )
    chunk.binary_data = _pack_chunk(item)
    return item


def duplicate_anmofs_chunk(source: AnmofsChunk, name: str) -> AnmofsChunk:
    item = copy.deepcopy(source)
    item.chunk = NuccChunkBinary(source.file_path, name)
    item.chunk.has_props = True
    item.chunk.extension = ".binary"
    item.chunk_name = name
    item.file_path = source.file_path
    item.chunk.name = name
    item.chunk.filePath = item.file_path
    item.chunk.binary_data = _pack_chunk(item)
    item.page_index = -1
    return item


def append_chunk_page(xfbin, item: AnmofsChunk) -> None:
    page = Page()
    page.chunks.append(item.chunk)
    xfbin.pages.append(page)
    item.page_index = len(xfbin.pages) - 1
