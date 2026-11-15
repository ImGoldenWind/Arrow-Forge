"""NetRankParam semantics, independent of Qt.

Native RVAs 541C7C/541CB4 scan backwards and compare unsigned points.
File order is significant, including duplicate IDs/thresholds. See research.
"""
from collections import Counter
from core.record_session import RecordSession

UINT32_MAX = 0xFFFFFFFF
FIELDS = ('rank_id', 'required_points', 'name_key')


def parse_field(key, text):
    if key == 'name_key':
        from parsers.netrankparam_parser import _table
        _table.encoded(text)
        return text
    if not text or not text.isascii() or not text.isdecimal():
        raise ValueError('An unsigned decimal integer is required.')
    value = int(text)
    if value > UINT32_MAX:
        raise ValueError('Outside u32 storage.')
    return value


def rank_at_points(entries, points):
    """Return the last eligible row, or None (native ID 0 / empty name)."""
    if not 0 <= points <= UINT32_MAX:
        raise ValueError('Outside u32 storage.')
    return next((i for i in range(len(entries) - 1, -1, -1)
                 if points >= entries[i]['required_points']), None)


def eligibility_ranges(entries):
    """Inclusive exact point interval per row; None means shadowed by a later row."""
    ceiling, ranges = UINT32_MAX, []
    for entry in reversed(entries):
        threshold = entry['required_points']
        ranges.append((threshold, ceiling) if threshold <= ceiling else None)
        ceiling = min(ceiling, threshold - 1)
    return list(reversed(ranges))


def duplicate_ids(entries):
    return {key for key, count in Counter(e['rank_id'] for e in entries).items() if count > 1}


def next_id(entries):
    used = {e['rank_id'] for e in entries}
    candidate = 0
    while candidate in used:
        candidate += 1
    if candidate > UINT32_MAX:
        raise ValueError('No unused u32 ID remains.')
    return candidate


class RankSession(RecordSession):
    """Original comparison follows row identity even after edits/insertion/deletion."""
    def __init__(self, result):
        super().__init__(result, FIELDS)
