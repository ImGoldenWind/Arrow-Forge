from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable

import numpy as np
from PIL import Image

from parsers.texture_xfbin_parser import TextureEntry, load_xfbin as load_texture_xfbin, nut_tex_to_pil
from parsers.xfbin_lib import (
    NuccChunkClump, NuccChunkCoord, NuccChunkDynamics, NuccChunkMaterial,
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
    colors: np.ndarray | None
    faces: np.ndarray
    texture: ResolvedTextureRef | MissingTextureRef | None
    texture_slots: dict[str, ResolvedTextureRef | MissingTextureRef]
    visible: bool = True


@dataclass
class RenderScene:
    meshes: list[RenderMesh]
    bones: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=list)
    bounds_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: tuple[float, float, float] = (0.0, 0.0, 0.0)


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

    for model in doc.model_chunks:
        if model.nud is None:
            continue
        mesh_counter = 0
        for group in model.nud.mesh_groups:
            for mesh in group.meshes:
                vertices = np.array([v.position for v in mesh.vertices], dtype=np.float32)
                vertices = _to_view_space_array(vertices)
                faces = np.array(mesh.faces, dtype=np.int32) if mesh.faces else np.zeros((0, 3), dtype=np.int32)
                normals = _array_or_none([v.normal for v in mesh.vertices], np.float32)
                if normals is not None:
                    normals = _to_view_space_array(normals)
                uvs = _first_uv_array(mesh.vertices)
                colors = _array_or_none([v.color for v in mesh.vertices], np.float32)
                if colors is not None:
                    colors = colors / 255.0
                material = _material_for_mesh(model, mesh_counter)
                texture_slots = _textures_for_material(material, texture_refs)
                texture = texture_slots.get("diffuse") or _primary_texture_for_material(material, texture_refs)
                meshes.append(RenderMesh(
                    name=f"{model.name} / {group.name} / {mesh_counter + 1}",
                    model_chunk=model,
                    material_chunk=material,
                    mesh_index=mesh_counter,
                    vertices=vertices,
                    normals=normals,
                    uvs=uvs,
                    colors=colors,
                    faces=faces,
                    texture=texture,
                    texture_slots=texture_slots,
                ))
                if len(vertices):
                    all_vertices.append(vertices)
                mesh_counter += 1

    bones = _build_bone_lines(doc.coord_chunks)
    if all_vertices:
        stack = np.vstack(all_vertices)
        bounds_min = tuple(float(x) for x in stack.min(axis=0))
        bounds_max = tuple(float(x) for x in stack.max(axis=0))
    else:
        bounds_min = bounds_max = (0.0, 0.0, 0.0)
    return RenderScene(meshes=meshes, bones=bones, bounds_min=bounds_min, bounds_max=bounds_max)


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


def _textures_for_material(material: NuccChunkMaterial | None, texture_refs: dict[str, ResolvedTextureRef]) -> dict[str, ResolvedTextureRef | MissingTextureRef]:
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
            result.setdefault(f"slot_{slot_idx}", resolved)
            result.setdefault(role, resolved)
            slot_idx += 1
    return result


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
    uvs = []
    for vertex in vertices:
        if not vertex.uv:
            return None
        u, v = vertex.uv[0]
        uvs.append((u, 1.0 - v))
    return np.array(uvs, dtype=np.float32)


def _build_bone_lines(coord_chunks: list[NuccChunkCoord]):
    lines = []
    world_positions = _coord_world_positions(coord_chunks)
    for chunk in coord_chunks:
        node = chunk.node
        if node.parent is None:
            continue
        start_raw = world_positions.get(node.parent)
        end_raw = world_positions.get(node)
        if start_raw is None or end_raw is None:
            continue
        start = _to_view_space_point(start_raw)
        end = _to_view_space_point(end_raw)
        lines.append((node.name, start, end))
    return lines


def _coord_world_positions(coord_chunks: list[NuccChunkCoord]) -> dict[object, tuple[float, float, float]]:
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

    result = {}
    for chunk in coord_chunks:
        world = matrix_for(chunk.node)
        result[chunk.node] = tuple(float(x) for x in world[:3, 3])
    return result


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
