"""TutorialParam.bin.xfbin parser / writer.

Confirmed retail layout inside the nuccChunkBinary payload:
  [0-3]   uint32 BE  inner size
  [4-7]   uint32 LE  version
  [8-11]  uint32 LE  entry count
  [12-19] uint64 LE  first_ptr (= 8 in the sample)
  [20+]   entries * 88 bytes, followed by an ASCII string pool

Each entry is 0x58 bytes. String fields are self-relative 64-bit pointers
from the pointer field itself to a null-terminated ASCII string.

Only the structure and repeated value patterns are confirmed by the file.
The file does not label most numeric fields, so the editor exposes them with
offset-based names and testing hints instead of invented meanings.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 88
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000

STRING_FIELDS = (
    ("category", 0x00),
    ("asset_path", 0x08),
    ("text_key", 0x18),
    ("dummy_key", 0x20),
)

UINT_FIELDS = (
    ("entry_type", 0x10),
    ("raw_28", 0x28),
    ("raw_2c", 0x2C),
    ("raw_30", 0x30),
    ("raw_44", 0x44),
    ("raw_48", 0x48),
    ("raw_50", 0x50),
    ("reserved_54", 0x54),
)

FLOAT_FIELDS = (
    ("value_34", 0x34),
    ("value_38", 0x38),
    ("value_3c", 0x3C),
    ("value_40", 0x40),
    ("value_4c", 0x4C),
)


def _find_binary_chunk(data: bytes | bytearray) -> tuple[int, int]:
    if len(data) < 28 or data[:4] != b"NUCC":
        raise ValueError("Not a NUCC/XFBIN file.")

    table_size = struct.unpack_from(">I", data, 16)[0]
    offset = 28 + table_size
    if offset % 4:
        offset += 4 - offset % 4

    best_off = -1
    best_size = 0
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        map_idx = struct.unpack_from(">I", data, offset + 4)[0]
        if map_idx == 1 and size >= INNER_SIZE_FIELD + HEADER_SIZE and size > best_size:
            best_off = offset
            best_size = size

        next_off = offset + 12 + (size if size else 0)
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    if best_off < 0:
        raise ValueError("Could not locate nuccChunkBinary in TutorialParam XFBIN.")
    return best_off, best_size


def _read_cstr(data: bytes | bytearray, offset: int, limit: int) -> str:
    if offset <= 0 or offset >= limit:
        return ""
    end = data.find(b"\x00", offset, limit)
    if end < 0:
        end = limit
    return data[offset:end].decode("ascii", errors="replace")


def _read_rel_string(data: bytes | bytearray, field_abs: int, ptr: int, limit: int) -> str:
    if not ptr:
        return ""
    return _read_cstr(data, field_abs + ptr, limit)


def parse_tutorialparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    param_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid TutorialParam inner size.")

    version = struct.unpack_from("<I", data, param_off)[0]
    count = struct.unpack_from("<I", data, param_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, param_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid TutorialParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = param_off + HEADER_SIZE
    entries_base = param_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("TutorialParam entry table exceeds binary chunk size.")

    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        entry = {"index": idx}
        for key, rel_off in STRING_FIELDS:
            ptr = struct.unpack_from("<Q", data, base + rel_off)[0]
            entry[key] = _read_rel_string(data, base + rel_off, ptr, chunk_end)
        for key, rel_off in UINT_FIELDS:
            entry[key] = struct.unpack_from("<I", data, base + rel_off)[0]
        for key, rel_off in FLOAT_FIELDS:
            entry[key] = struct.unpack_from("<f", data, base + rel_off)[0]
        entries.append(entry)

    return data, {
        "version": version,
        "notes": bytes(data[notes_off:notes_off + notes_len]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None) -> dict:
    if source is not None:
        entry = copy.deepcopy(source)
        entry.pop("index", None)
        return entry

    return {
        "category": "",
        "asset_path": "",
        "entry_type": 1,
        "text_key": "tutorial_new",
        "dummy_key": "dmy_tutorial_new",
        "raw_28": 0,
        "raw_2c": 0,
        "raw_30": 0,
        "value_34": 24.0,
        "value_38": -1.0,
        "value_3c": 0.0,
        "value_40": 0.0,
        "raw_44": 0,
        "raw_48": 0,
        "value_4c": 24.0,
        "raw_50": 0,
        "reserved_54": 0,
    }


def _pad8(pool: bytearray, text: str) -> int:
    off = len(pool)
    pool.extend(text.encode("ascii", errors="replace") + b"\x00")
    rem = len(pool) % 8
    if rem:
        pool.extend(b"\x00" * (8 - rem))
    return off


def _build_inner(version: int, notes: bytes, entries: list[dict]) -> bytes:
    count = len(entries)
    notes = bytes(notes or b"")
    entries_base_inner = HEADER_SIZE + len(notes)
    pool_abs = INNER_SIZE_FIELD + entries_base_inner + count * ENTRY_SIZE

    pool = bytearray()
    string_offsets: list[dict[str, int | None]] = []
    for entry in entries:
        offsets: dict[str, int | None] = {}
        for key, _rel_off in STRING_FIELDS:
            text = str(entry.get(key, ""))
            offsets[key] = _pad8(pool, text) if text else None
        string_offsets.append(offsets)

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8 + len(notes))
    buf += notes

    for idx, entry in enumerate(entries):
        entry_abs = INNER_SIZE_FIELD + entries_base_inner + idx * ENTRY_SIZE
        row = bytearray(ENTRY_SIZE)

        for key, rel_off in UINT_FIELDS:
            struct.pack_into("<I", row, rel_off, int(entry.get(key, 0)) & 0xFFFFFFFF)
        for key, rel_off in FLOAT_FIELDS:
            struct.pack_into("<f", row, rel_off, float(entry.get(key, 0.0)))
        for key, rel_off in STRING_FIELDS:
            string_off = string_offsets[idx][key]
            ptr = 0 if string_off is None else pool_abs + int(string_off) - (entry_abs + rel_off)
            struct.pack_into("<Q", row, rel_off, ptr & 0xFFFFFFFFFFFFFFFF)

        buf += row

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_tutorialparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", DEFAULT_VERSION)),
        bytes(result.get("notes", b"")),
        list(result.get("entries", [])),
    )
    payload = struct.pack(">I", len(inner)) + inner
    if len(payload) % 4:
        payload += b"\x00" * (4 - len(payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)
    prefix = bytes(original_data[:chunk_hdr_off])
    chunk_hdr = bytearray(original_data[chunk_hdr_off:chunk_hdr_off + 12])
    struct.pack_into(">I", chunk_hdr, 0, len(payload))

    orig_payload_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(original_data[orig_payload_end:])

    with open(filepath, "wb") as fh:
        fh.write(prefix + bytes(chunk_hdr) + payload + trailing)
