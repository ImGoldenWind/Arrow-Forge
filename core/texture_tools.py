"""Pixel operations for texture authoring; no game-scene simulation."""
from PIL import Image, ImageEnhance, ImageChops


def inspect_channel(image, channel):
    image = image.convert('RGBA')
    if channel == 'rgba':
        return image
    if channel == 'rgb':
        return image.convert('RGB').convert('RGBA')
    return image.getchannel(channel.upper()).convert('RGB').convert('RGBA')


def compare_pixels(current, original, mode, split=50):
    """Compare in native pixel coordinates, including differently sized images."""
    if mode == 'current' or original is None:
        return current
    if mode == 'original':
        return original
    size = (max(current.width, original.width), max(current.height, original.height))
    before, after = (Image.new('RGBA', size) for _ in range(2))
    before.paste(original, (0, 0))
    after.paste(current, (0, 0))
    if mode == 'difference':
        # Include alpha changes in the difference, then display opaquely.
        channels = ImageChops.difference(before, after).split()
        rgb = [ImageChops.lighter(c, channels[3]) for c in channels[:3]]
        return Image.merge('RGBA', (*rgb, Image.new('L', size, 255)))
    boundary = size[0] * split // 100
    before.paste(after.crop((boundary, 0, size[0], size[1])), (boundary, 0))
    return before
# Adjustment helpers
import numpy as _np

def _rgb_to_hsv_np(rgb: '_np.ndarray') -> '_np.ndarray':
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    maxc = _np.maximum(_np.maximum(r, g), b)
    minc = _np.minimum(_np.minimum(r, g), b)
    v = maxc
    diff = maxc - minc
    s = _np.divide(diff, maxc, out=_np.zeros_like(maxc), where=maxc > 1e-7)
    safe = _np.where(diff > 1e-7, diff, 1.0)
    h = _np.where(maxc == r, (g - b) / safe % 6,
        _np.where(maxc == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0)) / 6.0
    h = _np.where(diff > 1e-7, h % 1.0, 0.0)
    return _np.stack([h, s, v], axis=2).astype(_np.float32)

def _hsv_to_rgb_np(hsv: '_np.ndarray') -> '_np.ndarray':
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    i = (_np.floor(h * 6)).astype(_np.int32) % 6
    f = h * 6.0 - _np.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    r = _np.choose(i, [v, q, p, p, t, v])
    g = _np.choose(i, [t, v, v, q, p, p])
    b = _np.choose(i, [p, p, t, v, v, q])
    return _np.stack([r, g, b], axis=2).clip(0.0, 1.0).astype(_np.float32)

def apply_adjustments(img: Image.Image, adj: dict) -> Image.Image:
    img = img.convert('RGBA')

    def _f(v): return max(0.0, 1.0 + v / 100.0)

    b = adj.get('brightness', 0)
    if b != 0:
        img = ImageEnhance.Brightness(img).enhance(_f(b))

    c = adj.get('contrast', 0)
    if c != 0:
        img = ImageEnhance.Contrast(img).enhance(_f(c))

    sh = adj.get('sharpness', 0)
    if sh != 0:
        img = ImageEnhance.Sharpness(img).enhance(_f(sh))

    h        = adj.get('hue', 0)
    s        = adj.get('saturation', 0)
    l        = adj.get('lightness', 0)
    colorize = adj.get('colorize', False)

    if h != 0 or s != 0 or l != 0 or colorize:
        arr   = _np.array(img, dtype=_np.float32) / 255.0
        alpha = arr[:, :, 3].copy()
        hsv   = _rgb_to_hsv_np(arr[:, :, :3])

        if colorize:
            # Replace hue of every pixel with the slider's absolute hue,
            # use a fixed default saturation boosted by the sat slider,
            # then shift lightness (value).
            hsv[:, :, 0] = ((h + 180) / 360.0) % 1.0
            hsv[:, :, 1] = _np.clip(0.5 + s / 200.0, 0.0, 1.0)
            hsv[:, :, 2] = _np.clip(hsv[:, :, 2] + l / 100.0, 0.0, 1.0)
        else:
            if h != 0:
                hsv[:, :, 0] = (hsv[:, :, 0] + h / 360.0) % 1.0
            if s != 0:
                hsv[:, :, 1] = _np.clip(hsv[:, :, 1] * _f(s), 0.0, 1.0)
            if l != 0:
                hsv[:, :, 2] = _np.clip(hsv[:, :, 2] + l / 100.0, 0.0, 1.0)

        rgb_out = _hsv_to_rgb_np(hsv)
        out = _np.concatenate([rgb_out, alpha[:, :, _np.newaxis]], axis=2)
        img = Image.fromarray((out * 255).clip(0, 255).astype(_np.uint8), 'RGBA')

    return img
