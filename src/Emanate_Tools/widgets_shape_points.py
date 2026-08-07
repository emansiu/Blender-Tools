# Point data for bone widgets, keyed by widget name. Each value is a list of
# (points, cyclic) pairs -- one pair per spline, since a widget like the cube
# below takes several strokes to draw.
#
# ---------------------------------------------------------------------------
# Author-time exporter. Select the widget curves in Blender, run this in the
# scripting workspace, and paste the output into SHAPES below. Beziers won't
# work -- convert them first with Curve > Set Spline Type > Poly.
#
# import bpy
#
# for obj in bpy.context.selected_objects:
#     print(f'    "{obj.name}": [')
#     for spline in obj.data.splines:
#         pts = [tuple(round(c, 4) for c in p.co[:3]) for p in spline.points]
#         print(f"        ({pts}, {spline.use_cyclic_u}),")
#     print("    ],")
# ---------------------------------------------------------------------------

SHAPES = {
    "WGT_Cube": [
        ([(1.0, -1.0, -1.0), (-1.0, -1.0, -1.0), (-1.0, 1.0, -1.0), (-1.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, -1.0), (1.0, -1.0, -1.0), (1.0, -1.0, 1.0), (-1.0, -1.0, 1.0), (-1.0, 1.0, 1.0)], False),
        ([(1.0, 1.0, 1.0), (1.0, -1.0, 1.0)], False),
        ([(1.0, 1.0, -1.0), (-1.0, 1.0, -1.0)], False),
        ([(-1.0, -1.0, -1.0), (-1.0, -1.0, 1.0)], False),
    ],
}
