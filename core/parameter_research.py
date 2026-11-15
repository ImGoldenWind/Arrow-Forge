"""Evidence-backed explanations shared by the parameter editors.

Native addresses and unresolved fields are documented in parameter-research.md.
Game messages are read from the user's extracted assets, never bundled here.
"""
from functools import lru_cache
from pathlib import Path
import re

from core.translations import current_language, ui_text


# Native dispatch 517720 / 5179D0; the latter handles 243..246.
_DUEL_EFFECT_SEQUENCES = {
    17: (7, 8), 15: (9, 10), 16: (11, 12), 23: (13, 14),
    13: (*range(15, 19), *range(243, 247)), 14: tuple(range(19, 23)),
    19: tuple(range(23, 29)), 42: (29, 30), 43: (228, 229),
    63: (230,), 64: (231,), 65: (232,), 66: (233,), 67: (234,),
    68: (235,), 69: (236,), 57: (237,), 70: (238,), 71: (239,),
    72: (240,), 73: (241,), 58: (242,), 59: tuple(range(247, 251)),
    60: (251, 252, 302, 303), 61: (253, 254, 304, 305),
    62: (255, 256, 306, 307), 74: (257,),
}
_DUEL_EFFECTS = {sequence: effect for effect, sequences in _DUEL_EFFECT_SEQUENCES.items()
                 for sequence in sequences}


def duel_effect_id(entry):
    if int(entry.get('type_id', -1)) == 2:
        return _DUEL_EFFECTS.get(int(entry.get('sequence_id', -1)))
    return None


def duel_value_label(entry, index):
    from core.duel_research import value_label
    return value_label(entry, index)


def duel_value_hint(entry, index):
    from core.duel_research import value_hint
    return value_hint(entry, index)


_SUPPORT_ARGUMENTS = {
    0: {},
    13: {1: 'param_attack_multiplier'},
    14: {1: 'param_defense_multiplier'},
    15: {1: 'param_effect_interval_30hz', 2: 'param_hp_restore_amount',
         3: 'param_hp_initial_and_limit_percent'},
    16: {1: 'param_periodic_hp_damage'},
    17: {1: 'param_hh_restore_amount', 2: 'param_effect_interval_30hz'},
    19: {1: 'param_initial_health_fraction'},
    20: {1: 'param_initial_hh_fraction'},
    25: {1: 'param_guard_crush_multiplier'},
    35: {1: 'param_attack_multiplier', 2: 'param_defense_multiplier'},
    44: {}, 45: {}, 46: {}, 47: {},
}


def support_value_label(effect_type, index):
    arguments = _SUPPORT_ARGUMENTS.get(int(effect_type))
    if arguments is None:
        return ui_text('param_effect_parameter', index=index)
    key = arguments.get(index)
    return ui_text(key) if key else ui_text('param_unused_effect_argument', index=index)


def support_value_hint(effect_type, index):
    arguments = _SUPPORT_ARGUMENTS.get(int(effect_type))
    if arguments is not None and index not in arguments:
        return ui_text('param_unused_effect_argument_hint')
    key = arguments.get(index) if arguments else None
    if key in ('param_effect_interval_30hz', 'param_hp_restore_amount',
               'param_hh_restore_amount', 'param_hp_initial_and_limit_percent'):
        return ui_text(key + '_hint')
    return ui_text('param_effect_parameters_hint')


def set_field_hint(fields, key, text):
    from PyQt6.QtWidgets import QLabel
    editor = fields.get(key)
    if editor is None or editor.parentWidget() is None:
        return
    editor.setToolTip(text)
    layout = editor.parentWidget().layout()
    if layout:
        for index in range(1, layout.count()):
            label = layout.itemAt(index).widget()
            if isinstance(label, QLabel):
                label.setText(text)


def set_field_caption(fields, key, text):
    """Update a standard field shell without rebuilding focused editors."""
    from PyQt6.QtWidgets import QLabel
    editor = fields.get(key)
    if editor is None or editor.parentWidget() is None:
        return
    layout = editor.parentWidget().layout()
    label = layout.itemAt(0).widget() if layout and layout.count() else None
    if isinstance(label, QLabel):
        label.setText(text)


@lru_cache(maxsize=8)
def _message_table(path, mtime_ns):
    from parsers.messageinfo_parser import parse_messageinfo_xfbin
    _, _, entries = parse_messageinfo_xfbin(path)
    return {entry['crc32_id']: entry['message'] for entry in entries}


def resolve_messages(file_path, keys):
    """Resolve local game text next to an extracted data tree or configured root."""
    from core.settings import load_settings
    from parsers.messageinfo_parser import crc32_of
    roots = list(Path(file_path or '.').resolve().parents)[:4]
    configured = load_settings().get('game_files_dir', '')
    if configured:
        roots[:0] = [Path(configured), Path(configured) / 'data']
    languages = ('rus', 'eng') if current_language() == 'ru' else ('eng',)
    for root in dict.fromkeys(roots):
        for language in languages:
            path = root / 'message' / 'WIN64' / language / 'messageInfo.bin.xfbin'
            if not path.is_file():
                continue
            try:
                messages = _message_table(str(path), path.stat().st_mtime_ns)
            except (OSError, ValueError, IndexError):
                continue
            values = [messages.get(crc32_of(key), '') for key in keys if key]
            if any(values):
                return list(dict.fromkeys(re.sub(r'<[^>]*>', '', value).strip() for value in values if value))
    return []


def research_card_text(kind, entry=None, file_path=''):
    lines = []
    if kind == 'support' and entry:
        from core.support_research import row_description
        lines.insert(0, row_description(entry))
    if kind == 'duel' and entry:
        from core.duel_research import rule_description
        lines.insert(0, rule_description(entry))
    if entry:
        keys = [entry.get(key, '') for key in ('title_key', 'hidden_title_key', 'hint_key', 'story_title_key', 'story_hint_key', 'campaign_title_key', 'campaign_hint_key')]
        messages = resolve_messages(file_path, keys)
        if messages:
            lines.append(ui_text('param_game_text') + '\n' + '\n'.join(messages))
    return '\n\n'.join(lines)


def add_research_card(layout, kind, entry=None, file_path=''):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLabel
    from core.style_helpers import make_editor_card, add_editor_card_title, ss_dim_label
    card, body = make_editor_card()
    add_editor_card_title(body, ui_text('param_editing_help'), 'fa6s.circle-info')
    label = QLabel(research_card_text(kind, entry, file_path), card)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setStyleSheet(ss_dim_label())
    body.addWidget(label)
    card.research_label = label
    layout.addWidget(card)
    return card


def acf_column_description(table, column, value):
    name = column.name
    key = {
        'Src': 'source_category', 'Dest': 'destination_category',
        'SrcCategory': 'source_category', 'DestCategory': 'destination_category',
        'DecrementTime': 'duck_attack', 'IncrementTime': 'duck_release',
        'Level': 'duck_level', 'HoldType': 'hold_type', 'HoldTime': 'hold_time',
        'CountPausingCue': 'paused_cues', 'ParameterId': 'parameter_id',
        'SendBusNo': 'send_bus', 'SendLevel': 'send_level',
        'Pan3dVolume': 'pan_volume', 'Pan3dAngle': 'pan_angle', 'Pan3dDistance': 'pan_distance',
        'Volume': 'volume', 'BackupWorkOffset': 'work_offset',
        'MaxNumbers': 'max_voices', 'StartFxIndex': 'fx_start', 'NumFxs': 'fx_count',
        'StartBusLinkIndex': 'link_start', 'NumBusLinks': 'link_count',
        'AisacControlId': 'aisac_id', 'DefaultValue': 'default_value',
        'Command': 'command_blob', 'Parameters': 'dsp_blob', 'SrType': 'sr_type',
        'CommandIndex': 'command_index', 'BusNameIndex': 'bus_name_index',
        'StartIndex': 'bus_start', 'NumBuses': 'bus_count',
        'FxType': 'fx_type',
    }.get(name)
    if name == 'Type' and 'buslink' in table.name.lower():
        key = 'link_type'
    overrides = {
        'Header': {'Version': 'format_version', 'Target': 'target', 'CategoriesParPlayback': 'categories_per_playback',
                   'NumCueLimitListWorks': 'cue_lists', 'NumCueLimitNodeWorks': 'cue_nodes',
                   'CueLimitWorkTable': 'cue_workspace', 'CharacterEncodingType': 'encoding',
                   'LinkedCueCategoryLimitFlag': 'linked_cue_limit', 'PreReadTime': 'pre_read',
                   'BusNameActiveWork': 'bus_active_work', 'BusNameIndexListForAisacGraphType': 'aisac_bus_map',
                   'VoiceLimitGroupWork': 'voice_work', 'SnapshotBackupWork': 'snapshot_work',
                   'FileIdentifier': 'metadata', 'Size': 'metadata', 'Type': 'metadata', 'Md5Hash': 'hash',
                   'Name': 'project_name', 'VersionString': 'version_string'},
        'Category': {'Id': 'category_id', 'GroupIndex': 'category_group', 'AisacControlMap': 'aisac_map',
                     'NumAisacControlMaps': 'aisac_map_count', 'Aisacs': 'category_aisacs', 'ParameterPallet': 'parameter_pallet'},
        'CategoryName': {'Index': 'category_index'},
        'GameVariableName': {'Index': 'variable_index'},
        'GameVariable': {'Id': 'variable_id'},
        'DspSetting': {'StartExtendBusIndex': 'extend_start', 'NumExtendBuses': 'extend_count',
                       'SnapshotStartIndex': 'snapshot_start', 'NumSnapshots': 'snapshot_count',
                       'SnapshotWorkSize': 'snapshot_size'},
        'Bus': {'BusNo': 'bus_number'},
        'BusLink': {'BusNameIndex': 'link_name_index'},
        'BusIdListForAisacControl': {'Id': 'aisac_bus_id'},
        'VoiceLimitGroupWork': {'Work': 'voice_work'},
    }
    key = overrides.get(table.name, {}).get(name, key)
    if name.startswith('R') and name[1:].isdigit():
        key = 'zero_storage' if column.storage == 1 else 'reserved'
    result = ui_text('acf_help_' + key) if key else ui_text('acf_help_structural')
    return f'{table.name}.{name} ({column.type_name}, {column.storage_name})\n{result}'
