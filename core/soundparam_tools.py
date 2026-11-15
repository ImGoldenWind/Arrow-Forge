"""Sound-table semantics and resource inspection, independent of Qt.

Native reference: 5C6174/5C63E0/5C66A8, 5C77A8, 5C7BFC.
No acoustic or timing simulation is inferred from these routing tables.
"""
import math
import struct
from pathlib import Path
from collections import defaultdict

from parsers.sndcmnparam_parser import SCHEMAS, encode_string
from core.translations import ui_text
from core.story_tools import character_name

RELATED_KEYS = ('stand_index', 'unk2', 'unk3')


def fields(kind):
    _, strings, numbers = SCHEMAS[kind]
    return tuple(key for _, key, _ in (*strings, *numbers))


def display(value):
    if isinstance(value, float):
        return format(value, '.9g')
    return str(value)


def parse_field(kind, key, text, entry):
    _, strings, numbers = SCHEMAS[kind]
    for _, name, width in strings:
        if name == key:
            if text != entry[key]:
                encode_string(text, width)
            return text
    fmt = next(fmt for _, name, fmt in numbers if name == key)
    if fmt == 'H':
        value = int(text, 16 if text.lower().startswith('0x') else 10)
        if not 0 <= value <= 65535:
            raise ValueError('Expected u16.')
        return value
    # Untouched unusual values are preserved by the codec.
    if text == display(entry[key]):
        return entry[key]
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('Expected finite float32.')
    return struct.unpack('<f', struct.pack('<f', value))[0]


def native_int(value):
    """CVTTSS2SI used by the reference loaders, including its indefinite result."""
    if not math.isfinite(value) or not -2147483648 <= math.trunc(value) <= 2147483647:
        return -2147483648
    return math.trunc(value)


def related_entry(section, value):
    index = native_int(value)
    return (index, section['entries'][index]) if 0 <= index < min(111, len(section['entries'])) else None


def data_root(filepath, configured=''):
    if filepath:
        for parent in Path(filepath).resolve().parents:
            if (parent / 'sound').is_dir():
                return parent
    if configured:
        for candidate in (Path(configured), Path(configured) / 'data'):
            if (candidate / 'sound').is_dir():
                return candidate.resolve()
    return None


def asset_inventory(root):
    """Names/paths only: no decoding hundreds of audio banks on the UI thread."""
    if root is None:
        return ()
    return tuple(sorted((p.relative_to(root).as_posix() for p in (root / 'sound').rglob('*')
                         if p.is_file() and p.suffix.lower() in ('.xfbin', '.acf', '.acb', '.awb')), key=str.casefold))


def index_assets(inventory):
    result = defaultdict(list)
    for reference in inventory:
        path = Path(reference)
        result[path.name.casefold()].append(reference)
        result[path.stem.casefold()].append(reference)
    return {key: tuple(dict.fromkeys(values)) for key, values in result.items()}


def resource_matches(value, index):
    # Inventory inspection, not an assertion about active engine bank dispatch.
    if not value or 'NULL' in value:
        return ()
    return index.get(value.casefold(), ())


def choices(kind, key, sections, inventory):
    if kind == 'pldata' and key in RELATED_KEYS:
        section = next((s for s in sections if s['type'] == 'pldata'), None)
        return [('-1', ui_text('soundparam_no_relation'))] + [
            (str(i), f"{i} — {character_name(e['char_id'])} · {e['char_id']}")
            for i, e in enumerate(section['entries'][:111])]
    _, strings, _ = SCHEMAS[kind]
    widths = {name: width for _, name, width in strings}
    if key not in widths:
        return None
    values = {e[key] for s in sections if s['type'] == kind for e in s['entries'] if e[key]}
    if key not in ('char_id', 'audio_id'):
        values.add('NULL')
        for reference in inventory:
            path = Path(reference)
            candidate = path.name if kind == 'cridata' else path.stem
            try:
                encode_string(candidate, widths[key])
            except (ValueError, UnicodeError):
                continue
            if kind == 'cridata':
                if path.suffix.lower() in ('.acf', '.acb', '.awb'):
                    values.add(path.name)
            elif path.suffix.lower() == '.xfbin':
                values.add(path.stem)
    return [(value, f'{character_name(value)} · {value}' if key == 'char_id'
             and character_name(value) != value else value) for value in sorted(values, key=str.casefold)]


def make_default(kind):
    _, strings, numbers = SCHEMAS[kind]
    entry = {key: '' for _, key, _ in strings}
    entry.update({key: -1.0 if fmt == 'f' else 65535 for _, key, fmt in numbers})
    entry['idx'] = 0
    return entry


def issues(section, entry):
    result = []
    if section['type'] == 'pldata':
        for key in RELATED_KEYS:
            if native_int(entry[key]) != -1 and related_entry(section, entry[key]) is None:
                result.append(ui_text('soundparam_bad_relation', field=caption(key), value=display(entry[key])))
    for _, key, fmt in SCHEMAS[section['type']][2]:
        if fmt == 'f' and entry[key] != native_int(entry[key]):
            result.append(ui_text('soundparam_truncation', field=caption(key), value=native_int(entry[key])))
    identity = {'sndcmnparam': 'audio_id', 'pldata': 'char_id', 'cridata': 'str0'}[section['type']]
    if entry[identity] and sum(e[identity] == entry[identity] for e in section['entries']) > 1:
        result.append(ui_text('soundparam_duplicate_name'))
    return result


def caption(key):
    if key == 'audio_id':
        return ui_text('skill_operand_sound_id')
    return ui_text('soundparam_field_' + key)
