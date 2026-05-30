"""OnlineMissionParam.bin.xfbin parser / writer.

Confirmed retail layout inside the nuccChunkBinary payload:
  [0-3]   uint32 BE  inner size
  [4-7]   uint32 LE  version
  [8-11]  uint32 LE  entry count
  [12-19] uint64 LE  first_ptr (= 8 in the sample)
  [20+]   entries * 104 bytes, followed by an ASCII string pool

Each entry is 0x68 bytes. Pointer fields are self-relative 64-bit pointers
from the pointer field itself to a null-terminated ASCII string.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 104
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000

STRING_FIELDS = (
    ("character_id", 0x18),
    ("stage_id", 0x30),
    ("title_key", 0x38),
    ("condition_id", 0x48),
    ("reward_card_id", 0x58),
    ("banner_id", 0x60),
)

NUMERIC_FIELDS = (
    ("group_id", 0x00),
    ("mission_id", 0x04),
    ("flag_08", 0x08),
    ("mission_type", 0x0C),
    ("subtype_id", 0x10),
    ("raw_14", 0x14),
    ("raw_20", 0x20),
    ("raw_24", 0x24),
    ("objective_value", 0x28),
    ("raw_2c", 0x2C),
    ("display_slot", 0x40),
    ("raw_44", 0x44),
    ("reward_value", 0x50),
    ("reward_type", 0x54),
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
        raise ValueError("Could not locate nuccChunkBinary in OnlineMissionParam XFBIN.")
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


def parse_onlinemissionparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    param_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid OnlineMissionParam inner size.")

    version = struct.unpack_from("<I", data, param_off)[0]
    count = struct.unpack_from("<I", data, param_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, param_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid OnlineMissionParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = param_off + HEADER_SIZE
    entries_base = notes_off + notes_len
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("OnlineMissionParam entry table exceeds binary chunk size.")

    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        entry = {"index": idx}
        for key, rel_off in NUMERIC_FIELDS:
            entry[key] = struct.unpack_from("<I", data, base + rel_off)[0]
        for key, rel_off in STRING_FIELDS:
            ptr = struct.unpack_from("<Q", data, base + rel_off)[0]
            entry[key] = _read_rel_string(data, base + rel_off, ptr, chunk_end)
        entries.append(entry)

    return data, {
        "version": version,
        "notes": bytes(data[notes_off:entries_base]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None) -> dict:
    if source is not None:
        entry = copy.deepcopy(source)
        entry.pop("index", None)
        return entry

    return {
        "group_id": 0,
        "mission_id": 0,
        "flag_08": 0,
        "mission_type": 6,
        "subtype_id": 0,
        "raw_14": 0,
        "character_id": "",
        "raw_20": 0,
        "raw_24": 0,
        "objective_value": 1,
        "raw_2c": 0,
        "stage_id": "",
        "title_key": "online_mission_t_new",
        "display_slot": 0,
        "raw_44": 0,
        "condition_id": "",
        "reward_value": 0,
        "reward_type": 6,
        "reward_card_id": "",
        "banner_id": "",
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

        for key, rel_off in NUMERIC_FIELDS:
            struct.pack_into("<I", row, rel_off, int(entry.get(key, 0)) & 0xFFFFFFFF)

        for key, rel_off in STRING_FIELDS:
            string_off = string_offsets[idx][key]
            ptr = 0 if string_off is None else pool_abs + int(string_off) - (entry_abs + rel_off)
            struct.pack_into("<Q", row, rel_off, ptr & 0xFFFFFFFFFFFFFFFF)

        buf += row

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_onlinemissionparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
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
