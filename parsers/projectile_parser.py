"""parsers/projectile_parser.py  –  Parser for 0xxx00_x.xfbin projectile/skill files.

Binary layout of _x.xfbin:
  [NUCC header]        28 bytes
  [Chunk table]        variable (chunk_table_size from header)
  [Aligned to 4 bytes]
  [PRE_XML1_FIXED]     24 bytes  (static NUCC page/chunk headers)
  For each skill XML chunk:
    [size_a]           4 bytes BE  =  xml_size + 6
    [00 00 00 01]      4 bytes     (version)
    [00 79 6c 00]      4 bytes     (type hash)
    [size_b]           4 bytes BE  =  xml_size + 2
    [XML data]         xml_size bytes  (Shift_JIS)
    [\\r\\n]            2 bytes
    -- if not the last chunk --
    [INTER_FOOTER]     20 bytes  (fixed)
    [INTER_PREHEAD]    12 bytes  (fixed)
  [INTER_FOOTER]       20 bytes  (terminal footer after last XML)
"""

import struct
import re

# Fixed binary patterns

# 20-byte footer placed after every XML chunk's \\r\\n
_INTER_FOOTER = (
    b'\x00\x00\x00\x08'
    b'\x00\x00\x00\x02'
    b'\x00\x79\x50\x77'
    b'\x00\x00\x00\x04'
    b'\x00\x00\x00\x00'
)

# 12-byte header prefix placed before every non-first XML chunk's size fields
_INTER_PREHEAD = (
    b'\x00\x00\x00\x00'
    b'\x00\x00\x00\x00'
    b'\x00\x79\x6c\x00'
)

# Helpers

def _xml_attr(xml_text, attr, default=''):
    """Extract the first value of attribute from xml_text."""
    m = re.search(rf'\b{re.escape(attr)}="([^"]*)"', xml_text)
    return m.group(1) if m else default


def _xml_set_attr(xml_text, attr, new_value, nth=1):
    """Replace the nth occurrence of attr="..." in xml_text."""
    counter = [0]
    def _repl(m):
        counter[0] += 1
        if counter[0] == nth:
            return m.group(1) + str(new_value) + m.group(2)
        return m.group(0)
    return re.sub(rf'(\b{re.escape(attr)}=")[^"]*(")', _repl, xml_text)


# Public API

def parse_projectile_xfbin(filepath):
    """Parse a _x.xfbin file and return (raw_bytearray, chunks).

    Each chunk dict:
      skill_id   – str, value of the root <Skill id="..."> attribute
      xml_start  – int, byte offset of '<?xml' in original file
      xml_end    – int, byte offset after '</Skill>'
      xml_text   – str, XML text decoded from Shift_JIS (\\r\\n line endings)
    """
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    chunks = []
    for m in re.finditer(rb'<\?xml', data):
        xml_start = m.start()
        skill_end = data.find(b'</Skill>', xml_start)
        if skill_end < 0:
            continue
        xml_end = skill_end + 8  # position after '</Skill>'

        xml_bytes = bytes(data[xml_start:xml_end])
        xml_text  = xml_bytes.decode('shift_jis', errors='replace')

        # Extract skill id from root element
        id_m = re.search(r'<Skill\s[^>]*\bid="([^"]*)"', xml_text)
        skill_id = id_m.group(1) if id_m else f'skill_{len(chunks)}'

        chunks.append({
            'skill_id':  skill_id,
            'xml_start': xml_start,
            'xml_end':   xml_end,
            'xml_text':  xml_text,
        })

    return data, chunks


def save_projectile_xfbin(filepath, original_data, chunks):
    """Rebuild _x.xfbin with (possibly modified) XML chunks and write to filepath.

    original_data is used only to copy the immutable header/chunk-table section
    (everything before the first XML's size_a field).
    """
    if not chunks:
        with open(filepath, 'wb') as f:
            f.write(bytes(original_data))
        return

    first_xml_start = chunks[0]['xml_start']

    # Preserve everything before size_a of the first XML chunk
    # (NUCC header, chunk table, PRE_XML1_FIXED block)
    out = bytearray(original_data[:first_xml_start - 16])

    for i, chunk in enumerate(chunks):
        # Ensure consistent \r\n line endings for the file
        xml_text = chunk['xml_text']
        xml_text = xml_text.replace('\r\n', '\n').replace('\r', '\n')
        xml_text = xml_text.replace('\n', '\r\n')

        # Strip trailing whitespace / stray newlines after </Skill>
        skill_close = xml_text.rfind('</Skill>')
        if skill_close >= 0:
            xml_text = xml_text[:skill_close + 8]

        xml_bytes = xml_text.encode('shift_jis', errors='replace')
        xml_size  = len(xml_bytes)

        if i > 0:
            out += _INTER_FOOTER   # 20 bytes
            out += _INTER_PREHEAD  # 12 bytes

        # size_a | version | hash | size_b
        out += struct.pack('>I', xml_size + 6)   # size_a
        out += b'\x00\x00\x00\x01'               # version
        out += b'\x00\x79\x6c\x00'               # type hash
        out += struct.pack('>I', xml_size + 2)   # size_b

        out += xml_bytes
        out += b'\r\n'

    # Terminal footer
    out += _INTER_FOOTER

    with open(filepath, 'wb') as f:
        f.write(bytes(out))
