"""
CPK (CRI Middleware) archive parser, extractor, and builder.

Supports:
  - Reading @UTF tables (CRI's internal table format)
  - Parsing CPK header and TOC (Table of Contents)
  - Extracting files with CRILAYLA decompression
  - Building new CPK archives (files stored uncompressed)
"""

import struct
import os
import math
import zlib

_UTF_XOR_SEED = 0x0000655F
_UTF_XOR_MULT = 0x00004115
_CPK_OFFSET_SENTINEL = 0xFFFFFFFFFFFFFFFF
_ASBR_UNENCRYPTED_CPKS = {"adx2.cpk", "movie.cpk", "sound.cpk"}
_TOC_OFFSET_FALLBACK_BASE = 0x800

# @UTF table parser

_UTF_MAGIC = b"@UTF"

# Column storage types
_ST_ZERO     = 0x1   # value is always 0
_ST_CONSTANT = 0x3   # single value shared by all rows (stored in column def)
_ST_PERROW   = 0x5   # individual value per row

# Column data types
_DT_UINT8  = 0x0
_DT_SINT8  = 0x1
_DT_UINT16 = 0x2
_DT_SINT16 = 0x3
_DT_UINT32 = 0x4
_DT_SINT32 = 0x5
_DT_UINT64 = 0x6
_DT_SINT64 = 0x7
_DT_FLOAT  = 0x8
_DT_DOUBLE = 0x9
_DT_STRING = 0xA
_DT_VLDATA = 0xB


def _str_at(body: bytes, offset: int) -> str:
    end = body.index(b"\x00", offset)
    return body[offset:end].decode("utf-8", errors="replace")


def _read_typed_value(body: bytes, pos: int, dtype: int,
                       str_base: int, dat_base: int):
    """Read one typed value from *body* at *pos*.  Returns (value, new_pos)."""
    if dtype == _DT_UINT8:
        return body[pos], pos + 1
    elif dtype == _DT_SINT8:
        return struct.unpack_from("b", body, pos)[0], pos + 1
    elif dtype == _DT_UINT16:
        return struct.unpack_from(">H", body, pos)[0], pos + 2
    elif dtype == _DT_SINT16:
        return struct.unpack_from(">h", body, pos)[0], pos + 2
    elif dtype == _DT_UINT32:
        return struct.unpack_from(">I", body, pos)[0], pos + 4
    elif dtype == _DT_SINT32:
        return struct.unpack_from(">i", body, pos)[0], pos + 4
    elif dtype == _DT_UINT64:
        return struct.unpack_from(">Q", body, pos)[0], pos + 8
    elif dtype == _DT_SINT64:
        return struct.unpack_from(">q", body, pos)[0], pos + 8
    elif dtype == _DT_FLOAT:
        return struct.unpack_from(">f", body, pos)[0], pos + 4
    elif dtype == _DT_DOUBLE:
        return struct.unpack_from(">d", body, pos)[0], pos + 8
    elif dtype == _DT_STRING:
        soff = struct.unpack_from(">I", body, pos)[0]
        return _str_at(body, str_base + soff), pos + 4
    elif dtype == _DT_VLDATA:
        voff = struct.unpack_from(">I", body, pos)[0]
        vsz  = struct.unpack_from(">I", body, pos + 4)[0]
        return (dat_base + voff, vsz), pos + 8
    else:
        return None, pos


def parse_utf(data: bytes) -> list[dict]:
    """
    Parse an @UTF table from *data* (bytes starting with b'@UTF').
    Returns a list of row dicts.
    """
    if data[:4] != _UTF_MAGIC:
        raise ValueError(f"Not an @UTF table (got {data[:4]!r})")

    # Everything after the 8-byte prefix (magic + table_size) is the body
    body = data[8:]

    rows_offset    = struct.unpack_from(">I", body, 0)[0]
    strings_offset = struct.unpack_from(">I", body, 4)[0]
    data_offset    = struct.unpack_from(">I", body, 8)[0]
    _table_name_off = struct.unpack_from(">I", body, 12)[0]
    num_cols       = struct.unpack_from(">H", body, 16)[0]
    row_size       = struct.unpack_from(">H", body, 18)[0]
    num_rows       = struct.unpack_from(">I", body, 20)[0]

    # Parse column definitions (starts at offset 24 inside body)
    pos = 24
    col_defs = []
    for _ in range(num_cols):
        col_flags = body[pos]; pos += 1
        name_off  = struct.unpack_from(">I", body, pos)[0]; pos += 4
        col_name  = _str_at(body, strings_offset + name_off)
        storage   = (col_flags >> 4) & 0xF
        dtype     = col_flags & 0xF

        const_val = None
        if storage == _ST_CONSTANT:
            const_val, pos = _read_typed_value(
                body, pos, dtype, strings_offset, data_offset)

        col_defs.append((storage, dtype, col_name, const_val))

    # Parse rows
    rows = []
    for ri in range(num_rows):
        row = {}
        rpos = rows_offset + ri * row_size
        for storage, dtype, col_name, const_val in col_defs:
            if storage == _ST_ZERO:
                row[col_name] = 0
            elif storage == _ST_CONSTANT:
                row[col_name] = const_val
            elif storage == _ST_PERROW:
                val, rpos = _read_typed_value(
                    body, rpos, dtype, strings_offset, data_offset)
                row[col_name] = val
            else:
                row[col_name] = None
        rows.append(row)

    return rows


# CPK / ASBR encryption helpers

def decrypt_utf_packet(data: bytes) -> bytes:
    """Decrypt CRI's simple @UTF table obfuscation."""
    out = bytearray(len(data))
    mask = _UTF_XOR_SEED
    for i, value in enumerate(data):
        out[i] = value ^ (mask & 0xFF)
        mask = (mask * _UTF_XOR_MULT) & 0xFFFFFFFF
    return bytes(out)


def crypt_jojo_asbr(data: bytes) -> bytes:
    """Apply ASBR's per-file XOR stream. The operation is symmetric."""
    out = bytearray(data)
    size = len(out)
    remaining = size
    pos = 0

    def u32(value: int) -> int:
        return value & 0xFFFFFFFF

    v1 = u32(size * 0x5F64 + 0x5DEC219F)
    v1 = u32((v1 // 32) ^ u32(v1 * 0x1DA597))
    v2 = u32((v1 // 32 + 0x85C9C2) ^ u32(v1 * 0x1DA597))
    v3 = u32((v2 // 32 + 0x10B9384) ^ u32(v2 * 0x1DA597))
    v4 = u32((v3 // 32 + 0x1915D46) ^ u32(v3 * 0x1DA597))

    while remaining > 0:
        v1 = u32(u32(v1 * 2048) ^ v1)
        v5 = u32(v4 ^ (((v4 // 2048) ^ v1) // 256) ^ v1)
        key = (
            v5 & 0xFF,
            (v5 >> 8) & 0xFF,
            (v5 >> 16) & 0xFF,
            (v5 >> 24) & 0xFF,
        )

        take = min(4, remaining)
        for i in range(take):
            out[pos + i] ^= key[i]

        remaining -= take
        pos += 4
        v1, v2, v3, v4 = v2, v3, v4, v5

    return bytes(out)


def _cpk_uses_asbr_file_encryption(path: str, header: dict) -> bool:
    """Match CriPakTools' ASBR rule while avoiding archives built by this app."""
    if str(header.get("Tvers", "")) == "ArrowForge1.0":
        return False
    return os.path.basename(path).lower() not in _ASBR_UNENCRYPTED_CPKS


def _toc_add_offset(content_offset: int, toc_offset: int) -> int:
    """Compute the absolute-file offset base used by TOC FileOffset values."""
    content_offset = int(content_offset or 0)
    toc_offset = int(toc_offset or 0)
    toc_base = toc_offset
    if toc_base > _TOC_OFFSET_FALLBACK_BASE:
        toc_base = _TOC_OFFSET_FALLBACK_BASE
    if content_offset and content_offset < toc_base:
        return content_offset
    return toc_base


# CRILAYLA decompression

def decompress_crilayla(comp_data: bytes, uncomp_size: int) -> bytes:
    """
    Decompress CRILAYLA-compressed data.

    *comp_data*  - the compressed bytes as stored in CPK. Standard CRILAYLA
                   streams include a 16-byte header and a 0x100-byte raw prefix.
    *uncomp_size* - expected output size (ExtractSize from TOC).

    Returns decompressed bytes, or the original *comp_data* if decompression
    fails (callers should check len(result) == uncomp_size).
    """
    if comp_data[:8] == b"CRILAYLA":
        try:
            result = _crilayla_decompress_with_header(comp_data)
            if not uncomp_size or len(result) == uncomp_size:
                return result
        except Exception:
            pass

    # Headerless payload fallback for uncommon CPK variants.
    try:
        result = _crilayla_decompress(comp_data, uncomp_size)
        if len(result) == uncomp_size:
            return result
    except Exception:
        pass

    # Try zlib deflate with header, then raw deflate.
    for wbits in (15, -15):
        try:
            result = zlib.decompress(comp_data, wbits)
            if len(result) == uncomp_size:
                return result
        except Exception:
            pass

    # Cannot decompress; return raw bytes so the file can still be written.
    return comp_data


def _crilayla_decompress_with_header(data: bytes) -> bytes:
    """Decompress standard CRILAYLA data, including the embedded 0x100 prefix."""
    if len(data) < 0x110 or data[:8] != b"CRILAYLA":
        raise ValueError("Not a complete CRILAYLA stream")

    uncompressed_size = struct.unpack_from("<I", data, 8)[0]
    header_offset = struct.unpack_from("<I", data, 12)[0]
    prefix_pos = 0x10 + header_offset
    prefix_end = prefix_pos + 0x100
    if prefix_end > len(data):
        raise ValueError("Invalid CRILAYLA header offset")

    result = bytearray(uncompressed_size + 0x100)
    result[:0x100] = data[prefix_pos:prefix_end]

    input_offset = len(data) - 0x100 - 1
    output_end = len(result) - 1
    bit_pool = 0
    bits_left = 0
    bytes_output = 0
    vle_lens = (2, 3, 5, 8)

    def get_next_bits(bit_count: int) -> int:
        nonlocal input_offset, bit_pool, bits_left
        out_bits = 0
        produced = 0
        while produced < bit_count:
            if bits_left == 0:
                if input_offset < 0:
                    raise ValueError("CRILAYLA bitstream underrun")
                bit_pool = data[input_offset]
                bits_left = 8
                input_offset -= 1

            bits_this_round = min(bits_left, bit_count - produced)
            out_bits <<= bits_this_round
            out_bits |= (
                bit_pool >> (bits_left - bits_this_round)
            ) & ((1 << bits_this_round) - 1)
            bits_left -= bits_this_round
            produced += bits_this_round
        return out_bits

    while bytes_output < uncompressed_size:
        if get_next_bits(1) > 0:
            backreference_offset = (
                output_end - bytes_output + get_next_bits(13) + 3
            )
            backreference_length = 3

            for bit_count in vle_lens:
                this_level = get_next_bits(bit_count)
                backreference_length += this_level
                if this_level != ((1 << bit_count) - 1):
                    break
            else:
                this_level = 0xFF
                while this_level == 0xFF:
                    this_level = get_next_bits(8)
                    backreference_length += this_level

            for _ in range(backreference_length):
                if bytes_output >= uncompressed_size:
                    break
                if not 0 <= backreference_offset < len(result):
                    raise ValueError("CRILAYLA backreference out of bounds")
                result[output_end - bytes_output] = result[backreference_offset]
                backreference_offset -= 1
                bytes_output += 1
        else:
            result[output_end - bytes_output] = get_next_bits(8)
            bytes_output += 1

    return bytes(result)


def _crilayla_decompress(comp_data: bytes, uncomp_size: int) -> bytes:
    """
    Core CRILAYLA decompression.

    The compressed bitstream in CPK is stored in reverse byte order.
    We reverse it, then read bits LSB-first using an LZSS back-reference
    scheme where we write the output array from the end towards the start.
    """
    # Reverse the compressed payload
    rev = bytearray(reversed(comp_data))

    output   = bytearray(uncomp_size)
    out_pos  = uncomp_size       # write pointer (decrements toward 0)

    bit_pool = 0
    bits_left = 0
    read_pos  = 0

    def get_bits(n: int) -> int:
        nonlocal bit_pool, bits_left, read_pos
        while bits_left < n:
            if read_pos < len(rev):
                bit_pool |= rev[read_pos] << bits_left
                read_pos += 1
            bits_left += 8
        value = bit_pool & ((1 << n) - 1)
        bit_pool >>= n
        bits_left -= n
        return value

    while out_pos > 0:
        if get_bits(1):                          # back-reference
            ref_offset = get_bits(13) + 3        # distance (bytes ahead in output)
            ref_len    = 3                        # minimum match length
            while True:
                part = get_bits(2)
                ref_len += part
                if part != 3:
                    break
            for _ in range(ref_len):
                if out_pos == 0:
                    break
                out_pos -= 1
                src = out_pos + ref_offset
                # Out-of-bounds src = reference to unwritten region → treat as 0
                output[out_pos] = output[src] if src < len(output) else 0
        else:                                    # literal byte
            out_pos -= 1
            output[out_pos] = get_bits(8)

    return bytes(output)


# CPK entry dataclass-like container

class CpkEntry:
    __slots__ = ("dir_name", "file_name", "file_size", "extract_size",
                 "file_offset", "id", "user_string",
                 "absolute_offset", "is_compressed")

    def __init__(self, row: dict, offset_base: int):
        self.dir_name      = row.get("DirName", "") or ""
        self.file_name     = row.get("FileName", "") or ""
        self.file_size     = row.get("FileSize", 0) or 0
        self.extract_size  = row.get("ExtractSize", 0) or 0
        self.file_offset   = row.get("FileOffset", 0) or 0
        self.id            = row.get("ID", 0) or 0
        self.user_string   = row.get("UserString", "") or ""

        self.absolute_offset = offset_base + self.file_offset
        self.is_compressed   = (self.file_size != self.extract_size
                                 and self.extract_size > 0)

    @property
    def path(self) -> str:
        if self.dir_name:
            return self.dir_name + "/" + self.file_name
        return self.file_name

    @property
    def display_size(self) -> int:
        return self.extract_size if self.extract_size else self.file_size


# CPK file reader

class CpkReader:
    """Opens and parses a CPK archive, providing access to its entries."""

    _CPK_MAGIC = b"CPK "
    _TOC_MAGIC = b"TOC "
    _SECTION_HEADER_SIZE = 16   # magic(4) + flags(4) + size(8)

    def __init__(self, path: str):
        self.path    = path
        self.entries : list[CpkEntry] = []
        self._header : dict           = {}
        self._file   = None           # kept open for lazy extraction
        self._file_data_encrypted = False

        self._parse()

    # internal

    def _parse(self):
        with open(self.path, "rb") as f:
            cpk_utf_data = self._read_section_utf(f, 0, self._CPK_MAGIC)
            hdr_rows = parse_utf(cpk_utf_data)
            if not hdr_rows:
                raise ValueError("Empty CPK header @UTF table")
            self._header = hdr_rows[0]
            self._file_data_encrypted = _cpk_uses_asbr_file_encryption(
                self.path, self._header)

            content_offset = self._header.get("ContentOffset", 0) or 0
            toc_offset     = self._header.get("TocOffset", 0) or 0
            # toc_size       = self._header.get("TocSize", 0) or 0

            if not toc_offset or toc_offset == _CPK_OFFSET_SENTINEL:
                raise ValueError("CPK has no TOC (TocOffset = 0)")

            toc_utf_data = self._read_section_utf(f, toc_offset, self._TOC_MAGIC)
            toc_rows = parse_utf(toc_utf_data)
            offset_base = _toc_add_offset(content_offset, toc_offset)

            self.entries = [CpkEntry(row, offset_base) for row in toc_rows]

    @staticmethod
    def _read_section_utf(f, section_offset: int, expected_magic: bytes) -> bytes:
        """Read and decrypt a CPK section's @UTF payload."""
        f.seek(section_offset)
        magic = f.read(4)
        if magic != expected_magic:
            raise ValueError(
                f"Expected {expected_magic!r} at 0x{section_offset:x}, got {magic!r}")
        f.read(4)  # flags / unknown
        payload_size = struct.unpack("<Q", f.read(8))[0]
        payload = f.read(payload_size)
        if payload[:4] != _UTF_MAGIC:
            payload = decrypt_utf_packet(payload)
        if payload[:4] != _UTF_MAGIC:
            raise ValueError(
                f"Expected @UTF payload at 0x{section_offset + 0x10:x}, got {payload[:4]!r}")
        return payload

    # public API

    @property
    def num_files(self) -> int:
        return len(self.entries)

    @property
    def directories(self) -> list[str]:
        seen = set()
        result = []
        for e in self.entries:
            d = e.dir_name
            if d and d not in seen:
                seen.add(d)
                result.append(d)
        return sorted(result)

    def entries_for_dir(self, dir_name: str) -> list[CpkEntry]:
        return [e for e in self.entries if e.dir_name == dir_name]

    def read_entry_data(self, entry: CpkEntry,
                        decompress: bool = True) -> bytes:
        """
        Return the raw (or decompressed) bytes for *entry*.

        Raises IOError / ValueError on failure.
        """
        with open(self.path, "rb") as f:
            f.seek(entry.absolute_offset)
            raw = f.read(entry.file_size)

        if self._file_data_encrypted:
            raw = crypt_jojo_asbr(raw)

        if decompress and entry.is_compressed:
            return decompress_crilayla(raw, entry.extract_size)
        return raw

    def extract_entry(self, entry: CpkEntry, out_dir: str,
                      decompress: bool = True) -> tuple[str, bool]:
        """
        Extract *entry* under *out_dir*, preserving the directory path.

        Returns (dest_path, decompressed_ok).
        *decompressed_ok* is False when decompression was attempted but
        failed (output size mismatch); the raw compressed bytes are written.
        """
        data         = self.read_entry_data(entry, decompress=decompress)
        expected     = entry.extract_size if entry.extract_size else entry.file_size
        decomp_ok    = not entry.is_compressed or len(data) == expected
        rel_path     = entry.path.replace("/", os.sep)
        dest         = os.path.join(out_dir, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return dest, decomp_ok

    def extract_all(self, out_dir: str, decompress: bool = True,
                    progress_cb=None):
        """
        Extract every entry to *out_dir*.

        *progress_cb(done, total, path)* is called after each file if provided.
        """
        total = len(self.entries)
        for i, entry in enumerate(self.entries):
            dest = self.extract_entry(entry, out_dir, decompress=decompress)
            if progress_cb:
                progress_cb(i + 1, total, dest)

    def extract_dir(self, cpk_dir: str, out_dir: str,
                    decompress: bool = True, progress_cb=None):
        """
        Extract only the entries whose DirName matches *cpk_dir*.
        """
        entries = self.entries_for_dir(cpk_dir)
        total   = len(entries)
        for i, entry in enumerate(entries):
            dest = self.extract_entry(entry, out_dir, decompress=decompress)
            if progress_cb:
                progress_cb(i + 1, total, dest)


# @UTF table builder (for CPK writing)

_COL_FLAG_ZERO     = (_ST_ZERO     << 4)
_COL_FLAG_CONSTANT = (_ST_CONSTANT << 4)
_COL_FLAG_PERROW   = (_ST_PERROW   << 4)


def _encode_string(s: str, string_table: list, string_map: dict) -> int:
    """Add *s* to the string table if not already present; return its offset."""
    if s in string_map:
        return string_map[s]
    off = sum(len(x.encode("utf-8")) + 1 for x in string_table)
    string_table.append(s)
    string_map[s] = off
    return off


def _pack_value(dtype: int, value) -> bytes:
    if dtype == _DT_UINT8:  return struct.pack("B", value)
    if dtype == _DT_SINT8:  return struct.pack("b", value)
    if dtype == _DT_UINT16: return struct.pack(">H", value)
    if dtype == _DT_SINT16: return struct.pack(">h", value)
    if dtype == _DT_UINT32: return struct.pack(">I", value)
    if dtype == _DT_SINT32: return struct.pack(">i", value)
    if dtype == _DT_UINT64: return struct.pack(">Q", value)
    if dtype == _DT_SINT64: return struct.pack(">q", value)
    if dtype == _DT_FLOAT:  return struct.pack(">f", value)
    if dtype == _DT_DOUBLE: return struct.pack(">d", value)
    raise ValueError(f"Cannot pack dtype {dtype}")


class UtfBuilder:
    """Builds an @UTF table binary blob."""

    def __init__(self, table_name: str):
        self.table_name  = table_name
        self._cols: list[tuple] = []   # (name, storage, dtype)
        self._rows: list[dict]  = []

    def add_column(self, name: str, storage: int, dtype: int,
                   const_value=None):
        self._cols.append((name, storage, dtype, const_value))

    def add_row(self, **kw):
        self._rows.append(kw)

    def build(self) -> bytes:
        # collect strings
        string_table: list[str] = []
        string_map:   dict      = {}

        def intern(s: str) -> int:
            return _encode_string(s, string_table, string_map)

        intern("<NULL>")          # always first
        intern(self.table_name)

        # Column names
        col_name_offs = [intern(c[0]) for c in self._cols]

        # Per-row string values need to be collected first
        # (we'll inline them into rows later)
        for row in self._rows:
            for (col_name, storage, dtype, _cv) in self._cols:
                if storage == _ST_PERROW and dtype == _DT_STRING:
                    v = row.get(col_name, "")
                    intern(v if v is not None else "<NULL>")

        # Constant string values
        for (col_name, storage, dtype, cv) in self._cols:
            if storage == _ST_CONSTANT and dtype == _DT_STRING:
                intern(cv if cv is not None else "<NULL>")

        # Build string blob
        str_blob = b""
        for s in string_table:
            str_blob += s.encode("utf-8") + b"\x00"

        # build column definitions + constant values
        col_defs_blob = b""
        for i, (col_name, storage, dtype, cv) in enumerate(self._cols):
            flags = (storage << 4) | dtype
            col_defs_blob += struct.pack("B", flags)
            col_defs_blob += struct.pack(">I", col_name_offs[i])
            if storage == _ST_CONSTANT:
                if dtype == _DT_STRING:
                    col_defs_blob += struct.pack(">I", string_map.get(cv, 0))
                elif dtype == _DT_VLDATA:
                    # constants of vldata type unsupported here
                    col_defs_blob += struct.pack(">II", 0, 0)
                else:
                    col_defs_blob += _pack_value(dtype, cv)

        # build row data
        # Determine row size
        row_size = 0
        for (col_name, storage, dtype, _cv) in self._cols:
            if storage != _ST_PERROW:
                continue
            if dtype in (_DT_UINT8, _DT_SINT8):
                row_size += 1
            elif dtype in (_DT_UINT16, _DT_SINT16):
                row_size += 2
            elif dtype in (_DT_UINT32, _DT_SINT32, _DT_FLOAT, _DT_STRING):
                row_size += 4
            elif dtype in (_DT_UINT64, _DT_SINT64, _DT_DOUBLE):
                row_size += 8
            elif dtype == _DT_VLDATA:
                row_size += 8

        vldata_blobs: list[bytes] = []

        rows_blob = b""
        for row in self._rows:
            for (col_name, storage, dtype, _cv) in self._cols:
                if storage != _ST_PERROW:
                    continue
                v = row.get(col_name)
                if dtype == _DT_STRING:
                    rows_blob += struct.pack(
                        ">I", string_map.get(v, 0) if v is not None else 0)
                elif dtype == _DT_VLDATA:
                    if v is None:
                        rows_blob += struct.pack(">II", 0, 0)
                    else:
                        blob_off = sum(len(b) for b in vldata_blobs)
                        rows_blob += struct.pack(">II", blob_off, len(v))
                        vldata_blobs.append(v)
                else:
                    rows_blob += _pack_value(dtype, v if v is not None else 0)

        vl_blob = b"".join(vldata_blobs)

        # assemble body
        # Layout:
        #   [col_defs_blob][rows_blob][str_blob][vl_blob]
        # Offsets are relative to start of body (after magic+size)
        num_cols = len(self._cols)
        num_rows = len(self._rows)

        # The header is 24 bytes (rows_off, strings_off, data_off,
        # table_name_off, num_cols, row_size, num_rows)
        header_size  = 24
        col_def_size = len(col_defs_blob)

        rows_offset    = header_size + col_def_size
        strings_offset = rows_offset + row_size * max(num_rows, 1)
        data_offset    = strings_offset + len(str_blob)

        body  = struct.pack(">IIII", rows_offset, strings_offset,
                            data_offset, string_map.get(self.table_name, 0))
        body += struct.pack(">HHI", num_cols, row_size, num_rows)
        body += col_defs_blob
        body += rows_blob
        body += str_blob
        body += vl_blob

        # Pad to 8-byte boundary
        if len(body) % 8:
            body += b"\x00" * (8 - len(body) % 8)

        return _UTF_MAGIC + struct.pack(">I", len(body)) + body


# CPK builder

_ALIGN = 2048   # standard CPK alignment


def _align_up(value: int, alignment: int = _ALIGN) -> int:
    return math.ceil(value / alignment) * alignment


def build_cpk(entries: list[tuple[str, str, bytes]],
              align: int = _ALIGN) -> bytes:
    """
    Build a CPK archive from *entries*.

    *entries* is a list of (dir_name, file_name, data) tuples.
    All files are stored UNCOMPRESSED (FileSize == ExtractSize).

    Returns the complete CPK as a bytes object.
    """
    # layout file offsets
    # ContentOffset will be after CPK header section + TOC section (aligned)
    # We'll compute these iteratively.

    # Estimate TOC size (we'll need it to set ContentOffset)
    # Build the TOC @UTF first (with placeholder offsets, then patch)

    num_entries = len(entries)

    # Step 1: compute file data sizes / offsets (relative to ContentOffset)
    file_offsets: list[int] = []
    current = 0
    for _d, _f, data in entries:
        file_offsets.append(current)
        current = _align_up(current + len(data), align)

    total_content_size = current

    def make_toc(stored_file_offsets: list[int]) -> bytes:
        toc = UtfBuilder("CpkTocInfo")
        toc.add_column("DirName",     _ST_PERROW, _DT_STRING)
        toc.add_column("FileName",    _ST_PERROW, _DT_STRING)
        toc.add_column("FileSize",    _ST_PERROW, _DT_UINT32)
        toc.add_column("ExtractSize", _ST_PERROW, _DT_UINT32)
        toc.add_column("FileOffset",  _ST_PERROW, _DT_UINT64)
        toc.add_column("ID",          _ST_PERROW, _DT_UINT16)
        toc.add_column("UserString",  _ST_CONSTANT, _DT_STRING, "<NULL>")

        for i, (dir_name, file_name, data) in enumerate(entries):
            toc.add_row(
                DirName    = dir_name,
                FileName   = file_name,
                FileSize   = len(data),
                ExtractSize= len(data),
                FileOffset = stored_file_offsets[i],
                ID         = i,
            )
        return _make_section(b"TOC ", toc.build())

    # Step 2: build a provisional TOC so ContentOffset can be computed.
    toc_section = make_toc(file_offsets)
    toc_size = len(toc_section)

    # Step 3: compute section offsets
    # CPK header section is at offset 0; it occupies 0x800 bytes (2048)
    cpk_header_section_size = _ALIGN   # 2048 reserved for CPK header

    toc_offset     = cpk_header_section_size                 # = 2048
    content_offset = _align_up(toc_offset + toc_size, align) # aligned
    offset_base = _toc_add_offset(content_offset, toc_offset)
    toc_section = make_toc(
        [content_offset + rel - offset_base for rel in file_offsets])
    toc_size = len(toc_section)

    # Step 4: build CPK header @UTF
    cpk_hdr = UtfBuilder("CpkHeader")
    cpk_hdr.add_column("UpdateDateTime",     _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("FileSize",           _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("ContentOffset",      _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("ContentSize",        _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("TocOffset",          _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("TocSize",            _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("TocCrc",             _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("HtocOffset",         _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("HtocSize",           _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("EtocOffset",         _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("EtocSize",           _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("ItocOffset",         _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("ItocSize",           _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("ItocCrc",            _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("GtocOffset",         _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("GtocSize",           _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("GtocCrc",            _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("HgtocOffset",        _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("HgtocSize",          _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("EnabledPackedSize",  _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("EnabledDataSize",    _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("TotalDataSize",      _ST_PERROW,   _DT_UINT64)
    cpk_hdr.add_column("Tocs",              _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("Files",             _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("Groups",            _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("Attrs",             _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("TotalFiles",        _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("Directories",       _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("Updates",           _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("Version",           _ST_CONSTANT, _DT_UINT16, 7)
    cpk_hdr.add_column("Revision",          _ST_CONSTANT, _DT_UINT16, 0)
    cpk_hdr.add_column("Align",             _ST_PERROW,   _DT_UINT16)
    cpk_hdr.add_column("Sorted",            _ST_PERROW,   _DT_UINT16)
    cpk_hdr.add_column("EnableFileName",    _ST_PERROW,   _DT_UINT16)
    cpk_hdr.add_column("EID",              _ST_PERROW,   _DT_UINT16)
    cpk_hdr.add_column("CpkMode",          _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("Tvers",            _ST_PERROW,   _DT_STRING)
    cpk_hdr.add_column("Comment",          _ST_PERROW,   _DT_STRING)
    cpk_hdr.add_column("Codec",            _ST_PERROW,   _DT_UINT32)
    cpk_hdr.add_column("DpkItoc",          _ST_PERROW,   _DT_UINT32)

    total_file_size = content_offset + total_content_size
    total_data_size = sum(len(d) for _, _, d in entries)

    cpk_hdr.add_row(
        UpdateDateTime   = 0,
        FileSize         = total_file_size,
        ContentOffset    = content_offset,
        ContentSize      = total_content_size,
        TocOffset        = toc_offset,
        TocSize          = toc_size,
        TocCrc           = 0,
        HtocOffset       = 0,
        HtocSize         = 0,
        EtocOffset       = 0,
        EtocSize         = 0,
        ItocOffset       = 0,
        ItocSize         = 0,
        ItocCrc          = 0,
        GtocOffset       = 0,
        GtocSize         = 0,
        GtocCrc          = 0,
        HgtocOffset      = 0,
        HgtocSize        = 0,
        EnabledPackedSize= total_data_size,
        EnabledDataSize  = total_data_size,
        TotalDataSize    = total_data_size,
        Tocs             = 1,
        Files            = num_entries,
        Groups           = 0,
        Attrs            = 0,
        TotalFiles       = num_entries,
        Directories      = len({d for d, _, _ in entries}),
        Updates          = 0,
        Align            = align,
        Sorted           = 1,
        EnableFileName   = 1,
        EID              = 0,
        CpkMode          = 1,
        Tvers            = "ArrowForge1.0",
        Comment          = "<NULL>",
        Codec            = 0,
        DpkItoc          = 0,
    )

    hdr_utf_bytes    = cpk_hdr.build()
    hdr_section_body = _make_section(b"CPK ", hdr_utf_bytes)

    # Pad header section to cpk_header_section_size
    if len(hdr_section_body) < cpk_header_section_size:
        hdr_section_body = hdr_section_body + b"\x00" * (
            cpk_header_section_size - len(hdr_section_body))

    # Step 5: assemble the output
    output = bytearray()
    output += hdr_section_body                          # CPK header (2048 b)
    output += toc_section                               # TOC
    # Pad to content_offset
    if len(output) < content_offset:
        output += b"\x00" * (content_offset - len(output))

    # Write file data
    for i, (_d, _f, data) in enumerate(entries):
        assert len(output) == content_offset + file_offsets[i]
        output += data
        # Align
        padded = _align_up(len(data), align)
        if padded > len(data):
            output += b"\x00" * (padded - len(data))

    return bytes(output)


def _make_section(magic: bytes, utf_bytes: bytes) -> bytes:
    """Wrap an @UTF blob in a CPK section header."""
    assert len(magic) == 4
    data_size = len(utf_bytes)
    # flags = 0xFF000000 (observed in CPK files)
    header = magic + struct.pack("<I", 0xFF) + struct.pack("<Q", data_size)
    return header + utf_bytes


# Convenience: collect files from disk for repacking

def collect_files_from_dir(root_dir: str) -> list[tuple[str, str, bytes]]:
    """
    Walk *root_dir* and collect all files.

    Returns list of (dir_name, file_name, data) where dir_name uses
    forward-slash separators (the CPK convention).
    """
    entries = []
    root_dir = os.path.abspath(root_dir)
    for dirpath, _dirs, filenames in os.walk(root_dir):
        for fname in sorted(filenames):
            fpath   = os.path.join(dirpath, fname)
            rel_dir = os.path.relpath(dirpath, root_dir).replace(os.sep, "/")
            if rel_dir == ".":
                rel_dir = ""
            with open(fpath, "rb") as f:
                data = f.read()
            entries.append((rel_dir, fname, data))
    return entries


def replace_file_in_entries(existing: list[CpkEntry],
                             cpk_path: str,
                             target_cpk_dir: str,
                             target_file_name: str,
                             new_file_path: str
                             ) -> list[tuple[str, str, bytes]]:
    """
    Build an entry list for repacking where one specific file is replaced
    by the file at *new_file_path* on disk.
    """
    reader = CpkReader(cpk_path)
    result: list[tuple[str, str, bytes]] = []

    with open(new_file_path, "rb") as f:
        new_data = f.read()

    for entry in existing:
        if (entry.dir_name == target_cpk_dir and
                entry.file_name == target_file_name):
            result.append((entry.dir_name, entry.file_name, new_data))
        else:
            try:
                data = reader.read_entry_data(entry, decompress=True)
            except Exception:
                data = reader.read_entry_data(entry, decompress=False)
            result.append((entry.dir_name, entry.file_name, data))

    return result


def replace_dir_in_entries(existing: list[CpkEntry],
                            cpk_path: str,
                            new_dir_path: str,
                            target_cpk_dir: str
                            ) -> list[tuple[str, str, bytes]]:
    """
    Build an entry list for repacking where files under *target_cpk_dir* are
    replaced by files from *new_dir_path* on disk.

    Files in *existing* that are NOT in *target_cpk_dir* are kept as-is
    (read back from *cpk_path*).  Files in *target_cpk_dir* that exist on
    disk replace the original; files that do NOT exist on disk are dropped.
    New files in *new_dir_path* that have no counterpart in the CPK are added.
    """
    reader = CpkReader(cpk_path)
    result: list[tuple[str, str, bytes]] = []

    # Map existing entries NOT in target dir
    for entry in existing:
        if entry.dir_name == target_cpk_dir:
            continue
        data = reader.read_entry_data(entry, decompress=False)
        # If decompression produced the same bytes (no compression), store as-is.
        # We always store uncompressed in rebuilt CPKs, so decompress.
        try:
            data = reader.read_entry_data(entry, decompress=True)
        except Exception:
            pass
        result.append((entry.dir_name, entry.file_name, data))

    # Collect replacement files from disk
    new_dir_path = os.path.abspath(new_dir_path)
    for fname in sorted(os.listdir(new_dir_path)):
        fpath = os.path.join(new_dir_path, fname)
        if os.path.isfile(fpath):
            with open(fpath, "rb") as f:
                data = f.read()
            result.append((target_cpk_dir, fname, data))

    return result
