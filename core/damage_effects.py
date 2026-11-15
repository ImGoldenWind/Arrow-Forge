"""Damage-effect catalog discovery and file-derived captions (no guessed enums)."""
from pathlib import Path
import re


EFFECT_KEYS = ('eff_a', 'eff_b', 'eff_c', 'eff_d', 'eff_e')
_CAPTION_WORDS = frozenset(('hit slash ripple ice fire damage guard vector stand end rush start '
                          'offset throw cancel counter simble symbol stylish move break invincible '
                          'smoke sparkhit flame charge impact').split())


def effectprm_candidates(damage_path, game_dir=''):
    """Prefer this file's catalog, then the configured extracted-data tree.

    Never walk unrelated ancestors (Documents, a drive root, etc.). The explicit
    game-files root is the only recursive fallback. No game-specific user paths.
    """
    seen = set()

    def candidate(path):
        key = str(path.resolve()).casefold()
        if key not in seen and path.is_file():
            seen.add(key)
            return path
        return None

    parent = Path(damage_path).resolve().parent
    for path in (parent / 'effectprm.bin.xfbin',
                 parent / 'spc' / 'effectprm.bin.xfbin',
                 parent / 'data' / 'spc' / 'effectprm.bin.xfbin'):
        found = candidate(path)
        if found:
            yield found
    if not game_dir:
        return
    root = Path(game_dir).expanduser()
    if not root.is_dir():
        return
    for path in (root / 'effectprm.bin.xfbin', root / 'spc' / 'effectprm.bin.xfbin',
                 root / 'data' / 'spc' / 'effectprm.bin.xfbin'):
        found = candidate(path)
        if found:
            yield found
    for path in sorted(root.rglob('effectprm.bin.xfbin')):
        found = candidate(path)
        if found:
            yield found


def effect_caption(name, tr):
    """Readable asset spelling; exact authored name remains visible separately."""
    if not name:
        return tr('dme_empty_effect')
    words = name.split('_')
    if words[0] == 'ecmn':
        words.pop(0)
    prefix = ''
    if words and re.fullmatch(r'\d[a-z]+\d+', words[0]):
        prefix = words.pop(0) + ' · '
    words = [w for w in words if w not in ('common', 'eff')]
    result = []
    for word in words:
        match = re.fullmatch(r'([a-z]+)(\d*)', word)
        if not match:
            result.append(word)
            continue
        token, number = match.groups()
        key = 'dme_word_' + token
        translated = tr(key) if token in _CAPTION_WORDS else token.capitalize()
        result.append((token.capitalize() if translated == key else translated)
                      + (' ' + number if number else ''))
    return prefix + ' '.join(result)
