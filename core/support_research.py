"""SupportItem observations from the pinned ASBR native consumers.

See docs/support-items-research.md for RVAs, native oracles and limits.
Parser keys stay compatible with existing files and integrations.
"""
from core.translations import ui_text


EFFECT_IDS = (0, 13, 14, 15, 16, 17, 19, 20, 25, 35, 44, 45, 46, 47)
# 52D6E0: this is keyed by Support ID, independently of file +18.
_MENU_CLASSES = {0: 1, 21: 4, 22: 4, 24: 0, 25: 4, 26: 4,
                 27: 4, 28: 4, 29: 1}
RANDOM_POOL = (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 13, 20, 12, 16, 17, 18)


def menu_class(support_id):
    return _MENU_CLASSES.get(int(support_id), 2)


def packet_gate(entry):
    """Local gates only; DLC ownership is checked separately by the game."""
    availability = int(entry.get('empty_slot_marker', 0)) & 0xFFFFFFFF
    return (_local_availability(availability)
            and int(entry.get('target_group', 0)) != 0
            and 0 <= int(entry.get('effect_type', 0)) < 0x80000000)


def _local_availability(value):
    return (0 <= value < 10000 and value not in (2, 3)
            or 10000 <= value <= 10012 or 20000 <= value <= 20009)


def effect_options():
    return [(value, f"{value} — {ui_text('support_effect_' + str(value))}")
            for value in EFFECT_IDS]


def effect_name(value):
    value = int(value)
    return (ui_text('support_effect_' + str(value)) if value in EFFECT_IDS
            else ui_text('support_custom_effect', value=value))


def visibility(entry):
    """Menu-list conditions only: no claim about DLC ownership or purchases."""
    marker = int(entry.get('shop_marker', 0)) & 0xFFFFFFFF
    if not 0 < marker < 0x80000000:
        return 'hidden'
    return 'campaign' if entry.get('unlock_or_story_flag', 0) else 'both'


def availability_options():
    return [(0, ui_text('support_availability_base')),
            (2, ui_text('support_availability_excluded')),
            (3, ui_text('support_availability_blocked')),
            (0xFFFFFFFF, ui_text('support_availability_disabled')),
            *[(10000 + i, ui_text('support_availability_dlc', index=i, value=10000+i)) for i in range(13)],
            *[(20000 + i, ui_text('support_availability_content', index=i, value=20000+i)) for i in range(10)]]


def target_options(second=False):
    zero_key = 'support_target_second_zero' if second else 'support_target_first_zero'
    return [(0, ui_text(zero_key)), (1, ui_text('param_effect_target_1')),
            (2, ui_text('param_effect_target_2'))]


def identity_diagnostics(entry, entries):
    sid = int(entry.get('support_id', 0))
    lines = []
    if sid > 255:
        lines.append(ui_text('support_id_range_warning'))
    if sum(int(e.get('support_id', 0)) == sid for e in entries) > 1:
        lines.append(ui_text('support_duplicate_id_warning'))
    slot = int(entry.get('display_order', 0))
    if slot < 0x80000000 and sum(int(e.get('display_order', 0)) == slot for e in entries) > 1:
        lines.append(ui_text('support_duplicate_slot'))
    return '\n'.join(lines)


def row_description(entry):
    sid = int(entry.get('support_id', 0))
    marker = int(entry.get('shop_marker', 0)) & 0xFFFFFFFF
    slot = int(entry.get('display_order', 0)) & 0xFFFFFFFF
    if slot >= 0x80000000:
        slot -= 0x100000000
    lines = [ui_text('support_row_summary', support_id=sid,
                     menu_class=menu_class(sid), slot=slot)]
    if not 0 < marker < 0x80000000:
        lines.append(ui_text('support_hidden_marker'))
    if int(entry.get('unlock_or_story_flag', 0)):
        lines.append(ui_text('support_campaign_only'))
    availability = int(entry.get('empty_slot_marker', 0)) & 0xFFFFFFFF
    if not _local_availability(availability):
        lines.append(ui_text('support_unavailable'))
    if not packet_gate(entry):
        lines.append(ui_text('support_packets_disabled'))
    elif (int(entry.get('effect_2_type', 0))
          and int(entry.get('effect_2_target', 0)) != 2):
        lines.append(ui_text('support_second_self'))
    if sid == 23:
        lines.append(ui_text('support_random_handler'))
    elif sid in (21, 22, 24, 25, 26, 27, 28, 29):
        lines.append(ui_text('support_special_id'))
    return '\n'.join(lines)
