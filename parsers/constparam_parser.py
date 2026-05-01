"""parsers/constparam_parser.py  –  Parser for *_constParam.xfbin files.

Binary layout:
  [NUCC header + chunk table]   variable, preserved as-is
  [size_a]                       4 bytes BE  =  xml_size + 4
  [00 00 00 01]                  4 bytes     (version)
  [00 79 00 00]                  4 bytes     (type hash)
  [size_b]                       4 bytes BE  =  xml_size
  [XML data]                     xml_size bytes  (UTF-8, CRLF line endings)
  [FOOTER]                       20 bytes (fixed)
"""

import re
import struct

_FOOTER  = bytes.fromhex('0000000800000002007918000000000400000000')
_VERSION = b'\x00\x00\x00\x01'
_HASH    = b'\x00\x79\x00\x00'


def parse_constparam_xfbin(filepath):
    """Parse a *_constParam.xfbin file.

    Returns (raw_bytearray, params) where params is a list of dicts:
      {'name': str, 'value': str}
    """
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    xml_start = data.find(b'<?xml')
    if xml_start < 0:
        raise ValueError("No XML found in file")

    xml_end = data.find(b'</_root>')
    if xml_end < 0:
        raise ValueError("No </_root> tag found")
    xml_end += len(b'</_root>')

    xml_text = bytes(data[xml_start:xml_end]).decode('utf-8', errors='replace')
    params = _parse_xml(xml_text)
    return data, params


def _parse_xml(xml_text):
    """Extract list of {'name', 'value'} dicts from XML text."""
    return [
        {'name': m.group(1), 'value': m.group(2)}
        for m in re.finditer(r'<data\s+name="([^"]+)"\s+value="([^"]*)"', xml_text)
    ]


def save_constparam_xfbin(filepath, original_data, params):
    """Rebuild *_constParam.xfbin with updated params and write to filepath."""
    xml_start = original_data.find(b'<?xml')
    if xml_start < 0:
        raise ValueError("Cannot locate XML start in original data")

    xml_text = _build_xml(params)
    xml_bytes = xml_text.encode('utf-8')
    xml_size = len(xml_bytes)

    out = bytearray(original_data[:xml_start - 16])
    out += struct.pack('>I', xml_size + 4)  # size_a
    out += _VERSION
    out += _HASH
    out += struct.pack('>I', xml_size)      # size_b
    out += xml_bytes
    out += _FOOTER

    with open(filepath, 'wb') as f:
        f.write(bytes(out))


def _build_xml(params):
    """Reconstruct XML string from params list (preserves original format)."""
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<_root>']
    for p in params:
        parts.append(f'\r\n\t<data name="{p["name"]}" value="{p["value"]}"/>')
    parts.append('\r\n</_root>')
    return ''.join(parts)
