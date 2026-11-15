"""Lossless XML helpers and file-backed projectile field vocabulary."""

import copy
import math
import re
import xml.etree.ElementTree as ET


ACTION_TYPES = (
    'NONE', 'ARROW', 'ARROW_AFTER_HOMING', 'RETURN', 'SINCURVE', 'LASER',
    'CRAWLER', 'BOUNDBALL', 'ADHERE_INDUCTIVE', 'ELEVATOR', 'INDUCTIVE_COORD',
    'SHEER_HEART_ATTACK_S', 'SHEER_HEART_ATTACK_A', 'FOLLOW_OTHER', 'ATTACH',
    'ARROW_ONE_HOMING', 'SCM', 'SCM_DAMAGE_REACTION', 'JIR_BALL', 'RETURN_BEZIER',
)
EVENT_TYPES = (
    'FRAME_ELAPSED', 'HIT_CHARACTER_DEFAULT', 'HIT_CHARACTER_SUCCEED',
    'HIT_CHARACTER_GUARD', 'OWNER_DAMAGED', 'HIT_WORLD_DEFAULT', 'HIT_SKILL_DEFAULT',
    'ANIMATION_END', 'HIT_CHARACTER_FINAL', 'CLOSE_TO_TARGET', 'HIT_WORLD_WALL',
    'HIT_WORLD_FLOOR', 'HIT_CHARACTER_JUST_GUARD', 'KILL_BY_ENEMY', 'FALL_TOGETHER',
    'MOVE_STOP', 'RETURNED', 'HIT_SKILL_FRIEND', 'START_GHHA', 'HIT_WORLD_PLWALL',
    'HIT_WORLD_ROOF', 'CLOSE_TO_TARGET_HORIZONAL', 'HIT_POINT', 'HIT_POINT_ACTION',
    'OUT_OF_OWNER_SIGHT', *(f'ACT_CMD_{i}' for i in range(1, 8)),
)
EVENT_COMMANDS = ('ETC', 'KILL', 'CHANGE_ACTION', 'CATCHED', 'STICK', 'MULTI_VELOCITY', 'REMOVE')


def parse_skill(text):
    text = re.sub(r'<\?xml[^>]*\?>', '', text)
    root = ET.fromstring(text, parser=ET.XMLParser(
        target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    if root.tag != 'Skill':
        raise ValueError('Expected a Skill XML root')
    return root


def skill_xml(root):
    root = copy.deepcopy(root)
    ET.indent(root, space='\t')
    return ('<?xml version="1.0" encoding="Shift_JIS"?>\r\n' +
            ET.tostring(root, encoding='unicode', short_empty_elements=False)
            .replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n'))


def actions(root):
    return [(group, el) for name in ('Actions', 'GenActions')
            for group in root.findall(name) for el in group.findall('Action')]


def next_action_id(root):
    """Normal slots 0..7; stock shared actions occupy 8..11."""
    used = {el.get('id') for _, el in actions(root)}
    return next((str(i) for i in range(8) if str(i) not in used), None)


def sync_counts(root):
    for tag, child in (('Actions', 'Action'), ('GenActions', 'Action'), ('Files', 'File')):
        for group in root.findall(tag):
            group.set('num', str(len(group.findall(child))))


def finite_number(value):
    if not re.fullmatch(r'\s*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\s*', value):
        return False
    try:
        return bool(value.strip()) and math.isfinite(float(value))
    except ValueError:
        return False


def unique_skill_id(chunks, base):
    # The native loader copies this ID into a 32-byte field.
    base = base[:23]
    used = {c['skill_id'] for c in chunks}
    if base not in used:
        return base
    i = 1
    while f'{base}_{i}' in used:
        i += 1
    return f'{base}_{i}'


def skill_issues(root):
    """Structural diagnostics; never normalize an existing custom value."""
    issues = []
    pairs = actions(root)
    ids = [el.get('id', '') for _, el in pairs]
    if len(set(ids)) != len(ids):
        issues.append('proj_issue_duplicate')
    first = root.find('Actions')
    if first is not None and first.get('FirstActionId') not in ids:
        issues.append('proj_issue_first')
    if any(ev.get('command') == 'SKILL_EVENT_COMMAND_CHANGE_ACTION'
           and ev.get('commandParameter') not in ids for ev in root.iter('Event')):
        issues.append('proj_issue_target')
    return issues
