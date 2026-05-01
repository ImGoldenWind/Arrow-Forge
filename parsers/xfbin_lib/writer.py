from .binary_reader import BinaryReader, Endian
from .br_xfbin import BrXfbin
from .xfbin_types import Xfbin


def write_xfbin(xfbin: Xfbin) -> bytearray:
    """Serialise an Xfbin object to a bytearray."""
    br = BinaryReader(endianness=Endian.BIG)
    br.write_struct(BrXfbin(), xfbin)
    return br.buffer()


def write_xfbin_to_path(xfbin: Xfbin, path: str) -> None:
    """Serialise an Xfbin object and write it to `path`."""
    data = write_xfbin(xfbin)
    with open(path, 'wb') as fh:
        fh.write(data)
