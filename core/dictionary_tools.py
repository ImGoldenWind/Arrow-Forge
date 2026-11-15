"""Dictionary semantics and validation, independent of Qt.

Native evidence and the limits of category/unlock interpretation are documented
in docs/dictionary-research.md. Storage limits are never gameplay slider ranges.
"""
from functools import lru_cache
from pathlib import Path
import struct

from core.translations import ui_text
from parsers.dictionaryparam_parser import NUMERIC_FIELDS, STRING_FIELDS, _encoded

CATEGORY_KEYS = tuple(f'flag{i}' for i in range(1, 9)) + ('pad1',)
UNRESOLVED_KEYS = ('pad2', 'pad3', 'pad4', 'flag13', 'flag14', 'flag15',
                   'pad5', 'pad6', 'pad7', 'flag19')
LOADER_SKIPPED_KEYS = ('pad8', 'res1', 'index_padding')
SHARED_GALLERY_KEYS = ('dmy', 'const1', 'padding', 'availability_message1', 'availability_message2')
OFFSETS = {key: off for off, key in (*STRING_FIELDS, *NUMERIC_FIELDS)}
STRING_KEYS = frozenset(key for _, key in STRING_FIELDS)
UINT32_MAX = (1 << 32) - 1
SAVE_SLOT_COUNT = 4096  # Native 5FD7AC / 5FCF74 visit exactly 0x1000 slots.


def parse_field(key, text):
    if key in STRING_KEYS:
        _encoded(text)
        return text  # Significant spaces are part of a reference.
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    if key == 'padding' and -(1 << 31) <= value < 0:
        value &= UINT32_MAX  # Native shared-shop price checks are signed i32.
    if not 0 <= value <= UINT32_MAX:
        raise ValueError('outside uint32 storage range')
    return value


def category_label(key):
    number = CATEGORY_KEYS.index(key) + 1
    return (ui_text(f'ui_charviewer_part_{number}') if number <= 8 else
            ui_text('char_0bao01'))  # All three stock members are Baoh terms.


def categories(entry):
    # Native 4C5624 tests the whole word for nonzero, not a bit or equality to 1.
    return tuple(key for key in CATEGORY_KEYS if entry[key] != 0)


def unlock_choices(entries):
    names = {1: ui_text('cv_unlock_flag', mask='0x01'),
             2: ui_text('cv_unlock_flag', mask='0x40'),
             3: ui_text('ui_charviewer_3_dlc_unlock'),
             4: ui_text('cv_unlock_flag', mask='0x20')}
    return [(v, f'{v} — {names.get(v, ui_text("cv_unlock_other"))}')
            for v in sorted({0, *names, *(e['no_panel'] for e in entries)})]


def next_identity(entries):
    indices = {e['index'] for e in entries}
    index = next((i for i in range(SAVE_SLOT_COUNT) if i not in indices), None)
    if index is None:
        raise ValueError('No free native glossary save slot.')
    ids = {e['char_id'] for e in entries}
    number = 1
    while f'DIC_ID_DMY_{number}' in ids:
        number += 1
    return index, f'DIC_ID_DMY_{number}'


def stored_caption(key):
    names = {'dmy': 'dictionary_associated_character', 'const1': 'dictionary_shop_precheck',
             'padding': 'dictionary_gallery_price', 'availability_message1': 'dictionary_shared_name',
             'availability_message2': 'dictionary_shared_description'}
    return ui_text(names[key])


def stored_hint(key):
    names = {'dmy': 'dictionary_associated_character_hint', 'const1': 'dictionary_shop_precheck_hint',
             'padding': 'dictionary_gallery_price_hint',
             'availability_message1': 'dictionary_shared_message_hint',
             'availability_message2': 'dictionary_shared_message_hint'}
    return ui_text(names[key])


def stored_choices(key, entries, characters):
    if key == 'dmy':
        from core.story_tools import character_name
        return [(code, f'{code} — {character_name(code)}' if code in characters else code)
                for code in sorted(set(characters) | {e[key] for e in entries})]
    if key == 'const1':
        names = {0: ui_text('dictionary_shop_common_check'), 1: ui_text('dictionary_shop_extra_check')}
        return [(value, f'{value} — {names[value]}' if value in names else str(value))
                for value in sorted({0, 1, *(e[key] for e in entries)})]
    if key == 'padding':
        return [(value, ui_text('dictionary_price_negative_one') if value == UINT32_MAX else
                 str(value if value < 1 << 31 else value - (1 << 32)))
                for value in sorted({0, UINT32_MAX, *(e[key] for e in entries)})]
    return None


def _local_catalog_path(filepath, configured, relative):
    roots = list(Path(filepath).resolve().parents)[:5] if filepath else []
    if configured:
        roots.extend((Path(configured), Path(configured) / 'data'))
    return next((root / relative for root in dict.fromkeys(roots) if (root / relative).is_file()), None)


@lru_cache(maxsize=8)
def _character_catalog(path, stamp, size):
    from parsers.characode_parser import parse_characode_xfbin
    _, rows, _ = parse_characode_xfbin(path)
    return frozenset(row['char_code'] for row in rows)


def character_catalog(filepath, configured=''):
    path = _local_catalog_path(filepath, configured, 'spc/characode.bin.xfbin')
    if path is None:
        return frozenset(), ''
    try:
        stat = path.stat()
        return _character_catalog(str(path), stat.st_mtime_ns, stat.st_size), ''
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        return frozenset(), str(error)


@lru_cache(maxsize=8)
def _panel_catalog(path, stamp, size):
    from parsers.mainmodeparam_parser import parse_mainmodeparam
    _, result = parse_mainmodeparam(path)
    return result['panels']


def panel_catalog(filepath, configured=''):
    """Nearest extracted tree wins; never scan the installation recursively."""
    path = _local_catalog_path(filepath, configured, 'param/main_mode/MainModeParam.bin.xfbin')
    if path is None:
        return {}, ''
    try:
        stat = path.stat()
        from core.story_tools import panel_title
        rows = _panel_catalog(str(path), stat.st_mtime_ns, stat.st_size)
        return {row['ptr_panel_id']: panel_title(row) for row in rows}, ''
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        return {}, str(error)


def entry_issues(entry, entries, panels):
    issues = []
    if not entry['char_id']:
        issues.append(ui_text('dictionary_missing_id'))
    if sum(e['char_id'] == entry['char_id'] for e in entries) > 1:
        issues.append(ui_text('dictionary_duplicate_id'))
    if sum(e['index'] == entry['index'] for e in entries) > 1:
        issues.append(ui_text('dictionary_duplicate_index'))
    if entry['index'] >= 1 << 31:
        issues.append(ui_text('dictionary_signed_index'))
    if entry['index'] >= SAVE_SLOT_COUNT:
        issues.append(ui_text('dictionary_index_capacity', maximum=SAVE_SLOT_COUNT - 1))
    if not categories(entry):
        issues.append(ui_text('dictionary_no_category'))
    if panels and entry['panel'] and entry['panel'] not in panels:
        issues.append(ui_text('dictionary_missing_panel'))
    return issues
