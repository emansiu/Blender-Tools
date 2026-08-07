# ---- use this in blender to get the points of a POLY spline, beziers won't work unless you do: (Curve > Set Spline Type > Poly)
# import bpy

# obj = bpy.context.object
# for spline in obj.data.splines:
#     pts = [tuple(round(c, 4) for c in p.co[:3]) for p in spline.points]
#     print(f"({pts}, {spline.use_cyclic_u}),")