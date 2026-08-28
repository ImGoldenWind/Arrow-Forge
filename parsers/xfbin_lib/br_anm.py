"""Binary structures used by ``nuccChunkAnm``.

The layout mirrors the animation reader used by Blender-XFBIN-Importer.  The
writer intentionally keeps using the raw chunk buffer from ``BrNuccChunk``;
Arrow Forge only previews animations and must not rewrite motion data.
"""

from enum import IntEnum

from .binary_reader import BrStruct, Whence


class AnmEntryFormat(IntEnum):
    BONE = 1
    CAMERA = 2
    MATERIAL = 4
    LIGHTDIRC = 5
    LIGHTPOINT = 6
    AMBIENT = 8
    MORPH = 9


class AnmCurveType(IntEnum):
    VECTOR3FIXED = 5
    VECTOR3LINEAR = 6
    VECTOR3BEZIER = 7
    EULERXYZFIXED = 8
    EULERINTERPOLATE = 9
    QUATERNIONLINEAR = 10
    FLOATFIXED = 11
    FLOATLINEAR = 12
    VECTOR2FIXED = 13
    VECTOR2LINEAR = 14
    OPACITYI16TBL = 15
    SCALEI16TBL = 16
    QUATERNIONI16TBL = 17
    COLORRGBTBL = 20
    VECTOR3TBL = 21
    FLOATTBLNI = 22
    QUATERNIONTBL = 23
    FLOATTBL = 24
    VECTOR3I16LINEAR = 25
    VECTOR3TBL_NOINTERP = 26
    QUATERNIONI16TBL_NOINTERP = 27
    OPACITYI16TBL_NOINTERP = 29


class BrAnmClump(BrStruct):
    def __br_read__(self, br):
        self.clump_index = br.read_uint32()
        bone_count = br.read_uint16()
        model_count = br.read_uint16()
        self.bones = br.read_uint32(bone_count)
        self.models = br.read_uint32(model_count)


class BrAnmCoordParent(BrStruct):
    def __br_read__(self, br):
        self.parent_clump_index = br.read_int16()
        self.parent_coord_index = br.read_uint16()
        self.child_clump_index = br.read_int16()
        self.child_coord_index = br.read_uint16()


class BrAnmCurveHeader(BrStruct):
    def __br_read__(self, br):
        self.curve_index = br.read_uint16()
        self.curve_format = br.read_uint16()
        self.keyframe_count = br.read_uint16()
        self.curve_flags = br.read_int16()


class BrAnmEntry(BrStruct):
    def __br_read__(self, br):
        self.clump_index = br.read_int16()
        self.bone_index = br.read_uint16()
        self.entry_format = br.read_uint16()
        curve_count = br.read_uint16()
        self.curve_headers = br.read_struct(BrAnmCurveHeader, curve_count)
        self.curves = []
        readers = {
            AnmCurveType.VECTOR3FIXED: self._vector3_fixed,
            AnmCurveType.VECTOR3LINEAR: self._vector3_linear,
            AnmCurveType.VECTOR3BEZIER: self._vector3_linear,
            AnmCurveType.EULERXYZFIXED: self._vector3_fixed,
            AnmCurveType.EULERINTERPOLATE: self._vector3_fixed,
            AnmCurveType.QUATERNIONLINEAR: self._quaternion_linear,
            AnmCurveType.FLOATFIXED: self._float_fixed,
            AnmCurveType.FLOATLINEAR: self._float_linear,
            AnmCurveType.VECTOR2FIXED: self._short1,
            AnmCurveType.VECTOR2LINEAR: self._short3,
            AnmCurveType.OPACITYI16TBL: self._short1,
            AnmCurveType.SCALEI16TBL: self._short3,
            AnmCurveType.QUATERNIONI16TBL: self._short4,
            AnmCurveType.COLORRGBTBL: self._byte3,
            AnmCurveType.VECTOR3TBL: self._vector3_fixed,
            AnmCurveType.FLOATTBLNI: self._float_fixed,
            AnmCurveType.QUATERNIONTBL: self._quaternion_fixed,
            AnmCurveType.FLOATTBL: self._float_fixed,
            AnmCurveType.VECTOR3I16LINEAR: self._short_vector3_linear,
            AnmCurveType.VECTOR3TBL_NOINTERP: self._vector3_fixed,
            AnmCurveType.QUATERNIONI16TBL_NOINTERP: self._short4,
            AnmCurveType.OPACITYI16TBL_NOINTERP: self._short1,
        }
        for header in self.curve_headers:
            values = []
            reader = readers.get(header.curve_format)
            if reader is None:
                raise ValueError(f"Unsupported NUCC animation curve format: {header.curve_format}")
            reader(br, header.keyframe_count, values)
            br.align_pos(4)
            self.curves.append(values)

    @staticmethod
    def _vector3_fixed(br, count, out):
        out.extend(br.read_float(3) for _ in range(count))

    @staticmethod
    def _vector3_linear(br, count, out):
        out.extend((br.read_int32(), *br.read_float(3)) for _ in range(count))

    @staticmethod
    def _quaternion_linear(br, count, out):
        out.extend((br.read_int32(), *br.read_float(4)) for _ in range(count))

    @staticmethod
    def _float_fixed(br, count, out):
        out.extend(br.read_float() for _ in range(count))

    @staticmethod
    def _float_linear(br, count, out):
        out.extend((br.read_int32(), br.read_float()) for _ in range(count))

    @staticmethod
    def _short1(br, count, out):
        out.extend(br.read_int16() for _ in range(count))

    @staticmethod
    def _short3(br, count, out):
        out.extend(br.read_int16(3) for _ in range(count))

    @staticmethod
    def _short4(br, count, out):
        out.extend(br.read_int16(4) for _ in range(count))

    @staticmethod
    def _byte3(br, count, out):
        out.extend(br.read_uint8(3) for _ in range(count))

    @staticmethod
    def _quaternion_fixed(br, count, out):
        out.extend(br.read_float(4) for _ in range(count))

    @staticmethod
    def _short_vector3_linear(br, count, out):
        out.extend((br.read_int16(), *br.read_float(3)) for _ in range(count))

