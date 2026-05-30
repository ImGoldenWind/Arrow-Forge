from core.icons import (
    icon_person, icon_swords, icon_arrow, icon_play, icon_grid,
    icon_gallery_cat, icon_multiplayer_cat, icon_audio_assets,
    icon_stats, icon_id, icon_costume, icon_sound, icon_skill, icon_cpu_ai,
    icon_hit, icon_damage, icon_balance, icon_battle_result, icon_duel_setting, icon_arcade_reward, icon_net_rank, icon_net_result, icon_online_mission, icon_projectile, icon_effect,
    icon_movelist, icon_command_list_param, icon_constraint, icon_story, icon_dialogue,
    icon_assist, icon_support_item, icon_game_text, icon_term_list, icon_tutorial_param, icon_stage, icon_ui, icon_gimmick,
    icon_texture, icon_xfbin, icon_usm_video,
    icon_char_viewer, icon_guide_char, icon_dictionary, icon_custom_card,
    icon_custom_default, icon_dlc_info, icon_gallery, icon_player_title,
    icon_trophy_param,
    icon_sound_param, icon_sound_test, icon_lip_sync, icon_asb_acf,
)

# Tool & category data
TOOLS = {
    # Character identity, stats, costumes, and related content flags.
    "CHARACTER": [
        ("duelPlayerParam",      icon_stats,    "tool_char_stats", "dlg_char_stats"),
        ("characode.bin",        icon_id,       "tool_char_id",    "dlg_char_id"),
        ("PlayerColorParam.bin", icon_costume,  "tool_costume",    "dlg_costume"),
        ("DlcInfoParam.xfbin",   icon_dlc_info, "tool_dlc_info",   "dlg_dlc_info"),
    ],

    # Character actions and fight-call systems.
    "MOVESET": [
        ("0xxx00prm.bin, prm_gha.bin",         icon_skill,      "tool_char_skill", "dlg_char_skill"),
        ("0xxx00_SPM",            icon_movelist,   "tool_movelist",   "dlg_movelist"),
        ("*_lip.xfbin",           icon_lip_sync,   "tool_lip_sync",   "dlg_lip_sync"),
        ("CommandListParam.bin",   icon_command_list_param, "tool_command_list_param", "dlg_command_list_param"),
        ("0xxx00_x",              icon_projectile, "tool_projectile", "dlg_projectile"),
        ("SupportCharaParam.bin", icon_assist,     "tool_assist",     "dlg_assist"),
    ],

    # Global battle tuning and reaction rules.
    "BATTLE_PARAMS": [
        ("CPU AI / ArcadeCpuParam.bin", icon_cpu_ai,    "tool_cpu_ai",     "dlg_cpu_ai"),
        ("0xxx00_constParam", icon_constraint, "tool_char_const",  "dlg_char_const"),
        ("damageprm.bin",    icon_hit,        "tool_hit_react",   "dlg_hit_react"),
        ("damageeff.bin",    icon_damage,     "tool_dmg_effect",  "dlg_dmg_effect"),
        ("btladjprm.bin",    icon_balance,    "tool_battle_adj",  "dlg_battle_adj"),
        ("DuelSettingParam.bin", icon_duel_setting, "tool_duel_setting", "dlg_duel_setting"),
        ("BattleResultParam.bin, ArcadeResultParam.bin", icon_battle_result, "tool_battle_result", "dlg_battle_result"),
        ("ArcadeRewardParam.bin, CumulativeRewardParam.bin", icon_arcade_reward, "tool_arcade_reward", "dlg_arcade_reward"),
    ],

    # Story panels, special lines, menu guide characters, and localization text.
    "STORY_TEXT": [
        ("MainModeParam.bin",     icon_story,      "tool_story",      "dlg_story"),
        ("SupportItemParam.bin",  icon_support_item, "tool_support_item", "dlg_support_item"),
        ("SpeakingLineParam.bin", icon_dialogue,   "tool_dialogue",   "dlg_dialogue"),
        ("GuideCharParam.xfbin",  icon_guide_char, "tool_guide_char", "dlg_guide_char"),
        ("messageinfo",           icon_game_text,  "tool_game_text",  "dlg_game_text"),
        ("TermListParam.bin",     icon_term_list,  "tool_term_list",  "dlg_term_list"),
        ("TutorialParam.bin",     icon_tutorial_param, "tool_tutorial_param", "dlg_tutorial_param"),
    ],

    # Stage data and menu hit/click regions.
    "STAGE_UI": [
        ("StageInfo.bin", icon_stage,   "tool_stage_info", "dlg_stage_info"),
        ("Xcmnsfprm.bin", icon_gimmick, "tool_gimmick",    "dlg_gimmick"),
        ("info",          icon_ui,      "tool_ui_coll",    "dlg_ui_coll"),
    ],

    # Gallery viewers, unlockable gallery data, and sound-test entries.
    "GALLERY": [
        ("CharViewerParam.xfbin",       icon_char_viewer,    "tool_char_viewer",    "dlg_char_viewer"),
        ("DictionaryParam.xfbin",       icon_dictionary,     "tool_dictionary",     "dlg_dictionary"),
        ("CustomizeDefaultParam.xfbin", icon_custom_default, "tool_custom_default", "dlg_custom_default"),
        ("GalleryArtParam.xfbin",       icon_gallery,        "tool_gallery_param",  "dlg_gallery_param"),
        ("SoundTestParam.xfbin",        icon_sound_test,     "tool_sound_test",     "dlg_sound_test"),
    ],

    # Multiplayer profile, title, card, and online result data.
    "PROFILE": [
        ("CustomCardParam.xfbin",  icon_custom_card,  "tool_custom_card",  "dlg_custom_card"),
        ("PlayerTitleParam.xfbin", icon_player_title, "tool_player_title", "dlg_player_title"),
        ("TrophyParam.bin", icon_trophy_param, "tool_trophy_param", "dlg_trophy_param"),
        ("NetRankParam.bin", icon_net_rank, "tool_net_rank", "dlg_net_rank"),
        ("NetResultParam.bin", icon_net_result, "tool_net_result", "dlg_net_result"),
        ("OnlineMissionParam.bin", icon_online_mission, "tool_online_mission", "dlg_online_mission"),
    ],

    # Raw resource editors and audio playback parameters.
    "ASSETS": [
        (".awb",        icon_sound,       "tool_sound",       "dlg_sound"),
        (".xfbin textures",     icon_texture,     "tool_texture",     "dlg_texture"),
        (".xfbin sounds",       icon_xfbin,       "tool_xfbin_audio", "dlg_xfbin_audio"),
        (".usm",                icon_usm_video,   "tool_usm_video",   "dlg_usm_video"),
        ("effectprm.bin",       icon_effect,      "tool_effect",      "dlg_effect"),
        ("sndcmnparam.xfbin",   icon_sound_param, "tool_sound_param", "dlg_sound_param"),
        ("ASB.acf",             icon_asb_acf,     "tool_asb_acf",     "dlg_asb_acf"),
    ],
}

CAT_KEYS = [
    "CHARACTER",
    "MOVESET",
    "BATTLE_PARAMS",
    "STORY_TEXT",
    "STAGE_UI",
    "GALLERY",
    "PROFILE",
    "ASSETS",
]

CAT_PORTRAIT = {
    "FAVORITES":     "resources/guides/guide_favorites.png",
    "CHARACTER":     "resources/guides/guide_characters.png",
    "MOVESET":       "resources/guides/guide_moveset.png",
    "BATTLE_PARAMS": "resources/guides/guide_battle_params.png",
    "STORY_TEXT":    "resources/guides/guide_story_text.png",
    "STAGE_UI":      "resources/guides/guide_stages_ui.png",
    "GALLERY":       "resources/guides/guide_gallery.png",
    "PROFILE":       "resources/guides/guide_player_profile.png",
    "ASSETS":        "resources/guides/guide_assets.png",
}

# (icon_func, i18n_key, speaker_i18n_key)
CAT_META = {
    "CHARACTER":     (icon_person,       "cat_CHARACTER",     "speaker_CHARACTER"),
    "MOVESET":       (icon_arrow,        "cat_MOVESET",       "speaker_MOVESET"),
    "BATTLE_PARAMS": (icon_swords,       "cat_BATTLE_PARAMS", "speaker_BATTLE_PARAMS"),
    "STORY_TEXT":    (icon_play,         "cat_STORY_TEXT",    "speaker_STORY_TEXT"),
    "STAGE_UI":      (icon_grid,         "cat_STAGE_UI",      "speaker_STAGE_UI"),
    "GALLERY":       (icon_gallery_cat,  "cat_GALLERY",       "speaker_GALLERY"),
    "PROFILE":       (icon_multiplayer_cat, "cat_PROFILE",       "speaker_PROFILE"),
    "ASSETS":        (icon_audio_assets, "cat_ASSETS",        "speaker_ASSETS"),
}
