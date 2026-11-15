"""Native 16-byte NetRankParam rows with lossless shared NUCC framing."""
import copy
from parsers.relative_table import RelativeTable

ENTRY_SIZE, HEADER_SIZE, INNER_SIZE_FIELD, DEFAULT_VERSION = 16, 16, 4, 1000
_table = RelativeTable('NetRankParam', ENTRY_SIZE, ((8, 'name_key'),),
                       ((0, 'rank_id', 'I'), (4, 'required_points', 'I')))
_find_binary_chunk = _table.find_chunk


def parse_netrankparam_xfbin(filepath):
    raw, version, entries = _table.parse(filepath)
    header, size = _table.find_chunk(raw)
    _, _, prefix, _, tail = _table.parse_payload(raw[header + 12:header + 12 + size])
    for index, entry in enumerate(entries):
        # The shared codec can retain arbitrary string bytes. This editor uses
        # Unicode Message IDs, so reject undecodable references before exposing
        # them to Qt/message lookup rather than replacing bytes or crashing UI.
        try:
            entry['name_key'].encode('utf-8')
        except UnicodeEncodeError as exc:
            raise ValueError('NetRankParam name reference is not valid UTF-8.') from exc
        entry['index'] = index
    return raw, dict(version=version, prefix_bytes=prefix, tail_bytes=tail, entries=entries)


def make_default_entry(source=None, rank_id=0):
    if source is not None:
        entry = copy.deepcopy(source)
        entry.pop('index', None)
        entry.pop('_offset', None)
        return entry
    return dict(rank_id=rank_id, required_points=0, name_key=f'rankname_{rank_id:03d}')


def _build_inner(version, prefix_bytes, entries):
    return _table.build(version, entries, prefix_bytes)


def save_netrankparam_xfbin(filepath, original_data, result):
    _table.save(filepath, original_data, result.get('version', DEFAULT_VERSION), result['entries'])
