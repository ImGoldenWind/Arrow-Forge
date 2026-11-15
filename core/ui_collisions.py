"""UI collision geometry from ASBR's signed-integer consumer (RVA 7D5D40).

Coordinates are authored UI coordinates, not desktop pixels. Keep this module
independent of Qt; the canvas is a view of these values, not a scene simulator.
"""
I32_MIN, I32_MAX = -(1 << 31), (1 << 31) - 1
GEOMETRY_FIELDS = ('x', 'y', 'w', 'h', 'rtoX', 'rtoY', 'lboX', 'lboY')


def i32(value):
    return (value + (1 << 31)) % (1 << 32) - (1 << 31)


def half(value):
    return value // 2 if value >= 0 else -((-value) // 2)


def parse_integer(text):
    value = int(text.strip(), 10)
    if not I32_MIN <= value <= I32_MAX:
        raise ValueError('signed 32-bit integer required')
    return value


def xml_text_valid(text):
    return all(c in '\t\r\n' or 0x20 <= ord(c) <= 0xD7FF
               or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF for c in text)


def vertices(c):
    x, y, w, h = (c[k] for k in ('x', 'y', 'w', 'h'))
    if c['type'] == 2:
        return ((x, y), (i32(x + w + c['rtoX']), i32(y + c['rtoY'])),
                (i32(x + w), i32(y + h)), (i32(x + c['lboX']), i32(y + h + c['lboY'])))
    return ((x, y), (i32(x + w), y), (i32(x + w), i32(y + h)), (x, i32(y + h)))


def circle(c):
    return i32(c['x'] + half(c['w'])), i32(c['y'] + half(c['h'])), half(c['h'])


def hit_score(c, px, py):
    """Exact native return value. Callers accept nonnegative scores.

    Rect/circle edges are inclusive; all four quadrilateral edges are strict.
    Arithmetic deliberately wraps at 32 bits, including squared distance.
    """
    x, y, w, h = (c[k] for k in ('x', 'y', 'w', 'h'))
    if c['type'] == 0:
        if not (x <= px <= i32(x + w) and y <= py <= i32(y + h)):
            return -1
    elif c['type'] == 1:
        cx, cy, radius = circle(c)
        dx, dy = i32(cx - px), i32(cy - py)
        distance = i32(dx * dx + dy * dy)
        return distance if distance <= i32(radius * radius) else -1
    elif c['type'] == 2:
        points = vertices(c)
        for a, b in zip(points, points[1:] + points[:1]):
            cross = i32(i32(b[0] - a[0]) * i32(py - a[1]) - i32(b[1] - a[1]) * i32(px - a[0]))
            if cross <= 0:
                return -1
    else:
        return -1
    dx, dy = i32(px - half(w) - x), i32(py - half(h) - y)
    return i32(dx * dx + dy * dy)


def bounds(c):
    if c['type'] == 1:
        cx, cy, r = circle(c)
        r = abs(r)
        return cx - r, cy - r, cx + r, cy + r
    points = vertices(c)
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def preview_polygon(c):
    """Continuous edge intersection for the fill; authored vertices stay visible.

    A concave/crossed edited quad must not acquire the usual odd-even polygon
    fill: the native consumer intersects four directed half-planes instead.
    Integer boundary/overflow behavior is handled by hit_score, not raster fill.
    """
    if c['type'] == 0:
        return vertices(c) if c['w'] >= 0 and c['h'] >= 0 else ()
    if c['type'] != 2:
        return ()
    points = vertices(c)
    x0, y0, x1, y1 = bounds(c)
    polygon = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for a, b in zip(points, points[1:] + points[:1]):
        if a == b:
            return ()  # The strict native test rejects a zero-length edge.
        def cross(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        clipped = []
        for p, q in zip(polygon, polygon[1:] + polygon[:1]):
            cp, cq = cross(p), cross(q)
            if cp >= 0:
                clipped.append(p)
            if (cp >= 0) != (cq >= 0):
                ratio = cp / (cp - cq)
                clipped.append((p[0] + ratio * (q[0] - p[0]), p[1] + ratio * (q[1] - p[1])))
        polygon = clipped
        if not polygon:
            break
    return tuple(polygon)


def identity_index(items, item):
    return next((i for i, value in enumerate(items) if value is item), -1)


def resize_box(original, mode, dx, dy):
    """Resize without crossing the opposite edge; never invent a game limit."""
    result = {k: original[k] for k in GEOMETRY_FIELDS}
    if mode == 'move':
        result['x'] = max(I32_MIN, min(I32_MAX, original['x'] + dx))
        result['y'] = max(I32_MIN, min(I32_MAX, original['y'] + dy))
    elif mode in ('rto', 'lbo'):
        for axis, delta in (('X', dx), ('Y', dy)):
            key = mode + axis
            result[key] = max(I32_MIN, min(I32_MAX, original[key] + delta))
    else:
        for axis, size, delta, low, high in (('x', 'w', dx, 'l', 'r'), ('y', 'h', dy, 't', 'b')):
            if low in mode:
                delta = min(delta, original[size])
                result[axis] = original[axis] + delta
                result[size] = original[size] - delta
            elif high in mode:
                result[size] = max(0, original[size] + delta)
    return result if all(I32_MIN <= v <= I32_MAX for v in result.values()) else None
