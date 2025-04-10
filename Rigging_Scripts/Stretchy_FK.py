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
def get_current_mode():
    return bpy.context.object.mode

def swith_to_mode(mode_to_switch_to:str):
    """takes OBJECT, EDIT, OR POSE values"""
    bpy.ops.object.mode_set(mode=mode_to_switch_to)

def DESELECT_ALL():
    match get_current_mode():
        case 'EDIT':
            bpy.ops.armature.select_all(action='DESELECT')
        case 'OBJECT':
            bpy.ops.object.select_all(action="DESELECT")
        case 'POSE':
            bpy.ops.pose.select_all(action="DESELECT")
        case _:
            print('we are in some other mode not covered in this script')

def select_bone(bone):
    bone.select = True
    bone.select_head = True
    bone.select_tail = True

def select_mesh_by_name(mesh_name):
    bpy.data.objects[mesh_name].select_set(True)

def assign_to_icon_collection(mesh_obj):
    icon_collection = bpy.data.collections.get("Armature_Icons")
    if icon_collection is None:
        return
    # remove from old collection, link (or assign) to icon collections
    mesh_obj.users_collection[0].objects.unlink(mesh_obj)
    # mesh_obj.hide_viewport = True
    icon_collection.objects.link(mesh_obj)

def rename_org_to_tweak(bone_to_rename):
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

def rename_tweak_tip(bone_to_rename):
    # ----RENAMING ----
    # replace any ORG's with MCH
    if "ORG" in bone_to_rename.name:
        bone_to_rename.name = bone_to_rename.name.replace("ORG","MCH")

    # add "tweak" to the appropriate location (not simply suffix - need to retain integrigy of .L or )
    if ".L" in bone_to_rename.name:
        index = bone_to_rename.name.find(".L")
        changed_bone_name = bone_to_rename.name[:index] + "_tweak_tip"
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)
    else:
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,bone_to_rename.name+"_tweak_tip")

    if ".001" in bone_to_rename.name:
        index = bone_to_rename.name.find(".001")
        changed_bone_name = bone_to_rename.name[:index]
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)

def rename_org_to_fk(bone_to_rename):
    # ----RENAMING ----
    # replace any ORG's with FK
    if "ORG" in bone_to_rename.name:
        bone_to_rename.name = bone_to_rename.name.replace("ORG","FK")

    if ".001" in bone_to_rename.name:
        index = bone_to_rename.name.find(".001")
        changed_bone_name = bone_to_rename.name[:index]
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)

# =================================== CLASS TO CREATE STRETCHY FK RIG ================================
class VIEW3D_OT_StretchFK(bpy.types.Operator):
    """ Creates the stretchy FK system"""
    bl_idname = "object.stretchyfk"
    bl_label = "Stretchy FK Operator"

    def create_collection(self):
        collection_name = "Armature_Icons"

        if collection_name in bpy.data.collections:
            print("this collection already exists")
        else:
            print("let's make this bad boy!!!")
            new_collection = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(new_collection)

    def create_icons(self):

        # -- creating fk circle icon and assigning to icon collection
        bpy.ops.curve.primitive_bezier_circle_add(radius=0.5)
        bpy.context.active_object.name = "fk_circle_icon"
        # assign to new collection remove from old
        assign_to_icon_collection(bpy.context.active_object)

        # -- creating tweak icosphere icon and assigning to icon collection
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=0.5, enter_editmode=True)
        bpy.context.active_object.name = "tweak_icosphere_icon"
        bpy.ops.mesh.delete(type='ONLY_FACE')
        assign_to_icon_collection(bpy.context.active_object)

        bpy.ops.object.mode_set(mode='OBJECT')


    def execute(self, context):





        print("============== NEW STRETCHY EXECUTION =================")
        armature = bpy.context.object
        bones_down_the_chain = context.active_bone.children_recursive

        first_bone = context.active_bone
        first_bone.use_connect = False
        original_bones = [context.active_bone.name]

        # --- CREATE ONE BONE AT END; notice this is done AFTER variable "bones_down_the_chain" so as to not include it in loops concerning that chain.
        DESELECT_ALL()
        bones_down_the_chain[len(bones_down_the_chain)-1].select_tail = True
        bpy.ops.armature.extrude_move(TRANSFORM_OT_translate={"value":(0.0,0.2,0.0)})
        bpy.ops.armature.align()

        tip_tweak_bone = bpy.context.active_bone
        tip_tweak_bone.use_connect = False
        tip_tweak_bone.color.palette = "THEME09"
        rename_tweak_tip(tip_tweak_bone)


    
        DESELECT_ALL()
        # -- select original chain and disconnect if connected to duplicate
        select_bone(first_bone)
        for bone in bones_down_the_chain:
            original_bones.append(bone.name)
            bone.use_connect = False
            select_bone(bone)

      
        # [!NOTICE!] --- when this operation is done it will select all the duplicated bones
        # --- create fk bones
        bpy.ops.armature.duplicate()
        fk_bones = bpy.context.selected_bones
        bpy.ops.transform.resize(value= ( 0.75, 0.75, 0.75))
        for bone in fk_bones:
            rename_org_to_fk(bone)


        #---- again, with all bones selected, duplicate and resize, asign to new variable
        bpy.ops.armature.duplicate()
        tweak_bones = bpy.context.selected_bones
        bpy.ops.transform.resize(value= ( 0.75, 0.75, 0.75))

        # ---- Renaming duplicated bones, then parent originals to these new bones. ----
        for index, bone in enumerate(tweak_bones):
            bone.use_connect = False
            bone.color.palette = "THEME09"

            rename_org_to_tweak(bone)
            # --- PARENT ORIGINAL BONES TO NEW DUPLICATED (TWEAK) BONES ----
            armature.data.edit_bones[original_bones[index]].parent = armature.data.edit_bones[bone.name]

            # --- PARENT NEW TWEAK BONES TO FK CONTROLLER BONES ----
            armature.data.edit_bones[bone.name].parent = armature.data.edit_bones[fk_bones[index].name]

        # --- PARENT LONELY TIP TWEAK TO LAST FK CONTROLLER ----
            armature.data.edit_bones[tip_tweak_bone.name].parent = armature.data.edit_bones[fk_bones[-1].name]


        DESELECT_ALL()
        # --- Assign constraints in pose bone mode --------
        bpy.ops.object.mode_set(mode="POSE")
        final_original_bone = len(original_bones)-1
        for index, bone in enumerate(original_bones):

            bone_constraint_owner = bpy.context.object.pose.bones.get(bone)
            if index != final_original_bone:
                bone_constraint_target = context.object.pose.bones.get(tweak_bones[index+1].name)
            else:
                bone_constraint_target = context.object.pose.bones.get(tip_tweak_bone.name)

            print(f"constraining target: '{bone_constraint_target.name}' to owner: '{bone_constraint_owner.name}'")

            constraint = bone_constraint_owner.constraints.new("STRETCH_TO")
            constraint.target = armature
            constraint.subtarget = bone_constraint_target.name

        #---- create icons and move to collection---
        self.create_collection()
        self.create_icons()

        DESELECT_ALL()
                
        
        
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

