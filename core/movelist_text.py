"""Read-only Move List text lookup. Never writes translated text to game data."""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import re
import struct

from core.runtime_paths import app_path
from parsers.messageinfo_parser import crc32_of, parse_messageinfo_xfbin


LANGUAGES = {'en': 'eng', 'ru': 'rus', 'ja': 'jpn', 'de': 'ger',
             'fr': 'fre', 'it': 'ita', 'es': 'spa', 'ko': 'kor',
             'zh': 'chs', 'zh-TW': 'cht'}
ICONS = {'arr_l': '←', 'arr_r': '→', 'arr_u': '↑', 'arr_d': '↓',
         'arr_lu': '↖', 'arr_ru': '↗', 'arr_ld': '↙', 'arr_rd': '↘',
         'plus': '+', 'btn_L': '[L]', 'btn_M': '[M]', 'btn_H': '[H]',
         'btn_S': '[S]', 'btn_G': '[GHA]', 'btn_T': '[Throw]', 'btn_B': '[Assist]'}


@lru_cache(maxsize=64)
def _table(path, stamp, size):
    _, _, rows = parse_messageinfo_xfbin(path)
    return {row['crc32_id']: row for row in rows}


@lru_cache(maxsize=1)
def _russian_names():
    try:
        return json.loads(Path(app_path('resources', 'movelist_names_ru.json')).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def name_fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class MoveListText:
    def __init__(self, file_path='', language='en', game_root=''):
        self.language = language
        self.tables = {}
        roots = []
        if file_path:
            roots.extend(list(Path(file_path).resolve().parents)[:5])
        if game_root:
            roots.extend((Path(game_root), Path(game_root) / 'data'))
        for lang in dict.fromkeys((LANGUAGES.get(language, language), 'eng', 'jpn')):
            for root in dict.fromkeys(roots):
                directory = root / 'message' / 'WIN64' / lang
                # Updates are complete/partial message tables too. The base
                # English table, for example, has no TermList messages.
                updates = sorted(
                    (p for p in directory.glob('message_DLC*.bin.xfbin')
                     if re.fullmatch(r'message_DLC\d+\.bin\.xfbin', p.name)),
                    key=lambda p: int(re.search(r'DLC(\d+)', p.name)[1]),
                )
                merged = {}
                found = False
                for path in [directory / 'messageInfo.bin.xfbin', *updates]:
                    try:
                        stat = path.stat()
                        merged.update(_table(str(path), stat.st_mtime_ns, stat.st_size))
                        found = True
                    except (OSError, ValueError, IndexError, struct.error):
                        continue
                if found:
                    self.tables[lang] = merged
                    break

    def _resolve(self, key, table, seen=()):
        ident = crc32_of(key) if isinstance(key, str) else key
        if ident in seen or len(seen) >= 24:
            return ''
        row = table.get(ident)
        if not row:
            return ''
        seen = (*seen, ident)
        if row.get('is_ref') == 1:
            return self._resolve(row['ref_crc32'], table, seen)
        text = row.get('message', '')
        text = re.sub(r'<text\s+([^\s/>]+)[^>]*?/?>',
                      lambda m: self._resolve(m[1], table, seen) or '[' + m[1] + ']', text)
        text = re.sub(r'<icon\s+([^\s/>]+)[^>]*>',
                      lambda m: ICONS.get(m[1], '[' + m[1] + ']'), text)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
        text = re.sub(r'</?(?:color|size|font|ruby)\b[^>]*>', '', text)
        return text.replace('\\n', '\n').strip()

    def text(self, key, *, name=False, japanese=False):
        if not key:
            return '', ''
        langs = ('jpn',) if japanese else tuple(dict.fromkeys((LANGUAGES.get(self.language, self.language), 'eng', 'jpn')))
        for lang in langs:
            value = self._resolve(key, self.tables.get(lang, {}))
            if value:
                if name and self.language == 'ru' and lang in ('eng', 'jpn') and not japanese:
                    translated = _russian_names().get(name_fingerprint(value))
                    if translated:
                        return translated, 'ru'
                return value, lang
        return '', ''

    def name(self, entry):
        return self.text(entry.get('name_key', ''), name=True)[0] or entry.get('name_key', '')
