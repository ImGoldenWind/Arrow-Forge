"""Read and update the XML payload in a ConstParam XFBIN."""

import re
import struct
from xml.parsers import expat
from xml.sax.saxutils import escape

from .xfbin_lib.writer import write_bytes_atomically


_DATA_TAG = re.compile(rb'''<data\b(?:[^<>"']|"[^"]*"|'[^']*')*>''')
_ATTRIBUTE = re.compile(rb'''\s+([^\s=/]+)\s*=\s*(?:"([^"]*)"|'([^']*)')''')
_XML_ESCAPES = {'"': '&quot;', "'": '&apos;', '\t': '&#9;', '\n': '&#10;', '\r': '&#13;'}


class _Parameter(dict):
    def __init__(self, name, value, source_index):
        super().__init__(name=name, value=value)
        self.source_index = source_index


def _xml_section(data):
    start = data.find(b'<?xml')
    if start < 16:
        raise ValueError('Cannot locate the ConstParam XML payload')
    size = struct.unpack_from('>I', data, start - 4)[0]
    end = start + size
    if end > len(data) or struct.unpack_from('>I', data, start - 16)[0] != size + 4:
        raise ValueError('Invalid ConstParam XML payload size')
    return start, end


def _read_parameters(xml):
    parser = expat.ParserCreate()
    params = []
    tags = []
    elements = []

    def start_element(tag, attrs):
        index = None
        if len(elements) == 1 and tag == 'data' and 'name' in attrs and 'value' in attrs:
            match = _DATA_TAG.match(xml, parser.CurrentByteIndex)
            if match is None:
                raise ValueError('Cannot locate the ConstParam data tag')
            index = len(params)
            params.append(_Parameter(attrs['name'], attrs['value'], index))
            start, opening_end = match.span()
            end = opening_end if xml[opening_end - 2:opening_end] == b'/>' else None
            tags.append((start, opening_end, end))
        elements.append(index)

    def end_element(_tag):
        index = elements.pop()
        if index is not None:
            start, opening_end, end = tags[index]
            if end is None:
                end = xml.index(b'>', parser.CurrentByteIndex) + 1
                tags[index] = (start, opening_end, end)

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.Parse(xml, True)
    return params, tags


def parse_constparam_xfbin(filepath):
    """Return the original bytes and a list of editable name/value mappings."""
    with open(filepath, 'rb') as stream:
        data = bytearray(stream.read())
    start, end = _xml_section(data)
    params, _ = _read_parameters(data[start:end])
    return data, params


def _encode_value(text):
    return escape(text, _XML_ESCAPES).encode('utf-8')


def _edit_tag(tag, baseline, current):
    updated = bytearray(tag)
    for match in reversed(list(_ATTRIBUTE.finditer(tag))):
        key = match[1].decode('utf-8')
        if key in baseline and current[key] != baseline[key]:
            start, end = match.span(2 if match[2] is not None else 3)
            updated[start:end] = _encode_value(current[key])
    return updated


def _new_tag(param):
    return b'<data name="%s" value="%s"/>' % (_encode_value(param['name']), _encode_value(param['value']))


def _update_xml(xml, params):
    baseline, tags = _read_parameters(xml)
    if params == baseline:
        return xml
    newline = b'\r\n' if b'\r\n' in xml else b'\n'
    separator = newline + b'\t'
    source_indices = [getattr(param, 'source_index', None) for param in params]
    if len(params) == len(baseline) and all(index is None for index in source_indices):
        source_indices = list(range(len(baseline)))
    slots = iter(sorted({index for index in source_indices if index is not None}))
    seen = set()
    replacements = {}
    insertions = {}
    anchor = None
    for index, param in zip(source_indices, params):
        if index is None or index in seen:
            insertions.setdefault(anchor, []).append(_new_tag(param))
        else:
            seen.add(index)
            anchor = next(slots)
            replacements[anchor] = (index, param)

    result = bytearray()
    cursor = 0
    for index, (start, _, end) in enumerate(tags):
        result.extend(xml[cursor:start])
        if index == 0 and None in insertions:
            result.extend(separator.join(insertions[None]) + separator)
        if index in replacements:
            source_index, param = replacements[index]
            tag_start, opening_end, tag_end = tags[source_index]
            result.extend(_edit_tag(xml[tag_start:opening_end], baseline[source_index], param))
            result.extend(xml[opening_end:tag_end])
        for tag in insertions.get(index, ()):
            result.extend(separator + tag)
        cursor = end
    if not tags and None in insertions:
        cursor = xml.rfind(b'</_root>')
        if cursor < 0:
            raise ValueError('Cannot locate the end of the ConstParam XML root')
        result.extend(xml[:cursor])
        result.extend(separator + separator.join(insertions[None]) + newline)
    result.extend(xml[cursor:])
    # Validate new attribute values before replacing an existing file.
    _read_parameters(result)
    return result


def save_constparam_xfbin(filepath, original_data, params):
    """Replace only the XML payload and its two length fields."""
    start, end = _xml_section(original_data)
    xml = _update_xml(original_data[start:end], params)
    out = bytearray(original_data[:start])
    struct.pack_into('>I', out, start - 16, len(xml) + 4)
    struct.pack_into('>I', out, start - 4, len(xml))
    out.extend(xml)
    out.extend(original_data[end:])
    write_bytes_atomically(filepath, out)
