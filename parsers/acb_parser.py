import os
import struct

from parsers.cpk_parser import crypt_jojo_asbr


UTF_MAGIC = b"@UTF"
INVALID_U16 = 0xFFFF
INVALID_U32 = 0xFFFFFFFF

_ST_ZERO = 0x1
_ST_CONSTANT = 0x3
_ST_PERROW = 0x5

_DT_UINT8 = 0x0
_DT_SINT8 = 0x1
_DT_UINT16 = 0x2
_DT_SINT16 = 0x3
_DT_UINT32 = 0x4
_DT_SINT32 = 0x5
_DT_UINT64 = 0x6
_DT_SINT64 = 0x7
_DT_FLOAT = 0x8
_DT_DOUBLE = 0x9
_DT_STRING = 0xA
_DT_VLDATA = 0xB


class AcbUtfTable:
    __slots__ = ("name", "rows", "body")

    def __init__(self, name: str, rows: list[dict], body: bytes):
        self.name = name
        self.rows = rows
        self.body = body


def _read_cstr(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\x00", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="replace")


def _normalize_offset(value: int, size: int) -> int:
    # Some CRI tables set a high flag on offsets. The low 16 bits are the
    # real in-table position for these ACB/ACF metadata files.
    low = value & 0xFFFF
    if value > size and low <= size:
        return low
    return value


def _read_typed_value(body: bytes, pos: int, dtype: int, str_base: int, data_base: int):
    if dtype == _DT_UINT8:
        return body[pos], pos + 1
    if dtype == _DT_SINT8:
        return struct.unpack_from("b", body, pos)[0], pos + 1
    if dtype == _DT_UINT16:
        return struct.unpack_from(">H", body, pos)[0], pos + 2
    if dtype == _DT_SINT16:
        return struct.unpack_from(">h", body, pos)[0], pos + 2
    if dtype == _DT_UINT32:
        return struct.unpack_from(">I", body, pos)[0], pos + 4
    if dtype == _DT_SINT32:
        return struct.unpack_from(">i", body, pos)[0], pos + 4
    if dtype == _DT_UINT64:
        return struct.unpack_from(">Q", body, pos)[0], pos + 8
    if dtype == _DT_SINT64:
        return struct.unpack_from(">q", body, pos)[0], pos + 8
    if dtype == _DT_FLOAT:
        return struct.unpack_from(">f", body, pos)[0], pos + 4
    if dtype == _DT_DOUBLE:
        return struct.unpack_from(">d", body, pos)[0], pos + 8
    if dtype == _DT_STRING:
        str_off = struct.unpack_from(">I", body, pos)[0]
        return _read_cstr(body, str_base + str_off), pos + 4
    if dtype == _DT_VLDATA:
        data_off, data_size = struct.unpack_from(">II", body, pos)
        return (data_base + data_off, data_size), pos + 8
    return None, pos


def _parse_utf_at(data: bytes, offset: int = 0) -> tuple[AcbUtfTable, int]:
    if data[offset:offset + 4] != UTF_MAGIC:
        raise ValueError(f"Not an @UTF table at 0x{offset:x}")

    table_size = struct.unpack_from(">I", data, offset + 4)[0]
    body = data[offset + 8:offset + 8 + table_size]
    if len(body) < 24:
        raise ValueError("Truncated @UTF table")

    body_size = len(body)
    rows_offset = _normalize_offset(struct.unpack_from(">I", body, 0)[0], body_size)
    strings_offset = _normalize_offset(struct.unpack_from(">I", body, 4)[0], body_size)
    data_offset = _normalize_offset(struct.unpack_from(">I", body, 8)[0], body_size)
    table_name_offset = struct.unpack_from(">I", body, 12)[0]
    num_cols, row_size, num_rows = struct.unpack_from(">HHI", body, 16)

    pos = 24
    columns = []
    for _ in range(num_cols):
        flags = body[pos]
        pos += 1
        name_offset = struct.unpack_from(">I", body, pos)[0]
        pos += 4

        storage = (flags >> 4) & 0xF
        dtype = flags & 0xF
        name = _read_cstr(body, strings_offset + name_offset)

        const_value = None
        if storage == _ST_CONSTANT:
            const_value, pos = _read_typed_value(
                body, pos, dtype, strings_offset, data_offset)
        columns.append((storage, dtype, name, const_value))

    rows = []
    for row_index in range(num_rows):
        row = {}
        row_pos = rows_offset + row_index * row_size
        for storage, dtype, name, const_value in columns:
            if storage == _ST_ZERO:
                row[name] = 0
            elif storage == _ST_CONSTANT:
                row[name] = const_value
            elif storage == _ST_PERROW:
                value, row_pos = _read_typed_value(
                    body, row_pos, dtype, strings_offset, data_offset)
                row[name] = value
            else:
                row[name] = None
        rows.append(row)

    table_name = _read_cstr(body, strings_offset + table_name_offset)
    return AcbUtfTable(table_name, rows, body), offset + 8 + table_size


def _read_acb_bytes(filepath: str) -> bytes:
    with open(filepath, "rb") as f:
        raw = f.read()
    if raw[:4] == UTF_MAGIC:
        return raw

    decrypted = crypt_jojo_asbr(raw)
    if decrypted[:4] == UTF_MAGIC:
        return decrypted
    return raw


def _vldata_bytes(table: AcbUtfTable, value) -> bytes:
    if not isinstance(value, tuple):
        return b""
    offset, size = value
    if size <= 0 or offset < 0 or offset >= len(table.body):
        return b""
    return table.body[offset:offset + size]


def _u16be_list(table: AcbUtfTable, value) -> list[int]:
    data = _vldata_bytes(table, value)
    return [
        struct.unpack_from(">H", data, pos)[0]
        for pos in range(0, len(data) - 1, 2)
    ]


def _reference_items(table: AcbUtfTable, value) -> list[tuple[int, int]]:
    data = _vldata_bytes(table, value)
    refs = []
    for pos in range(0, len(data) - 3, 4):
        ref_type, ref_index = struct.unpack_from(">HH", data, pos)
        refs.append((ref_type, ref_index))
    return refs


def _command_wave_indexes(command: bytes) -> list[int]:
    indexes = []
    patterns = (
        bytes.fromhex("004f05000100"),
        bytes.fromhex("07d004000200"),
    )
    for pattern in patterns:
        start = 0
        while True:
            pos = command.find(pattern, start)
            if pos < 0:
                break
            if pos + len(pattern) + 2 <= len(command):
                indexes.append(struct.unpack_from("<H", command, pos + len(pattern))[0])
            start = pos + 1
    return indexes


def _nested_tables(data: bytes, header: AcbUtfTable) -> dict[str, AcbUtfTable]:
    if not header.rows:
        return {}

    tables = {}
    for name, value in header.rows[0].items():
        if not isinstance(value, tuple):
            continue
        body_offset, size = value
        abs_offset = 8 + body_offset
        if size > 0 and data[abs_offset:abs_offset + 4] == UTF_MAGIC:
            try:
                table, _ = _parse_utf_at(data, abs_offset)
            except Exception:
                continue
            tables[name] = table
    return tables


def parse_acb_awb_labels(filepath: str) -> dict[int, str]:
    """Return AWB waveform ID -> cue name labels from a CRI ACB file.

    The parser focuses on the metadata needed by the AWB editor. It handles the
    ASBR-encrypted ACB files and the common CRI cue layouts used by BGM and
    character voice banks.
    """
    data = _read_acb_bytes(filepath)
    header, _ = _parse_utf_at(data)
    tables = _nested_tables(data, header)

    cue_table = tables.get("CueTable")
    cue_name_table = tables.get("CueNameTable")
    waveform_table = tables.get("WaveformTable")
    synth_table = tables.get("SynthTable")
    command_table = tables.get("CommandTable")
    track_table = tables.get("TrackTable")
    sequence_table = tables.get("SequenceTable")
    if not (cue_table and cue_name_table and waveform_table):
        return {}

    waveform_ids = [row.get("Id") for row in waveform_table.rows]
    command_bytes = []
    if command_table:
        command_bytes = [
            _vldata_bytes(command_table, row.get("Command"))
            for row in command_table.rows
        ]

    def valid_index(index: int, rows: list) -> bool:
        return isinstance(index, int) and 0 <= index < len(rows)

    def waveform_id_at(index: int):
        if valid_index(index, waveform_ids):
            return waveform_ids[index]
        return None

    def from_command(command_index: int) -> list[int]:
        if command_index in (None, INVALID_U16) or not valid_index(command_index, command_bytes):
            return []
        return [
            waveform_ids[i]
            for i in _command_wave_indexes(command_bytes[command_index])
            if valid_index(i, waveform_ids)
        ]

    def resolve_synth(index: int, seen: set[tuple[str, int]]) -> list[int]:
        if not synth_table or not valid_index(index, synth_table.rows):
            return []
        key = ("synth", index)
        if key in seen:
            return []
        seen.add(key)

        row = synth_table.rows[index]
        ids = from_command(row.get("CommandIndex"))
        for ref_type, ref_index in _reference_items(synth_table, row.get("ReferenceItems")):
            if ref_type == 1:
                waveform_id = waveform_id_at(ref_index)
                if waveform_id is not None:
                    ids.append(waveform_id)
            elif ref_type == 2:
                ids.extend(resolve_track(ref_index, seen))
            elif ref_type == 3:
                ids.extend(resolve_sequence(ref_index, seen))
        return ids

    def resolve_track(index: int, seen: set[tuple[str, int]]) -> list[int]:
        if not track_table or not valid_index(index, track_table.rows):
            return []
        key = ("track", index)
        if key in seen:
            return []
        seen.add(key)

        row = track_table.rows[index]
        ids = from_command(row.get("CommandIndex"))
        if ids:
            return ids
        event_index = row.get("EventIndex")
        if event_index not in (None, INVALID_U16):
            ids.extend(resolve_synth(event_index, seen))
        return ids

    def resolve_sequence(index: int, seen: set[tuple[str, int]]) -> list[int]:
        if not sequence_table or not valid_index(index, sequence_table.rows):
            return []
        key = ("sequence", index)
        if key in seen:
            return []
        seen.add(key)

        row = sequence_table.rows[index]
        ids = from_command(row.get("CommandIndex"))
        if ids:
            return ids
        for track_index in _u16be_list(sequence_table, row.get("TrackIndex")):
            ids.extend(resolve_track(track_index, seen))
        return ids

    def resolve_cue(row: dict) -> list[int]:
        ref_type = row.get("ReferenceType")
        ref_index = row.get("ReferenceIndex")
        if ref_type == 1:
            return resolve_synth(ref_index, set())
        if ref_type == 2:
            return resolve_track(ref_index, set())
        if ref_type == 3:
            return resolve_sequence(ref_index, set())
        return []

    labels_by_id: dict[int, list[str]] = {}
    for name_row in cue_name_table.rows:
        cue_name = str(name_row.get("CueName") or "").strip()
        cue_index = name_row.get("CueIndex")
        if not cue_name or not valid_index(cue_index, cue_table.rows):
            continue
        for waveform_id in resolve_cue(cue_table.rows[cue_index]):
            if isinstance(waveform_id, int) and waveform_id != INVALID_U16:
                labels_by_id.setdefault(waveform_id, [])
                if cue_name not in labels_by_id[waveform_id]:
                    labels_by_id[waveform_id].append(cue_name)

    return {
        waveform_id: " / ".join(names)
        for waveform_id, names in labels_by_id.items()
    }


def find_companion_acb(awb_path: str) -> str:
    base, _ = os.path.splitext(awb_path)
    direct = base + ".acb"
    if os.path.isfile(direct):
        return direct

    folder = os.path.dirname(awb_path) or "."
    stem = os.path.basename(base).lower()
    try:
        for name in os.listdir(folder):
            candidate_base, ext = os.path.splitext(name)
            if ext.lower() == ".acb" and candidate_base.lower() == stem:
                return os.path.join(folder, name)
    except OSError:
        pass
    return ""


def load_companion_acb_labels(awb_path: str) -> tuple[dict[int, str], str]:
    acb_path = find_companion_acb(awb_path)
    if not acb_path:
        return {}, ""
    return parse_acb_awb_labels(acb_path), acb_path
