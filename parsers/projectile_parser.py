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

    chunks = _read_projectile_bytes(data)
    if not bytes(data).startswith(b'NUCC'):
        raise ValueError('Not an XFBIN file')
    return data, chunks


def _read_projectile_bytes(data):
    """Parse original bytes without touching any source file."""
    chunks = []
    for match in re.finditer(rb'<\?xml', data):
        start = match.start()
        end = data.find(b'</Skill>', start)
        if end < 0:
            continue
        text = bytes(data[start:end + 8]).decode('shift_jis')
        from core.projectile_tools import parse_skill
        root = parse_skill(text)
        chunks.append({'skill_id': root.get('id', ''), 'xml_start': start,
                       'xml_end': end + 8, 'xml_text': text})
    return chunks


def save_projectile_xfbin(filepath, original_data, chunks):
    """Preserve untouched bytes; rebuild the NUCC table for structural edits.

    Validate and encode everything before atomically replacing the destination.
    An unencodable description must never silently turn into question marks.
    """
    import copy
    import os
    import tempfile
    from pathlib import Path
    from core.projectile_tools import parse_skill

    original = _read_projectile_bytes(original_data)
    if not original or not chunks:
        raise ValueError('No projectile Skill XML to save')
    encoded = []
    from collections import Counter
    original_ids = Counter(c['skill_id'] for c in original)
    output_ids = Counter(c['skill_id'] for c in chunks)
    if any(count > max(1, original_ids[ident]) for ident, count in output_ids.items()):
        raise ValueError('Projectile IDs must be unique; an existing duplicate may be preserved')
    for chunk in chunks:
        root = parse_skill(chunk['xml_text'])
        if root.get('id', '') != chunk['skill_id']:
            raise ValueError('Projectile ID does not match XML')
        if not re.fullmatch(r'[A-Za-z0-9_]{1,31}', chunk['skill_id']):
            raise ValueError('Projectile ID must contain 1 to 31 ASCII letters, digits or underscores')
        encoded.append(chunk['xml_text'].encode('shift_jis'))

    same_layout = (len(chunks) == len(original) and all(
        c.get('xml_start') == old['xml_start'] and c['skill_id'] == old['skill_id']
        for c, old in zip(chunks, original)))
    if same_layout:
        # XML sits in a nuccChunkBinary: outer size at -16, inner size at -4.
        # Retain each original header/version/map index, page and tail verbatim.
        out = bytearray()
        cursor = 0
        for chunk, old, xml in zip(chunks, original, encoded):
            start, end = old['xml_start'], old['xml_end']
            if chunk['xml_text'] == old['xml_text']:
                continue
            header = start - 16
            outer = struct.unpack_from('>I', original_data, header)[0]
            inner = struct.unpack_from('>I', original_data, start - 4)[0]
            if outer != inner + 4 or inner < end - start:
                raise ValueError('Unsupported projectile binary layout')
            delta = len(xml) - (end - start)
            out.extend(original_data[cursor:header])
            patched_header = bytearray(original_data[header:start])
            struct.pack_into('>I', patched_header, 0, outer + delta)
            struct.pack_into('>I', patched_header, 12, inner + delta)
            out.extend(patched_header)
            out.extend(xml)
            cursor = end
        out.extend(original_data[cursor:])
    else:
        from parsers.xfbin_lib.reader import read_xfbin
        from parsers.xfbin_lib.writer import write_xfbin
        from parsers.xfbin_lib.nucc import NuccChunkBinary
        # Rebuild map names and page indices together; never reuse hardcoded
        # chunk indices after adding/deleting/reordering a projectile.
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.xfbin'
            source.write_bytes(original_data)
            xfbin = read_xfbin(source)
        templates = []
        for page in xfbin.pages:
            binaries = [c for c in page.chunks if isinstance(c, NuccChunkBinary)
                        and b'<Skill' in c.binary_data]
            if binaries:
                if len(binaries) != 1:
                    raise ValueError('Unsupported multiple Skill payloads per page')
                templates.append((page, binaries[0]))
        if len(templates) != len(original):
            raise ValueError('Projectile page count mismatch')
        pages = []
        for chunk, xml in zip(chunks, encoded):
            index = next((i for i, old in enumerate(original)
                          if old['xml_start'] == chunk.get('xml_start')), 0)
            page, binary = copy.deepcopy(templates[index])
            binary.name = chunk['skill_id']
            # Preserve the source payload's suffix (normally CRLF).
            old = original[index]
            suffix = binary.binary_data[old['xml_end'] - old['xml_start']:]
            binary.binary_data = xml + suffix
            pages.append(page)
        template_ids = {id(page) for page, _ in templates}
        first = min(i for i, page in enumerate(xfbin.pages) if id(page) in template_ids)
        retained = [page for page in xfbin.pages if id(page) not in template_ids]
        retained[first:first] = pages
        xfbin.pages = retained
        out = write_xfbin(xfbin)

    destination = Path(filepath)
    fd, temp_path = tempfile.mkstemp(prefix='.projectile-', suffix='.tmp', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(out)
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
