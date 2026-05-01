import struct
from contextlib import contextmanager
from enum import Flag, IntEnum
from typing import Tuple, Union


class Endian(Flag):
    LITTLE = False
    BIG = True


class Whence(IntEnum):
    BEGIN = 0
    CUR = 1
    END = 2


_FMT_SIZE = {
    's': 1,
    'b': 1, 'B': 1,
    'h': 2, 'H': 2, 'e': 2,
    'i': 4, 'I': 4, 'f': 4,
    'q': 8, 'Q': 8,
}


class BrStruct:
    """Base class for binary-serializable structs."""
    def __init__(self):
        pass

    def __br_read__(self, br: 'BinaryReader', *args):
        pass

    def __br_write__(self, br: 'BinaryReader', *args):
        pass


class BinaryReader:
    """Buffer-backed binary reader/writer with explicit endianness."""

    def __init__(self, buffer=bytearray(), endianness: Endian = Endian.LITTLE, encoding: str = 'utf-8'):
        self._buf = bytearray(buffer)
        self._endian = endianness
        self._pos = 0
        ''.encode(encoding)          # validate encoding
        self._encoding = encoding

    # Context manager
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._buf.clear()

    # Buffer state
    def pos(self) -> int:
        return self._pos

    def size(self) -> int:
        return len(self._buf)

    def buffer(self) -> bytearray:
        return bytearray(self._buf)

    def eof(self) -> bool:
        return self._pos + 1 > self.size()

    def past_eof(self) -> bool:
        return self._pos > self.size()

    # Navigation
    def seek(self, offset: int, whence: Whence = Whence.BEGIN) -> None:
        if whence == Whence.BEGIN:
            new = offset
        elif whence == Whence.CUR:
            new = self._pos + offset
        elif whence == Whence.END:
            new = self.size() - offset
        else:
            raise ValueError(f'Invalid whence: {whence}')
        if new < 0 or new > self.size():
            raise IOError(f'Seek out of range: {new} (buffer size={self.size()})')
        self._pos = new

    @contextmanager
    def seek_to(self, offset: int, whence: Whence = Whence.BEGIN):
        prev = self._pos
        self.seek(offset, whence)
        yield self
        self._pos = prev

    def align_pos(self, size: int) -> int:
        """Advance position until aligned to `size`. Returns bytes skipped."""
        if self._pos % size:
            skip = size - (self._pos % size)
            self.seek(skip, Whence.CUR)
            return skip
        return 0

    def align(self, size: int) -> int:
        """Pad the buffer until its size is aligned to `size`. Returns bytes added."""
        if self.size() % size:
            pad = size - (self.size() % size)
            self.pad(pad)
            return pad
        return 0

    def extend(self, data) -> None:
        """Append bytes to the end of the buffer without moving position."""
        self._buf.extend(data)

    def pad(self, size: int) -> None:
        """Append `size` zero bytes; advance position only if it was at the end."""
        at_end = self._pos == self.size()
        self._buf.extend(bytes(size))
        if at_end:
            self._pos += size

    def trim(self, size: int) -> int:
        """Truncate buffer to `size` bytes. Returns bytes removed."""
        removed = max(0, self.size() - size)
        if removed > 0:
            self._buf = self._buf[:size]
            if self._pos > size:
                self._pos = self.size()
        return removed

    def set_endian(self, endianness: Endian) -> None:
        self._endian = endianness

    def set_encoding(self, encoding: str) -> None:
        ''.encode(encoding)
        self._encoding = encoding

    @staticmethod
    def is_iterable(x) -> bool:
        return hasattr(x, '__iter__') and not isinstance(x, (str, bytes))

    # Low-level read/write
    def _endian_char(self) -> str:
        return '>' if self._endian else '<'

    def _read(self, fmt: str, count: int):
        sz = _FMT_SIZE[fmt] * count
        if self._pos + sz > self.size():
            raise IOError(f'Read overrun: pos={self._pos} need={sz} bufsize={self.size()}')
        end = self._endian_char()
        result = struct.unpack_from(f'{end}{count}{fmt}', self._buf, self._pos)
        self._pos += sz
        return result

    def _write(self, fmt: str, value, is_iter: bool) -> None:
        end = self._endian_char()
        if is_iter or isinstance(value, bytes):
            count = len(value)
        else:
            count = 1
        sz = _FMT_SIZE[fmt] * count
        if self._pos + sz > self.size():
            self._buf.extend(bytes(self._pos + sz - self.size()))
        if is_iter:
            struct.pack_into(f'{end}{count}{fmt}', self._buf, self._pos, *value)
        else:
            struct.pack_into(f'{end}{count}{fmt}', self._buf, self._pos, value)
        self._pos += sz

    # Read primitives
    def read_bytes(self, size: int = 1) -> bytes:
        return self._read('s', size)[0]

    def read_str(self, size=None, encoding=None) -> str:
        enc = encoding or self._encoding
        if size is None:
            result = bytearray()
            while self._pos < self.size():
                b = self._buf[self._pos]
                self._pos += 1
                if b == 0:
                    break
                result.append(b)
            return result.decode(enc, errors='replace')
        return self.read_bytes(size).split(b'\x00', 1)[0].decode(enc, errors='replace')

    def read_uint64(self, count=None):
        r = self._read('Q', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_int64(self, count=None):
        r = self._read('q', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_uint32(self, count=None):
        r = self._read('I', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_int32(self, count=None):
        r = self._read('i', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_uint16(self, count=None):
        r = self._read('H', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_int16(self, count=None):
        r = self._read('h', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_uint8(self, count=None):
        r = self._read('B', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_int8(self, count=None):
        r = self._read('b', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_float(self, count=None):
        r = self._read('f', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_half_float(self, count=None):
        r = self._read('e', count if count is not None else 1)
        return r if count is not None else r[0]

    def read_struct(self, cls: type, count=None, *args) -> 'BrStruct':
        if not (cls and issubclass(cls, BrStruct)):
            raise TypeError(f'{cls} is not a subclass of BrStruct')
        if count is not None:
            result = []
            for _ in range(count):
                obj = cls()
                obj.__br_read__(self, *args)
                result.append(obj)
            return tuple(result)
        obj = cls()
        obj.__br_read__(self, *args)
        return obj

    # Write primitives
    def write_bytes(self, value: bytes) -> None:
        self._write('s', value, False)

    def write_str(self, s: str, null: bool = False, encoding=None) -> int:
        enc = encoding or self._encoding
        data = s.encode(enc) + (b'\x00' if null else b'')
        self.write_bytes(data)
        return len(data)

    def write_str_fixed(self, s: str, size: int, encoding=None) -> None:
        enc = encoding or self._encoding
        self.write_bytes(s.encode(enc)[:size].ljust(size, b'\x00'))

    def write_uint64(self, value) -> None:
        self._write('Q', value, self.is_iterable(value))

    def write_int64(self, value) -> None:
        self._write('q', value, self.is_iterable(value))

    def write_uint32(self, value) -> None:
        self._write('I', value, self.is_iterable(value))

    def write_int32(self, value) -> None:
        self._write('i', value, self.is_iterable(value))

    def write_uint16(self, value) -> None:
        self._write('H', value, self.is_iterable(value))

    def write_int16(self, value) -> None:
        self._write('h', value, self.is_iterable(value))

    def write_uint8(self, value) -> None:
        self._write('B', value, self.is_iterable(value))

    def write_int8(self, value) -> None:
        self._write('b', value, self.is_iterable(value))

    def write_float(self, value) -> None:
        self._write('f', value, self.is_iterable(value))

    def write_half_float(self, value) -> None:
        self._write('e', value, self.is_iterable(value))

    def write_struct(self, obj: 'BrStruct', *args) -> None:
        if not isinstance(obj, BrStruct):
            raise TypeError(f'{obj} is not an instance of BrStruct')
        obj.__br_write__(self, *args)
