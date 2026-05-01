"""parsers/playertitleparam_parser.py  –  PlayerTitleParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  – inner_size  (bytes that follow)
  [4-7]   uint32 LE  – version     (1000)
  [8-11]  uint32 LE  – entry count (781 in retail)
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes section)
  [20+]   entries × 80 bytes each

Each entry (80 bytes):
  +0   uint64 LE  – relative ptr → TitleID     string  (e.g. "PLCARD_TITLE_001")
  +8   uint64 LE  – relative ptr → AnimID      string  (e.g. "1jnt01_02")
  +16  uint64 LE  – Part          (JoJo part number: 0–8)
  +24  uint64 LE  – relative ptr → CharaCode   string  (e.g. "1jnt01")
  +32  uint32 LE  – DlcId         (0 = base game; 10005-10011 = DLC packs)
  +36  uint32 LE  – Patch         (game patch version: 0, 130, 140…230)
  +40  uint32 LE  – UnlockCondition (4 = DLC, 6 = purchase/default)
  +44  uint32 LE  – unk2          (always 1)
  +48  uint32 LE  – unk3          (always 1)
  +52  uint32 LE  – unk4          (always 0)
  +56  uint64 LE  – relative ptr → CardString1 string  (e.g. "playercard_title_t001")
  +64  uint64 LE  – relative ptr → CardString2 string  (e.g. "playercard_title_h001")
  +72  uint64 LE  – Index         (sequential display index)
= 80 bytes

String pool: null-terminated ASCII, each string padded to 8-byte boundary.

Pointer resolution (standard ASBR convention):
  string_abs_offset = ptr_field_abs_offset + pointer_value

UnlockCondition values observed in retail:
  4  = DLC-gated (requires DLC pack)
  6  = purchasable / default-available

Part values: 0–8 (JoJo parts 1–8, 0 = none/special)
DlcId: 0 (base game), 10005–10011 (DLC character packs)
Patch: 0 (launch), 130/140/…/230 (patch version ×10; e.g. 130 = v1.30)
"""

import struct

ENTRY_SIZE    = 80   # bytes per entry
HEADER_SIZE   = 16   # version(4) + count(4) + first_ptr(8)
_INNER_SZ_FLD =  4   # leading BE uint32 inner_size in payload

# String field offsets within each entry and their dict keys
_STR_FIELDS: list[tuple[int, str]] = [
    (0,  "title_id"),
    (8,  "anim_id"),
    (24, "chara_code"),
    (56, "card_string1"),
    (64, "card_string2"),
]
_STR_KEYS = [k for _, k in _STR_FIELDS]

UNLOCK_LABELS = {
    4: "DLC",
    6: "Purchase / Default",
}

PART_LABELS = {
    0: "0 – None",
    1: "1 – Phantom Blood",
    2: "2 – Battle Tendency",
    3: "3 – Stardust Crusaders",
    4: "4 – Diamond is Unbreakable",
    5: "5 – Golden Wind",
    6: "6 – Stone Ocean",
    7: "7 – Steel Ball Run",
    8: "8 – JoJolion",
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
    """Return (chunk_header_offset, chunk_data_size) for nuccChunkBinary.

    Uses the largest-chunk heuristic: the binary data chunk is always the
    largest non-trivial chunk in the file.
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
        raise ValueError("Could not locate nuccChunkBinary in PlayerTitleParam XFBIN.")

    return best_off, best_size


# Public API

def parse_playertitleparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse PlayerTitleParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        title_id      str  – player card title identifier   e.g. "PLCARD_TITLE_001"
        anim_id       str  – animation / pose identifier    e.g. "1jnt01_02"
        part          int  – JoJo part number (0–8)
        chara_code    str  – character code                 e.g. "1jnt01"
        dlc_id        int  – DLC pack ID (0 = base game)
        patch         int  – patch version ×10 (0 = launch)
        unlock_cond   int  – unlock condition (4 or 6)
        unk2          int  – always 1 in retail
        unk3          int  – always 1 in retail
        unk4          int  – always 0 in retail
        card_string1  str  – card texture ID (text)         e.g. "playercard_title_t001"
        card_string2  str  – card texture ID (highlight)    e.g. "playercard_title_h001"
        index         int  – sequential display index
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
            "title_id":    _str(0),
            "anim_id":     _str(8),
            "part":        struct.unpack_from("<Q", data, base + 16)[0],
            "chara_code":  _str(24),
            "dlc_id":      struct.unpack_from("<I", data, base + 32)[0],
            "patch":       struct.unpack_from("<I", data, base + 36)[0],
            "unlock_cond": struct.unpack_from("<I", data, base + 40)[0],
            "unk2":        struct.unpack_from("<I", data, base + 44)[0],
            "unk3":        struct.unpack_from("<I", data, base + 48)[0],
            "unk4":        struct.unpack_from("<I", data, base + 52)[0],
            "card_string1":_str(56),
            "card_string2":_str(64),
            "index":       struct.unpack_from("<Q", data, base + 72)[0],
        })

    return data, version, entries


def make_default_entry(index: int = 0) -> dict:
    """Return a blank PlayerTitleParam entry with sensible defaults."""
    n = index + 1
    return {
        "title_id":    f"PLCARD_TITLE_{n:03d}",
        "anim_id":     "",
        "part":        1,
        "chara_code":  "",
        "dlc_id":      0,
        "patch":       0,
        "unlock_cond": 6,
        "unk2":        1,
        "unk3":        1,
        "unk4":        0,
        "card_string1": f"playercard_title_t{n:03d}",
        "card_string2": f"playercard_title_h{n:03d}",
        "index":       index,
    }


# Binary builder

def _build_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner binary payload (WITHOUT the 4-byte BE inner_size field).

    Layout:
      version(4) count(4) first_ptr(8)        ← HEADER_SIZE = 16
      entries × ENTRY_SIZE                     ← 80 bytes each
      string pool (null-terminated ASCII, padded to 8-byte boundary each)
    """
    count = len(entries)

    # 1. Build string pool (deduplicated)
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
    # (after the 4-byte BE inner_size field at the front)
    pool_abs = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 2. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)    # first_ptr = 8 (no notes section)

    for i, (e, soff) in enumerate(zip(entries, str_offsets)):
        entry_abs = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE

        def _ptr(field_off: int, key: str, _ea=entry_abs, _so=soff) -> int:
            """Relative pointer: pool_abs + pool_offset - field_abs_pos."""
            return pool_abs + _so[key] - (_ea + field_off)

        buf += struct.pack("<Q", _ptr(0,  "title_id"))
        buf += struct.pack("<Q", _ptr(8,  "anim_id"))
        buf += struct.pack("<Q", int(e.get("part", 0)))
        buf += struct.pack("<Q", _ptr(24, "chara_code"))
        buf += struct.pack("<I", int(e.get("dlc_id",     0)))
        buf += struct.pack("<I", int(e.get("patch",      0)))
        buf += struct.pack("<I", int(e.get("unlock_cond",6)))
        buf += struct.pack("<I", int(e.get("unk2",       1)))
        buf += struct.pack("<I", int(e.get("unk3",       1)))
        buf += struct.pack("<I", int(e.get("unk4",       0)))
        buf += struct.pack("<Q", _ptr(56, "card_string1"))
        buf += struct.pack("<Q", _ptr(64, "card_string2"))
        buf += struct.pack("<Q", int(e.get("index", i)))

    buf += pool

    # Pad to 4-byte boundary
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_playertitleparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated PlayerTitleParam data and write to filepath."""
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
