import math

import bpy
from mathutils import Vector

from ..helpers import deform_cleanup
from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "pre_rig_initialize",
    label="Pre-Rig Tools",
    owner=__name__,
    description="checks settings for armature objects and scene settings to make sure we are working in an environment ready for rigs that can be exported to Unreal Engine",
    order=10,
)

NAMES_DEF_SKELETON = naming.register_tool(
    "create_deformation_skeleton",
    label="Make DEF[ormation] Skeleton",
    owner=__name__,
    description="Builds the deformation skeleton -- root, spine and left arm chain -- then mirrors the left side onto the right",
)

# ------ Scene settings a rig destined for Unreal Engine expects -------------
TARGET_UNIT_SYSTEM = "METRIC"
TARGET_SCALE_LENGTH = 0.01
TARGET_LENGTH_UNIT = "CENTIMETERS"
TARGET_GRID_SCALE = 0.01
TARGET_RENDER_ENGINE = "CYCLES"
TARGET_CYCLES_DEVICE = "GPU"
TARGET_PIVOT_POINT = "INDIVIDUAL_ORIGINS"

# scale_length is stored as a 32-bit float, so it never compares equal to the
# Python literal 0.01 even immediately after being set. Compare with slack.
_SCALE_TOLERANCE = 1e-6
# ---------------------------------------------------------------------------

# ------ Not yet implemented -- reserved for the Unreal unit-match checkbox --
MATCH_UNREAL_UNITS_PROP = naming.prop_name("match_unreal_units")


def match_unreal_units_update(self, context):
    pass


# ---------------------------------------------------------------------------


def fix_scene_units(scene):
    """Force the scene onto centimetres. Returns a list of what it changed."""
    units = scene.unit_settings
    changed = []

    # CENTIMETERS is only a valid length_unit while the system is metric, so
    # this has to happen first or the assignment further down raises TypeError.
    if units.system != TARGET_UNIT_SYSTEM:
        changed.append(f"unit system {units.system} -> {TARGET_UNIT_SYSTEM}")
        units.system = TARGET_UNIT_SYSTEM

    if abs(units.scale_length - TARGET_SCALE_LENGTH) > _SCALE_TOLERANCE:
        changed.append(f"unit scale {units.scale_length:g} -> {TARGET_SCALE_LENGTH}")
        units.scale_length = TARGET_SCALE_LENGTH

    if units.length_unit != TARGET_LENGTH_UNIT:
        changed.append(f"length unit {units.length_unit} -> {TARGET_LENGTH_UNIT}")
        units.length_unit = TARGET_LENGTH_UNIT

    return changed


def fix_pivot_point(scene):
    """Set the transform pivot to individual origins.

    The stretchy FK tool depends on this being set before it runs, so getting
    it right up front is the whole point of initializing.
    """
    changed = []
    tool_settings = scene.tool_settings

    if tool_settings.transform_pivot_point != TARGET_PIVOT_POINT:
        changed.append(
            f"pivot point {tool_settings.transform_pivot_point} -> {TARGET_PIVOT_POINT}"
        )
        tool_settings.transform_pivot_point = TARGET_PIVOT_POINT

    return changed


def fix_viewport_overlays():
    """Match the overlay grid scale to the unit scale, in every 3D viewport.

    grid_scale lives on the View3D *space*, not on the scene, so there is one
    per viewport. Walking bpy.data.screens covers every workspace, not just
    the one the button happened to be clicked in.
    """
    changed = []
    fixed_viewports = 0
    old_scale = None

    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                # An area keeps spaces from every type it has previously been,
                if abs(space.overlay.grid_scale - TARGET_GRID_SCALE) > _SCALE_TOLERANCE:
                    if old_scale is None:
                        old_scale = space.overlay.grid_scale
                    space.overlay.grid_scale = TARGET_GRID_SCALE
                    fixed_viewports += 1

    if fixed_viewports:
        changed.append(
            f"overlay grid scale {old_scale:g} -> {TARGET_GRID_SCALE} "
            f"({fixed_viewports} viewport{'s' if fixed_viewports > 1 else ''})"
        )

    return changed


def fix_render_settings(scene):
    """Put the scene on Cycles + GPU Compute. Returns a list of what changed."""
    changed = []

    if scene.render.engine != TARGET_RENDER_ENGINE:
        changed.append(f"render engine {scene.render.engine} -> {TARGET_RENDER_ENGINE}")
        scene.render.engine = TARGET_RENDER_ENGINE

    # scene.cycles only exists while the Cycles add-on is enabled. It ships
    # enabled by default, but a user can turn it off, and the attribute goes
    # with it -- so ask before reaching for the device.
    cycles = getattr(scene, "cycles", None)
    if cycles is None:
        return changed

    if cycles.device != TARGET_CYCLES_DEVICE:
        changed.append(f"cycles device {cycles.device} -> {TARGET_CYCLES_DEVICE}")
        cycles.device = TARGET_CYCLES_DEVICE

    return changed


def gpu_backend_is_configured():
    """True if Preferences has a compute backend picked (CUDA/OPTIX/HIP/...).

    Setting cycles.device = 'GPU' always succeeds, but Cycles silently falls
    back to the CPU when no backend is selected in Preferences > System.
    """
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is None:
        return False
    return getattr(addon.preferences, "compute_device_type", "NONE") != "NONE"


def create_deformation_skeleton(context):
    """Make a deformation skeleton. Returns a list of what changed."""
    """Create the base armature with a single Root bone, pointing -X... """
    armature_data = bpy.data.armatures.new("Armature")
    armature_obj = bpy.data.objects.new("Armature", armature_data)
    armature_obj.name = "Character Armature"
    armature_data.name = "Character Armature"

    armature_obj.show_in_front = True
    armature_obj.display_type = "WIRE"
    armature_data.show_axes = True
    armature_data.show_names = True
    context.collection.objects.link(armature_obj)

    context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")

    # ------- START OF ROOT CREATION -------
    root = armature_data.edit_bones.new("Root")
    root.head = (0, 0, 0)
    root.tail = (0, 0.5, 0)

    # ------- START OF SPINE CREATION -------
    DEF_Hips = armature_data.edit_bones.new("DEF_Hips")
    DEF_Hips.head = (0, 0, 0.85)
    DEF_Hips.tail = (0,  -0.019, 0.97)
    DEF_Hips.parent = root
    DEF_Hips.use_connect = False
    # --- spine 01 ---
    DEF_Spine_01 = armature_data.edit_bones.new("DEF_Spine_01")
    DEF_Spine_01.head = (0, -0.019, 0.97)
    DEF_Spine_01.tail = (0, -0.028, 1.1)
    DEF_Spine_01.parent = DEF_Hips
    DEF_Spine_01.use_connect = False
    # --- spine 02 ---
    DEF_Spine_02 = armature_data.edit_bones.new("DEF_Spine_02")
    DEF_Spine_02.head = (0, -0.028, 1.1)
    DEF_Spine_02.tail = (0, 0, 1.2)
    DEF_Spine_02.parent = DEF_Spine_01
    DEF_Spine_02.use_connect = False
    # --- chest ---
    DEF_Chest = armature_data.edit_bones.new("DEF_Chest")
    DEF_Chest.head = (0, 0, 1.2)
    DEF_Chest.tail = (0, 0, 1.3)
    DEF_Chest.parent = DEF_Spine_02
    DEF_Chest.use_connect = False
    # --- chest 01 --- extra control for chest
    DEF_Chest_Sub_01 = armature_data.edit_bones.new("DEF_Chest_Sub_01")
    DEF_Chest_Sub_01.head = DEF_Chest.head
    DEF_Chest_Sub_01.tail = (DEF_Chest.tail + DEF_Chest.head)/2
    DEF_Chest_Sub_01.parent = DEF_Chest
    DEF_Chest_Sub_01.use_connect = False
    # --- chest 02 ---extra control for chest
    DEF_Chest_Sub_02 = armature_data.edit_bones.new("DEF_Chest_Sub_02")
    DEF_Chest_Sub_02.head = DEF_Chest_Sub_01.tail
    DEF_Chest_Sub_02.tail = DEF_Chest.tail
    DEF_Chest_Sub_02.parent = DEF_Chest
    DEF_Chest_Sub_02.use_connect = False
    # --- neck ---
    DEF_Neck = armature_data.edit_bones.new("DEF_Neck")
    DEF_Neck.head = (0, 0, 1.3)
    DEF_Neck.tail = (0, 0, 1.5)
    DEF_Neck.parent = DEF_Chest
    DEF_Neck.use_connect = False
    # --- head ---
    DEF_Head = armature_data.edit_bones.new("DEF_Head")
    DEF_Head.head = (0, 0, 1.5)
    DEF_Head.tail = (0, 0, 1.7)
    DEF_Head.parent = DEF_Neck
    DEF_Head.use_connect = False

    # ------- START OF LEFT ARM CREATION -------
    # --- Left Shoulder ---
    DEF_Shoulder_left = armature_data.edit_bones.new("DEF_Shoulder.L")
    DEF_Shoulder_left.head = (0.04, 0, 1.25)
    DEF_Shoulder_left.tail = (0.2, 0, 1.25)
    DEF_Shoulder_left.parent = DEF_Chest
    DEF_Shoulder_left.use_connect = False
    # --- Left Arm
    DEF_Arm_left = armature_data.edit_bones.new("DEF_Arm.L")
    DEF_Arm_left.head = (0.21, 0, 1.25)
    DEF_Arm_left.tail = (0.37, 0.05, 1.25)
    DEF_Arm_left.parent = DEF_Shoulder_left
    DEF_Arm_left.roll = math.pi
    DEF_Arm_left.use_connect = False
    # --- Left Forearm (ONE piece) --- !!! When ORG BONES generate, the forarm will be subdivided !!!
    DEF_Forearm_left = armature_data.edit_bones.new("DEF_Forearm.L")
    DEF_Forearm_left.head = DEF_Arm_left.tail
    DEF_Forearm_left.tail = (0.69, 0, 1.25)
    DEF_Forearm_left.parent = DEF_Arm_left
    DEF_Forearm_left.roll = math.pi
    DEF_Forearm_left.use_connect = False
    # --- Left Hand ---
    DEF_Hand_Left = armature_data.edit_bones.new("DEF_Hand.L")
    DEF_Hand_Left.head = DEF_Forearm_left.tail
    DEF_Hand_Left.tail = (0.85, 0, 1.25)
    DEF_Hand_Left.parent = DEF_Forearm_left
    DEF_Hand_Left.roll = math.pi
    DEF_Hand_Left.use_connect = False

    # --- Left Thumb 01------------------------------------------------------------
    DEF_Thumb_01_Left = armature_data.edit_bones.new("DEF_Thumb_01.L")
    DEF_Thumb_01_Left.head = (0.85, -0.04, 1.25)
    DEF_Thumb_01_Left.tail = (0.87, -0.04, 1.25)
    DEF_Thumb_01_Left.parent = DEF_Hand_Left
    DEF_Thumb_01_Left.use_connect = False
    # --- Left Thumb 02---
    DEF_Thumb_02_Left = armature_data.edit_bones.new("DEF_Thumb_02.L")
    DEF_Thumb_02_Left.head = DEF_Thumb_01_Left.tail
    DEF_Thumb_02_Left.tail = (0.89, -0.04, 1.25)
    DEF_Thumb_02_Left.parent = DEF_Thumb_01_Left
    DEF_Thumb_02_Left.use_connect = False
    # --- Left Thumb 03---
    DEF_Thumb_03_Left = armature_data.edit_bones.new("DEF_Thumb_03.L")
    DEF_Thumb_03_Left.head = DEF_Thumb_02_Left.tail
    DEF_Thumb_03_Left.tail = (0.91, -0.04, 1.25)
    DEF_Thumb_03_Left.parent = DEF_Thumb_02_Left
    DEF_Thumb_03_Left.use_connect = False

    # --- Left Index_Finger Palm ------------------------------------------------------------
    DEF_Index_Finger_Palm_Left = armature_data.edit_bones.new("DEF_Index_Finger_Palm.L")
    DEF_Index_Finger_Palm_Left.head = (0.86, -0.02, 1.25)
    DEF_Index_Finger_Palm_Left.tail = (0.88, -0.02, 1.25)
    DEF_Index_Finger_Palm_Left.parent = DEF_Hand_Left
    DEF_Index_Finger_Palm_Left.roll = -(math.pi / 2)
    DEF_Index_Finger_Palm_Left.use_connect = False
    # --- Left Index_Finger 01----
    DEF_Index_Finger_01_Left = armature_data.edit_bones.new("DEF_Index_Finger_01.L")
    DEF_Index_Finger_01_Left.head = DEF_Index_Finger_Palm_Left.tail
    DEF_Index_Finger_01_Left.tail = (0.90, -0.02, 1.25)
    DEF_Index_Finger_01_Left.parent = DEF_Index_Finger_Palm_Left
    DEF_Index_Finger_01_Left.roll = -(math.pi / 2)
    DEF_Index_Finger_01_Left.use_connect = False
    # --- Left Index_Finger 02---
    DEF_Index_Finger_02_Left = armature_data.edit_bones.new("DEF_Index_Finger_02.L")
    DEF_Index_Finger_02_Left.head = DEF_Index_Finger_01_Left.tail
    DEF_Index_Finger_02_Left.tail = (0.92, -0.02, 1.25)
    DEF_Index_Finger_02_Left.parent = DEF_Index_Finger_01_Left
    DEF_Index_Finger_02_Left.roll = -(math.pi / 2)
    DEF_Index_Finger_02_Left.use_connect = False
    # --- Left Index_Finger 03---
    DEF_Index_Finger_03_Left = armature_data.edit_bones.new("DEF_Index_Finger_03.L")
    DEF_Index_Finger_03_Left.head = DEF_Index_Finger_02_Left.tail
    DEF_Index_Finger_03_Left.tail = (0.94, -0.02, 1.25)
    DEF_Index_Finger_03_Left.parent = DEF_Index_Finger_02_Left
    DEF_Index_Finger_03_Left.roll = -(math.pi / 2)
    DEF_Index_Finger_03_Left.use_connect = False

    # --- Left Middle_Finger Palm ---------------------------------------------------------
    DEF_Middle_Finger_Palm_Left = armature_data.edit_bones.new("DEF_Middle_Finger_Palm.L")
    DEF_Middle_Finger_Palm_Left.head = (0.86, 0.00, 1.25)
    DEF_Middle_Finger_Palm_Left.tail = (0.88, 0.00, 1.25)
    DEF_Middle_Finger_Palm_Left.parent = DEF_Hand_Left
    DEF_Middle_Finger_Palm_Left.roll = -(math.pi / 2)
    DEF_Middle_Finger_Palm_Left.use_connect = False
    # --- Left Middle_Finger 01---------------------------------------------------------
    DEF_Middle_Finger_01_Left = armature_data.edit_bones.new("DEF_Middle_Finger_01.L")
    DEF_Middle_Finger_01_Left.head = DEF_Middle_Finger_Palm_Left.tail
    DEF_Middle_Finger_01_Left.tail = (0.90, 0.00, 1.25)
    DEF_Middle_Finger_01_Left.parent = DEF_Middle_Finger_Palm_Left
    DEF_Middle_Finger_01_Left.roll = -(math.pi / 2)
    DEF_Middle_Finger_01_Left.use_connect = False
    # --- Left Middle_Finger 02---
    DEF_Middle_Finger_02_Left = armature_data.edit_bones.new("DEF_Middle_Finger_02.L")
    DEF_Middle_Finger_02_Left.head = DEF_Middle_Finger_01_Left.tail
    DEF_Middle_Finger_02_Left.tail = (0.92, 0.00, 1.25)
    DEF_Middle_Finger_02_Left.parent = DEF_Middle_Finger_01_Left
    DEF_Middle_Finger_02_Left.roll = -(math.pi / 2)
    DEF_Middle_Finger_02_Left.use_connect = False
    # --- Left Middle_Finger 03---
    DEF_Middle_Finger_03_Left = armature_data.edit_bones.new("DEF_Middle_Finger_03.L")
    DEF_Middle_Finger_03_Left.head = DEF_Middle_Finger_02_Left.tail
    DEF_Middle_Finger_03_Left.tail = (0.94, 0.00, 1.25)
    DEF_Middle_Finger_03_Left.parent = DEF_Middle_Finger_02_Left
    DEF_Middle_Finger_03_Left.roll = -(math.pi / 2)
    DEF_Middle_Finger_03_Left.use_connect = False

    # --- Left Ring_Finger Palm---------------------------------------------------------
    DEF_Ring_Finger_Palm_Left = armature_data.edit_bones.new("DEF_Ring_Finger_Palm.L")
    DEF_Ring_Finger_Palm_Left.head = (0.86, 0.02, 1.25)
    DEF_Ring_Finger_Palm_Left.tail = (0.88, 0.02, 1.25)
    DEF_Ring_Finger_Palm_Left.parent = DEF_Hand_Left
    DEF_Ring_Finger_Palm_Left.roll = -(math.pi / 2)
    DEF_Ring_Finger_Palm_Left.use_connect = False

    # --- Left Ring_Finger 01----
    DEF_Ring_Finger_01_Left = armature_data.edit_bones.new("DEF_Ring_Finger_01.L")
    DEF_Ring_Finger_01_Left.head = (0.88, 0.02, 1.25)
    DEF_Ring_Finger_01_Left.tail = (0.90, 0.02, 1.25)
    DEF_Ring_Finger_01_Left.parent = DEF_Ring_Finger_Palm_Left
    DEF_Ring_Finger_01_Left.roll = -(math.pi / 2)
    DEF_Ring_Finger_01_Left.use_connect = False
    # --- Left Ring_Finger 02---
    DEF_Ring_Finger_02_Left = armature_data.edit_bones.new("DEF_Ring_Finger_02.L")
    DEF_Ring_Finger_02_Left.head = DEF_Ring_Finger_01_Left.tail
    DEF_Ring_Finger_02_Left.tail = (0.92, 0.02, 1.25)
    DEF_Ring_Finger_02_Left.parent = DEF_Ring_Finger_01_Left
    DEF_Ring_Finger_02_Left.roll = -(math.pi / 2)
    DEF_Ring_Finger_02_Left.use_connect = False
    # --- Left Ring_Finger 03---
    DEF_Ring_Finger_03_Left = armature_data.edit_bones.new("DEF_Ring_Finger_03.L")
    DEF_Ring_Finger_03_Left.head = DEF_Ring_Finger_02_Left.tail
    DEF_Ring_Finger_03_Left.tail = (0.94, 0.02, 1.25)
    DEF_Ring_Finger_03_Left.parent = DEF_Ring_Finger_02_Left
    DEF_Ring_Finger_03_Left.roll = -(math.pi / 2)
    DEF_Ring_Finger_03_Left.use_connect = False

    # --- Left Pinky_Finger Palm---------------------------------------------------------
    DEF_Pinky_Finger_Palm_Left = armature_data.edit_bones.new("DEF_Pinky_Finger_Palm.L")
    DEF_Pinky_Finger_Palm_Left.head = (0.86, 0.04, 1.25)
    DEF_Pinky_Finger_Palm_Left.tail = (0.88, 0.04, 1.25)
    DEF_Pinky_Finger_Palm_Left.parent = DEF_Hand_Left
    DEF_Pinky_Finger_Palm_Left.roll = -(math.pi / 2)
    DEF_Pinky_Finger_Palm_Left.use_connect = False

    # --- Left Pinky_Finger 01---------------------------------------------------------
    DEF_Pinky_Finger_01_Left = armature_data.edit_bones.new("DEF_Pinky_Finger_01.L")
    DEF_Pinky_Finger_01_Left.head = (0.88, 0.04, 1.25)
    DEF_Pinky_Finger_01_Left.tail = (0.90, 0.04, 1.25)
    DEF_Pinky_Finger_01_Left.parent = DEF_Pinky_Finger_Palm_Left
    DEF_Pinky_Finger_01_Left.roll = -(math.pi / 2)
    DEF_Pinky_Finger_01_Left.use_connect = False
    # --- Left Pinky_Finger 02---
    DEF_Pinky_Finger_02_Left = armature_data.edit_bones.new("DEF_Pinky_Finger_02.L")
    DEF_Pinky_Finger_02_Left.head = DEF_Pinky_Finger_01_Left.tail
    DEF_Pinky_Finger_02_Left.tail = (0.92, 0.04, 1.25)
    DEF_Pinky_Finger_02_Left.parent = DEF_Pinky_Finger_01_Left
    DEF_Pinky_Finger_02_Left.roll = -(math.pi / 2)
    DEF_Pinky_Finger_02_Left.use_connect = False
    # --- Left Pinky_Finger 03---
    DEF_Pinky_Finger_03_Left = armature_data.edit_bones.new("DEF_Pinky_Finger_03.L")
    DEF_Pinky_Finger_03_Left.head = DEF_Pinky_Finger_02_Left.tail
    DEF_Pinky_Finger_03_Left.tail = (0.94, 0.04, 1.25)
    DEF_Pinky_Finger_03_Left.parent = DEF_Pinky_Finger_02_Left
    DEF_Pinky_Finger_03_Left.roll = -(math.pi / 2)
    DEF_Pinky_Finger_03_Left.use_connect = False

    # --- Left Thigh---------------------------------------------------------
    DEF_Thigh_Left = armature_data.edit_bones.new("DEF_Thigh.L")
    DEF_Thigh_Left.head = (0.09, 0.00, 0.87)
    DEF_Thigh_Left.tail = (0.09, -0.05, 0.56)
    DEF_Thigh_Left.parent = DEF_Hips
    DEF_Thigh_Left.roll = math.pi / 2
    DEF_Thigh_Left.use_connect = False

    # --- Left Shin---------------------------------------------------------
    DEF_Shin_Left = armature_data.edit_bones.new("DEF_Shin.L")
    DEF_Shin_Left.head = (0.09, -0.05, 0.56)
    DEF_Shin_Left.tail = (0.09, 0.00, 0.15)
    DEF_Shin_Left.parent = DEF_Thigh_Left
    DEF_Shin_Left.roll = math.pi / 2
    DEF_Shin_Left.use_connect = True

    # --- Left Foot---------------------------------------------------------
    DEF_Foot_Left = armature_data.edit_bones.new("DEF_Foot.L")
    DEF_Foot_Left.head = (0.09, 0.00, 0.15)
    DEF_Foot_Left.tail = (0.09, -0.20, 0.03)
    DEF_Foot_Left.parent = DEF_Shin_Left
    DEF_Foot_Left.roll = math.pi / 2
    DEF_Foot_Left.use_connect = True

    # --- Left Toe---------------------------------------------------------
    DEF_Toe_Left = armature_data.edit_bones.new("DEF_Toe.L")
    DEF_Toe_Left.head = (0.09, 0.20, 0.03)
    DEF_Toe_Left.tail = (0.09, -0.31, 0.03)
    DEF_Toe_Left.parent = DEF_Foot_Left
    DEF_Toe_Left.roll = -(math.pi / 2)
    DEF_Toe_Left.use_connect = True

    # ---!!! MCH HEEL AND FOOT BANKS - Needs to be positioned manually in blender before rigging---------------------------------------------------------
    # --- HEEL Mechanism ----
    MCH_Heel_left = armature_data.edit_bones.new("MCH_Heel.L")
    MCH_Heel_left.head = (0.09, 0.0, 0.00)
    MCH_Heel_left.tail = (0.09, 0.0, 0.08)

    # --- Bank left Mechanism ----
    MCH_Foot_Bank_01_left = armature_data.edit_bones.new("MCH_Foot_Bank_01.L")
    MCH_Foot_Bank_01_left.head = (0.02, -0.2, 0.00)
    MCH_Foot_Bank_01_left.tail = (0.16, -0.2, 0.00)
    MCH_Foot_Bank_01_left.align_roll(Vector((0.0, -1.0, 0.0)))

    # --- Bank right Mechanism ----
    MCH_Foot_Bank_02_left = armature_data.edit_bones.new("MCH_Foot_Bank_02.L")
    MCH_Foot_Bank_02_left.head = (0.16, -0.2, 0.00)
    MCH_Foot_Bank_02_left.tail = (0.02, -0.2, 0.00)
    MCH_Foot_Bank_02_left.parent = MCH_Foot_Bank_01_left
    MCH_Foot_Bank_02_left.align_roll(Vector((0.0, -1.0, 0.0)))
    MCH_Foot_Bank_02_left.use_connect = True

    # ------- END OF BONE CREATION -------

    # bpy.ops.object.mode_set(mode='OBJECT')
    return armature_obj


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Set Up Scene" BUTTON IS CLICKED =========
class EMANATE_OT_pre_rig_initialize(bpy.types.Operator):
    bl_idname = NAMES.operator_idname
    bl_label = "Set Up Scene"  # This is the label that will be displayed in the button
    bl_description = NAMES.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        changed = []
        changed += fix_pivot_point(context.scene)
        changed += fix_render_settings(context.scene)

        if getattr(context.scene, MATCH_UNREAL_UNITS_PROP):
            changed += fix_scene_units(context.scene)
            changed += fix_viewport_overlays()

        changed += deform_cleanup.sync_deform_flags(context.active_object)

        # Warn either way -- the setting can already be GPU from a previous run
        # and still not actually be rendering on the GPU.
        if not gpu_backend_is_configured():
            self.report(
                {"WARNING"},
                "No GPU backend selected in Preferences > System; "
                "Cycles will fall back to CPU",
            )

        if not changed:
            self.report({"INFO"}, "Scene already initialized")
            return {"FINISHED"}

        # Print every change to the console first, then one summary in the
        # status bar -- report() only keeps the last message it is given.
        for change in changed:
            print(f"[pre-rig] {change}")

        self.report({"INFO"}, f"Fixed: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Make DEF Skeleton" BUTTON IS CLICKED =========
class EMANATE_OT_make_def_skeleton(bpy.types.Operator):
    bl_idname = NAMES_DEF_SKELETON.operator_idname
    bl_label = NAMES_DEF_SKELETON.label
    bl_description = NAMES_DEF_SKELETON.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armature_obj = create_deformation_skeleton(context)
        deform_cleanup.sync_deform_flags(armature_obj)

        self.report({"INFO"}, f"Built {armature_obj.name}")
        return {"FINISHED"}


# ========= THIS IS THE PANEL THAT OPENS WHEN THE BUTTON IS CLICKED =========
class EMANATE_PT_pre_rig_initialize(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, MATCH_UNREAL_UNITS_PROP)
        layout.operator(NAMES.operator_idname)
        layout.operator(NAMES_DEF_SKELETON.operator_idname)


_classes = (
    EMANATE_OT_pre_rig_initialize,
    EMANATE_OT_make_def_skeleton,
    EMANATE_PT_pre_rig_initialize,
)


def register():
    naming.check_classes(
        (EMANATE_OT_pre_rig_initialize, EMANATE_PT_pre_rig_initialize), NAMES
    )
    naming.check_classes((EMANATE_OT_make_def_skeleton,), NAMES_DEF_SKELETON)
    for cls in _classes:
        bpy.utils.register_class(cls)

    # ------ add the checkbox to the scene properties so it can be accessed by the operator ------
    setattr(
        bpy.types.Scene,
        MATCH_UNREAL_UNITS_PROP,
        bpy.props.BoolProperty(
            name="Change Blender Units to Match Unreal",
            description="Unit System remains metric. Blender scale is set to 0.01 and length unit is set to centimeters. Unreal as of 2025 will multiply rigs up by 100x, so this compensates for that. It is a toggle right now because this may not be an issue anymore in newer versions of blender and unreal",
            default=False,
            update=match_unreal_units_update,
        ),
    )


def unregister():
    delattr(bpy.types.Scene, MATCH_UNREAL_UNITS_PROP)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
