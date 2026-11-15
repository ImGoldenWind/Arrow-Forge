"""Presentation and structural checks for the XML-backed Move List editor."""
from functools import lru_cache
from pathlib import Path
import json
import re

from core.movelist_text import MoveListText, name_fingerprint
from core.runtime_paths import app_path
from core.settings import load_settings
from core.translations import current_language, ui_text


# Exact stored trigger codes, not a freely composable mask. Native 3A86F0.
TRIGGERS = {0: 'none', 512: 'L', 1024: 'M', 2048: 'H', 4096: 'sidestep',
            8192: 'S', 32768: 'two', 65536: 'three', 262144: 'attack',
            524288: 'attack_style'}
ACTION_LIMITS = {'spm': 45, 'nmm': 15, 'hha': 10}  # native 3723B4


@lru_cache(maxsize=1)
def _name_catalog():
    return json.loads(Path(app_path('resources', 'spm_name_catalog.json')).read_text(encoding='utf-8'))


class SpmNames:
    def __init__(self, file_path='', language=None):
        self.language = language or current_language()
        self.messages = MoveListText(file_path, self.language, load_settings().get('game_files_dir', ''))

    def display(self, name):
        entry = _name_catalog().get(name_fingerprint(name))
        if not entry or self.language not in ('en', 'ru'):
            return name
        base = ''
        if entry.get('key'):
            base = self.messages.text(entry['key'], name=True)[0]
        base = base or entry.get(self.language, '')
        if not base:
            return name
        def annotation(value):
            value = re.sub(r'[\[\]()「」『』]', ' ', value)
            return re.sub(r'\s+', ' ', value).strip(' _!:')
        prefix = annotation(entry.get('prefix_' + self.language, ''))
        suffix = annotation(entry.get('suffix_' + self.language, ''))
        return ' · '.join(part for part in (prefix, base, suffix) if part)


def field_label(attr):
    key = 'spm_field_' + attr
    value = ui_text(key)
    return value if value != key else attr


def trigger_label(value):
    try:
        kind = TRIGGERS.get(int(value))
    except ValueError:
        kind = None
    if kind in ('L', 'M', 'H', 'S'):
        return kind
    return ui_text('spm_trigger_' + kind) if kind else str(value)


def command_preview(command):
    arrows = {'1': '↙', '2': '↓', '3': '↘', '4': '←', '5': '●',
              '6': '→', '7': '↖', '8': '↑', '9': '↗'}
    sequence = ' '.join(arrows.get(e.get('key'), e.get('key', '?')) for e in command.findall('ComElement'))
    return (sequence + ' + ' if sequence else '') + trigger_label(command.get('trigger', '0'))


def next_action_id(moves, kind):
    used = {m['actID'] for m in moves if m['actKind'] == kind}
    limit = ACTION_LIMITS.get(kind)
    if limit is None:
        return None
    return next((str(i) for i in range(1, limit + 1) if str(i) not in used), None)


def validate_spm(root):
    """Return structural/native-limit issues without changing the XML."""
    issues = []
    identities = set()
    for elem in root:
        if elem.tag != 'SpecialMove':
            continue
        key = (elem.get('actID', ''), elem.get('actKind', ''))
        if key in identities:
            issues.append(ui_text('spm_duplicate_id', id=key[0], kind=key[1]))
        identities.add(key)
        limit = ACTION_LIMITS.get(key[1])
        if limit is not None:
            try:
                valid = 1 <= int(key[0]) <= limit
            except ValueError:
                valid = False
            if not valid:
                issues.append(ui_text('spm_action_limit', kind=key[1], limit=limit))
    return issues
