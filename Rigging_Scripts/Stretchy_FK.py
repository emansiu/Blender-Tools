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
import mathutils
import struct

# =============== CLASS TO CREATE STRETCHY FK RIG =============
class VIEW3D_OT_StretchFK(bpy.types.Operator):
    """ Creates the stretchy FK system"""
    bl_idname = "object.select_operator"
    bl_label = "Stretchy FK Operator"



    def execute(self, context):
        print("------------- NEW ATTEMPT ------------------")


        armature = bpy.context.object
        bones_down_the_chain = context.active_bone.children_recursive


        print(f"the number of bones in this chain are: '{len(bones_down_the_chain)}'")

        for bone in bones_down_the_chain:
            bpy.ops.armature.select_hierarchy(extend=True, direction="CHILD")
            # if bones are connected, we disconnect them here, but keep them parented
            bone.use_connect = False

            
        bpy.ops.armature.duplicate()
        bpy.ops.transform.resize(value= ( 0.5, 0.5, 0.5))

        
        return{'FINISHED'}


#=============== PANEL TO ACCESS RIG BUTTONS =============
class VIEW3D_PT_CustomRigs(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_label = "Simple Custom Menu"
    # bl_idname = "OBJECT_MT_simple_custom_menu"
    bl_category = "Custom Rigs"
    


    def draw(self, context):

        selectedObject = bpy.context.active_object

        def check_edit_mode_and_armature():
        # checking if active object is in edit mode

            if selectedObject is None:
                return ("no object selected" , False )

            if selectedObject.mode == 'EDIT' and selectedObject.type == 'ARMATURE':
                # print(f"Object '{selectedObject.name}' is in {selectedObject.mode} of type '{selectedObject.type}'.")
                return True
            if len(bpy.context.active_bone.children_recursive) > 0:
                return
            else:
                return (f"Object '{selectedObject.name}' is in {selectedObject.mode} of type '{selectedObject.type}'.", 
                        False
                        )


        #Create columns for menu 
        column = self.layout.column()
        if check_edit_mode_and_armature():
            column.operator("object.select_operator", 
            text="select hierarchy"
        )
        else:
            column.label(text='-not in edit mode-')



def register():
    bpy.utils.register_class(VIEW3D_PT_CustomRigs),
    bpy.utils.register_class(VIEW3D_OT_StretchFK)


def unregister():
    bpy.utils.unregister_class(VIEW3D_PT_CustomRigs),
    bpy.utils.unregister_class(VIEW3D_OT_StretchFK)

if __name__ == "__main__":
    register()
    # You can run your operator or interact with the panel here...
    unregister()