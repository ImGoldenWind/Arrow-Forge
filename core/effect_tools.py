"""Effect catalog semantics and read-only asset indexing, independent of Qt."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import struct

from core.gallery_tools import resource_path
from parsers.effectprm_parser import encode_string, uint32

# Reference native loader 240690 allocates 0x1e90/24 and 0xa30/8 slots.
NATIVE_SLOT_COUNT = 326
FACTORIES = tuple(range(6))  # 1281348: null, then five creator pointers.


def parse_field(key, text, entry, width):
    if key in ('slot_id', 'xfbins_count'):
        text = text.strip()
        return uint32(int(text, 16 if text.lower().startswith('0x') else 10))
    if text != entry[key]:
        encode_string(text, width)
    return text


def next_slot(entries):
    used = {e['slot_id'] for e in entries}
    return next((n for n in range(NATIVE_SLOT_COUNT) if n not in used), None)


def duplicate_slots(entries):
    return {key for key, count in Counter(e['slot_id'] for e in entries).items() if count > 1}


def effective_entry(entries, slot):
    return next((e for e in reversed(entries) if e['slot_id'] == slot), None)


def data_root(filepath, configured=''):
    if filepath:
        for parent in Path(filepath).resolve().parents:
            if parent.name.lower() == 'data' and parent.is_dir():
                return parent
    if configured:
        root = Path(configured).resolve()
        if root.name.lower() == 'data' and root.is_dir():
            return root
        if (root / 'data').is_dir():
            return root / 'data'
        if (root / 'spc').is_dir() or (root / 'effect').is_dir():
            return root
    return None


def path_choices(root, entries):
    paths = {e['xfbin_path'] for e in entries if e['xfbin_path']}
    if root is not None:
        for directory, pattern in (('effect', '*.xfbin'), ('spc', '*eff*.xfbin')):
            paths.update('data/' + p.relative_to(root).as_posix() for p in (root / directory).glob(pattern))
    return tuple((p, p) for p in sorted(paths))


@lru_cache(maxsize=12)
def _asset_index(path, stamp, size):
    """Read only the existing NUCC table, never models, particles or textures."""
    from parsers.xfbin_lib.binary_reader import BinaryReader, Endian
    from parsers.xfbin_lib.br_xfbin import BrChunkTable, BrNuccHeader
    with open(path, 'rb') as stream:
        prefix = stream.read(68)
        if len(prefix) != 68 or prefix[:4] != b'NUCC':
            raise ValueError('Not a NUCC/XFBIN resource')
        fields = struct.unpack_from('>10I', prefix, 28)
        end = ((68 + fields[1] + fields[3] + fields[5] + 3) & ~3)
        end += fields[6] * 12 + fields[9] * 8 + fields[8] * 4
        if end > size or end > 32 * 1024 * 1024:
            raise ValueError('Invalid or oversized XFBIN resource table')
        if any(fields[i] > end for i in (0, 2, 4, 6, 8, 9)):
            raise ValueError('Invalid XFBIN resource table counts')
        table_bytes = prefix + stream.read(end - len(prefix))
    with BinaryReader(table_bytes, Endian.BIG, 'cp932') as reader:
        reader.read_struct(BrNuccHeader)
        table = reader.read_struct(BrChunkTable)
    return tuple(dict.fromkeys((table.get_props_from_chunk_map(m)[0],
                               table.get_props_from_chunk_map(m)[2]) for m in table.chunk_maps))


def load_asset_index(root, reference):
    path = resource_path(root, reference)
    if path is None:
        return None, ()
    stat = path.stat()
    return path, _asset_index(str(path), stat.st_mtime_ns, stat.st_size)


def effect_names(index):
    return sorted({name for kind, name in index
                   if name and kind in ('nuccChunkParticle', 'nuccChunkAnm')})


def damage_references(filepath, root):
    """Optional sibling Damage Effects references; failure stays independent."""
    from parsers.damageeff_parser import parse_damageeff_xfbin
    paths = [Path(filepath).parent / 'damageeff.bin.xfbin']
    if root:
        paths.append(root / 'spc/damageeff.bin.xfbin')
    for path in dict.fromkeys(paths):
        if path.is_file():
            result = parse_damageeff_xfbin(path)[1]
            links = {}
            for i, entry in enumerate(result['entries']):
                for key in ('eff_a', 'eff_b', 'eff_c', 'eff_d', 'eff_e'):
                    value = entry[key]
                    if value != 0xffffffff:
                        links.setdefault(value, []).append((i, entry['entry_id'], key[-1].upper()))
            return str(path), links
    return '', {}
