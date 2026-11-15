"""Player Title semantics, validation and resource references, independent of Qt.

Evidence and limits: docs/player-title-research.md. Ranges describe storage;
the fixed save catalog is a separately verified native limit.
"""
from pathlib import Path

from core.story_tools import character_name
from core.gallery_tools import part_name
from core.translations import ui_text
from parsers.playertitleparam_parser import _INT_FIELDS, _STR_KEYS, _encoded

INTEGER_RANGES = {key: (-(1 << 31), (1 << 31) - 1) if fmt == 'i' else (0, (1 << 32) - 1)
                  for _, key, fmt in _INT_FIELDS}
MESSAGE_KEYS = ('card_string1', 'card_string2')
SAVE_SLOT_COUNT = 0x400  # Native 5F9C50 reconciles 1024 Player Title slots.


def parse_field(key, text):
    if key in _STR_KEYS:
        _encoded(text)
        return text
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    low, high = INTEGER_RANGES[key]
    if not low <= value <= high:
        raise ValueError('outside storage range')
    return value


def access_name(value):
    if value in (1, 2, 4):
        return ui_text('cv_unlock_flag', mask={1: '0x01', 2: '0x40', 4: '0x20'}[value])
    return ui_text('title_dlc_marker') if value == 3 else ui_text('title_access_raw', value=value)


def data_root(filepath, configured=''):
    if filepath:
        for parent in Path(filepath).resolve().parents:
            if (parent / 'ui/playerCard').is_dir():
                return parent
    if configured:
        for root in (Path(configured), Path(configured) / 'data'):
            if (root / 'ui/playerCard').is_dir():
                return root.resolve()
    return None


def background_reference(value):
    # Native 51497C / 5149D4 format these exact strings from file +08.
    if not value or not value.isascii() or any(c in value for c in '/\\:\0') or '..' in value:
        return None
    return (f'data/ui/playerCard/char_plate/playercard_bg_{value}.xfbin',
            f'playercard_bg_{value}')


def choices(key, entries, characters=(), root=None):
    values = {entry[key] for entry in entries}
    if key == 'part':
        names = {v: part_name(v) for v in range(9)}
    elif key == 'unlock_cond':
        names = {v: access_name(v) for v in range(7)}
    elif key == 'chara_code':
        return [(v, f'{character_name(v)} · {v}' if v else ui_text('title_no_character'))
                for v in sorted(values | set(characters) | {''})]
    elif key == 'anim_id':
        if root is not None:
            directory = root / 'ui/playerCard/char_plate'
            values.update(p.stem.removeprefix('playercard_bg_')
                          for p in directory.glob('playercard_bg_*.xfbin'))
        return [(v, v) for v in sorted(values)]
    elif key in ('dlc_id', 'patch', *MESSAGE_KEYS):
        return [(v, str(v)) for v in sorted(values)]
    else:
        return None
    return [(v, f'{v} — {names[v]}' if v in names else str(v)) for v in sorted(values | names.keys())]


def next_identity(entries):
    used = {entry['index'] for entry in entries}
    index = next((n for n in range(1, SAVE_SLOT_COUNT) if n not in used), None)
    if index is None:
        raise ValueError(ui_text('title_no_slots'))
    ids = {entry['title_id'] for entry in entries}
    number = index
    while f'PLCARD_TITLE_{number:03d}' in ids:
        number += 1
    return index, f'PLCARD_TITLE_{number:03d}'


def entry_issues(entry, entries, current):
    issues = []
    if not entry['title_id']:
        issues.append(ui_text('title_empty_id'))
    for key in ('title_id', 'index'):
        if any(other is not current and other[key] == entry[key] for other in entries):
            issues.append(ui_text('gallery_duplicate', field=ui_text('title_' + key)))
    if entry['index'] >= SAVE_SLOT_COUNT:
        issues.append(ui_text('title_index_limit', maximum=SAVE_SLOT_COUNT - 1))
    if not entry['card_string1']:
        issues.append(ui_text('title_empty_text'))
    if background_reference(entry['anim_id']) is None:
        issues.append(ui_text('title_background_unavailable'))
    return issues
