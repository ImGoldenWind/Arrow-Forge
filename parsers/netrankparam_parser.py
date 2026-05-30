"""NetRankParam.bin.xfbin parser / writer.

Confirmed retail layout inside the nuccChunkBinary payload:
  [0-3]   uint32 BE  inner size
  [4-7]   uint32 LE  version
  [8-11]  uint32 LE  entry count
  [12-19] uint64 LE  first_ptr (= 8 in the sample)
  [20+]   entries * 16 bytes, followed by an ASCII string pool

Each entry is 0x10 bytes:
  +0 uint32 LE - rank id
  +4 uint32 LE - required points / rank threshold
  +8 uint64 LE - self-relative pointer to a null-terminated ASCII rank name key
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 16
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000


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
        raise ValueError("Could not locate nuccChunkBinary in NetRankParam XFBIN.")
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


def parse_netrankparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    param_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid NetRankParam inner size.")

    version = struct.unpack_from("<I", data, param_off)[0]
    count = struct.unpack_from("<I", data, param_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, param_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid NetRankParam header: first_ptr is smaller than 8.")

    prefix_len = first_ptr - 8
    prefix_off = param_off + HEADER_SIZE
    entries_base = param_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("NetRankParam entry table exceeds binary chunk size.")

    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        rank_id, required_points = struct.unpack_from("<II", data, base)
        name_ptr = struct.unpack_from("<Q", data, base + 8)[0]
        entries.append({
            "index": idx,
            "rank_id": rank_id,
            "required_points": required_points,
            "name_key": _read_rel_string(data, base + 8, name_ptr, chunk_end),
        })

    return data, {
        "version": version,
        "prefix_bytes": bytes(data[prefix_off:prefix_off + prefix_len]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None, rank_id: int = 0) -> dict:
    if source is not None:
        entry = copy.deepcopy(source)
        entry.pop("index", None)
        return entry

    return {
        "rank_id": rank_id,
        "required_points": 0,
        "name_key": f"rankname_{rank_id:03d}",
    }


def _pad8(pool: bytearray, text: str) -> int:
    off = len(pool)
    pool.extend(text.encode("ascii", errors="replace") + b"\x00")
    rem = len(pool) % 8
    if rem:
        pool.extend(b"\x00" * (8 - rem))
    return off


def _build_inner(version: int, prefix_bytes: bytes, entries: list[dict]) -> bytes:
    count = len(entries)
    prefix_bytes = bytes(prefix_bytes or b"")
    entries_base_inner = HEADER_SIZE + len(prefix_bytes)
    pool_abs = INNER_SIZE_FIELD + entries_base_inner + count * ENTRY_SIZE

    pool = bytearray()
    string_offsets: list[int | None] = []
    for entry in entries:
        text = str(entry.get("name_key", ""))
        string_offsets.append(_pad8(pool, text) if text else None)

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8 + len(prefix_bytes))
    buf += prefix_bytes

    for idx, entry in enumerate(entries):
        entry_abs = INNER_SIZE_FIELD + entries_base_inner + idx * ENTRY_SIZE
        row = bytearray(ENTRY_SIZE)
        struct.pack_into("<I", row, 0x00, int(entry.get("rank_id", 0)) & 0xFFFFFFFF)
        struct.pack_into("<I", row, 0x04, int(entry.get("required_points", 0)) & 0xFFFFFFFF)

        string_off = string_offsets[idx]
        ptr = 0 if string_off is None else pool_abs + int(string_off) - (entry_abs + 0x08)
        struct.pack_into("<Q", row, 0x08, ptr & 0xFFFFFFFFFFFFFFFF)
        buf += row

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_netrankparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", DEFAULT_VERSION)),
        bytes(result.get("prefix_bytes", b"")),
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
