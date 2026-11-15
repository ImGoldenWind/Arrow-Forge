"""Native 0x50-byte PlayerTitleParam rows; see docs/player-title-research.md.

Legacy dictionary keys remain compatible. ``anim_id`` is a card background key,
``unk3`` is the signed low price word, and ``unk4`` its independent opaque word.
Only the low words of part and save identity are consumed by the native loader.
"""
from parsers.relative_table import RelativeTable

ENTRY_SIZE, HEADER_SIZE = 80, 16
_STR_FIELDS = ((0, 'title_id'), (8, 'anim_id'), (24, 'chara_code'),
               (56, 'card_string1'), (64, 'card_string2'))
_STR_KEYS = tuple(key for _, key in _STR_FIELDS)
_INT_FIELDS = ((16, 'part', 'i'), (20, 'part_padding', 'I'),
               (32, 'dlc_id', 'I'), (36, 'patch', 'I'),
               (40, 'unlock_cond', 'I'), (44, 'unk2', 'I'),
               (48, 'unk3', 'i'), (52, 'unk4', 'I'),
               (72, 'index', 'I'), (76, 'index_padding', 'I'))
_table = RelativeTable('PlayerTitleParam', ENTRY_SIZE, _STR_FIELDS, _INT_FIELDS)
_encoded = _table.encoded
_parse_payload = _table.parse_payload
_find_binary_chunk = _table.find_chunk
_build_binary = _table.build
parse_playertitleparam_xfbin = _table.parse
save_playertitleparam_xfbin = _table.save

# Compatibility constants; UI captions are localized by core.playertitle_tools.
UNLOCK_LABELS = {1: 'Initial flag 0x01', 2: 'Initial flag 0x40',
                 3: 'DLC marker', 4: 'Initial flag 0x20'}
PART_LABELS = dict(enumerate(('None / special', 'Phantom Blood', 'Battle Tendency',
    'Stardust Crusaders', 'Diamond is Unbreakable', 'Golden Wind', 'Stone Ocean',
    'Steel Ball Run', 'JoJolion')))


def make_default_entry(index=0):
    entry = {key: 0 for _, key, _ in _INT_FIELDS}
    entry.update({key: '' for key in _STR_KEYS})
    entry.update(title_id=f'PLCARD_TITLE_{index + 1:03d}', part=1,
                 unlock_cond=6, unk2=1, unk3=1, index=index)
    return entry
