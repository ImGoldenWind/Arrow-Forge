"""parsers/charviewer_parser.py  –  CharViewerParam.bin.xfbin parser / writer.

Binary layout (inside the XFBIN binary chunk payload):
  [0-3]   uint32 BE  – inner size (bytes that follow)
  [4-7]   uint32 LE  – version  (1000)
  [8-11]  uint32 LE  – entry count  (259 in retail)
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes)
  [20+]   entries × 408 bytes each

Each entry (408 bytes, all little-endian unless noted):
  +0    uint64  – ptr  → char_viewer_id string
  +8    int32   – part            (JoJo part, used in 3D Model shop)
  +12   int32   – menu1_index     (Character #)
  +16   int32   – menu2_index     (3D Model List Index)
  +20   int32   – unk             (hidden)
  +24   uint64  – ptr  → custom_list_title string   (only some entries have it)
  +32   uint64  – ptr  → viewer_id string
  — AnimationNames block (28 × 8 = 224 bytes, offsets +40 to +263) —
  +40   uint64  – ptr  → face_anim       (FaceAnimation1Name)
  +48   uint64  – ptr  → idle_anim1      (Idle Animation 1)
  +56   uint64  – ptr  → idle_anim2      (Idle Animation 2)
  +64   uint64  – ptr  → pose1_st        (Stylish Pose 1 Start)
  +72   uint64  – ptr  → pose1_lp        (Stylish Pose 1 Loop)
  +80   uint64  – ptr  → pose1_ed        (Stylish Pose 1 End)
  +88   uint64  – ptr  → pose2_st
  +96   uint64  – ptr  → pose2_lp
  +104  uint64  – ptr  → pose2_ed
  +112  uint64  – ptr  → pose3_st
  +120  uint64  – ptr  → pose3_lp
  +128  uint64  – ptr  → pose3_ed
  +136  uint64  – ptr  → pose4_st
  +144  uint64  – ptr  → pose4_lp
  +152  uint64  – ptr  → pose4_ed
  +160  uint64  – ptr  → pose5_st
  +168  uint64  – ptr  → pose5_lp
  +176  uint64  – ptr  → pose5_ed
  +184  uint64  – ptr  → object1
  +192  uint64  – ptr  → object2
  +200  uint64  – ptr  → object3
  +208  uint64  – ptr  → anim21
  +216  uint64  – ptr  → anim22_char_id
  +224  uint64  – ptr  → anim23_char_tints
  +232  uint64  – ptr  → anim24_char_ids
  +240  uint64  – ptr  → anim25_model_ids
  +248  uint64  – ptr  → anim26
  +256  uint64  – ptr  → anim27
  — end AnimationNames —
  +264  int32   – padding        (always 0)
  — Camera block (9 × float32 = 36 bytes) —
  +268  float   – cam_zoom       (Starting Camera Zoom; limits relative to this)
  +272  float   – cam_y          (Starting Camera Y; camera/model positions are inverse)
  +276  float   – cam_unk        (Expected StartX, does nothing)
  +280  float   – cam_anchor_y   (Camera Y Anchor)
  +284  float   – cam_anchor_x   (Camera X Anchor)
  +288  float   – cam_rot_y_min  (Camera Rotate Y Lower Limit)
  +292  float   – cam_rot_z      (Starting Camera Z Rotation)
  +296  float   – cam_zoom_in    (Camera Zoom-In Limit)
  +300  float   – cam_zoom_out   (Camera Zoom-Out Limit)
  — end Camera —
  +304  uint64  – unk2           (hidden; observed: 1)
  +312  uint64  – unk3           (hidden; observed: 0)
  +320  uint64  – ptr  → chara_code     (Character ID, e.g. "1jnt01")
  +328  uint64  – ptr  → custom_card    (Custom Card ID)
  +336  uint64  – ptr  → icon_path      (Custom Icon Path)
  +344  uint64  – ptr  → medal_img      (Medal Preview Image)
  +352  uint64  – ptr  → model_code     (Character Model ID)
  +360  uint32  – dlc_id          (0=base, 10000..10011)
  +364  uint32  – patch_id        (e.g. 0, 130, 200, 230)
  +368  uint32  – unlock_condition (0..6)
  +372  uint32  – unk4            (hidden)
  +376  uint64  – shop_price      (Gallery Shop Price)
  +384  uint64  – ptr  → extra_costume  (Extra Costume Title ID)
  +392  uint64  – ptr  → card_detail    (Card Detail ID)
  +400  uint64  – entry_padding   (always 0)
= 408 bytes per entry

String pool: null-terminated UTF-8, each string padded to 8-byte boundary.

Pointer resolution:
  string is at absolute file offset:  ptr_field_offset + pointer_value
  where ptr_field_offset = file offset of the uint64 pointer field itself.
"""

import struct

ENTRY_SIZE   = 408
HEADER_SIZE  = 16    # version(4) + count(4) + first_ptr(8)
_INNER_SZ_FLD = 4   # leading BE uint32 in payload

# String field offsets within each 408-byte entry (offset → dict key)
_STR_FIELDS: list[tuple[int, str]] = [
    (0,   "char_viewer_id"),
    (24,  "custom_list_title"),
    (32,  "viewer_id"),
    (40,  "face_anim"),
    (48,  "idle_anim1"),
    (56,  "idle_anim2"),
    (64,  "pose1_st"),
    (72,  "pose1_lp"),
    (80,  "pose1_ed"),
    (88,  "pose2_st"),
    (96,  "pose2_lp"),
    (104, "pose2_ed"),
    (112, "pose3_st"),
    (120, "pose3_lp"),
    (128, "pose3_ed"),
    (136, "pose4_st"),
    (144, "pose4_lp"),
    (152, "pose4_ed"),
    (160, "pose5_st"),
    (168, "pose5_lp"),
    (176, "pose5_ed"),
    (184, "object1"),
    (192, "object2"),
    (200, "object3"),
    (208, "anim21"),
    (216, "anim22_char_id"),
    (224, "anim23_char_tints"),
    (232, "anim24_char_ids"),
    (240, "anim25_model_ids"),
    (248, "anim26"),
    (256, "anim27"),
    (320, "chara_code"),
    (328, "custom_card"),
    (336, "icon_path"),
    (344, "medal_img"),
    (352, "model_code"),
    (384, "extra_costume"),
    (392, "card_detail"),
]

_STR_KEYS = [k for _, k in _STR_FIELDS]


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

def parse_charviewer_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse CharViewerParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        char_viewer_id, part, menu1_index, menu2_index, unk,
        custom_list_title, viewer_id,
        face_anim, idle_anim1, idle_anim2,
        pose1_st, pose1_lp, pose1_ed,
        pose2_st, pose2_lp, pose2_ed,
        pose3_st, pose3_lp, pose3_ed,
        pose4_st, pose4_lp, pose4_ed,
        pose5_st, pose5_lp, pose5_ed,
        object1, object2, object3,
        anim21, anim22_char_id, anim23_char_tints, anim24_char_ids,
        anim25_model_ids, anim26, anim27,
        padding,
        cam_zoom, cam_y, cam_unk, cam_anchor_y, cam_anchor_x,
        cam_rot_y_min, cam_rot_z, cam_zoom_in, cam_zoom_out,
        unk2, unk3,
        chara_code, custom_card, icon_path, medal_img, model_code,
        dlc_id, patch_id, unlock_condition, unk4,
        shop_price,
        extra_costume, card_detail,
        entry_padding
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

        def _str(field_off: int, _base=base) -> str:
            abs_field = _base + field_off
            ptr = struct.unpack_from("<Q", data, abs_field)[0]
            return _read_cstr(data, abs_field + ptr)

        e: dict = {
            # Identification
            "char_viewer_id":     _str(0),
            "part":               struct.unpack_from("<i", data, base + 8)[0],
            "menu1_index":        struct.unpack_from("<i", data, base + 12)[0],
            "menu2_index":        struct.unpack_from("<i", data, base + 16)[0],
            "unk":                struct.unpack_from("<i", data, base + 20)[0],
            "custom_list_title":  _str(24),
            "viewer_id":          _str(32),
            # Animation names
            "face_anim":          _str(40),
            "idle_anim1":         _str(48),
            "idle_anim2":         _str(56),
            "pose1_st":           _str(64),
            "pose1_lp":           _str(72),
            "pose1_ed":           _str(80),
            "pose2_st":           _str(88),
            "pose2_lp":           _str(96),
            "pose2_ed":           _str(104),
            "pose3_st":           _str(112),
            "pose3_lp":           _str(120),
            "pose3_ed":           _str(128),
            "pose4_st":           _str(136),
            "pose4_lp":           _str(144),
            "pose4_ed":           _str(152),
            "pose5_st":           _str(160),
            "pose5_lp":           _str(168),
            "pose5_ed":           _str(176),
            "object1":            _str(184),
            "object2":            _str(192),
            "object3":            _str(200),
            "anim21":             _str(208),
            "anim22_char_id":     _str(216),
            "anim23_char_tints":  _str(224),
            "anim24_char_ids":    _str(232),
            "anim25_model_ids":   _str(240),
            "anim26":             _str(248),
            "anim27":             _str(256),
            # Padding before camera
            "padding":            struct.unpack_from("<i", data, base + 264)[0],
            # Camera parameters
            "cam_zoom":           struct.unpack_from("<f", data, base + 268)[0],
            "cam_y":              struct.unpack_from("<f", data, base + 272)[0],
            "cam_unk":            struct.unpack_from("<f", data, base + 276)[0],
            "cam_anchor_y":       struct.unpack_from("<f", data, base + 280)[0],
            "cam_anchor_x":       struct.unpack_from("<f", data, base + 284)[0],
            "cam_rot_y_min":      struct.unpack_from("<f", data, base + 288)[0],
            "cam_rot_z":          struct.unpack_from("<f", data, base + 292)[0],
            "cam_zoom_in":        struct.unpack_from("<f", data, base + 296)[0],
            "cam_zoom_out":       struct.unpack_from("<f", data, base + 300)[0],
            # Hidden unknowns
            "unk2":               struct.unpack_from("<Q", data, base + 304)[0],
            "unk3":               struct.unpack_from("<Q", data, base + 312)[0],
            # Model / DLC fields
            "chara_code":         _str(320),
            "custom_card":        _str(328),
            "icon_path":          _str(336),
            "medal_img":          _str(344),
            "model_code":         _str(352),
            "dlc_id":             struct.unpack_from("<I", data, base + 360)[0],
            "patch_id":           struct.unpack_from("<I", data, base + 364)[0],
            "unlock_condition":   struct.unpack_from("<I", data, base + 368)[0],
            "unk4":               struct.unpack_from("<I", data, base + 372)[0],
            "shop_price":         struct.unpack_from("<Q", data, base + 376)[0],
            "extra_costume":      _str(384),
            "card_detail":        _str(392),
            "entry_padding":      struct.unpack_from("<Q", data, base + 400)[0],
        }
        entries.append(e)

    return data, version, entries


def make_default_entry(index: int = 0) -> dict:
    """Return a blank CharViewerParam entry with safe defaults."""
    n = index + 1
    return {
        "char_viewer_id":    f"CVID_{n:04d}",
        "part":              1,
        "menu1_index":       0,
        "menu2_index":       0,
        "unk":               0,
        "custom_list_title": "",
        "viewer_id":         "",
        "face_anim":         "",
        "idle_anim1":        "",
        "idle_anim2":        "",
        "pose1_st":          "",
        "pose1_lp":          "",
        "pose1_ed":          "",
        "pose2_st":          "",
        "pose2_lp":          "",
        "pose2_ed":          "",
        "pose3_st":          "",
        "pose3_lp":          "",
        "pose3_ed":          "",
        "pose4_st":          "",
        "pose4_lp":          "",
        "pose4_ed":          "",
        "pose5_st":          "",
        "pose5_lp":          "",
        "pose5_ed":          "",
        "object1":           "",
        "object2":           "",
        "object3":           "",
        "anim21":            "",
        "anim22_char_id":    "",
        "anim23_char_tints": "",
        "anim24_char_ids":   "",
        "anim25_model_ids":  "",
        "anim26":            "",
        "anim27":            "",
        "padding":           0,
        "cam_zoom":          -600.0,
        "cam_y":             0.0,
        "cam_unk":           0.0,
        "cam_anchor_y":      100.0,
        "cam_anchor_x":      0.0,
        "cam_rot_y_min":     -30.0,
        "cam_rot_z":         -90.0,
        "cam_zoom_in":       20.0,
        "cam_zoom_out":      60.0,
        "unk2":              1,
        "unk3":              0,
        "chara_code":        "",
        "custom_card":       "",
        "icon_path":         "",
        "medal_img":         "",
        "model_code":        "",
        "dlc_id":            0,
        "patch_id":          0,
        "unlock_condition":  1,
        "unk4":              1,
        "shop_price":        1500,
        "extra_costume":     "",
        "card_detail":       "",
        "entry_padding":     0,
    }


def _build_charviewer_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner CharViewerParam binary (WITHOUT the leading 4-byte BE inner_size).

    Layout:
      version(4) count(4) first_ptr(8)   ← HEADER_SIZE = 16
      entries × ENTRY_SIZE               ← 408 bytes each
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

    # Build pool offsets per entry (must be done before assembling entries
    # so we know where each string sits in the pool)
    str_offsets: list[dict[str, int]] = []
    for e in entries:
        offsets = {k: _pool_add(e.get(k, "")) for k in _STR_KEYS}
        str_offsets.append(offsets)

    # Pool starts right after: _INNER_SZ_FLD + HEADER_SIZE + count*ENTRY_SIZE
    pool_tmpl_off = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 2. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)   # first_ptr = 8

    for i, (e, soff) in enumerate(zip(entries, str_offsets)):
        entry_tmpl = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE

        def _ptr(field_off: int, key: str, _et=entry_tmpl, _soff=soff) -> int:
            """Relative pointer from field_off inside this entry to the pool string."""
            return pool_tmpl_off + _soff[key] - (_et + field_off)

        buf += struct.pack("<Q", _ptr(0,   "char_viewer_id"))
        buf += struct.pack("<i", e["part"])
        buf += struct.pack("<i", e["menu1_index"])
        buf += struct.pack("<i", e["menu2_index"])
        buf += struct.pack("<i", e["unk"])
        buf += struct.pack("<Q", _ptr(24,  "custom_list_title"))
        buf += struct.pack("<Q", _ptr(32,  "viewer_id"))

        # AnimationNames (28 strings, offsets 40..256)
        anim_keys = [
            "face_anim", "idle_anim1", "idle_anim2",
            "pose1_st", "pose1_lp", "pose1_ed",
            "pose2_st", "pose2_lp", "pose2_ed",
            "pose3_st", "pose3_lp", "pose3_ed",
            "pose4_st", "pose4_lp", "pose4_ed",
            "pose5_st", "pose5_lp", "pose5_ed",
            "object1", "object2", "object3",
            "anim21", "anim22_char_id", "anim23_char_tints",
            "anim24_char_ids", "anim25_model_ids", "anim26", "anim27",
        ]
        for j, key in enumerate(anim_keys):
            field_off = 40 + j * 8
            buf += struct.pack("<Q", _ptr(field_off, key))

        buf += struct.pack("<i", e.get("padding", 0))
        buf += struct.pack("<f", e["cam_zoom"])
        buf += struct.pack("<f", e["cam_y"])
        buf += struct.pack("<f", e["cam_unk"])
        buf += struct.pack("<f", e["cam_anchor_y"])
        buf += struct.pack("<f", e["cam_anchor_x"])
        buf += struct.pack("<f", e["cam_rot_y_min"])
        buf += struct.pack("<f", e["cam_rot_z"])
        buf += struct.pack("<f", e["cam_zoom_in"])
        buf += struct.pack("<f", e["cam_zoom_out"])
        buf += struct.pack("<Q", e.get("unk2", 1))
        buf += struct.pack("<Q", e.get("unk3", 0))
        buf += struct.pack("<Q", _ptr(320, "chara_code"))
        buf += struct.pack("<Q", _ptr(328, "custom_card"))
        buf += struct.pack("<Q", _ptr(336, "icon_path"))
        buf += struct.pack("<Q", _ptr(344, "medal_img"))
        buf += struct.pack("<Q", _ptr(352, "model_code"))
        buf += struct.pack("<I", e["dlc_id"])
        buf += struct.pack("<I", e["patch_id"])
        buf += struct.pack("<I", e["unlock_condition"])
        buf += struct.pack("<I", e.get("unk4", 1))
        buf += struct.pack("<Q", e["shop_price"])
        buf += struct.pack("<Q", _ptr(384, "extra_costume"))
        buf += struct.pack("<Q", _ptr(392, "card_detail"))
        buf += struct.pack("<Q", e.get("entry_padding", 0))

    buf += pool

    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_charviewer_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated CharViewerParam data and write to filepath."""
    new_inner   = _build_charviewer_binary(version, entries)
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
