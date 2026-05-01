"""parsers/dlcinfoparam_parser.py  –  DlcInfoParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  – inner_size  (bytes that follow)
  [4-7]   uint32 LE  – version     (1000)
  [8-11]  uint32 LE  – entry count
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes section)
  [20+]   entries × 32 bytes each

Each entry (32 bytes):
  +0   uint64 LE  – relative ptr → Type  string  (e.g. "GIFT01")
  +8   uint64 LE  – relative ptr → Name  string  (e.g. "JASBRCOSSPCOSSET")
  +16  uint64 LE  – relative ptr → Code  string  (e.g. "9MXZ8SM3R6BN")
  +24  uint32 LE  – index   (group index, e.g. 1 or 2)
  +28  uint32 LE  – dlc_id  (unique DLC identifier, e.g. 10000)

String pool: null-terminated ASCII, each string padded to 8-byte boundary.
Strings are laid out per-entry: type0, name0, code0, type1, name1, code1, ...

Pointer resolution (same convention as CustomizeDefaultParam):
  string_abs = ptr_field_abs_offset + pointer_value
  i.e. the stored uint64 is relative to the field's own position in the file.

Known retail entries (4 DLC gift packs):
  GIFT01 / JASBRCOSSPCOSSET / 9MXZ8SM3R6BN  index=1  dlc_id=10000
  GIFT02 / JASBRCOSJOLYN6SP / 9NPRJ1RK4MSF  index=1  dlc_id=10001
  GIFT03 / JASBRCOSROHAN4SP / 9NLD47HGBKMG  index=2  dlc_id=10002
  GIFT04 / JASBRCOSFATHERSP / 9NBG6W8DB7WR  index=2  dlc_id=10003
"""

import struct

ENTRY_SIZE    = 32   # bytes per entry
HEADER_SIZE   = 16   # version(4) + count(4) + first_ptr(8)
_INNER_SZ_FLD =  4   # leading BE uint32 inner_size in payload


# Low-level helpers

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
    """Return (chunk_header_offset, chunk_data_size) for the nuccChunkBinary.

    DlcInfoParam uses type_idx=0 (not 1) and size=340 – neither of which
    matches the generic condition used by other parsers.  Instead we look for
    the first chunk whose size is large enough to hold at least the 20-byte
    binary header (inner_size + version + count + first_ptr).
    """
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    best_off  = -1
    best_size = 0

    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset: offset + 4])[0]

        # The binary data chunk is the largest non-trivial chunk
        if size >= 20 and size > best_size:
            best_off  = offset
            best_size = size

        if size == 0:
            next_off = offset + 12
        else:
            next_off = offset + 12 + size
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    if best_off == -1:
        raise ValueError("Could not locate nuccChunkBinary in DlcInfoParam XFBIN.")

    return best_off, best_size


# Public API

def parse_dlcinfoparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse DlcInfoParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        type_str  str   – gift type identifier, e.g. "GIFT01"
        name      str   – internal DLC asset name, e.g. "JASBRCOSSPCOSSET"
        code      str   – product/redemption code,  e.g. "9MXZ8SM3R6BN"
        index     int   – group index (1 or 2 in retail)
        dlc_id    int   – unique DLC identifier (10000–10003 in retail)
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12

    spm_off   = payload_off + _INNER_SZ_FLD
    version   = struct.unpack_from("<I", data, spm_off)[0]
    count     = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8

    entries_base = spm_off + HEADER_SIZE + notes_len

    entries: list[dict] = []
    for i in range(count):
        base = entries_base + i * ENTRY_SIZE

        ptr_type = struct.unpack_from("<Q", data, base)[0]
        type_str = _read_cstr(data, base + ptr_type)

        ptr_name = struct.unpack_from("<Q", data, base + 8)[0]
        name_str = _read_cstr(data, base + 8 + ptr_name)

        ptr_code = struct.unpack_from("<Q", data, base + 16)[0]
        code_str = _read_cstr(data, base + 16 + ptr_code)

        index  = struct.unpack_from("<I", data, base + 24)[0]
        dlc_id = struct.unpack_from("<I", data, base + 28)[0]

        entries.append({
            "type_str": type_str,
            "name":     name_str,
            "code":     code_str,
            "index":    index,
            "dlc_id":   dlc_id,
        })

    return data, version, entries


def make_default_entry() -> dict:
    """Return a new blank entry with sensible defaults."""
    return {
        "type_str": "GIFT01",
        "name":     "",
        "code":     "",
        "index":    1,
        "dlc_id":   10000,
    }


def _build_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner binary payload (without the 4-byte BE inner_size field).

    Layout:
      version(4) count(4) first_ptr(8)          ← HEADER_SIZE = 16
      entries × ENTRY_SIZE                       ← 32 bytes each
      string pool (per-entry: type, name, code; each padded to 8 bytes)
    """
    count = len(entries)

    # 1. Build string pool
    pool: bytearray = bytearray()

    # pool_offsets[i] = (type_off, name_off, code_off) relative to pool start
    pool_offsets: list[tuple[int, int, int]] = []

    for e in entries:
        type_off = len(pool)
        for s in (e.get("type_str", ""), e.get("name", ""), e.get("code", "")):
            encoded = s.encode("ascii", errors="replace") + b"\x00"
            pool.extend(encoded)
            pad = (8 - len(pool) % 8) % 8
            if pad:
                pool.extend(b"\x00" * pad)
        # record where each string for this entry starts
        # recompute from scratch since we track running total above
    # redo: we need the per-string offsets, so rebuild properly
    pool = bytearray()
    pool_offsets_flat: list[int] = []  # flat: [type0, name0, code0, type1, ...]

    for e in entries:
        for field in ("type_str", "name", "code"):
            s = e.get(field, "")
            off = len(pool)
            pool_offsets_flat.append(off)
            encoded = s.encode("ascii", errors="replace") + b"\x00"
            pool.extend(encoded)
            rem = len(pool) % 8
            if rem:
                pool.extend(b"\x00" * (8 - rem))

    # pool_abs = absolute offset of string pool inside the full payload
    # (counting the 4-byte inner_size field at the very start of payload)
    pool_abs = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 2. Assemble binary
    buf = bytearray()

    # Header (no inner_size here – caller prepends it)
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)   # first_ptr = 8 (no notes)

    for i, e in enumerate(entries):
        entry_abs  = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE

        type_str_abs = pool_abs + pool_offsets_flat[i * 3 + 0]
        name_str_abs = pool_abs + pool_offsets_flat[i * 3 + 1]
        code_str_abs = pool_abs + pool_offsets_flat[i * 3 + 2]

        # field absolute positions inside payload
        type_field_abs = entry_abs + 0
        name_field_abs = entry_abs + 8
        code_field_abs = entry_abs + 16

        buf += struct.pack("<Q", type_str_abs - type_field_abs)
        buf += struct.pack("<Q", name_str_abs - name_field_abs)
        buf += struct.pack("<Q", code_str_abs - code_field_abs)
        buf += struct.pack("<I", int(e.get("index",  1)))
        buf += struct.pack("<I", int(e.get("dlc_id", 0)))

    buf += pool

    # Pad entire inner binary to 4-byte boundary
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_dlcinfoparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated DLC entry data and write to filepath."""
    new_inner   = _build_binary(version, entries)
    inner_size  = len(new_inner)
    new_payload = struct.pack(">I", inner_size) + new_inner

    if len(new_payload) % 4:
        new_payload += b"\x00" * (4 - len(new_payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)

    prefix   = bytes(original_data[:chunk_hdr_off])
    orig_hdr = bytearray(original_data[chunk_hdr_off: chunk_hdr_off + 12])
    struct.pack_into(">I", orig_hdr, 0, len(new_payload))
    new_hdr  = bytes(orig_hdr)

    orig_payload_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(original_data[orig_payload_end:])

    with open(filepath, "wb") as fh:
        fh.write(prefix + new_hdr + new_payload + trailing)
