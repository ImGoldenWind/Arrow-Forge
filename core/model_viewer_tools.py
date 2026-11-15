"""File-backed model references and verified material storage semantics.

Keep interpretation out of Qt and rendering. Unknown words remain unknown;
limits here describe storage, never an invented gameplay range.
"""
import math
import struct
import numpy as np


def float_value(text):
    value = float(text)
    packed = struct.unpack('>f', struct.pack('>f', value))[0]
    if not math.isfinite(packed):
        raise ValueError('model_invalid_float')
    return packed


def integer_value(text, minimum, maximum):
    value = int(text, 16 if text.lower().startswith('0x') else 10)
    if not minimum <= value <= maximum:
        raise ValueError('model_invalid_integer')
    return value


def model_coordinates(model, doc):
    clump = getattr(model, 'clump_chunk', None)
    return getattr(clump, 'coord_chunks', None) or doc.coord_chunks


def assign_coordinate(model, doc, index):
    coords = model_coordinates(model, doc)
    if index != -1 and not 0 <= index < len(coords):
        raise ValueError('model_invalid_coordinate')
    model.coord_index = index
    model.coord_chunk = coords[index] if index >= 0 else None


def material_meshes(doc, material):
    for model in doc.model_chunks:
        if model.nud is None:
            continue
        index = 0
        for group in model.nud.mesh_groups:
            for mesh in group.meshes:
                refs = model.material_chunks
                ref = refs[index] if index < len(refs) else (refs[-1] if refs else None)
                if ref is material:
                    yield model, group, index, mesh
                index += 1


# D3D11 blend enumeration retained by the NUD; 0 is the native opaque
# sentinel. Labels are composed in the UI, values are never normalized.
BLEND_FACTORS = ((0, 'opaque'), (1, 'zero'), (2, 'one'), (3, 'source_color'),
                 (4, 'inverse_source_color'), (5, 'source_alpha'),
                 (6, 'inverse_source_alpha'), (7, 'destination_alpha'),
                 (8, 'inverse_destination_alpha'), (9, 'destination_color'),
                 (10, 'inverse_destination_color'))

PROPERTY_LABELS = {
    'NU_lightingParam': 'model_prop_lighting',
    'NU_msParam0': 'model_prop_tone',
    'NU_hatchingParam': 'model_prop_hatching',
    'NU_specularParam': 'model_prop_specular',
    'NU_outline0Param': 'model_prop_outline',
    'NU_Kd0': 'model_prop_diffuse_color',
    'NU_Ks': 'model_prop_specular_color',
    'NU_uvOffset0': 'model_prop_uv0',
    'NU_uvOffset1': 'model_prop_uv1',
}


def material_uv_transforms(material):
    """735520: optional offset UV / scale UV tuples, in flag order 1..8."""
    values = tuple(getattr(material, 'floats', ()))
    flags = int(getattr(material, 'format', 0))
    offset, result = 0, []
    for bit in (1, 2, 4, 8):
        if flags & bit:
            result.append(values[offset:offset + 4] if len(values) >= offset + 4 else (0., 0., 1., 1.))
            offset += 4
        else:
            result.append((0., 0., 1., 1.))
    return tuple(result)


def pick_mesh(scene, x, y, width, height, yaw, pitch, distance, center):
    """Nearest visible triangle under an orbit-camera pixel (no GPU readback)."""
    from parsers.model_xfbin_parser import _rotation_matrix_x, _rotation_matrix_y
    rotation = (_rotation_matrix_x(pitch) @ _rotation_matrix_y(yaw))[:3, :3]
    origin = np.asarray(center, np.float64) + rotation.T @ (0., 0., distance)
    tangent = math.tan(math.radians(45.) / 2)
    direction = rotation.T @ np.array(((2*x/max(1, width)-1) * width/max(1, height)*tangent,
                                      (1-2*y/max(1, height))*tangent, -1.), np.float64)
    direction /= np.linalg.norm(direction)
    nearest, selected = math.inf, None
    for mesh in scene.meshes if scene else ():
        if not mesh.visible or not len(mesh.faces):
            continue
        triangles = mesh.vertices[np.asarray(mesh.faces, np.int32)]
        edge1, edge2 = triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]
        cross = np.cross(direction, edge2)
        det = np.einsum('ij,ij->i', edge1, cross)
        valid = np.abs(det) > 1e-8
        inverse = np.divide(1., det, out=np.zeros_like(det), where=valid)
        offset = origin - triangles[:, 0]
        u = inverse * np.einsum('ij,ij->i', offset, cross)
        q = np.cross(offset, edge1)
        v = inverse * (q @ direction)
        t = inverse * np.einsum('ij,ij->i', edge2, q)
        valid &= (u >= 0) & (v >= 0) & (u+v <= 1) & (t > 0)
        if np.any(valid):
            candidate = float(t[valid].min())
            if candidate < nearest:
                nearest, selected = candidate, mesh
    return selected


def model_lighting(source):
    """Resolve authored StageInfo lighting beside the model, without game state."""
    from pathlib import Path
    from core.stage_tools import data_root
    from parsers.stageinfo_parser import parse_stageinfo_xfbin
    path = Path(source)
    if path.name.casefold() != 'stageinfo.bin.xfbin':
        root = data_root(source)
        if root is None:
            return []
        path = root / 'stage' / 'HIGH_SPEC' / 'StageInfo.bin.xfbin'
    if not path.is_file():
        return []
    _, result = parse_stageinfo_xfbin(str(path))
    return [(stage['code'], bytes(stage['params']), str(path)) for stage in result['stages']]
