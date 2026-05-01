import struct
import xml.etree.ElementTree as ET

# info.xfbin parser
# File structure (XFBIN container):
#   [XFBIN Header 28 bytes] [Chunk Table] [Chunk Data Area]
# The binary chunk contains XML describing UI collision rectangles
# for all game scenes (menus, character select, gallery, etc.).
# XML structure:
#   <_root>
#     <info>
#       <_array num="N">
#         <set>
#           <name>sceneName</name>
#           <_array num="M">
#             <collision>
#               <type>0|2</type>
#               <name>elementName</name>
#               <x>int</x> <y>int</y> <w>int</w> <h>int</h>
#               <rtoX>int</rtoX> <rtoY>int</rtoY>
#               <lboX>int</lboX> <lboY>int</lboY>
#             </collision>
#           </_array>
#         </set>
#       </_array>
#     </info>
#   </_root>
# Collision types:
#   0 = standard clickable/touchable area
#   2 = panel / selectable region
# Key set: "ccSceneBattleSelectChar" — 61 FaceIcon collisions
# correspond to the character select screen slots. Adding a new
# character requires adding a FaceIcon collision here.

COLLISION_FIELDS = ['type', 'name', 'x', 'y', 'w', 'h', 'rtoX', 'rtoY', 'lboX', 'lboY']
INT_FIELDS = {'type', 'x', 'y', 'w', 'h', 'rtoX', 'rtoY', 'lboX', 'lboY'}


def parse_info_xfbin(filepath):
    """Parse an info.xfbin file.

    Returns (raw_data, sets, meta):
      - raw_data: bytearray of the entire file
      - sets: list of dicts with 'name' and 'collisions' (list of collision dicts)
      - meta: dict with offsets needed for saving
    """
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    if data[:4] != b'NUCC':
        raise ValueError("Not a valid XFBIN file (missing NUCC magic)")

    chunk_table_size = struct.unpack('>I', data[16:20])[0]
    chunk_data_start = 28 + chunk_table_size
    if chunk_data_start % 4:
        chunk_data_start += 4 - (chunk_data_start % 4)

    # Scan chunks to find the binary chunk with XML
    chunks = []
    binary_chunk_idx = None
    offset = chunk_data_start

    while offset < len(data) - 11:
        size = struct.unpack('>I', data[offset:offset + 4])[0]
        header = bytes(data[offset:offset + 12])
        chunk_data_bytes = bytes(data[offset + 12:offset + 12 + size])
        chunks.append({'header': header, 'data': chunk_data_bytes, 'offset': offset})

        if size > 16 and binary_chunk_idx is None:
            binary_chunk_idx = len(chunks) - 1

        offset += 12 + size

    if binary_chunk_idx is None:
        raise ValueError("Could not find binary chunk in XFBIN")

    # Extract XML from binary payload
    bd = chunks[binary_chunk_idx]['data']
    inner_size = struct.unpack('>I', bd[0:4])[0]
    xml_bytes = bd[4:4 + inner_size]
    xml_text = xml_bytes.decode('utf-8')

    root = ET.fromstring(xml_text)
    info_elem = root.find('info')
    if info_elem is None:
        raise ValueError("Missing <info> element in XML")

    array_elem = info_elem.find('_array')
    if array_elem is None:
        raise ValueError("Missing <_array> element in XML")

    sets = []
    for set_elem in array_elem.findall('set'):
        name_elem = set_elem.find('name')
        set_name = name_elem.text if name_elem is not None else ''

        collisions = []
        coll_array = set_elem.find('_array')
        orig_array_num = None
        if coll_array is not None:
            orig_array_num = coll_array.get('num')
            for coll_elem in coll_array.findall('collision'):
                coll = {}
                for field in COLLISION_FIELDS:
                    elem = coll_elem.find(field)
                    if elem is not None and elem.text is not None:
                        coll[field] = int(elem.text) if field in INT_FIELDS else elem.text
                    else:
                        coll[field] = 0 if field in INT_FIELDS else ''
                collisions.append(coll)

        sets.append({
            'name': set_name,
            'collisions': collisions,
            '_orig_array_num': orig_array_num,
            '_orig_coll_count': len(collisions),
        })

    meta = {
        'chunk_data_start': chunk_data_start,
        'chunks': chunks,
        'binary_chunk_idx': binary_chunk_idx,
        'header_bytes': bytes(data[:chunk_data_start]),
    }

    return data, sets, meta


def _build_xml(sets):
    """Rebuild the XML string from sets data."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>']
    lines.append('<_root>')
    lines.append('\t<info>')
    lines.append(f'\t\t<_array num="{len(sets)}">')

    for s in sets:
        lines.append('\t\t\t<set>')
        lines.append(f'\t\t\t\t<name>{s["name"]}</name>')
        collisions = s['collisions']
        # If collision count changed (user added/removed), update num.
        # If unchanged, preserve original num (handles pre-existing mismatches).
        orig_num = s.get('_orig_array_num')
        orig_count = s.get('_orig_coll_count')
        if orig_num is not None and orig_count == len(collisions):
            array_num = orig_num
        else:
            array_num = str(len(collisions))
        lines.append(f'\t\t\t\t<_array num="{array_num}">')

        for coll in collisions:
            lines.append('\t\t\t\t\t<collision>')
            for field in COLLISION_FIELDS:
                val = coll.get(field, 0 if field in INT_FIELDS else '')
                lines.append(f'\t\t\t\t\t\t<{field}>{val}</{field}>')
            lines.append('\t\t\t\t\t</collision>')

        lines.append('\t\t\t\t</_array>')
        lines.append('\t\t\t</set>')

    lines.append('\t\t</_array>')
    lines.append('\t</info>')
    lines.append('</_root>')
    # Original files end with \r\n after closing tag
    return '\r\n'.join(lines) + '\r\n'


def save_info_xfbin(filepath, data, sets, meta):
    """Save sets back to an XFBIN file."""
    xml_text = _build_xml(sets)
    xml_bytes = xml_text.encode('utf-8')

    # Build binary payload: [inner_size: u32 BE] [xml_bytes]
    inner_size = len(xml_bytes)
    payload = struct.pack('>I', inner_size) + xml_bytes

    result = bytearray(meta['header_bytes'])

    for i, chunk in enumerate(meta['chunks']):
        if i == meta['binary_chunk_idx']:
            new_header = bytearray(chunk['header'])
            struct.pack_into('>I', new_header, 0, len(payload))
            result += new_header
            result += payload
        else:
            result += chunk['header']
            result += chunk['data']


    with open(filepath, 'wb') as f:
        f.write(result)


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
                'typical_size': (face_icons[0]['w'], face_icons[0]['h']) if face_icons else (54, 46),
            }
    return None
