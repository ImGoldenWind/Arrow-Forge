"""Parser/saver for ASBR CPU AI XFBIN files.

CPU files are XFBIN containers with one XML payload in a nuccChunkBinary.
The XML itself is the editable AI data:
  * *_cpu_cmn.xfbin defines condition/action tokens.
  * *_cpu_p_*.xfbin defines difficulty patterns and action tables.
"""

from __future__ import annotations

import copy
import os
import struct
import xml.etree.ElementTree as ET


XML_DECL = '<?xml version="1.0" encoding="utf-8"?>\n'
ARCADE_CPU_ENTRY_SIZE = 40
ARCADE_CPU_HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
ARCADE_CPU_LEVEL_COUNT = 9


def _scan_chunks(raw: bytes) -> list[dict]:
    chunk_table_size = struct.unpack(">I", raw[16:20])[0]
    offset = 28 + chunk_table_size
    chunks = []
    while offset + 12 <= len(raw):
        chunk_size = struct.unpack(">I", raw[offset:offset + 4])[0]
        map_idx = struct.unpack(">I", raw[offset + 4:offset + 8])[0]
        chunks.append({
            "hdr_offset": offset,
            "data_offset": offset + 12,
            "chunk_size": chunk_size,
            "map_idx": map_idx,
        })
        offset += 12 if chunk_size == 0 else 12 + chunk_size
        if offset >= len(raw):
            break
    return chunks


def _find_xml_chunk(raw: bytes) -> dict:
    for chunk in _scan_chunks(raw):
        if chunk["map_idx"] != 1 or chunk["chunk_size"] <= 4:
            continue
        data_off = chunk["data_offset"]
        payload_size = struct.unpack(">I", raw[data_off:data_off + 4])[0]
        payload = raw[data_off + 4:data_off + 4 + payload_size]
        if payload.startswith(b"\xef\xbb\xbf<?xml") or payload.startswith(b"<?xml"):
            result = dict(chunk)
            result["xml_size"] = payload_size
            return result
    raise ValueError("CPU XML chunk not found in XFBIN")


def _find_binary_chunk(raw: bytes | bytearray) -> tuple[int, int]:
    best_off = -1
    best_size = 0
    for chunk in _scan_chunks(raw):
        if chunk["map_idx"] == 1 and chunk["chunk_size"] >= INNER_SIZE_FIELD + ARCADE_CPU_HEADER_SIZE:
            if chunk["chunk_size"] > best_size:
                best_off = chunk["hdr_offset"]
                best_size = chunk["chunk_size"]
    if best_off < 0:
        raise ValueError("ArcadeCpuParam binary chunk not found in XFBIN")
    return best_off, best_size


def _read_cstr(data: bytes | bytearray, off: int) -> str:
    if off < 0 or off >= len(data):
        return ""
    try:
        end = data.index(b"\x00", off)
    except ValueError:
        end = len(data)
    return bytes(data[off:end]).decode("ascii", errors="replace")


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _indent(elem: ET.Element, level: int = 0):
    """Small ElementTree indent fallback that matches the original 2-space style."""
    pad = "\n" + level * "  "
    child_pad = "\n" + (level + 1) * "  "
    children = list(elem)
    if children:
        if not elem.text or not elem.text.strip():
            elem.text = child_pad
        for child in children:
            _indent(child, level + 1)
        if not children[-1].tail or not children[-1].tail.strip():
            children[-1].tail = pad
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = pad


def _parse_xml_bytes(xml_bytes: bytes) -> ET.ElementTree:
    text = xml_bytes.decode("utf-8-sig")
    return ET.ElementTree(ET.fromstring(text))


def _element_label(element: ET.Element, index: int) -> str:
    tag = _strip_namespace(element.tag)
    attrs = element.attrib
    if tag == "Pattern":
        return attrs.get("name") or "Pattern"
    if tag == "BaseParam":
        return "BaseParam"
    if tag == "Cond":
        uid = attrs.get("uid") or attrs.get("name") or "Cond"
        return uid
    if tag == "Action":
        uid = attrs.get("uid") or attrs.get("name") or "Action"
        return uid
    if tag == "Data":
        rid = attrs.get("rid", index)
        status = attrs.get("OpStatus", "")
        pos = attrs.get("Position", "")
        action = attrs.get("Act1", "")
        parts = [f"rid {rid}"]
        if status:
            parts.append(status)
        if pos:
            parts.append(pos)
        if action and action != "0":
            parts.append(action)
        return " / ".join(parts)
    return tag


def _element_subtitle(element: ET.Element) -> str:
    tag = _strip_namespace(element.tag)
    attrs = element.attrib
    if tag in ("Cond", "Action"):
        return (attrs.get("name") or tag).strip()
    if tag == "Data":
        parts = []
        for key in ("OpStatus", "Position", "Act1"):
            value = attrs.get(key, "")
            if value and value != "0":
                parts.append(value)
        return " / ".join(parts)
    if tag == "Pattern":
        return tag
    if tag == "BaseParam":
        return tag
    return tag


def _element_group(element: ET.Element) -> str:
    tag = _strip_namespace(element.tag)
    if tag == "Pattern":
        return "pattern"
    if tag == "BaseParam":
        return "base"
    if tag == "Cond":
        return "conditions"
    if tag == "Action":
        return "actions"
    if tag == "Data":
        return "action_table"
    return "xml"


def editable_elements(root: ET.Element) -> list[dict]:
    """Return editable elements in a stable UI order."""
    items = []

    def add(elem: ET.Element):
        items.append({
            "element": elem,
            "tag": _strip_namespace(elem.tag),
            "group": _element_group(elem),
            "label": _element_label(elem, len(items)),
            "subtitle": _element_subtitle(elem),
        })

    pattern = root.find("Pattern")
    if pattern is not None:
        add(pattern)
        base = pattern.find("BaseParam")
        if base is not None:
            add(base)
        table = pattern.find("ActionTable")
        if table is not None:
            for elem in table.findall("Data"):
                add(elem)

    cond_define = root.find("ConditionDefine")
    if cond_define is not None:
        for elem in cond_define.findall("Cond"):
            add(elem)

    action_define = root.find("ActionDefine")
    if action_define is not None:
        for elem in action_define.findall("Action"):
            add(elem)

    if not items:
        for elem in root.iter():
            if elem is not root:
                add(elem)

    return items


def parse_cpu_xfbin(filepath: str) -> tuple[bytearray, dict, ET.ElementTree]:
    with open(filepath, "rb") as f:
        raw = bytearray(f.read())
    chunk = _find_xml_chunk(raw)
    data_off = chunk["data_offset"]
    xml_size = chunk["xml_size"]
    xml_bytes = bytes(raw[data_off + 4:data_off + 4 + xml_size])
    tree = _parse_xml_bytes(xml_bytes)
    return raw, chunk, tree


def parse_arcade_cpu_xfbin(filepath: str) -> tuple[bytearray, dict]:
    """Parse ArcadeCpuParam.bin.xfbin.

    The payload is a small binary table:
      [0-3]   uint32 BE - inner size
      [4-7]   uint32 LE - version
      [8-11]  uint32 LE - entry count
      [12-19] uint64 LE - first_ptr (= 8 in the sample)
      entries are 40 bytes: self-relative name pointer + 9 uint32 CPU levels.
    """
    with open(filepath, "rb") as f:
        raw = bytearray(f.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(raw)
    payload_off = chunk_hdr_off + 12
    inner_size = struct.unpack_from(">I", raw, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid ArcadeCpuParam inner size.")

    inner_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size
    version = struct.unpack_from("<I", raw, inner_off)[0]
    count = struct.unpack_from("<I", raw, inner_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", raw, inner_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid ArcadeCpuParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    entries_base = inner_off + ARCADE_CPU_HEADER_SIZE + notes_len
    entries_end = entries_base + count * ARCADE_CPU_ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("ArcadeCpuParam entry table exceeds binary chunk size.")

    entries = []
    for idx in range(count):
        base = entries_base + idx * ARCADE_CPU_ENTRY_SIZE
        name_ptr = struct.unpack_from("<I", raw, base)[0]
        name = _read_cstr(raw, base + name_ptr) if name_ptr else ""
        levels = list(struct.unpack_from("<" + "I" * ARCADE_CPU_LEVEL_COUNT, raw, base + 4))
        entries.append({
            "name": name,
            "levels": levels,
        })

    return raw, {
        "version": version,
        "notes": bytes(raw[inner_off + ARCADE_CPU_HEADER_SIZE:inner_off + ARCADE_CPU_HEADER_SIZE + notes_len]),
        "entries": entries,
    }


def save_cpu_xfbin(filepath: str, raw: bytearray, chunk: dict, tree: ET.ElementTree):
    root = tree.getroot()
    _indent(root)
    xml_text = XML_DECL + ET.tostring(root, encoding="unicode", short_empty_elements=True)
    xml_bytes = b"\xef\xbb\xbf" + xml_text.encode("utf-8")
    payload = struct.pack(">I", len(xml_bytes)) + xml_bytes

    hdr_off = chunk["hdr_offset"]
    data_off = chunk["data_offset"]
    old_chunk_size = chunk["chunk_size"]
    old_end = data_off + old_chunk_size

    new_hdr = bytearray(raw[hdr_off:hdr_off + 12])
    struct.pack_into(">I", new_hdr, 0, len(payload))
    out = raw[:hdr_off] + new_hdr + payload + raw[old_end:]

    with open(filepath, "wb") as f:
        f.write(out)


def make_default_arcade_cpu_entry(source: dict | None = None) -> dict:
    if source:
        return copy.deepcopy(source)
    return {
        "name": "NEW",
        "levels": [0] * ARCADE_CPU_LEVEL_COUNT,
    }


def _pad8(pool: bytearray, text: str) -> int:
    off = len(pool)
    pool.extend(str(text).encode("ascii", errors="replace") + b"\x00")
    rem = len(pool) % 8
    if rem:
        pool.extend(b"\x00" * (8 - rem))
    return off


def _build_arcade_cpu_inner(version: int, notes: bytes, entries: list[dict]) -> bytes:
    first_ptr = 8 + len(notes)
    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", len(entries))
    buf += struct.pack("<Q", first_ptr)
    buf += notes

    pool = bytearray()
    name_offsets = [_pad8(pool, entry.get("name", "")) for entry in entries]
    pool_abs = ARCADE_CPU_HEADER_SIZE + len(notes) + len(entries) * ARCADE_CPU_ENTRY_SIZE

    for idx, entry in enumerate(entries):
        entry_abs = ARCADE_CPU_HEADER_SIZE + len(notes) + idx * ARCADE_CPU_ENTRY_SIZE
        name_ptr = pool_abs + name_offsets[idx] - entry_abs
        levels = list(entry.get("levels", []))[:ARCADE_CPU_LEVEL_COUNT]
        levels += [0] * (ARCADE_CPU_LEVEL_COUNT - len(levels))
        buf += struct.pack("<I", name_ptr & 0xFFFFFFFF)
        buf += struct.pack("<" + "I" * ARCADE_CPU_LEVEL_COUNT, *(int(level) & 0xFFFFFFFF for level in levels))

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_arcade_cpu_xfbin(filepath: str, raw: bytearray, result: dict) -> None:
    inner = _build_arcade_cpu_inner(
        int(result.get("version", 1000)),
        bytes(result.get("notes", b"")),
        list(result.get("entries", [])),
    )
    payload = struct.pack(">I", len(inner)) + inner
    if len(payload) % 4:
        payload += b"\x00" * (4 - len(payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(raw)
    prefix = bytes(raw[:chunk_hdr_off])
    chunk_hdr = bytearray(raw[chunk_hdr_off:chunk_hdr_off + 12])
    struct.pack_into(">I", chunk_hdr, 0, len(payload))

    orig_payload_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(raw[orig_payload_end:])

    with open(filepath, "wb") as f:
        f.write(prefix + bytes(chunk_hdr) + payload + trailing)


def clone_element(element: ET.Element) -> ET.Element:
    return copy.deepcopy(element)


def add_element_like(parent: ET.Element, template: ET.Element | None, tag: str) -> ET.Element:
    if template is not None:
        elem = clone_element(template)
    else:
        elem = ET.Element(tag)
    parent.append(elem)
    return elem


def remove_element(parent: ET.Element, element: ET.Element):
    parent.remove(element)


def find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for parent in root.iter():
        if child in list(parent):
            return parent
    return None


def collect_cpu_value_catalog(directory: str) -> dict[str, list[str]]:
    """Collect editable-combo suggestions from all CPU files in a folder."""
    values: dict[str, set[str]] = {}
    if not directory or not os.path.isdir(directory):
        return {}

    for filename in sorted(os.listdir(directory)):
        if not filename.lower().endswith(".xfbin") or "_cpu" not in filename.lower():
            continue
        path = os.path.join(directory, filename)
        try:
            _, _, tree = parse_cpu_xfbin(path)
        except Exception:
            continue
        for item in editable_elements(tree.getroot()):
            tag = item["tag"]
            for key, value in item["element"].attrib.items():
                values.setdefault(key, set()).add(value)
                if key == "uid" and tag == "Cond":
                    for token_field in ("Cond1", "Cond2", "Cond3", "Combo", "StiffCond", "NextCond"):
                        values.setdefault(token_field, set()).add(value)
                elif key == "uid" and tag == "Action":
                    for action_field in ("Act1", "Act2", "Act3", "Act4", "Act5"):
                        values.setdefault(action_field, set()).add(value)

    for token_field in ("Cond1", "Cond2", "Cond3", "Combo", "StiffCond", "NextCond"):
        values.setdefault(token_field, set()).add("0")
    for action_field in ("Act1", "Act2", "Act3", "Act4", "Act5"):
        values.setdefault(action_field, set()).add("0")

    return {key: sorted(v for v in vals if v != "") for key, vals in values.items()}
