"""File-backed ACF navigation and choices. Native evidence: acf-research.md.

This module describes stored relationships; it does not synthesize audio or
infer enums/ranges from the underlying integer types.
"""
from core.acf_research import bus_name, category_name, table_by_name
from parsers.acf_dsp import FX_NAMES
from parsers.asb_acf_parser import AcfBlob, DT_VLDATA


TABLE_NAMES = ('Header', 'VoiceLimitGroup', 'VoiceLimitGroupWork', 'DspSetting',
               'Bus', 'DspFx', 'BusLink', 'AisacControlName', 'Category',
               'CategoryName', 'Command', 'React', 'GameVariable',
               'GameVariableName', 'AisacControlId', 'BusName', 'BusIdListForAisacControl')


def user_table(table):
    return table.name != 'VoiceLimitGroupWork'


def user_column(table, column):
    """Keep audio authoring fields; retain container bookkeeping in the model."""
    name = column.name
    if not user_table(table) or column.dtype == DT_VLDATA:
        return False
    if name in ('BackupWorkOffset', 'SnapshotWorkSize') or (name.startswith('R') and name[1:].isdigit()):
        return False
    if table.name == 'Header' and name not in ('Name', 'CategoriesParPlayback', 'NumCueLimitListWorks', 'NumCueLimitNodeWorks'):
        return False
    if table.name == 'DspFx' and name == 'SrType':
        return False
    if table.name == 'Category' and name in ('ParameterPallet', 'NumAisacControlMaps'):
        return False
    return True


def user_help(table, name):
    key = {
        'Src': 'source_category', 'Dest': 'destination_category',
        'DecrementTime': 'duck_attack', 'IncrementTime': 'duck_release',
        'Level': 'duck_level', 'Volume': 'volume', 'SendLevel': 'send_level',
        'Pan3dVolume': 'pan_volume', 'Pan3dAngle': 'pan_angle', 'Pan3dDistance': 'pan_distance',
        'MaxNumbers': 'max_voices', 'DefaultValue': 'default_value',
        'HoldType': 'hold_type', 'HoldTime': 'hold_time', 'CountPausingCue': 'paused_cues',
        'StartFxIndex': 'fx_start', 'NumFxs': 'fx_count', 'StartBusLinkIndex': 'link_start',
        'NumBusLinks': 'link_count', 'CommandIndex': 'command_index',
        'NumCueLimitListWorks': 'cue_lists', 'NumCueLimitNodeWorks': 'cue_nodes',
    }.get(name)
    return 'acf_user_' + key if key else None


def row_name(tables, table, index):
    row = table.rows[index]
    for key in ('Name', 'StringValue'):
        if row.get(key):
            return str(row[key])
    if table.name == 'Category':
        return category_name(tables, index)
    if table.name == 'Bus':
        return bus_name(tables, row.get('BusNameIndex', index))
    if table.name == 'BusLink':
        return '→ ' + bus_name(tables, row.get('BusNameIndex', row.get('SendBusNo')))
    if table.name == 'React':
        return ' → '.join(category_name(tables, row.get(k)) or str(row.get(k, '?')) for k in ('Src', 'Dest'))
    if table.name == 'DspFx':
        return FX_NAMES.get(row.get('FxType'), str(row.get('FxType', '?')))
    if table.name == 'Command':
        categories = table_by_name(tables, 'Category')
        return ' / '.join(category_name(tables, i) or str(i) for i, r in enumerate(categories.rows)
                          if r.get('CommandIndex') == index) if categories else ''
    return ''


def reference_target(table_name, field):
    return {
        ('React', 'Src'): 'Category', ('React', 'Dest'): 'Category',
        ('CategoryName', 'Index'): 'Category', ('Category', 'CommandIndex'): 'Command',
        ('GameVariableName', 'Index'): 'GameVariable',
        ('Bus', 'BusNameIndex'): 'BusName', ('BusLink', 'BusNameIndex'): 'BusName',
        ('Bus', 'StartFxIndex'): 'DspFx', ('Bus', 'StartBusLinkIndex'): 'BusLink',
        ('DspSetting', 'StartIndex'): 'Bus',
    }.get((table_name, field))


def value_choices(tables, table, field, tr):
    target_name = reference_target(table.name, field)
    if target_name:
        target = table_by_name(tables, target_name)
        choices = [(i, f'{i} · {row_name(tables, target, i)}') for i in range(len(target.rows))] if target else []
        if (table.name, field) in (('Category', 'CommandIndex'), ('Bus', 'StartFxIndex'),
                                  ('Bus', 'StartBusLinkIndex')):
            choices.append((65535, tr('acf_no_reference')))
        return choices
    if table.name == 'BusLink' and field == 'SendBusNo':
        buses = table_by_name(tables, 'Bus')
        return [(r['BusNo'], f'{r["BusNo"]} · {row_name(tables, buses, i)}')
                for i, r in enumerate(buses.rows) if 'BusNo' in r] if buses else []
    if table.name == 'DspFx' and field == 'FxType':
        return list(FX_NAMES.items())
    if table.name == 'DspFx' and field == 'SrType':
        return [(0, tr('acf_renderer_asr'))]
    if (table.name == 'React' and field in ('HoldType', 'CountPausingCue')) or (table.name == 'DspFx' and field == 'flags'):
        keys = ('acf_hold_playback', 'acf_hold_fixed') if field == 'HoldType' else (
            ('acf_pause_exclude', 'acf_pause_include') if field == 'CountPausingCue' else ('acf_fx_active', 'acf_fx_bypass'))
        return list(enumerate(map(tr, keys)))
    if table.name == 'BusLink' and field == 'Type':
        return [(i, tr('acf_link_' + str(i))) for i in range(3)]
    return []


def searchable_row(tables, table, index):
    row = table.rows[index]
    return ' '.join([str(index), row_name(tables, table, index),
        *(str(v) for v in row.values() if not isinstance(v, AcfBlob))]).casefold()
