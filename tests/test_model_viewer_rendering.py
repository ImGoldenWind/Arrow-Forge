import unittest
from types import SimpleNamespace

import numpy as np

from parsers.model_xfbin_parser import (
    AnimationClip,
    ResolvedTextureRef,
    _bone_arrays,
    _canonical_bone_name,
    _coord_world_matrices,
    _gpu_bone_arrays,
    _sample_curve,
    _textures_for_material,
    _transform_points,
)
from parsers.xfbin_lib.anm import AnmCurve, AnmKeyframe


class _Node:
    def __init__(self, name, position, parent=None):
        self.name = name
        self.position = position
        self.rotation = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.parent = parent


class ModelViewerRenderingTests(unittest.TestCase):
    def test_coord_world_matrices_include_parent_transform(self):
        root = _Node("root", (10.0, 0.0, 0.0))
        child = _Node("teeth", (0.0, 5.0, 2.0), root)
        chunks = [SimpleNamespace(node=root), SimpleNamespace(node=child)]

        matrices = _coord_world_matrices(chunks)

        np.testing.assert_allclose(matrices[child][:3, 3], (10.0, 5.0, 2.0))
        np.testing.assert_allclose(
            _transform_points(np.array([[1.0, 1.0, 1.0]], dtype=np.float32), matrices[child]),
            ((11.0, 6.0, 3.0),),
        )

    def test_bone_weights_are_normalized(self):
        vertices = [
            SimpleNamespace(bone_ids=(2, 3, 0, 0), bone_weights=(0.25, 0.25, 0.0, 0.0)),
            SimpleNamespace(bone_ids=(4, 0, 0, 0), bone_weights=(1.0, 0.0, 0.0, 0.0)),
        ]

        ids, weights = _bone_arrays(vertices)

        self.assertEqual(ids.shape, (2, 4))
        np.testing.assert_allclose(weights.sum(axis=1), (1.0, 1.0))
        np.testing.assert_allclose(weights[0, :2], (0.5, 0.5))

    def test_gpu_skinning_falls_back_to_model_coord(self):
        ids, weights = _gpu_bone_arrays(2, None, None, model_coord_index=7, bone_count=10)

        np.testing.assert_allclose(ids[:, 0], (7.0, 7.0))
        np.testing.assert_allclose(weights[:, 0], (1.0, 1.0))
        np.testing.assert_allclose(weights[:, 1:], 0.0)

    def test_animation_bone_names_ignore_costume_prefix(self):
        self.assertEqual(_canonical_bone_name("0bao01t1 L Arm"), "l arm")
        self.assertEqual(_canonical_bone_name("0bao11t3 L Arm"), "l arm")
        self.assertEqual(_canonical_bone_name("0bao11t3 L Arm_f"), "l arm")
        self.assertEqual(_canonical_bone_name("0bao11t3_f"), "__model_root__")

    def test_eye_shader_uses_second_texture_as_iris_detail(self):
        chunks = [SimpleNamespace(name="body_d", filePath=""), SimpleNamespace(name="iris", filePath="")]
        material = SimpleNamespace(texture_groups=[SimpleNamespace(texture_chunks=chunks)])
        refs = {
            "body_d": ResolvedTextureRef("body_d", "", None, None, "test"),
            "iris": ResolvedTextureRef("iris", "", None, None, "test"),
        }

        slots = _textures_for_material(material, refs, 0x1F130)

        self.assertIs(slots["diffuse"], refs["body_d"])
        self.assertIs(slots["detail"], refs["iris"])

    def test_animation_curve_interpolates_in_raw_frame_units(self):
        curve = AnmCurve(
            "location",
            [AnmKeyframe(0.0, (0.0, 0.0, 0.0)), AnmKeyframe(100.0, (10.0, 20.0, 30.0))],
            True,
        )

        np.testing.assert_allclose(_sample_curve(curve, 25.0), (2.5, 5.0, 7.5))

    def test_clip_exposes_viewer_frame_count(self):
        chunk = SimpleNamespace(frame_count=5900, frame_size=100, loop_flag=1)
        clip = AnimationClip("test", "test.xfbin", chunk)

        self.assertEqual(clip.frame_count, 59)
        self.assertTrue(clip.looped)


if __name__ == "__main__":
    unittest.main()
