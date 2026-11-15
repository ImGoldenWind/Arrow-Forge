"""Online Mission authoring helpers; native evidence: online-missions-research.md.

Catalogs are read-only suggestions, never a claim that a custom event is emitted.
The event probe models only string matching, not a battle or network lifecycle.
"""
from pathlib import Path
import re
import struct

from core.cumulative_research import reward_type_name
from core.dictionary_tools import character_catalog, _local_catalog_path
from core.story_tools import character_name
from core.translations import ui_text
from parsers.onlinemissionparam_parser import NUMERIC_FIELDS, STRING_FIELDS

INTEGER_RANGES = {key: (-(1 << 31), (1 << 31) - 1) if key == 'reward_value'
                  else (0, (1 << 32) - 1) for key, _ in NUMERIC_FIELDS}
STRING_KEYS = tuple(key for key, _ in STRING_FIELDS)


def field_value(key, text):
    if key in STRING_KEYS:
        if '\0' in text:
            raise ValueError('NUL in reference')
        text.encode('ascii')
        return text
    if not re.fullmatch(r'-?[0-9]+', text):
        raise ValueError('incomplete integer')
    value = int(text)  # Empty/incomplete text must never become zero.
    low, high = INTEGER_RANGES[key]
    if not low <= value <= high:
        raise ValueError('outside storage range')
    return value


def catalogs(filepath, configured=''):
    """Prefer catalogs next to the document; tolerate missing/broken resources."""
    characters, error = character_catalog(filepath, configured)
    result = {'characters': characters, 'stages': (), 'cards': ()}
    errors = [error] if error else []
    for name, relative, parser_name, function, rows in (
        ('stages', 'stage/HIGH_SPEC/StageInfo.bin.xfbin', 'stageinfo', 'parse_stageinfo_xfbin', 'stages'),
        ('cards', 'param/customize/CustomCardParam.bin.xfbin', 'customcardparam', 'parse_customcardparam_xfbin', 'entries'),
    ):
        path = _local_catalog_path(filepath, configured, relative)
        if path is None:
            continue
        try:
            from importlib import import_module
            parsed = getattr(import_module('parsers.' + parser_name + '_parser'), function)(path)
            result[name] = tuple(parsed[2] if name == 'cards' else parsed[1][rows])
        except (OSError, ValueError, KeyError, IndexError, UnicodeError, struct.error) as exc:
            errors.append(f'{Path(path).name}: {exc}')
    return result, '\n'.join(errors)


def choices(key, entries, resources, lookup=None, reward_type=None):
    values = {e.get(key, '') for e in entries}
    if key == 'group_id':
        names = {i: ui_text('om_group', value=i) for i in range(12)}
    elif key == 'display_slot':
        names = {i: ui_text('om_slot', value=i) for i in range(5)}
    elif key == 'mission_type':
        names = {6: ui_text('om_scope_both'), 7: ui_text('om_scope_ranked')}
    elif key == 'flag_08':
        names = {0: ui_text('om_any_result'), 1: ui_text('om_win_required')}
    elif key == 'subtype_id':
        names = {0: ui_text('om_any_fighter'),
                 **{i: ui_text(f'part_{i}') for i in range(1, 9)},
                 9: ui_text('om_roster_heroes'), 10: ui_text('om_roster_bosses')}
    elif key == 'reward_type':
        names = {i: reward_type_name(i) for i in range(9)}
        names[0xffffffff] = ui_text('online_reward_unsupported')
    elif key in ('character_id', 'opponent_character_id'):
        return [('', ui_text('om_any_fighter'))] + [
            (v, f'{character_name(v)} · {v}') for v in sorted(values | set(resources.get('characters', ()))) if v]
    elif key == 'stage_id':
        return [('', ui_text('om_any_stage'))] + [(v, v) for v in sorted(
            values | {r['code'] for r in resources.get('stages', ())}) if v]
    elif key == 'reward_card_id':
        # Types 3/6/8 share the CustomCard lookup. Do not infer a category
        # restriction: the dispatcher resolves the authored card ID directly.
        cards = resources.get('cards', ()) if reward_type in (3, 6, 8) else ()
        labels = {r['card_id']: f"{character_name(r['char_id'])} · {r['card_id']}" for r in cards}
        return [(v, labels.get(v, v) or ui_text('card_empty_reference'))
                for v in sorted(values | labels.keys() | {''})]
    elif key in ('title_key', 'condition_id', 'banner_id'):
        result = []
        for v in sorted(values | {''}):
            reference = lookup.resolve(v) if lookup and key == 'title_key' and v else None
            caption = f"{v} · {reference.text.replace(chr(10), ' ')}" if reference and reference.text else v
            if key == 'condition_id' and not v:
                caption = ui_text('om_match_completion')
            result.append((v, caption or ui_text('card_empty_reference')))
        return result
    else:
        return None
    return [(v, f'{v} — {names[v]}' if v in names else str(v))
            for v in sorted(values | names.keys())]


def group_slots(entries, group):
    """Loader: last group/slot wins, then mission lookup keeps the first ID."""
    first_ids = {}
    slots = [None] * 5
    for index, row in enumerate(entries):
        first_ids.setdefault(row['mission_id'], index)
    for row in entries:
        slot = row['display_slot']
        if row['group_id'] == group and 0 <= slot < 5:
            slots[slot] = first_ids[row['mission_id']]
    return slots


def entry_issues(entry, entries):
    issues = []
    if not 0 <= entry['group_id'] < 12 or not 0 <= entry['display_slot'] < 5:
        issues.append(ui_text('online_invalid_slot'))
    if entry['mission_id'] >= 60:
        issues.append(ui_text('om_unverified_identity'))
    if any(row is not entry and row['mission_id'] == entry['mission_id'] for row in entries):
        issues.append(ui_text('online_duplicate_id'))
    if any(row is not entry and (row['group_id'], row['display_slot']) ==
           (entry['group_id'], entry['display_slot']) for row in entries):
        issues.append(ui_text('online_duplicate_slot'))
    return issues


def event_match(entry, incoming, *, assist=False):
    """Only the confirmed string gates. None means runtime state is required."""
    incoming = incoming.split('\0', 1)[0]  # Native inputs are NUL-terminated.
    condition = entry.get('condition_id', '')
    mission = entry.get('mission_id', 0)
    if assist:
        return mission == 51 and condition == incoming
    if not condition or condition not in incoming:
        return False
    if mission == 6 and not any(v in incoming for v in ('2csr_skl_sabao_lens', '2csr_skl_sabao_laser')):
        return False
    return None if mission == 12 else True
