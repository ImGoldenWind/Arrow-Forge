"""NUD/NUCC draw state used by the original stage material programs."""
import numpy as np
import copy


def native_uv_coordinates(viewer_uvs):
    """Undo the shared Model Viewer's V flip for original game shaders."""
    values = np.array(viewer_uvs, dtype=np.float32, copy=True)
    values[:, 1] = 1. - values[:, 1]
    return values


def material_state(material, nud_material):
    from core.model_viewer_tools import material_uv_transforms
    return dict(alpha_reference=getattr(material, 'field02', 0) / 255.,
                glare=float(getattr(material, 'field04', 0.)),
                uv_transforms=material_uv_transforms(material),
                source=int(getattr(nud_material, 'sourceFactor', 2)),
                destination=int(getattr(nud_material, 'destFactor', 0)),
                cull=int(getattr(nud_material, 'cullMode', 0)),
                samplers=[dict(wrap_s=int(t.wrapModeS), wrap_t=int(t.wrapModeT),
                               min_filter=int(t.minFilter), mag_filter=int(t.magFilter),
                               mip_detail=int(t.mipDetail)) for t in getattr(nud_material, 'textures', [])])


def texture_mip_images(ref):
    """Keep the artist-authored NUT levels instead of regenerating their detail."""
    bundled = getattr(ref, 'mip_images', None)
    if bundled is not None:
        return bundled
    nut = getattr(getattr(ref, 'chunk', None), 'nut', None)
    texture = nut.textures[0] if nut and nut.textures else None
    levels = getattr(texture, 'mipmaps', None)
    if not isinstance(levels, (list, tuple)) or len(levels) < 2 or getattr(texture, 'is_cube_map', False):
        return [ref.pil_image]
    from parsers.texture_xfbin_parser import nut_tex_to_pil
    images = [ref.pil_image]
    for level, data in enumerate(levels[1:], 1):
        plane = copy.copy(texture)
        plane.width, plane.height = max(1, texture.width >> level), max(1, texture.height >> level)
        plane.mipmap_count, plane.mipmaps, plane.texture_data = 1, [data], data
        image = nut_tex_to_pil(plane)
        if image is None:
            # Some shipped non-power-of-two NUTs have truncated BC tails
            # (e.g. a 6x8 BC3 mip containing 32 rather than 64 bytes). Keep
            # the valid authored prefix and clamp LOD to it; never fail the
            # entire map or read beyond the supplied level.
            break
        images.append(image)
    return images
