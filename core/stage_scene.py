"""Read-only stage resource discovery and scene assembly for the shared renderer."""
from pathlib import Path
import copy

from core.stage_tools import data_root


def preview_roots(source, configured=''):
    roots = []
    for item in (source, configured):
        if not item:
            continue
        path = Path(item).expanduser().resolve()
        root = path if path.name.casefold() == 'data' else data_root(path)
        if root is None and (path / 'data').is_dir():
            root = path / 'data'
        if root and root not in roots:
            roots.append(root)
    return roots


def stage_resources(stage, source, configured=''):
    """Resolve authored paths and the game's _SPEC substitution, in source order."""
    roots = preview_roots(source, configured)
    values = list(stage.get('paths', [])) + [c['xfbin_path'] for c in stage.get('clumps', [])]
    values = list(dict.fromkeys(values))
    maps = [v for v in values if v.replace('\\', '/').casefold().startswith(('data/stage/', 'data/no_release/stage/'))]
    if maps:
        # Missing map geometry must not silently display an accompanying NPC
        # or palette XFBIN as if it were the selected arena.
        values = maps
    found = []
    variant = Path(source).parent.name if source else 'HIGH_SPEC'
    if not variant.upper().endswith('_SPEC') or variant == '_SPEC':
        variant = 'HIGH_SPEC'
    for value in values:
        normalized = value.replace('\\', '/')
        if not normalized.casefold().startswith('data/'):
            continue
        relative = normalized[5:]
        quality_path = '/'.join(variant if part.casefold() == '_spec' else part for part in relative.split('/'))
        alternatives = [quality_path, relative]
        if relative.casefold().startswith('stage/') and '/' not in relative[6:]:
            alternatives.append('stage/' + variant + '/' + relative[6:])
        for root in roots:
            for candidate in alternatives:
                path = (root / candidate).resolve()
                if path.is_relative_to(root) and path.is_file() and str(path) not in found:
                    found.append(str(path))
                    break
    return found


def load_stage_scene(path, stage):
    """Use the existing mesh/texture decoder, selecting the stage's clump graph."""
    import numpy as np
    from parsers.model_xfbin_parser import load_model_xfbin, build_render_scene
    root = data_root(path)
    common = root / 'spc/0cmn01bod1.xfbin' if root else None
    doc = load_model_xfbin(str(path), [str(common)] if common and common.is_file() else [])
    from core.stage_actor import common_stage_textures
    for name, ref in common_stage_textures().items():
        doc.external_textures.setdefault(name, ref)
    # Stage XFBINs contain many independent clumps. The character-viewer's
    # primary-clump heuristic would omit most of the map or include spare VFX.
    names = {c['clump_name'] for c in stage.get('clumps', [])
             if Path(c['xfbin_path'].replace('\\', '/')).name.casefold() == Path(path).name.casefold()}
    selected = [c for c in doc.clump_chunks if c.name in names]
    owners = {}
    if selected:
        models, coords = {}, {}
        for clump in selected:
            for coord in clump.coord_chunks:
                coords[id(coord)] = coord
            for model in [*clump.model_chunks, *(m for g in clump.model_groups for m in g.model_chunks)]:
                if model is not None and hasattr(model, 'nud'):
                    models[id(model)] = model
                    owners[id(model)] = clump.name.casefold()
        doc = copy.copy(doc)
        doc.model_chunks, doc.coord_chunks, doc.clump_chunks = list(models.values()), list(coords.values()), []
    scene = build_render_scene(doc)
    if not scene.meshes:
        raise ValueError('stage_preview_no_geometry')
    for mesh in scene.meshes:
        # The original material vertex shaders consume the authored tangent
        # frame as well as normals (normal maps and cross-hatching).
        from parsers.model_xfbin_parser import _transform_normals, _to_view_space_array
        original = [m for g in mesh.model_chunk.nud.mesh_groups for m in g.meshes][mesh.mesh_index]
        from core.stage_materials import material_state
        mesh.native_state = material_state(mesh.material_chunk, original.materials[0] if original.materials else None)
        mesh.casts_shadow = bool(int(mesh.model_chunk.rigging_flag) & 0x20)
        matrix = (scene.bind_world_matrices[mesh.model_coord_index]
                  if 0 <= mesh.model_coord_index < len(scene.bind_world_matrices) else np.eye(4))
        for key in ('tangent', 'bitangent'):
            values = [getattr(v, key, None) for v in original.vertices]
            setattr(mesh, key, _to_view_space_array(_transform_normals(np.asarray(values, np.float32)[:, :3], matrix))
                    if values and all(v is not None for v in values) else None)
        # Stage shadow/light maps are not tangent-space normal maps. The
        # character texture-slot fallback otherwise produces invalid lighting.
        normal = mesh.texture_slots.get('normal')
        if normal and 'shadow' in getattr(normal, 'name', '').casefold():
            mesh.texture_slots['shadowmap'] = mesh.texture_slots.pop('normal')
    # Sky/background shells and hit meshes must not determine the initial
    # camera distance. They retain their authored geometry in the scene.
    core, floors = [], []
    for mesh in scene.meshes:
        name = owners.get(id(mesh.model_chunk), '') + ' ' + mesh.name.casefold()
        collision_names = (owners.get(id(mesh.model_chunk), ''), mesh.model_chunk.name.casefold())
        collision = any(n.endswith('hit') or '_hit' in n or 'gimmick_area' in n for n in collision_names)
        mesh.visible = not collision
        if mesh.visible and not any(word in name for word in ('_bac', 'sky', 'cloud', '_far', '_eff')) and len(mesh.vertices):
            core.append(mesh.vertices)
            if '_flo' in name and len(mesh.vertices) > 3:
                span = np.ptp(mesh.vertices, axis=0)
                if span[1] <= max(5., max(span[0], span[2]) * .15):
                    floors.append(mesh.vertices)
    if core:
        # Background scenery can be kilometres wide. Frame a representative
        # floor mesh initially; orbit/pan/zoom still reaches all map geometry.
        if floors:
            floors.sort(key=lambda a: float(np.ptp(a, axis=0).max()))
            points = floors[len(floors) // 2]
        else:
            points = np.concatenate(core)
        scene.bounds_min = tuple(float(v) for v in points.min(axis=0))
        scene.bounds_max = tuple(float(v) for v in points.max(axis=0))
    return scene
