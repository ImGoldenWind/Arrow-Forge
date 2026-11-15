"""Exact BP awards and record snapshots, independent of Qt.

Native RVAs 53EB9C, 53EAC4 and update slice in 5402A0. File order matters.
"""
import struct
from dataclasses import dataclass
from core.record_session import RecordSession

INT32_MIN, INT32_MAX = -0x80000000, 0x7fffffff
POINTS_MAX = 9_999_999  # Native post-award clamp, not a file-field limit.
BASE_COUNT = 5
GRADES = ('S', 'A', 'B', 'C', 'D')
FIELDS = ('threshold', 'value')


def parse_integer(text, minimum=INT32_MIN, maximum=INT32_MAX):
    digits = text[1:] if text.startswith('-') else text
    if not digits or not digits.isascii() or not digits.isdecimal():
        raise ValueError('A complete decimal integer is required.')
    value = int(text)
    if not minimum <= value <= maximum:
        raise ValueError('Outside the supported range.')
    return value


def signed(value):
    return (value + 0x80000000) % 0x100000000 - 0x80000000


def bonus_row(entries, difference):
    """First signed inclusive match, starting at file position 5; no sorting."""
    difference = signed(difference)
    return next((i for i in range(BASE_COUNT, len(entries))
                 if entries[i]['threshold'] <= difference), None)


def bonus_ranges(entries):
    """Reachable signed intervals, None for base/fully shadowed records."""
    ceiling, intervals = INT32_MAX, [None] * min(BASE_COUNT, len(entries))
    for entry in entries[BASE_COUNT:]:
        low = entry['threshold']
        intervals.append((low, ceiling) if low <= ceiling else None)
        ceiling = min(ceiling, low - 1)
    return intervals


def _float32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def loser_delta(amount):
    """x64 signed conversion, MULSS by native -1/3, CVTTSS2SI truncation."""
    value = _float32(_float32(signed(amount)) * _float32(-1 / 3))
    return int(value) if INT32_MIN <= value < 0x80000000 else INT32_MIN


@dataclass(frozen=True)
class Award:
    difference: int | None
    row: int | None
    base: int
    bonus: int
    deltas: tuple[int, int]
    totals: tuple[int, int]


def calculate(entries, points1, points2, outcome, grade):
    """Outcome: 1 draw, 2 player 1 wins, 3 player 2 wins; grade index S..D.

    A short table cannot safely supply a base slot and is rejected explicitly.
    Network availability/updates are outside this isolated calculation.
    """
    if outcome not in (1, 2, 3) or not 0 <= grade < BASE_COUNT:
        raise ValueError('Unsupported outcome or grade.')
    if not all(0 <= p <= POINTS_MAX for p in (points1, points2)):
        raise ValueError('BP probe is outside the native clamped range.')
    if len(entries) < BASE_COUNT:
        raise ValueError('The five native grade slots are required.')
    difference, row, base, bonus = None, None, 0, 0
    if outcome == 1:
        deltas = (0, 0)
    else:
        difference = signed(points2 - points1 if outcome == 2 else points1 - points2)
        row = bonus_row(entries, difference)
        base = signed(entries[grade]['value'])
        bonus = signed(entries[row]['value']) if row is not None else 0
        amount = signed(base + bonus)
        loss = loser_delta(amount)
        deltas = (amount, loss) if outcome == 2 else (loss, amount)
    totals = tuple(max(0, min(POINTS_MAX, signed(p + d))) for p, d in zip((points1, points2), deltas))
    return Award(difference, row, base, bonus, deltas, totals)


class ResultSession(RecordSession):
    """Snapshot follows identity even after a positional role changes."""
    def __init__(self, result):
        super().__init__(result, FIELDS)
