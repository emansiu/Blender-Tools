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

# ------ Global Variables --------------------------------------------------------------------------
name_of_collection_for_icons = "Icons"
# --- get proper scaling for icons ----
scene_scale_unit = bpy.context.scene.unit_settings.scale_length
scene_unit_length = bpy.context.scene.unit_settings.length_unit
scene_unit_length_quantified:float | None = None

match scene_unit_length:
    case "METERS":
        scene_unit_length_quantified = 1.0
    case "CENTIMETERS":
        scene_unit_length_quantified = 0.01
    case "MILLIMETERS":
        scene_unit_length_quantified = 0.001
    case "KILOMETERS":
        scene_unit_length_quantified = 1000.0
    case "INCHES":
        scene_unit_length_quantified = 39.3701
    case _:
        print("scene unit is not one we have accounted for in code for this tool")
# --------------------------------------------------------------------------------------------------

def get_current_mode():
    return bpy.context.object.mode

def swith_to_mode(mode_to_switch_to):
    """takes OBJECT, EDIT, OR POSE values"""
    bpy.ops.object.mode_set(mode=mode_to_switch_to)

def DESELECT_ALL():
    """ Deselects ALL. WARNING!: when deselecting all in object mode you lose context of pose and cannot switch to pose mode until you select an armature"""
    match get_current_mode():
        case 'EDIT':
            if bpy.context.active_object.type == "ARMATURE":
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
    icon_collection = bpy.data.collections.get(name_of_collection_for_icons)
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
        changed_bone_name = bone_to_rename.name[:index] + "_tweak.L"
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)
    else:
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,bone_to_rename.name+"_tweak.L")

    if ".001" in bone_to_rename.name:
        index = bone_to_rename.name.find(".001")
        changed_bone_name = bone_to_rename.name[:index]
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)

def rename_tweak_tip(bone_to_rename):
    print('========================RENAMING TIP FUNCTION GETTING CALLED ===================')
    # ----RENAMING ----
    # replace any ORG's with MCH
    if "ORG" in bone_to_rename.name:
        bone_to_rename.name = bone_to_rename.name.replace("ORG","MCH")

    # add "tweak" to the appropriate location (not simply suffix - need to retain integrigy of .L or )
    if ".L" in bone_to_rename.name:
        print('========================FOUND .L REPLACING IT THE TIP CORRECTLY HOPEFULLY ===================')
        index = bone_to_rename.name.find(".L")
        changed_bone_name = bone_to_rename.name[:index] + "_tweak_tip.L"
        print(changed_bone_name)
        bone_to_rename.name = bone_to_rename.name.replace(bone_to_rename.name,changed_bone_name)
    else:
        print('========================DID NOT FIND .L, RENAMING TO TWEAK_TIP ===================')
        # if no .L, then it will be ending in .001
        index = bone_to_rename.name.find(".001")
        changed_bone_name = bone_to_rename.name[:index] + "_tweak_tip"
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
        collection_name = name_of_collection_for_icons

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

        return ["fk_circle_icon","tweak_icosphere_icon"]


    def execute(self, context):

        print("============== NEW STRETCHY EXECUTION =================")
        # --- for everything to work, pivot point transformations need to be set to "individual origins". We do that now.
        bpy.context.scene.tool_settings.transform_pivot_point = "INDIVIDUAL_ORIGINS"

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


            constraint = bone_constraint_owner.constraints.new("STRETCH_TO")
            constraint.target = armature
            constraint.subtarget = bone_constraint_target.name

        #---- create icons and move to collection---
        self.create_collection()
        icon_names = self.create_icons()

        DESELECT_ALL()
        swith_to_mode("OBJECT")
        DESELECT_ALL()
        # select and activate armature
        armature.select_set(True)
        context.view_layer.objects.active = armature
        swith_to_mode("POSE")

        
        


        # --- assign icon shapes to specific components of rig ------
        tweaker_shape_size = 3.0
        fk_shape_size = 8.0
        for index, bone in enumerate(original_bones):
            
            context.object.pose.bones[tweak_bones[index].name].custom_shape = bpy.data.objects.get("tweak_icosphere_icon")
            context.object.pose.bones[tweak_bones[index].name].use_custom_shape_bone_size = False
            context.object.pose.bones[tweak_bones[index].name].custom_shape_scale_xyz = (
                (tweaker_shape_size/scene_scale_unit)*scene_unit_length_quantified,
                (tweaker_shape_size/scene_scale_unit)*scene_unit_length_quantified,
                (tweaker_shape_size/scene_scale_unit)*scene_unit_length_quantified
            )


            context.object.pose.bones[fk_bones[index].name].custom_shape = bpy.data.objects.get("fk_circle_icon")
            # below is rotating 90 in x rotation but in radians
            context.object.pose.bones[fk_bones[index].name].custom_shape_rotation_euler[0] = 1.5707964
            context.object.pose.bones[fk_bones[index].name].use_custom_shape_bone_size = False
            context.object.pose.bones[fk_bones[index].name].custom_shape_scale_xyz = (
                (fk_shape_size/scene_scale_unit)*scene_unit_length_quantified,
                (fk_shape_size/scene_scale_unit)*scene_unit_length_quantified,
                (fk_shape_size/scene_scale_unit)*scene_unit_length_quantified
            )

        # give icon to final tweak bone
        context.object.pose.bones[tip_tweak_bone.name].custom_shape = bpy.data.objects.get("tweak_icosphere_icon")
        context.object.pose.bones[tip_tweak_bone.name].use_custom_shape_bone_size = False
        context.object.pose.bones[tip_tweak_bone.name].custom_shape_scale_xyz = (
            (tweaker_shape_size/scene_scale_unit)*scene_unit_length_quantified,
            (tweaker_shape_size/scene_scale_unit)*scene_unit_length_quantified,
            (tweaker_shape_size/scene_scale_unit)*scene_unit_length_quantified
        )

                
        # finally, hide shape icons
        DESELECT_ALL()
        swith_to_mode("OBJECT")
        for icon in icon_names:
            icon_object = bpy.data.objects.get(icon)
            icon_object.select_set(True)
            context.view_layer.objects.active = icon_object
            icon_object.hide_set(True)
        
        # End in pose mode
        DESELECT_ALL()
        # select and activate armature
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        swith_to_mode("POSE")
        
        return{'FINISHED'}



#================================ PANEL TO ACCESS RIG BUTTONS ==========================================
class VIEW3D_PT_CustomRigs(bpy.types.Panel):

    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_label = "Custom Rigging Tools"
    # bl_idname = "OBJECT_MT_simple_custom_menu"
    bl_category = "Custom Rigs"
    


    def draw(self, context):

        selected_object = context.active_object
        selected_bone = context.active_bone

        def check_edit_mode_and_armature():
            """checking what is selected, and if a bone, is it a single bone or a chain. Lastly checks if we're in edit mode"""
            

            if selected_object is None:
                print("no object selected")
                return False
            if selected_bone is None:
                print("no bone selected")
                return False

            if selected_object.mode == 'EDIT' and selected_object.type == 'ARMATURE':
                if len(selected_bone.children_recursive) > 0:
                    return True
                else:
                    print("there is only 1 bone in this chain")
                    return False
            
            else:
                print("Check edit mode function for menu has something unexpected")
                return False


        #Create columns for menu 
        column = self.layout.column()
        if check_edit_mode_and_armature():
            column.operator("object.stretchyfk", 
            text="Make Stretchy FK Rig"
        )
        else:
            column.label(text='- select bone chain in edit mode -')



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

