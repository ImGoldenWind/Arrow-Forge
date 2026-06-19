from enum import IntFlag
from typing import List

from .binary_reader import BrStruct, BinaryReader, Endian, Whence


class BrNud(BrStruct):
    """Binary reader/writer for CC2 NDP3/NUD model data."""

    def __br_read__(self, br: BinaryReader) -> None:
        self.magic = br.read_str(4)
        if self.magic != "NDP3":
            raise ValueError(f"Invalid NUD magic: {self.magic!r}")

        self.fileSize = br.read_uint32()
        self.version = br.read_uint16()
        self.meshGroupCount = br.read_uint16()
        self.boneStart = br.read_uint16()
        self.boneEnd = br.read_uint16()

        self.polyClumpStart = br.read_uint32() + 0x30
        self.polyClumpSize = br.read_uint32()
        self.vertClumpStart = self.polyClumpStart + self.polyClumpSize
        self.vertClumpSize = br.read_uint32()
        self.vertAddClumpStart = self.vertClumpStart + self.vertClumpSize
        self.vertAddClumpSize = br.read_uint32()
        self.nameStart = self.vertAddClumpStart + self.vertAddClumpSize
        self.boundingSphere = br.read_float(4)

        self.meshGroups = br.read_struct(BrNudMeshGroup, self.meshGroupCount, self)
        for group in self.meshGroups:
            group.meshes = br.read_struct(BrNudMesh, group.meshCount, self)

    def __br_write__(self, br: BinaryReader, nud):
        buffers = NudBuffers()
        with BinaryReader(endianness=Endian.BIG) as inner:
            mesh_group_count = len(nud.mesh_groups)
            mesh_count = sum(len(group.meshes) for group in nud.mesh_groups)
            for group in nud.mesh_groups:
                inner.write_struct(BrNudMeshGroup(), group, buffers, mesh_group_count, mesh_count)
            inner.extend(buffers.meshes.buffer())
            inner.extend(buffers.materials.buffer())
            inner.align(0x10)
            inner.seek(0, Whence.END)
            mesh_groups_buffer = inner.buffer()

        br.write_str("NDP3")
        br.write_uint32(0)
        br.write_uint16(0x0200)
        br.write_uint16(len(nud.mesh_groups))
        br.write_uint16(nud.get_bone_range())
        br.write_uint32(len(mesh_groups_buffer))
        br.write_uint32(0)
        br.write_uint32(0)
        br.write_uint32(0)
        br.write_float(nud.bounding_sphere)
        br.extend(mesh_groups_buffer)
        br.seek(0, Whence.END)

        for idx, other in enumerate(buffers):
            br.extend(other.buffer())
            if idx < 3:
                with br.seek_to(0x10 + (4 * (idx + 1))):
                    br.write_uint32(other.size() + br.align(0x10))
            br.seek(0, Whence.END)

        with br.seek_to(0x4):
            br.write_uint32(br.size())


class NudBuffers:
    def __init__(self):
        self.meshes = BinaryReader(endianness=Endian.BIG)
        self.materials = BinaryReader(endianness=Endian.BIG)
        self.polyClump = BinaryReader(endianness=Endian.BIG)
        self.vertClump = BinaryReader(endianness=Endian.BIG)
        self.vertAddClump = BinaryReader(endianness=Endian.BIG)
        self.names = BinaryReader(endianness=Endian.BIG)

    def __iter__(self):
        return iter([self.polyClump, self.vertClump, self.vertAddClump, self.names])


class BrNudMeshGroup(BrStruct):
    meshes: List["BrNudMesh"]

    def __br_read__(self, br: BinaryReader, nud: BrNud) -> None:
        self.boundingSphere = br.read_float(8)
        self.nameStart = br.read_uint32()
        with br.seek_to(self.nameStart + nud.nameStart):
            self.name = br.read_str()
        self.unk = br.read_uint16()
        self.boneFlags = br.read_uint16()
        self.singleBind = br.read_int16()
        self.meshCount = br.read_int16()
        self.positionb = br.read_uint32()

    def __br_write__(self, br: BinaryReader, mesh_group, buffers: NudBuffers, mesh_groups_count, mesh_count):
        br.write_float(mesh_group.bounding_sphere)
        buffers.names.align(0x10)
        br.write_uint32(buffers.names.size())
        buffers.names.write_str(mesh_group.name, True)
        br.write_uint16(0)
        br.write_uint16(mesh_group.bone_flags)
        br.write_int16(-1)
        br.write_int16(len(mesh_group.meshes))
        br.write_uint32(buffers.meshes.size() + 0x30 + (mesh_groups_count * 0x30))
        for mesh in mesh_group.meshes:
            buffers.meshes.write_struct(BrNudMesh(), mesh, buffers, mesh_groups_count, mesh_count)


class BrNudMesh(BrStruct):
    def __br_read__(self, br: BinaryReader, nud: BrNud) -> None:
        self.polyClumpStart = br.read_uint32() + nud.polyClumpStart
        self.vertClumpStart = br.read_uint32() + nud.vertClumpStart
        self.vertAddClumpStart = br.read_uint32() + nud.vertAddClumpStart
        self.vertexCount = br.read_uint16()
        self.vertexSize = br.read_uint8()
        self.uvSize = br.read_uint8()
        self.texProps = br.read_uint32(4)
        self.faceCount = br.read_uint16()
        self.faceSize = br.read_uint8()
        self.faceFlag = br.read_uint8()
        br.seek(0xC, Whence.CUR)

        with br.seek_to(self.polyClumpStart):
            self.faces = br.read_int16(self.faceCount)

        with br.seek_to(self.vertClumpStart):
            bone_type = self.vertexSize & 0xF0
            vertex_type = self.vertexSize & 0x0F
            colors = []
            uvs = []
            if bone_type > 0:
                uv_count = self.uvSize >> 4
                uv_type = self.uvSize & 0x0F
                for _ in range(self.vertexCount):
                    if uv_type == NudUvType.Null:
                        colors.append(tuple())
                    elif uv_type == NudUvType.Byte:
                        colors.append(br.read_uint8(4))
                    elif uv_type == NudUvType.HalfFloat:
                        colors.append(tuple(int(x * 255) for x in br.read_half_float(4)))
                    else:
                        colors.append(tuple())
                    channels = []
                    for _ in range(uv_count):
                        channels.append(br.read_half_float(2))
                    uvs.append(channels)
                br.seek(self.vertAddClumpStart)

            self.vertices = br.read_struct(BrNudVertex, self.vertexCount, vertex_type, bone_type, self.uvSize)
            if bone_type > 0:
                for idx in range(self.vertexCount):
                    self.vertices[idx].color = colors[idx]
                    self.vertices[idx].uv = uvs[idx]

        self.materials: List[BrNudMaterial] = []
        for tex_prop in self.texProps:
            if tex_prop == 0:
                break
            with br.seek_to(tex_prop):
                self.materials.append(br.read_struct(BrNudMaterial, None, self, nud.nameStart))

    def __br_write__(self, br: BinaryReader, mesh, buffers: NudBuffers, mesh_groups_count, mesh_count):
        vertex_type = mesh.vertex_type
        bone_type = mesh.bone_type if mesh.has_bones() else NudBoneType.NoBones
        uv_type = mesh.uv_type if mesh.has_color() else NudUvType.Null

        br.write_uint32(buffers.polyClump.size())
        br.write_uint32(buffers.vertClump.size())
        br.write_uint32(buffers.vertAddClump.size() if bone_type else 0)
        br.write_uint16(len(mesh.vertices))
        br.write_uint8(int(vertex_type | bone_type))
        br.write_uint8((mesh.get_uv_channel_count() << 4) | int(uv_type))

        tex_props = [0] * 4
        for idx, material in enumerate(mesh.materials[:4]):
            tex_props[idx] = buffers.materials.size() + 0x30 + (mesh_groups_count * 0x30) + (mesh_count * 0x30)
            buffers.materials.write_struct(BrNudMaterial(), material, buffers)
        br.write_uint32(tex_props)

        if mesh.faces:
            br.write_uint16((len(mesh.faces) * 4) - 1)
        else:
            br.write_uint16(0)
        br.write_uint8(0)
        br.write_uint8(mesh.face_flag)
        br.write_uint32([0] * 3)

        if mesh.faces:
            for face in mesh.faces[:-1]:
                buffers.polyClump.write_int16((face[2], face[0], face[1]))
                buffers.polyClump.write_int16(-1)
            buffers.polyClump.write_int16((mesh.faces[-1][2], mesh.faces[-1][0], mesh.faces[-1][1]))

        vertex_br = buffers.vertClump
        if bone_type != NudBoneType.NoBones:
            vertex_br = buffers.vertAddClump
            for vertex in mesh.vertices:
                if uv_type == NudUvType.Byte:
                    buffers.vertClump.write_uint8(vertex.color or (255, 255, 255, 255))
                elif uv_type == NudUvType.HalfFloat:
                    buffers.vertClump.write_half_float(tuple((c / 255.0) for c in (vertex.color or (255, 255, 255, 255))))
                for uv in vertex.uv or []:
                    buffers.vertClump.write_half_float(uv)

        for vertex in mesh.vertices:
            vertex_br.write_struct(BrNudVertex(), vertex, vertex_type, bone_type, uv_type)
        buffers.vertAddClump.align(4)


class NudVertexType(IntFlag):
    NoNormals = 0
    NormalsFloat = 1
    Unknown = 2
    NormalsTanBiTanFloat = 3
    NormalsHalfFloat = 6
    NormalsTanBiTanHalfFloat = 7


class NudBoneType(IntFlag):
    NoBones = 0
    Float = 0x10
    HalfFloat = 0x20
    Byte = 0x40


class NudUvType(IntFlag):
    Null = 0
    Byte = 2
    HalfFloat = 4


class BrNudVertex(BrStruct):
    def __br_read__(self, br: BinaryReader, vertex_type, bone_type, uv_size) -> None:
        self.position = br.read_float(3)
        self.normals = None
        self.biTangents = None
        self.tangents = None
        self.color = None
        self.uv = None
        self.boneIds = None
        self.boneWeights = None

        if vertex_type == NudVertexType.NoNormals:
            br.read_float()
        elif vertex_type == NudVertexType.NormalsFloat:
            br.read_float()
            self.normals = br.read_float(3)
            br.read_float()
        elif vertex_type == NudVertexType.Unknown:
            self.normals = br.read_float(3)
            br.read_float()
            br.read_float(3)
            br.read_float(3)
            br.read_float(3)
        elif vertex_type == NudVertexType.NormalsTanBiTanFloat:
            br.read_float()
            self.normals = br.read_float(3)
            br.read_float()
            self.biTangents = br.read_float(4)
            self.tangents = br.read_float(4)
        elif vertex_type == NudVertexType.NormalsHalfFloat:
            self.normals = br.read_half_float(3)
            br.read_half_float()
        elif vertex_type == NudVertexType.NormalsTanBiTanHalfFloat:
            self.normals = br.read_half_float(3)
            br.read_half_float()
            self.biTangents = br.read_half_float(4)
            self.tangents = br.read_half_float(4)
        else:
            raise ValueError(f"Unsupported vertex type: {vertex_type}")

        if bone_type == NudBoneType.NoBones:
            if uv_size >= 18:
                self.color = br.read_uint8(4)
            self.uv = []
            for _ in range(uv_size >> 4):
                self.uv.append(br.read_half_float(2))
        elif bone_type == NudBoneType.Float:
            self.boneIds = br.read_uint32(4)
            self.boneWeights = br.read_float(4)
        elif bone_type == NudBoneType.HalfFloat:
            self.boneIds = br.read_uint16(4)
            self.boneWeights = br.read_half_float(4)
        elif bone_type == NudBoneType.Byte:
            self.boneIds = br.read_uint8(4)
            self.boneWeights = tuple(float(x) / 255.0 for x in br.read_uint8(4))
        else:
            raise ValueError(f"Unsupported bone type: {bone_type}")

    def __br_write__(self, br: BinaryReader, vertex, vertex_type: NudVertexType, bone_type: NudBoneType, uv_type: int):
        br.write_float(vertex.position)
        normal = vertex.normal or (0.0, 1.0, 0.0)
        tangent = vertex.tangent or (0.0, 0.0, 1.0, 0.0)
        bitangent = vertex.bitangent or (1.0, 0.0, 0.0, 0.0)

        if vertex_type == NudVertexType.NoNormals:
            br.write_float(1.0)
        elif vertex_type == NudVertexType.NormalsFloat:
            br.write_float(1.0)
            br.write_float(normal)
            br.write_float(1.0)
        elif vertex_type == NudVertexType.Unknown:
            br.write_float(normal)
            br.write_float(1.0)
            br.write_float([1.0] * 3)
            br.write_float([1.0] * 3)
            br.write_float([1.0] * 3)
        elif vertex_type == NudVertexType.NormalsTanBiTanFloat:
            br.write_float(1.0)
            br.write_float(normal)
            br.write_float(1.0)
            br.write_float(bitangent[:3])
            br.write_float(bitangent[3] if len(bitangent) > 3 else 0.0)
            br.write_float(tangent[:3])
            br.write_float(tangent[3] if len(tangent) > 3 else 0.0)
        elif vertex_type == NudVertexType.NormalsHalfFloat:
            br.write_half_float(normal)
            br.write_half_float(1.0)
        elif vertex_type == NudVertexType.NormalsTanBiTanHalfFloat:
            br.write_half_float(normal)
            br.write_half_float(1.0)
            br.write_half_float(bitangent[:3])
            br.write_half_float(bitangent[3] if len(bitangent) > 3 else 0.0)
            br.write_half_float(tangent[:3])
            br.write_half_float(tangent[3] if len(tangent) > 3 else 0.0)
        else:
            raise ValueError(f"Unsupported vertex type: {vertex_type}")

        if bone_type == NudBoneType.NoBones:
            if uv_type:
                br.write_uint8(vertex.color or (255, 255, 255, 255))
            for uv in vertex.uv or []:
                br.write_half_float(uv)
        elif bone_type == NudBoneType.Float:
            br.write_uint32(vertex.bone_ids or (0, 0, 0, 0))
            br.write_float(vertex.bone_weights or (1.0, 0.0, 0.0, 0.0))
        elif bone_type == NudBoneType.HalfFloat:
            br.write_uint16(vertex.bone_ids or (0, 0, 0, 0))
            br.write_half_float(vertex.bone_weights or (1.0, 0.0, 0.0, 0.0))
        elif bone_type == NudBoneType.Byte:
            br.write_uint8(vertex.bone_ids or (0, 0, 0, 0))
            br.write_uint8(tuple(max(0, min(255, int(x * 255))) for x in (vertex.bone_weights or (1.0, 0.0, 0.0, 0.0))))


class BrNudMaterial(BrStruct):
    def __br_read__(self, br: BinaryReader, mesh: BrNudMesh, name_start: int) -> None:
        self.flags = br.read_uint32()
        br.read_uint32()
        self.sourceFactor = br.read_uint16()
        self.textureCount = br.read_uint16()
        self.destFactor = br.read_uint16()
        self.alphaTest = br.read_uint8()
        self.alphaFunction = br.read_uint8()
        self.refAlpha = br.read_uint16()
        self.cullMode = br.read_uint16()
        self.unk1 = br.read_float()
        self.unk2 = br.read_float()
        self.zBufferOffset = br.read_int32()
        self.textures = br.read_struct(BrNudMaterialTexture, self.textureCount)

        self.properties = []
        while True:
            prop_pos = br.pos()
            prop = br.read_struct(BrNudMaterialProperty, None, name_start)
            self.properties.append(prop)
            if prop.matAttSize == 0:
                break
            br.seek(prop_pos + prop.matAttSize)

    def __br_write__(self, br: BinaryReader, material, buffers: NudBuffers):
        br.write_uint32(material.flags)
        br.write_uint32(0)
        br.write_uint16(material.sourceFactor)
        br.write_uint16(len(material.textures))
        br.write_uint16(material.destFactor)
        br.write_uint8(material.alphaTest)
        br.write_uint8(material.alphaFunction)
        br.write_uint16(material.refAlpha)
        br.write_uint16(material.cullMode)
        br.write_float(material.unk1)
        br.write_float(material.unk2)
        br.write_int32(material.zBufferOffset)
        for texture in material.textures:
            br.write_struct(BrNudMaterialTexture(), texture)
        if material.properties:
            for idx, prop in enumerate(material.properties):
                br.write_struct(BrNudMaterialProperty(), prop, buffers, idx == len(material.properties) - 1)
        else:
            br.write_uint32([0] * 4)


class BrNudMaterialTexture(BrStruct):
    def __br_read__(self, br: BinaryReader) -> None:
        self.unk0 = br.read_int32()
        br.read_uint32()
        br.read_uint16()
        self.mapMode = br.read_uint16()
        self.wrapModeS = br.read_uint8()
        self.wrapModeT = br.read_uint8()
        self.minFilter = br.read_uint8()
        self.magFilter = br.read_uint8()
        self.mipDetail = br.read_uint8()
        self.unk1 = br.read_uint8()
        br.read_uint32()
        self.unk2 = br.read_int16()

    def __br_write__(self, br: BinaryReader, texture) -> None:
        br.write_int32(texture.unk0)
        br.write_uint32(0)
        br.write_uint16(0)
        br.write_uint16(texture.mapMode)
        br.write_uint8(texture.wrapModeS)
        br.write_uint8(texture.wrapModeT)
        br.write_uint8(texture.minFilter)
        br.write_uint8(texture.magFilter)
        br.write_uint8(texture.mipDetail)
        br.write_uint8(texture.unk1)
        br.write_uint32(0)
        br.write_int16(texture.unk2)


class BrNudMaterialProperty(BrStruct):
    def __br_read__(self, br: BinaryReader, name_start: int) -> None:
        self.matAttSize = br.read_uint32()
        self.nameStart = br.read_uint32()
        br.read_uint8(3)
        self.valueCount = br.read_uint8()
        br.read_uint32()
        self.name = ""
        if self.nameStart != 0:
            with br.seek_to(name_start + self.nameStart):
                self.name = br.read_str()
        self.values = []
        if self.valueCount != 0:
            self.values = list(br.read_float(self.valueCount))
            self.values.extend([0.0] * (4 - self.valueCount))

    def __br_write__(self, br: BinaryReader, prop, buffers: NudBuffers, is_last):
        buffers.names.align(0x10)
        br.write_uint32(0 if is_last else 0x10 + (4 * len(prop.values)))
        br.write_uint32(buffers.names.size())
        buffers.names.write_str(prop.name, True)
        br.write_uint8([0] * 3)
        br.write_uint8(len(prop.values))
        br.write_uint32(0)
        br.write_float(prop.values)
