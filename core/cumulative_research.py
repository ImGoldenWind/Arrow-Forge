"""Cumulative reward semantics established in the pinned ASBR executable.

Evidence, RVAs and limits: docs/cumulative-rewards-research.md.
This module describes rows; it never simulates or modifies game saves.
"""
from core.translations import ui_text


def threshold_label(group):
    group = int(group)
    if group == 3:
        return ui_text('param_part_number')
    return ui_text(f'cum_threshold_{group}' if group in (0, 1, 2)
                   else 'ui_arcaderewardparam_cumulative_threshold')


def reward_type_name(value):
    value = int(value)
    return ui_text(f'cum_type_{value}' if value in range(9) else 'cum_type_unknown')


def threshold_hint(group):
    return ui_text('cum_part_hint' if int(group) == 3 else 'cum_count_hint')


def type_hint(value):
    value = int(value)
    return ui_text(f'cum_type_hint_{value}' if value in range(9) else 'cum_type_hint_unknown')


def next_slot(entries, group):
    """Allocate within the native (group, slot) key, independently of row order."""
    used = {int(row.get('reward_index', 0)) for row in entries
            if int(row.get('reward_group', 0)) == int(group)}
    slot = 0
    while slot in used:
        slot += 1
    return slot


def has_dense_slots(entries, group):
    slots = sorted(int(row.get('reward_index', 0)) for row in entries
                   if int(row.get('reward_group', 0)) == int(group))
    return slots == list(range(len(slots)))


def compact_slots(entries, group):
    """Used only after deleting from a group which was already contiguous."""
    rows = sorted((row for row in entries if int(row.get('reward_group', 0)) == int(group)),
                  key=lambda row: int(row.get('reward_index', 0)))
    for slot, row in enumerate(rows):
        row['reward_index'] = slot


def row_description(entry, entries=()):
    group = int(entry.get('reward_group', 0))
    slot = int(entry.get('reward_index', 0))
    threshold = int(entry.get('threshold', 0))
    kind = int(entry.get('reward_type', 0))
    condition = ui_text(f'cum_condition_{group}' if group in range(4)
                        else 'cum_condition_unknown', value=threshold)
    lines = [condition, ui_text('cum_reward_summary', value=kind, name=reward_type_name(kind)),
             type_hint(kind)]
    if group == 3 and kind == 7:
        lines.append(ui_text('cum_silent_art'))
    if group == 3 and threshold not in range(1, 9):
        lines.append(ui_text('cum_invalid_part'))
    if group in (0, 1, 2) and threshold == 0:
        lines.append(ui_text('cum_zero_threshold'))
    if entries:
        peers = [row for row in entries if int(row.get('reward_group', 0)) == group]
        duplicates = sum(int(row.get('reward_index', 0)) == slot for row in peers)
        if duplicates > 1:
            lines.append(ui_text('cum_duplicate_slot', group=group, slot=slot))
        if not has_dense_slots(entries, group):
            lines.append(ui_text('cum_sparse_slots', group=group))
    return '\n\n'.join(lines)
