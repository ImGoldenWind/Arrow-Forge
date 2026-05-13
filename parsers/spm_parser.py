"""parsers/spm_parser.py  –  SPM XFBIN (Special Move Parameters) parser."""

import struct
import copy
import xml.etree.ElementTree as ET


def _find_binary_chunk(raw):
    """Return (hdr_off, data_off, chunk_size) for the first nuccChunkBinary."""
    table_size = struct.unpack('>I', raw[16:20])[0]
    start = 28 + table_size
    if start % 4:
        start += 4 - (start % 4)

    off = start
    while off + 12 <= len(raw):
        size    = struct.unpack('>I', raw[off:off + 4])[0]
        map_idx = struct.unpack('>I', raw[off + 4:off + 8])[0]
        if size > 0 and map_idx == 1:
            return off, off + 12, size
        if size == 0:
            off += 12
        else:
            off += 12 + size
            if off % 4:
                off += 4 - (off % 4)
    raise ValueError("nuccChunkBinary not found in XFBIN")


def _extract_xml(payload):
    """Return (prefix_bytes, xml_text) from chunk payload."""
    BOM = b'\xef\xbb\xbf'
    if payload[:3] == BOM:
        return BOM, payload[3:].rstrip(b'\x00').decode('utf-8')
    idx = payload.find(b'<?xml')
    if idx >= 0:
        return bytes(payload[:idx]), payload[idx:].rstrip(b'\x00').decode('utf-8')
    raise ValueError("XML not found in binary chunk payload")


def _indent(elem, level=0):
    """Indent ET element tree in-place for pretty-printing."""
    pad  = '\n' + '  ' * level
    padc = '\n' + '  ' * (level + 1)
    if len(elem):
        if not (elem.text and elem.text.strip()):
            elem.text = padc
        for i, child in enumerate(elem):
            _indent(child, level + 1)
            child.tail = padc if i < len(elem) - 1 else pad


def _to_xml_str(root):
    """Serialize root to XML string (uses deep-copy to leave live tree intact)."""
    r = copy.deepcopy(root)
    _indent(r)
    body = ET.tostring(r, encoding='unicode')
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + '\n'


def parse_spm_xfbin(filepath):
    """Parse SPM XFBIN.  Returns (raw_bytearray, result_dict).

    result_dict keys:
        'root'     – ET.Element  (<_root>)
        'prefix'   – bytes before the XML in the chunk  (usually BOM)
        'hdr_off'  – file offset of the binary chunk 12-byte header
        'data_off' – file offset where chunk payload begins
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    hdr_off, data_off, chunk_size = _find_binary_chunk(raw)
    payload = bytes(raw[data_off:data_off + chunk_size])
    prefix, xml_text = _extract_xml(payload)
    root = ET.fromstring(xml_text)

    # nuccChunkBinary stores an inner BE uint32 data_size before the XML/BOM.
    # Keep supporting raw XML payloads, but update this field on save when present.
    has_inner_size = False
    if len(prefix) >= 4:
        declared_size = struct.unpack('>I', prefix[:4])[0]
        inner_end = 4 + declared_size
        has_inner_size = inner_end <= chunk_size and all(b == 0 for b in payload[inner_end:])

    return raw, {
        'root':     root,
        'prefix':   prefix,
        'hdr_off':  hdr_off,
        'data_off': data_off,
        'has_inner_size': has_inner_size,
    }


def save_spm_xfbin(filepath, raw, result):
    """Write modified SPM XFBIN back to filepath."""
    xml_str = _to_xml_str(result['root'])
    xml_bytes = xml_str.encode('utf-8')

    prefix = result['prefix']
    if result.get('has_inner_size') and len(prefix) >= 4:
        binary_data = prefix[4:] + xml_bytes
        new_data = struct.pack('>I', len(binary_data)) + binary_data
    else:
        new_data = prefix + xml_bytes

    hdr_off  = result['hdr_off']
    data_off = result['data_off']

    old_size = struct.unpack('>I', raw[hdr_off:hdr_off + 4])[0]
    old_end  = data_off + old_size
    if old_end % 4:
        old_end += 4 - (old_end % 4)

    payload = bytearray(new_data)
    if len(payload) % 4:
        payload += b'\x00' * (4 - len(payload) % 4)

    new_hdr = bytearray(raw[hdr_off:hdr_off + 12])
    struct.pack_into('>I', new_hdr, 0, len(new_data))

    buf = bytes(raw[:hdr_off]) + bytes(new_hdr) + bytes(payload) + bytes(raw[old_end:])
    with open(filepath, 'wb') as f:
        f.write(buf)


def get_moves(root):
    """Group XML children into move dicts, preserving SpecialMove order.

    Each dict:  {'actID', 'actKind', 'spm_elem', 'entry_elem', 'decorator_elems'}
    """
    moves  = []
    by_key = {}
    for elem in root:
        aid   = elem.get('actID',  '')
        akind = elem.get('actKind', '')
        key   = (aid, akind)
        tag   = elem.tag

        if tag == 'SpecialMove':
            m = {
                'actID':           aid,
                'actKind':         akind,
                'spm_elem':        elem,
                'entry_elem':      None,
                'decorator_elems': [],
            }
            by_key[key] = m
            moves.append(m)
        elif tag == 'EntrySPM' and key in by_key:
            by_key[key]['entry_elem'] = elem
        elif tag == 'Decorator' and key in by_key:
            by_key[key]['decorator_elems'].append(elem)

    return moves
