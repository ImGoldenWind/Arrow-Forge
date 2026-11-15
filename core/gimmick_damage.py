"""Gimmick damage semantics established by the native loader and consumers.

No trajectory integration: the file supplies attack inputs, not scene state.
See docs/gimmick-damage-research.md for addresses and verification limits.
"""
import math
import struct
from pathlib import Path

from parsers.gimmickdmgparam_parser import float_to_word, word_to_float
from core.stage_tools import float32_text


FLOAT_OFFSETS = (0x10, 0x14, 0x18, 0x24, 0x28, 0x2C, 0x30, 0x34)
FLAG_OFFSETS = tuple(range(0x3C, 0x64, 4))


def signed(word):
    return word - 0x100000000 if word & 0x80000000 else word


def word_text(word, offset):
    if offset in FLOAT_OFFSETS:
        return float32_text(word_to_float(word))
    return str(signed(word)) if offset in FLAG_OFFSETS or offset == 0x1C else str(word)


def parse_word(text, offset):
    text = text.strip()
    if not text:
        raise ValueError('gdm_invalid_number')
    try:
        if offset in FLOAT_OFFSETS:
            value = float(text)
            if not math.isfinite(value):
                raise ValueError()
            return float_to_word(value)
        value = int(text, 16 if text.lower().startswith('0x') else 10)
        if not -0x80000000 <= value <= 0xFFFFFFFF:
            raise ValueError()
        return value & 0xFFFFFFFF
    except (ValueError, OverflowError, struct.error):
        raise ValueError('gdm_invalid_number') from None


def validate_identifier(text):
    if '\0' in text:
        raise ValueError('gdm_invalid_id')
    try:
        text.encode('ascii')
    except UnicodeEncodeError:
        raise ValueError('gdm_invalid_id') from None
    return text


def flag_indices(entry):
    """Negative slots are ignored; out-of-range positive values are unsafe."""
    return tuple(sorted({signed(entry.words[o // 4]) for o in FLAG_OFFSETS
                         if 0 <= signed(entry.words[o // 4]) < 128}))


def launch_velocity(entry, reaction):
    """Original SSE scalar multiply, then scalar add (not fused multiply-add).

    Gimmick setup leaves the extra velocity offsets at their attack defaults.
    Show only the base*scale contribution; no receiver/world direction claim.
    """
    def multiply(a, b):
        try:
            return word_to_float(float_to_word(a * b))
        except OverflowError:
            return math.copysign(math.inf, a * b)
    return (multiply(float(reaction['launch_x']), word_to_float(entry.words[5])),
            multiply(float(reaction['launch_y']), word_to_float(entry.words[6])))


def reference_candidates(source, filename, game_dir=''):
    """Bounded neighboring locations, then an explicitly configured tree."""
    parent = Path(source).resolve().parent
    roots = [parent, parent / 'data', parent / 'spc', parent / 'data' / 'spc']
    if parent.name.lower() == 'stage':
        roots.append(parent.parent / 'spc')
    if game_dir:
        root = Path(game_dir).expanduser()
        roots += [root, root / 'spc', root / 'data' / 'spc']
    seen = set()
    for root in roots:
        path = root / filename
        key = str(path.resolve()).casefold()
        if key not in seen and path.is_file():
            seen.add(key)
            yield path


def row_issues(entry, entries, reactions):
    issues = []
    def present(row, name, word):
        return bool(getattr(row, name) or row.words[word] or row.words[word + 1])
    if not present(entry, 'stage_id', 0) or not present(entry, 'damage_id', 2):
        issues.append('gdm_issue_inactive')
    if entry.stage_id and sum(e.stage_id == entry.stage_id and bool(e.damage_id)
                              for e in entries) > 1:
        issues.append('gdm_issue_duplicate')
    if reactions and entry.damage_id and entry.damage_id not in reactions:
        issues.append('gdm_issue_reaction')
    if len(entry.damage_id.encode('ascii', errors='replace')) >= 256:
        issues.append('gdm_issue_long_id')
    values = [signed(entry.words[o // 4]) for o in FLAG_OFFSETS]
    if any(n >= 128 for n in values):
        issues.append('gdm_issue_flag_range')
    if len([n for n in values if n >= 0]) != len(set(n for n in values if n >= 0)):
        issues.append('gdm_issue_duplicate_flags')
    return issues
