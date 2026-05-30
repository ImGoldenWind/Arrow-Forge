"""TrophyParam.bin.xfbin parser / writer.

Confirmed sample layout inside the nuccChunkBinary payload:
  [0-3]   uint32 BE  inner size
  [4-7]   uint32 LE  version
  [8-11]  uint32 LE  entry count
  [12-19] uint64 LE  first_ptr, from this field to entries (= 8 in sample)
  [20+]   optional prefix bytes, then entries

Each entry is 8 bytes:
  +0 uint32 LE - trophy id
  +4 uint32 LE - requirement value / threshold

The retail sample contains no strings or explicit field names.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 8
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
        raise ValueError("Could not locate nuccChunkBinary in TrophyParam XFBIN.")
    return best_off, best_size


def parse_trophyparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    body_off = payload_off + INNER_SIZE_FIELD
    inner_end = payload_off + INNER_SIZE_FIELD + struct.unpack_from(">I", data, payload_off)[0]
    chunk_end = payload_off + chunk_size

    if inner_end > chunk_end:
        raise ValueError("Invalid TrophyParam inner size.")

    version = struct.unpack_from("<I", data, body_off)[0]
    count = struct.unpack_from("<I", data, body_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, body_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid TrophyParam header: first_ptr is smaller than 8.")

    prefix_len = first_ptr - 8
    prefix_off = body_off + HEADER_SIZE
    entries_base = body_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > inner_end:
        raise ValueError("TrophyParam entry table exceeds binary chunk size.")

    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        trophy_id, requirement_value = struct.unpack_from("<II", data, base)
        entries.append({
            "index": idx,
            "trophy_id": trophy_id,
            "requirement_value": requirement_value,
        })

    return data, {
        "version": version,
        "prefix_bytes": bytes(data[prefix_off:prefix_off + prefix_len]),
        "tail_bytes": bytes(data[entries_end:inner_end]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None, trophy_id: int = 0) -> dict:
    if source is not None:
        entry = copy.deepcopy(source)
        entry.pop("index", None)
        return entry

    return {
        "trophy_id": trophy_id,
        "requirement_value": 1,
    }


def _build_inner(version: int, prefix_bytes: bytes, tail_bytes: bytes, entries: list[dict]) -> bytes:
    prefix_bytes = bytes(prefix_bytes or b"")
    tail_bytes = bytes(tail_bytes or b"")

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", len(entries))
    buf += struct.pack("<Q", 8 + len(prefix_bytes))
    buf += prefix_bytes

    for entry in entries:
        buf += struct.pack(
            "<II",
            int(entry.get("trophy_id", 0)) & 0xFFFFFFFF,
            int(entry.get("requirement_value", 0)) & 0xFFFFFFFF,
        )

    buf += tail_bytes
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_trophyparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", DEFAULT_VERSION)),
        bytes(result.get("prefix_bytes", b"")),
        bytes(result.get("tail_bytes", b"")),
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
