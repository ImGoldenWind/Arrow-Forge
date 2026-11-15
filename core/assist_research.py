"""Version-aware field captions backed by the SupportCharaParam native loader."""
from core.translations import ui_text

DIFFICULTIES = ('default', 'veryeasy', 'easy', 'hard', 'veryhard')


def field_groups(version):
    shift = int(version >= 1001)
    return [
        ('stocks', [2, 3] if shift else [2]),
        ('assault_entrance', list(range(3 + shift, 6 + shift))),
        ('reversal_entrance', list(range(6 + shift, 9 + shift))),
        ('sequence', list(range(9 + shift, 18 + shift))),
        ('technical', [18 + shift, 34 + shift] + ([] if shift else [35])),
    ]


def field_key(index, version):
    if index == 2:
        return 'assault_stocks'
    if version >= 1001 and index == 3:
        return 'reversal_stocks'
    logical = index - int(version >= 1001)
    names = {3: 'entry_x', 4: 'entry_y', 5: 'entry_z',
             6: 'entry_x', 7: 'entry_y', 8: 'entry_z',
             9: 'stand_action', 10: 'sequence_kind', 11: 'action_1',
             12: 'button_1', 13: 'extra_count', 14: 'action_2', 15: 'button_2',
             16: 'action_3', 17: 'button_3', 18: 'ai_range',
             34: 'category', 35: 'reserved'}
    return names.get(logical, 'raw')


def caption(index, version):
    return ui_text('assist_' + field_key(index, version))


def hint(index, version):
    key = field_key(index, version)
    if key.startswith('entry_'):
        key = 'position'
    elif key.startswith('action_'):
        key = 'action'
    elif key.startswith('button_'):
        key = 'button'
    return ui_text('assist_hint_' + key)


def cooldown_rows(version):
    first = 19 + int(version >= 1001)
    return [(ui_text('assist_difficulty_' + name), list(range(first + i * 3, first + i * 3 + 3)))
            for i, name in enumerate(DIFFICULTIES)]


def field_options(index, version):
    key = field_key(index, version)
    if key.startswith('button_'):
        # Stored IDs map to the native action-button IDs 0,5,6,7,9,13.
        return [(i, ui_text('assist_button_value', value=i, native=n))
                for i, n in enumerate((0, 5, 6, 7, 9, 13))]
    if key == 'sequence_kind':
        return [(i, ui_text('assist_sequence_value', value=i)) for i in range(1, 9)]
    if key == 'ai_range':
        return [(i, ui_text('assist_ai_range_' + str(i))) for i in (0, 1, 2)]
    return []
