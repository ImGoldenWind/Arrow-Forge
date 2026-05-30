"""ASB.acf CRI @UTF parser / writer.

ASB.acf is a top-level CRI @UTF table named ``Header``. Most editable
sections are nested @UTF blobs referenced from the single Header row.
This module keeps the original column storage/types, parses nested tables,
and rebuilds the file as valid @UTF so edited values can be saved back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import struct


UTF_MAGIC = b"@UTF"

ST_ZERO = 0x1
ST_CONSTANT = 0x3
ST_PERROW = 0x5

DT_UINT8 = 0x0
DT_SINT8 = 0x1
DT_UINT16 = 0x2
DT_SINT16 = 0x3
DT_UINT32 = 0x4
DT_SINT32 = 0x5
DT_UINT64 = 0x6
DT_SINT64 = 0x7
DT_FLOAT = 0x8
DT_DOUBLE = 0x9
DT_STRING = 0xA
DT_VLDATA = 0xB

DT_NAMES = {
    DT_UINT8: "u8",
    DT_SINT8: "i8",
    DT_UINT16: "u16",
    DT_SINT16: "i16",
    DT_UINT32: "u32",
    DT_SINT32: "i32",
    DT_UINT64: "u64",
    DT_SINT64: "i64",
    DT_FLOAT: "f32",
    DT_DOUBLE: "f64",
    DT_STRING: "str",
    DT_VLDATA: "vldata",
}

ST_NAMES = {
    ST_ZERO: "zero",
    ST_CONSTANT: "const",
    ST_PERROW: "row",
}

_INT_RANGES = {
    DT_UINT8: (0, 0xFF),
    DT_SINT8: (-0x80, 0x7F),
    DT_UINT16: (0, 0xFFFF),
    DT_SINT16: (-0x8000, 0x7FFF),
    DT_UINT32: (0, 0xFFFFFFFF),
    DT_SINT32: (-0x80000000, 0x7FFFFFFF),
    DT_UINT64: (0, 0xFFFFFFFFFFFFFFFF),
    DT_SINT64: (-0x8000000000000000, 0x7FFFFFFFFFFFFFFF),
}


@dataclass
class AcfBlob:
    data: bytes = b""
    table: "AcfUtfTable | None" = None

    def clone(self) -> "AcfBlob":
        return AcfBlob(bytes(self.data), self.table.clone() if self.table else None)


@dataclass
class AcfColumn:
    name: str
    storage: int
    dtype: int
    const_value: object = None

    @property
    def type_name(self) -> str:
        return DT_NAMES.get(self.dtype, f"type_{self.dtype}")

    @property
    def storage_name(self) -> str:
        return ST_NAMES.get(self.storage, f"storage_{self.storage}")


@dataclass
class AcfUtfTable:
    name: str
    columns: list[AcfColumn]
    rows: list[dict]
    rows_offset_high: int = 0
    strings_offset_high: int = 0
    data_offset_high: int = 0
    vldata_alignment: int = 1
    path: str = ""
    source_column: str = ""

    def clone(self) -> "AcfUtfTable":
        return copy.deepcopy(self)


def _normalize_offset(value: int, body_size: int) -> int:
    low = value & 0xFFFF
    if value > body_size and low <= body_size:
        return low
    return value


def _read_cstr(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\x00", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="replace")


def _read_typed_value(body: bytes, pos: int, dtype: int, str_base: int, data_base: int):
    if dtype == DT_UINT8:
        return body[pos], pos + 1
    if dtype == DT_SINT8:
        return struct.unpack_from("b", body, pos)[0], pos + 1
    if dtype == DT_UINT16:
        return struct.unpack_from(">H", body, pos)[0], pos + 2
    if dtype == DT_SINT16:
        return struct.unpack_from(">h", body, pos)[0], pos + 2
    if dtype == DT_UINT32:
        return struct.unpack_from(">I", body, pos)[0], pos + 4
    if dtype == DT_SINT32:
        return struct.unpack_from(">i", body, pos)[0], pos + 4
    if dtype == DT_UINT64:
        return struct.unpack_from(">Q", body, pos)[0], pos + 8
    if dtype == DT_SINT64:
        return struct.unpack_from(">q", body, pos)[0], pos + 8
    if dtype == DT_FLOAT:
        return struct.unpack_from(">f", body, pos)[0], pos + 4
    if dtype == DT_DOUBLE:
        return struct.unpack_from(">d", body, pos)[0], pos + 8
    if dtype == DT_STRING:
        str_off = struct.unpack_from(">I", body, pos)[0]
        return _read_cstr(body, str_base + str_off), pos + 4
    if dtype == DT_VLDATA:
        data_off, data_size = struct.unpack_from(">II", body, pos)
        return (data_base + data_off, data_size), pos + 8
    raise ValueError(f"Unsupported @UTF dtype {dtype}.")


def _pack_numeric(dtype: int, value) -> bytes:
    if dtype == DT_UINT8:
        return struct.pack("B", int(value))
    if dtype == DT_SINT8:
        return struct.pack("b", int(value))
    if dtype == DT_UINT16:
        return struct.pack(">H", int(value))
    if dtype == DT_SINT16:
        return struct.pack(">h", int(value))
    if dtype == DT_UINT32:
        return struct.pack(">I", int(value))
    if dtype == DT_SINT32:
        return struct.pack(">i", int(value))
    if dtype == DT_UINT64:
        return struct.pack(">Q", int(value))
    if dtype == DT_SINT64:
        return struct.pack(">q", int(value))
    if dtype == DT_FLOAT:
        return struct.pack(">f", float(value))
    if dtype == DT_DOUBLE:
        return struct.pack(">d", float(value))
    raise ValueError(f"Cannot pack @UTF dtype {dtype}.")


def _value_size(dtype: int) -> int:
    if dtype in (DT_UINT8, DT_SINT8):
        return 1
    if dtype in (DT_UINT16, DT_SINT16):
        return 2
    if dtype in (DT_UINT32, DT_SINT32, DT_FLOAT, DT_STRING):
        return 4
    if dtype in (DT_UINT64, DT_SINT64, DT_DOUBLE, DT_VLDATA):
        return 8
    raise ValueError(f"Unsupported @UTF dtype {dtype}.")


def _infer_vldata_alignment(offsets: list[int]) -> int:
    if len(offsets) < 2:
        return 1
    base = min(offsets)
    gcd = 0
    for off in offsets:
        gcd = _gcd(gcd, off - base)
    for candidate in (32, 16, 8, 4, 2):
        if gcd and gcd % candidate == 0:
            return candidate
    return 1


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return abs(a)


def _align(buf: bytearray, alignment: int):
    if alignment <= 1:
        return
    rem = len(buf) % alignment
    if rem:
        buf.extend(b"\x00" * (alignment - rem))


def parse_utf_table(data: bytes, offset: int = 0, path: str = "Header", source_column: str = "") -> AcfUtfTable:
    if data[offset:offset + 4] != UTF_MAGIC:
        raise ValueError(f"Not an @UTF table at 0x{offset:x}.")

    table_size = struct.unpack_from(">I", data, offset + 4)[0]
    body = data[offset + 8:offset + 8 + table_size]
    if len(body) < 24:
        raise ValueError("Truncated @UTF table.")

    body_size = len(body)
    raw_rows_offset, raw_strings_offset, raw_data_offset, table_name_offset = struct.unpack_from(">IIII", body, 0)
    rows_offset = _normalize_offset(raw_rows_offset, body_size)
    strings_offset = _normalize_offset(raw_strings_offset, body_size)
    data_offset = _normalize_offset(raw_data_offset, body_size)
    num_cols, row_size, num_rows = struct.unpack_from(">HHI", body, 16)
    table_name = _read_cstr(body, strings_offset + table_name_offset)

    pos = 24
    columns: list[AcfColumn] = []
    for _ in range(num_cols):
        flags = body[pos]
        pos += 1
        name_offset = struct.unpack_from(">I", body, pos)[0]
        pos += 4
        storage = (flags >> 4) & 0xF
        dtype = flags & 0xF
        name = _read_cstr(body, strings_offset + name_offset)
        const_value = None
        if storage == ST_CONSTANT:
            const_value, pos = _read_typed_value(body, pos, dtype, strings_offset, data_offset)
        columns.append(AcfColumn(name=name, storage=storage, dtype=dtype, const_value=const_value))

    rows: list[dict] = []
    vldata_offsets: list[int] = []
    for row_index in range(num_rows):
        row = {}
        row_pos = rows_offset + row_index * row_size
        for column in columns:
            if column.storage == ST_ZERO:
                row[column.name] = 0
                continue
            if column.storage == ST_CONSTANT:
                row[column.name] = column.const_value
                continue
            if column.storage != ST_PERROW:
                row[column.name] = None
                continue
            value, row_pos = _read_typed_value(body, row_pos, column.dtype, strings_offset, data_offset)
            if column.dtype == DT_VLDATA:
                blob_off, blob_size = value
                blob_bytes = bytes(body[blob_off:blob_off + blob_size]) if blob_size else b""
                nested = None
                if blob_bytes.startswith(UTF_MAGIC):
                    nested_path = f"{path}/{column.name}"
                    try:
                        nested = parse_utf_table(blob_bytes, 0, nested_path, column.name)
                    except Exception:
                        nested = None
                row[column.name] = AcfBlob(blob_bytes, nested)
                if blob_size:
                    vldata_offsets.append(blob_off)
            else:
                row[column.name] = value
        rows.append(row)

    return AcfUtfTable(
        name=table_name,
        columns=columns,
        rows=rows,
        rows_offset_high=raw_rows_offset & ~0xFFFF if raw_rows_offset > body_size else 0,
        strings_offset_high=raw_strings_offset & ~0xFFFF if raw_strings_offset > body_size else 0,
        data_offset_high=raw_data_offset & ~0xFFFF if raw_data_offset > body_size else 0,
        vldata_alignment=_infer_vldata_alignment(vldata_offsets),
        path=path,
        source_column=source_column,
    )


def parse_asb_acf(filepath: str) -> AcfUtfTable:
    with open(filepath, "rb") as fh:
        return parse_utf_table(fh.read())


def _intern_string(value: str, strings: list[str], offsets: dict[str, int]) -> int:
    value = "" if value is None else str(value)
    if value in offsets:
        return offsets[value]
    off = sum(len(item.encode("utf-8")) + 1 for item in strings)
    offsets[value] = off
    strings.append(value)
    return off


def _blob_bytes(value) -> bytes:
    if isinstance(value, AcfBlob):
        if value.table is not None:
            return build_utf_table(value.table)
        return bytes(value.data)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return b""


def build_utf_table(table: AcfUtfTable) -> bytes:
    strings: list[str] = []
    string_offsets: dict[str, int] = {}

    def intern(value: str) -> int:
        return _intern_string(value, strings, string_offsets)

    table_name_off = intern(table.name or "Header")
    column_name_offsets = [intern(column.name) for column in table.columns]

    for column in table.columns:
        if column.storage == ST_CONSTANT and column.dtype == DT_STRING:
            intern(str(column.const_value or ""))
    for row in table.rows:
        for column in table.columns:
            if column.storage == ST_PERROW and column.dtype == DT_STRING:
                intern(str(row.get(column.name, "")))

    str_blob = bytearray()
    for value in strings:
        str_blob += value.encode("utf-8") + b"\x00"

    col_defs = bytearray()
    for idx, column in enumerate(table.columns):
        col_defs += struct.pack("B", (column.storage << 4) | column.dtype)
        col_defs += struct.pack(">I", column_name_offsets[idx])
        if column.storage == ST_CONSTANT:
            if column.dtype == DT_STRING:
                col_defs += struct.pack(">I", intern(str(column.const_value or "")))
            elif column.dtype == DT_VLDATA:
                col_defs += struct.pack(">II", 0, 0)
            else:
                col_defs += _pack_numeric(column.dtype, column.const_value or 0)

    row_size = sum(_value_size(column.dtype) for column in table.columns if column.storage == ST_PERROW)
    vldata = bytearray()
    rows_blob = bytearray()

    for row in table.rows:
        for column in table.columns:
            if column.storage != ST_PERROW:
                continue
            value = row.get(column.name)
            if column.dtype == DT_STRING:
                rows_blob += struct.pack(">I", intern(str(value or "")))
            elif column.dtype == DT_VLDATA:
                blob = _blob_bytes(value)
                if blob:
                    _align(vldata, max(1, int(table.vldata_alignment or 1)))
                    blob_off = len(vldata)
                    vldata += blob
                    rows_blob += struct.pack(">II", blob_off, len(blob))
                else:
                    rows_blob += struct.pack(">II", 0, 0)
            else:
                rows_blob += _pack_numeric(column.dtype, value or 0)

    header_size = 24
    rows_offset = header_size + len(col_defs)
    strings_offset = rows_offset + row_size * len(table.rows)
    data_offset = strings_offset + len(str_blob)

    raw_rows_offset = rows_offset | table.rows_offset_high if table.rows_offset_high else rows_offset
    raw_strings_offset = strings_offset | table.strings_offset_high if table.strings_offset_high else strings_offset
    raw_data_offset = data_offset | table.data_offset_high if table.data_offset_high else data_offset

    body = bytearray()
    body += struct.pack(">IIII", raw_rows_offset, raw_strings_offset, raw_data_offset, table_name_off)
    body += struct.pack(">HHI", len(table.columns), row_size, len(table.rows))
    body += col_defs
    body += rows_blob
    body += str_blob
    body += vldata
    _align(body, 8)
    return UTF_MAGIC + struct.pack(">I", len(body)) + body


def save_asb_acf(filepath: str, table: AcfUtfTable) -> None:
    with open(filepath, "wb") as fh:
        fh.write(build_utf_table(table))


def make_default_row(table: AcfUtfTable, source: dict | None = None) -> dict:
    if source is not None:
        result = {}
        for column in table.columns:
            value = source.get(column.name)
            if isinstance(value, AcfBlob):
                result[column.name] = value.clone()
            else:
                result[column.name] = copy.deepcopy(value)
        return result

    row = {}
    for column in table.columns:
        if column.dtype == DT_STRING:
            row[column.name] = ""
        elif column.dtype == DT_VLDATA:
            row[column.name] = AcfBlob()
        elif column.dtype in (DT_FLOAT, DT_DOUBLE):
            row[column.name] = 0.0
        else:
            row[column.name] = 0
    return row


def validate_cell_value(column: AcfColumn, text: str):
    text = text.strip()
    if column.dtype == DT_STRING:
        return text
    if column.dtype == DT_VLDATA:
        compact = text.replace(" ", "").replace("\n", "").replace("\t", "")
        if not compact:
            return AcfBlob()
        try:
            return AcfBlob(bytes.fromhex(compact))
        except ValueError as exc:
            raise ValueError("invalid_hex") from exc
    if column.dtype in _INT_RANGES:
        try:
            value = int(text or "0", 0)
        except ValueError as exc:
            raise ValueError("invalid_integer") from exc
        min_value, max_value = _INT_RANGES[column.dtype]
        if value < min_value or value > max_value:
            raise ValueError("integer_range")
        return value
    if column.dtype in (DT_FLOAT, DT_DOUBLE):
        try:
            return float(text or "0")
        except ValueError as exc:
            raise ValueError("invalid_float") from exc
    return text
