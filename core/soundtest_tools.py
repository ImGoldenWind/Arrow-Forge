"""Sound Test semantics and validation, independent of the Qt form.

Native evidence: docs/sound-test-research.md. Storage ranges are not game limits.
"""
from core.translations import ui_text
from core.story_tools import character_name
from parsers.soundtestparam_parser import _STR_KEYS, _INT_FIELDS, _encoded

INTEGER_RANGES = {key: (-(1 << 31), (1 << 31) - 1) if fmt == 'i' else (0, (1 << 32) - 1)
                  for _, key, fmt in _INT_FIELDS}
MESSAGE_KEYS = ('sound_str1', 'sound_str2')
BGM_SAVE_SLOTS = 128  # Native 5FD444 initializes and 5FDBB8 reconciles 0x80 slots.


def parse_field(key, text):
    if key in _STR_KEYS:
        _encoded(text)
        return text
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    low, high = INTEGER_RANGES[key]
    if not low <= value <= high:
        raise ValueError('outside storage range')
    return value


def category(entry):
    # Loader 4D597E routes exactly 1 to voices; every other value to BGM.
    return int(entry['entry_type'] == 1)


def category_name(value):
    return ui_text('soundtest_voice' if value == 1 else 'soundtest_music')


def part_name(value):
    return ui_text('ui_galleryartparam_no_part_special') if value == 0 else (
        ui_text(f'part_{value}') if 1 <= value <= 8 else str(value))


def choices(key, entries, characters=()):
    values = {e[key] for e in entries}
    if key == 'entry_type':
        names = {0: category_name(0), 1: category_name(1)}
    elif key == 'part':
        names = {v: part_name(v) for v in range(9)}
    elif key == 'unlock_cond':
        names = {1: ui_text('cv_unlock_flag', mask='0x01'),
                 2: ui_text('cv_unlock_flag', mask='0x40'),
                 3: ui_text('ui_charviewer_3_dlc_unlock'),
                 4: ui_text('cv_unlock_flag', mask='0x20'),
                 5: ui_text('soundtest_shop_type'), 6: ui_text('soundtest_type6')}
    elif key == 'menu_index':
        names = {0: ui_text('gallery_precheck_off'), 1: ui_text('gallery_precheck_on')}
        return [(v, names.get(v, str(v))) for v in sorted(values | names.keys())]
    elif key == 'chara_code':
        values.update(characters)
        return [(v, f'{v} — {character_name(v)}' if character_name(v) != v else v)
                for v in sorted(values)]
    elif key in ('dlc_id', 'patch', *MESSAGE_KEYS):
        return [(v, str(v)) for v in sorted(values)]
    else:
        return None
    return [(v, f'{v} — {names[v]}' if v in names else str(v)) for v in sorted(values | names.keys())]


def next_identity(entries, template):
    # Separate native BGM/voice lookup maps. Do not renumber existing identities.
    used = {e['index'] for e in entries if category(e) == category(template)}
    index = 0
    while index in used:
        index += 1
    if not category(template) and index >= BGM_SAVE_SLOTS:
        raise ValueError(ui_text('soundtest_no_bgm_slots'))
    ids = {e['bgm_id'] for e in entries}
    prefix = 'ST_VOICE_' if category(template) else 'ST_BGM_'
    number = index
    while f'{prefix}{number:03d}' in ids:
        number += 1
    return index, f'{prefix}{number:03d}'


def entry_issues(entry, entries, current):
    issues = []
    if not entry['bgm_id']:
        issues.append(ui_text('soundtest_empty_id'))
    for key in ('bgm_id', 'index'):
        if any(e is not current and e[key] == entry[key] and
               (key == 'bgm_id' or category(e) == category(entry)) for e in entries):
            issues.append(ui_text('gallery_duplicate', field=ui_text('soundtest_' + key)))
    if entry['index'] >= (1 << 31):
        issues.append(ui_text('soundtest_negative_index'))
    if not category(entry) and entry['index'] >= BGM_SAVE_SLOTS:
        issues.append(ui_text('soundtest_bgm_capacity', maximum=BGM_SAVE_SLOTS - 1))
    if entry['entry_type'] not in (0, 1):
        issues.append(ui_text('soundtest_custom_type'))
    if entry['unlock_cond'] in (1, 5) and entry['price'] <= 0 and not category(entry):
        issues.append(ui_text('gallery_nonpositive_price'))
    if entry['native_flag'] not in (0, 1):
        issues.append(ui_text('soundtest_custom_flag'))
    return issues
