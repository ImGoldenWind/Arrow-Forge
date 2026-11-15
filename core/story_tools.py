"""Story navigation and local DuelSetting labels. See docs/story-mode-research.md."""
from pathlib import Path
import struct

from core.parameter_research import resolve_messages
from core.translations import ui_text
from parsers.duelsettingparam_parser import parse_duelsettingparam_xfbin


def character_name(code):
    key = 'char_' + code
    name = ui_text(key)
    return code if name == key else name


def part_name(value):
    return ui_text(f'part_{value}') if value in range(1, 9) else ui_text('story_part_custom', value=value)


def type_name(value):
    keys = {0: 'ui_mainmodeparam_normal', 1: 'skill_param_extra', 2: 'ui_mainmodeparam_boss'}
    return ui_text(keys[value]) if value in keys else ui_text('story_type_custom', value=value)


def panel_title(panel):
    return ui_text('story_match', player=character_name(panel.get('ptr_player_id', '')) or '—',
                   enemy=character_name(panel.get('ptr_enemy_id', '')) or '—')


def load_rules(file_path):
    """Prefer the sibling catalog; never hard-code a different mod's sequence IDs."""
    from core.settings import load_settings
    path = Path(file_path).with_name('DuelSettingParam.bin.xfbin')
    if not path.is_file():
        configured = load_settings().get('game_files_dir', '')
        candidates = [Path(configured) / prefix / 'param/main_mode/DuelSettingParam.bin.xfbin'
                      for prefix in ('', 'data')] if configured else []
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            return {}, ''
    try:
        _, result = parse_duelsettingparam_xfbin(path)
        rules = {}
        for entry in result['entries']:
            value = entry['sequence_id']
            value = value if value < 0x80000000 else value - 0x100000000
            titles = resolve_messages(file_path, [entry['title_key']])
            hints = resolve_messages(file_path, [entry['hint_key']])
            rules.setdefault(value, (titles[0] if titles else entry['title_key'],
                                     hints[0] if hints else '', entry['type_id']))
        return rules, str(path)
    except (OSError, ValueError, IndexError, KeyError, struct.error) as error:
        return {}, str(error)


def rule_name(value, rules):
    if value == -1:
        return ui_text('story_disabled')
    rule = rules.get(value)
    return rule[0] if rule else ui_text('story_custom_id')


def panel_issues(panel, panels, rules):
    issues = []
    if panel.get('part', 0) not in range(1, 9):
        issues.append(ui_text('story_invalid_part', value=panel.get('part', 0)))
    if panel.get('page', 0) not in range(1, 15):
        issues.append(ui_text('story_invalid_page', value=panel.get('page', 0)))
    panel_id = panel.get('ptr_panel_id', '')
    if not panel_id:
        issues.append(ui_text('story_empty_id'))
    elif sum(p.get('ptr_panel_id') == panel_id for p in panels) > 1:
        issues.append(ui_text('story_duplicate_id', value=panel_id))
    ids = {p.get('ptr_panel_id') for p in panels}
    for key in ('ptr_boss_id', 'ptr_up', 'ptr_down', 'ptr_left', 'ptr_right'):
        target = panel.get(key, '')
        if target and target not in ids:
            issues.append(ui_text('story_missing_link', value=target))
    if sum(p.get('total_idx') == panel.get('total_idx') for p in panels) > 1:
        issues.append(ui_text('story_duplicate_index', value=panel.get('total_idx')))
    if rules:
        missing = sorted({panel.get(key, -1) for key in
                          ('spec_rule_1', 'spec_rule_2', 'spec_rule_3',
                           'm1_cond', 'm2_cond', 'm3_cond', 'm4_cond')}
                         - {-1} - set(rules))
        if missing:
            issues.append(ui_text('story_missing_rules', values=', '.join(map(str, missing))))
        for key in ('m1_cond', 'm2_cond', 'm3_cond', 'm4_cond'):
            value = panel.get(key, -1)
            rule = rules.get(value, ())
            if value != -1 and len(rule) > 2 and rule[2] != 1:
                issues.append(ui_text('story_wrong_mission_type', value=value))
    return '\n'.join(dict.fromkeys(issues))
