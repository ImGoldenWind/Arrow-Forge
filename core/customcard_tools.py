"""Custom Card semantics and validation; no Qt or file mutation.

Native RVAs and limitations: docs/custom-card-research.md.
"""
from pathlib import Path

from core.story_tools import character_name
from core.translations import ui_text
from parsers.customcardparam_parser import _INT_FIELDS, _STR_KEYS, _encoded

INTEGER_RANGES = {key: (-(1 << 31), (1 << 31) - 1) if fmt == 'i' else (0, (1 << 32) - 1)
                  for _, key, fmt in _INT_FIELDS}
MESSAGE_KEYS = ('medal_name', 'card_detail')
SAVE_SLOT_COUNT = 0x800  # Native 5F7F14/5F7FD4 enumerate 2048 card save slots.
CATEGORY_IDS = (1, 2, 3, 4, 5, 7, 8, 9, 10)


def parse_field(key, text):
    if key in _STR_KEYS:
        _encoded(text)
        return text
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    low, high = INTEGER_RANGES[key]
    if not low <= value <= high:
        raise ValueError('outside storage range')
    return value


def category_name(value):
    return ui_text(f'card_category_{value}') if value in CATEGORY_IDS else str(value)


def part_name(value):
    return ui_text('ui_galleryartparam_no_part_special') if value == 0 else (
        ui_text(f'part_{value}') if 1 <= value <= 8 else str(value))


def variant_index(entry):
    """Exact first-byte conversion of native 5D82A4, including unusual values."""
    text = entry['letter'].encode('utf-8', errors='surrogateescape')
    if 1 <= entry['medal_type'] <= 5:
        return (text[0] if text[0] < 128 else text[0] - 256) - 65 if text else -1
    return -1 if text else 0


def name_message_id(entry):
    if entry['medal_name'] and entry['medal_type'] != 1:
        return entry['medal_name']
    prefixes = {1: ('color_', 5), 2: ('costume_a', 7), 3: ('prov_', 5),
                4: ('pose_', 5), 5: ('gion_', 2)}
    if entry['medal_type'] in prefixes:
        prefix, count = prefixes[entry['medal_type']]
        index = variant_index(entry)
        return f'medal_name_{prefix}{index}' if 0 <= index < count else ''
    if entry['medal_type'] == 8:
        return 'medal_name_color_a0' if not entry['letter'] else ''
    return {7: 'medal_name_word',
            9: 'medal_name_special', 10: 'medal_name_player_title'}.get(entry['medal_type'], '')


def choices(key, entries, characters=()):
    values = {entry[key] for entry in entries}
    if key == 'medal_type':
        names = {v: category_name(v) for v in CATEGORY_IDS}
    elif key == 'part':
        names = {v: part_name(v) for v in range(9)}
    elif key == 'unlock_condition':
        names = {v: ui_text(f'card_unlock_{v}') for v in (0, 1, 2, 3, 4, 5, 6)}
    elif key == 'char_id':
        return [(v, f'{character_name(v)} · {v}') for v in sorted(values | set(characters)) if v]
    elif key in ('letter', 'dlc_id', 'patch', 'interaction_type', *MESSAGE_KEYS,
                 'sfx1', 'sfx2', 'sfx3', 'sfx4'):
        return [(v, str(v)) for v in sorted(values)]
    else:
        return None
    return [(v, f'{v} — {names[v]}' if v in names else str(v)) for v in sorted(values | names.keys())]


def next_identity(entries):
    used = {e['index'] for e in entries}
    index = next((n for n in range(1, SAVE_SLOT_COUNT) if n not in used), None)
    if index is None:
        raise ValueError(ui_text('card_no_slots'))
    names = {e['card_id'] for e in entries}
    number = index
    while f'CCD_CUSTOM_CARD_ID_{number}' in names:
        number += 1
    return index, f'CCD_CUSTOM_CARD_ID_{number}'


def entry_issues(entry, entries, current):
    issues = []
    if not entry['card_id']:
        issues.append(ui_text('card_empty_id'))
    for key in ('card_id', 'index'):
        if any(e is not current and e[key] == entry[key] for e in entries):
            issues.append(ui_text('gallery_duplicate', field=ui_text('card_' + key)))
    if entry['index'] >= SAVE_SLOT_COUNT:
        issues.append(ui_text('card_index_limit', maximum=SAVE_SLOT_COUNT - 1))
    limits = {1: 5, 2: 7, 3: 5, 4: 5, 5: 2}
    count = limits.get(entry['medal_type'])
    if count is not None and not 0 <= variant_index(entry) < count:
        issues.append(ui_text('card_invalid_variant', last=chr(64 + count)))
    if entry['medal_type'] not in CATEGORY_IDS:
        issues.append(ui_text('card_unknown_category'))
    if entry['unk18'] <= 0:
        issues.append(ui_text('card_nonpositive_required'))
    return issues


def granted_values(entry):
    """Native lists, without asserting that referenced animations exist."""
    kind = entry['medal_type']
    if kind == 3:
        return ('taunts', (entry['unk7_2'], entry['unk7_3']))
    if kind == 4:
        return ('poses', (entry['unk7_0'], entry['unk7_1']))
    if kind == 7:
        # Both native branches add 10 using signed 32-bit arithmetic. Keep
        # large authored counts compact; never allocate a range from input.
        ranges = []
        for key in ('unk7_0', 'unk7_2'):
            end = ((entry[key] + 10 + (1 << 31)) % (1 << 32)) - (1 << 31)
            ranges.append(f'10–{end - 1}' if end > 10 else '—')
        return ('speech', tuple(ranges))
    if kind == 5:
        return ('sounds', tuple(entry[f'sfx{i}'] for i in range(1, 5) if entry[f'sfx{i}']))
    if kind == 9:
        return ('special', tuple(((v + 9 + (1 << 31)) % (1 << 32)) - (1 << 31)
                                 for v in (entry['unk7_0'], entry['unk7_2']) if v >= 0))
    return ('variant', (variant_index(entry),))


def image_reference(entry):
    """Exact static medal texture branch of 5D3724; not a runtime scene."""
    kind, index = entry['medal_type'], variant_index(entry)
    code = entry['char_id']
    if not code or not code.isascii() or any(c in code for c in '/\\:') or '..' in code:
        return None
    # Native 3BFCBC has two six-character exceptions; otherwise first four bytes.
    stem = {'6pci02': '6pci2', '7dio02': '7dio2'}.get(code, code[:4])
    if kind == 1 and 0 <= index < 5:
        return (f'data/ui/customize/img_costume/medal_img_costume_{stem}.xfbin',
                f'medal_img_costume_{stem}_normal_{index + 3}p')
    if kind == 2 and 0 <= index < 7:
        # DLC uses a runtime character-number exception. Do not guess that
        # registry's number from a code or substitute another costume's image.
        if entry['unlock_condition'] == 3:
            return None
        return (f'data/ui/customize/img_costume/medal_img_costume_{stem}.xfbin',
                f'medal_img_costume_{stem}_{chr(97 + index)}')
    if kind in (3, 4) and 0 <= index < 5:
        prefix = 'provocation' if kind == 3 else 'victory'
        return (f'data/ui/customize/img_medal/customize_image_{stem}.xfbin',
                f'medal_img_{prefix}_{stem}_{chr(97 + index)}')
    if kind in (5, 7, 9, 10):
        name = 'medal_img_gion' if kind == 5 else 'medal_img_word'
        return (f'data/ui/customize/img_medal/{name}.xfbin', name)
    return None


def data_root(filepath, configured=''):
    if filepath:
        for parent in Path(filepath).resolve().parents:
            if (parent / 'ui/customize').is_dir():
                return parent
    if configured:
        for root in (Path(configured), Path(configured) / 'data'):
            if (root / 'ui/customize').is_dir():
                return root.resolve()
    return None
