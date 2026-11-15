"""Native 0x90-byte CustomCardParam rows; docs/custom-card-research.md.

The common codec retains notes, null pointers, opaque upper words and adjacent
NUCC chunks, and validates before atomically replacing the destination.
"""
from parsers.relative_table import RelativeTable

ENTRY_SIZE, HEADER_SIZE = 144, 16
_STR_FIELDS = ((0, 'card_id'), (24, 'letter'), (48, 'sfx1'), (56, 'sfx2'),
               (64, 'sfx3'), (72, 'sfx4'), (88, 'char_id'),
               (120, 'medal_name'), (128, 'card_detail'))
_STR_KEYS = tuple(key for _, key in _STR_FIELDS)
_INT_FIELDS = ((8, 'part', 'i'), (12, 'interaction_type', 'i'),
               (16, 'medal_type', 'i'), (20, 'medal_padding', 'I'),
               (32, 'unk7_0', 'i'), (36, 'unk7_1', 'i'),
               (40, 'unk7_2', 'i'), (44, 'unk7_3', 'i'),
               (80, 'unk18', 'i'), (84, 'unk19', 'I'),
               (96, 'dlc_id', 'I'), (100, 'patch', 'I'),
               (104, 'unlock_condition', 'I'), (108, 'unk', 'I'),
               (112, 'price', 'i'), (116, 'price_padding', 'I'),
               (136, 'index', 'I'), (140, 'index_padding', 'I'))
_table = RelativeTable('CustomCardParam', ENTRY_SIZE, _STR_FIELDS, _INT_FIELDS)
_encoded = _table.encoded
_parse_payload = _table.parse_payload
_find_binary_chunk = _table.find_chunk
_build_customcardparam_binary = _table.build
parse_customcardparam_xfbin = _table.parse
save_customcardparam_xfbin = _table.save


def make_default_entry(index=0):
    entry = {key: 0 for _, key, _ in _INT_FIELDS}
    entry.update({key: '' for key in _STR_KEYS})
    entry.update(card_id=f'CCD_CUSTOM_CARD_ID_{index + 1}', part=1,
                 interaction_type=2, medal_type=2, letter='A',
                 unk7_0=-1, unk7_1=-1, unk7_2=-1, unk7_3=-1,
                 unk18=1, unlock_condition=6, unk=1, price=8500,
                 card_detail='custom_card_detail_id_0005', index=index + 1)
    return entry
