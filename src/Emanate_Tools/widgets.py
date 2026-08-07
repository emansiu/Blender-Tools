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


def assign_widget(pose_bone, name, scale=1.0):
    """Give `pose_bone` the widget called `name`. Returns the widget object."""
    widget = get_widget(name)
    pose_bone.custom_shape = widget
    pose_bone.custom_shape_scale_xyz = (scale, scale, scale)
    pose_bone.bone.show_wire = True
    return widget
