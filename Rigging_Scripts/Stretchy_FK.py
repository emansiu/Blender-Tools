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

def rename_duplicated_bone(bone_to_rename):
    # ----RENAMING ----
    # replace any ORG's with MCH
    if "ORG" in bone_to_rename.name:
        bone_to_rename.name = bone_to_rename.name.replace("ORG","MCH")

    # add "tweak" to the appropriate location (not simply suffix - need to retain integrigy of .L or )
    if ".L" in bone_to_rename.name:
        index = bone_to_rename.name.find(".L")
        changed_bone_name = bone_to_rename.name[:index] + "_tweak" + bone_to_rename.name[index:]
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)
    else:
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,bone_to_rename.name+"_tweak.L")

    if ".001" in bone_to_rename.name:
        index = bone_to_rename.name.find(".001")
        changed_bone_name = bone_to_rename.name[:index]
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)

# =================================== CLASS TO CREATE STRETCHY FK RIG ================================
class VIEW3D_OT_StretchFK(bpy.types.Operator):
    """ Creates the stretchy FK system"""
    bl_idname = "object.stretchyfk"
    bl_label = "Stretchy FK Operator"




    def execute(self, context):
        print("============== NEW EXECUTION =================")
        armature = bpy.context.object
        bones_down_the_chain = context.active_bone.children_recursive

        first_bone = context.active_bone
        first_bone.use_connect = False
        original_bones = [context.active_bone.name]


        for bone in bones_down_the_chain:
            bone.use_connect = False
            bpy.ops.armature.select_hierarchy(extend=True, direction="CHILD")
            original_bones.append(bone.name)
            # --- if bones are connected, we disconnect them here, but keep them parented
            

        # with all bones selected, duplicate and resize 
        # [!NOTICE!] --- when this operation is done it will select all the duplicated bones
        bpy.ops.armature.duplicate()
        bpy.ops.transform.resize(value= ( 0.5, 0.5, 0.5))

        duplicated_bones = bpy.context.selected_bones
        # Renaming duplicated bones, then parent originals to these new bones.
        for index, bone in enumerate(duplicated_bones):
            bone.use_connect = False
            print(f"index: '{index}' gives us bone: '{bone.name}'")

            rename_duplicated_bone(bone)
            # --- ASSIGNING NEW PARENTS ----
            print('-----  ORIGINAL BONES ------')
            print(original_bones[index])
            print('----- CURRENT DUPLICATED BONE ------')
            print(bone.name)
            armature.data.edit_bones[original_bones[index]].parent = armature.data.edit_bones[bone.name]


            

        
        return{'FINISHED'}



#================================ PANEL TO ACCESS RIG BUTTONS ==========================================
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
            column.operator("object.stretchyfk", 
            text="Make Stretchy FK Rig"
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