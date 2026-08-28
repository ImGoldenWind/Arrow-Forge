from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import re
from typing import Iterable

import numpy as np
from PIL import Image

from parsers.texture_xfbin_parser import TextureEntry, load_xfbin as load_texture_xfbin, nut_tex_to_pil
from parsers.xfbin_lib import (
    NuccChunkAnm, NuccChunkClump, NuccChunkCoord, NuccChunkDynamics, NuccChunkMaterial,
    NuccChunkModel, NuccChunkTexture, read_xfbin, write_xfbin_to_path,
)


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


@dataclass
class RenderScene:
    meshes: list[RenderMesh]
    bones: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=list)
    bounds_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: tuple[float, float, float] = (0.0, 0.0, 0.0)
    coord_names: list[str] = field(default_factory=list)
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
    animation_curve_cache: dict[int, dict[str, list]] = field(default_factory=dict)
    skin_bind_vertices: np.ndarray | None = None
    skin_bind_normals: np.ndarray | None = None
    skin_bone_ids: np.ndarray | None = None
    skin_bone_weights: np.ndarray | None = None
    mesh_vertex_ranges: list[tuple[int, int]] = field(default_factory=list)
    mesh_has_normals: list[bool] = field(default_factory=list)


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
    write_xfbin_to_path(doc.xfbin, path or doc.path)
    doc.dirty = False


def build_render_scene(doc: ModelXfbinDocument) -> RenderScene:
    texture_refs = doc.all_texture_refs
    meshes: list[RenderMesh] = []
    all_vertices = []

    coord_nodes = [chunk.node for chunk in doc.coord_chunks]
    coord_index = {node: index for index, node in enumerate(coord_nodes)}
    bind_local = [_coord_local_matrix(node) for node in coord_nodes]
    bind_world_by_node = _coord_world_matrices(doc.coord_chunks)
    bind_world = [bind_world_by_node[node] for node in coord_nodes]

    for model in doc.model_chunks:
        if model.nud is None:
            continue
        mesh_counter = 0
        for group in model.nud.mesh_groups:
            for mesh in group.meshes:
                local_vertices = np.array([v.position for v in mesh.vertices], dtype=np.float32)
                model_coord_index = int(getattr(model, "coord_index", -1))
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
                ))
                if len(vertices):
                    all_vertices.append(vertices)
                mesh_counter += 1

    model_coord_indices = {
        int(model.coord_index)
        for model in doc.model_chunks
        if 0 <= int(getattr(model, "coord_index", -1)) < len(coord_nodes)
    }
    display_bone_indices = [index for index in range(len(coord_nodes)) if index not in model_coord_indices]
    bones = _bone_lines_from_world(doc.coord_chunks, bind_world, display_bone_indices)
    if all_vertices:
        stack = np.vstack(all_vertices)
        bounds_min = tuple(float(x) for x in stack.min(axis=0))
        bounds_max = tuple(float(x) for x in stack.max(axis=0))
    else:
        bounds_min = bounds_max = (0.0, 0.0, 0.0)
    parents = [coord_index.get(node.parent, -1) for node in coord_nodes]
    decomposed = [_decompose_matrix(matrix) for matrix in bind_local]
    skin_data = _combined_skin_data(meshes, len(coord_nodes))
    return RenderScene(
        meshes=meshes,
        bones=bones,
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        coord_names=[node.name for node in coord_nodes],
        coord_parents=parents,
        bind_local_matrices=bind_local,
        bind_world_matrices=bind_world,
        pose_world_matrices=[matrix.copy() for matrix in bind_world],
        inverse_bind_matrices=[np.linalg.inv(matrix) for matrix in bind_world],
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
    if skin_meshes and pose_world:
        skin_matrices = np.matmul(np.stack(pose_world), np.stack(scene.inverse_bind_matrices))
    if skin_matrices is not None and scene.skin_bind_vertices is not None and len(scene.skin_bind_vertices):
        ids = scene.skin_bone_ids
        valid = (ids >= 0) & (ids < len(skin_matrices)) & (scene.skin_bone_weights > 0.0)
        weights = np.where(valid, scene.skin_bone_weights, 0.0).astype(np.float32, copy=False)
        safe_ids = np.where(valid, ids, 0)
        matrices = skin_matrices[safe_ids]
        homogeneous = np.column_stack((scene.skin_bind_vertices, np.ones(len(ids), dtype=np.float32)))
        transformed = np.einsum("nsij,nj->nsi", matrices, homogeneous)
        deformed = np.sum(transformed[:, :, :3] * weights[:, :, None], axis=1)
        total_weights = weights.sum(axis=1)
        missing = total_weights <= 1e-6
        deformed[missing] = scene.skin_bind_vertices[missing]
        transformed_normals = np.einsum("nsij,nj->nsi", matrices[:, :, :3, :3], scene.skin_bind_normals)
        deformed_normals = np.sum(transformed_normals * weights[:, :, None], axis=1)
        deformed_normals[missing] = scene.skin_bind_normals[missing]
        view_vertices = np.ascontiguousarray(_to_view_space_array(deformed), dtype=np.float32)
        view_normals = np.ascontiguousarray(_to_view_space_array(_normalize_rows(deformed_normals)), dtype=np.float32)
        for mesh, (start, end), has_normals in zip(scene.meshes, scene.mesh_vertex_ranges, scene.mesh_has_normals):
            mesh.vertices = view_vertices[start:end]
            mesh.normals = view_normals[start:end] if has_normals else None
    scene.bones = _bone_lines_from_world_names(scene.coord_names, scene.coord_parents, pose_world, scene.display_bone_indices)
    if skin_meshes:
        visible_vertices = [mesh.vertices for mesh in scene.meshes if mesh.visible and len(mesh.vertices)]
        if visible_vertices:
            stack = np.vstack(visible_vertices)
            scene.bounds_min = tuple(float(x) for x in stack.min(axis=0))
            scene.bounds_max = tuple(float(x) for x in stack.max(axis=0))


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
        lines.append((names[idx], start, end))
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
    target_curves = scene.animation_curve_cache.get(cache_key)
    if target_curves is None:
        target_curves = {}
        best_clump = None
        scene_names = set(scene.canonical_coord_names)
        best_overlap = 0
        for clump in clip.chunk.clumps:
            overlap = sum(_canonical_bone_name(target.name) in scene_names for target in clump.bones)
            if overlap > best_overlap:
                best_overlap = overlap
                best_clump = clump
        if best_clump is not None:
            target_curves = {_canonical_bone_name(target.name): target.curves for target in best_clump.bones}
        scene.animation_curve_cache[cache_key] = target_curves

    local_matrices = []
    for index, name in enumerate(scene.coord_names):
        location = scene.bind_locations[index].copy()
        rotation = scene.bind_rotations[index].copy()
        scale = scene.bind_scales[index].copy()
        for curve in target_curves.get(scene.canonical_coord_names[index], []):
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
        parent = scene.coord_parents[index]
        world[index] = resolve(parent) @ local_matrices[index] if 0 <= parent < len(world) else local_matrices[index]
        visiting.discard(index)
        resolved.add(index)
        return world[index]

    for index in range(len(world)):
        resolve(index)
    return world


_BONE_PREFIX_RE = re.compile(r"^[^\s]+t\d+(?:_[^\s]+)?(?:\s+(.*))?$", re.IGNORECASE)


def _canonical_bone_name(name: str) -> str:
    """Ignore costume/model prefixes while retaining the actual bone name."""
    match = _BONE_PREFIX_RE.match(name or "")
    if match:
        suffix = (match.group(1) or "__model_root__").strip()
        suffix = re.sub(r"_f$", "", suffix, flags=re.IGNORECASE)
        return suffix.lower()
    return (name or "").strip().lower()


def _sample_curve(curve, frame):
    keyframes = [key for key in curve.keyframes if key.frame >= 0]
    if not keyframes:
        return None
    if frame <= keyframes[0].frame:
        return keyframes[0].value
    if frame >= keyframes[-1].frame:
        return keyframes[-1].value
    for left, right in zip(keyframes, keyframes[1:]):
        if left.frame <= frame <= right.frame:
            if not curve.interpolate or right.frame <= left.frame:
                return left.value
            amount = (frame - left.frame) / (right.frame - left.frame)
            a = np.asarray(left.value, dtype=np.float64)
            b = np.asarray(right.value, dtype=np.float64)
            if curve.data_path == "rotation_quaternion":
                return _slerp(a, b, amount)
            return a + (b - a) * amount
    return keyframes[-1].value


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
    normal_matrix = np.linalg.inv(matrix[:3, :3]).T
    return _normalize_rows(np.asarray((normal_matrix @ normals.T).T, dtype=np.float32))


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
