"""Lossless editing of the XML UI collision payload inside an XFBIN."""
import copy
from collections import Counter
import os
import struct
import tempfile
import xml.etree.ElementTree as ET

from core.ui_collisions import parse_integer, xml_text_valid

COLLISION_FIELDS = ['type', 'name', 'x', 'y', 'w', 'h', 'rtoX', 'rtoY', 'lboX', 'lboY']
INT_FIELDS = set(COLLISION_FIELDS) - {'name'}


def _snapshot(sets):
    return [(s['name'], [{k: c.get(k, 0 if k in INT_FIELDS else '') for k in COLLISION_FIELDS}
                         for c in s['collisions']]) for s in sets]


def parse_info_xfbin(filepath):
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())
    if len(data) < 28 or data[:4] != b'NUCC':
        raise ValueError('Invalid or truncated XFBIN header')
    start = (28 + struct.unpack_from('>I', data, 16)[0] + 3) & ~3
    if start > len(data):
        raise ValueError('XFBIN chunk table exceeds file size')
    chunks, found = [], None
    offset = start
    while offset + 12 <= len(data):
        size = struct.unpack_from('>I', data, offset)[0]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError('Truncated XFBIN chunk')
        payload = bytes(data[offset + 12:end])
        chunk = {'header': bytes(data[offset:offset + 12]), 'data': payload,
                 'offset': offset}
        chunks.append(chunk)
        if len(payload) >= 4:
            n = struct.unpack_from('>I', payload)[0]
            if 0 < n <= len(payload) - 4 and payload[4:4 + n].lstrip().startswith((b'<?xml', b'<_root', b'\xef\xbb\xbf')):
                try:
                    candidate = ET.fromstring(payload[4:4 + n], parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
                except ET.ParseError:
                    candidate = None
                if candidate is not None and candidate.find('info/_array') is not None:
                    if found is not None:
                        raise ValueError('Multiple UI collision payloads are ambiguous')
                    found = len(chunks) - 1, candidate, n
        # NUCC envelopes follow their payload immediately, without alignment.
        offset = end
    if found is None:
        raise ValueError('No UI collision XML payload found')
    index, root, n = found
    sets = []
    for se in root.find('info/_array').findall('set'):
        ca = se.find('_array')
        collisions = []
        for ce in ca.findall('collision') if ca is not None else []:
            c = {'_xml': ET.tostring(ce, encoding='unicode')}
            for key in COLLISION_FIELDS:
                value = ce.findtext(key)
                c[key] = parse_integer(value) if key in INT_FIELDS and value is not None else (value or '' if key == 'name' else 0)
            collisions.append(c)
        sets.append({'name': se.findtext('name') or '', 'collisions': collisions,
                     '_xml': ET.tostring(se, encoding='unicode'),
                     '_orig_array_num': ca.get('num') if ca is not None else None,
                     '_orig_coll_count': len(collisions)})
    meta = {'chunk_data_start': start, 'chunks': chunks, 'binary_chunk_idx': index,
            'header_bytes': bytes(data[:start]), 'trailer': bytes(data[offset:]),
            'root': root, 'original': _snapshot(sets), 'original_count': len(sets),
            'binary_tail': chunks[index]['data'][4 + n:]}
    return data, sets, meta


def _set_text(parent, key, value):
    if not xml_text_valid(str(value)):
        raise ValueError('Text contains characters XML cannot store')
    child = parent.find(key)
    if child is None:
        child = ET.SubElement(parent, key)
    # Preserve lexical spelling (e.g. 0001) when the numeric value is unchanged.
    if key in INT_FIELDS:
        value = parse_integer(str(value))
        try:
            if int(child.text) == value:
                return
        except (TypeError, ValueError):
            pass
    child.text = str(value)


def _replace_children(parent, tag, children):
    old = [c for c in parent if c.tag == tag]
    insertion = list(parent).index(old[-1]) + 1 if old else len(parent)
    for prior, replacement in zip(old, children):
        index = list(parent).index(prior)
        parent.remove(prior)
        parent.insert(index, replacement)
    for prior in old[len(children):]:
        parent.remove(prior)
    for replacement in children[len(old):]:
        parent.insert(insertion, replacement)
        insertion += 1


def _build_xml(sets, meta=None):
    root = copy.deepcopy(meta['root']) if meta else ET.fromstring('<_root><info><_array/></info></_root>')
    array = root.find('info/_array')
    if not meta or len(sets) != meta['original_count']:
        array.set('num', str(len(sets)))
    elements = []
    for s in sets:
        se = ET.fromstring(s['_xml'], parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))) if '_xml' in s else ET.Element('set')
        _set_text(se, 'name', s['name'])
        ca = se.find('_array')
        if ca is None:
            ca = ET.SubElement(se, '_array')
        if s.get('_orig_coll_count') != len(s['collisions']):
            ca.set('num', str(len(s['collisions'])))
        records = []
        for c in s['collisions']:
            ce = ET.fromstring(c['_xml'], parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))) if '_xml' in c else ET.Element('collision')
            for key in COLLISION_FIELDS:
                value = c.get(key, 0 if key in INT_FIELDS else '')
                # Missing default fields are preserved rather than materialised.
                if ce.find(key) is None and '_xml' in c and value == (0 if key in INT_FIELDS else ''):
                    continue
                _set_text(ce, key, value)
            records.append(ce)
        _replace_children(ca, 'collision', records)
        elements.append(se)
    _replace_children(array, 'set', elements)
    return '<?xml version="1.0" encoding="utf-8"?>\r\n' + ET.tostring(root, encoding='unicode')


def save_info_xfbin(filepath, data, sets, meta):
    if _snapshot(sets) == meta['original']:
        result = bytes(data)
    else:
        xml = _build_xml(sets, meta).encode('utf-8')
        payload = struct.pack('>I', len(xml)) + xml + meta['binary_tail']
        result = bytearray(meta['header_bytes'])
        for i, chunk in enumerate(meta['chunks']):
            if i == meta['binary_chunk_idx']:
                header = bytearray(chunk['header'])
                struct.pack_into('>I', header, 0, len(payload))
                result += header + payload
            else:
                result += chunk['header'] + chunk['data']
        result += meta['trailer']
    folder = os.path.dirname(os.path.abspath(filepath))
    fd, temporary = tempfile.mkstemp(prefix='.arrow-info-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(result)
        os.replace(temporary, filepath)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def get_scene_description(scene_name):
    """Return a human-readable description for known scene names."""
    descriptions = {
        'ccSceneCommandList': 'Command List (move list viewer)',
        'ccUiMainModeRewardList': 'Main Mode — Reward List',
        'ccSceneModeSelect': 'Mode Select Screen',
        'ccSceneBattleSelectChar': 'Battle — Character Select (CSS)',
        'ccSceneBattleSelectStage': 'Battle — Stage Select',
        'ccSceneCustomizeMenu': 'Customize Menu',
        'ccSceneOptionMenuTitle': 'Options Menu (Title)',
        'ccUiStorySelectPart': 'Story — Part Select',
        'ccUiStorySelectScenario': 'Story — Scenario Select',
        'ccSceneGallery': 'Gallery Menu',
        'ccSceneGalleryShop': 'Gallery — Shop',
        'ccUiCardList': 'Card List',
        'ccSceneOfflineBattleMenu': 'Offline Battle Menu',
        'ccSceneGallerySoundTest': 'Gallery — Sound Test',
        'ccSceneGalleryDictionary': 'Gallery — Dictionary',
        'ccSceneGalleryImageViewer': 'Gallery — Image Viewer',
        'ccSceneCustomize': 'Customize Screen',
        'ccCustomizeSetProvoke': 'Customize — Set Provoke',
        'ccCustomizeSetWin': 'Customize — Set Win Pose',
        'ccSceneBrowsePlayerCard': 'Browse Player Card',
        'ccPlayerCardEditTitleName': 'Player Card — Edit Title/Name',
        'ccPlayerCardFriendCardList': 'Player Card — Friend Card List',
        'ccSceneNetBattleMenu': 'Online Battle Menu',
        'ccSceneGalleryCharViewer': 'Gallery — Character Viewer',
        'ccSceneCustomizePreview': 'Customize — Preview',
        'ccSceneOptionMenuTitleWin': 'Options Menu (Window)',
        'ccSceneMainMode': 'Main Mode Hub',
        'ccUiAgreementBase': 'Agreement / EULA',
        'ccUiOnlineMission': 'Online Mission',
        'ccUiRankMatchPresetSettingWindow': 'Ranked Match — Preset Settings',
        'ccUiPasswordSettingWindow': 'Password Setting',
        'ccUiTermList': 'Term List',
    }
    # Handle MainModePage variants
    if scene_name.startswith('ccSceneMainModePage'):
        page = scene_name.replace('ccSceneMainModePage', '')
        return f'Main Mode — Page {page}'
    if scene_name.startswith('PresetWindowSelection'):
        side = scene_name[-2:]
        return f'Preset Window — Player {side[-1]}'
    return descriptions.get(scene_name, scene_name)


def make_default_collision():
    """Create a new collision with default values."""
    return {
        'type': 0,
        'name': 'NewCollision',
        'x': 0, 'y': 0, 'w': 100, 'h': 50,
        'rtoX': 10, 'rtoY': -10,
        'lboX': -10, 'lboY': 10,
    }


def analyze_char_select(sets):
    """Analyze the character select screen set.

    Returns dict with analysis results, or None if set not found.
    """
    for s in sets:
        if s['name'] == 'ccSceneBattleSelectChar':
            collisions = s['collisions']
            face_icons = [c for c in collisions if c.get('name') == 'FaceIcon']

            # Detect grid layout
            y_values = sorted(set(c['y'] for c in face_icons))
            rows = {}
            for c in face_icons:
                rows.setdefault(c['y'], []).append(c)
            for y in rows:
                rows[y].sort(key=lambda c: c['x'])

            return {
                'total_collisions': len(collisions),
                'face_icon_count': len(face_icons),
                'row_count': len(y_values),
                'y_values': y_values,
                'rows': rows,
                'typical_size': Counter((c['w'], c['h']) for c in face_icons).most_common(1)[0][0] if face_icons else (0, 0),
            }
    return None
