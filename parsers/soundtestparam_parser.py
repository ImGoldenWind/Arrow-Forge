"""Native 0x50-byte SoundTestParam rows. See docs/sound-test-research.md.

The old 'unk1/2/3' pointers were scalar words. Only four fields are strings.
The shared codec retains notes, opaque words, pools and neighboring chunks.
"""
from parsers.relative_table import RelativeTable

ENTRY_SIZE, HEADER_SIZE = 80, 16
_STR_FIELDS = ((0, 'bgm_id'), (24, 'chara_code'),
               (56, 'sound_str1'), (64, 'sound_str2'))
_STR_KEYS = tuple(key for _, key in _STR_FIELDS)
_INT_FIELDS = ((8, 'entry_type', 'I'), (12, 'native_flag', 'I'),
               (16, 'part', 'i'), (20, 'part_padding', 'I'),
               (32, 'dlc_id', 'I'), (36, 'patch', 'I'),
               (40, 'unlock_cond', 'I'), (44, 'menu_index', 'I'),
               (48, 'price', 'i'), (52, 'price_padding', 'I'),
               (72, 'index', 'I'), (76, 'index_padding', 'I'))
_table = RelativeTable('SoundTestParam', ENTRY_SIZE, _STR_FIELDS, _INT_FIELDS)
_encoded = _table.encoded
_parse_payload = _table.parse_payload
_find_binary_chunk = _table.find_chunk
_build_binary = _table.build
parse_soundtestparam_xfbin = _table.parse
save_soundtestparam_xfbin = _table.save


def make_default_entry():
    entry = {key: 0 for _, key, _ in _INT_FIELDS}
    entry.update({key: '' for key in _STR_KEYS})
    entry.update(bgm_id='ST_BGM_NEW', chara_code='dmy01', unlock_cond=1,
                 menu_index=1, price=1000)
    return entry
