"""Parser / writer for ASBR character *_lip.xfbin files.

Each XFBIN page contains one ``nuccChunkBinary`` lip clip.  The binary payload
inside that chunk is:

    u16 entry_count
    entry_count * 40-byte key records

Key record layout, confirmed from 0bao01_lip.xfbin:

    0x00 f32       time value, likely seconds from clip start
    0x04 char[16]  lip animation token, e.g. PL_ANM_LIP_NO_A
    0x14 char[8]   modifier / tag A, usually empty, observed RISED
    0x1C char[8]   modifier / tag B, usually empty, observed VY
    0x24 f32       raw value; meaning is not named by the file
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import struct

from parsers.xfbin_lib import (
    NuccChunkBinary,
    Page,
    read_xfbin,
    write_xfbin,
)
from parsers.xfbin_lib.writer import write_bytes_atomically


ENTRY_SIZE = 40
HEADER_SIZE = 2

ANIMATION_MAX = 16
TAG_MAX = 8

OBSERVED_ANIMATION_TOKENS = [
    "PL_ANM_LIP_NO_N",
    "PL_ANM_LIP_NO_A",
    "PL_ANM_LIP_NO_U",
    "PL_ANM_LIP_NO_O",
    "PL_ANM_LIP_NO_E",
    "PL_ANM_LIP_NO_I",
]

OBSERVED_TAG_TOKENS = [
    "",
    "RISED",
    "VY",
]


@dataclass
class LipKey:
    time: float = 0.0
    animation: str = "PL_ANM_LIP_NO_N"
    tag_a: str = ""
    tag_b: str = ""
    value: float = 100.0
    _source_record: bytes = field(default=b'', repr=False, compare=False)


@dataclass
class LipClip:
    name: str
    file_path: str
    page_index: int
    chunk: NuccChunkBinary
    keys: list[LipKey] = field(default_factory=list)

    @property
    def duration(self) -> float:
        if not self.keys:
            return 0.0
        return max(key.time for key in self.keys)


def _read_fixed_ascii(data: bytes | bytearray, off: int, length: int) -> str:
    return data[off:off + length].split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _write_fixed_ascii(buf: bytearray, off: int, text: str, length: int) -> None:
    encoded = text.encode("ascii", errors="replace")[:length]
    end = off + length
    old_end = buf.find(b'\x00', off, end)
    # Replace the visible string and its terminator. Leave any opaque bytes
    # beyond the old terminator alone unless the new string occupies them.
    if old_end >= 0 and len(encoded) < length:
        end = max(old_end + 1, off + len(encoded) + 1)
    buf[off:end] = encoded.ljust(end - off, b'\x00')


def _looks_like_lip_binary(data: bytes | bytearray) -> bool:
    if len(data) < HEADER_SIZE:
        return False
    count = struct.unpack_from("<H", data, 0)[0]
    if count == 0:
        return len(data) == HEADER_SIZE
    if len(data) != HEADER_SIZE + count * ENTRY_SIZE:
        return False
    if count > 4096:
        return False
    sample_count = min(count, 8)
    for idx in range(sample_count):
        off = HEADER_SIZE + idx * ENTRY_SIZE
        token = _read_fixed_ascii(data, off + 0x04, 16)
        if not token.startswith("PL_ANM_LIP_"):
            return False
    return True


def _parse_keys(data: bytes | bytearray) -> list[LipKey]:
    if not _looks_like_lip_binary(data):
        raise ValueError("Binary chunk does not match the ASBR lip-sync key layout.")
    count = struct.unpack_from("<H", data, 0)[0]
    keys: list[LipKey] = []
    for idx in range(count):
        off = HEADER_SIZE + idx * ENTRY_SIZE
        keys.append(LipKey(
            time=struct.unpack_from("<f", data, off + 0x00)[0],
            animation=_read_fixed_ascii(data, off + 0x04, 16),
            tag_a=_read_fixed_ascii(data, off + 0x14, 8),
            tag_b=_read_fixed_ascii(data, off + 0x1C, 8),
            value=struct.unpack_from("<f", data, off + 0x24)[0],
            _source_record=bytes(data[off:off + ENTRY_SIZE]),
        ))
    return keys


def _pack_keys(keys: list[LipKey]) -> bytes:
    if len(keys) > 0xFFFF:
        raise ValueError("A lip clip can store at most 65535 keys.")
    buf = bytearray(HEADER_SIZE + len(keys) * ENTRY_SIZE)
    struct.pack_into("<H", buf, 0, len(keys))
    for idx, key in enumerate(keys):
        off = HEADER_SIZE + idx * ENTRY_SIZE
        raw = key._source_record
        if raw:
            buf[off:off + ENTRY_SIZE] = raw
        for offset, value in ((0x00, key.time), (0x24, key.value)):
            encoded = struct.pack('<f', value)
            if not raw or encoded != struct.pack('<f', struct.unpack_from('<f', raw, offset)[0]):
                buf[off + offset:off + offset + 4] = encoded
        for offset, value, size in ((0x04, key.animation, ANIMATION_MAX),
                                    (0x14, key.tag_a, TAG_MAX), (0x1C, key.tag_b, TAG_MAX)):
            if not raw or value != _read_fixed_ascii(raw, offset, size):
                _write_fixed_ascii(buf, off + offset, value, size)
    return bytes(buf)


def load_lipsync_xfbin(path: str):
    xfbin = read_xfbin(path, preserve_source=True)
    clips: list[LipClip] = []
    for page_index, page in enumerate(xfbin.pages):
        for chunk in page.chunks:
            if not isinstance(chunk, NuccChunkBinary):
                continue
            data = getattr(chunk, "binary_data", None)
            if data is None or not _looks_like_lip_binary(data):
                continue
            clips.append(LipClip(
                name=chunk.name,
                file_path=chunk.filePath,
                page_index=page_index,
                chunk=chunk,
                keys=_parse_keys(data),
            ))
    if not clips:
        raise ValueError("No *_lip binary clips were found in this XFBIN.")
    return xfbin, clips


def save_lipsync_xfbin(xfbin, path: str, clips: list[LipClip]) -> None:
    updates = [(clip, _pack_keys(clip.keys)) for clip in clips]
    previous = [(clip.chunk, clip.chunk.name, clip.chunk.filePath, clip.chunk.binary_data) for clip, _ in updates]
    try:
        for clip, data in updates:
            clip.chunk.name = clip.name
            clip.chunk.filePath = clip.file_path
            clip.chunk.binary_data = data
        write_bytes_atomically(path, write_xfbin(xfbin))
    except Exception:
        for chunk, old_name, old_path, old_data in previous:
            chunk.name, chunk.filePath, chunk.binary_data = old_name, old_path, old_data
        raise


def duplicate_clip(xfbin, clips: list[LipClip], source: LipClip) -> LipClip:
    new_chunk = NuccChunkBinary(source.file_path, _unique_clip_name(clips, f"{source.name}_copy"))
    new_chunk.has_props = True
    new_chunk.extension = ".binary"
    new_chunk.binary_data = _pack_keys(copy.deepcopy(source.keys))
    new_chunk.filePath = _make_copied_file_path(source.file_path, new_chunk.name)

    page = Page()
    page.chunks.append(new_chunk)
    xfbin.pages.append(page)

    clip = LipClip(
        name=new_chunk.name,
        file_path=new_chunk.filePath,
        page_index=len(xfbin.pages) - 1,
        chunk=new_chunk,
        keys=_parse_keys(new_chunk.binary_data),
    )
    clips.append(clip)
    return clip


def add_clip(xfbin, clips: list[LipClip], source: LipClip | None = None) -> LipClip:
    base_name = f"{source.name}_new" if source is not None and source.name else "lip_clip"
    name = _unique_clip_name(clips, base_name)
    file_path = _make_copied_file_path(source.file_path, name) if source is not None else f"{name}.bin"
    keys = [LipKey()]

    new_chunk = NuccChunkBinary(file_path, name)
    new_chunk.has_props = True
    new_chunk.extension = ".binary"
    new_chunk.binary_data = _pack_keys(keys)
    new_chunk.filePath = file_path

    page = Page()
    page.chunks.append(new_chunk)
    xfbin.pages.append(page)

    clip = LipClip(
        name=new_chunk.name,
        file_path=new_chunk.filePath,
        page_index=len(xfbin.pages) - 1,
        chunk=new_chunk,
        keys=_parse_keys(new_chunk.binary_data),
    )
    clips.append(clip)
    return clip


def delete_clip(xfbin, clips: list[LipClip], clip: LipClip) -> bool:
    if len(clips) <= 1:
        return False
    for page in list(xfbin.pages):
        if clip.chunk not in page.chunks:
            continue
        page.chunks.remove(clip.chunk)
        if not any(isinstance(chunk, NuccChunkBinary) for chunk in page.chunks):
            try:
                xfbin.pages.remove(page)
            except ValueError:
                pass
        clips.remove(clip)
        return True
    return False


def _unique_clip_name(clips: list[LipClip], base_name: str) -> str:
    existing = {clip.name.lower() for clip in clips}
    candidate = base_name
    suffix = 1
    while candidate.lower() in existing:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def _make_copied_file_path(source_path: str, new_name: str) -> str:
    if not source_path:
        return f"{new_name}.bin"
    slash = "/" if "/" in source_path else "\\"
    if slash in source_path:
        directory = source_path.rsplit(slash, 1)[0]
        return f"{directory}/{new_name}.bin"
    return f"{new_name}.bin"
