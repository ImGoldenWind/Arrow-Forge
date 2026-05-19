"""TermListParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  - inner_size (bytes after this field)
  [4-7]   uint32 LE  - version
  [8-11]  uint32 LE  - entry count
  [12-19] uint64 LE  - first_ptr, from this field to entries
  [20+]   optional notes bytes, then entries

Each entry is 48 bytes:
  +0   uint64 LE  - group / section id (retail sample uses 0, 1, 2)
  +8   uint64 LE  - title text key pointer
  +16  uint64 LE  - unknown_16 (retail sample is 0)
  +24  uint64 LE  - description text key pointer
  +32  uint64 LE  - optional term image XFBIN path pointer
  +40  uint64 LE  - optional term image name pointer
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 48
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
STRING_FIELDS = (
    ("title_key", 8),
    ("description_key", 24),
    ("image_file", 32),
    ("image_name", 40),
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
        raise ValueError("Could not locate nuccChunkBinary in TermListParam XFBIN.")
    return best_off, best_size


def _read_cstr(data: bytes | bytearray, off: int, limit: int) -> str:
    if off < 0 or off >= limit:
        return ""
    try:
        end = data.index(b"\x00", off, limit)
    except ValueError:
        end = limit
    return bytes(data[off:end]).decode("ascii", errors="replace")


def parse_termlistparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    term_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid TermListParam inner size.")

    version = struct.unpack_from("<I", data, term_off)[0]
    count = struct.unpack_from("<I", data, term_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, term_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid TermListParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = term_off + HEADER_SIZE
    entries_base = term_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("TermListParam entry table exceeds binary chunk size.")

    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        entry = {
            "group_id": struct.unpack_from("<Q", data, base)[0],
            "unknown_16": struct.unpack_from("<Q", data, base + 16)[0],
        }
        for key, field_off in STRING_FIELDS:
            ptr = struct.unpack_from("<Q", data, base + field_off)[0]
            entry[key] = "" if ptr == 0 else _read_cstr(data, base + field_off + ptr, chunk_end)
        entries.append(entry)

    return data, {
        "version": version,
        "notes": bytes(data[notes_off:notes_off + notes_len]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None) -> dict:
    if source:
        return copy.deepcopy(source)
    return {
        "group_id": 0,
        "title_key": "btlcmd_s_new",
        "unknown_16": 0,
        "description_key": "btlcmd_exp_new",
        "image_file": "",
        "image_name": "",
    }


def _pad_string(pool: bytearray, text: str) -> int:
    off = len(pool)
    pool.extend(str(text).encode("ascii", errors="replace") + b"\x00")
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
    offsets: list[dict[str, int | None]] = []
    for entry in entries:
        entry_offsets: dict[str, int | None] = {}
        for key, _field_off in STRING_FIELDS:
            text = str(entry.get(key, ""))
            entry_offsets[key] = _pad_string(pool, text) if text else None
        offsets.append(entry_offsets)

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", first_ptr)
    buf += notes

    for idx, entry in enumerate(entries):
        entry_base = INNER_SIZE_FIELD + entries_base + idx * ENTRY_SIZE
        entry_buf = bytearray(ENTRY_SIZE)
        struct.pack_into("<Q", entry_buf, 0, int(entry.get("group_id", 0)) & 0xFFFFFFFFFFFFFFFF)
        struct.pack_into("<Q", entry_buf, 16, int(entry.get("unknown_16", 0)) & 0xFFFFFFFFFFFFFFFF)
        for key, field_off in STRING_FIELDS:
            pool_off = offsets[idx][key]
            ptr = 0 if pool_off is None else INNER_SIZE_FIELD + pool_base + int(pool_off) - (entry_base + field_off)
            struct.pack_into("<Q", entry_buf, field_off, ptr)
        buf += entry_buf

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_termlistparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", 1000)),
        bytes(result.get("notes", b"")),
        list(result.get("entries", [])),
    )
    payload = struct.pack(">I", len(inner)) + inner
    if len(payload) % 4:
        payload += b"\x00" * (4 - len(payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)
    chunk_hdr = bytearray(original_data[chunk_hdr_off:chunk_hdr_off + 12])
    struct.pack_into(">I", chunk_hdr, 0, len(payload))

    orig_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_end % 4:
        orig_end += 4 - orig_end % 4

    with open(filepath, "wb") as fh:
        fh.write(bytes(original_data[:chunk_hdr_off]) + bytes(chunk_hdr) + payload + bytes(original_data[orig_end:]))
