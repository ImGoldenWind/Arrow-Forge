"""Self-contained, static stage lighting reference; loaded without game paths."""
import io
import json
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
from PIL import Image

from core.runtime_paths import app_path
from parsers.model_xfbin_parser import RenderMesh, RenderScene, ResolvedTextureRef


def _texture(archive, index, name, path):
    image = Image.open(io.BytesIO(archive[f't{index}'].tobytes())).convert('RGBA')
    ref = ResolvedTextureRef(name, '', None, image, path)
    ref.mip_images = [image]
    level = 1
    while f't{index}_mip{level}' in archive:
        ref.mip_images.append(Image.open(io.BytesIO(archive[f't{index}_mip{level}'].tobytes())).convert('RGBA'))
        level += 1
    return ref


@lru_cache(maxsize=1)
def common_stage_textures():
    """Shared hatching maps, also available when previewing a standalone map."""
    path = app_path('resources', 'stage_preview', 'jonathan.npz')
    refs = {}
    with np.load(path, allow_pickle=False) as archive:
        meta = json.loads(archive['metadata'].tobytes())
        for i, name in enumerate(meta['textures']):
            if name in ('haching_n', 'haching1'):
                refs[name] = _texture(archive, i, name, path)
    return refs


def load_stage_actor():
    path = app_path('resources', 'stage_preview', 'jonathan.npz')
    meshes = []
    with np.load(path, allow_pickle=False) as archive:
        meta = json.loads(archive['metadata'].tobytes())
        if meta['version'] != 1:
            raise ValueError('Unsupported preview actor version')
        textures = [_texture(archive, i, name, path) for i, name in enumerate(meta['textures'])]
        for i, item in enumerate(meta['meshes']):
            def array(name):
                key = f'm{i}_{name}'
                return archive[key].copy() if key in archive else None
            vertices, normals = array('vertices'), array('normals')
            slots = {key: textures[index] for key, index in item['textures'].items()}
            mesh = RenderMesh(name=item['name'], model_chunk=SimpleNamespace(name=item['name']),
                material_chunk=None, mesh_index=i, vertices=vertices, normals=normals,
                uvs=array('uvs'), uvs2=array('uvs2'), colors=array('colors'), faces=array('faces'),
                texture=slots.get('diffuse'), texture_slots=slots, bind_vertices=vertices,
                bind_normals=normals, bone_ids=None, bone_weights=None, bone_influences=[],
                gpu_bone_ids=np.zeros((len(vertices), 4), np.float32),
                gpu_bone_weights=np.zeros((len(vertices), 4), np.float32),
                gpu_bind_vertices=vertices, gpu_bind_normals=normals, model_coord_index=-1,
                shader_id=item['shader_id'], material_params=item['material_params'],
                source_factor=item['source_factor'], cull_mode=item['cull_mode'])
            mesh.tangent, mesh.bitangent = array('tangent'), array('bitangent')
            mesh.native_state = item.get('native_state', {})
            mesh.casts_shadow = item.get('casts_shadow', True)
            meshes.append(mesh)
    return RenderScene(meshes=meshes, bounds_min=tuple(meta['bounds'][0]), bounds_max=tuple(meta['bounds'][1]))


def place_stage_actor(actor, stage):
    """Stand at the arena origin, finding the floor directly under his feet."""
    heights = []
    for mesh in stage.meshes:
        if not mesh.visible or '_flo' not in mesh.name.casefold():
            continue
        for triangle in mesh.vertices[mesh.faces]:
            matrix = np.column_stack((triangle[:, 0], triangle[:, 2], np.ones(3)))
            try:
                weights = np.linalg.solve(matrix.T, [0., 0., 1.])
            except np.linalg.LinAlgError:
                continue
            if np.min(weights) >= -1e-5:
                heights.append(float(weights @ triangle[:, 1]))
    ground = min(heights, key=abs) if heights else 0.
    shift = np.array([0., ground - actor.bounds_min[1], 0.], np.float32)
    for mesh in actor.meshes:
        mesh.vertices = mesh.vertices + shift
    actor.bounds_min = tuple(np.asarray(actor.bounds_min) + shift)
    actor.bounds_max = tuple(np.asarray(actor.bounds_max) + shift)
    return actor
