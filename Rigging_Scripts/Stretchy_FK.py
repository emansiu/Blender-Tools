bl_info = {
    "name": "Stretchy IK",
    "author": "E Siu",
    "blender": (4,2,0),
    "location": "",
    "description": "Creates stretchy fk chain from selected root bone",
    "warning": "",
    "doc_url": "",
    "category": "Rig",
}

import bpy


#=============== CLASS TO CREATE STRETCHY FK RIG =============
class VIEW3D_OT_StretchFK(bpy.types.Armature):

    def draw(self, context):
        pass


#=============== PANEL TO ACCESS RIG BUTTONS =============
class VIEW3D_PT_CustomRigs(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_label = "Simple Custom Menu"
    # bl_idname = "OBJECT_MT_simple_custom_menu"
    bl_category = "Custom Rigs"
    

    

    def draw(self, context):
        def check_edit_mode():
    # """Checks if the active object is in Edit Mode and prints the status."""

            obj = bpy.context.active_object
            if obj is None:
                print("No object selected.")
                return False

            if obj.mode == 'EDIT':
                print(f"Object '{obj.name}' is in Edit Mode.")
                return True
            else:
                print(f"Object '{obj.name}' is in: {obj.mode} mode.")
                return False
        # self.layout.operator(context.active_object,
        #                               text="Stretchy FK",
        #                               icon='GROUP_BONE'
        #                               )

        column = self.layout.column()
        if context.active_object is None:
            column.label(text='-no active object-')
        else:
            column.prop(context.active_object, "hide_viewport")

        if check_edit_mode():
            column.prop(context.active_object, "hide_viewport")
        else:
            column.label(text='-not in edit mode-')

        # layout.operator("wm.open_mainfile")
        # layout.operator("wm.save_as_mainfile")


def register():
    bpy.utils.register_class(VIEW3D_PT_CustomRigs)


def unregister():
    bpy.utils.unregister_class(VIEW3D_PT_CustomRigs)
