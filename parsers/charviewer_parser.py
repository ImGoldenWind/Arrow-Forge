"""CharViewerParam: native 0x198 rows; see docs/char-viewer-research.md.

Relative string pointers are signed 64-bit, including +0x138 (formerly unk3).
Untouched payload bytes, null pointers, opaque prefix/tail and neighboring NUCC
chunks are preserved. Writes are atomic; game resources are never modified.
"""
import math
import os
import struct
import tempfile

ENTRY_SIZE = 408
HEADER_SIZE = 16
_INNER_SZ_FLD = 4

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
    (312, "resource_138"),
    (320, "chara_code"),
    (328, "custom_card"),
    (336, "icon_path"),
    (344, "medal_img"),
    (352, "model_code"),
    (384, "extra_costume"),
    (392, "card_detail"),
]

_STR_KEYS = [k for _, k in _STR_FIELDS]



# Numeric widths describe storage, not speculative gameplay slider bounds.
_INT_FIELDS = [(8, 'part', 'i'), (12, 'menu1_index', 'i'),
               (16, 'menu2_index', 'i'), (20, 'unk', 'i'),
               (304, 'unk2', 'Q'),
               (360, 'dlc_id', 'I'), (364, 'patch_id', 'I'),
               (368, 'unlock_condition', 'I'), (372, 'unk4', 'I'),
               (376, 'shop_price', 'I'), (380, 'shop_padding', 'I'),
               (400, 'entry_padding', 'Q')]
_FLOAT_KEYS = ('cam_pos_z', 'cam_zoom', 'cam_y', 'cam_unk', 'cam_anchor_y', 'cam_anchor_x',
               'cam_rot_y_min', 'cam_rot_z', 'cam_zoom_in', 'cam_zoom_out')
_NUM_FIELDS = _INT_FIELDS + [(264 + i * 4, key, 'f') for i, key in enumerate(_FLOAT_KEYS)]


def _read_cstr(data, off):
    if not 0 <= off < len(data):
        raise ValueError('CharViewer string pointer is outside its payload.')
    end = data.find(b'\0', off)
    if end < 0:
        raise ValueError('Unterminated CharViewer string.')
    return bytes(data[off:end]).decode('utf-8', errors='surrogateescape')


def _parse_payload(payload):
    if len(payload) < 20:
        raise ValueError('Truncated CharViewer header.')
    inner_size = struct.unpack_from('>I', payload)[0]
    if inner_size < HEADER_SIZE or inner_size + 4 > len(payload):
        raise ValueError('Invalid CharViewer inner size.')
    body = payload[:inner_size + 4]
    version, count, first = struct.unpack_from('<IIq', body, 4)
    start = 12 + first
    if start < 20 or start + count * ENTRY_SIZE > len(body):
        raise ValueError('Invalid CharViewer entry table.')
    entries = []
    for i in range(count):
        base = start + i * ENTRY_SIZE
        e = {'_offset': base}
        nulls = []
        for off, key in _STR_FIELDS:
            ptr = struct.unpack_from('<q', body, base + off)[0]
            e[key] = _read_cstr(body, base + off + ptr) if ptr else ''
            if not ptr:
                nulls.append(key)
        e['_null_fields'] = tuple(nulls)
        e['_numeric_bytes'] = {}
        for off, key, fmt in _NUM_FIELDS:
            e[key] = struct.unpack_from('<' + fmt, body, base + off)[0]
            e['_numeric_bytes'][key] = bytes(body[base + off:base + off + struct.calcsize(fmt)])
        entries.append(e)
    return version, entries, bytes(body[20:start])


def _find_binary_chunk(data):
    if len(data) < 28 or data[:4] != b'NUCC':
        raise ValueError('Not an XFBIN file.')
    offset = (28 + struct.unpack_from('>I', data, 16)[0] + 3) & ~3
    if len(data) >= 68:
        offset += 8 * struct.unpack_from('>I', data, 64)[0]
    found = None
    while offset + 12 <= len(data):
        size = struct.unpack_from('>I', data, offset)[0]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError('Truncated NUCC chunk.')
        if size >= 20:
            payload = data[offset + 12:end]
            try:
                _parse_payload(payload)
            except (ValueError, struct.error):
                pass
            else:
                if found is not None:
                    raise ValueError('Ambiguous CharViewer payloads.')
                found = offset, size
        offset = end  # NUCC envelopes are contiguous, with no implicit padding.
    if found is None:
        raise ValueError('Could not locate a valid CharViewer payload.')
    return found


def parse_charviewer_xfbin(filepath):
    with open(filepath, 'rb') as stream:
        data = bytearray(stream.read())
    header, size = _find_binary_chunk(data)
    version, entries, _ = _parse_payload(data[header + 12:header + 12 + size])
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
        "cam_pos_z":         0.0,
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
        "resource_138":      "",
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
        "shop_padding":      0,
        "extra_costume":     "",
        "card_detail":       "",
        "entry_padding":     0,
    }



def _encoded(value):
    if not isinstance(value, str) or '\0' in value:
        raise ValueError('CharViewer strings cannot contain NUL bytes.')
    return value.encode('utf-8', errors='surrogateescape') + b'\0'


def _build_charviewer_binary(version, entries, notes=b''):
    buf = bytearray(struct.pack('<IIq', version, len(entries), 8 + len(notes)))
    buf.extend(notes)
    start = len(buf)
    buf.extend(bytes(len(entries) * ENTRY_SIZE))
    pool = {}
    for i, e in enumerate(entries):
        base = start + i * ENTRY_SIZE
        for off, key in _STR_FIELDS:
            value = e.get(key, '')
            encoded = _encoded(value)
            if not value and key in e.get('_null_fields', _STR_KEYS):
                continue
            if value not in pool:
                pool[value] = len(buf)
                buf.extend(encoded)
                buf.extend(bytes(-len(buf) % 8))
            struct.pack_into('<q', buf, base + off, pool[value] - base - off)
        for off, key, fmt in _NUM_FIELDS:
            value = e.get(key, 0)
            original = e.get('_numeric_bytes', {}).get(key)
            if original and _same_number(value, struct.unpack('<' + fmt, original)[0], fmt):
                buf[base + off:base + off + len(original)] = original
            else:
                struct.pack_into('<' + fmt, buf, base + off, value)
    return bytes(buf)


def _same_number(a, b, fmt):
    if fmt == 'f':
        return (math.isnan(a) and math.isnan(b)) or struct.pack('<f', a) == struct.pack('<f', b)
    return a == b


def save_charviewer_xfbin(filepath, original_data, version, entries):
    header, size = _find_binary_chunk(original_data)
    offset = header + 12
    old = original_data[offset:offset + size]
    _, previous, notes = _parse_payload(old)
    inner_end = 4 + struct.unpack_from('>I', old)[0]
    # Validate before touching the destination, including structural rebuilds.
    for e in entries:
        for key in _STR_KEYS:
            _encoded(e.get(key, ''))
        for _, key, fmt in _NUM_FIELDS:
            struct.pack('<' + fmt, e.get(key, 0))
    stable = (len(entries) == len(previous) and all(
        e.get('_offset') == p['_offset'] for e, p in zip(entries, previous)))
    if stable:
        payload = bytearray(old[:inner_end])
        struct.pack_into('<I', payload, 4, version)
        for e, p in zip(entries, previous):
            base = p['_offset']
            for off, key in _STR_FIELDS:
                value = e.get(key, '')
                if value != p[key]:
                    struct.pack_into('<q', payload, base + off, len(payload) - base - off if value else 0)
                    if value:
                        payload.extend(_encoded(value))
            for off, key, fmt in _NUM_FIELDS:
                if not _same_number(e.get(key, 0), p[key], fmt):
                    struct.pack_into('<' + fmt, payload, base + off, e.get(key, 0))
        if payload != old[:inner_end]:
            struct.pack_into('>I', payload, 0, len(payload) - 4)
        payload += old[inner_end:]
    else:
        inner = _build_charviewer_binary(version, entries, notes)
        # Bytes after the last referenced string can carry opaque extensions.
        used_end = 20 + len(notes) + len(previous) * ENTRY_SIZE
        for e in previous:
            for off, key in _STR_FIELDS:
                ptr = struct.unpack_from('<q', old, e['_offset'] + off)[0]
                if ptr:
                    used_end = max(used_end, e['_offset'] + off + ptr + len(_encoded(e[key])))
        inner += old[used_end:inner_end]
        # Retain data outside the declared inner binary too.
        tail = old[4 + struct.unpack_from('>I', old)[0]:]
        payload = struct.pack('>I', len(inner)) + inner + tail
    envelope = bytearray(original_data[header:offset])
    struct.pack_into('>I', envelope, 0, len(payload))
    output = original_data[:header] + envelope + payload + original_data[offset + size:]
    destination = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.arrow-charviewer-', dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
