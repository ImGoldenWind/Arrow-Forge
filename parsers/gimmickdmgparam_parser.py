"""Parser / writer for ASBR gimmickDmgParam.bin.xfbin.

Confirmed from the provided sample:

    0x00 u32  file magic / format id, observed 1000
    0x04 u32  entry count
    0x08 u64  self-relative pointer to the record array (normally 8)

    entry_count * 0x68-byte records:
        0x00 u64  self-relative pointer to stage id string
        0x08 u64  self-relative pointer to damage id string
        0x10..0x64  remaining editable raw fields

    string table:
        null-terminated ASCII strings aligned to 8 bytes, in record order:
        stage id, then damage id.

Only the string pointers and entry count are regenerated on save. Every other
record word is preserved and editable by the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import struct
import os
import tempfile

from parsers.xfbin_lib import NuccChunkBinary, read_xfbin, write_xfbin


HEADER_SIZE = 0x10
RECORD_SIZE = 0x68
WORD_COUNT = RECORD_SIZE // 4
STAGE_PTR_OFF = 0x00
DAMAGE_PTR_OFF = 0x08
STAGE_PTR_WORD = STAGE_PTR_OFF // 4
DAMAGE_PTR_WORD = DAMAGE_PTR_OFF // 4
POINTER_WORDS = {STAGE_PTR_WORD, DAMAGE_PTR_WORD}


FIELD_SPECS = [
    ("stage_ptr_high", 0x04, "u32"),
    ("damage_ptr_high", 0x0C, "u32"),
    ("value_10", 0x10, "f32"),
    ("value_14", 0x14, "f32"),
    ("value_18", 0x18, "f32"),
    ("value_1c", 0x1C, "u32"),
    ("value_20", 0x20, "u32"),
    ("value_24", 0x24, "f32"),
    ("value_28", 0x28, "f32"),
    ("value_2c", 0x2C, "f32"),
    ("value_30", 0x30, "f32"),
    ("value_34", 0x34, "f32"),
    ("value_38", 0x38, "u32"),
    ("value_3c", 0x3C, "u32"),
    ("value_40", 0x40, "u32"),
    ("value_44", 0x44, "u32"),
    ("value_48", 0x48, "u32"),
    ("value_4c", 0x4C, "u32"),
    ("value_50", 0x50, "u32"),
    ("value_54", 0x54, "u32"),
    ("value_58", 0x58, "u32"),
    ("value_5c", 0x5C, "u32"),
    ("value_60", 0x60, "u32"),
    ("value_64", 0x64, "u32"),
]


@dataclass
class GimmickDmgEntry:
    stage_id: str = ""
    damage_id: str = ""
    words: list[int] = field(default_factory=lambda: [0] * WORD_COUNT)


@dataclass
class GimmickDmgParam:
    chunk: NuccChunkBinary
    chunk_name: str
    file_path: str
    magic: int = 1000
    unknown_08: int = 8
    reserved_0c: int = 0
    entries: list[GimmickDmgEntry] = field(default_factory=list)
    raw_bytes: bytes | None = None
    bin_size_offset: int | None = None
    bin_outer_size_offset: int | None = None
    bin_data_offset: int | None = None
    bin_chunk_size: int | None = None
    source_payload: bytes | None = None
    source_entries: list[GimmickDmgEntry] = field(default_factory=list)


def _read_cstr(data: bytes | bytearray, off: int) -> str:
    if off <= 0 or off >= len(data):
        return ""
    try:
        end = data.index(0, off)
    except ValueError:
        end = len(data)
    return data[off:end].decode("ascii", errors="replace")


def _validate_ascii(text: str, field_name: str) -> None:
    if '\0' in str(text):
        raise ValueError(f"{field_name} cannot contain NUL.")
    try:
        str(text).encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be ASCII.") from exc


def _u32(value: int, field_name: str) -> int:
    value = int(value)
    if not (0 <= value <= 0xFFFFFFFF):
        raise ValueError(f"{field_name} must fit in u32.")
    return value


def word_to_float(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", int(value) & 0xFFFFFFFF))[0]


def float_to_word(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def _align8(buf: bytearray) -> None:
    if len(buf) % 8:
        buf.extend(b"\x00" * (8 - (len(buf) % 8)))


def _looks_like_gimmick_dmg(data: bytes | bytearray) -> bool:
    if len(data) < HEADER_SIZE:
        return False
    magic, count, _unknown, _reserved = struct.unpack_from("<4I", data, 0)
    if magic != 1000 or count > 0x10000:
        return False
    records_start = 8 + struct.unpack_from('<Q', data, 8)[0]
    if records_start < HEADER_SIZE or records_start > len(data):
        return False
    records_end = records_start + count * RECORD_SIZE
    if records_end > len(data):
        return False
    blob = bytes(data)
    for idx in range(count):
        rec_off = records_start + idx * RECORD_SIZE
        for ptr_off in (STAGE_PTR_OFF, DAMAGE_PTR_OFF):
            rel = struct.unpack_from("<Q", data, rec_off + ptr_off)[0]
            if rel == 0:
                continue
            target = rec_off + ptr_off + rel
            if target < records_end or target >= len(data):
                return False
            if blob.find(b'\0', target) < 0:
                return False
    return True


def _find_payload_offsets(raw: bytes | bytearray, payload: bytes | bytearray) -> tuple[int, int | None, int, int]:
    data_off = bytes(raw).find(bytes(payload))
    if data_off < 4:
        raise ValueError("gimmickDmgParam payload was not found in the raw XFBIN.")
    size_off = data_off - 4
    chunk_size = struct.unpack(">I", raw[size_off:size_off + 4])[0]
    if chunk_size != len(payload):
        raise ValueError("gimmickDmgParam payload size marker does not match the parsed chunk.")

    outer_size_off = data_off - 0x10
    outer_size = None
    if outer_size_off >= 0:
        candidate = struct.unpack(">I", raw[outer_size_off:outer_size_off + 4])[0]
        if candidate == len(payload) + 4:
            outer_size = outer_size_off
    return size_off, outer_size, data_off, chunk_size


def _parse_chunk(chunk: NuccChunkBinary) -> GimmickDmgParam:
    data = getattr(chunk, "binary_data", None)
    if data is None or not _looks_like_gimmick_dmg(data):
        raise ValueError(f"Binary chunk {chunk.name!r} does not match gimmickDmgParam layout.")

    magic, count, unknown_08, reserved_0c = struct.unpack_from("<4I", data, 0)
    entries: list[GimmickDmgEntry] = []
    records_start = 8 + struct.unpack_from('<Q', data, 8)[0]
    for idx in range(count):
        rec_off = records_start + idx * RECORD_SIZE
        words = list(struct.unpack_from("<" + "I" * WORD_COUNT, data, rec_off))
        stage_rel = struct.unpack_from('<Q', data, rec_off)[0]
        damage_rel = struct.unpack_from('<Q', data, rec_off + 8)[0]
        stage_id = _read_cstr(data, rec_off + STAGE_PTR_OFF + stage_rel) if stage_rel else ""
        damage_id = _read_cstr(data, rec_off + DAMAGE_PTR_OFF + damage_rel) if damage_rel else ""
        entries.append(GimmickDmgEntry(stage_id=stage_id, damage_id=damage_id, words=words))

    return GimmickDmgParam(
        chunk=chunk,
        chunk_name=chunk.name,
        file_path=chunk.filePath,
        magic=magic,
        unknown_08=unknown_08,
        reserved_0c=reserved_0c,
        entries=entries,
        source_payload=bytes(data),
        source_entries=copy.deepcopy(entries),
    )


def _append_string(table: bytearray, text: str, string_base: int) -> int:
    _validate_ascii(text, "String")
    absolute = string_base + len(table)
    table.extend(text.encode("ascii"))
    table.append(0)
    _align8(table)
    return absolute


def _pack_payload(item: GimmickDmgParam) -> bytes:
    if len(item.entries) > 0xFFFFFFFF:
        raise ValueError("gimmickDmgParam has too many entries.")

    # Keep the original string topology, null/empty distinction, padding and
    # opaque tail when the table shape is unchanged. Changed strings append;
    # unchanged pointers and neighboring bytes remain exactly as authored.
    if item.source_payload is not None and len(item.entries) == len(item.source_entries):
        buf = bytearray(item.source_payload)
        start = 8 + struct.unpack_from('<Q', buf, 8)[0]
        struct.pack_into('<I', buf, 0, _u32(item.magic, 'Header magic'))
        for idx, (entry, original) in enumerate(zip(item.entries, item.source_entries)):
            if len(entry.words) != WORD_COUNT:
                raise ValueError('A gimmick damage record has an invalid word count.')
            base = start + idx * RECORD_SIZE
            for n, word in enumerate(entry.words):
                if n in (0, 1, 2, 3):
                    continue
                struct.pack_into('<I', buf, base + n * 4, _u32(word, 'Record word'))
            for off, name in ((0, 'stage_id'), (8, 'damage_id')):
                value = getattr(entry, name)
                if value == getattr(original, name):
                    continue
                _validate_ascii(value, name)
                if value:
                    _align8(buf)
                    relative = len(buf) - base - off
                    buf.extend(value.encode('ascii') + b'\0')
                    _align8(buf)
                else:
                    relative = 0
                struct.pack_into('<Q', buf, base + off, relative)
        return bytes(buf)

    records = bytearray(len(item.entries) * RECORD_SIZE)
    records_start = (8 + struct.unpack_from('<Q', item.source_payload, 8)[0]
                     if item.source_payload is not None else HEADER_SIZE)
    string_base = records_start + len(records)
    strings = bytearray()

    for idx, entry in enumerate(item.entries):
        if len(entry.words) != WORD_COUNT:
            raise ValueError("A gimmick damage record has an invalid word count.")

        rec_off = records_start + idx * RECORD_SIZE
        words = [_u32(word, f"record {idx} word {word_idx}") for word_idx, word in enumerate(entry.words)]

        words[STAGE_PTR_WORD] = 0
        words[DAMAGE_PTR_WORD] = 0
        words[1] = words[3] = 0

        if entry.stage_id or entry.words[0] or entry.words[1]:
            stage_abs = _append_string(strings, entry.stage_id, string_base)
            words[STAGE_PTR_WORD] = _u32(stage_abs - (rec_off + STAGE_PTR_OFF), "Stage ID pointer")
        if entry.damage_id or entry.words[2] or entry.words[3]:
            damage_abs = _append_string(strings, entry.damage_id, string_base)
            words[DAMAGE_PTR_WORD] = _u32(damage_abs - (rec_off + DAMAGE_PTR_OFF), "Damage ID pointer")

        struct.pack_into("<" + "I" * WORD_COUNT, records, idx * RECORD_SIZE, *words)

    buf = (bytearray(item.source_payload[:records_start]) if item.source_payload is not None
           else bytearray(HEADER_SIZE))
    struct.pack_into(
        "<4I",
        buf,
        0,
        _u32(item.magic, "Header magic"),
        len(item.entries),
        records_start - 8,
        0,
    )
    buf.extend(records)
    buf.extend(strings)
    if item.source_payload is not None:
        # Preserve the original string storage/opaque suffix on structural edits.
        old_start = 8 + struct.unpack_from('<Q', item.source_payload, 8)[0]
        old_end = old_start + len(item.source_entries) * RECORD_SIZE
        buf.extend(item.source_payload[old_end:])
    return bytes(buf)


def _atomic_write(path, data):
    target = os.path.abspath(path)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-gimmick-', dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _accept_payload(item, payload):
    start = 8 + struct.unpack_from('<Q', payload, 8)[0]
    for index, entry in enumerate(item.entries):
        entry.words[:4] = struct.unpack_from('<4I', payload, start + index * RECORD_SIZE)
    item.source_payload = payload
    item.source_entries = copy.deepcopy(item.entries)


def load_gimmickdmgparam_xfbin(path: str):
    with open(path, "rb") as fh:
        raw = fh.read()

    xfbin = read_xfbin(path)
    for page in xfbin.pages:
        for chunk in page.chunks:
            if not isinstance(chunk, NuccChunkBinary):
                continue
            data = getattr(chunk, "binary_data", None)
            if data is not None and _looks_like_gimmick_dmg(data):
                item = _parse_chunk(chunk)
                bin_size_offset, bin_outer_size_offset, bin_data_offset, bin_chunk_size = _find_payload_offsets(raw, data)
                item.raw_bytes = raw
                item.bin_size_offset = bin_size_offset
                item.bin_outer_size_offset = bin_outer_size_offset
                item.bin_data_offset = bin_data_offset
                item.bin_chunk_size = bin_chunk_size
                return xfbin, item
    raise ValueError("No gimmickDmgParam binary chunk was found in this XFBIN.")


def save_gimmickdmgparam_xfbin(xfbin, path: str, item: GimmickDmgParam) -> None:
    _validate_ascii(item.chunk_name, "Chunk name")
    _validate_ascii(item.file_path, "Chunk file path")
    payload = _pack_payload(item)

    can_raw_save = (
        item.raw_bytes is not None
        and item.bin_size_offset is not None
        and item.bin_data_offset is not None
        and item.bin_chunk_size is not None
        and item.chunk_name == item.chunk.name
        and item.file_path == item.chunk.filePath
    )
    if can_raw_save:
        old_end = item.bin_data_offset + item.bin_chunk_size

        prefix = bytearray(item.raw_bytes[:item.bin_data_offset])
        struct.pack_into(">I", prefix, item.bin_size_offset, len(payload))
        if item.bin_outer_size_offset is not None:
            struct.pack_into(">I", prefix, item.bin_outer_size_offset, len(payload) + 4)
        buf = (
            bytes(prefix)
            + payload
            + item.raw_bytes[old_end:]
        )
        _atomic_write(path, buf)
        item.raw_bytes = bytes(buf)
        item.bin_chunk_size = len(payload)
        item.chunk.binary_data = payload
        _accept_payload(item, payload)
        return

    staged_xfbin, staged_chunk = copy.deepcopy((xfbin, item.chunk))
    staged_chunk.name = item.chunk_name
    staged_chunk.filePath = item.file_path
    staged_chunk.binary_data = payload
    staged_chunk.has_props = True
    staged_chunk.extension = ".binary"
    buf = bytes(write_xfbin(staged_xfbin))
    offsets = _find_payload_offsets(buf, payload)
    _atomic_write(path, buf)
    item.chunk.name = item.chunk_name
    item.chunk.filePath = item.file_path
    item.chunk.binary_data = payload
    item.chunk.has_props = True
    item.chunk.extension = '.binary'
    item.raw_bytes = buf
    item.bin_size_offset, item.bin_outer_size_offset, item.bin_data_offset, item.bin_chunk_size = offsets
    _accept_payload(item, payload)


def make_default_entry(source: GimmickDmgEntry | None = None) -> GimmickDmgEntry:
    if source is not None:
        return copy.deepcopy(source)
    words = [0] * WORD_COUNT
    words[1] = 0
    words[3] = 0
    words[0x3C // 4:0x64 // 4] = [0xFFFFFFFF] * 10
    return GimmickDmgEntry(stage_id="STAGE_NEW", damage_id="DAMAGE_ID_NONE", words=words)
