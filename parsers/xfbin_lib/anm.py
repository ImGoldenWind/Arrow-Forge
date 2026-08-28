"""High-level NUCC animation objects used by the model viewer."""

from dataclasses import dataclass, field

from .br_anm import AnmCurveType, AnmEntryFormat


@dataclass
class AnmKeyframe:
    frame: float
    value: object


@dataclass
class AnmCurve:
    data_path: str
    keyframes: list[AnmKeyframe]
    interpolate: bool = True


@dataclass
class AnmTarget:
    name: str
    referenced_name: str
    chunk: object
    curves: list[AnmCurve] = field(default_factory=list)
    parent: "AnmTarget | None" = None
    children: list["AnmTarget"] = field(default_factory=list)


class AnmClump:
    def init_data(self, source, chunk_refs, initial_chunks):
        refs = chunk_refs if chunk_refs else [None] * len(initial_chunks)

        def resolve(index):
            if chunk_refs and 0 <= index < len(chunk_refs):
                ref = chunk_refs[index]
                return ref.name, ref.chunk
            chunk = initial_chunks[index]
            return chunk.name, chunk

        referenced_name, chunk = resolve(source.clump_index)
        self.name = chunk.name
        self.referenced_name = referenced_name
        self.chunk = chunk
        self.children = []
        self.bones = []
        self.materials = []
        self.models = []
        # Imported lazily to avoid a nucc <-> anm import cycle.
        from .nucc import NuccChunkMaterial
        for index in source.bones:
            ref_name, child_chunk = resolve(index)
            target = AnmTarget(child_chunk.name, ref_name, child_chunk)
            self.children.append(target)
            if isinstance(child_chunk, NuccChunkMaterial):
                self.materials.append(target)
            else:
                self.bones.append(target)
        for index in source.models:
            ref_name, model_chunk = resolve(index)
            self.models.append(AnmTarget(model_chunk.name, ref_name, model_chunk))


_BONE_PATHS = {0: "location", 1: "rotation_quaternion", 2: "scale", 3: "opacity", 11: "rotation_euler"}
_MATERIAL_PATHS = {
    0: "U0_LocX", 1: "V0_LocY", 2: "U1_LocX", 3: "V1_LocY",
    4: "U2_LocX", 5: "V2_LocY", 6: "U3_LocX", 7: "V3_LocY",
    8: "U0_ScaleX", 9: "V0_ScaleY", 10: "U1_ScaleX", 11: "V1_ScaleY",
    12: "BlendRate1", 13: "BlendRate2", 14: "Falloff", 15: "Glare",
    16: "Alpha", 17: "OutlineID", 18: "U2_ScaleX", 19: "V2_ScaleY",
    20: "U3_ScaleX", 21: "V3_ScaleY",
}


class AnmEntry:
    def init_data(self, source, frame_size, clumps, other_chunks):
        self.entry_format = AnmEntryFormat(source.entry_format)
        self.clump = clumps[source.clump_index] if source.clump_index >= 0 else None
        self.target = None
        if self.clump is not None and source.bone_index < len(self.clump.children):
            self.target = self.clump.children[source.bone_index]
        elif source.clump_index < 0 and source.bone_index < len(other_chunks):
            chunk = other_chunks[source.bone_index]
            self.target = AnmTarget(chunk.name, chunk.name, chunk)
        self.name = self.target.name if self.target else ""
        self.chunk = self.target.chunk if self.target else None
        self.curves = []
        for header, values in zip(source.curve_headers, source.curves):
            curve_type = AnmCurveType(header.curve_format)
            data_path = self._data_path(header.curve_index, curve_type)
            keyframes = _convert_keyframes(frame_size, curve_type, values)
            no_interp = curve_type in {
                AnmCurveType.VECTOR3FIXED, AnmCurveType.EULERXYZFIXED,
                AnmCurveType.VECTOR3TBL_NOINTERP, AnmCurveType.QUATERNIONI16TBL_NOINTERP,
                AnmCurveType.OPACITYI16TBL_NOINTERP,
            }
            self.curves.append(AnmCurve(data_path, keyframes, not no_interp))
        if self.target is not None:
            self.target.curves = self.curves

    def _data_path(self, index, curve_type):
        if self.entry_format == AnmEntryFormat.BONE:
            if curve_type in (AnmCurveType.EULERXYZFIXED, AnmCurveType.EULERINTERPOLATE):
                index += 10
            return _BONE_PATHS.get(index, "unknown")
        if self.entry_format == AnmEntryFormat.MATERIAL:
            return _MATERIAL_PATHS.get(index, "unknown")
        return "unknown"


def _convert_keyframes(frame_size, curve_type, values):
    explicit_frame = curve_type in {
        AnmCurveType.VECTOR3LINEAR, AnmCurveType.VECTOR3BEZIER,
        AnmCurveType.QUATERNIONLINEAR, AnmCurveType.FLOATLINEAR,
        AnmCurveType.VECTOR3I16LINEAR,
    }
    short_scale = {
        AnmCurveType.OPACITYI16TBL: 0x8000,
        AnmCurveType.SCALEI16TBL: 0x1000,
        AnmCurveType.QUATERNIONI16TBL: 0x8000,
        AnmCurveType.QUATERNIONI16TBL_NOINTERP: 0x8000,
        AnmCurveType.OPACITYI16TBL_NOINTERP: 0x8000,
    }.get(curve_type)
    result = []
    for index, raw in enumerate(values):
        if explicit_frame:
            frame, value = raw[0], raw[1:]
            if curve_type == AnmCurveType.FLOATLINEAR:
                value = raw[1]
        else:
            frame, value = frame_size * index, raw
        if short_scale:
            if isinstance(value, tuple):
                value = tuple(component / short_scale for component in value)
            else:
                value = value / short_scale
        elif curve_type == AnmCurveType.COLORRGBTBL:
            value = tuple(component / 255.0 for component in value)
        result.append(AnmKeyframe(float(frame), value))
    return result

