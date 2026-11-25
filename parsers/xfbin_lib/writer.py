import os
import tempfile

from .binary_reader import BinaryReader, Endian
from .br_xfbin import BrXfbin
from .xfbin_types import Xfbin


def write_xfbin(xfbin: Xfbin) -> bytearray:
    """Serialise an Xfbin object to a bytearray."""
    if hasattr(xfbin, 'source_layout'):
        return xfbin.source_layout.write(xfbin.pages)
    br = BinaryReader(endianness=Endian.BIG)
    br.write_struct(BrXfbin(), xfbin)
    return br.buffer()


def write_xfbin_to_path(xfbin: Xfbin, path: str) -> None:
    """Serialise an Xfbin object and write it to `path`."""
    data = write_xfbin(xfbin)
    with open(path, 'wb') as fh:
        fh.write(data)


def write_bytes_atomically(path, data) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix='.arrowforge-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
