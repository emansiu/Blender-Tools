"""Turn a LaTeX formula into a filled curve object.

No LaTeX install, no network: helpers/latex_layout.py parses the formula and
lays it out TeX-style, and the glyph outlines come from Noto Sans Math, which
ships inside Blender. The result is one 2D curve (fill on), so it can be
extruded, bevelled or converted to a mesh like any text object -- but unlike a
text object it can hold fractions, radicals, matrices and stretchy brackets.

Glyph metrics and outlines are read back from Blender itself: each character
is set in a throwaway text object, evaluated, and its splines copied out. That
works for any font Blender can open (.woff2 included), and is cached per font
for the session, so only the first formula pays for it.
"""

import os

import bpy

from ..helpers import latex_layout
from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "latex_to_object",
    label="LaTeX to Object",
    owner=__name__,
    description="Turn a LaTeX formula into a filled curve object",
    # Explicit, after Atom Constructor (1000), which wants to sit at the bottom.
    order=1010,
)

NAMES_CREATE = naming.register_tool(
    "create_latex_object",
    label="Create LaTeX Object",
    owner=__name__,
    description=(
        "Lay out the LaTeX formula and add it at the 3D cursor as a filled 2D curve, "
        "ready to extrude, bevel or convert to a mesh"
    ),
)

LATEX_SOURCE_PROP = naming.prop_name("latex_source")   # on Scene: what's typed in the panel
OBJECT_SOURCE_KEY = naming.prop_name("latex")          # ID property on each created object

MATH_FONT_FILE = "NotoSansMath-Regular.woff2"
FALLBACK_FONT = "<builtin>"   # for the odd glyph the math font lacks (plain Latin, mostly)
PROBE_NAME = "_emanate_latex_probe"
REFERENCE_CHAR = "|"          # advance(c) = right edge of "c|" minus right edge of "|"
TOFU_PROBES = ("", "\U0010fffd")   # private-use: no font has them, so they render as .notdef

# font filepath -> {char: _Glyph}. Outlines don't change, so this outlives any
# one operator call; Reload Scripts re-imports the module and empties it.
_glyph_cache = {}


class _Glyph(latex_layout.Glyph):
    __slots__ = ("splines",)


def math_font_path():
    return os.path.join(bpy.utils.system_resource("DATAFILES"), "fonts", MATH_FONT_FILE)


def _load_font(path):
    try:
        return bpy.data.fonts.load(path, check_existing=True)
    except (RuntimeError, OSError):
        return None


def _read_splines(curve):
    """Plain-Python copy of a curve's splines, so it survives the curve."""
    out = []
    for spline in curve.splines:
        if spline.type == "BEZIER":
            points = tuple(
                (p.co.x, p.co.y, p.handle_left.x, p.handle_left.y, p.handle_right.x, p.handle_right.y,
                 p.handle_left_type, p.handle_right_type)
                for p in spline.bezier_points
            )
            out.append(("BEZIER", spline.use_cyclic_u, points))
        else:
            out.append((spline.type, spline.use_cyclic_u, tuple((p.co.x, p.co.y) for p in spline.points)))
    return out


def _ink(splines):
    xs = [pt[0] for _, _, pts in splines for pt in pts]
    ys = [pt[1] for _, _, pts in splines for pt in pts]
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def _signature(splines):
    return tuple(round(v, 5) for v in (_ink(splines) or ())) + (len(splines),)


def _evaluate_bodies(context, font, bodies):
    """{body: splines} for each string set in `font` at size 1."""
    collection = context.scene.collection
    objects = []
    try:
        for body in bodies:
            curve = bpy.data.curves.new(PROBE_NAME, "FONT")
            curve.font = font
            curve.body = body
            obj = bpy.data.objects.new(PROBE_NAME, curve)
            collection.objects.link(obj)
            objects.append((body, obj))
        depsgraph = context.evaluated_depsgraph_get()
        result = {}
        for body, obj in objects:
            evaluated = obj.evaluated_get(depsgraph)
            curve = evaluated.to_curve(depsgraph, apply_modifiers=False)
            result[body] = _read_splines(curve) if curve is not None else []
            evaluated.to_curve_clear()
        return result
    finally:
        for _, obj in objects:
            curve = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.curves.remove(curve)


def _measure(context, font, chars):
    """{char: _Glyph} for the chars `font` really has (no .notdef boxes)."""
    bodies = {REFERENCE_CHAR, *TOFU_PROBES}
    for ch in chars:
        bodies.add(ch)
        bodies.add(ch + REFERENCE_CHAR)
    shapes = _evaluate_bodies(context, font, bodies)
    tofu = {_signature(shapes[t]) for t in TOFU_PROBES if shapes[t]}
    ref = _ink(shapes[REFERENCE_CHAR])
    if ref is None:
        return {}
    found = {}
    for ch in chars:
        splines = shapes[ch]
        if splines and _signature(splines) in tofu:
            continue
        pair = _ink(shapes[ch + REFERENCE_CHAR])
        if pair is None:
            continue
        advance = pair[1] - ref[1]
        ink = _ink(splines)
        if ink is None:
            if not ch.isspace():
                continue   # nothing drawn and not a space: the font lacks it
            ink = (0.0, 0.0, 0.0, 0.0)
        glyph = _Glyph(advance, *ink)
        glyph.splines = splines
        found[ch] = glyph
    return found


def _scaled(glyph, k):
    """`glyph` uniformly scaled by `k` about its origin."""
    if k == 1.0:
        return glyph
    out = _Glyph(glyph.advance * k, glyph.xmin * k, glyph.xmax * k, glyph.ymin * k, glyph.ymax * k)
    out.splines = [
        (kind, cyclic, tuple(tuple(v * k if isinstance(v, float) else v for v in pt) for pt in points))
        for kind, cyclic, points in glyph.splines
    ]
    return out


class GlyphSource:
    """metrics(ch) for latex_layout, backed by Blender-evaluated outlines.

    Tries the math font first and the built-in font for whatever it lacks
    (Noto Sans Math has no ℏ, ℓ or …). Fallback glyphs are scaled to the math
    font's x-height so they don't stand out a size larger.
    """

    def __init__(self, context, font_paths):
        self.context = context
        self.fonts = []
        for path in font_paths:
            font = _load_font(path)
            if font is not None:
                self.fonts.append((path, font))
        if not self.fonts:
            raise RuntimeError("No usable font found")
        self.glyphs = {}
        self.scales = {}

    def _font_glyphs(self, path, font, chars):
        cache = _glyph_cache.setdefault(path, {})
        unknown = {c for c in chars if c not in cache}
        if unknown:
            found = _measure(self.context, font, unknown)
            for ch in unknown:
                cache[ch] = found.get(ch)   # None remembers "this font lacks it"
        return cache

    def _scale(self, index):
        if index not in self.scales:
            k = 1.0
            if index > 0:
                ref = self._font_glyphs(*self.fonts[0], {"x"}).get("x")
                own = self._font_glyphs(*self.fonts[index], {"x"}).get("x")
                if ref is not None and own is not None and own.ymax > 0:
                    k = ref.ymax / own.ymax
            self.scales[index] = k
        return self.scales[index]

    def prefetch(self, chars):
        todo = {c for c in chars if c not in self.glyphs}
        for index, (path, font) in enumerate(self.fonts):
            if not todo:
                break
            cache = self._font_glyphs(path, font, todo)
            for ch in list(todo):
                if cache.get(ch) is not None:
                    self.glyphs[ch] = _scaled(cache[ch], self._scale(index))
                    todo.discard(ch)
        for ch in todo:
            self.glyphs[ch] = None

    def __call__(self, ch):
        if ch not in self.glyphs:
            self.prefetch((ch,))
        return self.glyphs[ch]


# -----------------------------------------------------------------------------
# Overlaps
# -----------------------------------------------------------------------------
# A filled 2D curve fills all its splines together, so two glyphs whose ink
# overlaps don't merge -- the overlap renders as garbage. (Text objects dodge
# this by filling each character on its own, but that index is read-only from
# Python.) TeX happily lets ink touch: the tail of an italic y runs under the
# x before it in "xy". So: test real outline crossings, and slide the later
# glyph right by the smallest step that clears it -- usually a hairline.

NUDGE_STEP = 0.004       # Blender units at size 1
NUDGE_LIMIT = 0.08       # beyond this the overlap is deliberate; leave it be
FLATTEN_STEPS = 4        # line segments per Bezier segment for the crossing test
_EPS = 1e-7


def _loops(item, glyphs):
    """Closed polylines for one Box item, in final coordinates."""
    if item[0] == "p":
        return [list(item[1])]
    _, ch, ox, oy, sx, sy = item
    glyph = glyphs(ch)
    if glyph is None:
        return []
    loops = []
    for kind, cyclic, points in glyph.splines:
        if kind != "BEZIER":
            loops.append([(ox + p[0] * sx, oy + p[1] * sy) for p in points])
            continue
        n = len(points)
        loop = []
        for i in range(n if cyclic else n - 1):
            a, b = points[i], points[(i + 1) % n]
            x0, y0, x1, y1 = a[0], a[1], a[4], a[5]
            x2, y2, x3, y3 = b[2], b[3], b[0], b[1]
            for step in range(FLATTEN_STEPS):
                t = step / FLATTEN_STEPS
                u = 1 - t
                w0, w1, w2, w3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
                loop.append((ox + (w0 * x0 + w1 * x1 + w2 * x2 + w3 * x3) * sx,
                             oy + (w0 * y0 + w1 * y1 + w2 * y2 + w3 * y3) * sy))
        loops.append(loop)
    return loops


def _segments(loops):
    segs = []
    for loop in loops:
        for i in range(len(loop)):
            (x0, y0), (x1, y1) = loop[i - 1], loop[i]
            segs.append((x0, y0, x1, y1, min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)))
    return segs


def _bbox(segs):
    return (min(s[4] for s in segs), max(s[5] for s in segs), min(s[6] for s in segs), max(s[7] for s in segs))


def _cross(ax, ay, bx, by, cx, cy):
    v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    return 0.0 if abs(v) < _EPS else v


def _crosses(a, b, dx):
    """True when segment lists `a` and `b` (b shifted right by dx) properly cross.

    Touching end to end doesn't count -- that's how the pieces of an
    assembled bracket meet.
    """
    box_a, box_b = _bbox(a), _bbox(b)
    x0, x1 = max(box_a[0], box_b[0] + dx), min(box_a[1], box_b[1] + dx)
    y0, y1 = max(box_a[2], box_b[2]), min(box_a[3], box_b[3])
    if x0 > x1 or y0 > y1:
        return False
    near_a = [s for s in a if s[5] >= x0 and s[4] <= x1 and s[7] >= y0 and s[6] <= y1]
    near_b = [(s[0] + dx, s[1], s[2] + dx, s[3], s[4] + dx, s[5] + dx, s[6], s[7]) for s in b
              if s[5] + dx >= x0 and s[4] + dx <= x1 and s[7] >= y0 and s[6] <= y1]
    for p in near_a:
        for q in near_b:
            if p[5] < q[4] or q[5] < p[4] or p[7] < q[6] or q[7] < p[6]:
                continue
            d1 = _cross(q[0], q[1], q[2], q[3], p[0], p[1])
            d2 = _cross(q[0], q[1], q[2], q[3], p[2], p[3])
            d3 = _cross(p[0], p[1], p[2], p[3], q[0], q[1])
            d4 = _cross(p[0], p[1], p[2], p[3], q[2], q[3])
            if d1 * d2 < 0 and d3 * d4 < 0:
                return True
    return False


def separate_overlaps(box, glyphs):
    """Nudge glyphs in `box` right until no two outlines cross. In place."""
    shapes = []
    for index, item in enumerate(box.items):
        segs = _segments(_loops(item, glyphs))
        if segs:
            shapes.append([index, segs, item[0] == "g"])
    shapes.sort(key=lambda shape: _bbox(shape[1])[0])
    placed = []
    for shape in shapes:
        index, segs, movable = shape
        if movable:
            dx = 0.0
            while dx <= NUDGE_LIMIT and any(_crosses(other[1], segs, dx) for other in placed):
                dx += NUDGE_STEP
            if 0.0 < dx <= NUDGE_LIMIT:
                _, ch, x, y, sx, sy = box.items[index]
                box.items[index] = ("g", ch, x + dx, y, sx, sy)
                shape[1] = [(s[0] + dx, s[1], s[2] + dx, s[3], s[4] + dx, s[5] + dx, s[6], s[7]) for s in segs]
        placed.append(shape)


def build_curve(name, box, glyphs):
    """A filled 2D curve holding every glyph and polygon in `box`."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.resolution_u = 12   # a text object's default
    for item in box.items:
        if item[0] == "p":
            spline = curve.splines.new("POLY")
            points = item[1]
            spline.points.add(len(points) - 1)
            for point, (x, y) in zip(spline.points, points):
                point.co = (x, y, 0.0, 1.0)
            spline.use_cyclic_u = True
            continue
        _, ch, ox, oy, sx, sy = item
        glyph = glyphs(ch)
        if glyph is None:
            continue
        for kind, cyclic, points in glyph.splines:
            spline = curve.splines.new(kind)
            if kind == "BEZIER":
                spline.bezier_points.add(len(points) - 1)
                for bp, (x, y, lx, ly, rx, ry, lt, rt) in zip(spline.bezier_points, points):
                    bp.handle_left_type = lt
                    bp.handle_right_type = rt
                    bp.co = (ox + x * sx, oy + y * sy, 0.0)
                    bp.handle_left = (ox + lx * sx, oy + ly * sy, 0.0)
                    bp.handle_right = (ox + rx * sx, oy + ry * sy, 0.0)
            else:
                spline.points.add(len(points) - 1)
                for point, (x, y) in zip(spline.points, points):
                    point.co = (ox + x * sx, oy + y * sy, 0.0, 1.0)
            spline.use_cyclic_u = cyclic
    return curve


def create_latex_object(context, source):
    """Lay out `source` and link the result at the 3D cursor.

    Returns (object, glyphs the fonts couldn't supply). Raises
    latex_layout.LatexError for input that doesn't parse.
    """
    tree, chars = latex_layout.parse(source)
    glyphs = GlyphSource(context, (math_font_path(), FALLBACK_FONT))
    glyphs.prefetch(chars | latex_layout.LAYOUT_CHARS)
    box, missing = latex_layout.layout(tree, glyphs)
    if not box.items:
        raise latex_layout.LatexError("The formula draws nothing")

    separate_overlaps(box, glyphs)
    curve = build_curve("LaTeX", box, glyphs)
    obj = bpy.data.objects.new("LaTeX", curve)
    obj[OBJECT_SOURCE_KEY] = source
    obj.location = context.scene.cursor.location
    context.collection.objects.link(obj)
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj, missing


class EMANATE_OT_create_latex_object(bpy.types.Operator):
    bl_idname = NAMES_CREATE.operator_idname
    bl_label = NAMES_CREATE.label
    bl_description = NAMES_CREATE.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context.scene, LATEX_SOURCE_PROP, "").strip())

    def execute(self, context):
        source = getattr(context.scene, LATEX_SOURCE_PROP).strip()
        # People paste from documents: drop the math-mode wrapper if it came along.
        for open_, close in (("$$", "$$"), ("\\[", "\\]"), ("$", "$"), ("\\(", "\\)")):
            if source.startswith(open_) and source.endswith(close) and len(source) > len(open_) + len(close):
                source = source[len(open_):-len(close)].strip()
                break

        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            obj, missing = create_latex_object(context, source)
        except latex_layout.LatexError as exc:
            self.report({"WARNING"}, f"LaTeX: {exc}")
            return {"CANCELLED"}
        except RuntimeError as exc:
            self.report({"ERROR"}, f"LaTeX: {exc}")
            return {"CANCELLED"}

        if missing:
            shown = " ".join(sorted(missing))
            self.report({"WARNING"}, f"{obj.name}: the font has no glyph for {shown}")
        else:
            self.report({"INFO"}, f"Created {obj.name}")
        return {"FINISHED"}


class EMANATE_PT_latex_to_object(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, LATEX_SOURCE_PROP, text="")
        layout.operator(NAMES_CREATE.operator_idname, icon="FONT_DATA")


_classes = (
    EMANATE_OT_create_latex_object,
    EMANATE_PT_latex_to_object,
)


def register():
    naming.check_classes((EMANATE_OT_create_latex_object,), NAMES_CREATE)
    naming.check_classes((EMANATE_PT_latex_to_object,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)
    setattr(
        bpy.types.Scene,
        LATEX_SOURCE_PROP,
        bpy.props.StringProperty(
            name="LaTeX",
            description=(
                "Math-mode LaTeX, e.g. \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}. "
                "Use \\\\ for line breaks and & to align them"
            ),
            default="e^{i\\pi} + 1 = 0",
        ),
    )


def unregister():
    delattr(bpy.types.Scene, LATEX_SOURCE_PROP)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
