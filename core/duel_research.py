"""DuelSetting semantics for the executable identified in duel-settings-research.md.

Keep the dispatch map in parameter_research for existing callers. These names
describe consumers, not guesses from nonzero values in the stock file.
"""
from core.translations import ui_text


# 23 judges at RVA 1281020. Argument 1 is truncated to i32 before dispatch.
COUNT_ARGUMENTS = {
    34: 'duel_counterattacks',
    **dict.fromkeys(range(35, 44), 'duel_combo_hits'),
    44: 'duel_stylish_evades', 45: 'duel_taunts',
    51: 'duel_hha_uses', 52: 'duel_gha_uses', 54: 'duel_hha_hits',
    209: 'duel_assist_calls', 210: 'duel_assist_calls',
}
BOOLEAN_JUDGES = frozenset((32, 33, 48, 55, 56, 187))

# These rules test packet presence; their five floats are not gameplay knobs.
# 5176E8's callers are character-specific checks of the selected three packets.
PRESENCE_EFFECTS = frozenset((23, 42, 43, 57, 58, *range(63, 75)))
ELEMENT_ARGUMENTS = {
    59: 'duel_hamon_multiplier', 60: 'duel_vampirism_damage_multiplier',
    61: 'duel_vampirism_recovery_multiplier', 62: 'duel_fire_multiplier',
}


def editable_arguments(entry):
    """Zero-based gameplay arguments; unknown consumers stay fully exposed.

    Based on the consumers documented in duel-settings-research.md, never on
    whether a slot happens to be zero in the stock file.
    """
    from core.parameter_research import duel_effect_id
    kind = int(entry.get('type_id', -1))
    sequence = int(entry.get('sequence_id', -1))
    if kind in (3, 4):
        return (0,)
    if kind in (0, 1):
        return (0,) if sequence in COUNT_ARGUMENTS else ()
    if kind == 2:
        effect = duel_effect_id(entry)
        if effect in PRESENCE_EFFECTS or sequence == 0xFFFFFFFF:
            return ()
        if effect in (15, 17):
            return (0, 1)
        if effect in (13, 14, 16, 19, *ELEMENT_ARGUMENTS):
            return (0,)
    return tuple(range(5))


def affected_side(sequence):
    """RVA 5176E8: 0 player, 1 opponent; also used by Assist dispatch."""
    sequence = int(sequence) & 0xFFFFFFFF
    return int(
        (229 <= sequence < 251 and (0x331E81 >> (sequence - 229)) & 1)
        or (sequence < 31 and (0x55555500 >> sequence) & 1)
        or 302 <= sequence < 308
    )


def value_label(entry, index):
    from core.parameter_research import duel_effect_id, support_value_label
    kind, sequence = int(entry.get('type_id', -1)), int(entry.get('sequence_id', -1))
    effect = duel_effect_id(entry)
    if kind == 2:
        if sequence in (9, 10) and index == 2:
            return ui_text('param_duel_fixed_hp_cap')
        if effect in PRESENCE_EFFECTS:
            return ui_text('duel_presence_argument', index=index + 1)
        if effect in ELEMENT_ARGUMENTS:
            return ui_text(ELEMENT_ARGUMENTS[effect]) if index == 0 else ui_text('param_unused_effect_argument', index=index + 1)
        if effect is not None:
            return support_value_label(effect, index + 1)
        return ui_text('duel_unmapped_argument', index=index + 1)
    if kind in (0, 1):
        if index == 0 and sequence in COUNT_ARGUMENTS:
            return ui_text(COUNT_ARGUMENTS[sequence])
        return ui_text('duel_unused_judge_argument', index=index + 1)
    if kind in (3, 4):
        if index == 0:
            return ui_text('param_round_count' if kind == 3 else 'param_timer_count')
        return ui_text('duel_unused_judge_argument', index=index + 1)
    return ui_text('param_condition_argument', index=index + 1)


def value_hint(entry, index):
    from core.parameter_research import duel_effect_id, support_value_hint
    kind, sequence = int(entry.get('type_id', -1)), int(entry.get('sequence_id', -1))
    effect = duel_effect_id(entry)
    if kind == 2:
        if sequence in (9, 10) and index == 2:
            return ui_text('param_duel_fixed_hp_cap_hint')
        if effect in PRESENCE_EFFECTS:
            return ui_text('duel_presence_argument_hint')
        if effect in ELEMENT_ARGUMENTS:
            return ui_text('duel_element_multiplier_hint') if index == 0 else ui_text('param_unused_effect_argument_hint')
        if effect is not None:
            return support_value_hint(effect, index + 1)
        return ui_text('duel_unmapped_hint')
    if kind in (0, 1, 3, 4):
        if index == 0 and (sequence in COUNT_ARGUMENTS or kind in (3, 4)):
            return ui_text('duel_integer_argument_hint')
        return ui_text('duel_unused_judge_argument_hint')
    return ui_text('ui_duelsettingparam_value_hint')


def control_label(entry, index):
    """Readable editor captions without giving unused fields invented meanings."""
    if index not in editable_arguments(entry):
        if int(entry.get('type_id', -1)) == 2 and int(entry.get('sequence_id', -1)) in (9, 10) and index == 2:
            return ui_text('duel_hp_cap_label')
        return ui_text('duel_extra_parameter', index=index + 1)
    return value_label(entry, index)


def control_hint(entry, index):
    """Concise inline help; the complete native explanation stays in tooltips."""
    from core.parameter_research import duel_effect_id
    if index not in editable_arguments(entry):
        if int(entry.get('type_id', -1)) == 2 and int(entry.get('sequence_id', -1)) in (9, 10) and index == 2:
            return ui_text('duel_hp_cap_help')
        return ui_text('duel_unused_help')
    kind = int(entry.get('type_id', -1))
    if kind in (0, 1, 3, 4):
        return ui_text('duel_integer_help')
    effect = duel_effect_id(entry)
    if effect in (13, 14, *ELEMENT_ARGUMENTS):
        return ui_text('duel_multiplier_help')
    if effect == 19:
        return ui_text('duel_initial_hp_help')
    if effect in (15, 17):
        if index == (0 if effect == 15 else 1):
            return ui_text('duel_interval_help')
        return ui_text('duel_hp_help' if effect == 15 else 'duel_hh_help')
    return value_hint(entry, index)


def rule_description(entry):
    """Short, current-row explanation suitable for the research card."""
    from core.parameter_research import duel_effect_id
    kind, sequence = int(entry.get('type_id', -1)), int(entry.get('sequence_id', -1))
    if kind == 2:
        effect = duel_effect_id(entry)
        if sequence == 0xFFFFFFFF:
            return ui_text('duel_no_conditions')
        if effect is None:
            return ui_text('duel_unmapped_hint')
        side = ui_text('duel_side_opponent' if affected_side(sequence) else 'duel_side_player')
        recipient = ui_text('duel_recipient_assist' if 243 <= sequence <= 246 else 'duel_recipient_fighter')
        lines = [ui_text('duel_effect_summary', effect=effect, side=side, recipient=recipient)]
        if effect in PRESENCE_EFFECTS:
            lines.append(ui_text('duel_presence_argument_hint'))
        elif effect in ELEMENT_ARGUMENTS:
            lines.append(ui_text('duel_element_multiplier_hint'))
        if sequence == 257:
            lines.append(ui_text('duel_action_52_hint'))
        return '\n'.join(lines)
    if kind in (0, 1):
        if sequence in COUNT_ARGUMENTS:
            lines = [ui_text('duel_count_judge_hint')]
        elif sequence in BOOLEAN_JUDGES:
            lines = [ui_text('duel_boolean_judge_hint')]
        else:
            lines = [ui_text('duel_no_judge_hint')]
        if entry.get('condition_id'):
            lines.append(ui_text('duel_scm_summary'))
        return '\n'.join(lines)
    if kind in (3, 4):
        return ui_text('duel_integer_argument_hint')
    return ui_text('duel_unknown_type_hint')
