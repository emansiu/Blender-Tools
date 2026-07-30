import bpy


class EMANATE_STUDIOS_PT_panel(bpy.types.Panel):
    bl_label = "Emanate Tools"
    bl_idname = "EMANATE_STUDIOS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Emanate"

    def draw(self, context):
        self.layout.label(text="Scaffold is working.")


def register():
    bpy.utils.register_class(EMANATE_STUDIOS_PT_panel)


def unregister():
    bpy.utils.unregister_class(EMANATE_STUDIOS_PT_panel)