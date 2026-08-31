import bpy
from mathutils import Vector

from ..helpers import bone_collections, deform_cleanup, widgets
from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "rigging_tools",
    label="Rigging Tools",
    owner=__name__,
    description="Container panel for the rig-creation tools: build the switchable FK/IK rig, symmetrize it onto the right side, wire drivers, and organize bone collections",
    order=20,
)

NAMES_LEG_RIG = naming.register_tool("generate_leg_rig", label="Generate Leg Rig", owner=__name__, description="Creates flexible rig with switchable fk/ik legs.")
NAMES_ARM_RIG = naming.register_tool("generate_arm_rig", label="Generate Arm Rig", owner=__name__, description="Creates flexible rig with switchable fk/ik arms.")
NAMES_SPINE_RIG = naming.register_tool("generate_spine_rig", label="Generate Spine Rig", owner=__name__, description="Creates flexible rig with switchable fk/ik spine.")
NAMES_SYMMETRIZE_RIG = naming.register_tool(
    "symmetrize_rig", label="Symmetrize Rig", owner=__name__, description="Mirrors every bone ending in .L onto the right side -- the whole rig, not just the deformation skeleton"
)
NAMES_ADD_DRIVERS = naming.register_tool(
    "add_all_drivers",
    label="Add All Drivers",
    owner=__name__,
    description="Wires every driven constraint in the rig, both sides, to its properties controller slider. Safe to re-run, and meant to be run after mirroring -- symmetrize copies constraints but not drivers",
)
NAMES_ORGANIZE_COLLECTIONS = naming.register_tool(
    "organize_bone_collections", label="Organize Bone Collections", owner=__name__, description="Sorts MCH_/FK_/IK_/ORG_/Tweak/WGT_/VIS_/PRPT_ bones into matching bone collections"
)

# ---------------------------------------------------------------------------
# Names the driver pass reaches for. A driver's data path is a string resolved
# from the constraint's name at driver_add time, so a constraint has to be
# named BEFORE it is driven, and renaming one afterwards silently breaks its
# driver. Keeping the names here means the builder and the driver pass cannot
# drift apart.
IK_SWITCH_CONSTRAINT_NAME = "IK_Transform_Influence"
ROTATION_FOLLOW_CONSTRAINT_NAME = "ROTATION_FOLLOW"
IK_PARENT_CONSTRAINT_NAME = "IK_PARENT_SWITCH"
HAND_IK_PARENT_CONSTRAINT_NAME = "HAND_IK_PARENT_SWITCH"
SLIDER_LIMIT_CONSTRAINT_NAME = "PROPERTIES_SLIDER_LIMIT"
ARM_IK_SWITCH_CONSTRAINT_NAME = "COPY_IK_TRANSFORMS"
ARM_FOLLOW_SHOULDER_CONSTRAINT_NAME = "FOLLOW_SHOULDER_ROTATION"

# Shared sizing for every PRPT_ container bone and the slider controller bone
# parented inside it (leg, hand, head, neck). One pair of numbers here keeps
# every properties rig the same size instead of each builder picking its own
# scale factor off a differently-sized container.
PROPERTIES_CONTAINER_LENGTH = 0.2
PROPERTIES_CONTROLLER_LENGTH = 0.05

# Every PRPT_ container reads as this one flat colour rather than a theme
# palette, so the whole properties panel looks like one piece across the leg,
# hand, neck and head rigs. Containers are backdrops for the slider riding
# inside them -- there is nothing on them to grab -- so each one also gets
# hide_select once its widget is assigned, which is what keeps a click landing
# on the slider instead of the panel behind it.
PROPERTIES_CONTAINER_COLOR = "#F7FF87"

# How far a properties controller's LIMIT_LOCATION constraint lets it slide
# on each active axis, in armature units. Matches PROPERTIES_CONTAINER_LENGTH
# so the controller travels exactly the width of its container widget --
# any other value and the controller either stops short of the container's
# edge or overshoots past it. The driver passes never hardcode this number;
# they read it back off the constraint via slider_travel, so changing this
# constant alone keeps the visuals and the drivers in sync.
PROPERTIES_CONTROLLER_TRAVEL = PROPERTIES_CONTAINER_LENGTH

# Bones carrying an IK_SWITCH_CONSTRAINT_NAME constraint, in chain order.
# Side-less -- the driver pass appends ".L" or ".R".
IK_SWITCH_BONES = ("MCH_SWITCH_Thigh", "MCH_SWITCH_Shin", "MCH_SWITCH_Foot", "MCH_SWITCH_Toe")

# Bones carrying an ARM_IK_SWITCH_CONSTRAINT_NAME constraint, in chain order.
# Side-less -- the driver pass appends ".L" or ".R". See add_hand_drivers.
ARM_IK_SWITCH_BONES = ("MCH_SWITCH_Arm", "MCH_SWITCH_Forearm", "MCH_SWITCH_Hand")

# side -> the properties controller that drives that side's limb. Both the
# hand and leg builders now build BOTH sides' controllers up front, at their
# own fixed, mirrored-in-position-only locations -- neither controller is a
# symmetrize-mirrored copy of the other, so neither one's local axes get the
# sign flip a mirrored bone would need. See add_hand_drivers/add_leg_drivers.
HAND_CONTROLLER_SIDES = {"L": "PRPT_Left_Hand_Controller", "R": "PRPT_Right_Hand_Controller"}
LEG_CONTROLLER_SIDES = {"L": "PRPT_Left_Leg_Controller", "R": "PRPT_Right_Leg_Controller"}

# (driven bone prefix, rotation_euler axis, clamp expression) for the foot
# roll/bank split. WGT_Foot_Roll is one control: turning it on Z is bank,
# on X is roll. Each pair below reads that same axis back off it and clamps
# to the half it owns, so Bank_01/Foot_Roll pick up the positive turn and
# Bank_02/Heel pick up the negative one. See add_leg_drivers.
FOOT_ROLL_SPLIT_DRIVERS = (
    ("MCH_Foot_Bank_01", "Z", "max(controller_rotation, 0)"),
    ("MCH_Foot_Bank_02", "Z", "min(controller_rotation, 0)"),
    ("MCH_Foot_Roll", "X", "max(controller_rotation, 0)"),
    ("MCH_Heel", "X", "min(controller_rotation, 0)"),
)

# Widget/control bones that only make sense in one FK/IK mode, auto-hidden
# once the slider crosses to the other one. FK_* bones carry their widget
# directly rather than through a separate WGT_ bone, so they are the mirror
# of IK_VISIBILITY_BONES even though the naming does not match it. See
# add_leg_drivers.
IK_VISIBILITY_BONES = ("WGT_Foot_IK_Master", "WGT_IK_Pole", "VIS_IK_Pole", "WGT_IK_Toe", "WGT_Foot_Roll")
FK_VISIBILITY_BONES = ("FK_Thigh", "FK_Shin", "FK_Foot", "FK_Toe")

# Same idea as IK_VISIBILITY_BONES/FK_VISIBILITY_BONES, for the arm. See
# add_hand_drivers.
ARM_IK_VISIBILITY_BONES = ("WGT_IK_Hand", "VIS_IK_Pole_Link", "WGT_IK_Pole_Target")
ARM_FK_VISIBILITY_BONES = ("FK_Arm", "FK_Forearm", "FK_Hand")

# (properties controller bone, target MCH bone that blends into its parent,
# rotation-follow constraint name, scale-follow constraint name). Both bones
# and both constraints are built by generate_spine_rig. X on the controller
# drives the rotation-follow constraint's influence (0 = does not follow the
# parent segment, 1 = fully follows); Z drives the scale-follow constraint's
# influence the same way. See add_spine_drivers.
HEAD_FOLLOW_DRIVERS = ("PRPT_Head_Controller", "MCH_Intermediary_Head", "FOLLOW_NECK_ROTATION", "FOLLOW_NECK_SCALE")
NECK_FOLLOW_DRIVERS = ("PRPT_Neck_Controller", "MCH_Intermediary_Neck", "FOLLOW_CHEST_ROTATION", "FOLLOW_CHEST_SCALE")
# ---------------------------------------------------------------------------


def slider_travel(limit_constraint, axis):
    """The signed distance the properties controller may slide on one axis.

    Symmetrize mirrors a LIMIT_LOCATION across X along with the bone that owns
    it, so a left controller built with min_x = 0, max_x = 0.1 comes out on the
    right as min_x = -0.1, max_x = 0. That is Blender being correct rather than
    Blender being annoying: the mirrored bone's local X points the other way,
    so the negative range is what makes the right slider travel the same
    direction on screen as the left one. Y and Z survive untouched -- the
    mirror is across X only.

    Reading whichever bound is non-zero therefore gives the travel *with its
    sign*, and dividing the slider channel by that signed value is what keeps
    both sides normalizing to the same 0..1: the right controller's -0.1 over
    -0.1 is the same 1.0 the left gets from 0.1 over 0.1.

    Assumes the range runs from zero out in one direction, which is what
    generate_leg_ik_fk_rig builds and what symmetrize preserves. A range
    straddling zero would need a driver expression shaped differently anyway.
    """
    axis = axis.lower()
    maximum = getattr(limit_constraint, f"max_{axis}", 0.0)
    minimum = getattr(limit_constraint, f"min_{axis}", 0.0)
    return maximum if maximum else minimum


def start_scripted_driver(owner, data_path, index=None):
    """Clear any existing driver on `owner`.<data_path> and start a fresh SCRIPTED one.

    Shared by every driver-adding helper below. Blender has no clean Python
    route for duplicating an existing driver onto another property -- the
    only native one is the copy/paste driver operators, which need button
    context -- so rebuilding one from scratch per property is the tidy way to
    share one setup across a chain.

    Wiping any existing driver first matters because driver_add on an
    already-driven property hands back the driver that is there rather than
    raising, so without this a second run would stack another variable on top
    rather than replacing it -- the mess would be invisible until someone
    opened the driver editor. A leftover generator modifier would override
    the expression outright and make the driver read as a flat ramp, so those
    are stripped too.

    `index` is required for array properties like "rotation_euler" (0/1/2 for
    X/Y/Z) and must stay unset for scalar ones like "influence" or "weight" --
    passing an index there would ask Blender for one component of a value
    that has none.
    """
    args = (data_path,) if index is None else (data_path, index)
    owner.driver_remove(*args)
    fcurve = owner.driver_add(*args)

    for modifier in list(fcurve.modifiers):
        fcurve.modifiers.remove(modifier)

    driver = fcurve.driver
    driver.type = "SCRIPTED"
    return driver


def add_slider_driver(owner, armature_obj, expression, axis="X", slider_bone="PRPT_Left_Leg_Controller", data_path="influence"):
    """Drive `owner`.<data_path> from a location channel of the slider bone.

    `axis` picks the channel: "X", "Y" or "Z". The driver variable is named to
    match, so axis="Y" reads LOC_Y and exposes it to the expression as
    `slider_y`. `expression` has to reference that same name -- pass the
    inverse form ("1 - slider_x / max") for whichever side should fade out.

    `data_path` defaults to "influence" for constraints, but also accepts
    "weight" to drive an armature constraint target's blend weight, or "hide"
    to drive a pose bone's own viewport visibility -- pass `owner=pose_bone`
    for that one. PoseBone.hide is its own property, separate from
    Bone.hide and EditBone.hide, so it must be driven on the pose bone
    itself rather than through `.bone`.
    """
    driver = start_scripted_driver(owner, data_path)

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


def add_rotation_clamp_driver(pose_bone, armature_obj, expression, axis, source_bone):
    """Drive `pose_bone`'s rotation_euler[axis] from `source_bone`'s rotation on that same axis.

    Built for the foot-roll split (see FOOT_ROLL_SPLIT_DRIVERS): one control
    bone's rotation on an axis gets read into two MCH bones, one clamped to
    the positive half via `expression="max(controller_rotation, 0)"` and the
    other to the negative half via `"min(controller_rotation, 0)"`.

    The variable is always named `controller_rotation` -- `expression` must
    reference that name. Reads with mode "AUTO" (Auto Euler) in "LOCAL_SPACE",
    matching the driver as configured by hand in Blender's driver editor.

    `pose_bone` must already be in Euler rotation_mode: rotation_euler is only
    live when the bone's own rotation_mode is an Euler order, so driving it
    under quaternion mode would compute a value pose evaluation never reads.
    """
    axis = axis.upper()
    index = "XYZ".index(axis)

    driver = start_scripted_driver(pose_bone, "rotation_euler", index)

    variable = driver.variables.new()
    variable.name = "controller_rotation"
    variable.type = "TRANSFORMS"

    target = variable.targets[0]
    target.id = armature_obj
    target.bone_target = source_bone
    target.transform_type = f"ROT_{axis}"
    target.rotation_mode = "AUTO"
    target.transform_space = "LOCAL_SPACE"

    driver.expression = expression
    return driver


def create_bone(edit_bones, name, head, tail, parent=None, roll=None, align_to=None, align_roll=None, length=None, connect=False):
    """Create one edit bone and return it.

    Returning the bone is the whole point -- the builder chains parents off the
    bones it just made, so a helper that only creates and drops the reference
    would leave everything downstream parented to None.

    `roll` and `align_roll` are both optional and `align_roll` is applied first,
    so passing both lets an explicit roll win over the aligned one. Order of the
    remaining assignments matches the hand-written blocks it replaces: parent,
    then connect (which snaps the head to the parent's tail), then the length
    scale, so `length` always scales from the bone's final head position.
    """
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent

    if align_to is not None:
        bone.align_orientation(align_to)
    if align_roll is not None:
        bone.align_roll(align_roll)
    if roll is not None:
        bone.roll = roll

    # use_connect only means something when the bone has a parent to connect
    # to. Blender ignores it on a parentless bone, so say so plainly rather
    # than letting a connect=True argument look like it did something.
    if parent is None:
        bone.use_connect = False
    else:
        bone.use_connect = connect

    if length is not None:
        bone.length = length

    return bone


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
    if any(bone is None for bone in (ORG_Hips, ORG_Thigh_Left, ORG_Shin_Left, ORG_Foot_Left, ORG_Toe_Left, Root)):
        return changed

    # ============================= MCH CHAIN ============================================================================================================
    # ---MCH Left Leg Socket---------------------------------------------------------
    # align_roll is more intentional than leaving roll to default or zero in case the rig is moved somehow in the future
    MCH_Leg_Socket_Left = create_bone(
        edit_bones, "MCH_Leg_Socket.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.head + Vector((0.0, 0.06, 0.0)), parent=ORG_Hips, align_roll=Vector((0.0, 0.0, 1.0))
    )

    # ---MCH Left Leg Intermediary Socket---------------------------------------------------------
    MCH_INT_Leg_Socket_Left = create_bone(
        edit_bones, "MCH_INT_Leg_Socket.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.head + Vector((0.0, 0.03, 0.0)), parent=Root, align_roll=Vector((0.0, 0.0, 1.0))
    )

    # ---MCH Left Thigh---------------------------------------------------------
    MCH_SWITCH_Thigh_Left = create_bone(edit_bones, "MCH_SWITCH_Thigh.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.tail, parent=MCH_INT_Leg_Socket_Left, roll=ORG_Thigh_Left.roll)

    # ---MCH Left Shin---------------------------------------------------------
    MCH_SWITCH_Shin_Left = create_bone(edit_bones, "MCH_SWITCH_Shin.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=MCH_SWITCH_Thigh_Left, roll=ORG_Shin_Left.roll, connect=True)

    # ---MCH Left Foot---------------------------------------------------------
    MCH_SWITCH_Foot_Left = create_bone(edit_bones, "MCH_SWITCH_Foot.L", head=ORG_Foot_Left.head, tail=ORG_Foot_Left.tail, parent=MCH_SWITCH_Shin_Left, roll=ORG_Foot_Left.roll, connect=True)

    # ---MCH Left Toe---------------------------------------------------------
    MCH_SWITCH_Toe_Left = create_bone(edit_bones, "MCH_SWITCH_Toe.L", head=ORG_Toe_Left.head, tail=ORG_Toe_Left.tail, parent=MCH_SWITCH_Foot_Left, roll=ORG_Toe_Left.roll, connect=True)

    # ==========================--------- FOOT RIG ------------------==============================

    # Both IK master bones sit flat on the floor plane (z = 0) at the toe's x,
    # running back to just behind the heel. Naming the two ends once keeps the
    # control and its parent from drifting apart if the shape is ever tweaked.
    foot_ik_master_head = Vector((ORG_Toe_Left.head.x, ORG_Toe_Left.head.y, 0))
    foot_ik_master_tail = Vector((ORG_Toe_Left.head.x, MCH_Heel_Left.head.y + 0.04, 0))

    # ---IK Master Parent for a switch constraint to root or hips ---------------------------------------------------------
    MCH_Parent_Foot_IK_Master_Left = create_bone(edit_bones, "MCH_Parent_Foot_IK_Master.L", head=foot_ik_master_head, tail=(foot_ik_master_head + foot_ik_master_tail) / 2)

    # ---IK Master Left Foot Control ---------------------------------------------------------
    WGT_Foot_IK_Master_Left = create_bone(edit_bones, "WGT_Foot_IK_Master.L", head=foot_ik_master_head, tail=foot_ik_master_tail, parent=MCH_Parent_Foot_IK_Master_Left)

    # ---MCH Foot Roll - Left ---------------------------------------------------------
    # align_roll here recalculates the bone roll to global z+
    MCH_Foot_Roll_Left = create_bone(edit_bones, "MCH_Foot_Roll.L", head=ORG_Toe_Left.head, tail=MCH_Heel_Left.head, parent=MCH_Heel_Left, align_roll=Vector((0.0, 0.0, 1.0)))

    # ---MCH Foot Roll - Left ---------------------------------------------------------
    WGT_Foot_Roll_Left = create_bone(
        edit_bones, "WGT_Foot_Roll.L", head=MCH_Heel_Left.head + Vector((0.0, 0.1, 0.0)), tail=MCH_Heel_Left.tail + Vector((0.0, 0.1, 0.0)), parent=WGT_Foot_IK_Master_Left
    )

    # parenting now that we have the roll
    MCH_Foot_Bank_01_Left.parent = MCH_Foot_Roll_Left
    MCH_Foot_Bank_02_Left.parent = MCH_Foot_Bank_01_Left
    MCH_Heel_Left.parent = WGT_Foot_IK_Master_Left

    # ============================= MCH TWEAK CHAIN ============================================================================================================
    # --- since we want all tweak bones to be the same length we take a percent of smallest bone in hierarchy that we can probably open up as parameter in the future ---
    desired_percent_size_of_tweakers = 0.5
    ORG_Leg_Chain_Left = (ORG_Thigh_Left, ORG_Shin_Left, ORG_Foot_Left, ORG_Toe_Left)
    # min() with a key returns the bone itself, so the chain stays inspectable; (name, roll, ...) instead of collapsing straight down to a float.
    smallest_bone_in_chain = min(ORG_Leg_Chain_Left, key=lambda bone: bone.length)
    tweaker_bone_length = smallest_bone_in_chain.length * desired_percent_size_of_tweakers

    # --- Left Thigh Tweak SCALE COMPENSATION CORRECTION ---------------------------------------------------------
    MCH_Thigh_Tweak_Scale_Compensation_Left = create_bone(
        edit_bones, "MCH_Thigh_Tweak_Scale_Compensation.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.tail, parent=MCH_SWITCH_Thigh_Left, roll=ORG_Thigh_Left.roll, length=tweaker_bone_length / 2
    )

    # ---TWEAK MCH Left Thigh---------------------------------------------------------
    Thigh_Tweak_Left = create_bone(
        edit_bones, "Thigh_Tweak.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.tail, parent=MCH_Thigh_Tweak_Scale_Compensation_Left, roll=ORG_Thigh_Left.roll, length=tweaker_bone_length
    )

    # --- TWEAK MCH Left Shin Tweak SCALE COMPENSATION CORRECTION---------------------------------------------------------
    MCH_Shin_Tweak_Scale_Compensation_Left = create_bone(
        edit_bones, "MCH_Shin_Tweak_Scale_Compensation.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=MCH_SWITCH_Shin_Left, roll=ORG_Shin_Left.roll, length=tweaker_bone_length
    )

    # --- TWEAK MCH Left Shin ---------------------------------------------------------
    Shin_Tweak_Left = create_bone(
        edit_bones, "Shin_Tweak.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=MCH_Shin_Tweak_Scale_Compensation_Left, roll=ORG_Shin_Left.roll, length=tweaker_bone_length
    )

    # --- TWEAK MCH Left Foot ---------------------------------------------------------
    Foot_Tweak_Left = create_bone(
        edit_bones, "Foot_Tweak.L", head=ORG_Foot_Left.head, tail=(ORG_Foot_Left.head + ORG_Foot_Left.tail) / 2, parent=MCH_SWITCH_Foot_Left, roll=ORG_Foot_Left.roll, length=tweaker_bone_length
    )

    # --- TWEAK MCH Left Toe  ---------------------------------------------------------
    Toe_Tweak_Left = create_bone(
        edit_bones, "Toe_Tweak.L", head=ORG_Toe_Left.head, tail=(ORG_Toe_Left.head + ORG_Toe_Left.tail) / 2, parent=MCH_SWITCH_Toe_Left, roll=ORG_Toe_Left.roll, length=tweaker_bone_length
    )

    # --- TWEAK MCH Left Toe TIP  ---------------------------------------------------------
    Toe_Tip_Tweak_Left = create_bone(
        edit_bones, "Toe_Tip_Tweak.L", head=ORG_Toe_Left.tail, tail=ORG_Toe_Left.tail - Vector((0.00, tweaker_bone_length, 0.0)), parent=MCH_SWITCH_Toe_Left, roll=ORG_Toe_Left.roll
    )

    # ============================= FK CHAIN ============================================================================================================================
    # ---FK Left Thigh---------------------------------------------------------
    FK_Thigh_Left = create_bone(edit_bones, "FK_Thigh.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.tail, parent=MCH_INT_Leg_Socket_Left, roll=ORG_Thigh_Left.roll)

    # ---FK Left Shin---------------------------------------------------------
    FK_Shin_Left = create_bone(edit_bones, "FK_Shin.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=FK_Thigh_Left, roll=ORG_Shin_Left.roll)

    # ---FK Left Foot---------------------------------------------------------
    FK_Foot_Left = create_bone(edit_bones, "FK_Foot.L", head=ORG_Foot_Left.head, tail=ORG_Foot_Left.tail, parent=FK_Shin_Left, roll=ORG_Foot_Left.roll)

    # ---FK Left Toe---------------------------------------------------------
    FK_Toe_Left = create_bone(edit_bones, "FK_Toe.L", head=ORG_Toe_Left.head, tail=ORG_Toe_Left.tail, parent=FK_Foot_Left, roll=ORG_Toe_Left.roll)

    # ============================= IK CHAIN ============================================================================================================================
    # ---IK Left Thigh---------------------------------------------------------
    IK_Thigh_Left = create_bone(edit_bones, "IK_Thigh.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.tail, parent=MCH_INT_Leg_Socket_Left, roll=ORG_Thigh_Left.roll)

    # ---IK Pole Target left leg ---------------------------------------------------------
    pole_distance = 0.4
    pole_head = ORG_Thigh_Left.tail + (ORG_Thigh_Left.matrix.to_3x3() @ Vector((pole_distance, 0.0, 0.0)))
    IK_Pole_Left = create_bone(edit_bones, "WGT_IK_Pole.L", head=pole_head, tail=pole_head + Vector((0.0, 0.075, 0.0)), parent=WGT_Foot_IK_Master_Left, align_roll=Vector((0.0, 0.0, 1.0)))

    # ---IK Pole Target Visualization bone ---------------------------------------------------------
    VIS_IK_Pole_Left = create_bone(edit_bones, "VIS_IK_Pole.L", head=IK_Thigh_Left.tail, tail=IK_Pole_Left.head, parent=IK_Thigh_Left)

    # ---IK Left Shin---------------------------------------------------------
    IK_Shin_Left = create_bone(edit_bones, "IK_Shin.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=IK_Thigh_Left, roll=ORG_Shin_Left.roll, connect=True)

    # ---IK Left Foot---------------------------------------------------------
    IK_Foot_Left = create_bone(edit_bones, "IK_Foot.L", head=ORG_Foot_Left.head, tail=ORG_Foot_Left.tail, parent=MCH_Foot_Bank_02_Left, roll=ORG_Foot_Left.roll)

    # ---IK Left Toe MCH bone---------------------------------------------------------
    MCH_Toe_IK_Left = create_bone(edit_bones, "MCH_Toe_IK.L", head=ORG_Toe_Left.head, tail=ORG_Toe_Left.tail, parent=IK_Foot_Left, roll=MCH_Foot_Roll_Left.roll, length=ORG_Toe_Left.length * 0.6)

    # ---IK Left Toe WGT Control ---------------------------------------------------------
    WGT_IK_Toe_Left = create_bone(edit_bones, "WGT_IK_Toe.L", head=ORG_Toe_Left.head, tail=ORG_Toe_Left.tail, parent=MCH_Toe_IK_Left, roll=ORG_Toe_Left.roll)

    # ------- Final Property Bones ---------------

    PRPT_Master_Container = create_bone(edit_bones, "PRPT_Master_Container", head=Vector((-3.0, 0, 0.0)), tail=Vector((-3.0, 1, 0.0)), parent=Root, length=1)

    PRPT_Left_Leg_Navigation = create_bone(
        edit_bones,
        "PRPT_Left_Leg_Container_Navigation",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 4.8, PROPERTIES_CONTAINER_LENGTH, PROPERTIES_CONTAINER_LENGTH * 2)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 4.8, PROPERTIES_CONTAINER_LENGTH * 1.1, PROPERTIES_CONTAINER_LENGTH * 2)),
        parent=PRPT_Master_Container,
        length=0.03,
    )
    PRPT_Left_Leg_Container = create_bone(
        edit_bones,
        "PRPT_Left_Leg_Container",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 5, 0, PROPERTIES_CONTAINER_LENGTH / 2)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 5, -0.5, PROPERTIES_CONTAINER_LENGTH / 2)),
        parent=PRPT_Left_Leg_Navigation,
        length=PROPERTIES_CONTAINER_LENGTH,
    )

    PRPT_Left_Leg_Controller = create_bone(
        edit_bones, "PRPT_Left_Leg_Controller", head=PRPT_Left_Leg_Container.head, tail=PRPT_Left_Leg_Container.tail, parent=PRPT_Left_Leg_Container, length=PROPERTIES_CONTROLLER_LENGTH
    )

    PRPT_Right_Leg_Navigation = create_bone(
        edit_bones,
        "PRPT_Right_Leg_Container_Navigation",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 3.2, PROPERTIES_CONTAINER_LENGTH, PROPERTIES_CONTAINER_LENGTH * 2)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 3.2, PROPERTIES_CONTAINER_LENGTH * 1.1, PROPERTIES_CONTAINER_LENGTH * 2)),
        parent=PRPT_Master_Container,
        length=0.03,
    )

    PRPT_Right_Leg_Container = create_bone(
        edit_bones,
        "PRPT_Right_Leg_Container",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 2, 0, PROPERTIES_CONTAINER_LENGTH / 2)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 2, -0.5, PROPERTIES_CONTAINER_LENGTH / 2)),
        parent=PRPT_Right_Leg_Navigation,
        length=PROPERTIES_CONTAINER_LENGTH,
    )

    PRPT_Right_Leg_Controller = create_bone(
        edit_bones, "PRPT_Right_Leg_Controller", head=PRPT_Right_Leg_Container.head, tail=PRPT_Right_Leg_Container.tail, parent=PRPT_Right_Leg_Container, length=PROPERTIES_CONTROLLER_LENGTH
    )

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
        changed.append("Issue: Cannot find ROOT bone, this rig is not ready; cancelling request")
        return changed

    # Every bone below has to be re-fetched from pose.bones by name. The
    # EditBone variables built further up are dangling pointers now -- leaving
    # edit mode frees the edit-bone structs, and touching one crashes Blender
    # outright rather than raising. Constraints only exist on pose bones anyway.
    pose_bones = armature_obj.pose.bones

    # ------- Set rotation for certain foot bones to XYZ Euler (only needs these rotatin axes) --------------------
    for name in ("MCH_Foot_Bank_01.L", "MCH_Foot_Bank_02.L", "MCH_Foot_Roll.L", "MCH_Heel.L", "WGT_Foot_Roll.L"):
        pb = pose_bones.get(name)
        if pb is not None:
            pb.rotation_mode = "XYZ"

    # ============================= location constraints =======================================================================================
    copy_leg_intermediary_socket_location = pose_bones["MCH_INT_Leg_Socket.L"].constraints.new("COPY_LOCATION")
    # -------- location targets --------
    copy_leg_intermediary_socket_location.target = armature_obj
    # -------- location subtargets --------
    copy_leg_intermediary_socket_location.subtarget = "MCH_Leg_Socket.L"

    # ============================= scale constraints =======================================================================================
    copy_thigh_scale = pose_bones["MCH_Thigh_Tweak_Scale_Compensation.L"].constraints.new("COPY_SCALE")
    copy_shin_scale = pose_bones["MCH_Shin_Tweak_Scale_Compensation.L"].constraints.new("COPY_SCALE")
    copy_leg_intermediary_socket_scale = pose_bones["MCH_INT_Leg_Socket.L"].constraints.new("COPY_SCALE")
    # -------- scale targets --------
    copy_thigh_scale.target = copy_shin_scale.target = copy_leg_intermediary_socket_scale.target = armature_obj
    # -------- scale subtargets --------
    copy_thigh_scale.subtarget = copy_shin_scale.subtarget = "Root"
    copy_leg_intermediary_socket_scale.subtarget = "MCH_Leg_Socket.L"

    # ============================= rotation constraints =======================================================================================
    copy_leg_intermediary_socket_rotation = pose_bones["MCH_INT_Leg_Socket.L"].constraints.new("COPY_ROTATION")
    copy_leg_intermediary_socket_rotation.name = "ROTATION_FOLLOW"

    copy_toe_rotation = pose_bones["MCH_Toe_IK.L"].constraints.new("COPY_ROTATION")
    copy_toe_rotation.target_space = copy_toe_rotation.owner_space = "LOCAL"
    copy_toe_rotation.use_y = copy_toe_rotation.use_z = False  # <------- only follow x axis

    # -------------rotation targets -------------
    copy_leg_intermediary_socket_rotation.target = armature_obj
    copy_toe_rotation.target = armature_obj

    # -------------rotation subtargets -------------
    copy_leg_intermediary_socket_rotation.subtarget = "MCH_Leg_Socket.L"
    copy_toe_rotation.subtarget = "MCH_Foot_Roll.L"

    # ============================= transform constraints =======================================================================================
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

    # -------------transform targets -------------
    copy_FK_thigh_transform.target = copy_FK_shin_transform.target = copy_FK_foot_transform.target = copy_FK_toe_transform.target = armature_obj
    copy_IK_thigh_transform.target = copy_IK_shin_transform.target = copy_IK_foot_transform.target = copy_IK_toe_transform.target = armature_obj

    # -------------transform subtargets -------------
    copy_FK_thigh_transform.subtarget = "FK_Thigh.L"
    copy_FK_shin_transform.subtarget = "FK_Shin.L"
    copy_FK_foot_transform.subtarget = "FK_Foot.L"
    copy_FK_toe_transform.subtarget = "FK_Toe.L"

    copy_IK_thigh_transform.subtarget = "IK_Thigh.L"
    copy_IK_shin_transform.subtarget = "IK_Shin.L"
    copy_IK_foot_transform.subtarget = "IK_Foot.L"
    copy_IK_toe_transform.subtarget = "WGT_IK_Toe.L"

    # ============================= limit location constraints =======================================================================================
    # --- left leg properties control limits ----
    limit_location_left_leg_properties_controller = pose_bones["PRPT_Left_Leg_Controller"].constraints.new("LIMIT_LOCATION")
    # Named because the driver pass reads max_x back off this constraint to
    # normalize the slider -- this is the single source of truth for how far
    # the controller travels, so nothing downstream hardcodes the number.
    limit_location_left_leg_properties_controller.name = SLIDER_LIMIT_CONSTRAINT_NAME
    limit_location_left_leg_properties_controller.owner_space = "LOCAL"
    limit_location_left_leg_properties_controller.use_min_x = limit_location_left_leg_properties_controller.use_min_y = limit_location_left_leg_properties_controller.use_min_z = True
    limit_location_left_leg_properties_controller.use_max_x = limit_location_left_leg_properties_controller.use_max_y = limit_location_left_leg_properties_controller.use_max_z = True
    limit_location_left_leg_properties_controller.use_transform_limit = True
    limit_location_left_leg_properties_controller.min_x = limit_location_left_leg_properties_controller.min_y = limit_location_left_leg_properties_controller.min_z = 0
    limit_location_left_leg_properties_controller.max_x = limit_location_left_leg_properties_controller.max_y = limit_location_left_leg_properties_controller.max_z = PROPERTIES_CONTROLLER_TRAVEL

    # --- right leg properties control limits ----
    limit_location_right_leg_properties_controller = pose_bones["PRPT_Right_Leg_Controller"].constraints.new("LIMIT_LOCATION")
    limit_location_right_leg_properties_controller.name = SLIDER_LIMIT_CONSTRAINT_NAME
    limit_location_right_leg_properties_controller.owner_space = "LOCAL"
    limit_location_right_leg_properties_controller.use_min_x = limit_location_right_leg_properties_controller.use_min_y = limit_location_right_leg_properties_controller.use_min_z = True
    limit_location_right_leg_properties_controller.use_max_x = limit_location_right_leg_properties_controller.use_max_y = limit_location_right_leg_properties_controller.use_max_z = True
    limit_location_right_leg_properties_controller.use_transform_limit = True
    limit_location_right_leg_properties_controller.min_x = limit_location_right_leg_properties_controller.min_y = limit_location_right_leg_properties_controller.min_z = 0
    limit_location_right_leg_properties_controller.max_x = limit_location_right_leg_properties_controller.max_y = limit_location_right_leg_properties_controller.max_z = PROPERTIES_CONTROLLER_TRAVEL

    # ============================= Armature constraints =======================================================================================
    Armature_IK_Parent = pose_bones["MCH_Parent_Foot_IK_Master.L"].constraints.new("ARMATURE")
    # Named so the driver pass can find it without depending on Blender's
    # default "Armature" label.
    Armature_IK_Parent.name = IK_PARENT_CONSTRAINT_NAME

    # ---- armature targets (including subtargets since this is a unique constraint with multible targets/subtargets) -------
    Armature_IK_Parent_root_target = Armature_IK_Parent.targets.new()
    Armature_IK_Parent_root_target.target = armature_obj
    Armature_IK_Parent_root_target.subtarget = "Root"
    Armature_IK_Parent_root_target.weight = 0.0

    Armature_IK_Parent_hip_target = Armature_IK_Parent.targets.new()
    Armature_IK_Parent_hip_target.target = armature_obj
    Armature_IK_Parent_hip_target.subtarget = "ORG_Hips"
    Armature_IK_Parent_hip_target.weight = 0.0

    # ============================= IK - proper inverse kinematic constraints for the IK leg ==========================================================
    shin_IK = pose_bones["IK_Shin.L"].constraints.new("IK")
    pose_bones["IK_Shin.L"].ik_stretch = 0.01
    pose_bones["IK_Thigh.L"].ik_stretch = 0.01
    shin_IK.chain_count = 2

    # -------------ik targets -------------
    shin_IK.target = shin_IK.pole_target = armature_obj

    # -------------ik subtargets -------------
    shin_IK.subtarget = "IK_Foot.L"
    shin_IK.pole_subtarget = "WGT_IK_Pole.L"

    # ============================= stretch to constraints ==========================================================
    stretch_toe = pose_bones["ORG_Toe.L"].constraints.new("STRETCH_TO")
    stretch_foot = pose_bones["ORG_Foot.L"].constraints.new("STRETCH_TO")
    stretch_shin = pose_bones["ORG_Shin.L"].constraints.new("STRETCH_TO")
    stretch_thigh = pose_bones["ORG_Thigh.L"].constraints.new("STRETCH_TO")
    stretch_pole_visualizer = pose_bones["VIS_IK_Pole.L"].constraints.new("STRETCH_TO")

    # ------------- stretch targets -------------
    stretch_toe.target = stretch_foot.target = stretch_shin.target = stretch_thigh.target = stretch_pole_visualizer.target = armature_obj

    # ----------------------- stretch subtargets --------------------------------
    stretch_toe.subtarget = "Toe_Tip_Tweak.L"
    stretch_foot.subtarget = "Toe_Tweak.L"
    stretch_shin.subtarget = "Foot_Tweak.L"
    stretch_thigh.subtarget = "Shin_Tweak.L"
    stretch_pole_visualizer.subtarget = "WGT_IK_Pole.L"

    # ========================================================================================================================
    # -------------------------------  WIDGET ASSIGNMENTS --------------------------------------------------------------------
    # ========================================================================================================================
    # --------- Root ----------
    widgets.assign_widget(pose_bones["Root"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, rotation_x=90, scale_x=2.0, scale_y=2.0, scale_z=2.0, color="THEME11")

    # --------- IK Pole Line Visualizer ----------
    widgets.assign_widget(pose_bones["VIS_IK_Pole.L"], "VIS_Line", wire_width=2, color="THEME07")

    # --------- IK Pole Controller ----------
    widgets.assign_widget(pose_bones["WGT_IK_Pole.L"], "WGT_Bottom_Face_Centered_Pyramid", scale_y=-1, wire_width=2, color="THEME07")

    # --------- Left Leg IK Master ----------
    widgets.assign_widget(pose_bones["WGT_Foot_IK_Master.L"], "WGT_Bottom_Face_Centered_Cube", scale_y=0.5, rotation_x=90, wire_width=2, color="THEME04")

    # --------- Left Leg IK Toe ----------
    widgets.assign_widget(pose_bones["WGT_IK_Toe.L"], "WGT_Bottom_Face_Centered_Cube", wire_width=1, color="THEME04")

    # --------- Left Leg IK Roll ----------
    widgets.assign_widget(pose_bones["WGT_Foot_Roll.L"], "WGT_Curved_Quadruple_Arrows", wire_width=2, color="THEME04")

    # --------- Left Leg FK Chain ----------
    FK_LEG_WIDGET_SIZE = 0.25  # armature units, tune to taste

    for name in ("FK_Thigh.L", "FK_Shin.L", "FK_Foot.L", "FK_Toe.L"):
        widgets.assign_widget(pose_bones[name], "WGT_Circle_Centered", scale_x=FK_LEG_WIDGET_SIZE, scale_y=FK_LEG_WIDGET_SIZE, scale_z=FK_LEG_WIDGET_SIZE, use_bone_size=False, color="THEME09")

    # --------- Left Tweakers --------------
    TWEAK_WIDGET_SIZE = 1  # armature units, tune to taste

    for name in ("Thigh_Tweak.L", "Shin_Tweak.L", "Foot_Tweak.L", "Toe_Tweak.L", "Toe_Tip_Tweak.L"):
        widgets.assign_widget(pose_bones[name], "WGT_Centered_IcoSphere", scale_x=TWEAK_WIDGET_SIZE, scale_y=TWEAK_WIDGET_SIZE, scale_z=TWEAK_WIDGET_SIZE, use_bone_size=True, color="THEME09")

    # --------- Properties Container ----------
    widgets.assign_widget(pose_bones["PRPT_Left_Leg_Container"], "WGT_Left_Foot_Properties", wire_width=1, color=PROPERTIES_CONTAINER_COLOR)
    widgets.assign_widget(pose_bones["PRPT_Right_Leg_Container"], "WGT_Right_Foot_Properties", wire_width=1, color=PROPERTIES_CONTAINER_COLOR)

    for name in ("PRPT_Left_Leg_Container", "PRPT_Right_Leg_Container"):
        pose_bones[name].bone.hide_select = True

    # --------- Properties Controller ----------
    widgets.assign_widget(pose_bones["PRPT_Left_Leg_Controller"], "WGT_Centered_IcoSphere", wire_width=1, color="#5CFF55")
    widgets.assign_widget(pose_bones["PRPT_Right_Leg_Controller"], "WGT_Centered_IcoSphere", wire_width=1, color="#5CFF55")

    # --------- Property Master Controllers and Navigators ----------
    widgets.assign_widget(pose_bones["PRPT_Master_Container"], "WGT_PRPT_Master", wire_width=2, color=PROPERTIES_CONTAINER_COLOR)
    widgets.assign_widget(pose_bones["PRPT_Left_Leg_Container_Navigation"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, color="#5CFF55")
    widgets.assign_widget(pose_bones["PRPT_Right_Leg_Container_Navigation"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, color="#5CFF55")

    changed.append("copy scale on the thigh/shin compensation bones -> Root")
    changed.append("stretch-to on the shin/foot/toe/toe-tip tweaks")
    changed.append("MCH legs added")

    return changed


def generate_arm_ik_fk_rig(context, armature_obj=None):

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

    # ORG_Shoulder.L is built by the org-bone generator tool from DEF_Shoulder.L,
    # so it has to be looked up by name here rather than created in this function.
    # We re-retrieve the ORG bones we need here
    PRPT_Master_Container = edit_bones.get("PRPT_Master_Container")
    ORG_Chest = edit_bones.get("ORG_Chest")
    ORG_Shoulder_Left = edit_bones.get("ORG_Shoulder.L")
    ORG_Arm_Left = edit_bones.get("ORG_Arm.L")
    ORG_Forearm_Proximal_Left = edit_bones.get("ORG_Forearm_Proximal.L")
    ORG_Forearm_Distal_Left = edit_bones.get("ORG_Forearm_Distal.L")
    ORG_Hand_Left = edit_bones.get("ORG_Hand.L")
    Root = edit_bones.get("Root")
    # `is None` binds to a single operand, so it has to be tested per bone --
    # chaining them with `or` would only check the last one.
    if any(bone is None for bone in (ORG_Shoulder_Left, ORG_Arm_Left, ORG_Forearm_Proximal_Left, ORG_Forearm_Distal_Left, ORG_Hand_Left, Root)):
        changed.append("You are missing a certain required bone")
        return changed

    # ============================= MCH BONES  ============================================================================================================
    # ------------- mch socket bones -------
    MCH_Arm_Socket_Left = create_bone(
        edit_bones, "MCH_Arm_Socket.L", head=ORG_Arm_Left.head, tail=(ORG_Arm_Left.head + Vector((0, 0.2, 0.0))), align_roll=Vector((0.0, 0.0, 1.0)), parent=ORG_Shoulder_Left
    )
    MCH_Intermediary_Arm_Socket_Left = create_bone(
        edit_bones,
        "MCH_Intermediary_Arm_Socket.L",
        head=ORG_Arm_Left.head,
        tail=(ORG_Arm_Left.head + Vector((0, 0.1, 0.0))),
        align_roll=Vector((0.0, 0.0, 1.0)),
        length=MCH_Arm_Socket_Left.length * 0.5,
        parent=Root,
    )

    MCH_SWITCH_Arm_Left = create_bone(edit_bones, "MCH_SWITCH_Arm.L", head=ORG_Arm_Left.head, tail=ORG_Arm_Left.tail, roll=ORG_Arm_Left.roll, parent=MCH_Intermediary_Arm_Socket_Left)
    MCH_SWITCH_Forearm_Left = create_bone(
        edit_bones, "MCH_SWITCH_Forearm.L", head=ORG_Forearm_Proximal_Left.head, tail=ORG_Forearm_Distal_Left.tail, roll=ORG_Forearm_Proximal_Left.roll, parent=MCH_SWITCH_Arm_Left
    )
    MCH_SWITCH_Hand_Left = create_bone(edit_bones, "MCH_SWITCH_Hand.L", head=ORG_Hand_Left.head, tail=ORG_Hand_Left.tail, roll=ORG_Hand_Left.roll, parent=MCH_SWITCH_Forearm_Left)

    # ============================= TWEAKERS BONES ============================================================================================================
    # ---  dynamically get tweaker size by smallest bone as we did in the legs to get a reasonable sized tweaker bone that doesn't look nasty in edit mode-----
    desired_percent_size_of_tweakers = 0.3
    ORG_ARM_CHAIN = (ORG_Arm_Left, ORG_Forearm_Proximal_Left, ORG_Forearm_Distal_Left, ORG_Hand_Left)  # <--- purposefully skipping ORG_Chest as we don't want a tweaker on this one
    # min() with a key returns the bone itself, so the chain stays inspectable; (name, roll, ...) instead of collapsing straight down to a float.
    smallest_bone_in_chain = min(ORG_ARM_CHAIN, key=lambda bone: bone.length)
    tweaker_bone_length = smallest_bone_in_chain.length * desired_percent_size_of_tweakers

    # ---All Arm Tweak Bones---------------------------------------------------------
    # ---Intermediary Arm Tweak Bones---------------------------------------------------------
    MCH_Arm_Intermediary_Tweak_Left = create_bone(
        edit_bones, "MCH_Arm_Intermediary_Tweak.L", head=ORG_Arm_Left.head, tail=ORG_Arm_Left.tail, roll=ORG_Arm_Left.roll, length=tweaker_bone_length * 0.5, parent=MCH_SWITCH_Arm_Left
    )
    MCH_Forearm_Proximal_Intermediary_Tweak_Left = create_bone(
        edit_bones,
        "MCH_Forearm_Proximal_Intermediary_Tweak.L",
        head=ORG_Forearm_Proximal_Left.head,
        tail=ORG_Forearm_Proximal_Left.tail,
        roll=ORG_Forearm_Proximal_Left.roll,
        length=tweaker_bone_length * 0.5,
        parent=MCH_SWITCH_Forearm_Left,
    )
    MCH_Forearm_Distal_Intermediary_Tweak_Left = create_bone(
        edit_bones,
        "MCH_Forearm_Distal_Intermediary_Tweak.L",
        head=ORG_Forearm_Distal_Left.head,
        tail=ORG_Forearm_Distal_Left.tail,
        roll=ORG_Forearm_Distal_Left.roll,
        length=tweaker_bone_length * 0.5,
        parent=MCH_SWITCH_Forearm_Left,
    )
    MCH_Hand_Intermediary_Tweak_Left = create_bone(
        edit_bones, "MCH_Hand_Intermediary_Tweak.L", head=ORG_Hand_Left.head, tail=ORG_Hand_Left.tail, roll=ORG_Hand_Left.roll, length=tweaker_bone_length * 0.5, parent=MCH_SWITCH_Hand_Left
    )
    # ---Primary Arm Tweak Bones---------------------------------------------------------
    Arm_Tweak_Left = create_bone(edit_bones, "Arm_Tweak.L", head=ORG_Arm_Left.head, tail=ORG_Arm_Left.tail, roll=ORG_Arm_Left.roll, length=tweaker_bone_length, parent=MCH_Arm_Intermediary_Tweak_Left)
    Forearm_Proximal_Tweak_Left = create_bone(
        edit_bones,
        "Forearm_Proximal_Tweak.L",
        head=ORG_Forearm_Proximal_Left.head,
        tail=ORG_Forearm_Proximal_Left.tail,
        roll=ORG_Forearm_Proximal_Left.roll,
        length=tweaker_bone_length,
        parent=MCH_Forearm_Proximal_Intermediary_Tweak_Left,
    )
    Forearm_Distal_Tweak_Left = create_bone(
        edit_bones,
        "Forearm_Distal_Tweak.L",
        head=ORG_Forearm_Distal_Left.head,
        tail=ORG_Forearm_Distal_Left.tail,
        roll=ORG_Forearm_Distal_Left.roll,
        length=tweaker_bone_length,
        parent=MCH_Forearm_Distal_Intermediary_Tweak_Left,
    )
    Hand_Tweak_Left = create_bone(
        edit_bones, "Hand_Tweak.L", head=ORG_Hand_Left.head, tail=ORG_Hand_Left.tail, roll=ORG_Hand_Left.roll, length=tweaker_bone_length, parent=MCH_Hand_Intermediary_Tweak_Left
    )
    Hand_Tip_Tweak_Left = create_bone(
        edit_bones, "Hand_Tip_Tweak.L", head=ORG_Hand_Left.tail, tail=(ORG_Hand_Left.tail + Vector((0.1, 0, 0))), align_to=ORG_Hand_Left, length=tweaker_bone_length, parent=MCH_SWITCH_Hand_Left
    )

    # ============================= FK BONES ===========================================================================================================================================

    FK_Arm_Left = create_bone(edit_bones, "FK_Arm.L", head=ORG_Arm_Left.head, tail=ORG_Arm_Left.tail, roll=ORG_Arm_Left.roll, parent=MCH_Intermediary_Arm_Socket_Left)
    FK_Forearm_Left = create_bone(edit_bones, "FK_Forearm.L", head=ORG_Forearm_Proximal_Left.head, tail=ORG_Forearm_Distal_Left.tail, roll=ORG_Forearm_Proximal_Left.roll, parent=FK_Arm_Left)
    FK_Hand_Left = create_bone(edit_bones, "FK_Hand.L", head=ORG_Hand_Left.head, tail=ORG_Hand_Left.tail, roll=ORG_Hand_Left.roll, parent=FK_Forearm_Left)

    # ============================= IK BONES ===========================================================================================================================================

    MCH_IK_Arm_Left = create_bone(edit_bones, "MCH_IK_Arm.L", head=ORG_Arm_Left.head, tail=ORG_Arm_Left.tail, roll=ORG_Arm_Left.roll, parent=MCH_Intermediary_Arm_Socket_Left)
    MCH_IK_Forearm_Left = create_bone(
        edit_bones, "MCH_IK_Forearm.L", head=ORG_Forearm_Proximal_Left.head, tail=ORG_Forearm_Distal_Left.tail, roll=ORG_Forearm_Proximal_Left.roll, parent=MCH_IK_Arm_Left
    )
    MCH_IK_Hand_Parent_Left = create_bone(edit_bones, "MCH_IK_Hand_Parent.L", head=ORG_Hand_Left.head, tail=ORG_Hand_Left.tail, roll=ORG_Hand_Left.roll, length=ORG_Hand_Left.length * 0.5)
    WGT_IK_Hand_Left = create_bone(edit_bones, "WGT_IK_Hand.L", head=ORG_Hand_Left.head, tail=ORG_Hand_Left.tail, roll=ORG_Hand_Left.roll, parent=MCH_IK_Hand_Parent_Left)

    pole_distance = 0.4
    pole_head = ORG_Arm_Left.tail + (ORG_Arm_Left.matrix.to_3x3() @ Vector((pole_distance, 0.0, 0.0)))
    WGT_IK_Pole_Target_Left = create_bone(edit_bones, "WGT_IK_Pole_Target.L", head=pole_head, tail=(pole_head + Vector((0.0, 0.075, 0.0))), align_roll=Vector((0.0, 0.0, 1.0)), parent=Root)
    VIS_IK_Pole_Link_Left = create_bone(edit_bones, "VIS_IK_Pole_Link.L", head=MCH_IK_Arm_Left.tail, tail=pole_head, parent=MCH_IK_Arm_Left)

    # ---- now we can parent ORG Bones to tweakers
    ORG_Arm_Left.parent = Arm_Tweak_Left
    ORG_Forearm_Proximal_Left.parent = Forearm_Proximal_Tweak_Left
    ORG_Forearm_Distal_Left.parent = Forearm_Distal_Tweak_Left
    ORG_Hand_Left.parent = Hand_Tweak_Left

    changed.append("Created MCH and Tweaks. Parented ORG bones to tweakers")

    # ============================= PROPERTY BONES ============================================================================================================
    # ----------- LEFT HAND PROPERTIES ---------------
    PRPT_Left_Hand_Navigator = create_bone(
        edit_bones,
        "PRPT_Left_Hand_Navigation",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 4.8, PROPERTIES_CONTAINER_LENGTH, PROPERTIES_CONTAINER_LENGTH * 5.5)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 4.8, PROPERTIES_CONTAINER_LENGTH * 1.1, PROPERTIES_CONTAINER_LENGTH * 5.5)),
        length=0.03,
        parent=PRPT_Master_Container,
    )
    PRPT_Left_Hand_Container = create_bone(
        edit_bones,
        "PRPT_Left_Hand_Container",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 5.0, 0, PROPERTIES_CONTAINER_LENGTH * 4)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 5.0, -0.5, PROPERTIES_CONTAINER_LENGTH * 4)),
        align_roll=Vector((0.0, 0.0, 1.0)),
        parent=PRPT_Left_Hand_Navigator,
        length=PROPERTIES_CONTAINER_LENGTH,
    )

    PRPT_Left_Hand_Controller = create_bone(
        edit_bones, "PRPT_Left_Hand_Controller", head=PRPT_Left_Hand_Container.head, tail=PRPT_Left_Hand_Container.tail, length=PROPERTIES_CONTROLLER_LENGTH, parent=PRPT_Left_Hand_Container
    )

    # ----------- RIGHT HAND PROPERTIES ---------------
    PRPT_Right_Hand_Navigator = create_bone(
        edit_bones,
        "PRPT_Right_Hand_Navigation",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 3.2, PROPERTIES_CONTAINER_LENGTH, PROPERTIES_CONTAINER_LENGTH * 5.5)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 3.2, PROPERTIES_CONTAINER_LENGTH * 1.1, PROPERTIES_CONTAINER_LENGTH * 5.5)),
        length=0.03,
        parent=PRPT_Master_Container,
    )

    PRPT_Right_Hand_Container = create_bone(
        edit_bones,
        "PRPT_Right_Hand_Container",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 2, 0, PROPERTIES_CONTAINER_LENGTH * 4)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 2, 0.1, PROPERTIES_CONTAINER_LENGTH * 4)),
        parent=PRPT_Right_Hand_Navigator,
        length=PROPERTIES_CONTAINER_LENGTH,
    )

    PRPT_Right_Hand_Controller = create_bone(
        edit_bones,
        "PRPT_Right_Hand_Controller",
        head=PRPT_Right_Hand_Container.head,
        tail=PRPT_Right_Hand_Container.tail,
        length=PROPERTIES_CONTROLLER_LENGTH,
        parent=PRPT_Right_Hand_Container,
    )

    changed.append("Created Property bones to complete all bone creations")

    # ========================================== ENTERING POSE MODE  ============================================================================
    # ============================================== CONSTRAINTS ============================================================================
    # Constraints hang off pose bones, and everything built above only shows up
    # in armature_obj.pose.bones once edit mode is left -- so the switch has to
    # happen here, after the whole chain exists.
    bpy.ops.object.mode_set(mode="POSE")

    # Root comes from the DEF skeleton, not from this function, so it can be
    # missing if the tools are run out of order.
    if armature_obj.data.bones.get("Root") is None:
        changed.append("Issue: Cannot find ROOT bone, this rig is not ready; cancelling request")
        return changed

    # Every bone below has to be re-fetched from pose.bones by name. The
    # EditBone variables built further up are dangling pointers now -- leaving
    # edit mode frees the edit-bone structs, and touching one crashes Blender
    # outright rather than raising. Constraints only exist on pose bones anyway.
    pose_bones = armature_obj.pose.bones

    # ============================= ROTATION CONSTRAINTS ==========================================================
    proximal_forearm_copy_rotation = pose_bones["ORG_Forearm_Proximal.L"].constraints.new("COPY_ROTATION")
    proximal_forearm_copy_rotation.influence = 0.1
    distal_forearm_copy_rotation = pose_bones["ORG_Forearm_Distal.L"].constraints.new("COPY_ROTATION")
    distal_forearm_copy_rotation.influence = 0.4

    # --------------------- rotation targets -----------------------------------
    proximal_forearm_copy_rotation.target = distal_forearm_copy_rotation.target = armature_obj
    # --------------------- rotation subtargets -----------------------------------
    proximal_forearm_copy_rotation.subtarget = "ORG_Hand.L"
    distal_forearm_copy_rotation.subtarget = "ORG_Hand.L"

    # ============================= STRETCH TO CONSTRAINTS ==========================================================
    stretch_arm = pose_bones["ORG_Arm.L"].constraints.new("STRETCH_TO")
    stretch_proximal_forearm = pose_bones["ORG_Forearm_Proximal.L"].constraints.new("STRETCH_TO")
    stretch_distal_forearm = pose_bones["ORG_Forearm_Distal.L"].constraints.new("STRETCH_TO")
    stretch_hand = pose_bones["ORG_Hand.L"].constraints.new("STRETCH_TO")
    stretch_vis_pole_link = pose_bones["VIS_IK_Pole_Link.L"].constraints.new("STRETCH_TO")

    stretch_arm.target = stretch_proximal_forearm.target = stretch_distal_forearm.target = stretch_hand.target = stretch_vis_pole_link.target = armature_obj

    # ----------------------- stretch subtargets --------------------------------
    stretch_arm.subtarget = "Forearm_Proximal_Tweak.L"
    stretch_proximal_forearm.subtarget = "Forearm_Distal_Tweak.L"
    stretch_distal_forearm.subtarget = "Hand_Tweak.L"
    stretch_hand.subtarget = "Hand_Tip_Tweak.L"
    stretch_vis_pole_link.subtarget = "WGT_IK_Pole_Target.L"

    # ============================= LOCATION CONSTRAINTS =======================================================================================
    arm_follow_socket_copy_location = pose_bones["MCH_Intermediary_Arm_Socket.L"].constraints.new("COPY_LOCATION")
    # ---- location targets -----------
    arm_follow_socket_copy_location.target = armature_obj
    # ---- location subtargets -----------
    arm_follow_socket_copy_location.subtarget = "MCH_Arm_Socket.L"

    # ============================= SCALE CONSTRAINTS =======================================================================================
    arm_follow_socket_copy_scale = pose_bones["MCH_Intermediary_Arm_Socket.L"].constraints.new("COPY_SCALE")
    MCH_Arm_Intermediary_Tweak_copy_scale = pose_bones["MCH_Arm_Intermediary_Tweak.L"].constraints.new("COPY_SCALE")
    MCH_Forearm_Proximal_Intermediary_Tweak_copy_scale = pose_bones["MCH_Forearm_Proximal_Intermediary_Tweak.L"].constraints.new("COPY_SCALE")
    MCH_Forearm_Distal_Intermediary_Tweak_copy_scale = pose_bones["MCH_Forearm_Distal_Intermediary_Tweak.L"].constraints.new("COPY_SCALE")
    MCH_Hand_Intermediary_Tweak_copy_scale = pose_bones["MCH_Hand_Intermediary_Tweak.L"].constraints.new("COPY_SCALE")

    # ---- scale targets -----------
    arm_follow_socket_copy_scale.target = MCH_Arm_Intermediary_Tweak_copy_scale.target = MCH_Forearm_Proximal_Intermediary_Tweak_copy_scale.target = (
        MCH_Forearm_Distal_Intermediary_Tweak_copy_scale.target
    ) = MCH_Hand_Intermediary_Tweak_copy_scale.target = armature_obj

    # ---- scale subtargets -----------
    arm_follow_socket_copy_scale.subtarget = "MCH_Arm_Socket.L"
    MCH_Arm_Intermediary_Tweak_copy_scale.subtarget = MCH_Forearm_Proximal_Intermediary_Tweak_copy_scale.subtarget = MCH_Forearm_Distal_Intermediary_Tweak_copy_scale.subtarget = (
        MCH_Hand_Intermediary_Tweak_copy_scale.subtarget
    ) = "Root"

    # ** !! Adendum ---- need the copy rotation to come last in this change so for this follow constraint we are adding this specific one after copy locatio and scale ----
    # ** We can't move all the copy rotations down here because the other ones above do need to come first in their order
    arm_follow_socket_copy_rotation = pose_bones["MCH_Intermediary_Arm_Socket.L"].constraints.new("COPY_ROTATION")
    arm_follow_socket_copy_rotation.name = ARM_FOLLOW_SHOULDER_CONSTRAINT_NAME
    arm_follow_socket_copy_rotation.target = armature_obj
    arm_follow_socket_copy_rotation.subtarget = "MCH_Arm_Socket.L"

    # ============================= TRANSFORM CONSTRAINTS =======================================================================================
    # ----------------------------- Switch arm fk follows -------------------------------------
    SWITCH_Arm_copy_fk_transform = pose_bones["MCH_SWITCH_Arm.L"].constraints.new("COPY_TRANSFORMS")
    SWITCH_Arm_copy_fk_transform.name = "COPY_FK_TRANSFORMS"
    SWITCH_Forearm_copy_fk_transform = pose_bones["MCH_SWITCH_Forearm.L"].constraints.new("COPY_TRANSFORMS")
    SWITCH_Forearm_copy_fk_transform.name = "COPY_FK_TRANSFORMS"
    SWITCH_Hand_copy_fk_transform = pose_bones["MCH_SWITCH_Hand.L"].constraints.new("COPY_TRANSFORMS")
    SWITCH_Hand_copy_fk_transform.name = "COPY_FK_TRANSFORMS"

    # --- fk targets ---
    SWITCH_Arm_copy_fk_transform.target = SWITCH_Forearm_copy_fk_transform.target = SWITCH_Hand_copy_fk_transform.target = armature_obj
    # --- fk subtargets ---
    SWITCH_Arm_copy_fk_transform.subtarget = "FK_Arm.L"
    SWITCH_Forearm_copy_fk_transform.subtarget = "FK_Forearm.L"
    SWITCH_Hand_copy_fk_transform.subtarget = "FK_Hand.L"

    # Switch arm ik follows
    # ----------------------------- Switch arm ik follows -------------------------------------
    SWITCH_Arm_copy_ik_transform = pose_bones["MCH_SWITCH_Arm.L"].constraints.new("COPY_TRANSFORMS")
    SWITCH_Arm_copy_ik_transform.name = ARM_IK_SWITCH_CONSTRAINT_NAME
    SWITCH_Forearm_copy_ik_transform = pose_bones["MCH_SWITCH_Forearm.L"].constraints.new("COPY_TRANSFORMS")
    SWITCH_Forearm_copy_ik_transform.name = ARM_IK_SWITCH_CONSTRAINT_NAME
    SWITCH_Hand_copy_ik_transform = pose_bones["MCH_SWITCH_Hand.L"].constraints.new("COPY_TRANSFORMS")
    SWITCH_Hand_copy_ik_transform.name = ARM_IK_SWITCH_CONSTRAINT_NAME

    # --- ik targets ---
    SWITCH_Arm_copy_ik_transform.target = SWITCH_Forearm_copy_ik_transform.target = SWITCH_Hand_copy_ik_transform.target = armature_obj
    # --- ik subtargets ---
    SWITCH_Arm_copy_ik_transform.subtarget = "MCH_IK_Arm.L"
    SWITCH_Forearm_copy_ik_transform.subtarget = "MCH_IK_Forearm.L"
    SWITCH_Hand_copy_ik_transform.subtarget = "WGT_IK_Hand.L"

    # ============================= IK - proper inverse kinematic constraints for the IK leg ==========================================================
    arm_IK = pose_bones["MCH_IK_Forearm.L"].constraints.new("IK")
    pose_bones["MCH_IK_Forearm.L"].ik_stretch = 0.01
    pose_bones["MCH_IK_Forearm.L"].lock_ik_x = True
    pose_bones["MCH_IK_Forearm.L"].lock_ik_y = True
    pose_bones["MCH_IK_Arm.L"].ik_stretch = 0.01
    arm_IK.chain_count = 2

    # -------------ik targets -------------
    arm_IK.target = arm_IK.pole_target = armature_obj

    # -------------ik subtargets -------------
    arm_IK.subtarget = "WGT_IK_Hand.L"
    arm_IK.pole_subtarget = "WGT_IK_Pole_Target.L"

    # ============================= IK LIMIT LOCATION CONSTRAINTS ==========================================================
    # --- hand properties control limits ----
    limit_location_left_hand_properties_controller = pose_bones["PRPT_Left_Hand_Controller"].constraints.new("LIMIT_LOCATION")
    # Named because the driver pass reads max_x back off this constraint to
    # normalize the slider -- this is the single source of truth for how far
    # the controller travels, so nothing downstream hardcodes the number.
    limit_location_left_hand_properties_controller.name = SLIDER_LIMIT_CONSTRAINT_NAME
    limit_location_left_hand_properties_controller.owner_space = "LOCAL"
    limit_location_left_hand_properties_controller.use_min_x = limit_location_left_hand_properties_controller.use_min_y = limit_location_left_hand_properties_controller.use_min_z = True
    limit_location_left_hand_properties_controller.use_max_x = limit_location_left_hand_properties_controller.use_max_y = limit_location_left_hand_properties_controller.use_max_z = True
    limit_location_left_hand_properties_controller.use_transform_limit = True
    limit_location_left_hand_properties_controller.min_x = limit_location_left_hand_properties_controller.min_y = limit_location_left_hand_properties_controller.min_z = 0
    limit_location_left_hand_properties_controller.max_x = limit_location_left_hand_properties_controller.max_y = limit_location_left_hand_properties_controller.max_z = PROPERTIES_CONTROLLER_TRAVEL

    limit_location_right_hand_properties_controller = pose_bones["PRPT_Right_Hand_Controller"].constraints.new("LIMIT_LOCATION")
    # Named because the driver pass reads max_x back off this constraint to
    # normalize the slider -- this is the single source of truth for how far
    # the controller travels, so nothing downstream hardcodes the number.
    limit_location_right_hand_properties_controller.name = SLIDER_LIMIT_CONSTRAINT_NAME
    limit_location_right_hand_properties_controller.owner_space = "LOCAL"
    limit_location_right_hand_properties_controller.use_min_x = limit_location_right_hand_properties_controller.use_min_y = limit_location_right_hand_properties_controller.use_min_z = True
    limit_location_right_hand_properties_controller.use_max_x = limit_location_right_hand_properties_controller.use_max_y = limit_location_right_hand_properties_controller.use_max_z = True
    limit_location_right_hand_properties_controller.use_transform_limit = True
    limit_location_right_hand_properties_controller.min_x = limit_location_right_hand_properties_controller.min_y = limit_location_right_hand_properties_controller.min_z = 0
    limit_location_right_hand_properties_controller.max_x = limit_location_right_hand_properties_controller.max_y = limit_location_right_hand_properties_controller.max_z = PROPERTIES_CONTROLLER_TRAVEL

    # ============================= Armature constraints =======================================================================================
    Armature_Hand_IK_Parent = pose_bones["MCH_IK_Hand_Parent.L"].constraints.new("ARMATURE")
    # Named so the driver pass can find it without depending on Blender's
    # default "Armature" label.
    Armature_Hand_IK_Parent.name = IK_PARENT_CONSTRAINT_NAME

    # ---- armature targets (including subtargets since this is a unique constraint with multible targets/subtargets) -------
    Armature_Hand_IK_Parent_root_target = Armature_Hand_IK_Parent.targets.new()
    Armature_Hand_IK_Parent_root_target.target = armature_obj
    Armature_Hand_IK_Parent_root_target.subtarget = "Root"
    Armature_Hand_IK_Parent_root_target.weight = 0.0

    Armature_Hand_IK_Parent_hip_target = Armature_Hand_IK_Parent.targets.new()
    Armature_Hand_IK_Parent_hip_target.target = armature_obj
    Armature_Hand_IK_Parent_hip_target.subtarget = "ORG_Hips"
    Armature_Hand_IK_Parent_hip_target.weight = 0.0

    # -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # =========================================== WIDGET SECTION ================================================================================================================================================
    # -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

    # --- Assign Tweak Shapes -----------------------------------------------------------------------------------
    TWEAK_WIDGET_SIZE = 0.06  # armature units, tune to taste

    for name in ("Arm_Tweak.L", "Forearm_Proximal_Tweak.L", "Forearm_Distal_Tweak.L", "Hand_Tweak.L", "Hand_Tip_Tweak.L"):
        widgets.assign_widget(pose_bones[name], "WGT_Centered_IcoSphere", scale_x=TWEAK_WIDGET_SIZE, scale_y=TWEAK_WIDGET_SIZE, scale_z=TWEAK_WIDGET_SIZE, use_bone_size=False, color="THEME09")

    # --- Assign FK Shapes -----------------------------------------------------------------------------------
    FK_WGT_SIZE = 0.25  # armature units, tune to taste

    for name in ("FK_Arm.L", "FK_Forearm.L", "FK_Hand.L"):
        widgets.assign_widget(pose_bones[name], "WGT_Circle_Centered", scale_x=FK_WGT_SIZE, scale_y=FK_WGT_SIZE, scale_z=FK_WGT_SIZE, use_bone_size=False, color="THEME09")

    # --- IK Arm Shapes -----------------------------------------------------------------------------------
    widgets.assign_widget(pose_bones["WGT_IK_Hand.L"], "WGT_Bottom_Face_Centered_Cube", scale_x=1, scale_y=1, scale_z=1, use_bone_size=True, color="THEME04")
    widgets.assign_widget(pose_bones["WGT_IK_Pole_Target.L"], "WGT_Bottom_Face_Centered_Pyramid", scale_x=1, scale_y=1, scale_z=1, use_bone_size=True, color="THEME07")
    widgets.assign_widget(pose_bones["VIS_IK_Pole_Link.L"], "VIS_Line", scale_x=1, scale_y=1, scale_z=1, use_bone_size=True, color="THEME07")

    # --- Arm Properties Shapes -----------------------------------------------------------------------------------
    controller_scale = 1
    widgets.assign_widget(pose_bones["PRPT_Left_Hand_Container"], "WGT_Left_Hand_Properties", scale_x=1, scale_y=1, scale_z=1, use_bone_size=True, color=PROPERTIES_CONTAINER_COLOR)
    widgets.assign_widget(
        pose_bones["PRPT_Left_Hand_Controller"], "WGT_Centered_IcoSphere", scale_x=controller_scale, scale_y=controller_scale, scale_z=controller_scale, use_bone_size=True, color="#5CFF55"
    )

    widgets.assign_widget(pose_bones["PRPT_Right_Hand_Container"], "WGT_Right_Hand_Properties", scale_x=1, scale_y=1, scale_z=1, use_bone_size=True, color=PROPERTIES_CONTAINER_COLOR)
    widgets.assign_widget(
        pose_bones["PRPT_Right_Hand_Controller"], "WGT_Centered_IcoSphere", scale_x=controller_scale, scale_y=controller_scale, scale_z=controller_scale, use_bone_size=True, color="#5CFF55"
    )

    for name in ("PRPT_Left_Hand_Container", "PRPT_Right_Hand_Container"):
        pose_bones[name].bone.hide_select = True

    # --- PRPT Navigators
    widgets.assign_widget(pose_bones["PRPT_Left_Hand_Navigation"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, color="#5CFF55")
    widgets.assign_widget(pose_bones["PRPT_Right_Hand_Navigation"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, color="#5CFF55")

    changed.append("Added arm widgets/icons")
    return changed


def generate_spine_rig(context, armature_obj=None):
    """Building spine rig here.

    Begins in EDIT mode to create bones, then transitions to POSE mode to add constraints and widgets.
    """
    changed = []

    # Recapture the armature
    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    if armature_obj.mode != "EDIT":
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")

    # ---------- Get bones we need that are already generated ----------
    edit_bones = armature_obj.data.edit_bones

    PRPT_Master_Container = edit_bones.get("PRPT_Master_Container")
    ORG_Hips = edit_bones.get("ORG_Hips")
    ORG_Spine_01 = edit_bones.get("ORG_Spine_01")
    ORG_Spine_02 = edit_bones.get("ORG_Spine_02")
    ORG_Chest = edit_bones.get("ORG_Chest")  # <---- the DEF Should be renamed to MCH later as this is not really a proper DEF bone...
    ORG_Chest_Sub_01 = edit_bones.get("ORG_Chest_Sub_01")
    ORG_Chest_Sub_02 = edit_bones.get("ORG_Chest_Sub_02")
    ORG_Neck = edit_bones.get("ORG_Neck")
    ORG_Head = edit_bones.get("ORG_Head")
    Root = edit_bones.get("Root")

    # ---WGT Torso Bone---------------------------------------------------------
    WGT_COG_Torso = create_bone(edit_bones, "WGT_COG_Torso", head=ORG_Spine_01.tail, tail=(ORG_Spine_01.tail + Vector((0, 0.5, 0))), parent=Root)
    Chest_Master = create_bone(edit_bones, "Chest_Master", head=WGT_COG_Torso.head, tail=WGT_COG_Torso.tail, parent=WGT_COG_Torso, length=WGT_COG_Torso.length * 0.75)
    Hips_Master = create_bone(edit_bones, "Hips_Master", head=Chest_Master.head, tail=Chest_Master.tail, parent=WGT_COG_Torso, length=Chest_Master.length * 0.75)

    # ==================================================  WIDGET AND FK CONTROLLER BONES   ====================================================================================================
    # ==================================================  MECHANISM Bones sprinkled in. They all depend on one another   ====================================================================================================
    # ------------ BOTTOM HALF CONTROLLERS -----------------
    MCH_Spine_01_FK = create_bone(edit_bones, "MCH_Spine_01_FK", head=WGT_COG_Torso.head, tail=WGT_COG_Torso.tail, parent=WGT_COG_Torso, length=WGT_COG_Torso.length * 0.075)
    FK_Spine_01 = create_bone(edit_bones, "FK_Spine_01", head=ORG_Spine_02.head, tail=ORG_Spine_02.tail, align_to=ORG_Spine_01, parent=MCH_Spine_01_FK)
    MCH_Hips_FK = create_bone(edit_bones, "MCH_Hips_FK", head=ORG_Spine_01.head, tail=(ORG_Spine_01.head + Vector((0, 0.04, 0))), parent=FK_Spine_01)
    FK_Hips = create_bone(edit_bones, "FK_Hips", head=ORG_Spine_01.head, tail=ORG_Spine_01.tail, align_to=ORG_Hips, parent=MCH_Hips_FK)

    # ------------ TOP HALF CONTROLLERS -----------------
    MCH_Spine_02_FK = create_bone(edit_bones, "MCH_Spine_02_FK", head=WGT_COG_Torso.head, tail=WGT_COG_Torso.tail, parent=WGT_COG_Torso, length=WGT_COG_Torso.length * 0.1)
    FK_Spine_02 = create_bone(edit_bones, "FK_Spine_02", head=ORG_Spine_02.head, tail=ORG_Spine_02.tail, parent=MCH_Spine_02_FK)
    MCH_Chest_FK = create_bone(edit_bones, "MCH_Chest_FK", head=ORG_Spine_02.tail, tail=(ORG_Spine_02.tail + Vector((0, 0.04, 0))), parent=FK_Spine_02)
    FK_Chest = create_bone(edit_bones, "FK_Chest", head=ORG_Chest.head, tail=ORG_Chest.tail, parent=MCH_Chest_FK)
    # --- neck ---
    MCH_Neck = create_bone(edit_bones, "MCH_Neck", head=ORG_Neck.head, tail=(ORG_Neck.head + Vector((0, 0.04, 0))), parent=FK_Chest)
    MCH_Intermediary_Neck = create_bone(edit_bones, "MCH_Intermediary_Neck", head=MCH_Neck.head, tail=MCH_Neck.tail, length=MCH_Neck.length * 0.75, parent=Root)
    FK_Neck = create_bone(edit_bones, "FK_Neck", head=ORG_Neck.head, tail=ORG_Neck.tail, parent=MCH_Intermediary_Neck)
    # --- head ---
    MCH_Head = create_bone(edit_bones, "MCH_Head", head=ORG_Head.head, tail=(ORG_Head.head + Vector((0, 0.05, 0))), parent=FK_Neck)
    MCH_Intermediary_Head = create_bone(edit_bones, "MCH_Intermediary_Head", head=MCH_Head.head, tail=MCH_Head.tail, length=MCH_Head.length * 0.8, parent=Root)
    WGT_Head = create_bone(edit_bones, "WGT_Head", head=ORG_Head.head, tail=ORG_Head.tail, parent=MCH_Intermediary_Head)

    MCH_Spine_Pivot = create_bone(edit_bones, "MCH_Spine_Pivot", head=FK_Spine_01.head, tail=FK_Spine_01.tail, parent=FK_Spine_02, length=FK_Spine_01.length * 0.6)

    # ==================================================  TWEAKER BONES   ====================================================================================================
    # ---  dynamically get tweaker size by smallest bone as we did in the legs to get a reasonable sized tweaker bone that doesn't look nasty in edit mode-----
    desired_percent_size_of_tweakers = 0.8
    ORG_Spine_Chain = (ORG_Hips, ORG_Spine_01, ORG_Spine_02, ORG_Chest_Sub_01, ORG_Chest_Sub_02, ORG_Neck, ORG_Head)  # <--- purposefully skipping ORG_Chest as we don't want a tweaker on this one
    # min() with a key returns the bone itself, so the chain stays inspectable; (name, roll, ...) instead of collapsing straight down to a float.
    smallest_bone_in_chain = min(ORG_Spine_Chain, key=lambda bone: bone.length)
    tweaker_bone_length = smallest_bone_in_chain.length * desired_percent_size_of_tweakers

    Hips_Tweak = create_bone(edit_bones, "Hips_Tweak", head=ORG_Hips.head, tail=ORG_Hips.tail, parent=FK_Hips, length=tweaker_bone_length)
    Spine_01_Tweak = create_bone(edit_bones, "Spine_01_Tweak", head=ORG_Spine_01.head, tail=ORG_Spine_01.tail, parent=FK_Hips, length=tweaker_bone_length)
    Spine_02_Tweak = create_bone(edit_bones, "Spine_02_Tweak", head=ORG_Spine_02.head, tail=ORG_Spine_02.tail, parent=MCH_Spine_Pivot, length=tweaker_bone_length)
    Chest_01_Tweak = create_bone(edit_bones, "Chest_01_Tweak", head=ORG_Chest_Sub_01.head, tail=ORG_Chest_Sub_01.tail, parent=FK_Chest, length=tweaker_bone_length)
    Chest_02_Tweak = create_bone(edit_bones, "Chest_02_Tweak", head=ORG_Chest_Sub_02.head, tail=ORG_Chest_Sub_02.tail, parent=ORG_Chest, length=tweaker_bone_length)
    Neck_Tweak = create_bone(edit_bones, "Neck_Tweak", head=ORG_Neck.head, tail=ORG_Neck.tail, parent=FK_Neck, length=tweaker_bone_length)
    Head_Tweak = create_bone(edit_bones, "Head_Tweak", head=ORG_Head.head, tail=ORG_Head.tail, parent=WGT_Head, length=tweaker_bone_length)
    Head_Top_Tweak = create_bone(edit_bones, "Head_Top_Tweak", head=ORG_Head.tail, tail=(ORG_Head.tail + Vector((0, 0, 0.1))), parent=WGT_Head, length=tweaker_bone_length)

    # ------  now we can parent ORG bones where we need to ------
    ORG_Hips.parent = Hips_Tweak
    ORG_Spine_01.parent = Spine_01_Tweak
    ORG_Spine_02.parent = Spine_02_Tweak
    ORG_Chest.parent = Chest_01_Tweak  # <---- unclear for sure where this parents to, shall come back to look at it later
    ORG_Chest_Sub_01.parent = Chest_01_Tweak
    ORG_Chest_Sub_02.parent = Chest_02_Tweak
    ORG_Neck.parent = Neck_Tweak
    ORG_Head.parent = Head_Tweak

    # ========================================== FINAL PROPERTIES BONES  ============================================================================
    # ---- Neck Property Bones ----
    PRPT_Neck_Navigator = create_bone(
        edit_bones,
        "PRPT_Neck_Navigation",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 3.2, PROPERTIES_CONTAINER_LENGTH/2, PROPERTIES_CONTAINER_LENGTH * 8.8)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 3.2, (PROPERTIES_CONTAINER_LENGTH/2)*1.1, PROPERTIES_CONTAINER_LENGTH * 8.8)),
        length=0.03,
        parent=PRPT_Master_Container,
    )
    PRPT_Neck_Container = create_bone(
        edit_bones,
        "PRPT_Neck_Container",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 2, PROPERTIES_CONTAINER_LENGTH/2, PROPERTIES_CONTAINER_LENGTH * 7)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 2,(PROPERTIES_CONTAINER_LENGTH/2)*1.1, PROPERTIES_CONTAINER_LENGTH * 7)),
        parent=PRPT_Neck_Navigator,
        length=PROPERTIES_CONTAINER_LENGTH,
    )

    PRPT_Neck_Controller = create_bone(
        edit_bones, "PRPT_Neck_Controller", head=PRPT_Neck_Container.head, tail=PRPT_Neck_Container.tail, length=PROPERTIES_CONTROLLER_LENGTH, parent=PRPT_Neck_Container
    )

    # ---- Head Property Bones ----

    PRPT_Head_Navigator = create_bone(
        edit_bones,
        "PRPT_Head_Navigation",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 4.8, PROPERTIES_CONTAINER_LENGTH/2, PROPERTIES_CONTAINER_LENGTH * 8.8)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 4.8, (PROPERTIES_CONTAINER_LENGTH/2)*1.1, PROPERTIES_CONTAINER_LENGTH * 8.8)),
        length=0.03,
        parent=PRPT_Master_Container,
    )

    PRPT_Head_Container = create_bone(
        edit_bones,
        "PRPT_Head_Container",
        head=PRPT_Master_Container.head + Vector((PROPERTIES_CONTAINER_LENGTH * 5, PROPERTIES_CONTAINER_LENGTH/2, PROPERTIES_CONTAINER_LENGTH * 7)),
        tail=PRPT_Master_Container.tail + Vector((PROPERTIES_CONTAINER_LENGTH * 5, (PROPERTIES_CONTAINER_LENGTH/2)*1.1, PROPERTIES_CONTAINER_LENGTH * 7)),
        parent=PRPT_Head_Navigator,
        length=PROPERTIES_CONTAINER_LENGTH,
    )
    
    PRPT_Head_Controller = create_bone(
        edit_bones, "PRPT_Head_Controller", head=PRPT_Head_Container.head, tail=PRPT_Head_Container.tail, length=PROPERTIES_CONTROLLER_LENGTH, parent=PRPT_Head_Container
    )

    # ========================================== ENTERING POSE MODE  ============================================================================
    # ============================================== CONSTRAINTS ============================================================================
    # Constraints hang off pose bones, and everything built above only shows up
    # in armature_obj.pose.bones once edit mode is left -- so the switch has to
    # happen here, after the whole chain exists.
    bpy.ops.object.mode_set(mode="POSE")

    # Root comes from the DEF skeleton, not from this function, so it can be
    # missing if the tools are run out of order.
    if armature_obj.data.bones.get("Root") is None:
        changed.append("Issue: Cannot find ROOT bone, this rig is not ready; cancelling request")
        return changed

    # Every bone below has to be re-fetched from pose.bones by name. The
    # EditBone variables built further up are dangling pointers now -- leaving
    # edit mode frees the edit-bone structs, and touching one crashes Blender
    # outright rather than raising. Constraints only exist on pose bones anyway.
    pose_bones = armature_obj.pose.bones

    # ============================= STRETCH TO CONSTRAINTS ==========================================================
    stretch_hips = pose_bones["ORG_Hips"].constraints.new("STRETCH_TO")
    stretch_spine_01 = pose_bones["ORG_Spine_01"].constraints.new("STRETCH_TO")
    stretch_spine_02 = pose_bones["ORG_Spine_02"].constraints.new("STRETCH_TO")
    stretch_chest = pose_bones["ORG_Chest"].constraints.new("STRETCH_TO")
    stretch_chest_sub_01 = pose_bones["ORG_Chest_Sub_01"].constraints.new("STRETCH_TO")
    stretch_chest_sub_02 = pose_bones["ORG_Chest_Sub_02"].constraints.new("STRETCH_TO")
    stretch_neck = pose_bones["ORG_Neck"].constraints.new("STRETCH_TO")
    stretch_head = pose_bones["ORG_Head"].constraints.new("STRETCH_TO")

    # ------------- stretch targets -------------
    stretch_hips.target = stretch_spine_01.target = stretch_spine_02.target = stretch_chest.target = stretch_chest_sub_01.target = stretch_chest_sub_02.target = stretch_neck.target = (
        stretch_head.target
    ) = armature_obj

    # ----------------------- stretch subtargets --------------------------------
    stretch_hips.subtarget = "Spine_01_Tweak"
    stretch_spine_01.subtarget = "Spine_02_Tweak"
    stretch_spine_02.subtarget = "Chest_01_Tweak"
    stretch_chest.subtarget = "Neck_Tweak"
    stretch_chest_sub_01.subtarget = "Chest_02_Tweak"
    stretch_chest_sub_02.subtarget = "Neck_Tweak"
    stretch_neck.subtarget = "Head_Tweak"
    stretch_head.subtarget = "Head_Top_Tweak"

    # ============================= COPY TRANSFORM CONSTRAINTS ==========================================================
    copy_spine_01_fk_transforms = pose_bones["MCH_Spine_Pivot"].constraints.new("COPY_TRANSFORMS")
    copy_spine_01_fk_transforms.influence = 0.5
    copy_mch_chest_fk_transforms = pose_bones["MCH_Chest_FK"].constraints.new("COPY_TRANSFORMS")
    copy_mch_chest_fk_transforms.influence = 0.5
    copy_mch_chest_fk_transforms.target_space = copy_mch_chest_fk_transforms.owner_space = "LOCAL"

    copy_mch_spine_01_fk_transforms = pose_bones["MCH_Spine_01_FK"].constraints.new("COPY_TRANSFORMS")
    copy_mch_spine_01_fk_transforms.target_space = copy_mch_spine_01_fk_transforms.owner_space = "LOCAL"
    copy_mch_spine_01_fk_transforms.influence = 0.5

    copy_mch_hips_fk_transforms = pose_bones["MCH_Hips_FK"].constraints.new("COPY_TRANSFORMS")
    copy_mch_hips_fk_transforms.target_space = copy_mch_hips_fk_transforms.owner_space = "LOCAL"
    copy_mch_hips_fk_transforms.influence = 0.5

    copy_mch_spine_02_fk_transforms = pose_bones["MCH_Spine_02_FK"].constraints.new("COPY_TRANSFORMS")
    copy_mch_spine_02_fk_transforms.target_space = copy_mch_spine_02_fk_transforms.owner_space = "LOCAL"
    copy_mch_spine_02_fk_transforms.influence = 0.5

    # ------------- copy transform targets -------------
    copy_spine_01_fk_transforms.target = copy_mch_chest_fk_transforms.target = copy_mch_spine_02_fk_transforms.target = copy_mch_hips_fk_transforms.target = copy_mch_spine_01_fk_transforms.target = (
        armature_obj
    )
    # ------------- copy transform subtargets -------------
    copy_spine_01_fk_transforms.subtarget = "FK_Spine_01"
    copy_mch_chest_fk_transforms.subtarget = "Chest_Master"
    copy_mch_spine_02_fk_transforms.subtarget = "Chest_Master"
    copy_mch_hips_fk_transforms.subtarget = "Hips_Master"
    copy_mch_spine_01_fk_transforms.subtarget = "Hips_Master"

    # ============================= COPY LOCATION CONSTRAINTS ==========================================================
    copy_int_neck_location = pose_bones["MCH_Intermediary_Neck"].constraints.new("COPY_LOCATION")
    copy_int_head_location = pose_bones["MCH_Intermediary_Head"].constraints.new("COPY_LOCATION")
    # targets
    copy_int_neck_location.target = copy_int_head_location.target = armature_obj
    # subtargets
    copy_int_neck_location.subtarget = "MCH_Neck"
    copy_int_head_location.subtarget = "MCH_Head"

    # ============================= COPY SCALE CONSTRAINTS ==========================================================
    copy_int_neck_scale = pose_bones["MCH_Intermediary_Neck"].constraints.new("COPY_SCALE")
    copy_int_neck_scale.name = "FOLLOW_CHEST_SCALE"
    copy_int_head_scale = pose_bones["MCH_Intermediary_Head"].constraints.new("COPY_SCALE")
    copy_int_head_scale.name = "FOLLOW_NECK_SCALE"
    # targets
    copy_int_neck_scale.target = copy_int_head_scale.target = armature_obj
    # subtargets
    copy_int_neck_scale.subtarget = "MCH_Neck"
    copy_int_head_scale.subtarget = "MCH_Head"

    # ============================= COPY ROTATION CONSTRAINTS ==========================================================
    copy_int_neck_rotation = pose_bones["MCH_Intermediary_Neck"].constraints.new("COPY_ROTATION")
    copy_int_neck_rotation.name = "FOLLOW_CHEST_ROTATION"
    copy_int_head_rotation = pose_bones["MCH_Intermediary_Head"].constraints.new("COPY_ROTATION")
    copy_int_head_rotation.name = "FOLLOW_NECK_ROTATION"
    # targets
    copy_int_neck_rotation.target = copy_int_head_rotation.target = armature_obj
    # subtargets
    copy_int_neck_rotation.subtarget = "MCH_Neck"
    copy_int_head_rotation.subtarget = "MCH_Head"

    # ============================= LIMIT LOCATION CONSTRAINTS =======================================================================================
    # --- head properties control limits -----------------------------------------------------------------------------------------------------------------------------------------------
    limit_location_head_properties_controller = pose_bones["PRPT_Head_Controller"].constraints.new("LIMIT_LOCATION")
    # Named because the driver pass reads max_x back off this constraint to
    # normalize the slider -- this is the single source of truth for how far
    # the controller travels, so nothing downstream hardcodes the number.
    limit_location_head_properties_controller.name = SLIDER_LIMIT_CONSTRAINT_NAME
    limit_location_head_properties_controller.owner_space = "LOCAL"
    limit_location_head_properties_controller.use_min_x = limit_location_head_properties_controller.use_min_y = limit_location_head_properties_controller.use_min_z = True
    limit_location_head_properties_controller.use_max_x = limit_location_head_properties_controller.use_max_y = limit_location_head_properties_controller.use_max_z = True
    limit_location_head_properties_controller.use_transform_limit = True
    limit_location_head_properties_controller.min_x = limit_location_head_properties_controller.min_y = limit_location_head_properties_controller.min_z = (
        limit_location_head_properties_controller.max_y
    ) = 0
    limit_location_head_properties_controller.max_x = limit_location_head_properties_controller.max_z = PROPERTIES_CONTROLLER_TRAVEL

    # --- neck properties control limits -----------------------------------------------------------------------------------------------------------------------------------------------
    limit_location_neck_properties_controller = pose_bones["PRPT_Neck_Controller"].constraints.new("LIMIT_LOCATION")
    # Named because the driver pass reads max_x back off this constraint to
    # normalize the slider -- this is the single source of truth for how far
    # the controller travels, so nothing downstream hardcodes the number.
    limit_location_neck_properties_controller.name = SLIDER_LIMIT_CONSTRAINT_NAME
    limit_location_neck_properties_controller.owner_space = "LOCAL"
    limit_location_neck_properties_controller.use_min_x = limit_location_neck_properties_controller.use_min_y = limit_location_neck_properties_controller.use_min_z = True
    limit_location_neck_properties_controller.use_max_x = limit_location_neck_properties_controller.use_max_y = limit_location_neck_properties_controller.use_max_z = True
    limit_location_neck_properties_controller.use_transform_limit = True
    limit_location_neck_properties_controller.min_x = limit_location_neck_properties_controller.min_y = limit_location_neck_properties_controller.min_z = (
        limit_location_neck_properties_controller.max_y
    ) = 0
    limit_location_neck_properties_controller.max_x = limit_location_neck_properties_controller.max_z = PROPERTIES_CONTROLLER_TRAVEL

    # ================================================================================================================================================================================================================================================
    # -------------------------------  WIDGET ASSIGNMENTS ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # ================================================================================================================================================================================================================================================

    # --- Assign Tweak Shapes -----------------------------------------------------------------------------------
    TWEAK_WIDGET_SIZE = 1  # armature units, tune to taste

    for name in ("Hips_Tweak", "Spine_01_Tweak", "Spine_02_Tweak", "Chest_01_Tweak", "Chest_02_Tweak", "Neck_Tweak", "Head_Tweak", "Head_Top_Tweak"):
        widgets.assign_widget(pose_bones[name], "WGT_Centered_IcoSphere", scale_x=TWEAK_WIDGET_SIZE, scale_y=TWEAK_WIDGET_SIZE, scale_z=TWEAK_WIDGET_SIZE, use_bone_size=True, color="THEME09")

    # --- Assign FK Shapes -----------------------------------------------------------------------------------
    TWEAK_FK_SIZE = 0.3  # armature units, tune to taste

    for name in ("FK_Hips", "FK_Spine_01", "FK_Chest"):
        widgets.assign_widget(pose_bones[name], "WGT_Circle_Centered", scale_x=TWEAK_FK_SIZE, scale_y=TWEAK_FK_SIZE, scale_z=TWEAK_FK_SIZE, use_bone_size=False, color="THEME09")
    # --FK_Spine_02 is in the same spot as 01, so we need to make it smaller for now
    widgets.assign_widget(pose_bones["FK_Spine_02"], "WGT_Circle_Centered", scale_x=TWEAK_FK_SIZE / 2, scale_y=TWEAK_FK_SIZE / 2, scale_z=TWEAK_FK_SIZE / 2, use_bone_size=False, color="THEME09")
    # -- neck --
    widgets.assign_widget(pose_bones["FK_Neck"], "WGT_Circle_Centered", scale_x=TWEAK_FK_SIZE / 3, scale_y=TWEAK_FK_SIZE / 3, scale_z=TWEAK_FK_SIZE / 3, use_bone_size=False, color="THEME09")

    # --------- Torso COG Master ----------
    COG_scale = 2.0
    widgets.assign_widget(pose_bones["WGT_COG_Torso"], "WGT_Center_Of_Gravity_Hip", wire_width=2, rotation_y=90, scale_x=COG_scale, scale_y=COG_scale, scale_z=COG_scale, color="THEME04")
    # --------- Torso HIPS Master ----------
    hips_scale = 0.9
    widgets.assign_widget(pose_bones["Hips_Master"], "WGT_Bottom_Face_Centered_Cube", wire_width=2, rotation_x=-90, scale_x=hips_scale, scale_y=hips_scale, scale_z=hips_scale, color="THEME01")
    # --------- Torso CHEST Master ----------
    chest_scale = 0.9
    widgets.assign_widget(pose_bones["Chest_Master"], "WGT_Bottom_Face_Centered_Cube", wire_width=2, rotation_x=90, scale_x=chest_scale, scale_y=chest_scale, scale_z=chest_scale, color="THEME01")
    # --------- Head Master ----------
    head_scale = 2.0
    widgets.assign_widget(pose_bones["WGT_Head"], "WGT_Curved_Quadruple_Arrows", wire_width=2, rotation_x=90, scale_x=head_scale, scale_y=head_scale, scale_z=head_scale, color="THEME01")
    pose_bones["WGT_Head"].custom_shape_translation[1] = pose_bones["ORG_Head"].bone.length
    # --------- Property Controllers ----------
    widgets.assign_widget(pose_bones["PRPT_Neck_Container"], "WGT_Neck_Properties", wire_width=1, color=PROPERTIES_CONTAINER_COLOR)
    widgets.assign_widget(pose_bones["PRPT_Neck_Controller"], "WGT_Circle_Centered", wire_width=5, color="#5CFF55")
    widgets.assign_widget(pose_bones["PRPT_Head_Container"], "WGT_Head_Properties", wire_width=1, color=PROPERTIES_CONTAINER_COLOR)
    widgets.assign_widget(pose_bones["PRPT_Head_Controller"], "WGT_Circle_Centered", wire_width=5, color="#5CFF55")
    # --------- Property Navigators ----------
    widgets.assign_widget(pose_bones["PRPT_Head_Navigation"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, color="#5CFF55")
    widgets.assign_widget(pose_bones["PRPT_Neck_Navigation"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, color="#5CFF55")

    for name in ("PRPT_Neck_Container", "PRPT_Head_Container"):
        pose_bones[name].bone.hide_select = True

    changed.append("stretch-to on the hips/spine/chest/neck/head chain")
    changed.append("FK and tweak controllers wired up")
    changed.append("spine, neck and head widgets assigned")

    return changed


def add_leg_drivers(context, armature_obj=None, side="L"):
    """Drive one leg's constraints from its properties controller slider.

    Re-runnable: add_slider_driver clears any existing driver on a property
    before rebuilding it, so pressing the button twice rebuilds rather than
    accumulates.

    Like add_hand_drivers, PRPT_Left_Leg_Controller and PRPT_Right_Leg_Controller
    are both built directly by generate_leg_ik_fk_rig -- neither is a
    symmetrize-mirrored copy of the other, so neither one's local axes get the
    sign flip a mirrored bone would need. Every expression below reads
    straight off the signed range with no side-dependent inversion. See
    LEG_CONTROLLER_SIDES.

    A missing bone or constraint is skipped rather than raised on -- the right
    side legitimately does not exist until the mirror has been run.
    """
    changed = []

    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    # Constraints require pose mode, so moving here if not here already.
    if armature_obj.mode == "EDIT":
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="POSE")

    pose_bones = armature_obj.pose.bones

    def constraint_on(bone_name, constraint_name):
        """The named constraint, or None if either the bone or it is missing."""
        pose_bone = pose_bones.get(bone_name)
        if pose_bone is None:
            return None
        return pose_bone.constraints.get(constraint_name)

    slider_bone_name = LEG_CONTROLLER_SIDES.get(side)
    if slider_bone_name is None:
        return changed

    slider_limit = constraint_on(slider_bone_name, SLIDER_LIMIT_CONSTRAINT_NAME)

    if slider_limit is None:
        return changed

    # The limit constraint is the source of truth for how far the controller
    # travels, so read the range back off it rather than hardcoding a copy --
    # retuning the limit then retunes every expression built below. Neither
    # controller's range gets sign-flipped, so both sides read the same
    # normalized 0..1 straight off their own max. A zero range would put a
    # division by zero into a driver, so bail instead.
    travel = {axis: slider_travel(slider_limit, axis) for axis in ("X", "Y", "Z")}
    flat = [axis for axis, distance in travel.items() if not distance]

    if flat:
        changed.append(f"Issue: {slider_bone_name} has no slide range on {', '.join(flat)}; cannot normalize drivers")
        return changed

    # :g keeps the expression readable in the driver editor. The value read
    # back off the constraint is a 32-bit float, so a plain f-string would
    # write "slider_x / 0.10000000149011612" into every driver.
    normalize = {axis: f"{distance:.6g}" for axis, distance in travel.items()}

    driven = 0

    # ------------------------ IK / FK "Switch" - slider that controls whether MCH leg follows FK or IK -----------------------------
    # Left (rest) = 0 = pure FK, all the way right = 1 = pure IK. The whole
    # IK chain reads the same slider, so one expression covers all four.
    ik_switch_expression = f"slider_x / {normalize['X']}"

    for bone_prefix in IK_SWITCH_BONES:
        ik_constraint = constraint_on(f"{bone_prefix}.{side}", IK_SWITCH_CONSTRAINT_NAME)
        if ik_constraint is None:
            continue

        add_slider_driver(ik_constraint, armature_obj, ik_switch_expression, axis="X", slider_bone=slider_bone_name)
        driven += 1

    # ------------------------ IK/FK widget auto-hide ------------------------
    # Same slider, same normalized 0..1 reading as the switch above -- past
    # the halfway point (half of whatever max_x the limit constraint allows)
    # the rig is IK, so the FK controls hide and the IK ones show; below
    # halfway it is the other way round.
    #
    # Driven on the pose bone itself (pose.bones["Name"].hide), not
    # data.bones[name].hide or pose.bones[name].bone.hide -- both looked
    # right but neither is a path driver_add can actually resolve back to an
    # ID through, so both silently added nothing.
    hide_while_fk_expression = f"({ik_switch_expression}) < 0.5"
    hide_while_ik_expression = f"({ik_switch_expression}) >= 0.5"

    for bone_prefix in IK_VISIBILITY_BONES:
        pose_bone = pose_bones.get(f"{bone_prefix}.{side}")
        if pose_bone is None:
            continue

        add_slider_driver(pose_bone, armature_obj, hide_while_fk_expression, axis="X", slider_bone=slider_bone_name, data_path="hide")
        driven += 1

    for bone_prefix in FK_VISIBILITY_BONES:
        pose_bone = pose_bones.get(f"{bone_prefix}.{side}")
        if pose_bone is None:
            continue

        add_slider_driver(pose_bone, armature_obj, hide_while_ik_expression, axis="X", slider_bone=slider_bone_name, data_path="hide")
        driven += 1

    # ------------------------ follow hip rotation slider ------------------------

    follow_rotation = constraint_on(f"MCH_INT_Leg_Socket.{side}", ROTATION_FOLLOW_CONSTRAINT_NAME)

    if follow_rotation is not None:
        add_slider_driver(follow_rotation, armature_obj, f"slider_y / {normalize['Y']}", axis="Y", slider_bone=slider_bone_name)

        driven += 1

    # ------------------------ IK follow hip or root ------------------------
    # Root and ORG_Hips are the two blend targets on the same armature
    # constraint, so their weights have to be complementary -- ORG_Hips rises
    # with the slider while Root falls, keeping the blend at 1.0 total.
    # All the way up on Z -> Hips 1 / Root 0. All the way down -> Root 1 / Hips 0.
    ik_parent = constraint_on(f"MCH_Parent_Foot_IK_Master.{side}", IK_PARENT_CONSTRAINT_NAME)

    if ik_parent is not None:
        # An armature constraint's targets have no name field to look up, so
        # they are matched on subtarget instead of trusting creation order to
        # survive a symmetrize. Both are centreline bones, so the names are
        # the same on either side.

        root_target = next((target for target in ik_parent.targets if target.subtarget == "Root"), None)

        hip_target = next((target for target in ik_parent.targets if target.subtarget == "ORG_Hips"), None)

        ik_follow_hip_expression = f"slider_z / {normalize['Z']}"

        if hip_target is not None:
            add_slider_driver(hip_target, armature_obj, ik_follow_hip_expression, axis="Z", slider_bone=slider_bone_name, data_path="weight")

            driven += 1

        if root_target is not None:
            add_slider_driver(root_target, armature_obj, f"1 - ({ik_follow_hip_expression})", axis="Z", slider_bone=slider_bone_name, data_path="weight")

            driven += 1

    # ------------------------ foot roll/bank split from WGT_Foot_Roll ------------------------

    foot_roll_source = f"WGT_Foot_Roll.{side}"

    if pose_bones.get(foot_roll_source) is not None:
        for bone_prefix, axis, expression in FOOT_ROLL_SPLIT_DRIVERS:
            pose_bone = pose_bones.get(f"{bone_prefix}.{side}")
            if pose_bone is None:
                continue

            # Only generate_leg_ik_fk_rig sets this, and only for .L -- enforce
            # it here too so the mirrored .R side gets it after symmetrize.
            pose_bone.rotation_mode = "XYZ"
            add_rotation_clamp_driver(pose_bone, armature_obj, expression, axis=axis, source_bone=foot_roll_source)

            driven += 1

    if driven:
        changed.append(f"{driven} driver(s) on .{side} -> {slider_bone_name}")

    return changed


def add_hand_drivers(context, armature_obj=None, side="L"):
    """Drive one arm's constraints from its hand properties controller slider.

    Unlike add_leg_drivers, PRPT_Left_Hand_Controller and
    PRPT_Right_Hand_Controller are both built directly by
    generate_arm_ik_fk_rig -- neither is a symmetrize-mirrored copy of the
    other, so neither one's local axes get the sign flip a mirrored bone
    would need. Every expression below reads straight off the signed range
    with no side-dependent inversion. See HAND_CONTROLLER_SIDES.

    Re-runnable and missing-bone-tolerant like add_leg_drivers: the .R side
    legitimately does not exist until the arm has been mirrored.
    """
    changed = []

    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    # Constraints require pose mode, so moving here if not here already.
    if armature_obj.mode == "EDIT":
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="POSE")

    pose_bones = armature_obj.pose.bones

    def constraint_on(bone_name, constraint_name):
        """The named constraint, or None if either the bone or it is missing."""
        pose_bone = pose_bones.get(bone_name)
        if pose_bone is None:
            return None
        return pose_bone.constraints.get(constraint_name)

    slider_bone_name = HAND_CONTROLLER_SIDES.get(side)
    if slider_bone_name is None:
        return changed

    slider_limit = constraint_on(slider_bone_name, SLIDER_LIMIT_CONSTRAINT_NAME)

    if slider_limit is None:
        return changed

    # The limit constraint is the source of truth for how far the controller
    # travels, same reasoning as add_leg_drivers -- but unlike that one,
    # neither hand controller's range gets sign-flipped, so both sides read
    # the same normalized 0..1 straight off their own max.
    travel = {axis: slider_travel(slider_limit, axis) for axis in ("X", "Y", "Z")}
    flat = [axis for axis, distance in travel.items() if not distance]

    if flat:
        changed.append(f"Issue: {slider_bone_name} has no slide range on {', '.join(flat)}; cannot normalize drivers")
        return changed

    normalize = {axis: f"{distance:.6g}" for axis, distance in travel.items()}

    driven = 0

    # ------------------------ IK / FK "Switch" - slider that controls whether MCH arm follows FK or IK -----------------------------
    # Left (rest) = 0 = pure FK, all the way right = 1 = pure IK. The whole
    # IK chain reads the same slider, so one expression covers all three.
    ik_switch_expression = f"slider_x / {normalize['X']}"

    for bone_prefix in ARM_IK_SWITCH_BONES:
        ik_constraint = constraint_on(f"{bone_prefix}.{side}", ARM_IK_SWITCH_CONSTRAINT_NAME)
        if ik_constraint is None:
            continue

        add_slider_driver(ik_constraint, armature_obj, ik_switch_expression, axis="X", slider_bone=slider_bone_name)
        driven += 1

    # ------------------------ IK/FK widget auto-hide ------------------------
    # Same slider, same normalized 0..1 reading as the switch above -- past
    # the halfway point the arm is IK, so the FK controls hide and the IK
    # ones show; below halfway it is the other way round. See add_leg_drivers
    # for why this is driven on the pose bone's own .hide rather than
    # .bone.hide.
    hide_while_fk_expression = f"({ik_switch_expression}) < 0.5"
    hide_while_ik_expression = f"({ik_switch_expression}) >= 0.5"

    for bone_prefix in ARM_IK_VISIBILITY_BONES:
        pose_bone = pose_bones.get(f"{bone_prefix}.{side}")
        if pose_bone is None:
            continue

        add_slider_driver(pose_bone, armature_obj, hide_while_fk_expression, axis="X", slider_bone=slider_bone_name, data_path="hide")
        driven += 1

    for bone_prefix in ARM_FK_VISIBILITY_BONES:
        pose_bone = pose_bones.get(f"{bone_prefix}.{side}")
        if pose_bone is None:
            continue

        add_slider_driver(pose_bone, armature_obj, hide_while_ik_expression, axis="X", slider_bone=slider_bone_name, data_path="hide")
        driven += 1

    # ------------------------ IK follow hips or root ------------------------
    # Root and ORG_Hips are the two blend targets on the same armature
    # constraint, so their weights have to be complementary -- ORG_Hips rises
    # with the slider while Root falls, keeping the blend at 1.0 total.
    # All the way up on Z -> Hips 1 / Root 0. All the way down -> Root 1 / Hips 0.
    ik_parent = constraint_on(f"MCH_IK_Hand_Parent.{side}", IK_PARENT_CONSTRAINT_NAME)

    if ik_parent is not None:
        # An armature constraint's targets have no name field to look up, so
        # they are matched on subtarget instead of trusting creation order to
        # survive a symmetrize. Both are centreline bones, so the names are
        # the same on either side.
        root_target = next((target for target in ik_parent.targets if target.subtarget == "Root"), None)

        hip_target = next((target for target in ik_parent.targets if target.subtarget == "ORG_Hips"), None)

        ik_follow_hip_expression = f"slider_z / {normalize['Z']}"

        if hip_target is not None:
            add_slider_driver(hip_target, armature_obj, ik_follow_hip_expression, axis="Z", slider_bone=slider_bone_name, data_path="weight")

            driven += 1

        if root_target is not None:
            add_slider_driver(root_target, armature_obj, f"1 - ({ik_follow_hip_expression})", axis="Z", slider_bone=slider_bone_name, data_path="weight")

            driven += 1

    # ------------------------ FK follow shoulder rotation ------------------------
    # Forward (away from Root) on Y -> influence 1, fully follows the shoulder.
    # Pulled back toward Root on Y -> influence 0.
    follow_shoulder = constraint_on(f"MCH_Intermediary_Arm_Socket.{side}", ARM_FOLLOW_SHOULDER_CONSTRAINT_NAME)

    if follow_shoulder is not None:
        add_slider_driver(follow_shoulder, armature_obj, f"slider_y / {normalize['Y']}", axis="Y", slider_bone=slider_bone_name)

        driven += 1

    if driven:
        changed.append(f"{driven} driver(s) on .{side} -> {slider_bone_name}")

    return changed


def add_spine_drivers(context, armature_obj, controller_bone, target_bone, rotation_constraint_name, scale_constraint_name):
    """Drive one follow-rotation/follow-scale blend from its properties controller slider.

    Generic over which bones/constraints it wires, so the same function
    covers PRPT_Head_Controller -> MCH_Intermediary_Head and
    PRPT_Neck_Controller -> MCH_Intermediary_Neck alike -- see
    HEAD_FOLLOW_DRIVERS and NECK_FOLLOW_DRIVERS. Home for any other
    generate_spine_rig-specific driver passes that show up later, the way
    add_leg_drivers is home for the leg's.

    Re-runnable like add_leg_drivers: add_slider_driver clears any existing
    driver on a property before rebuilding it.

    Unlike the leg controller, this slider only moves on X and Z -- Y is
    pinned to 0 by the LIMIT_LOCATION constraint generate_spine_rig builds on
    the controller -- so only those two axes are read for travel and
    normalized here. Asking slider_travel for Y's range too would find it
    flat by design and bail every driver out for a range that was never
    meant to be driven in the first place.

    X drives the rotation-follow constraint's influence directly (slider at
    0 -> 0, does not follow; slider at max -> 1, fully follows). Z drives the
    scale-follow constraint's influence the same way. A missing bone or
    constraint is skipped rather than raised on, same reasoning as
    add_leg_drivers: the neck side of this legitimately does not exist until
    its slider limit is built.
    """
    changed = []

    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    # Constraints require pose mode, so moving here if not here already.
    if armature_obj.mode == "EDIT":
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="POSE")

    pose_bones = armature_obj.pose.bones

    def constraint_on(bone_name, constraint_name):
        """The named constraint, or None if either the bone or it is missing."""
        pose_bone = pose_bones.get(bone_name)
        if pose_bone is None:
            return None
        return pose_bone.constraints.get(constraint_name)

    slider_limit = constraint_on(controller_bone, SLIDER_LIMIT_CONSTRAINT_NAME)

    if slider_limit is None:
        return changed

    travel = {axis: slider_travel(slider_limit, axis) for axis in ("X", "Z")}
    flat = [axis for axis, distance in travel.items() if not distance]

    if flat:
        changed.append(f"Issue: {controller_bone} has no slide range on {', '.join(flat)}; cannot normalize drivers")
        return changed

    normalize = {axis: f"{distance:.6g}" for axis, distance in travel.items()}

    driven = 0

    rotation_constraint = constraint_on(target_bone, rotation_constraint_name)
    if rotation_constraint is not None:
        add_slider_driver(rotation_constraint, armature_obj, f"slider_x / {normalize['X']}", axis="X", slider_bone=controller_bone)
        driven += 1

    scale_constraint = constraint_on(target_bone, scale_constraint_name)
    if scale_constraint is not None:
        add_slider_driver(scale_constraint, armature_obj, f"slider_z / {normalize['Z']}", axis="Z", slider_bone=controller_bone)
        driven += 1

    if driven:
        changed.append(f"{driven} driver(s) on {target_bone} -> {controller_bone}")

    return changed


def add_all_drivers(context, armature_obj=None):
    """Run every driver pass in the rig, both sides.

    The one-stop entry point behind the "Add All Drivers" button. Each limb
    gets its own pass below, and each pass skips quietly when the bones it
    wants are not there, so this stays safe to press at any point after the
    rig has been generated.
    """
    changed = []

    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    for side in ("L", "R"):
        changed += add_leg_drivers(context, armature_obj, side=side)
        changed += add_hand_drivers(context, armature_obj, side=side)

    changed += add_spine_drivers(context, armature_obj, *HEAD_FOLLOW_DRIVERS)
    changed += add_spine_drivers(context, armature_obj, *NECK_FOLLOW_DRIVERS)

    return changed


def symmetrize_rig(context, armature_obj=None):
    """Mirror every ".L" bone onto the right side. Returns a list of what changed.

    Named for the whole rig rather than the deformation skeleton it started
    out on, because the ".L" sweep below now catches every side-suffixed bone
    the builders make -- DEF_, ORG_, FK_, IK_, MCH_, WGT_, VIS_ and the tweaks
    alike, not only the DEF_ chain.

    The PRPT_ properties bones are the deliberate exception, and they exclude
    themselves: each builder makes both sides up front as PRPT_Left_* and
    PRPT_Right_*, with no ".L"/".R" suffix for this pass to match. That is not
    a naming accident -- a mirrored bone gets its local X flipped, which would
    invert the slider travel the drivers normalize against. See
    HAND_CONTROLLER_SIDES/LEG_CONTROLLER_SIDES.

    symmetrize does the rest of the job: the ".L" -> ".R" rename, negating X on
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

    bone_count_before_symmetrize = len(edit_bones)
    bpy.ops.armature.symmetrize(direction="POSITIVE_X")
    bones_created = len(armature_obj.data.edit_bones) - bone_count_before_symmetrize

    if bones_created:
        changed.append(f"mirrored {bones_created} bone{'s' if bones_created > 1 else ''} to the right side")

    return changed


def organize_bone_collections(context, armature_obj=None):
    """Sort every rig bone into a collection keyed off its name.

    MCH_ -> MECHANISM, FK_ -> FK, IK_ -> IK, ORG_ -> ORIGINAL,
    *Tweak* -> TWEAK, WGT_ -> WIDGETS, VIS_ -> VISUAL,
    PRPT_ -> PROPERTY (every properties container and slider controller --
    hand, leg, neck and head alike).

    Order matters: move_bones_matching unassigns every other collection a
    bone sits in before adding its own, so a later pass wins any overlap --
    e.g. "WGT_IK_Toe.L" matches the IK_ pass too, but WGT_ runs after IK_ and
    puts it in WIDGETS. Likewise "MCH_Shin_Tweak_Scale_Compensation.L" matches
    both MCH_ and *Tweak*, so MCH_ runs after Tweak to keep it in MECHANISM.

    Must run in EDIT mode -- move_bones_matching only sees edit_bones.
    """
    changed = []

    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    if armature_obj.mode != "EDIT":
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")

    armature = armature_obj.data

    passes = (
        ("*Root*", "ROOT"),
        ("FK_*", "FK"),
        ("IK_*", "IK"),
        ("ORG_*", "ORIGINAL"),
        ("*Tweak*", "TWEAK"),
        ("MCH_*", "MECHANISM"),
        ("WGT_*", "WIDGETS"),
        ("VIS_*", "VISUAL"),
        ("PRPT_*", "PROPERTY"),
    )

    for pattern, collection_name in passes:
        collection, was_created = bone_collections.get_or_create_collection(armature, collection_name)
        if was_created:
            changed.append(f"created collection {collection_name}")
        moved = bone_collections.move_bones_matching(armature, pattern, collection)
        if moved:
            changed.append(f"{moved} bone(s) -> {collection_name}")

    # The DEF skeleton builder turns these on to make bone placement easier to
    # see while building; a finished rig with dozens of sorted bones is busier
    # with them on than off, so switch them off once sorting is done.
    if armature.show_names:
        changed.append("armature display: Names -> off")
        armature.show_names = False

    if armature.show_axes:
        changed.append("armature display: Axes -> off")
        armature.show_axes = False

    # ---- Hide layers that are no required to manipulate the rig. ----
    # ---- Layers we want on are in tuple below -----------------------
    collections_needed_for_control = ("FK", "TWEAK", "WIDGETS", "VISUAL", "PROPERTY")

    for collection in armature.collections_all:
        should_be_visible = collection.name in collections_needed_for_control
        if collection.is_visible != should_be_visible:
            collection.is_visible = should_be_visible
            changed.append(f"collection {collection.name} visibility -> {should_be_visible}")

    return changed


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Generate Leg Rig" BUTTON IS CLICKED =========
class EMANATE_OT_generate_leg_rig(bpy.types.Operator):
    bl_idname = NAMES_LEG_RIG.operator_idname
    bl_label = NAMES_LEG_RIG.label
    bl_description = NAMES_LEG_RIG.description
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
            self.report({"WARNING"}, f"{armature_obj.name} has no ORG_Hips bone -- run the ORG bone generator first")
            return {"CANCELLED"}

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[generate-leg-rig] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Generate Arm Rig" BUTTON IS CLICKED =========
class EMANATE_OT_generate_arm_rig(bpy.types.Operator):
    bl_idname = NAMES_ARM_RIG.operator_idname
    bl_label = NAMES_ARM_RIG.label
    bl_description = NAMES_ARM_RIG.description
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

        changed = generate_arm_ik_fk_rig(context, armature_obj)

        if not changed:
            self.report({"WARNING"}, f"{armature_obj.name} has no ORG arm bones -- run the ORG bone generator first")
            return {"CANCELLED"}

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[generate-arm-rig] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Generate Spine Rig" BUTTON IS CLICKED =========
class EMANATE_OT_generate_spine_rig(bpy.types.Operator):
    bl_idname = NAMES_SPINE_RIG.operator_idname
    bl_label = NAMES_SPINE_RIG.label
    bl_description = NAMES_SPINE_RIG.description
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

        changed = generate_spine_rig(context, armature_obj)

        if not changed:
            self.report({"WARNING"}, f"{armature_obj.name}: spine rig generator is having issues - check this function for further debugging")
            return {"CANCELLED"}

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[generate-spine-rig] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Symmetrize Rig" BUTTON IS CLICKED =========
class EMANATE_OT_symmetrize_rig(bpy.types.Operator):
    bl_idname = NAMES_SYMMETRIZE_RIG.operator_idname
    bl_label = NAMES_SYMMETRIZE_RIG.label
    bl_description = NAMES_SYMMETRIZE_RIG.description
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

        changed = symmetrize_rig(context, armature_obj)

        if not changed:
            self.report({"WARNING"}, f"{armature_obj.name} has no .L bones to mirror")
            return {"CANCELLED"}

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[symmetrize-rig] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Add All Drivers" BUTTON IS CLICKED =========
class EMANATE_OT_add_all_drivers(bpy.types.Operator):
    bl_idname = NAMES_ADD_DRIVERS.operator_idname
    bl_label = NAMES_ADD_DRIVERS.label
    bl_description = NAMES_ADD_DRIVERS.description
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

        # Both sides every time. Run before the mirror and the right side is
        # simply skipped; run after and this is the pass that gives the
        # mirrored limbs the drivers symmetrize could not copy.
        changed = add_all_drivers(context, armature_obj)

        if not changed:
            self.report({"WARNING"}, f"{armature_obj.name} has no properties controller to drive from -- run the rig generator first")
            return {"CANCELLED"}

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[add-all-drivers] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE "Organize Bone Collections" BUTTON IS CLICKED =========
class EMANATE_OT_organize_bone_collections(bpy.types.Operator):
    bl_idname = NAMES_ORGANIZE_COLLECTIONS.operator_idname
    bl_label = NAMES_ORGANIZE_COLLECTIONS.label
    bl_description = NAMES_ORGANIZE_COLLECTIONS.description
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

        changed = organize_bone_collections(context, armature_obj)

        if not changed:
            self.report({"INFO"}, f"{armature_obj.name}: no matching bones found")
            return {"FINISHED"}

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[organize-collections] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
        return {"FINISHED"}


# ========= THIS IS THE PANEL THAT OPENS WHEN THE BUTTON IS CLICKED =========
class EMANATE_PT_rigging_tools(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        layout.operator(NAMES_LEG_RIG.operator_idname)
        layout.operator(NAMES_ARM_RIG.operator_idname)
        layout.operator(NAMES_SPINE_RIG.operator_idname)
        layout.operator(NAMES_SYMMETRIZE_RIG.operator_idname)
        layout.operator(NAMES_ADD_DRIVERS.operator_idname)
        layout.operator(NAMES_ORGANIZE_COLLECTIONS.operator_idname)


_classes = (
    EMANATE_OT_generate_leg_rig,
    EMANATE_OT_generate_arm_rig,
    EMANATE_OT_generate_spine_rig,
    EMANATE_OT_symmetrize_rig,
    EMANATE_OT_add_all_drivers,
    EMANATE_OT_organize_bone_collections,
    EMANATE_PT_rigging_tools,
)


def register():
    naming.check_classes((EMANATE_OT_generate_leg_rig,), NAMES_LEG_RIG)
    naming.check_classes((EMANATE_OT_generate_arm_rig,), NAMES_ARM_RIG)
    naming.check_classes((EMANATE_OT_generate_spine_rig,), NAMES_SPINE_RIG)
    naming.check_classes((EMANATE_OT_symmetrize_rig,), NAMES_SYMMETRIZE_RIG)
    naming.check_classes((EMANATE_OT_add_all_drivers,), NAMES_ADD_DRIVERS)
    naming.check_classes((EMANATE_OT_organize_bone_collections,), NAMES_ORGANIZE_COLLECTIONS)
    naming.check_classes((EMANATE_PT_rigging_tools,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
