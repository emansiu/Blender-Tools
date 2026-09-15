"""Technical drawing / measuring tools.

Nothing here touches armatures. These are scene-level annotation objects --
things you drop next to a model to read a dimension off it.

THE RULER
---------
"Add Ruler" builds three objects:

    RULER_Arrow_A   an Arrows_For_Rulers curve, tip on one measured point
    RULER_Arrow_B   the same curve, tip on the other measured point
    RULER_Label     a text object floating over the middle

Grab either arrow, move it anywhere, and the label follows: it re-centres, it
re-aligns, and the number in it re-reads the distance between the two arrows.

WHAT IS A CONSTRAINT AND WHAT IS A HANDLER
------------------------------------------
The label is pure constraints, because constraints are evaluated by the
depsgraph -- they stay correct mid-drag, on undo and on file load, none of
which a Python handler gets for free:

    * midpoint: two COPY_LOCATION constraints -- copy A at full influence, then
      copy B at 0.5, which lands exactly halfway between them.
    * TRACK_TO runs the label's +X along the line and keeps its +Y upright, so
      the text reads along the measurement, in the plane the line lives in.

The arrows deliberately carry NO constraints. The obvious build -- each arrow
TRACK_TO'ing the other so their heads point outward -- makes A's transform
depend on B's and B's on A's, and Blender reports it as a dependency cycle:

    Dependency cycle detected:
      OBRULER_Arrow_A/TRANSFORM_CONSTRAINTS() depends on
      OBRULER_Arrow_B/TRANSFORM_FINAL() via 'Track To' ...

It even resolves to the right answer most of the time, which is what makes it
worth spelling out: a cycle means the depsgraph picks an evaluation order for
you, so the wrongness shows up later as one arrow lagging a frame behind. So
the arrows stay dependency-free -- nothing at all constrains them, which is
also what keeps them freely draggable -- and the handler aims them instead.

The handler has to exist regardless, for the text: `body` is a string, and
strings are not animatable, so no driver or constraint can reach it. Aiming two
arrows on the same pass it is already making is close to free. See
_emanate_ruler_text_update.

THE NUMBER
----------
It is the raw distance between the two arrow origins in Blender units, times
the ruler's Unit Scale. Which unit that *is* depends on the scene's unit scale
(the Pre-Rig tools put this file on 0.01 = centimetres), so the suffix is where
you name it: prefix "R= ", suffix "mm" and Unit Scale 10 in a centimetre scene
reads "R= 30.00mm" across 3 units.
"""

import bpy
from mathutils import Vector

from ..helpers import naming_unity as naming
from ..helpers import widgets

NAMES = naming.register_tool(
    "tech_tools",
    label="Tech Tools",
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

# ------ What the ruler is built out of -------------------------------------
ARROW_WIDGET = "Arrows_For_Rulers"
RULER_COLLECTION = "RULERS"

# Distance between the two arrows on a fresh ruler, in Blender units.
DEFAULT_SPAN = 1.0

# The arrow curve is drawn 1 unit long, which is the height of half a character
# next to a rig -- far too big to read as an arrowhead. Both of these are
# object-level, so any ruler can still be scaled by hand afterwards. Scaling
# an arrow scales it about its tip, which is where its origin sits, so the
# measured point does not move.
ARROW_SIZE = 0.2
TEXT_SIZE = 0.15

# Below this separation there is no direction left to aim the arrows along, so
# they keep the rotation they had. Squared, to compare against length_squared.
_MIN_SPAN_SQUARED = 1e-12

# Rotation is stored as 32-bit floats, so reading back what we just wrote never
# compares equal to the 64-bit value Python computed. Without slack here the
# handler would write on every pass, and every write schedules another pass.
_ROTATION_EPSILON = 1e-6

_EULER_ORDERS = frozenset(("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"))
# ---------------------------------------------------------------------------

# Per-ruler settings, stored on the label object -- the label is the one object
# of the three that knows about the other two, so it is the ruler's identity.
RULER_PROP = naming.prop_name("ruler")

# The two fields above the button. These seed a NEW ruler; each ruler keeps its
# own copy from then on, so two rulers in one scene can read differently.
SCENE_PREFIX_PROP = naming.prop_name("ruler_prefix")
SCENE_SUFFIX_PROP = naming.prop_name("ruler_suffix")


# ---------------------------------------------------------------------------
# Finding rulers
# ---------------------------------------------------------------------------


def ruler_settings(obj):
    """The ruler settings on `obj`, or None if the property is not registered.

    getattr with a default matters during Reload Scripts: the module is
    re-executed before register() re-attaches the property, and a panel can
    redraw in between.
    """
    if obj is None:
        return None
    return getattr(obj, RULER_PROP, None)


def is_ruler_label(obj):
    """True if `obj` is a text object wired up as a ruler label.

    Both endpoints are part of the test: deleting an arrow empties the pointer
    that referenced it, and a half-deleted ruler is one to skip, not to crash on.
    """
    if obj is None or obj.type != "FONT":
        return False
    settings = ruler_settings(obj)
    return bool(settings and settings.point_a and settings.point_b)


def find_ruler_label(obj):
    """The label of the ruler `obj` belongs to, whether `obj` is the label or an arrow."""
    if obj is None:
        return None
    if is_ruler_label(obj):
        return obj
    for candidate in bpy.data.objects:
        if not is_ruler_label(candidate):
            continue
        settings = ruler_settings(candidate)
        if obj in (settings.point_a, settings.point_b):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def _world_origin(obj, depsgraph=None):
    """Where `obj`'s origin actually is, after constraints and parenting."""
    # The depsgraph argument is the one the handler is handed. Reading the
    # evaluated copy is what lets an arrow that has been parented to something
    # moving -- a bone, a rig -- measure from where it is now rather than from
    # its own rest position.
    if depsgraph is not None:
        evaluated = obj.evaluated_get(depsgraph)
        if evaluated is not None:
            obj = evaluated
    return obj.matrix_world.translation.copy()


def measured_distance(settings, depsgraph=None):
    """Distance between a ruler's two points, in Blender units."""
    a = _world_origin(settings.point_a, depsgraph)
    b = _world_origin(settings.point_b, depsgraph)
    return (b - a).length


def format_measurement(settings, distance):
    """The full string a ruler label should be showing: prefix + number + suffix."""
    value = distance * settings.unit_scale
    return f"{settings.prefix}{value:.{settings.decimals}f}{settings.suffix}"


# ---------------------------------------------------------------------------
# Aiming the arrows
# ---------------------------------------------------------------------------


def _aim(obj, direction):
    """Point `obj`'s local +X -- the arrow tip -- along world-space `direction`.

    to_track_quat("X", "Z") is the same maths the Track To constraint runs, so
    the arrows end up oriented exactly as the constrained version would have
    done, just without the dependency on each other.
    """
    if direction.length_squared < _MIN_SPAN_SQUARED:
        return

    if obj.parent is not None:
        # rotation_euler is in parent space, so a parented arrow needs the
        # world direction brought into that space first.
        basis = (obj.parent.matrix_world @ obj.matrix_parent_inverse).to_3x3()
        try:
            basis.invert()
        except ValueError:
            # Parent has a zero-scaled axis; there is no sane local direction.
            return
        direction = basis @ direction
        if direction.length_squared < _MIN_SPAN_SQUARED:
            return

    quaternion = direction.to_track_quat("X", "Z")

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

    current = getattr(obj, attribute)
    if any(abs(now - want) > _ROTATION_EPSILON for now, want in zip(current, target)):
        setattr(obj, attribute, target)


# ---------------------------------------------------------------------------
# The refresh
# ---------------------------------------------------------------------------


def refresh_ruler(label, depsgraph=None):
    """Aim one ruler's arrows and write its text. `label` must be a ruler label."""
    settings = ruler_settings(label)
    point_a = _world_origin(settings.point_a, depsgraph)
    point_b = _world_origin(settings.point_b, depsgraph)

    # Each arrow aims its +X -- which is where the tip is -- away from the other
    # one, so the two heads end up back to back, <--- --->, the way a dimension
    # is drawn. The tip is the origin of the Arrows_For_Rulers shape, so each
    # head lands exactly on its measured point and the shaft trails inward.
    _aim(settings.point_a, point_a - point_b)
    _aim(settings.point_b, point_b - point_a)

    body = format_measurement(settings, (point_b - point_a).length)
    # Only write when the string actually changed. That comparison is not an
    # optimization, it is the loop guard: this runs from depsgraph_update_post,
    # and writing `body` schedules another depsgraph update.
    if label.data.body != body:
        label.data.body = body


def refresh_rulers(depsgraph=None):
    """Re-read every ruler in the file."""
    for obj in bpy.data.objects:
        if is_ruler_label(obj):
            refresh_ruler(obj, depsgraph)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _settings_changed(self, context):
    """Typing in a prefix/suffix field has to repaint the text right away.

    Editing a property does not move anything, so there may be no depsgraph
    update to ride on -- refresh straight from the update callback instead.
    """
    refresh_rulers()


class EMANATE_PG_ruler(bpy.types.PropertyGroup):
    """Everything one ruler needs, hung off its label object."""

    prefix: bpy.props.StringProperty(name="Prefix", description='Text before the measurement, e.g. "R= "', update=_settings_changed)
    suffix: bpy.props.StringProperty(name="Suffix", description='Text after the measurement, e.g. "mm"', update=_settings_changed)
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
            "Multiplies the raw distance before it is displayed. Leave at 1 to read "
            "Blender units; set 10 to read millimetres in a centimetre-scaled scene"
        ),
        default=1.0,
        min=0.0,
        soft_max=1000.0,
        update=_settings_changed,
    )
    point_a: bpy.props.PointerProperty(name="Point A", type=bpy.types.Object)
    point_b: bpy.props.PointerProperty(name="Point B", type=bpy.types.Object)


# ---------------------------------------------------------------------------
# Building a ruler
# ---------------------------------------------------------------------------


def ruler_collection(scene):
    """The RULERS collection, made and linked to the scene if it isn't there.

    children_recursive rather than scene.collection.children: the collection may
    already be nested inside another one, and linking a second time raises.
    """
    collection = bpy.data.collections.get(RULER_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(RULER_COLLECTION)

    if collection not in scene.collection.children_recursive:
        scene.collection.children.link(collection)
    return collection


def _add_arrow(name, location, collection):
    """One arrow of a ruler: its own object, sharing the one arrow curve.

    No constraints, by design -- see the module docstring. These two objects are
    the ruler's handles, and the only things in it the user drags.
    """
    arrow = bpy.data.objects.new(name, widgets.get_widget_curve(ARROW_WIDGET))
    arrow.location = location
    arrow.scale = (ARROW_SIZE, ARROW_SIZE, ARROW_SIZE)
    # A measurement you cannot see behind the model is no measurement.
    arrow.show_in_front = True
    collection.objects.link(arrow)
    return arrow


def _add_label(name, collection, point_a, point_b, prefix, suffix):
    """The text object between the arrows, constrained to the midpoint."""
    text = bpy.data.curves.new(name, type="FONT")
    text.size = TEXT_SIZE
    # CENTER/BOTTOM puts the string centred on the line and sitting just above
    # it, rather than straddling it.
    text.align_x = "CENTER"
    text.align_y = "BOTTOM"

    label = bpy.data.objects.new(name, text)
    label.show_in_front = True
    # The label is not a handle. Making it unselectable means a click-drag
    # anywhere near the middle of the ruler still grabs an arrow.
    label.hide_select = True
    collection.objects.link(label)

    midpoint_a = label.constraints.new("COPY_LOCATION")
    midpoint_a.target = point_a
    midpoint_b = label.constraints.new("COPY_LOCATION")
    midpoint_b.target = point_b
    midpoint_b.influence = 0.5

    align = label.constraints.new("TRACK_TO")
    align.target = point_b
    align.track_axis = "TRACK_X"
    align.up_axis = "UP_Y"

    settings = ruler_settings(label)
    settings.point_a = point_a
    settings.point_b = point_b
    settings.prefix = prefix
    settings.suffix = suffix
    return label


def add_ruler(context, prefix="", suffix=""):
    """Build a ruler at the 3D cursor. Returns (arrow_a, arrow_b, label)."""
    collection = ruler_collection(context.scene)

    origin = Vector(context.scene.cursor.location)
    arrow_a = _add_arrow("RULER_Arrow_A", origin, collection)
    arrow_b = _add_arrow("RULER_Arrow_B", origin + Vector((DEFAULT_SPAN, 0.0, 0.0)), collection)
    label = _add_label("RULER_Label", collection, arrow_a, arrow_b, prefix, suffix)

    # matrix_world on a brand new object is still identity until the depsgraph
    # has run, and the first measurement is read off matrix_world.
    context.view_layer.update()
    refresh_ruler(label)
    return arrow_a, arrow_b, label


# ---------------------------------------------------------------------------
# The handler that keeps a ruler live
# ---------------------------------------------------------------------------

_in_update = False


@bpy.app.handlers.persistent
def _emanate_ruler_text_update(scene, depsgraph=None):
    """Keep every ruler's arrows and text in step with its endpoints.

    persistent so it survives loading a file. The depsgraph argument is absent
    from frame_change_post on older Blender versions, hence the default.

    The re-entrancy guard and the write-only-when-changed tests in refresh_ruler
    are two halves of the same job: this handler writes data, writing data
    schedules another depsgraph update, and that update lands back here.
    """
    global _in_update
    if _in_update:
        return
    _in_update = True
    try:
        refresh_rulers(depsgraph)
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
# Operator and panel
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
        arrow_a, arrow_b, label = add_ruler(
            context,
            prefix=getattr(context.scene, SCENE_PREFIX_PROP),
            suffix=getattr(context.scene, SCENE_SUFFIX_PROP),
        )

        # Hand back one end ready to grab. Deselecting by hand rather than with
        # select_all, which would need a context this operator may not have.
        for obj in context.selected_objects:
            obj.select_set(False)
        arrow_b.select_set(True)
        context.view_layer.objects.active = arrow_b

        self.report({"INFO"}, f"Added {label.name} -- move {arrow_a.name} or {arrow_b.name} to measure")
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

        fields = layout.column(align=True)
        fields.prop(context.scene, SCENE_PREFIX_PROP)
        fields.prop(context.scene, SCENE_SUFFIX_PROP)

        if context.mode != "OBJECT":
            layout.label(text="Object Mode to add a ruler", icon="INFO")
        layout.operator(NAMES_ADD_RULER.operator_idname, icon="DRIVER_DISTANCE")

        # The fields above belong to the next ruler. Once one exists, editing it
        # means editing that ruler -- drawn only while one is selected, so the
        # panel stays two fields and a button the rest of the time.
        label = find_ruler_label(context.active_object)
        if label is None:
            return

        box = layout.box()
        box.label(text=label.name, icon="FONT_DATA")
        settings = ruler_settings(label)
        box.prop(settings, "prefix")
        box.prop(settings, "suffix")
        box.prop(settings, "decimals")
        box.prop(settings, "unit_scale")


# EMANATE_PG_ruler is deliberately left out of check_classes: it only knows the
# _OT_ and _PT_ tags, and reports a _PG_ class as untagged.
_classes = (EMANATE_PG_ruler, EMANATE_OT_add_ruler, EMANATE_PT_tech_tools)


def register():
    naming.check_classes((EMANATE_OT_add_ruler,), NAMES_ADD_RULER)
    naming.check_classes((EMANATE_PT_tech_tools,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)

    # After register_class(EMANATE_PG_ruler), never before -- PointerProperty
    # needs the group registered to point at it.
    setattr(bpy.types.Object, RULER_PROP, bpy.props.PointerProperty(type=EMANATE_PG_ruler))

    setattr(
        bpy.types.Scene,
        SCENE_PREFIX_PROP,
        bpy.props.StringProperty(name="Prefix", description='Text placed before the measurement on the next ruler you add, e.g. "R= "', default=""),
    )
    setattr(
        bpy.types.Scene,
        SCENE_SUFFIX_PROP,
        bpy.props.StringProperty(name="Suffix", description='Text placed after the measurement on the next ruler you add, e.g. "mm"', default=""),
    )

    _install_handlers()


def unregister():
    _remove_handlers()

    delattr(bpy.types.Scene, SCENE_SUFFIX_PROP)
    delattr(bpy.types.Scene, SCENE_PREFIX_PROP)
    delattr(bpy.types.Object, RULER_PROP)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
