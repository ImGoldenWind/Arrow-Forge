"""Parser / writer for ASBR *_anmofs.xfbin animation offset files.

Confirmed from the native loader/consumers and the stock corpus:

    0x00 char[64]  animation name
    0x40 char[8]   character code
    0x48 u32       skipped storage word, observed 0
    0x4C i32       entry count
    entry_count * 28-byte records:
        0x00 i32   frame (negative entries are ignored)
        0x04 f32   local translation X
        0x08 f32   local translation Y
        0x0C f32   local translation Z
        0x10 f32   rotation X
        0x14 f32   rotation Y
        0x18 f32   rotation Z

ASBR.exe RVAs 33A3FC, 33A230, 3691FC: two Vector3s, step/hold lookup,
first duplicate key wins, mirrored X translation and X/Z rotation. The file
owner attacks; chunk names select the receiving character.
Header +48 is skipped by the native loader. Chunk names select the receiver;
the copied +40 code is consulted by the d-only motion gate. Stock headers can
disagree with the chunk name. See docs/anmofs-research.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import math
import os
import struct
import tempfile

from parsers.xfbin_lib import NuccChunkBinary, Page, read_xfbin, write_xfbin


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
        """Conventional header-derived name; stock mismatches are valid."""
        if not self.anm_name or not self.characode:
            return ""
        return f"{self.anm_name}_{self.characode}"


def _read_fixed_ascii(data: bytes | bytearray, off: int, length: int) -> str:
    return data[off:off + length].split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _validate_fixed_ascii(text: str, length: int, field_name: str) -> None:
    if '\x00' in str(text):
        raise ValueError(f"{field_name} cannot contain a NUL character.")
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
    count = struct.unpack_from("<i", data, 0x4C)[0]
    if count < 0:
        return False
    return len(data) == HEADER_SIZE + count * ENTRY_SIZE


def _parse_chunk(page_index: int, chunk: NuccChunkBinary) -> AnmofsChunk:
    data = getattr(chunk, "binary_data", None)
    if data is None or not _looks_like_anmofs_binary(data):
        raise ValueError(f"Binary chunk {chunk.name!r} does not match the ASBR Anmofs layout.")

    count = struct.unpack_from("<i", data, 0x4C)[0]
    entries: list[AnmofsEntry] = []
    for idx in range(count):
        off = HEADER_SIZE + idx * ENTRY_SIZE
        values = struct.unpack_from("<i6f", data, off)
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
    if len(item.entries) > 0x7FFFFFFF:
        raise ValueError("An Anmofs chunk has too many entries.")
    if not (0 <= int(item.reserved) <= 0xFFFFFFFF):
        raise ValueError("Reserved value must fit in u32.")

    buf = bytearray(HEADER_SIZE + len(item.entries) * ENTRY_SIZE)
    original = getattr(item.chunk, 'binary_data', b'') or b''
    for off, text, size, label in ((0, item.anm_name, ANM_NAME_SIZE, 'Animation name'),
                                   (0x40, item.characode, CHAR_CODE_SIZE, 'Character code')):
        _validate_fixed_ascii(text, size, label)
        if len(original) >= HEADER_SIZE and _read_fixed_ascii(original, off, size) == text:
            buf[off:off + size] = original[off:off + size]
        else:
            _write_fixed_ascii(buf, off, text, size, label)
    struct.pack_into("<I", buf, 0x48, int(item.reserved))
    struct.pack_into("<i", buf, 0x4C, len(item.entries))

    for idx, entry in enumerate(item.entries):
        if not (-0x80000000 <= int(entry.frame) <= 0x7FFFFFFF):
            raise ValueError("Frame value must fit in i32.")
        off = HEADER_SIZE + idx * ENTRY_SIZE
        struct.pack_into(
            "<i6f",
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
        # Retain original IEEE payloads (including signaling NaNs) for words
        # whose decoded value was not changed. Neighboring edits stay local.
        if len(original) >= off + ENTRY_SIZE:
            for index in range(6):
                word = off + 4 + index * 4
                old_value = struct.unpack_from('<f', original, word)[0]
                new_value = float(getattr(entry, f'value_{index + 1}'))
                if old_value == new_value or math.isnan(old_value) and math.isnan(new_value):
                    buf[word:word + 4] = original[word:word + 4]
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
    # Validate everything before touching either the live model or destination.
    payloads = []
    for item in chunks:
        _validate_fixed_ascii(item.chunk_name, 255, "Chunk name")
        _validate_fixed_ascii(item.file_path, 255, "Chunk file path")
        payloads.append(_pack_chunk(item))
    # Copy both together: page payloads and per-occurrence envelopes must keep
    # their references to the same chunk objects, including after a rename.
    staged, staged_items = copy.deepcopy((xfbin, chunks))
    for item, payload in zip(staged_items, payloads):
        item.chunk.name = item.chunk_name
        item.chunk.filePath = item.file_path
        item.chunk.binary_data = payload
        item.chunk.has_props = True
        item.chunk.extension = ".binary"
    encoded = write_xfbin(staged)
    target = os.path.abspath(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(target),
                                         prefix='.anmofs-', suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            stream.write(encoded)
        os.replace(temporary, target)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    for item, payload in zip(chunks, payloads):
        item.chunk.name = item.chunk_name
        item.chunk.filePath = item.file_path
        item.chunk.binary_data = payload
        item.chunk.has_props = True
        item.chunk.extension = ".binary"


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
