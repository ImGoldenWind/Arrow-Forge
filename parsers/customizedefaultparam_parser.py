"""parsers/customizedefaultparam_parser.py  –  CustomizeDefaultParam.bin.xfbin parser / writer.

Binary layout (inside the XFBIN nuccChunkBinary payload):
  [0-3]   uint32 BE  – inner_size  (bytes that follow)
  [4-7]   uint32 LE  – version     (1000)
  [8-11]  uint32 LE  – entry count (180 in retail = 60 chars × 3 slots)
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes section)
  [20+]   entries × 32 bytes each

Each entry (32 bytes):
  +0   uint64 LE  – relative ptr → char_code string  (e.g. "1jnt01")
  +8   uint32 LE  – slot index   (0 = Normal A, 1 = Normal B, 2 = Zoom)
  +12  float32 LE – pos_x        (horizontal position on screen)
  +16  float32 LE – pos_y        (vertical position on screen)
  +20  float32 LE – unk          (always 0.0 in retail)
  +24  float32 LE – scale        (model scale factor)
  +28  float32 LE – unk2         (always 0.0 in retail)

String pool: null-terminated ASCII, each string padded to 8-byte boundary.

Pointer resolution:
  string is at absolute offset:  ptr_field_offset + pointer_value
  where ptr_field_offset = absolute file offset of the uint64 field itself.

Typical retail values:
  Slot 0 & 1: pos_x=480.0, pos_y=576.0, scale=1.0   (normal preview)
  Slot 2:     pos_x=980.0, pos_y=320.0, scale=1.8    (zoom/detail view)
"""

import struct

ENTRY_SIZE   = 32   # bytes per entry
HEADER_SIZE  = 16   # version(4) + count(4) + first_ptr(8)
_INNER_SZ_FLD = 4   # leading BE uint32 inner_size in payload


# Known character codes (retail)
KNOWN_CHAR_CODES = [
    # Part 1
    "1jnt01", "1zpl01", "1dio01", "1sdw01",
    # Part 2
    "2jsp01", "2csr01", "2lsa01", "2wmu01", "2esd01", "2krs01",
    # Part 3
    "3jtr01", "3jsp01", "3abd01", "3kki01", "3pln01", "3hhs01",
    "3igy01", "3dio01", "3vni01", "3mra01", "3psp01",
    # Part 4
    "4jsk01", "4jtr01", "4koi01", "4oky01", "4rhn01", "4oti01",
    "4sgc01", "4kir01", "4kwk01", "4ykk01",
    # Part 5
    "5grn01", "5bct01", "5mst01", "5nrc01", "5fgo01", "5dvl01",
    "5trs01", "5prs01", "5gac01",
    # Part 6
    "6jln01", "6elm01", "6ans01", "6pci01", "6pci02", "6wet01", "6fit01",
    # Part 7
    "7jny01", "7jir01", "7vtn01", "7dio01",
    # Part 8
    "8jsk01",
    # DLC / Special
    "0bao01", "5ris01", "2shm01", "4kch01", "7dio02", "5abc01", "4fgm01", "8wou01",
]

SLOT_NAMES = {0: "Normal A", 1: "Normal B", 2: "Zoom"}


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
    """Return (chunk_header_offset, chunk_data_size) for the nuccChunkBinary."""
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    while offset + 12 <= len(data):
        size     = struct.unpack(">I", data[offset:     offset + 4])[0]
        type_idx = struct.unpack(">H", data[offset + 4: offset + 6])[0]
        if size > 0 and (type_idx == 1 or size > 512):
            return offset, size
        next_off = offset + 12 + size
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    raise ValueError("Could not locate nuccChunkBinary in XFBIN file.")


# Public API

def parse_customizedefaultparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse CustomizeDefaultParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        char_code  str    – character identifier, e.g. "1jnt01"
        slot       int    – slot index: 0=Normal A, 1=Normal B, 2=Zoom
        pos_x      float  – horizontal position in the customization screen
        pos_y      float  – vertical position in the customization screen
        unk        float  – unknown float (always 0.0 in retail)
        scale      float  – character model scale factor
        unk2       float  – unknown float (always 0.0 in retail)
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12

    spm_off  = payload_off + _INNER_SZ_FLD
    version  = struct.unpack_from("<I", data, spm_off)[0]
    count    = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8

    entries_base = spm_off + HEADER_SIZE + notes_len

    entries: list[dict] = []
    for i in range(count):
        base = entries_base + i * ENTRY_SIZE

        ptr       = struct.unpack_from("<Q",  data, base)[0]
        char_code = _read_cstr(data, base + ptr)
        slot      = struct.unpack_from("<I",  data, base + 8)[0]
        pos_x     = struct.unpack_from("<f",  data, base + 12)[0]
        pos_y     = struct.unpack_from("<f",  data, base + 16)[0]
        unk       = struct.unpack_from("<f",  data, base + 20)[0]
        scale     = struct.unpack_from("<f",  data, base + 24)[0]
        unk2      = struct.unpack_from("<f",  data, base + 28)[0]

        entries.append({
            "char_code": char_code,
            "slot":      slot,
            "pos_x":     pos_x,
            "pos_y":     pos_y,
            "unk":       unk,
            "scale":     scale,
            "unk2":      unk2,
        })

    return data, version, entries


def make_default_entry(char_code: str = "1jnt01", slot: int = 0) -> dict:
    """Return a blank entry with retail-typical default values."""
    if slot == 2:
        return {"char_code": char_code, "slot": 2,
                "pos_x": 980.0, "pos_y": 320.0, "unk": 0.0, "scale": 1.8, "unk2": 0.0}
    return {"char_code": char_code, "slot": slot,
            "pos_x": 480.0, "pos_y": 576.0, "unk": 0.0, "scale": 1.0, "unk2": 0.0}


def _build_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner binary (WITHOUT the 4-byte leading inner_size field).

    Layout:
      version(4) count(4) first_ptr(8)  ← HEADER_SIZE = 16
      entries × ENTRY_SIZE              ← 32 bytes each
      string pool (ASCII, padded to 8-byte boundary per string)
    """
    count = len(entries)

    # 1. Build string pool
    pool: bytearray = bytearray()
    pool_offsets: list[int] = []

    for e in entries:
        s = e.get("char_code", "")
        off = len(pool)
        pool_offsets.append(off)
        encoded = s.encode("ascii", errors="replace") + b"\x00"
        pool.extend(encoded)
        pad = (8 - len(pool) % 8) % 8
        if pad:
            pool.extend(b"\x00" * pad)

    # Pool starts at this absolute offset inside the full payload
    # (including the leading 4-byte inner_size field):
    #   _INNER_SZ_FLD(4) + HEADER_SIZE(16) + count*ENTRY_SIZE
    pool_abs = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 2. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)   # first_ptr = 8 (no notes section)

    for i, e in enumerate(entries):
        entry_abs = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE
        str_abs   = pool_abs + pool_offsets[i]
        ptr_val   = str_abs - entry_abs   # relative: pool position − field position

        buf += struct.pack("<Q", ptr_val)
        buf += struct.pack("<I", int(e.get("slot", 0)))
        buf += struct.pack("<f", float(e.get("pos_x", 480.0)))
        buf += struct.pack("<f", float(e.get("pos_y", 576.0)))
        buf += struct.pack("<f", float(e.get("unk",   0.0)))
        buf += struct.pack("<f", float(e.get("scale", 1.0)))
        buf += struct.pack("<f", float(e.get("unk2",  0.0)))

    buf += pool

    # Pad to 4-byte boundary
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_customizedefaultparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated data and write to filepath."""
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
