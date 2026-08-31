import math

import bpy

from . import widgets_shape_points as shape_points


def get_widget(name):
    """Return the widget object called `name`, building it if it doesn't exist."""
    # Without this guard a second run appends WGT_Cube.001, .002, and so on.
    existing = bpy.data.objects.get(name)
    if existing is not None:
        return existing

    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    for points, cyclic in shape_points.SHAPES[name]:
        spline = curve.splines.new("POLY")
        # A new spline arrives with one point already in it.
        spline.points.add(len(points) - 1)
        for point, co in zip(spline.points, points):
            point.co = (*co, 1.0)
        spline.use_cyclic_u = cyclic

    # Deliberately not linked to a collection: custom_shape counts as a user, so
    # the object survives save/reload while staying out of the outliner.
    return bpy.data.objects.new(name, curve)


def hex_to_rgb(value):
    """(r, g, b) floats in 0..1 from a "#RRGGBB" string.

    Blender's bone color slots are COLOR_GAMMA properties, so the sRGB values
    straight off a hex picker go in as they are -- converting to linear here
    would land a visibly darker colour than the one that was asked for.
    """
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def set_bone_color(bone, color):
    """Colour `bone` from a theme palette name ("THEME07") or a hex string ("#F7FF87").

    A hex value goes into the CUSTOM palette, which carries three slots --
    normal, select and active. All three get the same colour: filling in only
    `normal` leaves the other two at black, so the bone would flip to black the
    moment anything selected it. Bones that are meant to read as one flat
    colour regardless of state are the whole reason this takes a hex at all.
    """
    if not color.startswith("#"):
        bone.color.palette = color
        return

    bone.color.palette = "CUSTOM"
    rgb = hex_to_rgb(color)
    bone.color.custom.normal = rgb
    bone.color.custom.select = rgb
    bone.color.custom.active = rgb


def assign_widget(
    pose_bone,
    name,
    scale_x=1.0,
    scale_y=1.0,
    scale_z=1.0,
    rotation_x=0.0,
    rotation_y=0.0,
    rotation_z=0.0,
    color=None,
    wire_width=None,
    use_bone_size=True,
):
    """Give `pose_bone` the widget called `name`. Returns the widget object.

    Each axis is its own argument, so overriding one means naming one: pass
    scale_y=0.5 to flatten a cube, or scale_y=-1 to flip a pyramid, and leave
    the other two at their default.

    The rotation_* arguments are in DEGREES. Blender stores the underlying
    property in radians, so this converts -- assigning a bare 90 to
    custom_shape_rotation_euler means 90 *radians*, which is the mistake these
    arguments exist to make hard.

    color is either a theme palette name such as "THEME07" or a hex string such
    as "#F7FF87" -- see set_bone_color; wire_width is in pixels. Both stay at
    Blender's default when left as None.

    use_bone_size=True multiplies the shape by the bone's length, so one widget
    draws small on a short bone and large on a long one. Pass False for a set of
    bones that should all read at the same size regardless of their individual
    lengths -- the tweaks -- and the scale_* values become an absolute size in
    armature units instead of a multiplier. Either way the widget still rides
    the rig's transform chain, so scaling the character scales the widget; only
    the bone-length term drops out.
    """
    widget = get_widget(name)
    pose_bone.custom_shape = widget
    pose_bone.custom_shape_scale_xyz = (scale_x, scale_y, scale_z)
    pose_bone.custom_shape_rotation_euler = (
        math.radians(rotation_x),
        math.radians(rotation_y),
        math.radians(rotation_z),
    )
    pose_bone.use_custom_shape_bone_size = use_bone_size

    if wire_width is not None:
        pose_bone.custom_shape_wire_width = wire_width

    if color is not None:
        set_bone_color(pose_bone.bone, color)

    pose_bone.bone.show_wire = True
    return widget
