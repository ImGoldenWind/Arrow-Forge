"""parsers/galleryartparam_parser.py  –  GalleryArtParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  – inner_size  (bytes that follow)
  [4-7]   uint32 LE  – version     (1000)
  [8-11]  uint32 LE  – entry count (224 in retail)
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes section)
  [20+]   entries × 104 bytes each

Each entry (104 bytes):
  +0   uint64 LE  – relative ptr → ArtId        string  (e.g. "ID_ART_001")
  +8   uint64 LE  – relative ptr → IconPath      string  (e.g. "data/ui/gallery/art/icon/gallery_art_icon.xfbin")
  +16  uint64 LE  – relative ptr → IconName      string  (e.g. "01_jnt00_s")
  +24  uint64 LE  – relative ptr → ArtPath       string  (e.g. "data/ui/gallery/art/img/01_jnt00.xfbin")
  +32  uint64 LE  – relative ptr → ArtName       string  (e.g. "01_jnt00")
  +40  uint64 LE  – Part          (JoJo part number: 0–8)
  +48  uint64 LE  – relative ptr → CharaCode     string  (e.g. "1jnt01")
  +56  uint32 LE  – DlcId         (0 = base game, 10005–10011 = DLC packs)
  +60  uint32 LE  – Patch         (game patch version: 0, 130, 140…230)
  +64  uint32 LE  – UnlockCondition (1 = always unlocked, 4 = DLC, 6 = buy with in-game points)
  +68  uint32 LE  – MenuIndex     (display order / page)
  +72  uint64 LE  – Price         (in-game point cost, e.g. 1500)
  +80  uint64 LE  – relative ptr → ArtString1    string  (title ID 1, e.g. "artv_t000")
  +88  uint64 LE  – relative ptr → ArtString2    string  (title ID 2, e.g. "artv_h000")
  +96  uint64 LE  – Index         (sequential gallery index, e.g. 0, 1, 62…)
= 104 bytes

String pool: null-terminated ASCII, each string padded to 8-byte boundary.

Pointer resolution (standard ASBR convention):
  string_abs_offset = ptr_field_abs_offset + pointer_value

UnlockCondition values observed in retail:
  1  = always unlocked (default available)
  4  = DLC-gated (requires DLC pack)
  6  = purchasable with in-game points (Price > 0)

Part values: 0–8 (JoJo parts 1–8, 0 = no part / special)
DlcId values: 0 (base), 10005–10011 (DLC packs)
Patch values: 0 (launch), 130/140/150/160/170/210/220/230 (patch versions ×10)
"""

import struct

ENTRY_SIZE    = 104   # bytes per entry
HEADER_SIZE   = 16    # version(4) + count(4) + first_ptr(8)
_INNER_SZ_FLD =  4    # leading BE uint32 inner_size in payload

# String field offsets within each entry and their dict keys
_STR_FIELDS: list[tuple[int, str]] = [
    (0,  "art_id"),
    (8,  "icon_path"),
    (16, "icon_name"),
    (24, "art_path"),
    (32, "art_name"),
    (48, "chara_code"),
    (80, "art_string1"),
    (88, "art_string2"),
]
_STR_KEYS = [k for _, k in _STR_FIELDS]

# Known unlock condition meanings
UNLOCK_LABELS = {
    1: "Always Unlocked",
    4: "DLC",
    6: "Purchase (Points)",
}


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

    Uses the largest-chunk heuristic (same as DlcInfoParam) since
    GalleryArtParam has type_idx=0 in its chunk header.
    """
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    best_off  = -1
    best_size = 0

    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset: offset + 4])[0]
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
        raise ValueError("Could not locate nuccChunkBinary in GalleryArtParam XFBIN.")

    return best_off, best_size


# Public API

def parse_galleryartparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse GalleryArtParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        art_id        str   – gallery art identifier,       e.g. "ID_ART_001"
        icon_path     str   – XFBIN path of the icon,       e.g. "data/ui/gallery/art/icon/gallery_art_icon.xfbin"
        icon_name     str   – icon texture name,            e.g. "01_jnt00_s"
        art_path      str   – XFBIN path of the full art,   e.g. "data/ui/gallery/art/img/01_jnt00.xfbin"
        art_name      str   – full-art texture name,        e.g. "01_jnt00"
        part          int   – JoJo part number (0–8)
        chara_code    str   – character code,               e.g. "1jnt01"
        dlc_id        int   – DLC pack ID (0 = base game)
        patch         int   – patch version ×10 (0 = launch)
        unlock_cond   int   – unlock condition (1/4/6)
        menu_index    int   – menu display order
        price         int   – in-game point cost
        art_string1   str   – title string ID 1,            e.g. "artv_t000"
        art_string2   str   – title string ID 2,            e.g. "artv_h000"
        index         int   – sequential gallery index
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

        def _str(field_off: int, _b=base) -> str:
            abs_field = _b + field_off
            ptr = struct.unpack_from("<Q", data, abs_field)[0]
            return _read_cstr(data, abs_field + ptr)

        entries.append({
            "art_id":     _str(0),
            "icon_path":  _str(8),
            "icon_name":  _str(16),
            "art_path":   _str(24),
            "art_name":   _str(32),
            "part":       struct.unpack_from("<Q", data, base + 40)[0],
            "chara_code": _str(48),
            "dlc_id":     struct.unpack_from("<I", data, base + 56)[0],
            "patch":      struct.unpack_from("<I", data, base + 60)[0],
            "unlock_cond":struct.unpack_from("<I", data, base + 64)[0],
            "menu_index": struct.unpack_from("<I", data, base + 68)[0],
            "price":      struct.unpack_from("<Q", data, base + 72)[0],
            "art_string1":_str(80),
            "art_string2":_str(88),
            "index":      struct.unpack_from("<Q", data, base + 96)[0],
        })

    return data, version, entries


def make_default_entry(index: int = 0) -> dict:
    """Return a blank GalleryArtParam entry with sensible defaults."""
    n = index + 1
    return {
        "art_id":      f"ID_ART_{n:03d}",
        "icon_path":   "data/ui/gallery/art/icon/gallery_art_icon.xfbin",
        "icon_name":   "",
        "art_path":    "",
        "art_name":    "",
        "part":        1,
        "chara_code":  "",
        "dlc_id":      0,
        "patch":       0,
        "unlock_cond": 6,
        "menu_index":  1,
        "price":       1500,
        "art_string1": f"artv_t{index:03d}",
        "art_string2": f"artv_h{index:03d}",
        "index":       index,
    }


# Binary builder

def _build_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner binary payload (WITHOUT the 4-byte BE inner_size field).

    Layout:
      version(4) count(4) first_ptr(8)        ← HEADER_SIZE = 16
      entries × ENTRY_SIZE                     ← 104 bytes each
      string pool (null-terminated ASCII, padded to 8-byte boundary each)
    """
    count = len(entries)

    # 1. Build string pool
    pool: bytearray = bytearray()
    pool_map: dict[str, int] = {}

    def _pool_add(s: str) -> int:
        if s not in pool_map:
            pool_map[s] = len(pool)
            encoded = s.encode("ascii", errors="replace") + b"\x00"
            pool.extend(encoded)
            pad = (8 - len(pool) % 8) % 8
            if pad:
                pool.extend(b"\x00" * pad)
        return pool_map[s]

    str_offsets: list[dict[str, int]] = []
    for e in entries:
        offsets = {k: _pool_add(e.get(k, "")) for k in _STR_KEYS}
        str_offsets.append(offsets)

    # Absolute offset of the string pool within the full payload
    # (counting the 4-byte BE inner_size field at the very front)
    pool_abs = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 2. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)   # first_ptr = 8 (no notes section)

    for i, (e, soff) in enumerate(zip(entries, str_offsets)):
        entry_tmpl = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE

        def _ptr(field_off: int, key: str, _et=entry_tmpl, _soff=soff) -> int:
            """Relative pointer from this field to its string in the pool."""
            return pool_abs + _soff[key] - (_et + field_off)

        # 5 string ptrs before Part
        buf += struct.pack("<Q", _ptr(0,  "art_id"))
        buf += struct.pack("<Q", _ptr(8,  "icon_path"))
        buf += struct.pack("<Q", _ptr(16, "icon_name"))
        buf += struct.pack("<Q", _ptr(24, "art_path"))
        buf += struct.pack("<Q", _ptr(32, "art_name"))
        # Part (uint64)
        buf += struct.pack("<Q", int(e.get("part", 0)))
        # CharaCode ptr
        buf += struct.pack("<Q", _ptr(48, "chara_code"))
        # Numeric fields
        buf += struct.pack("<I", int(e.get("dlc_id",     0)))
        buf += struct.pack("<I", int(e.get("patch",      0)))
        buf += struct.pack("<I", int(e.get("unlock_cond",6)))
        buf += struct.pack("<I", int(e.get("menu_index", 1)))
        buf += struct.pack("<Q", int(e.get("price",      0)))
        # ArtString1 & ArtString2 ptrs
        buf += struct.pack("<Q", _ptr(80, "art_string1"))
        buf += struct.pack("<Q", _ptr(88, "art_string2"))
        # Index (uint64)
        buf += struct.pack("<Q", int(e.get("index", i)))

    buf += pool

    # Pad to 4-byte boundary
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_galleryartparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated GalleryArtParam data and write to filepath."""
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
