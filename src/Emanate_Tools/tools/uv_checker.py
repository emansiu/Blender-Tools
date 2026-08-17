import bpy

from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "uv_checker",
    label="UV Checker",
    owner=__name__,
    description="Report which UDIM tiles the selection uses",
)


class EMANATE_OT_uv_checker(bpy.types.Operator):

    bl_idname = NAMES.operator_idname
    bl_label = NAMES.label
    bl_description = NAMES.description
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'INFO'}, "Ran UV checker")
        return {'FINISHED'}


class EMANATE_PT_uv_checker(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = NAMES.order

    def draw(self, context):
        self.layout.operator(NAMES.operator_idname)


_classes = (EMANATE_OT_uv_checker, EMANATE_PT_uv_checker)


def register():
    naming.check_classes(_classes, NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)