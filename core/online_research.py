"""OnlineMission behavior established in ASBR.exe; see online-missions-research.md.

Only describes parameters. No save manipulation or network operations.
"""
from core.translations import ui_text


def next_identity(entries, preferred_group=0):
    """Use a vacant native slot and a free identity within the stock save range."""
    used_ids = {int(row.get('mission_id', 0)) for row in entries}
    identity = next((i for i in range(60) if i not in used_ids), None)
    used_slots = {(int(row.get('group_id', 0)), int(row.get('display_slot', 0)))
                  for row in entries}
    groups = [preferred_group] if preferred_group in range(12) else []
    groups += [g for g in range(12) if g not in groups]
    for group in groups:
        for slot in range(5):
            if identity is not None and (group, slot) not in used_slots:
                return dict(mission_id=identity, group_id=group, display_slot=slot)
    return None


def row_description(entry, entries=()):
    mission = int(entry.get('mission_id', 0))
    group = int(entry.get('group_id', 0))
    slot = int(entry.get('display_slot', 0))
    scope = int(entry.get('mission_type', 0))
    part = int(entry.get('subtype_id', 0))
    count = int(entry.get('objective_value', 0))
    kind = int(entry.get('reward_type', 0))
    lines = [ui_text('online_scope_any' if scope == 6 else 'online_scope_ranked'),
             ui_text('online_wins' if int(entry.get('flag_08', 0)) == 1 else 'online_participation')]
    if entry.get('character_id'):
        lines.append(ui_text('online_character_priority', character=entry['character_id']))
    elif part:
        lines.append(ui_text(f'online_part_{part}' if part in (9, 10) else 'online_part_number', value=part))
    if entry.get('opponent_character_id'):
        lines.append(ui_text('online_opponent', character=entry['opponent_character_id']))
    if entry.get('stage_id'):
        lines.append(ui_text('online_stage', stage=entry['stage_id']))
    if entry.get('condition_id'):
        lines.append(ui_text('online_event_count', condition=entry['condition_id'], value=count))
    else:
        lines.append(ui_text('online_match_count', value=count))
    if count > 255:
        lines.append(ui_text('online_byte_threshold', value=count & 255))
    if mission in (6, 12, 51):
        lines.append(ui_text(f'online_special_{mission}'))
    from core.cumulative_research import reward_type_name
    name = reward_type_name(kind) if kind in range(9) else ui_text('online_reward_unsupported')
    lines.append(ui_text('online_rewards_summary', gp=int(entry.get('reward_value', 0)), kind=kind, name=name))
    if slot != 0:
        lines.append(ui_text('online_reward_slot0'))
    if not (0 <= group < 12 and 0 <= slot < 5):
        lines.append(ui_text('online_invalid_slot'))
    if any(row is not entry and int(row.get('mission_id', 0)) == mission for row in entries):
        lines.append(ui_text('online_duplicate_id'))
    if any(row is not entry and (int(row.get('group_id', 0)), int(row.get('display_slot', 0))) == (group, slot)
           for row in entries):
        lines.append(ui_text('online_duplicate_slot'))
    return '\n'.join(lines)
