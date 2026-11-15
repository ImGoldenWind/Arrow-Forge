"""Reaction categories observed in stock damageprm; gaps are deliberately unnamed.

These are category IDs, not row slots or animation IDs. Native dispatch at
386558 maps them to context-dependent states. See the research notes.
"""
REACTION_KEYS = {
    0: 'hit_no_reaction', 1: 'ui_damageprm_small_uc', 2: 'ui_damageprm_collapse',
    3: 'ui_damageprm_tumble', 4: 'ui_damageprm_smash', 5: 'ui_damageprm_smash_roll',
    6: 'ui_damageprm_smash_up', 7: 'ui_damageprm_throw_begin', 8: 'ui_damageprm_rush',
    9: 'ui_damageprm_bind', 14: 'ui_damageprm_crash_ground', 15: 'ui_damageprm_wall_crash',
    16: 'ui_damageprm_rise', 17: 'ui_damageprm_throw_blow', 18: 'ui_damageprm_smash_down',
    19: 'ui_damageprm_throw_command', 20: 'ui_damageprm_smash_gimmick',
    21: 'ui_damageprm_rush_speed_lose', 22: 'ui_damageprm_freeze',
    23: 'ui_damageprm_raise', 24: 'ui_damageprm_dummy_lock_release',
    25: 'ui_damageprm_3mra_strap_bind', 26: 'ui_damageprm_5prs_string_bind',
    27: 'ui_damageprm_pull_ground',
}

# Authored identifiers establish these associations, independently of edited values.
STOCK_REACTIONS = {
    'NONE': 0, 'DUMMY_NOREACTION': 0, 'SMALL_UC': 1, 'SMALL_CMN_SKILL': 1,
    'SMALL_UC_SKILL': 1, 'COLLAPSE': 2, 'TUMBLE': 3, 'SMASH': 4,
    'SMASH_DEM_RUSH': 4, 'GHHA_BLOWN': 4, 'SMASH_ROLL': 5, 'SMASH_UP': 6,
    'THROW_BEGIN': 7, 'RUSH': 8, 'BIND': 9, 'CRASH_GROUND': 14, 'WALL_CRASH': 15,
    'RISE': 16, 'THROW_BLOW': 17, 'SMASH_DOWN': 18, 'THROW_COMMAND': 19,
    'SMASH_GIMMICK': 20, 'RUSHSPEEDCOMPARE_LOSE': 21, 'FREEZE': 22, 'RAISE': 23,
    'DUMMY_LOCK_RELEASE': 24, '3MRA_STRAP_BIND': 25, '5PRS_STRING_BIND': 26,
    'PULL_GROUND_DMG': 27,
}


def reaction_name(value, tr):
    return tr(REACTION_KEYS[value]) if value in REACTION_KEYS else tr('hit_unknown', value=value)


def entry_name(entry, tr):
    suffix = entry['name'].removeprefix('DAMAGE_ID_')
    special = {'SMALL_CMN_SKILL': 'common_skill', 'SMALL_UC_SKILL': 'uc_skill',
               'SMASH_DEM_RUSH': 'dem_rush', 'GHHA_BLOWN': 'ghha',
               'DUMMY_NOREACTION': 'no_reaction'}
    if suffix in special:
        return tr('hit_entry_' + special[suffix])
    if suffix in STOCK_REACTIONS:
        return reaction_name(STOCK_REACTIONS[suffix], tr)
    return entry['name']
