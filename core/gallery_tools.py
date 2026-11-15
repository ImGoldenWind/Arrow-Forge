"""Gallery Art semantics, storage validation and read-only resource resolution."""
from functools import lru_cache
from pathlib import Path, PurePosixPath
import struct

from core.translations import current_language, ui_text
from parsers.galleryartparam_parser import _INT_FIELDS, _STR_KEYS, _encoded

INTEGER_RANGES = {key: (-(1 << 31), (1 << 31) - 1) if fmt == 'i' else (0, (1 << 32) - 1)
                  for _, key, fmt in _INT_FIELDS}
SAVE_SLOT_COUNT = 256  # Original 5FCBE8 and 5FDA84 iterate 0x100 art slots.
MESSAGE_KEYS = ('art_string1', 'art_string2')


def parse_field(key, text):
    if key in _STR_KEYS:
        _encoded(text)
        return text
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    low, high = INTEGER_RANGES[key]
    if not low <= value <= high:
        raise ValueError('outside storage range')
    return value


def part_name(value):
    keys = ('no_part_special', 'phantom_blood', 'battle_tendency', 'stardust_crusaders',
            'diamond_is_unbreakable', 'golden_wind', 'stone_ocean', 'steel_ball_run', 'jojolion')
    return ui_text('ui_galleryartparam_' + keys[value]) if 0 <= value < len(keys) else str(value)


def unlock_choices(entries):
    names = {1: ui_text('gallery_unlock_shop'), 2: ui_text('cv_unlock_flag', mask='0x40'),
             3: ui_text('gallery_unlock_dlc'), 4: ui_text('cv_unlock_flag', mask='0x20'),
             5: ui_text('gallery_unlock_shop_other'), 6: ui_text('gallery_unlock_content')}
    return [(value, f'{value} — {names.get(value, ui_text("cv_unlock_other"))}')
            for value in sorted({*names, *(e['unlock_cond'] for e in entries)})]


def next_identity(entries):
    used = {e['index'] for e in entries}
    index = next((n for n in range(SAVE_SLOT_COUNT) if n not in used), None)
    if index is None:
        raise ValueError(ui_text('gallery_no_slots'))
    names = {e['art_id'] for e in entries}
    n = index + 1
    while f'ID_ART_{n:03d}' in names:
        n += 1
    return index, f'ID_ART_{n:03d}'


def entry_issues(entry, entries, current):
    issues = []
    if not entry['art_id']:
        issues.append(ui_text('gallery_empty_id'))
    others = [e for e in entries if e is not current]
    for key in ('art_id', 'index'):
        if any(e[key] == entry[key] for e in others):
            issues.append(ui_text('gallery_duplicate', field=ui_text('gallery_' + key)))
    if entry['index'] >= SAVE_SLOT_COUNT:
        issues.append(ui_text('gallery_index_limit', maximum=SAVE_SLOT_COUNT - 1))
    if entry['unlock_cond'] in (1, 5) and entry['price'] <= 0:
        issues.append(ui_text('gallery_nonpositive_price'))
    if not entry['art_path'] or not entry['art_name']:
        issues.append(ui_text('gallery_no_image'))
    return issues


def data_root(filepath, configured=''):
    if filepath:
        for parent in Path(filepath).resolve().parents:
            if (parent / 'ui' / 'gallery').is_dir():
                return parent
    if configured:
        for candidate in (Path(configured), Path(configured) / 'data'):
            if (candidate / 'ui' / 'gallery').is_dir():
                return candidate.resolve()
    return None


def resource_path(root, reference, language=None):
    if root is None or not reference:
        return None
    relative = PurePosixPath(reference.replace('\\', '/'))
    if relative.is_absolute() or '..' in relative.parts or ':' in reference:
        raise ValueError(ui_text('gallery_unsafe_path'))
    parts = relative.parts[1:] if relative.parts and relative.parts[0].lower() == 'data' else relative.parts
    if 'LANG' in parts:
        from core.movelist_text import LANGUAGES
        language = current_language() if language is None else language
        preferred = LANGUAGES.get(language, language if language in LANGUAGES.values() else 'eng')
        # Inspection policy, not a claim about the game's missing-file fallback.
        # The UI always reports the resolved path, including the chosen language.
        for code in dict.fromkeys((preferred, 'eng', 'jpn')):
            candidate = (root / Path(*(code if part == 'LANG' else part for part in parts))).resolve()
            if not candidate.is_relative_to(root.resolve()):
                raise ValueError(ui_text('gallery_unsafe_path'))
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(ui_text('gallery_language_missing', path=reference))
    path = (root / Path(*parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(ui_text('gallery_unsafe_path'))
    return path


@lru_cache(maxsize=2)
def _bundle(path, stamp, size):
    if size > 128 * 1024 * 1024:
        raise ValueError(ui_text('gallery_asset_too_large'))
    from parsers.xfbin_lib import read_xfbin
    return read_xfbin(path)


@lru_cache(maxsize=8)
def _image(path, stamp, size, name):
    from parsers.texture_xfbin_parser import _chunk_to_entry
    from parsers.xfbin_lib import NuccChunkTexture, NuccChunkBinary
    bundle = _bundle(path, stamp, size)
    textures = [(i, c) for i, page in enumerate(bundle.pages) for c in page.chunks
                if isinstance(c, (NuccChunkTexture, NuccChunkBinary))]
    names = tuple(dict.fromkeys(c.name for _, c in textures))
    matches = [(i, c) for i, c in textures if c.name == name]
    if len(matches) != 1:
        return None, names, ui_text('gallery_texture_missing', name=name)
    i, chunk = matches[0]
    width = height = 0
    if isinstance(chunk, NuccChunkTexture) and chunk.nut and chunk.nut.textures:
        texture = chunk.nut.textures[0]
        width, height = texture.width, texture.height
    elif isinstance(chunk, NuccChunkBinary):
        data = getattr(chunk, 'binary_data', b'')
        if data[:4] == b'DDS ' and len(data) >= 20:
            height, width = struct.unpack_from('<II', data, 12)
        elif data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
            width, height = struct.unpack_from('>II', data, 16)
    if width * height > 16 * 1024 * 1024:
        raise ValueError(ui_text('gallery_asset_too_large'))
    entry = _chunk_to_entry(chunk, i)
    if entry is None or entry.pil_image is None:
        return None, names, ui_text('gallery_decode_failed')
    return entry.pil_image, names, ''


def load_image(root, reference, name, language=None):
    if root is not None and not reference:
        return None, (), ui_text('gallery_no_image')
    path = resource_path(root, reference, language)
    if path is None:
        return None, (), ui_text('gallery_resources_missing')
    stat = path.stat()
    return _image(str(path), stat.st_mtime_ns, stat.st_size, name)


def path_choices(root, entries, key):
    values = {e[key] for e in entries if e[key]}
    if root is not None:
        directory = root / 'ui/gallery/art' / ('icon' if key == 'icon_path' else 'img')
        values.update('data/' + p.relative_to(root).as_posix() for p in directory.glob('*.xfbin'))
    return tuple((v, v) for v in sorted(values))
