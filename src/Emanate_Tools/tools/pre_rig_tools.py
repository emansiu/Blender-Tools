import math

import bpy
from mathutils import Vector

from ..helpers import bone_collections, deform_cleanup
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

NAMES_ORG_BONES = naming.register_tool(
    "org_bone_generator",
    label="generate ORG bones",
    owner=__name__,
    description="Creates ORG bones and assigns copy transform constraints to DEF bones",
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
    DEF_Forearm_left.use_connect = True
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


# ---------------------------------------------------------------------------
# ORG bone generation -- mirrors every DEF_ bone as an ORG_ bone and wires a
# copy-transforms constraint from each DEF bone back onto its ORG twin.
# ---------------------------------------------------------------------------

# ------ Naming convention this tool works to ------------------------------
DEF_PREFIX = deform_cleanup.DEF_PREFIX
ORG_PREFIX = "ORG_"

# Naming the constraint lets a second run recognise its own work instead of
# stacking a duplicate constraint on every DEF bone.
CONSTRAINT_NAME = "ORG Copy Transforms"
CONSTRAINT_TYPE = 'COPY_TRANSFORMS'

# Bone collections the two sets get sorted into.
DEFORM_COLLECTION = "DEFORMATION"
ORIGINAL_COLLECTION = "ORIGINAL"

# DEF bones built as one piece that have to end up as two halves before the
# ORG pass runs, keyed by the whole bone's name: (root half, tip half).
BONES_TO_SUBDIVIDE = {
    "DEF_Forearm.L": ("DEF_Forearm_Proximal.L", "DEF_Forearm_Distal.L"),
}
# ---------------------------------------------------------------------------


def org_name_for(def_bone_name):
    """DEF_base -> ORG_base. Only the prefix changes; the rest is untouched."""
    return ORG_PREFIX + def_bone_name[len(DEF_PREFIX):]


def subdivide_def_bones(armature_obj):
    """Split each bone in BONES_TO_SUBDIVIDE in two. Must be called in EDIT mode.

    The whole bone does not survive: subdivide leaves the root half under the
    original name and a new tip half carrying the children, and both are then
    renamed. Returns the list of names created.
    """
    edit_bones = armature_obj.data.edit_bones
    created = []

    for bone_name, (proximal_name, distal_name) in BONES_TO_SUBDIVIDE.items():
        source = edit_bones.get(bone_name)
        if source is None:
            # Either the rig never had it or a previous run already split it.
            continue

        for bone in edit_bones:
            bone.select = bone.select_head = bone.select_tail = False
        source.select = source.select_head = source.select_tail = True
        edit_bones.active = source

        before = {bone.name for bone in edit_bones}
        bpy.ops.armature.subdivide(number_cuts=1)
        new_names = [bone.name for bone in edit_bones if bone.name not in before]
        if not new_names:
            continue

        # Subdivide keeps the root half under the original name and gives the
        # half towards the tail -- the one that carries the children -- a name
        # of its own choosing, so that is the one to call distal.
        edit_bones[bone_name].name = proximal_name
        edit_bones[new_names[0]].name = distal_name
        created += [proximal_name, distal_name]

    return created


def create_org_bones(armature_obj):
    """Mirror every DEF_ bone as an ORG_ bone. Must be called in EDIT mode.

    Returns (pairs, created, reused) where pairs is a list of
    (def_name, org_name) covering every DEF bone, whether or not its ORG
    counterpart had to be built this run.
    """
    edit_bones = armature_obj.data.edit_bones

    # Split first so the halves are picked up by the sweep below and get ORG
    # twins of their own.
    subdivide_def_bones(armature_obj)

    source_bones = [eb for eb in edit_bones if eb.name.startswith(DEF_PREFIX)]

    pairs = []
    created = []
    reused = []

    # --- pass one: create the bones -------------------------------------
    # Parenting is deferred to pass two because a bone's ORG parent may not
    # exist yet when the bone itself is created.
    for source in source_bones:
        org_name = org_name_for(source.name)
        pairs.append((source.name, org_name))

        if org_name in edit_bones:
            # Already generated by a previous run. Leave it as the user left
            # it -- overwriting would throw away any edits they made.
            reused.append(org_name)
            continue

        new_bone = edit_bones.new(org_name)
        new_bone.head = source.head
        new_bone.tail = source.tail
        new_bone.roll = source.roll
        new_bone.use_deform = False
        new_bone.inherit_scale = source.inherit_scale

        # Deliberately NOT copying the source bone's collection membership:
        # organize_bone_collections() below files this bone under ORIGINAL,
        # and inheriting DEF's membership would drag it into the hidden
        # DEFORMATION collection too.
        created.append(org_name)

    # --- pass two: rebuild the hierarchy --------------------------------
    def_to_org = dict(pairs)

    for def_name, org_name in pairs:
        if org_name not in created:
            continue

        source_parent = edit_bones[def_name].parent
        if source_parent is None:
            continue

        # A DEF parent maps to its ORG twin, so the ORG chain stands alone.
        # Any other parent (a control bone, say) is kept as-is, which is what
        # Blender's own duplicate does.
        parent_name = def_to_org.get(source_parent.name, source_parent.name)
        org_bone = edit_bones[org_name]
        org_bone.parent = edit_bones[parent_name]
        org_bone.use_connect = edit_bones[def_name].use_connect

    return pairs, created, reused


def organize_org_bone_collections(armature_obj, pairs):
    """File DEF bones under DEFORMATION (hidden) and ORG under ORIGINAL.

    Must be called in EDIT mode -- it works through edit_bones, which is the
    only view of the bones that is valid there.

    Returns a list of description strings.
    """
    armature = armature_obj.data
    changes = []

    deform, was_created = bone_collections.get_or_create_collection(armature, DEFORM_COLLECTION)
    if was_created:
        changes.append(f"created collection {DEFORM_COLLECTION}")
    moved = bone_collections.move_bones_to_collection(armature, [d for d, _ in pairs], deform)
    changes.append(f"{moved} bone(s) -> {DEFORM_COLLECTION} (hidden)")
    deform.is_visible = False

    original, was_created = bone_collections.get_or_create_collection(armature, ORIGINAL_COLLECTION)
    if was_created:
        changes.append(f"created collection {ORIGINAL_COLLECTION}")
    moved = bone_collections.move_bones_to_collection(armature, [o for _, o in pairs], original)
    changes.append(f"{moved} bone(s) -> {ORIGINAL_COLLECTION} (visible)")
    original.is_visible = True

    return changes


def add_copy_transforms(armature_obj, pairs):
    """Constrain each DEF bone to its ORG bone. Must be called in POSE mode.

    Returns (added, skipped) as lists of DEF bone names.
    """
    added = []
    skipped = []

    for def_name, org_name in pairs:
        pose_bone = armature_obj.pose.bones.get(def_name)
        if pose_bone is None:
            continue

        # Re-runs must not stack constraints. Match on what the constraint
        # does (type + target) rather than on its name, so a renamed one is
        # still recognised.
        already_there = any(
            con.type == CONSTRAINT_TYPE
            and con.target == armature_obj
            and con.subtarget == org_name
            for con in pose_bone.constraints
        )
        if already_there:
            skipped.append(def_name)
            continue

        constraint = pose_bone.constraints.new(CONSTRAINT_TYPE)
        constraint.name = CONSTRAINT_NAME
        constraint.target = armature_obj
        constraint.subtarget = org_name
        added.append(def_name)

    return added, skipped


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


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Generate ORG Bones" BUTTON IS CLICKED =========
class EMANATE_OT_org_bone_generator(bpy.types.Operator):

    bl_idname = NAMES_ORG_BONES.operator_idname
    bl_label = NAMES_ORG_BONES.label
    bl_description = NAMES_ORG_BONES.description
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature_obj = context.active_object
        starting_mode = armature_obj.mode

        bpy.ops.object.mode_set(mode='EDIT')
        pairs, created, reused = create_org_bones(armature_obj)

        if not pairs:
            bpy.ops.object.mode_set(mode=starting_mode)
            self.report({'WARNING'}, f"No bones prefixed {DEF_PREFIX} on {armature_obj.name}")
            return {'CANCELLED'}

        # Still in edit mode, which is where collection membership has to be
        # set -- armature.bones is not valid until edit mode is left.
        collection_changes = organize_org_bone_collections(armature_obj, pairs)
        deform_cleanup.sync_deform_flags(armature_obj)

        # Constraints live on pose bones, and pose bones for freshly created
        # edit bones only exist once edit mode has been left.
        bpy.ops.object.mode_set(mode='POSE')
        added, skipped = add_copy_transforms(armature_obj, pairs)

        bpy.ops.object.mode_set(mode=starting_mode)

        for def_name, org_name in pairs:
            print(f"[org-bones] {def_name} -> {org_name}")
        for change in collection_changes:
            print(f"[org-bones] {change}")

        self.report(
            {'INFO'},
            f"{len(created)} ORG bone(s) created, {len(reused)} reused; "
            f"{len(added)} constraint(s) added, {len(skipped)} already present"
        )
        return {'FINISHED'}


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

        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            row = layout.row()
            row.alignment = 'CENTER'
            row.label(text='- Gen ORG Button Requires Armature -')
        else:
            layout.operator(NAMES_ORG_BONES.operator_idname, text="Generate ORG Bones")


_classes = (
    EMANATE_OT_pre_rig_initialize,
    EMANATE_OT_make_def_skeleton,
    EMANATE_OT_org_bone_generator,
    EMANATE_PT_pre_rig_initialize,
)


def register():
    naming.check_classes(
        (EMANATE_OT_pre_rig_initialize, EMANATE_PT_pre_rig_initialize), NAMES
    )
    naming.check_classes((EMANATE_OT_make_def_skeleton,), NAMES_DEF_SKELETON)
    naming.check_classes((EMANATE_OT_org_bone_generator,), NAMES_ORG_BONES)
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
