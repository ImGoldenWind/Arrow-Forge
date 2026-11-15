"""Native 0x68-byte GalleryArtParam rows; see docs/gallery-art-research.md.

The common relative-table codec retains notes, null pointers, opaque words and
neighboring NUCC chunks, and atomically replaces the destination.
"""
from parsers.relative_table import RelativeTable

ENTRY_SIZE, HEADER_SIZE = 104, 16
_STR_FIELDS = ((0, 'art_id'), (8, 'icon_path'), (16, 'icon_name'),
               (24, 'art_path'), (32, 'art_name'), (48, 'chara_code'),
               (80, 'art_string1'), (88, 'art_string2'))
_STR_KEYS = tuple(key for _, key in _STR_FIELDS)
_INT_FIELDS = ((40, 'part', 'i'), (44, 'part_padding', 'I'),
               (56, 'dlc_id', 'I'), (60, 'patch', 'I'),
               (64, 'unlock_cond', 'I'), (68, 'menu_index', 'I'),
               (72, 'price', 'i'), (76, 'price_padding', 'I'),
               (96, 'index', 'I'), (100, 'index_padding', 'I'))
_table = RelativeTable('GalleryArtParam', ENTRY_SIZE, _STR_FIELDS, _INT_FIELDS)
_encoded = _table.encoded
_parse_payload = _table.parse_payload
_find_binary_chunk = _table.find_chunk
_build_binary = _table.build
parse_galleryartparam_xfbin = _table.parse
save_galleryartparam_xfbin = _table.save


def make_default_entry(index=0):
    entry = {key: 0 for _, key, _ in _INT_FIELDS}
    entry.update({key: '' for key in _STR_KEYS})
    entry.update(art_id=f'ID_ART_{index + 1:03d}', part=1, unlock_cond=6,
                 menu_index=1, price=1500, index=index)
    return entry
