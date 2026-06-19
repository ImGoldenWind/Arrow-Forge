from itertools import chain
from typing import List, Tuple

from .br_nud import (
    BrNud, BrNudMaterial, BrNudMaterialProperty, BrNudMaterialTexture,
    BrNudMesh, BrNudMeshGroup, BrNudVertex, NudBoneType, NudUvType,
    NudVertexType,
)


class Nud:
    """High-level NDP3/NUD model wrapper."""

    name: str
    mesh_groups: List["NudMeshGroup"]

    def init_data(self, name: str, br_nud: BrNud):
        self.name = name
        self.bounding_sphere = br_nud.boundingSphere
        self.mesh_groups = []
        for br_group in br_nud.meshGroups:
            group = NudMeshGroup()
            group.init_data(br_group)
            self.mesh_groups.append(group)

    def get_bone_range(self) -> Tuple[int, int]:
        if not (
            self.mesh_groups
            and self.mesh_groups[0].meshes
            and self.mesh_groups[0].meshes[0].bone_type != NudBoneType.NoBones
        ):
            return (0, 0)

        lower = 0xFFFF
        higher = 0
        for mesh in [m for m in self.mesh_groups[0].meshes if m.vertices and m.vertices[0].bone_ids]:
            lower = min(lower, min(chain(*[v.bone_ids for v in mesh.vertices])))
            higher = max(higher, max(chain(*[v.bone_ids for v in mesh.vertices])))
        return (0, 0) if lower > higher else (lower, higher)


class NudMeshGroup:
    name: str
    meshes: List["NudMesh"]

    def init_data(self, br_group: BrNudMeshGroup):
        self.name = br_group.name
        self.bone_flags = br_group.boneFlags
        self.bounding_sphere = br_group.boundingSphere
        self.meshes = []
        for br_mesh in br_group.meshes:
            mesh = NudMesh()
            mesh.init_data(br_mesh)
            self.meshes.append(mesh)


class NudMesh:
    MAX_VERTICES = 32767
    MAX_FACES = 16383

    vertices: List["NudVertex"]
    faces: List[Tuple[int, int, int]]
    materials: List["NudMaterial"]
    vertex_type: NudVertexType
    bone_type: NudBoneType
    uv_type: NudUvType

    def init_data(self, br_mesh: BrNudMesh):
        self.add_vertices(br_mesh.vertices)
        self.add_faces(br_mesh.faces, br_mesh.faceSize)
        self.add_materials(br_mesh.materials)
        self.vertex_type = NudVertexType(br_mesh.vertexSize & 0x0F)
        self.bone_type = NudBoneType(br_mesh.vertexSize & 0xF0)
        self.uv_type = NudUvType(br_mesh.uvSize & 0x0F)
        self.face_flag = br_mesh.faceFlag
        self.raw_tex_props = br_mesh.texProps

    def has_bones(self):
        return bool(self.vertices and self.vertices[0].bone_ids)

    def has_color(self):
        return bool(self.vertices and self.vertices[0].color)

    def get_uv_channel_count(self):
        return len(self.vertices[0].uv) if self.vertices and self.vertices[0].uv else 0

    def add_vertices(self, vertices: List[BrNudVertex]):
        self.vertices = []
        for br_vertex in vertices:
            vertex = NudVertex()
            vertex.init_data(br_vertex)
            self.vertices.append(vertex)

    def add_faces(self, faces: List[int], face_size: int):
        face_iter = iter(faces)
        if face_size & 0x40:
            self.faces = list(zip(face_iter, face_iter, face_iter))
            return

        self.faces = []
        try:
            f1 = next(face_iter)
            f2 = next(face_iter)
        except StopIteration:
            return

        face_dir = 1
        try:
            while True:
                f3 = next(face_iter)
                if f3 == -1:
                    f1 = next(face_iter)
                    f2 = next(face_iter)
                    face_dir = 1
                    continue

                face_dir = -face_dir
                if f1 != f2 and f2 != f3 and f1 != f3:
                    if face_dir > 0:
                        self.faces.append((f3, f2, f1))
                    else:
                        self.faces.append((f2, f3, f1))
                f1 = f2
                f2 = f3
        except StopIteration:
            pass

    def add_materials(self, materials: List[BrNudMaterial]):
        self.materials = []
        for br_material in materials:
            material = NudMaterial()
            material.init_data(br_material)
            self.materials.append(material)


class NudVertex:
    def init_data(self, br_vertex: BrNudVertex):
        self.position = br_vertex.position
        self.normal = br_vertex.normals
        self.bitangent = br_vertex.biTangents if br_vertex.biTangents else None
        self.tangent = br_vertex.tangents if br_vertex.tangents else None
        self.color = tuple(int(x) for x in br_vertex.color) if br_vertex.color else None
        self.uv = br_vertex.uv
        self.bone_ids = br_vertex.boneIds
        self.bone_weights = br_vertex.boneWeights


class NudMaterial:
    def init_data(self, material: BrNudMaterial):
        self.flags = material.flags
        self.sourceFactor = material.sourceFactor
        self.destFactor = material.destFactor
        self.alphaTest = material.alphaTest
        self.alphaFunction = material.alphaFunction
        self.refAlpha = material.refAlpha
        self.cullMode = material.cullMode
        self.unk1 = material.unk1
        self.unk2 = material.unk2
        self.zBufferOffset = material.zBufferOffset
        self.textures = []
        for br_texture in material.textures:
            texture = NudMaterialTexture()
            texture.init_data(br_texture)
            self.textures.append(texture)
        self.properties = []
        for br_property in [p for p in material.properties if p.name]:
            prop = NudMaterialProperty()
            prop.init_data(br_property)
            self.properties.append(prop)


class NudMaterialTexture:
    def init_data(self, texture: BrNudMaterialTexture):
        self.unk0 = texture.unk0
        self.mapMode = texture.mapMode
        self.wrapModeS = texture.wrapModeS
        self.wrapModeT = texture.wrapModeT
        self.minFilter = texture.minFilter
        self.magFilter = texture.magFilter
        self.mipDetail = texture.mipDetail
        self.unk1 = texture.unk1
        self.unk2 = texture.unk2


class NudMaterialProperty:
    def init_data(self, prop: BrNudMaterialProperty):
        self.name = prop.name
        self.values = prop.values
