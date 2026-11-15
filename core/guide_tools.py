"""Readable Guide labels. IDs remain data; captions are UI descriptions."""
from core.translations import ui_text

CHARACTER_KEYS = {
    'speedwagon': 'ui_guidecharparam_speedwagon_p1',
    'polnareff': 'ui_guidecharparam_polnareff_p3',
    'messina': 'ui_guidecharparam_messina_p2',
    'melone': 'ui_guidecharparam_melone_p5',
    'abbacchio': 'ui_guidecharparam_abbacchio_p5',
    'emporio': 'ui_guidecharparam_emporio_p6',
    'wangchen': 'ui_guidecharparam_wang_chen_p3',
    'boingo': 'ui_guidecharparam_boingo_p4',
    'derbyd': 'ui_guidecharparam_darby_d_p4',
    'derbyt': 'ui_guidecharparam_darby_t_p4',
    'giatcho': 'ui_guidecharparam_ghiaccio_p5',
    'ringo': 'ui_guidecharparam_ringo_p7',
}
GROUPS = ('VERSUS_ONLINE', 'GALLERY_DICTIONARY', 'GALLERY_MODEL', 'GALLERY_SOUND',
          'GALLERY_SHOP', 'GALLERY_ART', 'MODESEL', 'SUPPORT', 'MAIN', 'VERSUS',
          'ARCADE', 'PRACTICE', 'GALLERY', 'CUSTOMIZE', 'OPTION')
ACTIONS = ('IN OUT DECIDE CANCEL MAIN ARCADE VERSUS ONLINE PRACTICE GALLERY CUSTOMIZE OPTION '
           'COMFIRM BATTLE_DETAIL BATTLE_CONFIRM BATTLE_WIN BATTLE_LOSE BOSS_OPEN BOSS_DETAIL '
           'BOSS_WIN BOSS_ALL_CLEAR STAFFROLL PAGE_OPEN PAGE_MOVE PART_CLEAR CLEAR_3 CLEAR_5 '
           'CLEAR_8 CLEAR_10 MISSION_3 MISSION_5 MISSION_8 MISSION_10 STAGE_IN SINGLE TEAM '
           'TOURNAMENT SELECT LOBBY_IN LOBBY_OUT SESSION_IN MATCHING UNMATCHING RANK PLAYER '
           'RANKING MISSION CHALLENGE ENDLESS CSEL_IN SSEL_IN MODEL SOUND ART DICTIONARY '
           'STAFF SHOP EDIT MEDAL PLCARD GHOST').split()


def character_label(value):
    key = CHARACTER_KEYS.get(value.removeprefix('guide_chara_'))
    return ui_text(key) if key else value


def event_label(value):
    for group in GROUPS:
        prefix = f'GUIDE_{group}_'
        if value.startswith(prefix) and value[len(prefix):] in ACTIONS:
            return ui_text('guide_event_caption', group=ui_text('guide_group_' + group.lower()),
                           action=ui_text('guide_action_' + value[len(prefix):].lower()))
    return value or ui_text('ui_guidecharparam_no_event')


def unique_event(base, entries):
    used = {entry.get('event', '') for entry in entries}
    result = base
    index = 2
    while result in used:
        result = f'{base}_{index}'
        index += 1
    return result
