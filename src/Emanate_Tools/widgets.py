import bpy

from . import widget_shapes


def get_widget(name):
    """Return the widget object called `name`, building it if it doesn't exist."""
    existing = bpy.data.objects.get(name)
    if existing is not None:
        return existing

    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    for points, cyclic in widget_shapes.SHAPES[name]:
        spline = curve.splines.new("POLY")
        # A new spline arrives with one point already in it.
        spline.points.add(len(points) - 1)
        for point, co in zip(spline.points, points):
            point.co = (*co, 1.0)
        spline.use_cyclic_u = cyclic

    return bpy.data.objects.new(name, curve)

# The bpy.data.objects.get(name) guard is the important part — without it a second run appends WGT_Circle.001, .002, and so on.

# Assigning it:

pose_bone = armature_obj.pose.bones["Foot_IK.L"]
pose_bone.custom_shape = get_widget("WGT_Circle")
pose_bone.use_custom_shape_bone_size = False
pose_bone.bone.show_wire = True