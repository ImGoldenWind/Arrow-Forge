# Stage preview resources

The stage preview loads these resources through `core.runtime_paths.app_path`.
`ASBR-Tools.spec` already includes the entire `resources` directory in the
one-file executable. Neither Jonathan nor the shaders require an installed game
or external XFBIN paths at runtime. Map geometry still comes from the selected
stage's extracted resources or the user's manual XFBIN choice.

* `jonathan.npz`: Jonathan Joestar (`1jnt01`), neutral standing pose
  `1jnt01_bas_nut`, frame 0. Eleven meshes, original material parameters,
  authored tangent frames, seven decoded textures including common hatching,
  and their original mip levels and NUD sampler/alpha/culling state.
  Geometry is baked into the shared viewer's coordinate system; the original
  game shaders receive native coordinates again at draw time.
* `materials.nsh`: original `nuccMaterial_dx11.nsh`, 133 VS/PS pairs.
* `post_effects.nsh`: original `nuccPostEffect_dx11.nsh`, 61 pairs / 60 unique
  identifiers. The duplicate `0x11000005` is byte-identical. Stage colour
  conversion uses the original pixel program `0x11000025`.
* `shadow_math.npz`: 129,838-byte isolated math image for the original
  perspective shadow fitting function at RVA `0x707980` and its helpers.
  Unicorn executes it in private virtual memory with an instruction limit;
  it never launches/attaches to the game or loads the PE into the host process.
  Four cascades occupy the native 2048×5120 atlas. The input PE's SHA-256 is
  in its JSON metadata. Windows CRT supplies the original scalar math calls.

These are local game-derived assets for the requested preview, not generated
art. Original characters, textures and shaders are from JoJo's Bizarre
Adventure: All-Star Battle R. Source asset hashes are embedded in the NPZ's
JSON metadata. NPZ resources contain numeric/byte arrays, PNG images and JSON;
loading never enables NumPy pickle support.

To rebuild the posed actor from the user's extracted files:

```powershell
python tools/bake_stage_actor.py --source <body-palette-animation-folder> --common <path-to-0cmn01bod1.xfbin>
```

The source folder must contain `1jnt01bod1.xfbin`, `1jnt01col0.xfbin`, and
`1jnt01mot1.xfbin`. Only the posed geometry and required textures enter the
bundle; the full animation bank is not needed at runtime.

Install `requirements.txt` before running/building. The spec collects Unicorn's
runtime DLL along with the renderer resources; shadow fitting also works from
the bundled files without the original executable.

`tools/bake_stage_shadows.py --exe <path-to-ASBR.exe>` rebuilds the math
resource (developer environment additionally needs `pefile`). It verifies the
researched EXE hash before extracting its pinned math/constant pages.

Shader arithmetic and complete-frame limitations are documented in
[`docs/stage-info-research.md`](../../docs/stage-info-research.md).
