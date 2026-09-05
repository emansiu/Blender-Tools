bl_info = {
    "name": "Stretchy FK",
    "author": "E Siu",
    "blender": (4,2,0),
    "location": "",
    "description": "Creates stretchy fk chain from selected root bone",
    "warning": "",
    "doc_url": "",
    "category": "Rig",
}

import bpy

from ..helpers import deform_cleanup
from ..helpers import widgets
from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "stretchy_fk",
    label="Stretchy FK",
    owner=__name__,
    description="Creates a stretchy FK chain from the selected root bone",
    order=30,
)

# ------ Global Variables --------------------------------------------------------------------------
# # --- get proper scaling for icons ----
# scene_scale_unit = bpy.context.scene.unit_settings.scale_length
# scene_unit_length = bpy.context.scene.unit_settings.length_unit
# scene_unit_length_quantified:float | None = None

# match scene_unit_length:
#     case "METERS":
#         scene_unit_length_quantified = 1.0
#     case "CENTIMETERS":
#         scene_unit_length_quantified = 0.01
#     case "MILLIMETERS":
#         scene_unit_length_quantified = 0.001
#     case "KILOMETERS":
#         scene_unit_length_quantified = 1000.0
#     case "INCHES":
#         scene_unit_length_quantified = 39.3701
#     case _:
#         print("scene unit is not one we have accounted for in code for this tool")
# --------------------------------------------------------------------------------------------------

def get_current_mode():
    return bpy.context.object.mode

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
class EMANATE_OT_stretchy_fk(bpy.types.Operator):
    """ Creates the stretchy FK system"""
    bl_idname = NAMES.operator_idname
    bl_label = NAMES.label
    bl_description = NAMES.description
    bl_options = {'REGISTER', 'UNDO'}


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
        # --- re-select the ORIGINAL chain: the previous duplicate() call left the
        # new fk_bones selected, so without this the second duplicate would copy
        # the fk_bones instead of the original chain, producing mis-named,
        # mis-positioned tweak bones.
        DESELECT_ALL()
        for name in original_bones:
            select_bone(armature.data.edit_bones[name])
        bpy.ops.armature.duplicate()
        tweak_bones = bpy.context.selected_bones
        bpy.ops.transform.resize(value= ( 0.75, 0.75, 0.75))

        # ---- Renaming duplicated bones, then parent originals to these new bones. ----
        for index, bone in enumerate(tweak_bones):
            bone.use_connect = False

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

        # --- assign widget shapes to specific components of rig ------
        # get_widget()/assign_widget() build their curve objects directly via the
        # data API rather than bpy.ops, so -- unlike the old icon-mesh creation --
        # they never touch active/selected object, and no mode round-trip is
        # needed to get back to the armature in pose mode.
        tweaker_shape_size = 3.0
        fk_shape_size = 8.0
        pose_bones = context.object.pose.bones
        for index, bone in enumerate(original_bones):

            widgets.assign_widget(
                pose_bones[tweak_bones[index].name], "WGT_Centered_IcoSphere",
                scale_x=tweaker_shape_size, scale_y=tweaker_shape_size, scale_z=tweaker_shape_size,
                use_bone_size=False, color="THEME09",
            )

            widgets.assign_widget(
                pose_bones[fk_bones[index].name], "WGT_Circle_Centered",
                scale_x=fk_shape_size, scale_y=fk_shape_size, scale_z=fk_shape_size,
                use_bone_size=False,
            )

        # give widget to final tweak bone
        widgets.assign_widget(
            pose_bones[tip_tweak_bone.name], "WGT_Centered_IcoSphere",
            scale_x=tweaker_shape_size, scale_y=tweaker_shape_size, scale_z=tweaker_shape_size,
            use_bone_size=False, color="THEME09",
        )

        deform_cleanup.sync_deform_flags(armature)

        return{'FINISHED'}



#================================ PANEL TO ACCESS RIG BUTTONS ==========================================
class EMANATE_PT_stretchy_fk(bpy.types.Panel):

    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = NAMES.order



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
            column.operator(NAMES.operator_idname,
            text="Make Stretchy FK Rig"
        )
        else:
            column.label(text='- select bone chain in edit mode -')



_classes = (EMANATE_OT_stretchy_fk, EMANATE_PT_stretchy_fk)


def register():
    naming.check_classes(_classes, NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

