"""parsers/customcardparam_parser.py  –  CustomCardParam.bin.xfbin parser / writer.

Binary layout (inside the XFBIN binary chunk payload):
  [0-3]   uint32 BE  – inner size (bytes that follow)
  [4-7]   uint32 LE  – version  (1000)
  [8-11]  uint32 LE  – entry count  (1069 in retail)
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes)
  [20+]   entries × 144 bytes each

Each entry (144 bytes, all little-endian unless noted):
  +0    uint64  – ptr  → card_id string      (e.g. "CCD_CUSTOM_CARD_ID_1")
  +8    uint32  – part            (JoJo part, 0..8)
  +12   uint32  – interaction_type  (0..4)
  +16   uint64  – medal_type      (1..10)
  +24   uint64  – ptr  → letter string       (e.g. "A", "B", …)
  +32   int32   – unk7_0          (usually -1)
  +36   int32   – unk7_1          (usually -1)
  +40   int32   – unk7_2          (usually -1)
  +44   int32   – unk7_3          (usually -1)
  +48   uint64  – ptr  → sfx1 string
  +56   uint64  – ptr  → sfx2 string
  +64   uint64  – ptr  → sfx3 string
  +72   uint64  – ptr  → sfx4 string
  +80   int32   – unk18           (usually 1)
  +84   int32   – unk19           (usually 0)
  +88   uint64  – ptr  → char_id string      (e.g. "1jnt01")
  +96   int32   – dlc_id          (0=base, 10000..10011)
  +100  int32   – patch           (e.g. 0, 130, 140, 150, 160, 200, 210, 220, 230)
  +104  int32   – unlock_condition (0..6)
  +108  int32   – unk             (usually 1)
  +112  uint64  – price           (e.g. 8500, 450, 200)
  +120  uint64  – ptr  → medal_name string
  +128  uint64  – ptr  → card_detail string  (e.g. "custom_card_detail_id_0005")
  +136  int64   – index           (sort/display index)

String pool: null-terminated UTF-8, each entry padded to 8-byte boundary.

Pointer resolution:
  string is at absolute file offset:  ptr_field_offset + pointer_value
  where ptr_field_offset = file offset of the uint64 pointer field itself.
"""

import struct

ENTRY_SIZE    = 144
HEADER_SIZE   = 16     # version(4) + count(4) + first_ptr(8)
_INNER_SZ_FLD = 4      # leading BE uint32 in payload

# String field offsets within each entry
_STR_FIELDS = [
    (0,   "card_id"),
    (24,  "letter"),
    (48,  "sfx1"),
    (56,  "sfx2"),
    (64,  "sfx3"),
    (72,  "sfx4"),
    (88,  "char_id"),
    (120, "medal_name"),
    (128, "card_detail"),
]


# Helpers

def _read_cstr(data: bytes | bytearray, off: int) -> str:
    if off >= len(data):
        return ""
    try:
        end = data.index(b"\x00", off)
        raw = data[off:end]
    except ValueError:
        raw = data[off:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _find_binary_chunk(data: bytes | bytearray):
    """Return (chunk_header_offset, chunk_size) for the nuccChunkBinary."""
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

def parse_customcardparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse CustomCardParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        card_id, part, interaction_type, medal_type,
        letter, unk7_0..unk7_3,
        sfx1, sfx2, sfx3, sfx4,
        unk18, unk19,
        char_id, dlc_id, patch, unlock_condition, unk,
        price, medal_name, card_detail, index
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12

    spm_off = payload_off + _INNER_SZ_FLD

    version   = struct.unpack_from("<I", data, spm_off)[0]
    count     = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8

    entries_base = spm_off + HEADER_SIZE + notes_len

    entries: list[dict] = []
    for i in range(count):
        base = entries_base + i * ENTRY_SIZE

        def _str(field_off: int) -> str:
            abs_field = base + field_off
            ptr = struct.unpack_from("<Q", data, abs_field)[0]
            return _read_cstr(data, abs_field + ptr)

        e: dict = {
            "card_id":          _str(0),
            "part":             struct.unpack_from("<I", data, base + 8)[0],
            "interaction_type": struct.unpack_from("<I", data, base + 12)[0],
            "medal_type":       struct.unpack_from("<Q", data, base + 16)[0],
            "letter":           _str(24),
            "unk7_0":           struct.unpack_from("<i", data, base + 32)[0],
            "unk7_1":           struct.unpack_from("<i", data, base + 36)[0],
            "unk7_2":           struct.unpack_from("<i", data, base + 40)[0],
            "unk7_3":           struct.unpack_from("<i", data, base + 44)[0],
            "sfx1":             _str(48),
            "sfx2":             _str(56),
            "sfx3":             _str(64),
            "sfx4":             _str(72),
            "unk18":            struct.unpack_from("<i", data, base + 80)[0],
            "unk19":            struct.unpack_from("<i", data, base + 84)[0],
            "char_id":          _str(88),
            "dlc_id":           struct.unpack_from("<i", data, base + 96)[0],
            "patch":            struct.unpack_from("<i", data, base + 100)[0],
            "unlock_condition": struct.unpack_from("<i", data, base + 104)[0],
            "unk":              struct.unpack_from("<i", data, base + 108)[0],
            "price":            struct.unpack_from("<Q", data, base + 112)[0],
            "medal_name":       _str(120),
            "card_detail":      _str(128),
            "index":            struct.unpack_from("<q", data, base + 136)[0],
        }
        entries.append(e)

    return data, version, entries


def make_default_entry(index: int = 0) -> dict:
    """Return a blank CustomCardParam entry with safe defaults."""
    n = index + 1
    return {
        "card_id":          f"CCD_CUSTOM_CARD_ID_{n}",
        "part":             1,
        "interaction_type": 2,
        "medal_type":       2,
        "letter":           "A",
        "unk7_0":           -1,
        "unk7_1":           -1,
        "unk7_2":           -1,
        "unk7_3":           -1,
        "sfx1":             "",
        "sfx2":             "",
        "sfx3":             "",
        "sfx4":             "",
        "unk18":            1,
        "unk19":            0,
        "char_id":          "",
        "dlc_id":           0,
        "patch":            0,
        "unlock_condition": 6,
        "unk":              1,
        "price":            8500,
        "medal_name":       "",
        "card_detail":      f"custom_card_detail_id_{n:04d}",
        "index":            n,
    }


def _build_customcardparam_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner CustomCardParam binary (WITHOUT the leading 4-byte BE inner_size).

    Layout:
      version(4) count(4) first_ptr(8)   ← HEADER_SIZE = 16
      entries × ENTRY_SIZE               ← 144 bytes each
      string pool (null-terminated UTF-8, padded to 8-byte boundary each)
    """
    count = len(entries)

    # 1. Build string pool
    pool: bytearray = bytearray()
    pool_map: dict[str, int] = {}

    def _pool_add(s: str) -> int:
        if s not in pool_map:
            pool_map[s] = len(pool)
            encoded = s.encode("utf-8") + b"\x00"
            pool.extend(encoded)
            pad = (8 - len(pool) % 8) % 8
            if pad:
                pool.extend(b"\x00" * pad)
        return pool_map[s]

    # Collect pool offsets per entry in the order they appear in the entry
    STR_FIELD_NAMES = [
        "card_id", "letter", "sfx1", "sfx2", "sfx3", "sfx4",
        "char_id", "medal_name", "card_detail",
    ]
    str_offsets: list[dict[str, int]] = []
    for e in entries:
        offsets = {k: _pool_add(e[k]) for k in STR_FIELD_NAMES}
        str_offsets.append(offsets)

    # 2. Pool starts right after: _INNER_SZ_FLD + HEADER_SIZE + count*ENTRY_SIZE
    pool_tmpl_off = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 3. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)   # first_ptr = 8

    for i, (e, soff) in enumerate(zip(entries, str_offsets)):
        entry_tmpl = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE

        def _ptr(field_off: int, pool_off: int) -> int:
            return pool_tmpl_off + pool_off - (entry_tmpl + field_off)

        buf += struct.pack("<Q", _ptr(0,   soff["card_id"]))
        buf += struct.pack("<I", e["part"])
        buf += struct.pack("<I", e["interaction_type"])
        buf += struct.pack("<Q", e["medal_type"])
        buf += struct.pack("<Q", _ptr(24,  soff["letter"]))
        buf += struct.pack("<i", e["unk7_0"])
        buf += struct.pack("<i", e["unk7_1"])
        buf += struct.pack("<i", e["unk7_2"])
        buf += struct.pack("<i", e["unk7_3"])
        buf += struct.pack("<Q", _ptr(48,  soff["sfx1"]))
        buf += struct.pack("<Q", _ptr(56,  soff["sfx2"]))
        buf += struct.pack("<Q", _ptr(64,  soff["sfx3"]))
        buf += struct.pack("<Q", _ptr(72,  soff["sfx4"]))
        buf += struct.pack("<i", e["unk18"])
        buf += struct.pack("<i", e["unk19"])
        buf += struct.pack("<Q", _ptr(88,  soff["char_id"]))
        buf += struct.pack("<i", e["dlc_id"])
        buf += struct.pack("<i", e["patch"])
        buf += struct.pack("<i", e["unlock_condition"])
        buf += struct.pack("<i", e["unk"])
        buf += struct.pack("<Q", e["price"])
        buf += struct.pack("<Q", _ptr(120, soff["medal_name"]))
        buf += struct.pack("<Q", _ptr(128, soff["card_detail"]))
        buf += struct.pack("<q", e["index"])

    buf += pool

    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_customcardparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated CustomCardParam data and write to filepath."""
    new_inner   = _build_customcardparam_binary(version, entries)
    inner_size  = len(new_inner)
    new_payload = struct.pack(">I", inner_size) + new_inner

    # Pad to 4-byte boundary
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
