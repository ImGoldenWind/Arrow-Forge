"""Native NetResultParam i32 pairs with lossless shared NUCC framing.

The first five values are grade bases; later rows are ordered BP-difference
bonuses. Both words are consumed as i32; see docs/netresult-research.md.
"""
import copy
from parsers.relative_table import RelativeTable

ENTRY_SIZE, HEADER_SIZE, INNER_SIZE_FIELD, DEFAULT_VERSION = 8, 16, 4, 1000
_table = RelativeTable('NetResultParam', ENTRY_SIZE, (),
                       ((0, 'threshold', 'i'), (4, 'value', 'i')))
_find_binary_chunk = _table.find_chunk


def parse_netresultparam_xfbin(filepath):
    raw, version, entries = _table.parse(filepath)
    header, size = _table.find_chunk(raw)
    _, _, notes, pool, tail = _table.parse_payload(raw[header + 12:header + 12 + size])
    return raw, dict(version=version, notes=notes, pool_bytes=pool, tail_bytes=tail, entries=entries)


def make_default_entry(source=None):
    entry = copy.deepcopy(source) if source is not None else dict(threshold=0, value=0)
    entry.pop('_offset', None)
    return entry


def _compatible_entries(entries):
    # Previous API exposed the second word as u32. Accept its exact bit pattern
    # while rejecting overflow; never mask an out-of-range value silently.
    result = []
    for entry in entries:
        row = dict(entry)
        value = row.get('value', 0)
        if 0x80000000 <= value <= 0xffffffff:
            row['value'] = value - 0x100000000
        result.append(row)
    return result


def _build_inner(version, notes, entries):
    return _table.build(version, _compatible_entries(entries), notes)


def save_netresultparam_xfbin(filepath, original_data, result):
    _table.save(filepath, original_data, result.get('version', DEFAULT_VERSION),
                _compatible_entries(result['entries']))
