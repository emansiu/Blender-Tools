import math

import bpy
from mathutils import Vector

from ..helpers import naming_unity as naming
from ..helpers import widgets

NAMES = naming.register_tool(
    "pre_rig_initialize",
    label="Initialize Pre-Rigging Settings",
    owner=__name__,
    description="checks settings for armature objects and scene settings to make sure we are working in an environment ready for rigs that can be exported to Unreal Engine",
)

NAMES_DEF_SKELETON = naming.register_tool(
    "create_deformation_skeleton",
    label="Make DEF[ormation] Skeleton",
    owner=__name__,
    description="Builds the deformation skeleton -- root, spine and left arm chain -- then mirrors the left side onto the right",
)

NAMES_DEF_MIRROR = naming.register_tool(
    "mirror_deformation_skeleton",
    label="Mirror .L to .R over X",
    owner=__name__,
    description="Mirrors anything ending in .L onto the right side",
)
NAMES_MAKE_RIG = naming.register_tool(
    "generate_rigs_for_body",
    label="Generate Rig",
    owner=__name__,
    description="Creates flexible rig with switchable fk/ik arms and legs.",
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
    DEF_Hips.tail = (0, 0, 0.97)
    DEF_Hips.parent = root
    DEF_Hips.use_connect = False
    # --- spine 01 ---
    DEF_Spine_01 = armature_data.edit_bones.new("DEF_Spine_01")
    DEF_Spine_01.head = (0, 0, 0.97)
    DEF_Spine_01.tail = (0, 0, 1.1)
    DEF_Spine_01.parent = DEF_Hips
    DEF_Spine_01.use_connect = False
    # --- spine 02 ---
    DEF_Spine_02 = armature_data.edit_bones.new("DEF_Spine_02")
    DEF_Spine_02.head = (0, 0, 1.1)
    DEF_Spine_02.tail = (0, 0, 1.2)
    DEF_Spine_02.parent = DEF_Spine_01
    DEF_Spine_02.use_connect = False
    # --- chest ---
    DEF_Chest = armature_data.edit_bones.new("DEF_Chest")
    DEF_Chest.head = (0, 0, 1.2)
    DEF_Chest.tail = (0, 0, 1.3)
    DEF_Chest.parent = DEF_Spine_02
    DEF_Chest.use_connect = False
    # --- neck 01---
    DEF_Neck_01 = armature_data.edit_bones.new("DEF_Neck_01")
    DEF_Neck_01.head = (0, 0, 1.3)
    DEF_Neck_01.tail = (0, 0, 1.4)
    DEF_Neck_01.parent = DEF_Chest
    DEF_Neck_01.use_connect = False
    # --- neck 02 ---
    DEF_Neck_02 = armature_data.edit_bones.new("DEF_Neck_02")
    DEF_Neck_02.head = (0, 0, 1.4)
    DEF_Neck_02.tail = (0, 0, 1.5)
    DEF_Neck_02.parent = DEF_Neck_01
    DEF_Neck_02.use_connect = False
    # --- head ---
    DEF_Head = armature_data.edit_bones.new("DEF_Head")
    DEF_Head.head = (0, 0, 1.5)
    DEF_Head.tail = (0, 0, 1.7)
    DEF_Head.parent = DEF_Neck_02
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
    DEF_Arm_left.tail = (0.37, 0, 1.25)
    DEF_Arm_left.parent = DEF_Shoulder_left
    DEF_Arm_left.roll = math.pi
    DEF_Arm_left.use_connect = False
    # --- Left Forearm 01 ---
    DEF_Forearm_01_left = armature_data.edit_bones.new("DEF_Forearm_01.L")
    DEF_Forearm_01_left.head = (0.37, 0, 1.25)
    DEF_Forearm_01_left.tail = (0.53, 0, 1.25)
    DEF_Forearm_01_left.parent = DEF_Arm_left
    DEF_Forearm_01_left.roll = math.pi
    DEF_Forearm_01_left.use_connect = True
    # --- Left Forearm 02 ---
    DEF_Forearm_02_left = armature_data.edit_bones.new("DEF_Forearm_02.L")
    DEF_Forearm_02_left.head = (0.53, 0, 1.25)
    DEF_Forearm_02_left.tail = (0.69, 0, 1.25)
    DEF_Forearm_02_left.parent = DEF_Forearm_01_left
    DEF_Forearm_02_left.roll = math.pi
    DEF_Forearm_02_left.use_connect = True
    # --- Left Hand ---
    DEF_Hand_Left = armature_data.edit_bones.new("DEF_Hand.L")
    DEF_Hand_Left.head = (0.69, 0, 1.25)
    DEF_Hand_Left.tail = (0.85, 0, 1.25)
    DEF_Hand_Left.parent = DEF_Forearm_02_left
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
    DEF_Thumb_02_Left.head = (0.87, -0.04, 1.25)
    DEF_Thumb_02_Left.tail = (0.89, -0.04, 1.25)
    DEF_Thumb_02_Left.parent = DEF_Thumb_01_Left
    DEF_Thumb_02_Left.use_connect = True
    # --- Left Thumb 03---
    DEF_Thumb_03_Left = armature_data.edit_bones.new("DEF_Thumb_03.L")
    DEF_Thumb_03_Left.head = (0.89, -0.04, 1.25)
    DEF_Thumb_03_Left.tail = (0.91, -0.04, 1.25)
    DEF_Thumb_03_Left.parent = DEF_Thumb_02_Left
    DEF_Thumb_03_Left.use_connect = True

    # --- Left IndexFinger 01------------------------------------------------------------
    DEF_IndexFinger_01_Left = armature_data.edit_bones.new("DEF_IndexFinger_01.L")
    DEF_IndexFinger_01_Left.head = (0.88, -0.02, 1.25)
    DEF_IndexFinger_01_Left.tail = (0.90, -0.02, 1.25)
    DEF_IndexFinger_01_Left.parent = DEF_Hand_Left
    DEF_IndexFinger_01_Left.roll = -(math.pi / 2)
    DEF_IndexFinger_01_Left.use_connect = False
    # --- Left IndexFinger 02---
    DEF_IndexFinger_02_Left = armature_data.edit_bones.new("DEF_IndexFinger_02.L")
    DEF_IndexFinger_02_Left.head = (0.90, -0.02, 1.25)
    DEF_IndexFinger_02_Left.tail = (0.92, -0.02, 1.25)
    DEF_IndexFinger_02_Left.parent = DEF_IndexFinger_01_Left
    DEF_IndexFinger_02_Left.roll = -(math.pi / 2)
    DEF_IndexFinger_02_Left.use_connect = True
    # --- Left IndexFinger 03---
    DEF_IndexFinger_03_Left = armature_data.edit_bones.new("DEF_IndexFinger_03.L")
    DEF_IndexFinger_03_Left.head = (0.92, -0.02, 1.25)
    DEF_IndexFinger_03_Left.tail = (0.94, -0.02, 1.25)
    DEF_IndexFinger_03_Left.parent = DEF_IndexFinger_02_Left
    DEF_IndexFinger_03_Left.roll = -(math.pi / 2)
    DEF_IndexFinger_03_Left.use_connect = True

    # --- Left MiddleFinger 01---------------------------------------------------------
    DEF_MiddleFinger_01_Left = armature_data.edit_bones.new("DEF_MiddleFinger_01.L")
    DEF_MiddleFinger_01_Left.head = (0.88, 0.00, 1.25)
    DEF_MiddleFinger_01_Left.tail = (0.90, 0.00, 1.25)
    DEF_MiddleFinger_01_Left.parent = DEF_Hand_Left
    DEF_MiddleFinger_01_Left.roll = -(math.pi / 2)
    DEF_MiddleFinger_01_Left.use_connect = False
    # --- Left MiddleFinger 02---
    DEF_MiddleFinger_02_Left = armature_data.edit_bones.new("DEF_MiddleFinger_02.L")
    DEF_MiddleFinger_02_Left.head = (0.90, 0.00, 1.25)
    DEF_MiddleFinger_02_Left.tail = (0.92, 0.00, 1.25)
    DEF_MiddleFinger_02_Left.parent = DEF_MiddleFinger_01_Left
    DEF_MiddleFinger_02_Left.roll = -(math.pi / 2)
    DEF_MiddleFinger_02_Left.use_connect = True
    # --- Left MiddleFinger 03---
    DEF_MiddleFinger_03_Left = armature_data.edit_bones.new("DEF_MiddleFinger_03.L")
    DEF_MiddleFinger_03_Left.head = (0.92, 0.00, 1.25)
    DEF_MiddleFinger_03_Left.tail = (0.94, 0.00, 1.25)
    DEF_MiddleFinger_03_Left.parent = DEF_MiddleFinger_02_Left
    DEF_MiddleFinger_03_Left.roll = -(math.pi / 2)
    DEF_MiddleFinger_03_Left.use_connect = True

    # --- Left RingFinger 01---------------------------------------------------------
    DEF_RingFinger_01_Left = armature_data.edit_bones.new("DEF_RingFinger_01.L")
    DEF_RingFinger_01_Left.head = (0.88, 0.02, 1.25)
    DEF_RingFinger_01_Left.tail = (0.90, 0.02, 1.25)
    DEF_RingFinger_01_Left.parent = DEF_Hand_Left
    DEF_RingFinger_01_Left.roll = -(math.pi / 2)
    DEF_RingFinger_01_Left.use_connect = False
    # --- Left RingFinger 02---
    DEF_RingFinger_02_Left = armature_data.edit_bones.new("DEF_RingFinger_02.L")
    DEF_RingFinger_02_Left.head = (0.90, 0.02, 1.25)
    DEF_RingFinger_02_Left.tail = (0.92, 0.02, 1.25)
    DEF_RingFinger_02_Left.parent = DEF_RingFinger_01_Left
    DEF_RingFinger_02_Left.roll = -(math.pi / 2)
    DEF_RingFinger_02_Left.use_connect = True
    # --- Left RingFinger 03---
    DEF_RingFinger_03_Left = armature_data.edit_bones.new("DEF_RingFinger_03.L")
    DEF_RingFinger_03_Left.head = (0.92, 0.02, 1.25)
    DEF_RingFinger_03_Left.tail = (0.94, 0.02, 1.25)
    DEF_RingFinger_03_Left.parent = DEF_RingFinger_02_Left
    DEF_RingFinger_03_Left.roll = -(math.pi / 2)
    DEF_RingFinger_03_Left.use_connect = True

    # --- Left PinkyFinger 01---------------------------------------------------------
    DEF_PinkyFinger_01_Left = armature_data.edit_bones.new("DEF_PinkyFinger_01.L")
    DEF_PinkyFinger_01_Left.head = (0.88, 0.04, 1.25)
    DEF_PinkyFinger_01_Left.tail = (0.90, 0.04, 1.25)
    DEF_PinkyFinger_01_Left.parent = DEF_Hand_Left
    DEF_PinkyFinger_01_Left.roll = -(math.pi / 2)
    DEF_PinkyFinger_01_Left.use_connect = False
    # --- Left PinkyFinger 02---
    DEF_PinkyFinger_02_Left = armature_data.edit_bones.new("DEF_PinkyFinger_02.L")
    DEF_PinkyFinger_02_Left.head = (0.90, 0.04, 1.25)
    DEF_PinkyFinger_02_Left.tail = (0.92, 0.04, 1.25)
    DEF_PinkyFinger_02_Left.parent = DEF_PinkyFinger_01_Left
    DEF_PinkyFinger_02_Left.roll = -(math.pi / 2)
    DEF_PinkyFinger_02_Left.use_connect = True
    # --- Left PinkyFinger 03---
    DEF_PinkyFinger_03_Left = armature_data.edit_bones.new("DEF_PinkyFinger_03.L")
    DEF_PinkyFinger_03_Left.head = (0.92, 0.04, 1.25)
    DEF_PinkyFinger_03_Left.tail = (0.94, 0.04, 1.25)
    DEF_PinkyFinger_03_Left.parent = DEF_PinkyFinger_02_Left
    DEF_PinkyFinger_03_Left.roll = -(math.pi / 2)
    DEF_PinkyFinger_03_Left.use_connect = True

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
    MCH_Foot_Bank_01_left.align_roll(Vector((0.0,-1.0,0.0)))

    # --- Bank right Mechanism ----
    MCH_Foot_Bank_02_left = armature_data.edit_bones.new("MCH_Foot_Bank_02.L")
    MCH_Foot_Bank_02_left.head = (0.16, -0.2, 0.00)
    MCH_Foot_Bank_02_left.tail = (0.02, -0.2, 0.00)
    MCH_Foot_Bank_02_left.parent = MCH_Foot_Bank_01_left
    MCH_Foot_Bank_02_left.align_roll(Vector((0.0,-1.0,0.0)))
    MCH_Foot_Bank_02_left.use_connect = True

    # ------- END OF BONE CREATION -------

    # bpy.ops.object.mode_set(mode='OBJECT')
    return armature_obj


def add_slider_driver(
    constraint,
    armature_obj,
    expression,
    axis="X",
    slider_bone="WGT_Leg_Properties_Controller.L",
    data_path="influence",
):
    """Drive `constraint`.<data_path> from a location channel of the slider bone.

    Blender has no clean Python route for duplicating an existing driver onto
    another property -- the only native one is the copy/paste driver operators,
    which need button context -- so rebuilding it per constraint is the tidy
    way to share one setup across a chain.

    `axis` picks the channel: "X", "Y" or "Z". The driver variable is named to
    match, so axis="Y" reads LOC_Y and exposes it to the expression as
    `slider_y`. `expression` has to reference that same name -- pass the
    inverse form ("1 - slider_x / max") for whichever side should fade out.

    `data_path` defaults to "influence" for constraints, but also accepts
    "weight" so the same helper can drive an armature constraint target's
    blend weight.
    """
    fcurve = constraint.driver_add(data_path)

    # Defensive: a generator modifier on the curve would override the
    # expression and make the driver read as a flat ramp. Removing any that
    # turn up costs nothing when there are none.
    for modifier in list(fcurve.modifiers):
        fcurve.modifiers.remove(modifier)

    driver = fcurve.driver
    driver.type = "SCRIPTED"

    variable = driver.variables.new()
    variable.name = f"slider_{axis.lower()}"
    variable.type = "TRANSFORMS"

    target = variable.targets[0]
    target.id = armature_obj
    target.bone_target = slider_bone
    target.transform_type = f"LOC_{axis.upper()}"
    # TRANSFORM_SPACE reads the raw channel value -- the same number the
    # sidebar shows and the same one LIMIT_LOCATION clamps in LOCAL space --
    # so the bone's rest roll cannot rotate the axis out from under the slider.
    target.transform_space = "TRANSFORM_SPACE"

    driver.expression = expression
    return driver


def generate_leg_ik_fk_rig(context, armature_obj=None):

    changed = []

    # Recapture the armature
    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    # edit_bones is only populated in edit mode, so we have to be in it whether
    # or not the caller already was.
    if armature_obj.mode != "EDIT":
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = armature_obj.data.edit_bones

    # ORG_Hips is built by the org-bone generator tool from DEF_Hips, so it
    # has to be looked up by name here rather than created in this function.
    # We re-retrieve the ORG bones we need here
    ORG_Hips = edit_bones.get("ORG_Hips")
    ORG_Thigh_Left = edit_bones.get("ORG_Thigh.L")
    ORG_Shin_Left = edit_bones.get("ORG_Shin.L")
    ORG_Foot_Left = edit_bones.get("ORG_Foot.L")
    ORG_Toe_Left = edit_bones.get("ORG_Toe.L")
    Root = edit_bones.get("Root")
    # These bones below are manually placed during def skeleton, before ORG one generation
    MCH_Heel_Left = edit_bones.get("MCH_Heel.L")
    MCH_Foot_Bank_01_Left = edit_bones.get("MCH_Foot_Bank_01.L")
    MCH_Foot_Bank_02_Left = edit_bones.get("MCH_Foot_Bank_02.L")
    # `is None` binds to a single operand, so it has to be tested per bone --
    # chaining them with `or` would only check the last one.
    if any(
        bone is None
        for bone in (
            ORG_Hips,
            ORG_Thigh_Left,
            ORG_Shin_Left,
            ORG_Foot_Left,
            ORG_Toe_Left,
            Root
        )
    ):
        return changed



    # ============================= MCH CHAIN ============================================================================================================
    # ---MCH Left Leg Socket---------------------------------------------------------
    MCH_Leg_Socket_Left = edit_bones.new("MCH_Leg_Socket.L")
    MCH_Leg_Socket_Left.head = ORG_Thigh_Left.head
    MCH_Leg_Socket_Left.tail = ORG_Thigh_Left.head + Vector((0.0, 0.06,0.0))
    MCH_Leg_Socket_Left.parent = ORG_Hips
    # align_roll is more intentional than leaving roll to default or zero in case the rig is moved somehow in the future
    MCH_Leg_Socket_Left.align_roll(Vector((0.0,0.0,1.0)))
    MCH_Leg_Socket_Left.use_connect = False

    # ---MCH Left Leg Intermediary Socket---------------------------------------------------------
    MCH_INT_Leg_Socket_Left = edit_bones.new("MCH_INT_Leg_Socket.L")
    MCH_INT_Leg_Socket_Left.head = ORG_Thigh_Left.head
    MCH_INT_Leg_Socket_Left.tail = ORG_Thigh_Left.head + Vector((0.0, 0.03,0.0))
    MCH_INT_Leg_Socket_Left.parent = Root
    MCH_INT_Leg_Socket_Left.align_roll(Vector((0.0,0.0,1.0)))
    MCH_INT_Leg_Socket_Left.use_connect = False

    # ---MCH Left Thigh---------------------------------------------------------
    MCH_SWITCH_Thigh_Left = edit_bones.new("MCH_SWITCH_Thigh.L")
    MCH_SWITCH_Thigh_Left.head = ORG_Thigh_Left.head
    MCH_SWITCH_Thigh_Left.tail = ORG_Thigh_Left.tail
    MCH_SWITCH_Thigh_Left.parent = MCH_INT_Leg_Socket_Left
    MCH_SWITCH_Thigh_Left.roll = ORG_Thigh_Left.roll
    MCH_SWITCH_Thigh_Left.use_connect = False

    # ---MCH Left Shin---------------------------------------------------------
    MCH_SWITCH_Shin_Left = edit_bones.new("MCH_SWITCH_Shin.L")
    MCH_SWITCH_Shin_Left.head = ORG_Shin_Left.head
    MCH_SWITCH_Shin_Left.tail = ORG_Shin_Left.tail
    MCH_SWITCH_Shin_Left.parent = MCH_SWITCH_Thigh_Left
    MCH_SWITCH_Shin_Left.roll = ORG_Shin_Left.roll
    MCH_SWITCH_Shin_Left.use_connect = True

    # ---MCH Left Foot---------------------------------------------------------
    MCH_SWITCH_Foot_Left = edit_bones.new("MCH_SWITCH_Foot.L")
    MCH_SWITCH_Foot_Left.head = ORG_Foot_Left.head
    MCH_SWITCH_Foot_Left.tail = ORG_Foot_Left.tail
    MCH_SWITCH_Foot_Left.parent = MCH_SWITCH_Shin_Left
    MCH_SWITCH_Foot_Left.roll = ORG_Foot_Left.roll 
    MCH_SWITCH_Foot_Left.use_connect = True

    # ---MCH Left Toe---------------------------------------------------------
    MCH_SWITCH_Toe_Left = edit_bones.new("MCH_SWITCH_Toe.L")
    MCH_SWITCH_Toe_Left.head = ORG_Toe_Left.head
    MCH_SWITCH_Toe_Left.tail = ORG_Toe_Left.tail
    MCH_SWITCH_Toe_Left.parent = MCH_SWITCH_Foot_Left
    MCH_SWITCH_Toe_Left.roll = ORG_Toe_Left.roll 
    MCH_SWITCH_Toe_Left.use_connect = True

    # ==========================--------- FOOT RIG ------------------==============================

    # ---IK Master Parent for a switch constraint to root or hips ---------------------------------------------------------
    MCH_Parent_Foot_IK_Master_Left = edit_bones.new("MCH_Parent_Foot_IK_Master.L")
    MCH_Parent_Foot_IK_Master_Left.head = Vector((ORG_Toe_Left.head.x,ORG_Toe_Left.head.y ,0))
    MCH_Parent_Foot_IK_Master_Left.tail = Vector((ORG_Toe_Left.head.x, MCH_Heel_Left.head.y + 0.04 ,0))
    MCH_Parent_Foot_IK_Master_Left.use_connect = False
    MCH_Parent_Foot_IK_Master_Left.length *= 0.6

    # ---IK Master Left Foot Control ---------------------------------------------------------
    WGT_Foot_IK_Master_Left = edit_bones.new("WGT_Foot_IK_Master.L")
    WGT_Foot_IK_Master_Left.head = Vector((ORG_Toe_Left.head.x,ORG_Toe_Left.head.y ,0))
    WGT_Foot_IK_Master_Left.tail = Vector((ORG_Toe_Left.head.x, MCH_Heel_Left.head.y + 0.04 ,0))
    WGT_Foot_IK_Master_Left.parent = MCH_Parent_Foot_IK_Master_Left
    WGT_Foot_IK_Master_Left.use_connect = False
    

    

    # ---MCH Foot Roll - Left ---------------------------------------------------------
    MCH_Foot_Roll_Left = edit_bones.new("MCH_Foot_Roll.L")
    MCH_Foot_Roll_Left.head = ORG_Toe_Left.head
    MCH_Foot_Roll_Left.tail = MCH_Heel_Left.head
    MCH_Foot_Roll_Left.parent = MCH_Heel_Left
    MCH_Foot_Roll_Left.align_roll(Vector((0.0,0.0,1.0))) #--- reminder this recalculate bone roll global z+
    MCH_Foot_Roll_Left.use_connect = False

    # ---MCH Foot Roll - Left ---------------------------------------------------------
    WGT_Foot_Roll_Left = edit_bones.new("WGT_Foot_Roll.L")
    WGT_Foot_Roll_Left.head = MCH_Heel_Left.head + Vector((0.0,0.1,0.0))
    WGT_Foot_Roll_Left.tail = MCH_Heel_Left.tail + Vector((0.0,0.1,0.0))
    WGT_Foot_Roll_Left.parent = WGT_Foot_IK_Master_Left
    WGT_Foot_Roll_Left.use_connect = False

    # parenting now that we have the roll
    MCH_Foot_Bank_01_Left.parent = MCH_Foot_Roll_Left
    MCH_Foot_Bank_02_Left.parent = MCH_Foot_Bank_01_Left
    MCH_Heel_Left.parent = WGT_Foot_IK_Master_Left
    

    # ============================= MCH TWEAK CHAIN ============================================================================================================
    # --- Left Thigh Tweak SCALE COMPENSATION CORRECTION ---------------------------------------------------------
    MCH_Thigh_Tweak_Scale_Compensation_Left = edit_bones.new(
        "MCH_Thigh_Tweak_Scale_Compensation.L"
    )
    MCH_Thigh_Tweak_Scale_Compensation_Left.head = ORG_Thigh_Left.head
    MCH_Thigh_Tweak_Scale_Compensation_Left.tail = ORG_Thigh_Left.tail
    MCH_Thigh_Tweak_Scale_Compensation_Left.parent = MCH_SWITCH_Thigh_Left
    MCH_Thigh_Tweak_Scale_Compensation_Left.roll = ORG_Thigh_Left.roll 
    MCH_Thigh_Tweak_Scale_Compensation_Left.use_connect = False
    MCH_Thigh_Tweak_Scale_Compensation_Left.length *= 0.25

    # ---TWEAK MCH Left Thigh---------------------------------------------------------
    Thigh_Tweak_Left = edit_bones.new("Thigh_Tweak.L")
    Thigh_Tweak_Left.head = ORG_Thigh_Left.head
    Thigh_Tweak_Left.tail = ORG_Thigh_Left.tail
    Thigh_Tweak_Left.parent = MCH_Thigh_Tweak_Scale_Compensation_Left
    Thigh_Tweak_Left.roll = ORG_Thigh_Left.roll 
    Thigh_Tweak_Left.use_connect = False
    Thigh_Tweak_Left.length *= 0.5

    # --- TWEAK MCH Left Shin Tweak SCALE COMPENSATION CORRECTION---------------------------------------------------------
    MCH_Shin_Tweak_Scale_Compensation_Left = edit_bones.new(
        "MCH_Shin_Tweak_Scale_Compensation.L"
    )
    MCH_Shin_Tweak_Scale_Compensation_Left.head = ORG_Shin_Left.head
    MCH_Shin_Tweak_Scale_Compensation_Left.tail = ORG_Shin_Left.tail
    MCH_Shin_Tweak_Scale_Compensation_Left.parent = MCH_SWITCH_Shin_Left
    MCH_Shin_Tweak_Scale_Compensation_Left.roll = ORG_Shin_Left.roll 
    MCH_Shin_Tweak_Scale_Compensation_Left.use_connect = False
    MCH_Shin_Tweak_Scale_Compensation_Left.length *= 0.25

    # --- TWEAK MCH Left Shin ---------------------------------------------------------
    Shin_Tweak_Left = edit_bones.new("Shin_Tweak.L")
    Shin_Tweak_Left.head = ORG_Shin_Left.head
    Shin_Tweak_Left.tail = ORG_Shin_Left.tail
    Shin_Tweak_Left.parent = MCH_Shin_Tweak_Scale_Compensation_Left
    Shin_Tweak_Left.roll = ORG_Shin_Left.roll 
    Shin_Tweak_Left.use_connect = False
    Shin_Tweak_Left.length *= 0.5

    # --- TWEAK MCH Left Foot ---------------------------------------------------------
    Foot_Tweak_Left = edit_bones.new("Foot_Tweak.L")
    Foot_Tweak_Left.head = ORG_Foot_Left.head
    Foot_Tweak_Left.tail = ORG_Foot_Left.tail
    Foot_Tweak_Left.parent = MCH_SWITCH_Foot_Left
    Foot_Tweak_Left.roll = ORG_Foot_Left.roll 
    Foot_Tweak_Left.use_connect = False
    Foot_Tweak_Left.length *= 0.5

    # --- TWEAK MCH Left Toe  ---------------------------------------------------------
    Toe_Tweak_Left = edit_bones.new("Toe_Tweak.L")
    Toe_Tweak_Left.head = ORG_Toe_Left.head
    Toe_Tweak_Left.tail = ORG_Toe_Left.tail
    Toe_Tweak_Left.parent = MCH_SWITCH_Toe_Left
    Toe_Tweak_Left.roll = ORG_Toe_Left.roll 
    Toe_Tweak_Left.use_connect = False
    Toe_Tweak_Left.length *= 0.5

    # --- TWEAK MCH Left Toe TIP  ---------------------------------------------------------
    Toe_Tip_Tweak_Left = edit_bones.new("Toe_Tip_Tweak.L")
    Toe_Tip_Tweak_Left.head = ORG_Toe_Left.tail
    Toe_Tip_Tweak_Left.tail = ORG_Toe_Left.tail - Vector((0.00, 0.07, 0.0))
    Toe_Tip_Tweak_Left.parent = MCH_SWITCH_Toe_Left
    Toe_Tip_Tweak_Left.roll = ORG_Toe_Left.roll
    Toe_Tip_Tweak_Left.use_connect = False

    # ============================= FK CHAIN ============================================================================================================================
    # ---FK Left Thigh---------------------------------------------------------
    FK_Thigh_Left = edit_bones.new("FK_Thigh.L")
    FK_Thigh_Left.head = ORG_Thigh_Left.head
    FK_Thigh_Left.tail = ORG_Thigh_Left.tail
    FK_Thigh_Left.parent = MCH_INT_Leg_Socket_Left
    FK_Thigh_Left.roll = ORG_Thigh_Left.roll 
    FK_Thigh_Left.use_connect = False

    # ---FK Left Shin---------------------------------------------------------
    FK_Shin_Left = edit_bones.new("FK_Shin.L")
    FK_Shin_Left.head = ORG_Shin_Left.head
    FK_Shin_Left.tail = ORG_Shin_Left.tail
    FK_Shin_Left.parent = FK_Thigh_Left
    FK_Shin_Left.roll = ORG_Shin_Left.roll
    FK_Shin_Left.use_connect = False

    # ---FK Left Foot---------------------------------------------------------
    FK_Foot_Left = edit_bones.new("FK_Foot.L")
    FK_Foot_Left.head = ORG_Foot_Left.head
    FK_Foot_Left.tail = ORG_Foot_Left.tail
    FK_Foot_Left.parent = FK_Shin_Left
    FK_Foot_Left.roll = ORG_Foot_Left.roll
    FK_Foot_Left.use_connect = False

    # ---FK Left Toe---------------------------------------------------------
    FK_Toe_Left = edit_bones.new("FK_Toe.L")
    FK_Toe_Left.head = ORG_Toe_Left.head
    FK_Toe_Left.tail = ORG_Toe_Left.tail
    FK_Toe_Left.parent = FK_Foot_Left
    FK_Toe_Left.roll =  ORG_Toe_Left.roll 
    FK_Toe_Left.use_connect = False

    # ============================= IK CHAIN ============================================================================================================================
    # ---IK Left Thigh---------------------------------------------------------
    IK_Thigh_Left = edit_bones.new("IK_Thigh.L")
    IK_Thigh_Left.head = ORG_Thigh_Left.head
    IK_Thigh_Left.tail = ORG_Thigh_Left.tail
    IK_Thigh_Left.parent = MCH_INT_Leg_Socket_Left
    IK_Thigh_Left.roll = ORG_Thigh_Left.roll 
    IK_Thigh_Left.use_connect = False

    # ---TEMP IK Pole Target base (fastest way to position pole exactly as we need ---------------------------------------------------------
    TEMP_Left_Leg_Pole = edit_bones.new("TEMP_Left_Leg_Pole")
    TEMP_Left_Leg_Pole.head = ORG_Thigh_Left.head + Vector((0.0,-0.4, 0.0))
    TEMP_Left_Leg_Pole.tail = ORG_Thigh_Left.tail + Vector((0.0,-0.4, 0.0))
    TEMP_Left_Leg_Pole.roll = ORG_Thigh_Left.roll 
    TEMP_Left_Leg_Pole.use_connect = False

    # ---IK Pole Target left leg ---------------------------------------------------------
    IK_Pole_Left = edit_bones.new("WGT_IK_Pole.L")
    IK_Pole_Left.head = TEMP_Left_Leg_Pole.tail 
    IK_Pole_Left.tail = TEMP_Left_Leg_Pole.tail + Vector((0.0,0.075, 0.0))
    IK_Pole_Left.align_roll(Vector((0.0,0.0,1.0)))
    IK_Pole_Left.parent = WGT_Foot_IK_Master_Left
    IK_Pole_Left.use_connect = False

    # TEMP_Left_Leg_Pole was only needed to derive the pole position/roll above; discard it now.     
    edit_bones.remove(TEMP_Left_Leg_Pole)

    # ---IK Pole Target Visualization bone ---------------------------------------------------------
    VIS_IK_Pole_Left = edit_bones.new("VIS_IK_Pole.L")
    VIS_IK_Pole_Left.head = IK_Thigh_Left.tail
    VIS_IK_Pole_Left.tail = IK_Pole_Left.head
    VIS_IK_Pole_Left.parent = IK_Thigh_Left
    VIS_IK_Pole_Left.use_connect = False

    # ---IK Left Shin---------------------------------------------------------
    IK_Shin_Left = edit_bones.new("IK_Shin.L")
    IK_Shin_Left.head = ORG_Shin_Left.head
    IK_Shin_Left.tail = ORG_Shin_Left.tail
    IK_Shin_Left.parent = IK_Thigh_Left
    IK_Shin_Left.roll = ORG_Shin_Left.roll 
    IK_Shin_Left.use_connect = True

    # ---IK Left Foot---------------------------------------------------------
    IK_Foot_Left = edit_bones.new("IK_Foot.L")
    IK_Foot_Left.head = ORG_Foot_Left.head
    IK_Foot_Left.tail = ORG_Foot_Left.tail
    IK_Foot_Left.parent = MCH_Foot_Bank_02_Left
    IK_Foot_Left.roll = ORG_Foot_Left.roll
    IK_Foot_Left.use_connect = False

    # ---IK Left Toe MCH bone---------------------------------------------------------
    MCH_Toe_IK_Left = edit_bones.new("MCH_Toe_IK.L")
    MCH_Toe_IK_Left.head = ORG_Toe_Left.head
    MCH_Toe_IK_Left.tail = ORG_Toe_Left.tail
    MCH_Toe_IK_Left.parent = IK_Foot_Left
    MCH_Toe_IK_Left.roll = MCH_Foot_Roll_Left.roll
    MCH_Toe_IK_Left.use_connect = False
    MCH_Toe_IK_Left.length *= 0.6
    
    # ---IK Left Toe WGT Control ---------------------------------------------------------
    WGT_IK_Toe_Left = edit_bones.new("WGT_IK_Toe.L")
    WGT_IK_Toe_Left.head = ORG_Toe_Left.head
    WGT_IK_Toe_Left.tail = ORG_Toe_Left.tail
    WGT_IK_Toe_Left.parent = MCH_Toe_IK_Left
    WGT_IK_Toe_Left.roll = ORG_Toe_Left.roll 
    WGT_IK_Toe_Left.use_connect = False

    # ------- Final Property Bones ---------------
    WGT_Leg_Properties_Left = edit_bones.new("WGT_Leg_Properties.L")
    WGT_Leg_Properties_Left.head = WGT_Foot_IK_Master_Left.head + Vector((0.0,-0.3,0.0))
    WGT_Leg_Properties_Left.tail = WGT_Foot_IK_Master_Left.head + Vector((0.0,-0.2,0.0))
    WGT_Leg_Properties_Left.parent = WGT_Foot_IK_Master_Left
    WGT_Leg_Properties_Left.use_connect = False

    WGT_Leg_Properties_Controller_Left = edit_bones.new("WGT_Leg_Properties_Controller.L")
    WGT_Leg_Properties_Controller_Left.head = WGT_Leg_Properties_Left.head
    WGT_Leg_Properties_Controller_Left.tail = WGT_Leg_Properties_Left.tail
    WGT_Leg_Properties_Controller_Left.parent = WGT_Leg_Properties_Left
    WGT_Leg_Properties_Controller_Left.use_connect = False
    WGT_Leg_Properties_Controller_Left.length *= 0.4


    

    # =============== Parenting ORG BONES to new appropriate corresponding RIG bone =======================
    # use_connect welds a child's head onto its parent's tail. The ORG bones
    # inherit it from the DEF chain (shin/foot/toe are all connected), so
    # reparenting them would snap each head up to the half-length tweak tail.
    # Clearing it first keeps the offset -- parenting alone never moves a bone.
    ORG_Thigh_Left.use_connect = False
    ORG_Thigh_Left.parent = Thigh_Tweak_Left
    ORG_Shin_Left.use_connect = False
    ORG_Shin_Left.parent = Shin_Tweak_Left
    ORG_Foot_Left.use_connect = False
    ORG_Foot_Left.parent = Foot_Tweak_Left
    ORG_Toe_Left.use_connect = False
    ORG_Toe_Left.parent = Toe_Tweak_Left

    # ========================================== ENTERING POSE MODE  ============================================================================
    # ============================================== CONSTRAINTS ============================================================================
    # Constraints hang off pose bones, and everything built above only shows up
    # in armature_obj.pose.bones once edit mode is left -- so the switch has to
    # happen here, after the whole chain exists.
    bpy.ops.object.mode_set(mode="POSE")

    # Root comes from the DEF skeleton, not from this function, so it can be
    # missing if the tools are run out of order.
    if armature_obj.data.bones.get("Root") is None:
        changed.append(
            "Issue: Cannot find ROOT bone, this rig is not ready; cancelling request"
        )
        return changed

    # Every bone below has to be re-fetched from pose.bones by name. The
    # EditBone variables built further up are dangling pointers now -- leaving
    # edit mode frees the edit-bone structs, and touching one crashes Blender
    # outright rather than raising. Constraints only exist on pose bones anyway.
    pose_bones = armature_obj.pose.bones

    #------- Set rotation for certain foot bones to XYZ Euler (only needs these rotatin axes) --------------------
    for name in ("MCH_Foot_Bank_01.L","MCH_Foot_Bank_02.L","MCH_Foot_Roll.L","MCH_Heel.L","WGT_Foot_Roll.L"):
        pb = pose_bones.get(name)
        if pb is not None:
            pb.rotation_mode = "XYZ"

    # --- location constraints -----------------------------------------------------------------------------------------
    copy_leg_intermediary_socket_location = pose_bones["MCH_INT_Leg_Socket.L"].constraints.new("COPY_LOCATION")

    # --- scale constraints -----------------------------------------------------------------------------------------
    copy_thigh_scale = pose_bones["MCH_Thigh_Tweak_Scale_Compensation.L"].constraints.new("COPY_SCALE")
    copy_shin_scale = pose_bones["MCH_Shin_Tweak_Scale_Compensation.L"].constraints.new("COPY_SCALE")
    copy_leg_intermediary_socket_scale = pose_bones["MCH_INT_Leg_Socket.L"].constraints.new("COPY_SCALE")

    # --- rotation constraints -------------------------------------------------------------------------------------
    copy_leg_intermediary_socket_rotation = pose_bones["MCH_INT_Leg_Socket.L"].constraints.new("COPY_ROTATION")
    copy_leg_intermediary_socket_rotation.name = "ROTATION_FOLLOW"

    copy_heel_rotation = pose_bones["MCH_Heel.L"].constraints.new("COPY_ROTATION")
    copy_heel_rotation.target_space = copy_heel_rotation.owner_space = "LOCAL"
    copy_heel_rotation.use_y = copy_heel_rotation.use_z = False # <------- only follow x axis

    copy_foot_roll_rotation = pose_bones["MCH_Foot_Roll.L"].constraints.new("COPY_ROTATION")
    copy_foot_roll_rotation.target_space = copy_foot_roll_rotation.owner_space = "LOCAL"
    copy_foot_roll_rotation.use_y = copy_foot_roll_rotation.use_z = False # <------- only follow x axis

    copy_foot_bank_01_rotation = pose_bones["MCH_Foot_Bank_01.L"].constraints.new("COPY_ROTATION")
    copy_foot_bank_01_rotation.target_space = copy_foot_bank_01_rotation.owner_space = "LOCAL"
    copy_foot_bank_01_rotation.use_y = copy_foot_bank_01_rotation.use_x = False # <------- only follow z axis

    copy_foot_bank_02_rotation = pose_bones["MCH_Foot_Bank_02.L"].constraints.new("COPY_ROTATION")
    copy_foot_bank_02_rotation.target_space = copy_foot_bank_02_rotation.owner_space = "LOCAL"
    copy_foot_bank_02_rotation.use_y = copy_foot_bank_02_rotation.use_x = False # <------- only follow z axis

    copy_toe_rotation = pose_bones["MCH_Toe_IK.L"].constraints.new("COPY_ROTATION")
    copy_toe_rotation.target_space = copy_toe_rotation.owner_space = "LOCAL"
    copy_toe_rotation.use_y = copy_toe_rotation.use_z = False # <------- only follow x axis

    

    # --- limit rotation constraints -------------------------------------------------------------------------------------
    # --- heel limits ----
    limit_heel_rotation = pose_bones["MCH_Heel.L"].constraints.new("LIMIT_ROTATION")
    limit_heel_rotation.target_space = limit_heel_rotation.owner_space = "LOCAL"
    limit_heel_rotation.use_limit_x = True
    limit_heel_rotation.min_x = math.radians(-100)
    limit_heel_rotation.max_x = math.radians(0)
    # --- foot roll limits ----
    limit_foot_roll_rotation = pose_bones["MCH_Foot_Roll.L"].constraints.new("LIMIT_ROTATION")
    limit_foot_roll_rotation.target_space = limit_foot_roll_rotation.owner_space = "LOCAL"
    limit_foot_roll_rotation.use_limit_x = True
    limit_foot_roll_rotation.min_x = math.radians(0)
    limit_foot_roll_rotation.max_x = math.radians(180)
    # --- foot bank 01 limits ----
    limit_foot_bank_01_rotation = pose_bones["MCH_Foot_Bank_01.L"].constraints.new("LIMIT_ROTATION")
    limit_foot_bank_01_rotation.target_space = limit_foot_bank_01_rotation.owner_space = "LOCAL"
    limit_foot_bank_01_rotation.use_limit_z = True
    limit_foot_bank_01_rotation.min_z = math.radians(0)
    limit_foot_bank_01_rotation.max_z = math.radians(180)
    # --- foot bank 02 limits ----
    limit_foot_bank_02_rotation = pose_bones["MCH_Foot_Bank_02.L"].constraints.new("LIMIT_ROTATION")
    limit_foot_bank_02_rotation.target_space = limit_foot_bank_02_rotation.owner_space = "LOCAL"
    limit_foot_bank_02_rotation.use_limit_z = True
    limit_foot_bank_02_rotation.min_z = math.radians(-180)
    limit_foot_bank_02_rotation.max_z = math.radians(0)

    # --- transform constraints -------------------------------------------------------------------------------------
    # --- FK leg copy transform constraints ---------------------------------
    copy_FK_thigh_transform = pose_bones["MCH_SWITCH_Thigh.L"].constraints.new("COPY_TRANSFORMS")
    copy_FK_thigh_transform.name = "FK_Copy_Transform"
    copy_FK_shin_transform = pose_bones["MCH_SWITCH_Shin.L"].constraints.new("COPY_TRANSFORMS")
    copy_FK_shin_transform.name = "FK_Copy_Transform"
    copy_FK_foot_transform = pose_bones["MCH_SWITCH_Foot.L"].constraints.new("COPY_TRANSFORMS")
    copy_FK_foot_transform.name = "FK_Copy_Transform"
    copy_FK_toe_transform = pose_bones["MCH_SWITCH_Toe.L"].constraints.new("COPY_TRANSFORMS")
    copy_FK_toe_transform.name = "FK_Copy_Transform"
    # --- IK leg copy transform constraints ---------------------------------
    copy_IK_thigh_transform = pose_bones["MCH_SWITCH_Thigh.L"].constraints.new("COPY_TRANSFORMS")
    copy_IK_thigh_transform.name = "IK_Transform_Influence"
    copy_IK_shin_transform = pose_bones["MCH_SWITCH_Shin.L"].constraints.new("COPY_TRANSFORMS")
    copy_IK_shin_transform.name = "IK_Transform_Influence"
    copy_IK_foot_transform = pose_bones["MCH_SWITCH_Foot.L"].constraints.new("COPY_TRANSFORMS")
    copy_IK_foot_transform.name = "IK_Transform_Influence"
    copy_IK_toe_transform = pose_bones["MCH_SWITCH_Toe.L"].constraints.new("COPY_TRANSFORMS")
    copy_IK_toe_transform.name = "IK_Transform_Influence"

    # --- limit location constraints -------------------------------------------------------------------------------------
    # --- leg properties control limits ----
    limit_location_properties_controller = pose_bones["WGT_Leg_Properties_Controller.L"].constraints.new("LIMIT_LOCATION")
    limit_location_properties_controller.owner_space = "LOCAL"
    limit_location_properties_controller.use_min_x = limit_location_properties_controller.use_min_y = limit_location_properties_controller.use_min_z = True
    limit_location_properties_controller.use_max_x = limit_location_properties_controller.use_max_y = limit_location_properties_controller.use_max_z = True
    limit_location_properties_controller.use_transform_limit = True
    limit_location_properties_controller.min_x = limit_location_properties_controller.min_y = limit_location_properties_controller.min_z = 0
    max_distance_for_controller  = 0.1
    limit_location_properties_controller.max_x = limit_location_properties_controller.max_y = limit_location_properties_controller.max_z = max_distance_for_controller

    # --- Armature constraints -------------------------------------------------------------------------------------
    Armature_IK_Parent = pose_bones["MCH_Parent_Foot_IK_Master.L"].constraints.new("ARMATURE")

    # --- IK - proper inverse kinematic constraints for the IK leg ---------------------------------
    shin_IK = pose_bones["IK_Shin.L"].constraints.new("IK")
    pose_bones["IK_Shin.L"].ik_stretch = 0.01
    pose_bones["IK_Thigh.L"].ik_stretch = 0.01
    shin_IK.chain_count = 2

    # ----- stretch to constraints -------------------------------------------------------------------------------------

    stretch_toe = pose_bones["ORG_Toe.L"].constraints.new("STRETCH_TO")
    stretch_foot = pose_bones["ORG_Foot.L"].constraints.new("STRETCH_TO")
    stretch_shin = pose_bones["ORG_Shin.L"].constraints.new("STRETCH_TO")
    stretch_thigh = pose_bones["ORG_Thigh.L"].constraints.new("STRETCH_TO")
    stretch_pole_visualizer = pose_bones["VIS_IK_Pole.L"].constraints.new("STRETCH_TO")

    # -------------------------------- ASSIGNING TARGETS AND SUBTARGETS -------------------------------------------------------------------------------------
    # Chaining is fine here -- every constraint points at the same armature.
    # subtarget is the part that cannot be chained: it differs per constraint.
    # ------------- scale targets -------------
    copy_thigh_scale.target = copy_shin_scale.target  = copy_leg_intermediary_socket_scale.target  = armature_obj
    # ------------- stretch targets -------------
    stretch_toe.target = stretch_foot.target = stretch_shin.target = stretch_thigh.target = stretch_pole_visualizer.target = armature_obj
    # -------------rotation targets -------------
    copy_heel_rotation.target = copy_leg_intermediary_socket_rotation.target = armature_obj
    copy_foot_roll_rotation.target = copy_foot_bank_01_rotation.target = copy_foot_bank_02_rotation.target = copy_toe_rotation.target = armature_obj
    
    # ------------- location targets -------------
    copy_leg_intermediary_socket_location.target = armature_obj
    # -------------transform targets -------------
    copy_FK_thigh_transform.target = copy_FK_shin_transform.target = copy_FK_foot_transform.target = copy_FK_toe_transform.target = copy_IK_thigh_transform.target = copy_IK_shin_transform.target = copy_IK_foot_transform.target = copy_IK_toe_transform.target = armature_obj
    # -------------ik targets -------------
    shin_IK.target = shin_IK.pole_target = armature_obj
    # -------------armature targets -------------
    Armature_IK_Parent_root_target = Armature_IK_Parent.targets.new()
    Armature_IK_Parent_root_target.target = armature_obj
    Armature_IK_Parent_root_target.subtarget = "Root"
    Armature_IK_Parent_root_target.weight = 0.0

    Armature_IK_Parent_hip_target = Armature_IK_Parent.targets.new()
    Armature_IK_Parent_hip_target.target = armature_obj
    Armature_IK_Parent_hip_target.subtarget = "ORG_Hips"
    Armature_IK_Parent_hip_target.weight = 0.0


    # ----------------------- all subtargets --------------------------------
    copy_leg_intermediary_socket_location.subtarget = "MCH_Leg_Socket.L"

    copy_leg_intermediary_socket_rotation.subtarget = "MCH_Leg_Socket.L"
    copy_toe_rotation.subtarget = "MCH_Foot_Roll.L"
    copy_heel_rotation.subtarget = copy_foot_roll_rotation.subtarget = copy_foot_bank_01_rotation.subtarget = copy_foot_bank_02_rotation.subtarget= "WGT_Foot_Roll.L"

    copy_leg_intermediary_socket_scale.subtarget = "MCH_Leg_Socket.L"
    copy_thigh_scale.subtarget = copy_shin_scale.subtarget = "Root"

    stretch_toe.subtarget = "Toe_Tip_Tweak.L"
    stretch_foot.subtarget = "Toe_Tweak.L"
    stretch_shin.subtarget = "Foot_Tweak.L"
    stretch_thigh.subtarget = "Shin_Tweak.L"
    stretch_pole_visualizer.subtarget = "WGT_IK_Pole.L"

    copy_FK_thigh_transform.subtarget = "FK_Thigh.L"
    copy_FK_shin_transform.subtarget = "FK_Shin.L"
    copy_FK_foot_transform.subtarget = "FK_Foot.L"
    copy_FK_toe_transform.subtarget = "FK_Toe.L"

    copy_IK_thigh_transform.subtarget = "IK_Thigh.L"
    copy_IK_shin_transform.subtarget = "IK_Shin.L"
    copy_IK_foot_transform.subtarget = "IK_Foot.L"
    copy_IK_toe_transform.subtarget = "WGT_IK_Toe.L"

    shin_IK.subtarget = "IK_Foot.L"
    shin_IK.pole_subtarget = "WGT_IK_Pole.L"

    # ========================================================================================================================
    # -------------------------------  DRIVERS -------------------------------------------------------------------------------
    # ========================================================================================================================
    # --- IK influence follows the properties controller slider ----
    # The controller slides from 0 to max_distance_for_controller on X -- that
    # is what the LIMIT_LOCATION above pins it to -- so dividing by that max
    # normalizes the slide into the 0..1 range influence expects. The whole IK
    # chain reads the same slider, so one expression covers all four.
    ik_switch_expression = f"slider_x / {max_distance_for_controller}"
    for ik_constraint in (
        copy_IK_thigh_transform,
        copy_IK_shin_transform,
        copy_IK_foot_transform,
        copy_IK_toe_transform,
    ):
        add_slider_driver(ik_constraint, armature_obj, ik_switch_expression, axis="X")

    # ---------- follow hip rotation slider ----------------
    follow_rotation_expression = f"slider_y / {max_distance_for_controller}"
    add_slider_driver(copy_leg_intermediary_socket_rotation, armature_obj, follow_rotation_expression, axis="Y")

    # ---------- IK follow hip or root ----------------
    # Root and ORG_Hips are the two blend targets on the same armature
    # constraint, so their weights have to be complementary -- Root rises
    # with the slider while ORG_Hips falls, keeping the blend at 1.0 total.
    ik_follow_hip_or_root_expression = f"slider_z / {max_distance_for_controller}"
    add_slider_driver(
        Armature_IK_Parent_root_target,
        armature_obj,
        ik_follow_hip_or_root_expression,
        axis="Z",
        data_path="weight",
    )
    add_slider_driver(
        Armature_IK_Parent_hip_target,
        armature_obj,
        f"1 - ({ik_follow_hip_or_root_expression})",
        axis="Z",
        data_path="weight",
    )

    # ========================================================================================================================
    # -------------------------------  WIDGET ASSIGNMENTS --------------------------------------------------------------------
    # ========================================================================================================================
    # --------- IK Pole Line Visualizer ----------
    widgets.assign_widget(
        pose_bones["VIS_IK_Pole.L"],
        "VIS_Line",
        wire_width=2,
        color="THEME07",
    )

    # --------- IK Pole Controller ----------
    widgets.assign_widget(
        pose_bones["WGT_IK_Pole.L"],
        "WGT_Bottom_Face_Centered_Pyramid",
        scale_y=-1,
        wire_width=2,
        color="THEME07",
    )

    # --------- Left Leg IK Master ----------
    widgets.assign_widget(
        pose_bones["WGT_Foot_IK_Master.L"],
        "WGT_Bottom_Face_Centered_Cube",
        scale_y=0.5,
        rotation_x=90,
        wire_width=2,
        color="THEME04",
    )
    # --------- Left Leg IK Toe ----------

    # --------- Left Leg IK Roll ----------
    widgets.assign_widget(
        pose_bones["WGT_Foot_Roll.L"],
        "WGT_Curved_Quadruple_Arrows",
        wire_width=2,
        color="THEME04",
    )

    # --------- Left Leg FK Chain ----------
    FK_LEG_WIDGET_SIZE = 0.25  # armature units, tune to taste

    for name in ("FK_Thigh.L", "FK_Shin.L", "FK_Foot.L","FK_Toe.L"):
        widgets.assign_widget(
            pose_bones[name],
            "WGT_Circle_Centered",
            scale_x=FK_LEG_WIDGET_SIZE,
            scale_y=FK_LEG_WIDGET_SIZE,
            scale_z=FK_LEG_WIDGET_SIZE,
            use_bone_size=False,
            color="THEME09",
        )

    # --------- Left Tweakers --------------
    TWEAK_WIDGET_SIZE = 0.05  # armature units, tune to taste

    for name in ("Thigh_Tweak.L", "Shin_Tweak.L", "Foot_Tweak.L",
                "Toe_Tweak.L", "Toe_Tip_Tweak.L"):
        widgets.assign_widget(
            pose_bones[name],
            "WGT_Centered_IcoSphere",
            scale_x=TWEAK_WIDGET_SIZE,
            scale_y=TWEAK_WIDGET_SIZE,
            scale_z=TWEAK_WIDGET_SIZE,
            use_bone_size=False,
            color="THEME09",
        )

    # --------- Properties Container ----------
    widgets.assign_widget(
        pose_bones["WGT_Leg_Properties.L"],
        "WGT_Left_Foot_Properties",
        wire_width=1,
        color="THEME04",
    )

    # --------- Properties Controller ----------
    widgets.assign_widget(
        pose_bones["WGT_Leg_Properties_Controller.L"],
        "WGT_Centered_IcoSphere",
        wire_width=1,
        color="THEME07",
    )

    changed.append("copy scale on the thigh/shin compensation bones -> Root")
    changed.append("stretch-to on the shin/foot/toe/toe-tip tweaks")
    changed.append("MCH legs added")

    return changed


def mirror_deformation_skeleton(context, armature_obj=None):
    """Mirror every ".L" bone onto the right side. Returns a list of what changed.

    symmetrize does the whole job: the ".L" -> ".R" rename, negating X on
    head/tail/roll, and re-parenting each new bone to its mirrored parent --
    falling back to the original parent when that parent has no mirror, which
    is what lands DEF_Shoulder.R back on DEF_Chest instead of on itself.

    Pass armature_obj when chaining straight off create_deformation_skeleton;
    leave it out to mirror whatever armature is currently active.
    """
    changed = []

    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    # edit_bones is only populated in edit mode, so we have to be in it whether
    # or not the caller already was.
    if armature_obj.mode != "EDIT":
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = armature_obj.data.edit_bones
    selected = 0
    for bone in edit_bones:
        is_left = bone.name.endswith(".L")
        bone.select = bone.select_head = bone.select_tail = is_left
        selected += is_left

    # return empty changed [] if there are no .L bones
    if selected == 0:
        return changed

    bone_count_before_symetrize = len(edit_bones)
    bpy.ops.armature.symmetrize(direction="POSITIVE_X")
    bones_created = len(armature_obj.data.edit_bones) - bone_count_before_symetrize

    if bones_created:
        changed.append(
            f"mirrored {bones_created} bone{'s' if bones_created > 1 else ''} to the right side"
        )

    return changed


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

        self.report({"INFO"}, f"Built {armature_obj.name}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Mirror .L to .R" BUTTON IS CLICKED =========
class EMANATE_OT_mirror_def_skeleton(bpy.types.Operator):
    bl_idname = NAMES_DEF_MIRROR.operator_idname
    bl_label = NAMES_DEF_MIRROR.label
    bl_description = NAMES_DEF_MIRROR.description
    bl_options = {"REGISTER", "UNDO"}

    # Greys the button out unless there is an armature to act on, so the user
    # gets a disabled button instead of an error after the fact.
    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context):
        # context.object is the active object -- the one the header and the
        # properties editor are pointing at, which is what the user thinks of
        # as "the selected armature".
        armature_obj = context.object

        # poll() covers the button, but an operator can still be called from a
        # script or the search menu, where poll is not guaranteed to have run.
        if armature_obj is None or armature_obj.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature first")
            return {"CANCELLED"}

        changed = mirror_deformation_skeleton(context, armature_obj)

        if not changed:
            self.report({"WARNING"}, f"{armature_obj.name} has no .L bones to mirror")
            return {"CANCELLED"}

        for change in changed:
            print(f"[def-mirror] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Generate " BUTTON IS CLICKED =========
class EMANATE_OT_generate_rig(bpy.types.Operator):
    bl_idname = NAMES_MAKE_RIG.operator_idname
    bl_label = NAMES_MAKE_RIG.label
    bl_description = NAMES_MAKE_RIG.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context):
        armature_obj = context.object

        # poll() covers the button, but an operator can still be called from a
        # script or the search menu, where poll is not guaranteed to have run.
        if armature_obj is None or armature_obj.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature first")
            return {"CANCELLED"}

        changed = generate_leg_ik_fk_rig(context, armature_obj)

        if not changed:
            self.report(
                {"WARNING"},
                f"{armature_obj.name} has no ORG_Hips bone -- run the ORG bone "
                f"generator first",
            )
            return {"CANCELLED"}

        for change in changed:
            print(f"[generate-rig] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
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
        layout.operator(NAMES_DEF_MIRROR.operator_idname)
        layout.operator(NAMES_MAKE_RIG.operator_idname)


_classes = (
    EMANATE_OT_pre_rig_initialize,
    EMANATE_OT_make_def_skeleton,
    EMANATE_OT_mirror_def_skeleton,
    EMANATE_OT_generate_rig,
    EMANATE_PT_pre_rig_initialize,
)


def register():
    naming.check_classes(
        (EMANATE_OT_pre_rig_initialize, EMANATE_PT_pre_rig_initialize), NAMES
    )
    naming.check_classes((EMANATE_OT_make_def_skeleton,), NAMES_DEF_SKELETON)
    naming.check_classes((EMANATE_OT_mirror_def_skeleton,), NAMES_DEF_MIRROR)
    naming.check_classes((EMANATE_OT_generate_rig,), NAMES_MAKE_RIG)
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
