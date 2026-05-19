"""ArcadeRewardParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  - inner_size (bytes after this field)
  [4-7]   uint32 LE  - version    (1000 in the sample)
  [8-11]  uint32 LE  - entry count (35 in the sample)
  [12-19] uint64 LE  - first_ptr, from this field to Entries (= 8)
  [20+]   optional notes bytes, then entries

Each entry is 40 bytes and uses a self-relative string pointer:
  +0   uint64 LE - pointer to reward_id string
  +8   uint32 LE - difficulty_index
  +12  uint32 LE - battle_step / progression value
  +16  uint64 LE - reserved_1
  +24  uint64 LE - reserved_2
  +32  uint64 LE - reward_value

Strings are null-terminated ASCII and 8-byte aligned.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 40
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000


def _read_cstr(data: bytes | bytearray, off: int) -> str:
    if off >= len(data):
        return ""
    try:
        end = data.index(b"\x00", off)
        raw = data[off:end]
    except ValueError:
        raw = data[off:]
    return raw.decode("ascii", errors="replace")


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
        raise ValueError("Could not locate nuccChunkBinary in ArcadeRewardParam XFBIN.")
    return best_off, best_size


def parse_arcaderewardparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    arcade_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid ArcadeRewardParam inner size.")

    version = struct.unpack_from("<I", data, arcade_off)[0]
    count = struct.unpack_from("<I", data, arcade_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, arcade_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid ArcadeRewardParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = arcade_off + HEADER_SIZE
    entries_base = arcade_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("ArcadeRewardParam entry table exceeds binary chunk size.")

    entries = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        ptr, difficulty_index, battle_step, reserved_1, reserved_2, reward_value = struct.unpack_from(
            "<QIIQQQ",
            data,
            base,
        )
        reward_id = _read_cstr(data, base + ptr) if ptr else ""
        entries.append({
            "reward_id": reward_id,
            "difficulty_index": difficulty_index,
            "battle_step": battle_step,
            "reserved_1": reserved_1,
            "reserved_2": reserved_2,
            "reward_value": reward_value,
        })

    return data, {
        "version": version,
        "notes": bytes(data[notes_off:notes_off + notes_len]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None) -> dict:
    if source:
        return copy.deepcopy(source)
    return {
        "reward_id": "NORMAL_1",
        "difficulty_index": 2,
        "battle_step": 1,
        "reserved_1": 0,
        "reserved_2": 0,
        "reward_value": 0,
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
    first_ptr = 8 + len(notes)
    entries_base = 8 + first_ptr
    pool_base = entries_base + count * ENTRY_SIZE

    pool = bytearray()
    string_offsets = []
    for entry in entries:
        string_offsets.append(_pad8(pool, str(entry.get("reward_id", ""))))

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", first_ptr)
    buf += notes

    for idx, entry in enumerate(entries):
        entry_base = entries_base + idx * ENTRY_SIZE
        ptr = pool_base + string_offsets[idx] - entry_base
        buf += struct.pack(
            "<QIIQQQ",
            ptr,
            int(entry.get("difficulty_index", 0)) & 0xFFFFFFFF,
            int(entry.get("battle_step", 0)) & 0xFFFFFFFF,
            int(entry.get("reserved_1", 0)) & 0xFFFFFFFFFFFFFFFF,
            int(entry.get("reserved_2", 0)) & 0xFFFFFFFFFFFFFFFF,
            int(entry.get("reward_value", 0)) & 0xFFFFFFFFFFFFFFFF,
        )

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_arcaderewardparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
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
