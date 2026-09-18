"""Technical drawing / measuring tools.

Nothing here touches armatures. These are scene-level annotation objects --
things you drop next to a model to read a dimension off it.

THE RULER -- "Add Ruler"
------------------------
Three objects:

    RULER_Arrow_A   a cone-and-cylinder arrow, tip on one measured point
    RULER_Arrow_B   the same mesh, tip on the other measured point
    RULER_Label     a text object floating over the middle

Grab either arrow, move it anywhere, and the label follows: it re-centres, it
re-aligns, and the number in it re-reads the distance between the two arrows.

THE ANGLE -- "Add Angle"
------------------------
Six objects:

    ANGLE_Vertex    the corner, where the two arms meet
    ANGLE_Arrow_A   tip on the end of one arm
    ANGLE_Arrow_B   tip on the end of the other
    ANGLE_Arms      two lines, vertex out to each arrow tip
    ANGLE_Arc       the sweep across the corner, down near the vertex
    ANGLE_Label     a text object outside the corner, square to the view

All three handles move freely. The two arrows are held perpendicular to their
own arm and pointing into the angle -- which is also tangent to the arc, the way
an angular dimension is drawn -- and they are kept parallel to the plane the
angle is measured in, so they never twist out of the measurement.

The arc sits at ARC_RADIUS_FRACTION of the *shorter* arm's length, so it always
crosses both arms rather than overshooting the end of the short one, and it
reads as an angle marked at the corner rather than as a cap joining the two
arrowheads. The label sits outside the corner, on the far side of the vertex
from the arc.

Its POSITION is part of the measurement; its ROTATION is not. The text copies
whatever you are looking through, and nothing else, so it reads upright from any
angle no matter what the arms are doing underneath it -- see _billboard. Name a
camera in the panel and it copies that camera instead, wherever you look.

The plane is whichever one the three handles happen to define, and each arrow's
inward direction is found from it without any explicit normal: it is the *other*
arm's component across this one, which by construction lies in the plane and
points into the wedge. Nothing here handles a reflex angle -- 0 to 180 only --
and at exactly 0 or 180 the three points are collinear, there is no plane left
to measure in, and the tool holds its last orientation rather than guessing one.

WHAT IS A CONSTRAINT AND WHAT IS A HANDLER
------------------------------------------
The ruler's label is pure constraints, because constraints are evaluated by the
depsgraph -- they stay correct mid-drag, on undo and on file load, none of which
a Python handler gets for free:

    * midpoint: two COPY_LOCATION constraints -- copy A at full influence, then
      copy B at 0.5, which lands exactly halfway between them.
    * TRACK_TO runs the label's +X along the line and keeps its +Y upright, so
      the text reads along the measurement, in the plane the line lives in.

Everything else is the handler, for two separate reasons.

The arrows carry NO constraints. The obvious build -- each arrow TRACK_TO'ing
the other so their heads point outward -- makes A's transform depend on B's and
B's on A's, and Blender reports it as a dependency cycle:

    Dependency cycle detected:
      OBRULER_Arrow_A/TRANSFORM_CONSTRAINTS() depends on
      OBRULER_Arrow_B/TRANSFORM_FINAL() via 'Track To' ...

It even resolves to the right answer most of the time, which is what makes it
worth spelling out: a cycle means the depsgraph picks an evaluation order for
you, so the wrongness shows up later as one arrow lagging a frame behind. So the
arrows stay dependency-free -- which is also what keeps them freely draggable.

And an angle's bisector, its plane, its arc and its arms are not expressible as
constraints at all, at any price.

The handler has to exist regardless, for the text: `body` is a string, and
strings are not animatable, so no driver or constraint can reach it. Everything
else it writes rides along on a pass it was already making. See
_emanate_ruler_text_update.

And there is one thing the depsgraph handler cannot see at all: orbiting the
viewport changes no data, so it schedules no update. Keeping the text square to
the view therefore needs a clock of its own -- see _install_timer.

RENDERING
---------
A curve with no bevel has no surface, so Cycles draws nothing for it -- a
measurement built out of bare wireframes is a viewport-only thing. So every part
of one carries real geometry: LINE_THICKNESS of bevel on the curves, and an
emission material, flat-coloured rather than lit, because an annotation is not
scene geometry and should not read as though it were.

The arrows are modelled rather than drawn -- see new_arrow_mesh. An outline is
a wireframe, and a wireframe beveled into tubes reads as a hollow chevron once
there is real geometry in the shot, so the head is a cone and the shaft is a
cylinder, on the silhouette the outline had.

The vertex widget is COPIED before being beveled. WGT_Centered_IcoSphere is the
tweak and PRPT bone widget all through rig_creation_tools.py, and beveling the
curve every one of those bones shares would turn each of their wireframes into
a solid tube.

Each part is also taken out of every ray type but the camera, so the labels
appear in the render without their emission lighting the model or casting
shadows across it -- see _render_visibility.

THE NUMBER
----------
A ruler reads the distance between its two arrow origins in Blender units; an
angle reads degrees. Either way it is multiplied by the measurement's Unit
Scale, then wrapped in its prefix and suffix. Which unit a *distance* is in
depends on the scene's unit scale (the Pre-Rig tools put this file on 0.01 =
centimetres), so the suffix is where you name it: prefix "R= ", suffix "mm" and
Unit Scale 10 in a centimetre scene reads "R= 30.00mm" across 3 units.

Unitless drops the number entirely and leaves the prefix and suffix, so the text
never changes again however the handles move -- for when a set of arrows is
there to point something out rather than to say how far apart it is.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

from ..helpers import naming_unity as naming
from ..helpers import widgets

NAMES = naming.register_tool(
    "tech_tools",
    label="Measurements",
    owner=__name__,
    description="Measuring and annotation objects that live in the scene rather than on a rig",
    # Last of the sub-panels: this one is not part of the rigging flow above it.
    order=80,
)

NAMES_ADD_RULER = naming.register_tool(
    "add_ruler",
    label="Add Ruler",
    owner=__name__,
    description=(
        "Adds a two-arrow ruler at the 3D cursor. Move either arrow and the text "
        "between them re-reads the distance, wrapped in the prefix and suffix above"
    ),
)

NAMES_ADD_ANGLE = naming.register_tool(
    "add_angle",
    label="Add Angle",
    owner=__name__,
    description=(
        "Adds a three-handle angle at the 3D cursor. Move the vertex or either arm "
        "and the arms, the arc, the arrows and the text re-read the angle in degrees, "
        "wrapped in the prefix and suffix above"
    ),
)

NAMES_UPDATE_TEXT = naming.register_tool(
    "update_measure_text",
    label="Update Prefix/Suffix",
    owner=__name__,
    description=(
        "Copies the fields above onto the selected measurement. Until this is pressed "
        "those fields leave the selection alone, so they can be typed up for the next "
        "measurement without disturbing the one already there"
    ),
)

# ------ What a measurement is built out of ---------------------------------
VERTEX_WIDGET = "WGT_Centered_IcoSphere"
MEASURE_COLLECTION = "RULERS"

# Arm length / arrow separation on a fresh measurement, in Blender units.
DEFAULT_SPAN = 1.0

# The arrow is modelled 1 unit long, which is the height of half a character
# next to a rig -- far too big to read as an arrowhead. These are all
# object-level, so any measurement can still be scaled by hand afterwards.
# Scaling an arrow scales it about its tip, which is where its origin sits, so
# the measured point does not move.
ARROW_SIZE = 0.2
TEXT_SIZE = 0.15
VERTEX_SIZE = 0.12

# Where the arc crosses the arms, as a fraction of the SHORTER arm's length.
# Measuring off the shorter one is what keeps the sweep between the two arms
# instead of running past the end of one; the fraction is what drops it down
# near the corner instead of capping the arrowheads.
ARC_RADIUS_FRACTION = 0.2

# How far outside the corner an angle's text sits, as a fraction of the arc
# radius -- so a big measurement pushes its text further out than a small one.
LABEL_GAP = 0.25

# Floor under that fraction, which is what the default sizes actually use.
#
# It has to clear the vertex widget, which draws at half the object scale it is
# given -- the WGT_Centered_IcoSphere points span +/-0.5. And it has to clear
# the text itself: the label's origin is the middle of the string's baseline
# (CENTER/BOTTOM), so the glyphs hang up-SCREEN from it, and since the billboard
# rotation is unrelated to which way "outside the corner" points, that overhang
# swings across the vertex as the view moves. One text size of it, plus the
# widget's radius, is what keeps "90.00" off the icosphere at the default sizes.
LABEL_CLEARANCE = VERTEX_SIZE * 0.5 + TEXT_SIZE * 1.5

# Segments in the angle arc. The point count never changes, so a refresh
# overwrites coordinates in place instead of rebuilding the spline.
ARC_SEGMENTS = 32

# Panel breathing room, as a fraction of separator()'s full row. Enough to read
# as a break between two groups of fields without opening a real gap.
UI_GAP = 0.35

# ------ How a measurement renders ------------------------------------------
# Radius of the tube every measurement line becomes, in WORLD units -- the
# per-shape bevel is this divided by the object scale it is drawn at, so an
# arrow and an arc come out the same weight on screen. Change it here for
# everything, or per object in Curve Properties > Geometry > Bevel > Depth.
LINE_THICKNESS = 0.005

# Subdivisions of the round bevel profile. 2 is a 12-sided tube: smooth enough
# at this thickness, and these curves are 33 points at their largest.
BEVEL_RESOLUTION = 2

# The arrow's proportions, in its own units, where the whole arrow is 1 long
# from the tip at the origin to the tail at -X. Head radius three times the
# shaft's is what makes an arrowhead read as one; these are the numbers the
# outline shape drew, kept so the silhouette does not change.
ARROW_HEAD_LENGTH = 0.3
ARROW_HEAD_RADIUS = 0.15
ARROW_SHAFT_RADIUS = 0.05

# Sides on the cone and the cylinder. At the size an arrowhead draws, more than
# this is polygons nobody sees.
ARROW_SEGMENTS = 16

# The four parts a measurement is made of, each with its own material and its
# own colour swatch in the panel: (part, panel label, default colour).
#
# The part name is both the material's name, as MEASURE_<part>, and the tail of
# its scene colour property. Arms and arc share one, since both are lines.
# Defaults are saturated on purpose. A white or near-white annotation is the
# obvious choice right up until it is rendered over a pale model or onto a
# transparent film, where it disappears; orange and blue read against both a
# light and a dark background.
PARTS = (
    ("Arrow", "Arrows", (0.95, 0.40, 0.05)),
    ("Vertex", "Vertex", (0.15, 0.60, 1.00)),
    ("Line", "Lines", (0.75, 0.32, 0.04)),
    ("Text", "Text", (0.95, 0.40, 0.05)),
)
PART_ARROW, PART_VERTEX, PART_LINE, PART_TEXT = (part for part, _label, _default in PARTS)

# Below this, a vector has no direction worth using -- an arm of zero length, or
# three collinear points with no plane between them. Squared, to compare against
# length_squared.
_MIN_LENGTH_SQUARED = 1e-12

# Slack for "is this value already stored?". Everything the handler writes is
# stored as 32-bit floats, so reading back what was just written never compares
# equal to the 64-bit value Python computed. Without slack the handler would
# write on every pass, and every write schedules another pass.
_TOLERANCE = 1e-6

_EULER_ORDERS = frozenset(("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"))

# How often the billboard tick re-checks which way the viewport is facing.
# Orbiting is the only thing it watches for, and 30 times a second keeps up with
# a drag without being felt.
_TICK_INTERVAL = 1.0 / 30.0
# ---------------------------------------------------------------------------

# Per-measurement settings, stored on the label object -- the label is the one
# object of the set that knows about all the others, so it is the measurement's
# identity.
#
# The property is still named "ruler", and so is the collection: those two
# strings are what gets written into .blend files, and renaming them now would
# orphan every ruler already saved in one.
MEASURE_PROP = naming.prop_name("ruler")

# The panel's four formatting fields. They are a buffer, not a view of the
# selection: a new measurement copies them, and an existing one only when the
# Update Prefix/Suffix button says so -- see _apply_authored_text. Each
# measurement keeps its own copy from the moment it is made, so two in one scene
# can read differently, and typing up the next one disturbs neither.
SCENE_PREFIX_PROP = naming.prop_name("ruler_prefix")
SCENE_SUFFIX_PROP = naming.prop_name("ruler_suffix")
SCENE_UNITLESS_PROP = naming.prop_name("ruler_unitless")
SCENE_DECIMALS_PROP = naming.prop_name("ruler_decimals")
SCENE_UNIT_SCALE_PROP = naming.prop_name("ruler_unit_scale")

# The camera every angle's text lines up to. Empty -- the default -- means the
# text follows whatever viewport it is being looked at through instead.
SCENE_CAMERA_PROP = naming.prop_name("ruler_camera")


def color_prop(part):
    """Name of the scene colour property for one part of a measurement."""
    return naming.prop_name(f"ruler_color_{part.lower()}")


def material_name(part):
    """Name of the material for one part. Also the name of its curve, where it
    has one of its own -- different ID namespaces, and the same thing named."""
    return f"MEASURE_{part}"

RULER = "RULER"
ANGLE = "ANGLE"


# ---------------------------------------------------------------------------
# Finding measurements
# ---------------------------------------------------------------------------


def measure_settings(obj):
    """The measurement settings on `obj`, or None if the property is not registered.

    getattr with a default matters during Reload Scripts: the module is
    re-executed before register() re-attaches the property, and a panel can
    redraw in between.
    """
    if obj is None:
        return None
    return getattr(obj, MEASURE_PROP, None)


def measure_handles(settings):
    """The objects a measurement needs in order to be readable at all.

    The drawings -- arms, arc -- are left out on purpose: an angle whose arc has
    been deleted still measures fine, it just stops drawing one.
    """
    if settings.kind == ANGLE:
        return (settings.vertex, settings.point_a, settings.point_b)
    return (settings.point_a, settings.point_b)


def measure_drawings(settings):
    """The objects a measurement draws into. Any of them may be missing."""
    return (settings.arms, settings.arc)


def is_measure_label(obj):
    """True if `obj` is a text object wired up as a ruler or angle label.

    Every handle is part of the test: deleting one empties the pointer that
    referenced it, and a half-deleted measurement is one to skip, not to crash
    on.
    """
    if obj is None or obj.type != "FONT":
        return False
    settings = measure_settings(obj)
    return bool(settings and all(measure_handles(settings)))


def find_measure_label(obj):
    """The label of the measurement `obj` belongs to, label or part alike."""
    if obj is None:
        return None
    if is_measure_label(obj):
        return obj
    for candidate in bpy.data.objects:
        if not is_measure_label(candidate):
            continue
        settings = measure_settings(candidate)
        if obj in (*measure_handles(settings), *measure_drawings(settings)):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _world_origin(obj, depsgraph=None):
    """Where `obj`'s origin actually is, after constraints and parenting."""
    # The depsgraph argument is the one the handler is handed. Reading the
    # evaluated copy is what lets a handle that has been parented to something
    # moving -- a bone, a rig -- measure from where it is now rather than from
    # its own rest position.
    if depsgraph is not None:
        evaluated = obj.evaluated_get(depsgraph)
        if evaluated is not None:
            obj = evaluated
    return obj.matrix_world.translation.copy()


def _resolve_scene(scene):
    """The scene to read settings from.

    scene is whatever the handler was handed. The settings callbacks and the
    billboard tick have no handler scene to pass, so they fall back to context.
    """
    return scene if scene is not None else bpy.context.scene


def _view_region():
    """The RegionView3D of the viewport being worked in, or None if there is none.

    An object has one transform and a screen can hold several 3D viewports, so
    "the view" has to be a choice: this takes the first 3D viewport of the
    active window, then any other window. Looking *through* the scene camera
    needs no special case -- in camera view a viewport's rotation is the
    camera's rotation, so the two come out the same.
    """
    active = getattr(bpy.context, "window", None)
    manager = getattr(bpy.context, "window_manager", None)
    windows = ([active] if active is not None else []) + [w for w in (manager.windows if manager else ()) if w != active]

    for window in windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region_3d = getattr(area.spaces.active, "region_3d", None)
            if region_3d is not None:
                return region_3d
    return None


def _viewer_rotation(scene=None):
    """The rotation that stands a text object square to the viewer, or None.

    A view's rotation already maps local +Z to "out of the screen, towards the
    viewer" and local +Y to "up the screen" -- which is exactly the basis a text
    object is readable in. So a label does not need aiming at anything: it
    copies a rotation outright. Nothing about where the label is, or what it
    measures, comes into it, and that is what keeps the text upright while the
    measurement moves around underneath.

    Which rotation, in order:

    1. the camera named in the panel, if one is. Naming a camera pins the text
       to it for good -- it stops following the viewport, which is the point of
       naming one.
    2. the viewport being worked in. Note that looking THROUGH a camera lands
       here and comes out the same as pinning to it, since a viewport in camera
       view carries the camera's own rotation.
    3. the scene camera, when there is no viewport to read at all -- a
       background render.

    None when none of those exist, in which case the label is left exactly as it
    is rather than snapped somewhere arbitrary.
    """
    scene = _resolve_scene(scene)

    # A camera looks down its own -Z, so its rotation already faces +Z back
    # towards itself -- the same convention as a view rotation.
    pinned = getattr(scene, SCENE_CAMERA_PROP, None) if scene else None
    if pinned is not None:
        return pinned.matrix_world.to_quaternion()

    region_3d = _view_region()
    if region_3d is not None:
        return region_3d.view_rotation.copy()

    if scene and scene.camera is not None:
        return scene.camera.matrix_world.to_quaternion()
    return None


def format_measurement(settings, value):
    """The full string a label should be showing: prefix + number + suffix.

    Or just prefix and suffix, when the measurement is unitless. The handles
    still aim, the arc still sweeps and the text still faces you -- there is
    simply no number in it, and nothing the handles do will change it.
    """
    if settings.unitless:
        return f"{settings.prefix}{settings.suffix}"
    return f"{settings.prefix}{value * settings.unit_scale:.{settings.decimals}f}{settings.suffix}"


# ---------------------------------------------------------------------------
# Writing
#
# Every write in this section goes through _unchanged first. That is not an
# optimization, it is the loop guard: these run from depsgraph_update_post, and
# writing anything schedules another depsgraph update.
# ---------------------------------------------------------------------------


def _unchanged(current, target):
    """True if `current` already holds every component of `target`.

    isclose with a relative tolerance as well as an absolute one: these values
    are stored as 32-bit floats, whose spacing grows with magnitude, so a fixed
    epsilon that works near the origin would never be satisfied out at a
    thousand units -- and the handler would rewrite, and so re-trigger itself,
    forever.
    """
    return all(math.isclose(now, want, rel_tol=_TOLERANCE, abs_tol=_TOLERANCE) for now, want in zip(current, target))


def _parent_basis(obj):
    """The matrix `obj`'s own location and rotation are measured against."""
    return obj.parent.matrix_world @ obj.matrix_parent_inverse


def _orientation(direction, up):
    """Quaternion putting local +X along `direction` and local +Z along `up`.

    On an arrow, +X is the tip, and pinning +Z is what keeps it parallel to the
    plane it is measuring in: the shape's outlines are drawn in the XY and XZ
    planes, so with +Z on the plane normal the XY outline lies flat in the
    measurement. On the text, +X reads left to right and +Z comes out of the
    page, so pinning +Z aims the readable face.
    """
    x = direction.normalized()
    z = up - x * up.dot(x)  # up, orthogonalised against the aim
    if z.length_squared < _MIN_LENGTH_SQUARED:
        # `up` is parallel to the aim, so it says nothing about roll.
        return direction.to_track_quat("X", "Z")
    z.normalize()
    # Rows x, z cross x, z -- transposed so they become the columns, which is
    # what maps local +X onto x and local +Z onto z.
    return Matrix((x, z.cross(x), z)).transposed().to_quaternion()


def _write_rotation(obj, quaternion):
    """Give `obj` this world-space rotation, in whatever rotation mode it uses."""
    if obj.parent is not None:
        # rotation_euler is measured in parent space, so a parented object needs
        # the world rotation brought into that space first.
        quaternion = _parent_basis(obj).to_quaternion().inverted() @ quaternion

    if obj.rotation_mode in _EULER_ORDERS:
        attribute = "rotation_euler"
        target = quaternion.to_euler(obj.rotation_mode)
    elif obj.rotation_mode == "QUATERNION":
        attribute = "rotation_quaternion"
        target = quaternion
    else:
        # AXIS_ANGLE. Nothing here creates one, and a user who switched to it
        # is better served by being left alone than by a lossy conversion.
        return

    if not _unchanged(getattr(obj, attribute), target):
        setattr(obj, attribute, target)


def _aim(obj, direction, up=None):
    """Point `obj`'s local +X along world-space `direction`.

    With no `up`, roll is left to to_track_quat, which is the same maths the
    Track To constraint runs. Pass `up` to pin the roll as well.
    """
    if direction.length_squared < _MIN_LENGTH_SQUARED:
        return
    _write_rotation(obj, _orientation(direction, up) if up is not None else direction.to_track_quat("X", "Z"))


def _move(obj, location):
    """Put `obj`'s origin at world-space `location`."""
    if obj.parent is not None:
        location = _parent_basis(obj).inverted_safe() @ location
    if not _unchanged(obj.location, location):
        obj.location = location


def _write_body(label, settings, value):
    """Put the formatted measurement into the label's text."""
    body = format_measurement(settings, value)
    if label.data.body != body:
        label.data.body = body


def _billboard(label, scene=None):
    """Stand `label` square to the view, upright, wherever the view happens to be.

    This is the whole of the text's rotation, with nothing of the measurement in
    it. Called from the refresh, so a new or moved measurement is right
    immediately, and from the billboard tick, so it stays right while the
    viewport orbits.
    """
    rotation = _viewer_rotation(scene)
    if rotation is not None:
        _write_rotation(label, rotation)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _paint(material, color):
    """Write `color` into both the render shader and the solid-mode swatch."""
    for node in material.node_tree.nodes:
        if node.type == "EMISSION":
            node.inputs["Color"].default_value = (*color, 1.0)
    # Solid shading reads diffuse_color, Cycles reads the node. One swatch in
    # the panel has to move both or the viewport and the render disagree.
    material.diffuse_color = (*color, 1.0)


def measure_material(part, scene=None):
    """The emission material for one part of a measurement, built on first use.

    Emission, not a lit shader: an annotation is not scene geometry, and should
    come out the colour it was given instead of picking up the lighting of
    whatever it is measuring.
    """
    name = material_name(part)
    material = bpy.data.materials.get(name)
    if material is not None:
        return material

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    emission = tree.nodes.new("ShaderNodeEmission")
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (200.0, 0.0)
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])

    scene = _resolve_scene(scene)
    color = getattr(scene, color_prop(part), None) if scene else None
    _paint(material, tuple(color) if color is not None else dict((p, d) for p, _l, d in PARTS)[part])
    return material


def _colors_changed(self, context):
    """Push the panel's swatches into the materials that have been built."""
    for part, _label, _default in PARTS:
        material = bpy.data.materials.get(material_name(part))
        if material is not None:
            _paint(material, tuple(getattr(self, color_prop(part))))


def _render_visibility(obj):
    """Camera rays only.

    A measurement should show up in the render without its emission lighting the
    model, bouncing off it, or casting a shadow across the thing being measured.
    """
    obj.visible_diffuse = False
    obj.visible_glossy = False
    obj.visible_transmission = False
    obj.visible_volume_scatter = False
    obj.visible_shadow = False


def _make_renderable(curve, part, bevel_depth, scene=None):
    """Give `curve` a surface Cycles can see, and the colour of its part."""
    curve.bevel_depth = bevel_depth
    curve.bevel_resolution = BEVEL_RESOLUTION
    # Open curves -- the arms, the arc -- are hollow pipes without this.
    curve.use_fill_caps = True
    curve.materials.append(measure_material(part, scene))
    return curve


def new_arrow_mesh(scene=None):
    """The arrow: a cone for the head, a cylinder for the shaft, built once.

    Tip on the origin and body trailing down -X -- the same pivot, length and
    silhouette as the outline it replaces, so it aims, scales and lands on a
    measured point exactly as before. Solid, because a beveled outline reads as
    a hollow chevron next to real geometry.

    Shared by every arrow in the file, the way the widget curves are: the mesh
    is identical for all of them, and only the object transform differs.
    """
    name = material_name(PART_ARROW)
    existing = bpy.data.meshes.get(name)
    if existing is not None:
        return existing

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    # create_cone builds around the origin along +Z, so each piece is turned
    # onto +X and then slid back down the shaft to where it belongs.
    onto_x = Matrix.Rotation(math.radians(90.0), 4, "Y")

    # Head: apex at the origin, base ARROW_HEAD_LENGTH behind it. radius2 = 0 is
    # what makes the +Z end a point rather than a cap.
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=ARROW_SEGMENTS,
        radius1=ARROW_HEAD_RADIUS,
        radius2=0.0,
        depth=ARROW_HEAD_LENGTH,
        matrix=Matrix.Translation((-ARROW_HEAD_LENGTH / 2.0, 0.0, 0.0)) @ onto_x,
    )

    # Shaft: from the back of the head to the tail at -1.
    shaft_length = 1.0 - ARROW_HEAD_LENGTH
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=ARROW_SEGMENTS,
        radius1=ARROW_SHAFT_RADIUS,
        radius2=ARROW_SHAFT_RADIUS,
        depth=shaft_length,
        matrix=Matrix.Translation((-ARROW_HEAD_LENGTH - shaft_length / 2.0, 0.0, 0.0)) @ onto_x,
    )

    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(measure_material(PART_ARROW, scene))
    return mesh


def measure_curve(widget, part, size, scene=None):
    """A renderable copy of widget shape `widget`, shared by every part like it.

    A copy, because the widget curve belongs to the bones that use it as a
    custom shape -- WGT_Centered_IcoSphere is every tweak in the rig -- and
    beveling it would turn all of them into tubes.

    `size` is the object scale the copy will be drawn at, and the bevel is
    divided by it so one LINE_THICKNESS covers parts drawn at different scales.
    """
    name = material_name(part)
    existing = bpy.data.curves.get(name)
    if existing is not None:
        return existing

    curve = widgets.get_widget_curve(widget).copy()
    curve.name = name
    return _make_renderable(curve, part, LINE_THICKNESS / size, scene)


# ---------------------------------------------------------------------------
# The curves the handler draws into
#
# An angle's arms and arc are not shapes with a transform, they are drawings:
# their points are the picture, and every refresh recomputes them. The objects
# they live in stay untransformed and unselectable.
# ---------------------------------------------------------------------------


def new_drawing_curve(name, point_counts, scene=None):
    """A curve of open poly splines, one per entry in `point_counts`.

    Not shared between measurements the way the arrow curve is: every angle
    draws a different sweep. Drawn at object scale 1, so it takes the line
    thickness as it is.
    """
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    for count in point_counts:
        spline = curve.splines.new("POLY")
        # A new spline arrives with one point already in it.
        spline.points.add(count - 1)
    return _make_renderable(curve, PART_LINE, LINE_THICKNESS, scene)


def _drawing_splines(obj, strokes):
    """`obj`'s splines, if they match `strokes` point for point. None otherwise."""
    if obj is None or obj.type != "CURVE":
        return None
    splines = obj.data.splines
    if len(splines) != len(strokes):
        return None
    if any(len(spline.points) != len(stroke) for spline, stroke in zip(splines, strokes)):
        return None
    return splines


def _draw(obj, strokes):
    """Draw `strokes` -- one list of world-space points per spline -- into `obj`."""
    splines = _drawing_splines(obj, strokes)
    if splines is None:
        return

    # Points are stored in the object's own space. These objects are created
    # untransformed, so this is the identity -- but it costs one matrix multiply
    # to also be right for a drawing that has been moved since.
    to_local = obj.matrix_world.inverted_safe()

    dirty = False
    for spline, stroke in zip(splines, strokes):
        flat = []
        for point in stroke:
            local = to_local @ point
            flat.extend((local.x, local.y, local.z, 1.0))

        current = [0.0] * len(flat)
        spline.points.foreach_get("co", current)
        if _unchanged(current, flat):
            continue
        spline.points.foreach_set("co", flat)
        dirty = True

    if dirty:
        # foreach_set writes straight into the point array without going through
        # RNA, so nothing has told Blender the curve changed. Without this the
        # viewport keeps drawing the previous version.
        obj.data.update_tag()


def _draw_arms(arms, vertex, point_a, point_b):
    """One line from the vertex out to each arrow tip."""
    _draw(arms, ([vertex, point_a], [vertex, point_b]))


def _draw_arc(arc, vertex, start, normal, angle, radius):
    """Sweep the arc from `start` about `normal` through `angle`, at `radius`."""
    points = []
    for step in range(ARC_SEGMENTS + 1):
        offset = start.copy()
        offset.rotate(Quaternion(normal, angle * step / ARC_SEGMENTS))
        points.append(vertex + offset * radius)
    _draw(arc, (points,))


def _collapse_arc(arc, vertex):
    """Draw nothing: every point on the vertex, so there is no sweep to see.

    For collinear arms. There is no plane, so there is no arc -- and holding the
    last one drawn would leave a sweep hanging in a plane that no longer exists.
    """
    _draw(arc, ([vertex] * (ARC_SEGMENTS + 1),))


# ---------------------------------------------------------------------------
# Refreshing
# ---------------------------------------------------------------------------


def _refresh_ruler(label, settings, depsgraph=None, scene=None):
    """Aim a ruler's arrows and write its distance."""
    point_a = _world_origin(settings.point_a, depsgraph)
    point_b = _world_origin(settings.point_b, depsgraph)

    # Each arrow aims its +X -- which is where the tip is -- away from the other
    # one, so the two heads end up back to back, <--- --->, the way a dimension
    # is drawn. The tip is the arrow mesh's origin, so each head lands exactly
    # on its measured point and the shaft trails inward.
    _aim(settings.point_a, point_a - point_b)
    _aim(settings.point_b, point_b - point_a)

    _write_body(label, settings, (point_b - point_a).length)


def _refresh_angle(label, settings, depsgraph=None, scene=None):
    """Draw an angle's arms and arc, aim its arrows, place its text, write its degrees."""
    vertex = _world_origin(settings.vertex, depsgraph)
    point_a = _world_origin(settings.point_a, depsgraph)
    point_b = _world_origin(settings.point_b, depsgraph)
    arm_a = point_a - vertex
    arm_b = point_b - vertex

    # The fallback is what Vector.angle returns instead of raising when either
    # arm has no length -- a handle sitting exactly on the vertex.
    angle = arm_a.angle(arm_b, 0.0)
    _write_body(label, settings, math.degrees(angle))

    # The arms are just the two lines, so they are drawn whatever the angle has
    # collapsed to.
    _draw_arms(settings.arms, vertex, point_a, point_b)

    # The plane the angle is measured in. Zero length means the two arms are
    # collinear -- 0 or 180 degrees -- or one of them has collapsed onto the
    # vertex. Either way there is no plane, so there is no perpendicular to aim
    # the arrows along and no arc to sweep.
    normal = arm_a.cross(arm_b)
    collinear = normal.length_squared < _MIN_LENGTH_SQUARED

    if collinear:
        _collapse_arc(settings.arc, vertex)
    else:
        normal.normalize()

        # Where "inward" is, without needing the normal: the other arm's
        # component across this one. It lies in the plane, and it points into
        # the wedge, for any angle between 0 and 180. It is also the arc's
        # tangent where it crosses this arm, which is why the arrows sit square
        # to it.
        inward_a = arm_b - arm_a * (arm_b.dot(arm_a) / arm_a.length_squared)
        inward_b = arm_a - arm_b * (arm_a.dot(arm_b) / arm_b.length_squared)
        _aim(settings.point_a, inward_a, normal)
        _aim(settings.point_b, inward_b, normal)

        radius = min(arm_a.length, arm_b.length) * ARC_RADIUS_FRACTION
        _draw_arc(settings.arc, vertex, arm_a.normalized(), normal, angle, radius)

        # The text goes on the far side of the vertex from the wedge, which is
        # straight back down the bisector. Position only: its rotation is
        # deliberately none of the angle's business.
        bisector = arm_a.normalized() + arm_b.normalized()
        if bisector.length_squared > _MIN_LENGTH_SQUARED:
            outward = -bisector.normalized()
            _move(label, vertex + outward * max(radius * LABEL_GAP, LABEL_CLEARANCE))

    _billboard(label, scene)


_REFRESH = {RULER: _refresh_ruler, ANGLE: _refresh_angle}


def refresh_measure(label, depsgraph=None, scene=None):
    """Re-read one measurement. `label` must pass is_measure_label."""
    settings = measure_settings(label)
    _REFRESH[settings.kind](label, settings, depsgraph, scene)


def refresh_measures(depsgraph=None, scene=None):
    """Re-read every measurement, and note which labels the billboard tick wants.

    The tick runs 30 times a second and must not walk every object in the file
    to find five of them, so the walk that is happening anyway leaves it a list.
    Names rather than object references: a name cannot become a dangling pointer
    when the label it refers to is deleted.
    """
    labels = []
    for obj in bpy.data.objects:
        if not is_measure_label(obj):
            continue
        refresh_measure(obj, depsgraph, scene)
        if measure_settings(obj).kind == ANGLE:
            labels.append(obj.name)
    _angle_labels[:] = labels


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _settings_changed(self, context):
    """Typing in a prefix/suffix field has to repaint the text right away.

    Editing a property does not move anything, so there may be no depsgraph
    update to ride on -- refresh straight from the update callback instead.
    """
    refresh_measures()


def _camera_only(self, obj):
    """Keep the camera field -- its dropdown and its eyedropper -- to cameras."""
    return obj.type == "CAMERA"


def _apply_authored_text(scene, settings):
    """Copy the panel's formatting fields onto one measurement.

    The only route from those fields to a measurement: taken once when a
    measurement is built, and again whenever the Update Prefix/Suffix button is
    pressed. Nothing else writes them, which is what keeps a selected label
    still while the fields are being typed up for the next one.
    """
    settings.prefix = getattr(scene, SCENE_PREFIX_PROP)
    settings.suffix = getattr(scene, SCENE_SUFFIX_PROP)
    settings.unitless = getattr(scene, SCENE_UNITLESS_PROP)
    settings.decimals = getattr(scene, SCENE_DECIMALS_PROP)
    settings.unit_scale = getattr(scene, SCENE_UNIT_SCALE_PROP)


class EMANATE_PG_ruler(bpy.types.PropertyGroup):
    """Everything one measurement needs, hung off its label object."""

    kind: bpy.props.EnumProperty(
        name="Kind",
        description="What this label measures",
        items=((RULER, "Ruler", "Distance between two points"), (ANGLE, "Angle", "Angle at a vertex, in degrees")),
        # Rulers predate angles, and a ruler saved before this existed has to
        # keep loading as one.
        default=RULER,
    )
    prefix: bpy.props.StringProperty(name="Prefix", description='Text before the measurement, e.g. "R= "', update=_settings_changed)
    suffix: bpy.props.StringProperty(name="Suffix", description='Text after the measurement, e.g. "mm"', update=_settings_changed)
    unitless: bpy.props.BoolProperty(
        name="Unitless",
        description="Leave the number out and show only the prefix and suffix, so the text stays put however the handles move",
        default=False,
        update=_settings_changed,
    )
    decimals: bpy.props.IntProperty(
        name="Decimals",
        description='Digits after the decimal point. 0 reads "3" instead of "3.00"',
        default=2,
        min=0,
        max=6,
        update=_settings_changed,
    )
    unit_scale: bpy.props.FloatProperty(
        name="Unit Scale",
        description=(
            "Multiplies the raw measurement before it is displayed. Leave at 1 to read "
            "Blender units, or degrees; set 10 to read millimetres in a centimetre-scaled scene"
        ),
        default=1.0,
        min=0.0,
        soft_max=1000.0,
        update=_settings_changed,
    )
    point_a: bpy.props.PointerProperty(name="Point A", type=bpy.types.Object)
    point_b: bpy.props.PointerProperty(name="Point B", type=bpy.types.Object)
    vertex: bpy.props.PointerProperty(name="Vertex", type=bpy.types.Object, description="An angle's corner. Unused by a ruler")
    arms: bpy.props.PointerProperty(name="Arms", type=bpy.types.Object, description="The curve an angle draws its two arms into")
    arc: bpy.props.PointerProperty(name="Arc", type=bpy.types.Object, description="The curve an angle sweeps across its corner")


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def measure_collection(scene):
    """The measurements collection, made and linked to the scene if it isn't there.

    children_recursive rather than scene.collection.children: the collection may
    already be nested inside another one, and linking a second time raises.
    """
    collection = bpy.data.collections.get(MEASURE_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(MEASURE_COLLECTION)

    if collection not in scene.collection.children_recursive:
        scene.collection.children.link(collection)
    return collection


def _add_handle(name, data, size, location, collection):
    """A draggable handle: its own object around shared, renderable data.

    No constraints, by design -- see the module docstring. The handles are the
    only objects in a measurement the user ever grabs.
    """
    handle = bpy.data.objects.new(name, data)
    handle.location = location
    handle.scale = (size, size, size)
    # A measurement you cannot see behind the model is no measurement.
    handle.show_in_front = True
    _render_visibility(handle)
    collection.objects.link(handle)
    return handle


def _add_label(name, collection, kind, scene):
    """The text object for a measurement."""
    text = bpy.data.curves.new(name, type="FONT")
    text.size = TEXT_SIZE
    # CENTER/BOTTOM puts the string centred on whatever it is aligned to, and
    # sitting above it rather than straddling it.
    text.align_x = "CENTER"
    text.align_y = "BOTTOM"

    text.materials.append(measure_material(PART_TEXT, scene))

    label = bpy.data.objects.new(name, text)
    label.show_in_front = True
    _render_visibility(label)
    # The label is not a handle. Making it unselectable means a click-drag near
    # it still grabs the handle the user was aiming for.
    label.hide_select = True
    collection.objects.link(label)

    settings = measure_settings(label)
    settings.kind = kind
    _apply_authored_text(scene, settings)
    return label


def _add_drawing(name, collection, point_counts, scene):
    """A curve object the handler redraws. Its points are written every refresh."""
    drawing = bpy.data.objects.new(name, new_drawing_curve(name, point_counts, scene))
    drawing.show_in_front = True
    _render_visibility(drawing)
    # Unselectable for the same reason as the label, and additionally because
    # its points are stored in its own space: dragging it would take the drawing
    # with it and leave the picture sitting off the corner it belongs to.
    drawing.hide_select = True
    collection.objects.link(drawing)
    return drawing


def _finish(context, label, active):
    """Evaluate the new objects, read the measurement, hand back one handle."""
    # matrix_world on a brand new object is still identity until the depsgraph
    # has run, and the first measurement is read off matrix_world.
    context.view_layer.update()
    refresh_measure(label, scene=context.scene)

    # Deselect by hand rather than with select_all, which would need a context
    # the operator may not have.
    for obj in context.selected_objects:
        obj.select_set(False)
    active.select_set(True)
    context.view_layer.objects.active = active


def add_ruler(context):
    """Build a ruler at the 3D cursor. Returns (arrow_a, arrow_b, label)."""
    collection = measure_collection(context.scene)
    origin = Vector(context.scene.cursor.location)

    arrow = new_arrow_mesh(context.scene)
    arrow_a = _add_handle("RULER_Arrow_A", arrow, ARROW_SIZE, origin, collection)
    arrow_b = _add_handle("RULER_Arrow_B", arrow, ARROW_SIZE, origin + Vector((DEFAULT_SPAN, 0.0, 0.0)), collection)

    label = _add_label("RULER_Label", collection, RULER, context.scene)
    settings = measure_settings(label)
    settings.point_a = arrow_a
    settings.point_b = arrow_b

    # The one part of a measurement constraints can carry on their own: copy A
    # at full influence, then copy B at 0.5, and the label lands halfway.
    midpoint_a = label.constraints.new("COPY_LOCATION")
    midpoint_a.target = arrow_a
    midpoint_b = label.constraints.new("COPY_LOCATION")
    midpoint_b.target = arrow_b
    midpoint_b.influence = 0.5

    align = label.constraints.new("TRACK_TO")
    align.target = arrow_b
    align.track_axis = "TRACK_X"
    align.up_axis = "UP_Y"

    _finish(context, label, arrow_b)
    return arrow_a, arrow_b, label


def add_angle(context):
    """Build a 90-degree angle at the 3D cursor. Returns (vertex, a, b, label)."""
    collection = measure_collection(context.scene)
    origin = Vector(context.scene.cursor.location)

    # Opened in XZ: the plane the widget shapes are drawn in, and the one the
    # front view looks straight at.
    scene = context.scene
    arrow = new_arrow_mesh(scene)
    vertex = _add_handle("ANGLE_Vertex", measure_curve(VERTEX_WIDGET, PART_VERTEX, VERTEX_SIZE, scene), VERTEX_SIZE, origin, collection)
    arrow_a = _add_handle("ANGLE_Arrow_A", arrow, ARROW_SIZE, origin + Vector((DEFAULT_SPAN, 0.0, 0.0)), collection)
    arrow_b = _add_handle("ANGLE_Arrow_B", arrow, ARROW_SIZE, origin + Vector((0.0, 0.0, DEFAULT_SPAN)), collection)
    arms = _add_drawing("ANGLE_Arms", collection, (2, 2), scene)
    arc = _add_drawing("ANGLE_Arc", collection, (ARC_SEGMENTS + 1,), scene)

    label = _add_label("ANGLE_Label", collection, ANGLE, context.scene)
    settings = measure_settings(label)
    settings.vertex = vertex
    settings.point_a = arrow_a
    settings.point_b = arrow_b
    settings.arms = arms
    settings.arc = arc

    _finish(context, label, arrow_b)
    return vertex, arrow_a, arrow_b, label


# ---------------------------------------------------------------------------
# The handler that keeps a measurement live
# ---------------------------------------------------------------------------

_in_update = False


@bpy.app.handlers.persistent
def _emanate_ruler_text_update(scene, depsgraph=None):
    """Keep every measurement in step with its handles.

    persistent so it survives loading a file. The depsgraph argument is absent
    from frame_change_post on older Blender versions, hence the default.

    The re-entrancy guard and the _unchanged tests on every write are two halves
    of the same job: this handler writes data, writing data schedules another
    depsgraph update, and that update lands back here.
    """
    global _in_update
    if _in_update:
        return
    _in_update = True
    try:
        refresh_measures(depsgraph=depsgraph, scene=scene)
    finally:
        _in_update = False


def _handler_lists():
    """Every handler list this module appends to."""
    return (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post)


def _remove_handlers():
    """Drop our handler from every list, matching on name rather than identity.

    Reload Scripts re-executes this module, which builds a *new* function
    object -- so the already-registered handler is no longer `is` anything this
    module can reach. Its __name__ is still ours, and matching on that is what
    makes this idempotent instead of stacking a second copy on every reload.
    """
    name = _emanate_ruler_text_update.__name__
    for handlers in _handler_lists():
        for handler in list(handlers):
            if getattr(handler, "__name__", None) == name:
                handlers.remove(handler)


def _install_handlers():
    _remove_handlers()
    for handlers in _handler_lists():
        handlers.append(_emanate_ruler_text_update)


# ---------------------------------------------------------------------------
# The clock that keeps the text square to the view
#
# Moving anything schedules a depsgraph update, and the handler above catches
# it. ORBITING does not: the view turns, no data changes, and nothing is
# scheduled -- so the handler never hears that the text is now sideways. The
# only two places that do hear it are a draw callback, where writing to objects
# is not allowed, and a timer, which runs on the main thread between events and
# may write freely. Hence a timer.
# ---------------------------------------------------------------------------

# Names of the angle labels the tick keeps square to the view, left here by
# refresh_measures so the tick never walks bpy.data.objects itself.
_angle_labels = []

# Identity of the live tick. Re-registering -- or a Reload Scripts -- mints a
# new token, and any tick still running against an older one retires itself on
# its next call. That is the only way to stop a timer whose function object has
# been replaced: bpy.app.timers cannot be enumerated, and is_registered() wants
# the exact function that was registered, which a reload has already discarded.
_tick_token = None


def _install_timer():
    global _tick_token
    token = object()
    _tick_token = token

    def tick():
        if _tick_token is not token:
            return None
        if _angle_labels:
            rotation = _viewer_rotation()
            if rotation is not None:
                for name in _angle_labels:
                    label = bpy.data.objects.get(name)
                    if label is not None:
                        _write_rotation(label, rotation)
        return _TICK_INTERVAL

    # persistent, or it would stop the first time a file is opened.
    bpy.app.timers.register(tick, first_interval=_TICK_INTERVAL, persistent=True)


def _remove_timer():
    """Retire the live tick. It sees the token has gone and stops itself."""
    global _tick_token
    _tick_token = None


# ---------------------------------------------------------------------------
# Operators and panel
# ---------------------------------------------------------------------------


class EMANATE_OT_add_ruler(bpy.types.Operator):
    bl_idname = NAMES_ADD_RULER.operator_idname
    bl_label = NAMES_ADD_RULER.label
    bl_description = NAMES_ADD_RULER.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # Linking new objects and selecting them is object-mode work.
        return context.mode == "OBJECT"

    def execute(self, context):
        arrow_a, arrow_b, label = add_ruler(context)
        self.report({"INFO"}, f"Added {label.name} -- move {arrow_a.name} or {arrow_b.name} to measure")
        return {"FINISHED"}


class EMANATE_OT_add_angle(bpy.types.Operator):
    bl_idname = NAMES_ADD_ANGLE.operator_idname
    bl_label = NAMES_ADD_ANGLE.label
    bl_description = NAMES_ADD_ANGLE.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        vertex, arrow_a, arrow_b, label = add_angle(context)
        self.report({"INFO"}, f"Added {label.name} -- move {vertex.name}, {arrow_a.name} or {arrow_b.name} to measure")
        return {"FINISHED"}


class EMANATE_OT_update_measure_text(bpy.types.Operator):
    bl_idname = NAMES_UPDATE_TEXT.operator_idname
    bl_label = NAMES_UPDATE_TEXT.label
    bl_description = NAMES_UPDATE_TEXT.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # Greyed out rather than hidden: the button is what the fields are for,
        # so it should be visible even with nothing selected to apply them to.
        return find_measure_label(context.active_object) is not None

    def execute(self, context):
        label = find_measure_label(context.active_object)
        if label is None:
            self.report({"WARNING"}, "Select a measurement first")
            return {"CANCELLED"}

        _apply_authored_text(context.scene, measure_settings(label))
        refresh_measure(label, scene=context.scene)

        self.report({"INFO"}, f"{label.name} now reads {label.data.body!r}")
        return {"FINISHED"}


class EMANATE_PT_tech_tools(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Which measurement the Update button at the bottom would write to.
        label = find_measure_label(context.active_object)
        if label is not None:
            layout.label(text=label.name, icon="FONT_DATA")

        # These four are a buffer for the next measurement, not a view of the
        # selected one -- see _apply_authored_text.
        strings = layout.column(align=True)
        strings.prop(scene, SCENE_PREFIX_PROP)
        strings.prop(scene, SCENE_SUFFIX_PROP)
        strings.prop(scene, SCENE_UNITLESS_PROP)

        layout.separator(factor=UI_GAP)
        numbers = layout.column(align=True)
        # Greyed rather than hidden: they are still what the next measurement
        # will use, they just have no number to format while Unitless is on.
        numbers.active = not getattr(scene, SCENE_UNITLESS_PROP)
        numbers.prop(scene, SCENE_DECIMALS_PROP)
        numbers.prop(scene, SCENE_UNIT_SCALE_PROP)

        if context.mode != "OBJECT":
            layout.label(text="Object Mode to add a measurement", icon="INFO")

        layout.operator(NAMES_ADD_RULER.operator_idname, icon="DRIVER_DISTANCE")

        # The camera goes with the angle button it affects. Blender draws an ID
        # pointer as a search field with an eyedropper of its own, so picking
        # from the viewport or the outliner comes for free.
        angle = layout.column(align=True)
        angle.operator(NAMES_ADD_ANGLE.operator_idname, icon="DRIVER_ROTATIONAL_DIFFERENCE")
        angle.separator(factor=UI_GAP)
        angle.prop(scene, SCENE_CAMERA_PROP, text="Camera to Look At")

        layout.operator(NAMES_UPDATE_TEXT.operator_idname, icon="FILE_REFRESH")

        # Collapsed by default, and a layout panel rather than a class of its
        # own: naming_unity wants every registered panel parented to the root,
        # and this is a section of this one rather than a panel in its own right.
        header, body = layout.panel("emanate_measure_colors", default_closed=True)
        header.label(text="Colors")
        if body:
            for part, _label, _default in PARTS:
                body.prop(scene, color_prop(part))
            body.label(text=f"= emission on {material_name('*')} materials", icon="MATERIAL")


# EMANATE_PG_ruler is deliberately left out of check_classes: it only knows the
# _OT_ and _PT_ tags, and reports a _PG_ class as untagged.
_classes = (EMANATE_PG_ruler, EMANATE_OT_add_ruler, EMANATE_OT_add_angle, EMANATE_OT_update_measure_text, EMANATE_PT_tech_tools)


def register():
    naming.check_classes((EMANATE_OT_add_ruler,), NAMES_ADD_RULER)
    naming.check_classes((EMANATE_OT_add_angle,), NAMES_ADD_ANGLE)
    naming.check_classes((EMANATE_OT_update_measure_text,), NAMES_UPDATE_TEXT)
    naming.check_classes((EMANATE_PT_tech_tools,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)

    # After register_class(EMANATE_PG_ruler), never before -- PointerProperty
    # needs the group registered to point at it.
    setattr(bpy.types.Object, MEASURE_PROP, bpy.props.PointerProperty(type=EMANATE_PG_ruler))

    setattr(
        bpy.types.Scene,
        SCENE_PREFIX_PROP,
        bpy.props.StringProperty(name="Prefix", description='Text placed before the measurement on the next one you add, e.g. "R= "', default=""),
    )
    setattr(
        bpy.types.Scene,
        SCENE_SUFFIX_PROP,
        bpy.props.StringProperty(name="Suffix", description='Text placed after the measurement on the next one you add, e.g. "mm"', default=""),
    )
    setattr(
        bpy.types.Scene,
        SCENE_UNITLESS_PROP,
        bpy.props.BoolProperty(
            name="Unitless",
            description=(
                "Leave the measurement out of the next one you add, and show only the prefix "
                "and suffix. A static caption on a set of handles rather than a live reading"
            ),
            default=False,
        ),
    )
    setattr(
        bpy.types.Scene,
        SCENE_DECIMALS_PROP,
        bpy.props.IntProperty(
            name="Decimals",
            description='Digits after the decimal point, for the next measurement you add. 0 reads "3" instead of "3.00"',
            default=2,
            min=0,
            max=6,
        ),
    )
    setattr(
        bpy.types.Scene,
        SCENE_UNIT_SCALE_PROP,
        bpy.props.FloatProperty(
            name="Unit Scale",
            description=(
                "Multiplies the raw measurement before it is displayed, for the next one you "
                "add. Leave at 1 to read Blender units, or degrees; set 10 to read millimetres "
                "in a centimetre-scaled scene"
            ),
            default=1.0,
            min=0.0,
            soft_max=1000.0,
        ),
    )
    setattr(
        bpy.types.Scene,
        SCENE_CAMERA_PROP,
        bpy.props.PointerProperty(
            name="Text Faces",
            description=(
                "Camera that every angle's text lines up to. Leave it empty and the text "
                "faces whichever viewport you are looking through instead, which is also "
                "what a camera here gives you while you look through that camera"
            ),
            type=bpy.types.Object,
            poll=_camera_only,
            update=_settings_changed,
        ),
    )

    for part, label, default in PARTS:
        setattr(
            bpy.types.Scene,
            color_prop(part),
            bpy.props.FloatVectorProperty(
                name=label,
                description=f"Colour of every measurement's {label.lower()}, in the viewport and in a render",
                subtype="COLOR",
                size=3,
                min=0.0,
                max=1.0,
                default=default,
                update=_colors_changed,
            ),
        )

    _install_handlers()
    _install_timer()


def unregister():
    _remove_timer()
    _remove_handlers()

    for part, _label, _default in PARTS:
        delattr(bpy.types.Scene, color_prop(part))

    delattr(bpy.types.Scene, SCENE_CAMERA_PROP)
    delattr(bpy.types.Scene, SCENE_UNIT_SCALE_PROP)
    delattr(bpy.types.Scene, SCENE_DECIMALS_PROP)
    delattr(bpy.types.Scene, SCENE_UNITLESS_PROP)
    delattr(bpy.types.Scene, SCENE_SUFFIX_PROP)
    delattr(bpy.types.Scene, SCENE_PREFIX_PROP)
    delattr(bpy.types.Object, MEASURE_PROP)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
