from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
import copy
import math
import os
import re
import tempfile
from typing import Iterable

import numpy as np
from PIL import Image

from parsers.texture_xfbin_parser import TextureEntry, load_xfbin as load_texture_xfbin, nut_tex_to_pil
from parsers.xfbin_lib import (
    NuccChunkAnm, NuccChunkClump, NuccChunkCoord, NuccChunkDynamics, NuccChunkMaterial,
    NuccChunkModel, NuccChunkTexture, read_xfbin, write_xfbin,
)
from parsers.xfbin_lib.br_anm import AnmEntryFormat


@dataclass
class MissingTextureRef:
    name: str
    file_path: str = ""


@dataclass
class ResolvedTextureRef:
    name: str
    file_path: str
    chunk: object | None
    pil_image: Image.Image | None
    source_path: str


@dataclass
class RenderMesh:
    name: str
    model_chunk: NuccChunkModel
    material_chunk: NuccChunkMaterial | None
    mesh_index: int
    vertices: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    uvs2: np.ndarray | None
    colors: np.ndarray | None
    faces: np.ndarray
    texture: ResolvedTextureRef | MissingTextureRef | None
    texture_slots: dict[str, ResolvedTextureRef | MissingTextureRef]
    bind_vertices: np.ndarray
    bind_normals: np.ndarray | None
    bone_ids: np.ndarray | None
    bone_weights: np.ndarray | None
    bone_influences: list[tuple[int, np.ndarray, np.ndarray]]
    gpu_bone_ids: np.ndarray
    gpu_bone_weights: np.ndarray
    gpu_bind_vertices: np.ndarray
    gpu_bind_normals: np.ndarray | None
    model_coord_index: int
    shader_id: int = 0
    material_params: dict[str, tuple[float, ...]] = field(default_factory=dict)
    source_factor: int = 0
    cull_mode: int = 0
    visible: bool = True
    native_state: dict = field(default_factory=dict)
    tangent: np.ndarray | None = None
    bitangent: np.ndarray | None = None
    bind_tangent: np.ndarray | None = None
    bind_bitangent: np.ndarray | None = None
    direction_influences: list = field(default_factory=list)


@dataclass
class RenderScene:
    meshes: list[RenderMesh]
    bones: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=list)
    bounds_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: tuple[float, float, float] = (0.0, 0.0, 0.0)
    coord_names: list[str] = field(default_factory=list)
    coord_identities: list[tuple[str, str, str]] = field(default_factory=list)
    coord_parents: list[int] = field(default_factory=list)
    bind_local_matrices: list[np.ndarray] = field(default_factory=list)
    bind_world_matrices: list[np.ndarray] = field(default_factory=list)
    pose_world_matrices: list[np.ndarray] = field(default_factory=list)
    inverse_bind_matrices: list[np.ndarray] = field(default_factory=list)
    display_bone_indices: list[int] = field(default_factory=list)
    bind_locations: np.ndarray | None = None
    bind_rotations: np.ndarray | None = None
    bind_scales: np.ndarray | None = None
    canonical_coord_names: list[str] = field(default_factory=list)
    animation_curve_cache: dict[int, tuple[dict[int, list], list[int]]] = field(default_factory=dict)
    skin_bind_vertices: np.ndarray | None = None
    skin_bind_normals: np.ndarray | None = None
    skin_bone_ids: np.ndarray | None = None
    skin_bone_weights: np.ndarray | None = None
    mesh_vertex_ranges: list[tuple[int, int]] = field(default_factory=list)
    mesh_has_normals: list[bool] = field(default_factory=list)
    cpu_skin_cache: dict = field(default_factory=dict, repr=False)


@dataclass
class AnimationClip:
    name: str
    source_path: str
    chunk: NuccChunkAnm

    @property
    def frame_count(self) -> int:
        size = max(1, int(self.chunk.frame_size))
        return max(0, int(round(self.chunk.frame_count / size)))

    @property
    def looped(self) -> bool:
        return bool(self.chunk.loop_flag)


@dataclass
class ModelXfbinDocument:
    path: str
    xfbin: object
    model_chunks: list[NuccChunkModel]
    coord_chunks: list[NuccChunkCoord]
    material_chunks: list[NuccChunkMaterial]
    texture_chunks: list[NuccChunkTexture]
    clump_chunks: list[NuccChunkClump]
    dynamics_chunks: list[NuccChunkDynamics]
    external_textures: dict[str, ResolvedTextureRef] = field(default_factory=dict)
    dirty: bool = False
    source_bytes: bytes = b''
    chunk_baselines: dict = field(default_factory=dict)
    primary_clump_name: str = ''

    @property
    def all_texture_refs(self) -> dict[str, ResolvedTextureRef]:
        refs: dict[str, ResolvedTextureRef] = {}
        for chunk in self.texture_chunks:
            ref = _texture_ref_from_chunk(chunk, self.path)
            if ref:
                refs[_texture_key(chunk.name)] = ref
                refs[_texture_key(chunk.filePath)] = ref
        refs.update(self.external_textures)
        return refs


def load_model_xfbin(
    model_path: str,
    texture_paths: Iterable[str] | None = None,
    *,
    palette_alias_index: int | None = None,
) -> ModelXfbinDocument:
    xfbin = read_xfbin(model_path)
    doc = ModelXfbinDocument(
        path=model_path,
        xfbin=xfbin,
        model_chunks=_chunks_of_type(xfbin, NuccChunkModel),
        coord_chunks=_chunks_of_type(xfbin, NuccChunkCoord),
        material_chunks=_chunks_of_type(xfbin, NuccChunkMaterial),
        texture_chunks=_chunks_of_type(xfbin, NuccChunkTexture),
        clump_chunks=_chunks_of_type(xfbin, NuccChunkClump),
        dynamics_chunks=_chunks_of_type(xfbin, NuccChunkDynamics),
    )
    for tex_path in texture_paths or []:
        add_texture_xfbin(doc, tex_path, palette_alias_index=palette_alias_index)
    doc.source_bytes = Path(model_path).read_bytes()
    doc.primary_clump_name = Path(model_path).stem.casefold()
    for page in xfbin.pages:
        for chunk in page.chunks:
            if isinstance(chunk, (NuccChunkCoord, NuccChunkMaterial, NuccChunkModel, NuccChunkDynamics)) and chunk.has_props:
                doc.chunk_baselines[id(chunk)] = _chunk_storage(chunk, page)
    return doc


def add_texture_xfbin(doc: ModelXfbinDocument, texture_path: str, *, palette_alias_index: int | None = None) -> int:
    _, entries = load_texture_xfbin(texture_path)
    added = 0
    for entry in entries:
        ref = ResolvedTextureRef(
            name=entry.name,
            file_path=entry.file_path,
            chunk=entry.chunk,
            pil_image=entry.pil_image,
            source_path=texture_path,
        )
        keys = {_texture_key(entry.name), _texture_key(entry.file_path)}
        if palette_alias_index is not None:
            keys.add(_texture_key(_texture_palette_alias(entry.name, palette_alias_index)))
            keys.add(_texture_key(_texture_palette_alias(entry.file_path, palette_alias_index)))
        for key in keys:
            if key:
                doc.external_textures[key] = ref
        added += 1
    return added


def save_model_xfbin(doc: ModelXfbinDocument, path: str | None = None) -> None:
    target_path = str(path or doc.path)
    data = _model_storage(doc)
    directory = os.path.dirname(os.path.abspath(target_path))
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(target_path)}.",
        suffix=".arrowforge.tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        parsed = read_xfbin(temp_path)
        if not getattr(parsed, "pages", None):
            raise ValueError(f"Round-trip validation failed for {os.path.basename(target_path)}")
        os.replace(temp_path, target_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    doc.path = target_path
    doc.dirty = False


def _chunk_storage(chunk, page):
    from parsers.xfbin_lib.binary_reader import BinaryReader, Endian
    from parsers.xfbin_lib.br_nucc import BrNuccChunk
    from parsers.xfbin_lib.iterative_dict import IterativeDict
    indices = IterativeDict()
    indices.update_or_next(page.initial_page_chunks)
    writer = BrNuccChunk.get_br_nucc_type_from_str(type(chunk).__name__)()
    writer.nuccChunk = chunk
    with BinaryReader(endianness=Endian.BIG) as stream:
        stream.write_struct(writer, indices)
        return bytes(stream.buffer())


def _model_storage(doc):
    """Keep untouched NUDs/opaque chunks verbatim, even when a neighbour changes.

    Canonical serializer snapshots detect edits without deep-copying the model
    graph. Temporary raw wrappers keep the live document untouched on failure.
    """
    if not doc.source_bytes or not doc.chunk_baselines:
        return bytes(write_xfbin(doc.xfbin))
    rebuild_table = False
    for page in doc.xfbin.pages:
        for chunk in page.chunks:
            if isinstance(chunk, NuccChunkMaterial):
                for group in chunk.texture_groups:
                    if any(ref not in page.initial_page_chunks for ref in group.texture_chunks):
                        rebuild_table = True
    changed = {}
    for page in doc.xfbin.pages:
        for chunk in page.chunks:
            baseline = doc.chunk_baselines.get(id(chunk))
            if baseline is not None:
                current = _chunk_storage(chunk, page)
                if current != baseline:
                    if isinstance(chunk, NuccChunkMaterial) and len(chunk.floats) != chunk.float_count(chunk.format):
                        raise ValueError('model_material_layout_mismatch')
                    if isinstance(chunk, NuccChunkModel) and bool(chunk.material_flags[1] & 4) != bool(chunk.flag1_floats):
                        raise ValueError('model_model_layout_mismatch')
                    changed[id(chunk)] = current
    if not changed:
        return doc.source_bytes
    if rebuild_table:
        from parsers.xfbin_lib.nucc import NuccChunkNull, NuccChunkPage, NuccChunkIndex
        xfbin = copy.copy(doc.xfbin)
        xfbin.pages = []
        for page in doc.xfbin.pages:
            output = copy.copy(page)
            output.chunks = []
            # Page/Index occupy the tail of the authored table. The writer
            # regenerates them after appending any new texture references.
            dependencies = [c for c in page.initial_page_chunks
                            if not isinstance(c, (NuccChunkPage, NuccChunkIndex))]
            for chunk in page.chunks:
                if id(chunk) in changed or isinstance(chunk, (NuccChunkNull, NuccChunkPage, NuccChunkIndex)):
                    output.chunks.append(chunk)
                else:
                    raw = copy.copy(chunk)
                    raw.has_props = False
                    raw.chunks = dependencies
                    output.chunks.append(raw)
            xfbin.pages.append(output)
        return bytes(write_xfbin(xfbin))
    # Ordinary parameter edits keep the authored chunk index table. Replace
    # envelopes in the original stream; untouched payloads and table bytes are
    # never reserialized. Model NUD size changes are local to its envelope.
    from parsers.xfbin_lib.binary_reader import BinaryReader, Endian
    from parsers.xfbin_lib.br_xfbin import BrNuccHeader, BrChunkTable
    from parsers.xfbin_lib.nucc import NuccChunkPage
    import struct
    with BinaryReader(doc.source_bytes, Endian.BIG, 'cp932') as stream:
        stream.read_struct(BrNuccHeader)
        stream.read_struct(BrChunkTable)
        offset = stream.pos()
    output = bytearray(doc.source_bytes[:offset])
    page_index = 0
    while offset < len(doc.source_bytes):
        size, index = struct.unpack_from('>II', doc.source_bytes, offset)
        page = doc.xfbin.pages[page_index]
        chunk = page.initial_page_chunks[index]
        current = changed.get(id(chunk))
        original = doc.source_bytes[offset + 12:offset + 12 + size]
        if current is None:
            output.extend(doc.source_bytes[offset:offset + 12 + size])
        else:
            baseline = doc.chunk_baselines[id(chunk)]
            if len(current) == len(baseline) == len(original):
                current = bytes(new if old != new else source
                                for source, old, new in zip(original, baseline, current))
            output.extend(struct.pack('>I', len(current)))
            output.extend(doc.source_bytes[offset + 4:offset + 12])
            output.extend(current)
        offset += 12 + size
        if isinstance(chunk, NuccChunkPage):
            page_index += 1
    return bytes(output)


def _primary_clump_for_document(doc: ModelXfbinDocument) -> NuccChunkClump | None:
    stem = getattr(doc, 'primary_clump_name', '') or Path(doc.path).stem.casefold()
    return next(
        (clump for clump in doc.clump_chunks if str(clump.name).casefold() == stem),
        None,
    )


def _render_coords_for_document(doc: ModelXfbinDocument) -> list[NuccChunkCoord]:
    """Use only the Coord graph owned by the primary rendered Clump."""
    primary = _primary_clump_for_document(doc)
    if primary is not None and primary.coord_chunks:
        return list(primary.coord_chunks)
    return list(doc.coord_chunks)


def _render_models_for_document(doc: ModelXfbinDocument) -> list[NuccChunkModel]:
    """Select the models owned by the XFBIN's primary Clump.

    Character body files commonly contain extra effect Clumps and stale Model
    chunks on the same NUCC page.  Rendering every page-level Model is not how
    the Clump contract works and makes detached model parts appear as
    exploded geometry.  Prefer the Clump whose name matches the file stem and
    preserve the old all-model fallback for files without such a primary
    Clump.
    """
    primary = _primary_clump_for_document(doc)
    if primary is None:
        return list(doc.model_chunks)

    candidates = list(primary.model_chunks)
    if not candidates:
        candidates = [
            model
            for group in primary.model_groups
            for model in group.model_chunks
            if model is not None
        ]
    selected = []
    seen = set()
    for model in candidates:
        if not isinstance(model, NuccChunkModel) or id(model) in seen:
            continue
        seen.add(id(model))
        selected.append(model)
    return selected


def build_render_scene(doc: ModelXfbinDocument) -> RenderScene:
    texture_refs = doc.all_texture_refs
    meshes: list[RenderMesh] = []
    all_vertices = []

    coord_chunks = _render_coords_for_document(doc)
    coord_nodes = [chunk.node for chunk in coord_chunks]
    coord_index = {node: index for index, node in enumerate(coord_nodes)}
    bind_local = [_coord_local_matrix(node) for node in coord_nodes]
    bind_world_by_node = _coord_world_matrices(coord_chunks)
    bind_world = [bind_world_by_node[node] for node in coord_nodes]

    for model in _render_models_for_document(doc):
        if model.nud is None:
            continue
        mesh_counter = 0
        for group in model.nud.mesh_groups:
            for mesh in group.meshes:
                local_vertices = np.array([v.position for v in mesh.vertices], dtype=np.float32)
                model_coord_index = _model_global_coord_index(model, coord_index)
                model_matrix = bind_world[model_coord_index] if 0 <= model_coord_index < len(bind_world) else np.identity(4, dtype=np.float32)
                bind_vertices = _transform_points(local_vertices, model_matrix)
                vertices = _to_view_space_array(bind_vertices)
                faces = np.array(mesh.faces, dtype=np.int32) if mesh.faces else np.zeros((0, 3), dtype=np.int32)
                normals = _array_or_none([v.normal for v in mesh.vertices], np.float32)
                if normals is not None:
                    bind_normals = _transform_normals(normals, model_matrix)
                    normals = _to_view_space_array(bind_normals)
                else:
                    bind_normals = None
                uvs = _first_uv_array(mesh.vertices)
                uvs2 = _uv_array(mesh.vertices, 1)
                colors = _array_or_none([v.color for v in mesh.vertices], np.float32)
                if colors is not None:
                    colors = colors / 255.0
                material = _material_for_mesh(model, mesh_counter)
                nud_material = mesh.materials[0] if mesh.materials else None
                shader_id = int(getattr(nud_material, "flags", 0))
                texture_slots = _textures_for_material(material, texture_refs, shader_id)
                texture = texture_slots.get("diffuse") or _primary_texture_for_material(material, texture_refs)
                bone_ids, bone_weights = _bone_arrays(mesh.vertices)
                bone_ids = _global_bone_ids(model, bone_ids, coord_index)
                gpu_bone_ids, gpu_bone_weights = _gpu_bone_arrays(
                    len(mesh.vertices), bone_ids, bone_weights, model_coord_index, len(coord_nodes)
                )
                meshes.append(RenderMesh(
                    name=f"{model.name} / {group.name} / {mesh_counter + 1}",
                    model_chunk=model,
                    material_chunk=material,
                    mesh_index=mesh_counter,
                    vertices=vertices,
                    normals=normals,
                    uvs=uvs,
                    uvs2=uvs2,
                    colors=colors,
                    faces=faces,
                    texture=texture,
                    texture_slots=texture_slots,
                    bind_vertices=bind_vertices,
                    bind_normals=bind_normals,
                    bone_ids=bone_ids,
                    bone_weights=bone_weights,
                    bone_influences=_bone_influences(bone_ids, bone_weights),
                    gpu_bone_ids=gpu_bone_ids,
                    gpu_bone_weights=gpu_bone_weights,
                    gpu_bind_vertices=np.ascontiguousarray(vertices.copy(), dtype=np.float32),
                    gpu_bind_normals=np.ascontiguousarray(normals.copy(), dtype=np.float32) if normals is not None else None,
                    model_coord_index=model_coord_index,
                    shader_id=shader_id,
                    material_params=_material_properties(nud_material),
                    source_factor=int(getattr(nud_material, "sourceFactor", 0)),
                    cull_mode=int(getattr(nud_material, "cullMode", 0)),
                    direction_influences=_bone_influences(gpu_bone_ids.astype(np.int32), gpu_bone_weights),
                ))
                from core.stage_materials import material_state
                rendered = meshes[-1]
                rendered.native_state = material_state(material, nud_material)
                for key in ('tangent', 'bitangent'):
                    values = _array_or_none([getattr(v, key, None) for v in mesh.vertices], np.float32)
                    if values is not None:
                        bind = _transform_normals(values[:, :3], model_matrix)
                        setattr(rendered, 'bind_' + key, bind)
                        setattr(rendered, key, _to_view_space_array(bind))
                if len(vertices):
                    all_vertices.append(vertices)
                mesh_counter += 1

    model_coord_indices = {mesh.model_coord_index for mesh in meshes if mesh.model_coord_index >= 0}
    skin_data = _combined_skin_data(meshes, len(coord_nodes))
    skin_ids, skin_weights = skin_data[2], skin_data[3]
    if skin_ids is not None and skin_weights is not None:
        used_bone_indices = {
            int(index)
            for index in skin_ids[skin_weights > 0.0]
            if 0 <= int(index) < len(coord_nodes)
        }
        display_bone_indices = sorted(used_bone_indices - model_coord_indices)
    else:
        display_bone_indices = [
            index for index in range(len(coord_nodes))
            if index not in model_coord_indices
        ]
    bones = _bone_lines_from_world(coord_chunks, bind_world, display_bone_indices)
    if all_vertices:
        stack = np.vstack(all_vertices)
        bounds_min = tuple(float(x) for x in stack.min(axis=0))
        bounds_max = tuple(float(x) for x in stack.max(axis=0))
    else:
        bounds_min = bounds_max = (0.0, 0.0, 0.0)
    parents = [coord_index.get(node.parent, -1) for node in coord_nodes]
    decomposed = [_decompose_matrix(matrix) for matrix in bind_local]
    return RenderScene(
        meshes=meshes,
        bones=bones,
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        coord_names=[node.name for node in coord_nodes],
        coord_identities=[_chunk_identity(chunk) for chunk in coord_chunks],
        coord_parents=parents,
        bind_local_matrices=bind_local,
        bind_world_matrices=bind_world,
        pose_world_matrices=[matrix.copy() for matrix in bind_world],
        inverse_bind_matrices=[_inverse_matrix(matrix) for matrix in bind_world],
        display_bone_indices=display_bone_indices,
        bind_locations=np.stack([value[0] for value in decomposed]) if decomposed else np.zeros((0, 3), dtype=np.float32),
        bind_rotations=np.stack([value[1] for value in decomposed]) if decomposed else np.zeros((0, 3, 3), dtype=np.float32),
        bind_scales=np.stack([value[2] for value in decomposed]) if decomposed else np.zeros((0, 3), dtype=np.float32),
        canonical_coord_names=[_canonical_bone_name(node.name) for node in coord_nodes],
        skin_bind_vertices=skin_data[0],
        skin_bind_normals=skin_data[1],
        skin_bone_ids=skin_data[2],
        skin_bone_weights=skin_data[3],
        mesh_vertex_ranges=skin_data[4],
        mesh_has_normals=skin_data[5],
    )


def load_animation_clips(paths: Iterable[str]) -> list[AnimationClip]:
    clips = []
    seen = set()
    for path in paths:
        if not path or not Path(path).is_file():
            continue
        xfbin = read_xfbin(path)
        for chunk in _chunks_of_type(xfbin, NuccChunkAnm):
            key = (chunk.name.lower(), str(Path(path).resolve()).lower())
            if key in seen:
                continue
            seen.add(key)
            clips.append(AnimationClip(chunk.name, str(path), chunk))
    return clips


def apply_animation(scene: RenderScene, clip: AnimationClip | None, frame: float, *, skin_meshes: bool = True) -> None:
    """Evaluate a clip and optionally CPU-skin the preview using the NUD bind matrices."""
    if clip is None:
        pose_world = [matrix.copy() for matrix in scene.bind_world_matrices]
    else:
        pose_world = _animation_pose(scene, clip, frame)
    scene.pose_world_matrices = pose_world
    skin_matrices = None
    skinned = False
    if skin_meshes and pose_world:
        skin_matrices = np.matmul(np.stack(pose_world), np.stack(scene.inverse_bind_matrices))
    if skin_matrices is not None and scene.skin_bind_vertices is not None and len(scene.skin_bind_vertices):
        _skin_scene_cpu(scene, skin_matrices)
        skinned = True
    scene.bones = _bone_lines_from_world_names(scene.coord_names, scene.coord_parents, pose_world, scene.display_bone_indices)
    if skin_meshes and not skinned:
        for mesh in scene.meshes:
            for key in ('tangent', 'bitangent'):
                bind = getattr(mesh, 'bind_' + key, None)
                if bind is None:
                    continue
                result = bind.copy()
                if skin_matrices is not None:
                    result[:] = 0
                    total = np.zeros(len(bind), np.float32)
                    for index, indices, weights in mesh.direction_influences:
                        if not 0 <= index < len(skin_matrices):
                            continue
                        result[indices] += _transform_directions(bind[indices], skin_matrices[index]) * weights[:, None]
                        total[indices] += weights
                    missing = total <= 1e-6
                    result[missing] = bind[missing]
                setattr(mesh, key, _to_view_space_array(_normalize_rows(result)))
    if skin_meshes:
        visible_vertices = [mesh.vertices for mesh in scene.meshes if mesh.visible and len(mesh.vertices)]
        if visible_vertices:
            stack = np.vstack(visible_vertices)
            scene.bounds_min = tuple(float(x) for x in stack.min(axis=0))
            scene.bounds_max = tuple(float(x) for x in stack.max(axis=0))


def _skin_scene_cpu(scene, palette):
    """Blend one affine matrix per vertex, then transform its whole tangent frame.

    The old implementation allocated N×4×4×4 palettes every frame and executed
    two Python loops over thousands of bone groups for tangents. Bind data and
    validated influences are immutable for the lifetime of a RenderScene.
    """
    key = (id(scene.skin_bind_vertices), id(scene.skin_bone_ids), len(palette))
    cache = scene.cpu_skin_cache
    if cache.get('key') != key:
        ids, weights = scene.skin_bone_ids, scene.skin_bone_weights
        valid = (ids >= 0) & (ids < len(palette)) & (weights > 0)
        safe_ids = np.where(valid, ids, 0)
        weights = np.where(valid, weights, 0).astype(np.float32)
        directions = np.zeros((len(ids), 3, 3), np.float32)
        directions[:, :, 0] = scene.skin_bind_normals
        for mesh, (start, end) in zip(scene.meshes, scene.mesh_vertex_ranges):
            for column, name in ((1, 'bind_tangent'), (2, 'bind_bitangent')):
                values = getattr(mesh, name, None)
                if values is not None:
                    directions[start:end, :, column] = values
        direction_ids = np.concatenate([m.gpu_bone_ids.astype(np.int32) for m in scene.meshes])
        direction_weights = np.concatenate([m.gpu_bone_weights for m in scene.meshes])
        direction_valid = (direction_ids >= 0) & (direction_ids < len(palette)) & (direction_weights > 0)
        direction_ids = np.where(direction_valid, direction_ids, 0)
        direction_weights = np.where(direction_valid, direction_weights, 0).astype(np.float32)
        cache.clear()
        cache.update(key=key, ids=safe_ids, weights=weights, missing=weights.sum(axis=1) <= 1e-6,
                     directions=directions, direction_ids=direction_ids, direction_weights=direction_weights,
                     direction_missing=direction_weights.sum(axis=1) <= 1e-6,
                     same_directions=np.array_equal(safe_ids, direction_ids) and np.array_equal(weights, direction_weights))

    def blend(ids, weights):
        result = np.zeros((len(ids), 3, 4), np.float32)
        for slot in range(ids.shape[1]):
            result += palette[ids[:, slot], :3, :] * weights[:, slot, None, None]
        return result

    matrices = blend(cache['ids'], cache['weights'])
    deformed = np.einsum('nij,nj->ni', matrices[:, :, :3], scene.skin_bind_vertices) + matrices[:, :, 3]
    deformed[cache['missing']] = scene.skin_bind_vertices[cache['missing']]
    directions = np.matmul(matrices[:, :, :3], cache['directions'])
    directions[cache['missing']] = cache['directions'][cache['missing']]
    if not cache['same_directions']:
        other = blend(cache['direction_ids'], cache['direction_weights'])
        directions[:, :, 1:] = np.matmul(other[:, :, :3], cache['directions'][:, :, 1:])
        missing = cache['direction_missing']
        directions[missing, :, 1:] = cache['directions'][missing, :, 1:]
    lengths = np.linalg.norm(directions, axis=1, keepdims=True)
    directions /= np.where(lengths > 1e-8, lengths, 1.)
    view_vertices = _to_view_space_array(deformed)
    view_directions = directions[:, [0, 2, 1], :].copy()
    view_directions[:, 2, :] *= -1
    for mesh, (start, end), has_normals in zip(scene.meshes, scene.mesh_vertex_ranges, scene.mesh_has_normals):
        mesh.vertices = view_vertices[start:end]
        mesh.normals = np.ascontiguousarray(view_directions[start:end, :, 0]) if has_normals else None
        for column, name in ((1, 'tangent'), (2, 'bitangent')):
            if getattr(mesh, 'bind_' + name, None) is not None:
                setattr(mesh, name, np.ascontiguousarray(view_directions[start:end, :, column]))


def available_texture_refs(doc: ModelXfbinDocument) -> list[ResolvedTextureRef]:
    seen = set()
    refs = []
    for ref in doc.all_texture_refs.values():
        key = (_texture_key(ref.name), _texture_key(ref.file_path))
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return sorted(refs, key=lambda r: (r.name or r.file_path).lower())


def material_texture_refs(material: NuccChunkMaterial | None, doc: ModelXfbinDocument):
    texture_refs = doc.all_texture_refs
    result = []
    if material is None:
        return result
    for group_idx, group in enumerate(material.texture_groups):
        for slot_idx, texture_chunk in enumerate(group.texture_chunks):
            result.append((group_idx, slot_idx, texture_chunk, _resolve_texture(texture_chunk, texture_refs)))
    return result


def set_material_texture(material: NuccChunkMaterial, group_idx: int, slot_idx: int, texture_ref: ResolvedTextureRef) -> None:
    material.texture_groups[group_idx].texture_chunks[slot_idx] = texture_ref.chunk


def _chunks_of_type(xfbin, cls):
    return [chunk for page in xfbin.pages for chunk in page.chunks if isinstance(chunk, cls)]


def _texture_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.replace("\\", "/").lower().strip()
    return Path(normalized).stem if "/" in normalized else normalized


def _texture_palette_alias(value: str | None, palette_index: int) -> str:
    if not value:
        return ""
    return re.sub(r"#\d+", f"#{palette_index}", value)


def _texture_ref_from_chunk(chunk: NuccChunkTexture, source_path: str) -> ResolvedTextureRef | None:
    pil_image = None
    if getattr(chunk, "nut", None) and chunk.nut.textures:
        pil_image = nut_tex_to_pil(chunk.nut.textures[0])
    if pil_image is None and not getattr(chunk, "nut", None):
        return None
    return ResolvedTextureRef(
        name=chunk.name,
        file_path=chunk.filePath,
        chunk=chunk,
        pil_image=pil_image,
        source_path=source_path,
    )


def _resolve_texture(chunk, texture_refs: dict[str, ResolvedTextureRef]):
    if chunk is None:
        return None
    for key in (_texture_key(getattr(chunk, "name", "")), _texture_key(getattr(chunk, "filePath", ""))):
        if key and key in texture_refs:
            return texture_refs[key]
    return MissingTextureRef(getattr(chunk, "name", ""), getattr(chunk, "filePath", ""))


def _primary_texture_for_material(material: NuccChunkMaterial | None, texture_refs: dict[str, ResolvedTextureRef]):
    if material is None:
        return None
    for group in material.texture_groups:
        for chunk in group.texture_chunks:
            resolved = _resolve_texture(chunk, texture_refs)
            if isinstance(resolved, ResolvedTextureRef):
                return resolved
    for group in material.texture_groups:
        for chunk in group.texture_chunks:
            missing = _resolve_texture(chunk, texture_refs)
            if missing is not None:
                return missing
    return None


def _textures_for_material(material: NuccChunkMaterial | None, texture_refs: dict[str, ResolvedTextureRef], shader_id: int = 0) -> dict[str, ResolvedTextureRef | MissingTextureRef]:
    result: dict[str, ResolvedTextureRef | MissingTextureRef] = {}
    if material is None:
        return result
    slot_idx = 0
    for group in material.texture_groups:
        for chunk in group.texture_chunks:
            resolved = _resolve_texture(chunk, texture_refs)
            if resolved is None:
                slot_idx += 1
                continue
            role = _texture_role(getattr(chunk, "name", "") or getattr(chunk, "filePath", ""), slot_idx)
            if shader_id == 0x1F130 and slot_idx == 1:
                role = "detail"
            result.setdefault(f"slot_{slot_idx}", resolved)
            result.setdefault(role, resolved)
            slot_idx += 1
    return result


def _material_properties(material) -> dict[str, tuple[float, ...]]:
    if material is None:
        return {}
    return {
        prop.name: tuple(float(value) for value in prop.values)
        for prop in getattr(material, "properties", [])
    }


def _bone_arrays(vertices):
    if not vertices or not any(vertex.bone_ids for vertex in vertices):
        return None, None
    width = max(len(vertex.bone_ids or ()) for vertex in vertices)
    ids = np.full((len(vertices), width), -1, dtype=np.int32)
    weights = np.zeros((len(vertices), width), dtype=np.float32)
    for row, vertex in enumerate(vertices):
        vertex_ids = tuple(vertex.bone_ids or ())
        vertex_weights = tuple(vertex.bone_weights or ())
        ids[row, :len(vertex_ids)] = vertex_ids
        weights[row, :min(len(vertex_ids), len(vertex_weights))] = vertex_weights[:len(vertex_ids)]
    sums = weights.sum(axis=1)
    valid = sums > 1e-6
    weights[valid] /= sums[valid, None]
    return ids, weights


def _model_global_coord_index(model, global_coord_index) -> int:
    coord_chunk = getattr(model, "coord_chunk", None)
    node = getattr(coord_chunk, "node", None)
    if node is not None:
        return int(global_coord_index.get(node, -1))
    # Older/synthetic documents may not have their clump references resolved.
    index = int(getattr(model, "coord_index", -1))
    return index if 0 <= index < len(global_coord_index) else -1


def _global_bone_ids(model, ids, global_coord_index):
    """Translate NUD bone IDs from their clump-local table into scene indices."""
    if ids is None:
        return None
    clump = getattr(model, "clump_chunk", None)
    coord_chunks = getattr(clump, "coord_chunks", None)
    if not coord_chunks:
        return ids
    mapping = np.full(len(coord_chunks), -1, dtype=np.int32)
    for local_index, coord_chunk in enumerate(coord_chunks):
        mapping[local_index] = global_coord_index.get(getattr(coord_chunk, "node", None), -1)
    valid = (ids >= 0) & (ids < len(mapping))
    result = np.full(ids.shape, -1, dtype=np.int32)
    result[valid] = mapping[ids[valid]]
    return result


def _bone_influences(ids, weights):
    if ids is None or weights is None:
        return []
    result = []
    for bone_id in np.unique(ids[weights > 0.0]):
        bone_id = int(bone_id)
        for slot in range(ids.shape[1]):
            indices = np.flatnonzero((ids[:, slot] == bone_id) & (weights[:, slot] > 0.0))
            if len(indices):
                result.append((bone_id, indices, weights[indices, slot].copy()))
    return result


def _gpu_bone_arrays(vertex_count, ids, weights, model_coord_index, bone_count):
    gpu_ids = np.zeros((vertex_count, 4), dtype=np.float32)
    gpu_weights = np.zeros((vertex_count, 4), dtype=np.float32)
    if ids is not None and weights is not None:
        width = min(4, ids.shape[1])
        valid = (ids[:, :width] >= 0) & (ids[:, :width] < bone_count)
        gpu_ids[:, :width] = np.where(valid, ids[:, :width], 0)
        gpu_weights[:, :width] = np.where(valid, weights[:, :width], 0.0)
        totals = gpu_weights.sum(axis=1)
        weighted = totals > 1e-6
        gpu_weights[weighted] /= totals[weighted, None]
    elif 0 <= model_coord_index < bone_count:
        gpu_ids[:, 0] = float(model_coord_index)
        gpu_weights[:, 0] = 1.0
    return gpu_ids, gpu_weights


def _combined_skin_data(meshes, bone_count):
    if not meshes:
        empty3 = np.zeros((0, 3), dtype=np.float32)
        empty_ids = np.zeros((0, 1), dtype=np.int32)
        return empty3, empty3.copy(), empty_ids, empty_ids.astype(np.float32), [], []
    slot_count = max((mesh.bone_ids.shape[1] if mesh.bone_ids is not None else 1) for mesh in meshes)
    vertex_count = sum(len(mesh.bind_vertices) for mesh in meshes)
    vertices = np.zeros((vertex_count, 3), dtype=np.float32)
    normals = np.zeros((vertex_count, 3), dtype=np.float32)
    ids = np.full((vertex_count, slot_count), -1, dtype=np.int32)
    weights = np.zeros((vertex_count, slot_count), dtype=np.float32)
    ranges = []
    has_normals = []
    start = 0
    for mesh in meshes:
        end = start + len(mesh.bind_vertices)
        ranges.append((start, end))
        vertices[start:end] = mesh.bind_vertices
        normal_present = mesh.bind_normals is not None
        has_normals.append(normal_present)
        if normal_present:
            normals[start:end] = mesh.bind_normals
        if mesh.bone_ids is not None and mesh.bone_weights is not None:
            width = mesh.bone_ids.shape[1]
            ids[start:end, :width] = mesh.bone_ids
            weights[start:end, :width] = mesh.bone_weights
        elif 0 <= mesh.model_coord_index < bone_count:
            ids[start:end, 0] = mesh.model_coord_index
            weights[start:end, 0] = 1.0
        start = end
    return vertices, normals, ids, weights, ranges, has_normals


def _texture_role(name: str, slot_idx: int | None = None) -> str:
    lowered = (name or "").lower()
    if "haching" in lowered or "hatching" in lowered:
        if lowered.endswith("_n") or "_n_" in lowered or lowered.endswith("_n#0"):
            return "hatching_normal"
        return "hatching"
    if re.search(r"(?:^|[_/-])n(?:[#_.-]|\d|$)", lowered):
        return "normal"
    if re.search(r"(?:^|[_/-])s(?:[#_.-]|\d|$)", lowered):
        return "specular"
    if re.search(r"(?:^|[_/-])m(?:[#_.-]|\d|$)", lowered):
        return "mask"
    if re.search(r"(?:^|[_/-])d(?:[#_.-]|\d|$)", lowered):
        return "diffuse"
    if slot_idx == 0:
        return "diffuse"
    if slot_idx == 1:
        return "normal"
    if slot_idx == 2:
        return "hatching_normal"
    if slot_idx == 3:
        return "hatching"
    if slot_idx == 4:
        return "mask"
    if slot_idx == 5:
        return "specular"
    return "diffuse"


def _material_for_mesh(model: NuccChunkModel, mesh_index: int):
    if not model.material_chunks:
        return None
    if mesh_index < len(model.material_chunks):
        return model.material_chunks[mesh_index]
    return model.material_chunks[-1]


def _array_or_none(values, dtype):
    if not values or any(v is None for v in values):
        return None
    return np.array(values, dtype=dtype)


def _to_view_space_array(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    transformed = np.empty_like(values, dtype=np.float32)
    transformed[:, 0] = values[:, 0]
    transformed[:, 1] = values[:, 2]
    transformed[:, 2] = -values[:, 1]
    return transformed


def _to_view_space_point(value) -> tuple[float, float, float]:
    return (float(value[0]), float(value[2]), -float(value[1]))


def _first_uv_array(vertices):
    return _uv_array(vertices, 0)


def _uv_array(vertices, channel):
    uvs = []
    for vertex in vertices:
        if not vertex.uv or channel >= len(vertex.uv):
            return None
        u, v = vertex.uv[channel]
        uvs.append((u, 1.0 - v))
    return np.array(uvs, dtype=np.float32)


def _build_bone_lines(coord_chunks: list[NuccChunkCoord]):
    matrices = _coord_world_matrices(coord_chunks)
    ordered = [matrices[chunk.node] for chunk in coord_chunks]
    return _bone_lines_from_world(coord_chunks, ordered)


def _bone_lines_from_world(coord_chunks, matrices, display_indices=None):
    index = {chunk.node: idx for idx, chunk in enumerate(coord_chunks)}
    names = [chunk.node.name for chunk in coord_chunks]
    parents = [index.get(chunk.node.parent, -1) for chunk in coord_chunks]
    return _bone_lines_from_world_names(names, parents, matrices, display_indices)


def _bone_lines_from_world_names(names, parents, matrices, display_indices=None):
    lines = []
    indices = display_indices if display_indices is not None else range(len(parents))
    for idx in indices:
        parent_idx = parents[idx]
        if not (0 <= parent_idx < len(matrices)):
            continue
        start = _to_view_space_point(matrices[parent_idx][:3, 3])
        end = _to_view_space_point(matrices[idx][:3, 3])
        # A Coord stores a joint pivot.  The segment from parent pivot to this
        # pivot is the parent's anatomical bone (upperarm->forearm is the
        # upper arm, forearm->hand is the forearm).  Labelling it with the
        # child made a correctly placed hand joint look as if "hand" lived in
        # the forearm.  Use the segment owner, matching Blender bone display.
        lines.append((names[parent_idx], start, end))
    return lines


def _coord_world_positions(coord_chunks: list[NuccChunkCoord]) -> dict[object, tuple[float, float, float]]:
    matrices = _coord_world_matrices(coord_chunks)
    return {node: tuple(float(x) for x in matrix[:3, 3]) for node, matrix in matrices.items()}


def _coord_world_matrices(coord_chunks: list[NuccChunkCoord]) -> dict[object, np.ndarray]:
    matrices: dict[object, np.ndarray] = {}
    visiting: set[object] = set()

    def matrix_for(node) -> np.ndarray:
        if node in matrices:
            return matrices[node]
        if node in visiting:
            return _coord_local_matrix(node)
        visiting.add(node)
        local = _coord_local_matrix(node)
        if node.parent is not None:
            world = matrix_for(node.parent) @ local
        else:
            world = local
        visiting.discard(node)
        matrices[node] = world
        return world

    for chunk in coord_chunks:
        matrix_for(chunk.node)
    return matrices


def _animation_pose(scene: RenderScene, clip: AnimationClip, frame: float) -> list[np.ndarray]:
    raw_frame = float(frame) * max(1, int(clip.chunk.frame_size))
    cache_key = id(clip.chunk)
    cached = scene.animation_curve_cache.get(cache_key)
    if cached is None:
        cached = _resolved_animation_contract(scene, clip)
        scene.animation_curve_cache[cache_key] = cached
    target_curves, pose_parents = cached

    local_matrices = []
    for index, name in enumerate(scene.coord_names):
        location = scene.bind_locations[index].copy()
        rotation = scene.bind_rotations[index].copy()
        scale = scene.bind_scales[index].copy()
        for curve in target_curves.get(index, []):
            value = _sample_curve(curve, raw_frame)
            if value is None:
                continue
            if curve.data_path == "location":
                location = np.asarray(value, dtype=np.float32)[:3]
            elif curve.data_path == "scale":
                scale = np.abs(np.asarray(value, dtype=np.float32)[:3])
            elif curve.data_path == "rotation_euler":
                rotation = _euler_matrix(value)[:3, :3]
            elif curve.data_path == "rotation_quaternion":
                rotation = _quaternion_matrix(value)[:3, :3]
        matrix = np.identity(4, dtype=np.float32)
        matrix[:3, :3] = rotation @ np.diag(scale)
        matrix[:3, 3] = location
        local_matrices.append(matrix)

    world = [np.identity(4, dtype=np.float32) for _ in local_matrices]
    visiting = set()
    resolved = set()

    def resolve(index):
        if index in resolved:
            return world[index]
        if index in visiting:
            return local_matrices[index]
        visiting.add(index)
        parent = pose_parents[index]
        world[index] = resolve(parent) @ local_matrices[index] if 0 <= parent < len(world) else local_matrices[index]
        visiting.discard(index)
        resolved.add(index)
        return world[index]

    for index in range(len(world)):
        resolve(index)
    return world


def _chunk_identity(chunk) -> tuple[str, str, str]:
    """Return the XFBIN reference identity used by ANM target tables."""
    type_name = type(chunk).__name__
    nucc_type = type_name[0].lower() + type_name[1:]
    return nucc_type, str(getattr(chunk, "filePath", "")), str(getattr(chunk, "name", ""))


def _resolved_animation_contract(
    scene: RenderScene,
    clip: AnimationClip,
) -> tuple[dict[int, list], list[int]]:
    """Resolve curves and parent overrides by exact Coord identity.

    An ANM can reference several clumps which contain identically named bones.
    The previous viewer collapsed all of those targets to a canonical bone
    name and kept the first curve it encountered.  In 1jnt01ghh1, for example,
    that selected a common/effect clump instead of the body clump and reversed
    the evaluated arm directions by roughly 160 degrees.  XFBIN does not bind
    animation by a display-name suffix: it binds the full chunk identity
    (type, file path and name), so the preview must do the same.
    """
    identities = list(scene.coord_identities)
    if len(identities) != len(scene.coord_names):
        identities = [
            ("nuccChunkCoord", "", str(name)) for name in scene.coord_names
        ]
    exact: dict[tuple[str, str, str], list[int]] = {}
    canonical: dict[str, list[int]] = {}
    for index, (identity, name) in enumerate(zip(identities, scene.coord_names)):
        exact.setdefault(tuple(identity), []).append(index)
        canonical.setdefault(_canonical_bone_name(name), []).append(index)

    def resolve_exact(target) -> int | None:
        matches = exact.get(_chunk_identity(target.chunk), ())
        return matches[0] if len(matches) == 1 else None

    def resolve_fallback(target) -> int | None:
        # Retain support for older motion files whose external filePath differs
        # only because they address another costume variant.  Ambiguous names
        # are deliberately rejected instead of silently selecting a clump.
        fallback = canonical.get(_canonical_bone_name(target.name), ())
        return fallback[0] if len(fallback) == 1 else None

    target_curves: dict[int, list] = {}
    fallback_entries = []
    for entry in getattr(clip.chunk, "entries", ()):
        if (
            entry.entry_format != AnmEntryFormat.BONE
            or entry.target is None
            or not entry.curves
        ):
            continue
        index = resolve_exact(entry.target)
        if index is None:
            fallback_entries.append(entry)
            continue
        # Multiple entries for one exact Coord would be an ambiguous runtime
        # contract.  Combine disjoint channels but let the later entry replace
        # a channel of the same data path, matching serialized entry order.
        merged = {
            curve.data_path: curve for curve in target_curves.get(index, ())
        }
        merged.update({curve.data_path: curve for curve in entry.curves})
        target_curves[index] = list(merged.values())

    # Costume-variant fallback is lower priority than any exact target.  This
    # matters for clips containing both the character body and 0cmn: their
    # suffixes are intentionally alike, but the common-rig curves must never
    # overwrite an exact body Coord merely because they appear later.
    for entry in fallback_entries:
        index = resolve_fallback(entry.target)
        if index is not None and index not in target_curves:
            target_curves[index] = list(entry.curves)

    pose_parents = list(scene.coord_parents)
    fallback_relations = []
    exact_parent_children = set()
    for clump in getattr(clip.chunk, "clumps", ()):
        for target in getattr(clump, "children", ()):
            if target.parent is None:
                continue
            child_index = resolve_exact(target)
            parent_index = resolve_exact(target.parent)
            if child_index is not None and parent_index is not None:
                pose_parents[child_index] = parent_index
                exact_parent_children.add(child_index)
            else:
                fallback_relations.append((target.parent, target))
    for parent, child in fallback_relations:
        child_index = resolve_fallback(child)
        parent_index = resolve_fallback(parent)
        if (
            child_index is not None
            and parent_index is not None
            and child_index not in exact_parent_children
        ):
            pose_parents[child_index] = parent_index
    return target_curves, pose_parents


_BONE_PREFIX_RE = re.compile(r"^.+?\d{2}t\d+(?:_[^\s]+)?(?:\s+(.*))?$", re.IGNORECASE)


def _canonical_bone_name(name: str) -> str:
    """Ignore costume/model prefixes while retaining the actual bone name."""
    match = _BONE_PREFIX_RE.match(name or "")
    if match:
        suffix = (match.group(1) or "__model_root__").strip()
        suffix = re.sub(r"_f$", "", suffix, flags=re.IGNORECASE)
        return suffix.lower()
    normalized = (name or "").strip()
    # Effect clumps keep the character code in every coord name. Normalize the
    # costume digit so bod1 animation clumps also match bod2/bod3 variants.
    normalized = re.sub(
        r"^(?P<base>.*?)(?P<variant>\d)(?P<slot>\d)(?=_)",
        lambda value: f"{value.group('base')}0{value.group('slot')}",
        normalized,
        count=1,
    )
    return normalized.lower()


def _sample_curve(curve, frame):
    keyframes = curve.sample_keyframes
    if not keyframes:
        keyframes = tuple(key for key in curve.keyframes if key.frame >= 0)
        curve.sample_keyframes = keyframes
        curve.sample_frames = tuple(key.frame for key in keyframes)
    if not keyframes:
        return None
    if frame <= keyframes[0].frame:
        return keyframes[0].value
    if frame >= keyframes[-1].frame:
        return keyframes[-1].value
    right_index = bisect_right(curve.sample_frames, frame)
    left = keyframes[right_index - 1]
    right = keyframes[right_index]
    if not curve.interpolate or right.frame <= left.frame:
        return left.value
    amount = (frame - left.frame) / (right.frame - left.frame)
    a = np.asarray(left.value, dtype=np.float64)
    b = np.asarray(right.value, dtype=np.float64)
    if curve.data_path == "rotation_quaternion":
        return _slerp(a, b, amount)
    return a + (b - a) * amount


def _decompose_matrix(matrix):
    location = matrix[:3, 3].copy()
    basis = matrix[:3, :3]
    scale = np.linalg.norm(basis, axis=0)
    safe_scale = np.where(scale > 1e-8, scale, 1.0)
    rotation = basis / safe_scale
    return location, rotation, scale


def _euler_matrix(value):
    rx, ry, rz = (float(component) for component in value[:3])
    return _rotation_matrix_x(rx) @ _rotation_matrix_y(ry) @ _rotation_matrix_z(rz)


def _quaternion_matrix(value):
    x, y, z, w = (float(component) for component in value[:4])
    # NUCC animation quaternions use the inverse convention; this is the same
    # conversion performed by Blender-XFBIN-Importer.
    x, y, z = -x, -y, -z
    length = math.sqrt(w*w + x*x + y*y + z*z) or 1.0
    w, x, y, z = w/length, x/length, y/length, z/length
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w), 0.0],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w), 0.0],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float32)


def _slerp(a, b, amount):
    a = a / (np.linalg.norm(a) or 1.0)
    b = b / (np.linalg.norm(b) or 1.0)
    dot = float(np.dot(a, b))
    if dot < 0.0:
        b = -b
        dot = -dot
    if dot > 0.9995:
        result = a + (b - a) * amount
        return result / (np.linalg.norm(result) or 1.0)
    theta = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta = math.sin(theta)
    return (math.sin((1.0 - amount) * theta) / sin_theta) * a + (math.sin(amount * theta) / sin_theta) * b


def _transform_points(points, matrix):
    if points.size == 0:
        return points.astype(np.float32, copy=True)
    homogeneous = np.column_stack((points, np.ones(len(points), dtype=np.float32)))
    return np.asarray((matrix @ homogeneous.T).T[:, :3], dtype=np.float32)


def _transform_normals(normals, matrix):
    normal_matrix = _inverse_matrix(matrix[:3, :3]).T
    return _normalize_rows(np.asarray((normal_matrix @ normals.T).T, dtype=np.float32))


def _inverse_matrix(matrix):
    try:
        return np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        # Zero-scale model axes are editable. A degenerate transform should
        # flatten geometry, not unwind a Qt callback or destroy the document.
        return np.linalg.pinv(matrix).astype(np.float32)


def _transform_directions(vectors, matrix):
    return np.asarray((matrix[:3, :3] @ vectors.T).T, dtype=np.float32)


def _normalize_rows(values):
    lengths = np.linalg.norm(values, axis=1)
    safe = np.where(lengths > 1e-8, lengths, 1.0)
    return values / safe[:, None]


def _coord_local_matrix(node) -> np.ndarray:
    matrix = np.identity(4, dtype=np.float32)
    matrix[:3, 3] = np.array(node.position, dtype=np.float32)
    rx, ry, rz = (float(v) for v in node.rotation)
    sx, sy, sz = (float(v) for v in node.scale)
    matrix = matrix @ _rotation_matrix_x(rx)
    matrix = matrix @ _rotation_matrix_y(ry)
    matrix = matrix @ _rotation_matrix_z(rz)
    matrix = matrix @ np.diag([sx, sy, sz, 1.0]).astype(np.float32)
    return matrix


def _rotation_matrix_x(degrees: float) -> np.ndarray:
    radians = np.deg2rad(degrees)
    c = float(np.cos(radians))
    s = float(np.sin(radians))
    return np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, c, -s, 0.0],
        [0.0, s, c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float32)


def _rotation_matrix_y(degrees: float) -> np.ndarray:
    radians = np.deg2rad(degrees)
    c = float(np.cos(radians))
    s = float(np.sin(radians))
    return np.array([
        [c, 0.0, s, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [-s, 0.0, c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float32)


def _rotation_matrix_z(degrees: float) -> np.ndarray:
    radians = np.deg2rad(degrees)
    c = float(np.cos(radians))
    s = float(np.sin(radians))
    return np.array([
        [c, -s, 0.0, 0.0],
        [s, c, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float32)
