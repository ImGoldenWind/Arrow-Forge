"""PC achievement facts; deliberately independent of TrophyParam file IDs.

RVAs refer to executable SHA-256 4d6044d5...922fee. See
docs/trophy-research.md for evidence and the unresolved file consumer.
No entry in this module assigns semantics to a TrophyParam row.
"""

from core.translations import ui_text


# ID -> (condition translation key, arguments, native producer RVA).
PC_ACHIEVEMENTS = {
    0: ('all_achievements', {}, 0x7B9AC0),
    1: ('all_parts', {}, 0x5FAED0),
    7: ('part_panels', {'part': 3, 'count': 5}, 0x5FAF7C),
    19: ('single_vs', {}, 0x5FAF7C),
    20: ('gallery', {'count': 100}, 0x5FAAB0),
    21: ('gallery', {'count': 500}, 0x5FAAB0),
    22: ('hha', {}, 0x5FAA2C),
    23: ('gha', {}, 0x5FAA2C),
    24: ('easy_beat', {}, 0x5FAA2C),
    25: ('assist', {}, 0x5FAA2C),
    26: ('taunt', {}, 0x5FAA2C),
    27: ('evade', {}, 0x5FAA2C),
    28: ('flash_cancel', {}, 0x5FAA2C),
    29: ('rush', {}, 0x5FAA2C),
    30: ('secret_first', {}, 0x5FB084),
    31: ('secret_count', {'count': 30}, 0x5FB084),
    32: ('secret_count', {'count': 50}, 0x5FB084),
    33: ('gimmick_first', {}, 0x5FB214),
    34: ('gimmick_all', {}, 0x5FB214),
    35: ('gimmick_hit_first', {}, 0x5FADBC),
    36: ('gimmick_hit_all', {}, 0x5FADBC),
    37: ('dramatic_first', {}, 0x5FB100),
    38: ('dramatic_all', {}, 0x5FB100),
    39: ('challenge', {}, 0x477F6C),
    40: ('endless', {}, 0x5321C0),
    41: ('tournament_first', {}, 0x53E2E8),
    42: ('tournament_all', {}, 0x53E2E8),
    43: ('online_first', {}, 0x541058),
    44: ('rank_up', {}, 0x5402A0),
    45: ('online_count', {'count': 100}, 0x5FAA68),
}
for _part, _first, _all in (
    (1, 2, 3), (2, 4, 5), (3, 6, 8), (4, 9, 10),
    (5, 11, 12), (6, 13, 14), (7, 15, 16), (8, 17, 18),
):
    PC_ACHIEVEMENTS[_first] = ('part_panels', {'part': _part, 'count': 1}, 0x5FAF7C)
    PC_ACHIEVEMENTS[_all] = ('part_all', {'part': _part}, 0x5FAED0)


def pc_condition(pc_id):
    key, args, _rva = PC_ACHIEVEMENTS[pc_id]
    return ui_text('trophy_pc_' + key, **args)


def pc_label(pc_id):
    return pc_condition(pc_id)


def pc_description(pc_id):
    """User-facing condition; native implementation details stay in research."""
    return pc_condition(pc_id)
