"""CPU editor presentation and file-scoped symbol lookup (no game writes)."""
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

from parsers.cpu_parser import parse_cpu_xfbin, NUMERIC_FIELDS
from core.spm_tools import SpmNames


TOKEN_SECTIONS = {'Cond': 'ConditionDefine', 'Action': 'ActionDefine',
                  'Status': 'StatusDefine', 'Combo': 'ComboCondition',
                  'Stiff': 'StiffCondition', 'Next': 'NextCondition'}
TOKEN_FIELDS = {'Cond1': 'Cond', 'Cond2': 'Cond', 'Cond3': 'Cond',
                'Combo': 'Combo', 'StiffCond': 'Stiff', 'NextCond': 'Next',
                'OpStatus': 'Status', **{f'Act{i}': 'Action' for i in range(1, 6)}}


def related_paths(filepath):
    path = Path(filepath)
    character = path.stem.split('_cpu', 1)[0]
    names = ['cmn_cpu.xfbin']
    if character != 'cmn':
        names.append(character + '_cpu_cmn.xfbin')
    return [path.parent / name for name in names if path.parent / name != path]


def load_symbols(filepath, root):
    symbols = {tag: {} for tag in TOKEN_SECTIONS}
    missing = []
    sources = []
    for path in related_paths(filepath):
        try:
            _, _, tree = parse_cpu_xfbin(path)
            sources.append((path.name, tree.getroot()))
        except (OSError, ValueError, UnicodeError, ET.ParseError, struct.error):
            missing.append(path.name)
    sources.append((Path(filepath).name, root))
    for source, source_root in sources:
        for tag, section in TOKEN_SECTIONS.items():
            for elem in source_root.findall(f'{section}/{tag}'):
                token = elem.get('uid', '')
                symbols[tag][token] = {'name': elem.get('name', ''), 'source': source,
                                       'element': elem, 'local': source_root is root,
                                       'id': elem.get('id', ''), 'strength': elem.get('strength', '')}
    return symbols, missing


def valid_integer(value):
    return bool(re.fullmatch(r'[+-]?[0-9]+', value)) and -2147483648 <= int(value) <= 2147483647


def field_groups(element):
    tag = element.tag
    if tag == 'Data':
        groups = [('rule', 'rid OpStatus Position Rate'),
                  ('conditions', 'Cond1 Cond2 Cond3 Combo'),
                  ('sequence', 'Act1 Delay2 Act2 Delay3 Act3 Delay4 Act4 Delay5 Act5'),
                  ('followup', 'StiffCond StiffMin StiffMax NextCond NextRate Next')]
    elif tag == 'BaseParam':
        groups = [('defense', 'GuardRate JustGuardRate RecoverDown ThrowCounter'),
                  ('distance', 'NearInterval FarInterval')]
    elif tag == 'Action':
        groups = [('identity', 'name uid id'),
                  ('input', 'strength level crouch direction stand keepTime quitTime')]
    else:
        groups = [('identity', 'name uid memo')]
    used = set()
    result = []
    for name, fields in groups:
        keys = [key for key in fields.split() if key in element.attrib]
        used.update(keys)
        if keys:
            result.append((name, keys))
    rest = [key for key in element.attrib if key not in used]
    if rest:
        result.append(('advanced', rest))
    return result


def free_identity(parent, element):
    """Allocate only within the owning table; never overwrite stock duplicates."""
    tag = element.tag
    for key in ('rid',) if tag == 'Data' else ('tid', 'uid'):
        if key not in element.attrib:
            continue
        used = {e.get(key) for e in parent if e is not element}
        if key in ('rid', 'tid'):
            value = 1
            while str(value) in used:
                value += 1
            element.set(key, str(value))
        else:
            base = element.get(key) or 'New' + tag
            candidate = base + '_COPY'
            index = 2
            while candidate in used:
                candidate = f'{base}_COPY{index}'
                index += 1
            element.set(key, candidate)


def numeric_field(key):
    return key in NUMERIC_FIELDS


class CpuNames(SpmNames):
    """Read names from linked SPM commands when the designer's alias is Japanese.

    These are command names, not invented translations of character-specific
    behavior. Matching is strictly by the stored SPM/NMM/HHA number and kind.
    """
    def __init__(self, filepath):
        super().__init__(filepath)
        self.commands = {}
        from parsers.spm_parser import parse_spm_xfbin
        path = Path(filepath)
        character = path.stem.split('_cpu', 1)[0]
        for candidate in (path.parent / (character + '_SPM.xfbin'),
                          path.parent.parent / 'spm' / (character + '_SPM.xfbin')):
            try:
                root = parse_spm_xfbin(candidate)[1]['root']
            except (OSError, ValueError, UnicodeError, ET.ParseError, struct.error):
                continue
            for move in root.findall('SpecialMove'):
                kind, number = move.get('actKind', ''), move.get('actID', '')
                if number.isdecimal():
                    key = f'{kind.upper()}_{int(number):02d}'
                    name = move.get('name', '')
                    display = self.display(name)
                    if display != name:
                        self.commands[key] = display
            break
