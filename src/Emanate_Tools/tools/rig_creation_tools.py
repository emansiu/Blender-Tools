import bpy
from mathutils import Vector

from ..helpers import bone_collections, deform_cleanup, widgets
from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "rigging_tools",
    label="Rigging Tools",
    owner=__name__,
    description="Container panel for the rig-creation tools: build the switchable FK/IK rig, mirror the deformation skeleton, wire drivers, and organize bone collections",
    order=20,
)

NAMES_MAKE_RIG = naming.register_tool("generate_rigs_for_body", label="Generate Rig", owner=__name__, description="Creates flexible rig with switchable fk/ik arms and legs.")
NAMES_DEF_MIRROR = naming.register_tool("mirror_deformation_skeleton", label="Mirror .L to .R over X", owner=__name__, description="Mirrors anything ending in .L onto the right side")
NAMES_ADD_DRIVERS = naming.register_tool(
    "add_all_drivers",
    label="Add All Drivers",
    owner=__name__,
    description="Wires every driven constraint in the rig, both sides, to its properties controller slider. Safe to re-run, and meant to be run after mirroring -- symmetrize copies constraints but not drivers",
)
NAMES_ORGANIZE_COLLECTIONS = naming.register_tool(
    "organize_bone_collections", label="Organize Bone Collections", owner=__name__, description="Sorts MCH_/FK_/IK_/ORG_/Tweak/WGT_/VIS_ bones into matching bone collections"
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
SLIDER_LIMIT_CONSTRAINT_NAME = "PROPERTIES_SLIDER_LIMIT"

# Bones carrying an IK_SWITCH_CONSTRAINT_NAME constraint, in chain order.
# Side-less -- the driver pass appends ".L" or ".R".
IK_SWITCH_BONES = ("MCH_SWITCH_Thigh", "MCH_SWITCH_Shin", "MCH_SWITCH_Foot", "MCH_SWITCH_Toe")

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


def add_slider_driver(owner, armature_obj, expression, axis="X", slider_bone="WGT_Leg_Properties_Controller.L", data_path="influence"):
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


def create_bone(edit_bones, name, head, tail, parent=None, roll=None, align_roll=None, length=1.0, connect=False):
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

    if length != 1.0:
        bone.length *= length

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
    MCH_Parent_Foot_IK_Master_Left = create_bone(edit_bones, "MCH_Parent_Foot_IK_Master.L", head=foot_ik_master_head, tail=foot_ik_master_tail, length=0.6)

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
    # --- Left Thigh Tweak SCALE COMPENSATION CORRECTION ---------------------------------------------------------
    MCH_Thigh_Tweak_Scale_Compensation_Left = create_bone(
        edit_bones, "MCH_Thigh_Tweak_Scale_Compensation.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.tail, parent=MCH_SWITCH_Thigh_Left, roll=ORG_Thigh_Left.roll, length=0.25
    )

    # ---TWEAK MCH Left Thigh---------------------------------------------------------
    Thigh_Tweak_Left = create_bone(
        edit_bones, "Thigh_Tweak.L", head=ORG_Thigh_Left.head, tail=ORG_Thigh_Left.tail, parent=MCH_Thigh_Tweak_Scale_Compensation_Left, roll=ORG_Thigh_Left.roll, length=0.5
    )

    # --- TWEAK MCH Left Shin Tweak SCALE COMPENSATION CORRECTION---------------------------------------------------------
    MCH_Shin_Tweak_Scale_Compensation_Left = create_bone(
        edit_bones, "MCH_Shin_Tweak_Scale_Compensation.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=MCH_SWITCH_Shin_Left, roll=ORG_Shin_Left.roll, length=0.25
    )

    # --- TWEAK MCH Left Shin ---------------------------------------------------------
    Shin_Tweak_Left = create_bone(edit_bones, "Shin_Tweak.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=MCH_Shin_Tweak_Scale_Compensation_Left, roll=ORG_Shin_Left.roll, length=0.5)

    # --- TWEAK MCH Left Foot ---------------------------------------------------------
    Foot_Tweak_Left = create_bone(edit_bones, "Foot_Tweak.L", head=ORG_Foot_Left.head, tail=ORG_Foot_Left.tail, parent=MCH_SWITCH_Foot_Left, roll=ORG_Foot_Left.roll, length=0.5)

    # --- TWEAK MCH Left Toe  ---------------------------------------------------------
    Toe_Tweak_Left = create_bone(edit_bones, "Toe_Tweak.L", head=ORG_Toe_Left.head, tail=ORG_Toe_Left.tail, parent=MCH_SWITCH_Toe_Left, roll=ORG_Toe_Left.roll, length=0.5)

    # --- TWEAK MCH Left Toe TIP  ---------------------------------------------------------
    Toe_Tip_Tweak_Left = create_bone(edit_bones, "Toe_Tip_Tweak.L", head=ORG_Toe_Left.tail, tail=ORG_Toe_Left.tail - Vector((0.00, 0.07, 0.0)), parent=MCH_SWITCH_Toe_Left, roll=ORG_Toe_Left.roll)

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

    # ---TEMP IK Pole Target base (fastest way to position pole exactly as we need ---------------------------------------------------------
    TEMP_Left_Leg_Pole = create_bone(
        edit_bones, "TEMP_Left_Leg_Pole", head=ORG_Thigh_Left.head + Vector((0.0, -0.4, 0.0)), tail=ORG_Thigh_Left.tail + Vector((0.0, -0.4, 0.0)), roll=ORG_Thigh_Left.roll
    )

    # ---IK Pole Target left leg ---------------------------------------------------------
    IK_Pole_Left = create_bone(
        edit_bones, "WGT_IK_Pole.L", head=TEMP_Left_Leg_Pole.tail, tail=TEMP_Left_Leg_Pole.tail + Vector((0.0, 0.075, 0.0)), parent=WGT_Foot_IK_Master_Left, align_roll=Vector((0.0, 0.0, 1.0))
    )

    # TEMP_Left_Leg_Pole was only needed to derive the pole position/roll above; discard it now.
    edit_bones.remove(TEMP_Left_Leg_Pole)

    # ---IK Pole Target Visualization bone ---------------------------------------------------------
    VIS_IK_Pole_Left = create_bone(edit_bones, "VIS_IK_Pole.L", head=IK_Thigh_Left.tail, tail=IK_Pole_Left.head, parent=IK_Thigh_Left)

    # ---IK Left Shin---------------------------------------------------------
    IK_Shin_Left = create_bone(edit_bones, "IK_Shin.L", head=ORG_Shin_Left.head, tail=ORG_Shin_Left.tail, parent=IK_Thigh_Left, roll=ORG_Shin_Left.roll, connect=True)

    # ---IK Left Foot---------------------------------------------------------
    IK_Foot_Left = create_bone(edit_bones, "IK_Foot.L", head=ORG_Foot_Left.head, tail=ORG_Foot_Left.tail, parent=MCH_Foot_Bank_02_Left, roll=ORG_Foot_Left.roll)

    # ---IK Left Toe MCH bone---------------------------------------------------------
    MCH_Toe_IK_Left = create_bone(edit_bones, "MCH_Toe_IK.L", head=ORG_Toe_Left.head, tail=ORG_Toe_Left.tail, parent=IK_Foot_Left, roll=MCH_Foot_Roll_Left.roll, length=0.6)

    # ---IK Left Toe WGT Control ---------------------------------------------------------
    WGT_IK_Toe_Left = create_bone(edit_bones, "WGT_IK_Toe.L", head=ORG_Toe_Left.head, tail=ORG_Toe_Left.tail, parent=MCH_Toe_IK_Left, roll=ORG_Toe_Left.roll)

    # ------- Final Property Bones ---------------
    # Parented to Root rather than WGT_Foot_IK_Master_Left: the properties
    # controller slider that lives under this bone drives the Armature
    # constraint weights on MCH_Parent_Foot_IK_Master_Left, and that bone is
    # WGT_Foot_IK_Master_Left's parent -- nesting the slider chain under its
    # own child creates a dependency cycle (the ancestor's constraint driver
    # would need the descendant's pose done before the descendant's pose can
    # be done). A fixed screen position next to the foot control does not
    # require inheriting the foot control's pose anyway.
    WGT_Leg_Properties_Left = create_bone(
        edit_bones, "WGT_Leg_Properties.L", head=WGT_Foot_IK_Master_Left.head + Vector((0.0, -0.3, 0.0)), tail=WGT_Foot_IK_Master_Left.head + Vector((0.0, -0.2, 0.0)), parent=Root
    )

    WGT_Leg_Properties_Controller_Left = create_bone(
        edit_bones, "WGT_Leg_Properties_Controller.L", head=WGT_Leg_Properties_Left.head, tail=WGT_Leg_Properties_Left.tail, parent=WGT_Leg_Properties_Left, length=0.4
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
    # --- leg properties control limits ----
    limit_location_properties_controller = pose_bones["WGT_Leg_Properties_Controller.L"].constraints.new("LIMIT_LOCATION")
    # Named because the driver pass reads max_x back off this constraint to
    # normalize the slider -- this is the single source of truth for how far
    # the controller travels, so nothing downstream hardcodes the number.
    limit_location_properties_controller.name = SLIDER_LIMIT_CONSTRAINT_NAME
    limit_location_properties_controller.owner_space = "LOCAL"
    limit_location_properties_controller.use_min_x = limit_location_properties_controller.use_min_y = limit_location_properties_controller.use_min_z = True
    limit_location_properties_controller.use_max_x = limit_location_properties_controller.use_max_y = limit_location_properties_controller.use_max_z = True
    limit_location_properties_controller.use_transform_limit = True
    limit_location_properties_controller.min_x = limit_location_properties_controller.min_y = limit_location_properties_controller.min_z = 0
    max_distance_for_controller = 0.1
    limit_location_properties_controller.max_x = limit_location_properties_controller.max_y = limit_location_properties_controller.max_z = max_distance_for_controller

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
    widgets.assign_widget(pose_bones["Root"], "WGT_Four_Arrow_Centered_Circle", wire_width=2, rotation_x=90, color="THEME11")

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
    TWEAK_WIDGET_SIZE = 0.05  # armature units, tune to taste

    for name in ("Thigh_Tweak.L", "Shin_Tweak.L", "Foot_Tweak.L", "Toe_Tweak.L", "Toe_Tip_Tweak.L"):
        widgets.assign_widget(pose_bones[name], "WGT_Centered_IcoSphere", scale_x=TWEAK_WIDGET_SIZE, scale_y=TWEAK_WIDGET_SIZE, scale_z=TWEAK_WIDGET_SIZE, use_bone_size=False, color="THEME09")

    # --------- Properties Container ----------
    widgets.assign_widget(pose_bones["WGT_Leg_Properties.L"], "WGT_Left_Foot_Properties", wire_width=1, color="THEME04")

    # --------- Properties Controller ----------
    widgets.assign_widget(pose_bones["WGT_Leg_Properties_Controller.L"], "WGT_Centered_IcoSphere", wire_width=1, color="THEME07")

    changed.append("copy scale on the thigh/shin compensation bones -> Root")
    changed.append("stretch-to on the shin/foot/toe/toe-tip tweaks")
    changed.append("MCH legs added")

    return changed


def add_leg_drivers(context, armature_obj=None, side="L"):
    """Drive one leg's constraints from its properties controller slider.

    Re-runnable: add_slider_driver clears any existing driver on a property
    before rebuilding it, so pressing the button twice rebuilds rather than
    accumulates.

    A missing bone or constraint is skipped rather than raised on -- the right
    side legitimately does not exist until the mirror has been run.

    Sides are not assumed to be identical: symmetrize flips the controller's
    X limit to run -1 -> 0 travel on the right, so every expression divides by
    the signed range read off that constraint. See slider_travel.
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

    slider_bone_name = f"WGT_Leg_Properties_Controller.{side}"
    slider_limit = constraint_on(slider_bone_name, SLIDER_LIMIT_CONSTRAINT_NAME)

    if slider_limit is None:
        return changed

    # The limit constraint is the source of truth for how far the controller
    # travels, so read the range back off it rather than hardcoding a copy --
    # retuning the limit then retunes every expression built below, and reading
    # it per axis is what absorbs the sign flip symmetrize puts on X. A zero
    # range would put a division by zero into a driver, so bail instead.
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
    # Dividing by the slide range normalizes the slide into the 0..1 that
    # influence expects. The whole IK chain reads the same slider, so one
    # expression covers all four.

    ik_switch_expression = f"slider_x / {normalize['X']}"

    if side == "R":
        # Mirroring flips .R's local X axis, so the same world-space drag that
        # pushes .L toward IK pushes .R the other way. Negating the normalized
        # reading re-syncs them: grabbing both and sliding the same screen
        # direction now moves both into IK, or both into FK, together. This
        # also flips what slider_x = 0 (rest) means on .R alone -- .R now
        # starts in IK rather than FK until it is dragged back.
        ik_switch_expression = f"1 - ({ik_switch_expression})"

    for bone_prefix in IK_SWITCH_BONES:
        ik_constraint = constraint_on(f"{bone_prefix}.{side}", IK_SWITCH_CONSTRAINT_NAME)
        if ik_constraint is None:
            continue

        add_slider_driver(ik_constraint, armature_obj, ik_switch_expression, axis="X", slider_bone=slider_bone_name)
        driven += 1

    # ------------------------ IK/FK widget auto-hide ------------------------
    # Same slider, same normalized 0..1 reading as the switch above -- past
    # the halfway point (which is what comparing the normalized value to 0.5
    # means: half of whatever max_x the limit constraint allows, on either
    # side's sign) the rig is IK, so the FK controls hide and the IK ones
    # show; below halfway it is the other way round.
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
    # constraint, so their weights have to be complementary -- Root rises
    # with the slider while ORG_Hips falls, keeping the blend at 1.0 total.

    ik_parent = constraint_on(f"MCH_Parent_Foot_IK_Master.{side}", IK_PARENT_CONSTRAINT_NAME)

    if ik_parent is not None:
        # An armature constraint's targets have no name field to look up, so
        # they are matched on subtarget instead of trusting creation order to
        # survive a symmetrize. Both are centreline bones, so the names are
        # the same on either side.

        root_target = next((target for target in ik_parent.targets if target.subtarget == "Root"), None)

        hip_target = next((target for target in ik_parent.targets if target.subtarget == "ORG_Hips"), None)

        ik_follow_hip_or_root_expression = f"slider_z / {normalize['Z']}"

        if root_target is not None:
            add_slider_driver(root_target, armature_obj, ik_follow_hip_or_root_expression, axis="Z", slider_bone=slider_bone_name, data_path="weight")

            driven += 1

        if hip_target is not None:
            add_slider_driver(hip_target, armature_obj, f"1 - ({ik_follow_hip_or_root_expression})", axis="Z", slider_bone=slider_bone_name, data_path="weight")

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


def add_all_drivers(context, armature_obj=None):
    """Run every driver pass in the rig, both sides.

    The one-stop entry point behind the "Add All Drivers" button. Each limb
    gets its own pass below -- arms will need their own, since they hang off a
    different properties controller -- and each pass skips quietly when the
    bones it wants are not there, so this stays safe to press at any point
    after the rig has been generated.
    """
    changed = []

    if armature_obj is None:
        armature_obj = context.object
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return changed

    for side in ("L", "R"):
        changed += add_leg_drivers(context, armature_obj, side=side)

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
        changed.append(f"mirrored {bones_created} bone{'s' if bones_created > 1 else ''} to the right side")

    # ========== Re-assigning widgets that had text which could not be mirrored ==============
    # ---- need to move to pose mode ------
    bpy.ops.object.mode_set(mode="POSE")
    pose_bones = armature_obj.pose.bones    
    widgets.assign_widget(pose_bones["WGT_Leg_Properties.R"], "WGT_Right_Foot_Properties", wire_width=1, color="THEME04")
    pose_bones["WGT_Leg_Properties_Controller.L"].location[0] = 0.1

    return changed


def organize_bone_collections(context, armature_obj=None):
    """Sort every rig bone into a collection keyed off its name.

    MCH_ -> MECHANISM, FK_ -> FK, IK_ -> IK, ORG_ -> ORIGINAL,
    *Tweak* -> TWEAK, WGT_ -> WIDGETS, VIS_ -> VISUAL.

    Order matters: move_bones_matching unassigns every other collection a
    bone sits in before adding its own, so a later pass wins any overlap --
    e.g. "WGT_IK_Toe.L" matches the IK_ pass too, but WGT_ runs after IK_ and
    puts it in WIDGETS.

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

    passes = (("*Root*", "ROOT"), ("MCH_*", "MECHANISM"), ("FK_*", "FK"), ("IK_*", "IK"), ("ORG_*", "ORIGINAL"), ("*Tweak*", "TWEAK"), ("WGT_*", "WIDGETS"), ("VIS_*", "VISUAL"))

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

    return changed


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
            self.report({"WARNING"}, f"{armature_obj.name} has no ORG_Hips bone -- run the ORG bone generator first")
            return {"CANCELLED"}

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[generate-rig] {change}")

        self.report({"INFO"}, f"{armature_obj.name}: {'; '.join(changed)}")
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

        changed += deform_cleanup.sync_deform_flags(armature_obj)

        for change in changed:
            print(f"[def-mirror] {change}")

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
        layout.operator(NAMES_MAKE_RIG.operator_idname)
        layout.operator(NAMES_DEF_MIRROR.operator_idname)
        layout.operator(NAMES_ADD_DRIVERS.operator_idname)
        layout.operator(NAMES_ORGANIZE_COLLECTIONS.operator_idname)


_classes = (EMANATE_OT_generate_rig, EMANATE_OT_mirror_def_skeleton, EMANATE_OT_add_all_drivers, EMANATE_OT_organize_bone_collections, EMANATE_PT_rigging_tools)


def register():
    naming.check_classes((EMANATE_OT_generate_rig,), NAMES_MAKE_RIG)
    naming.check_classes((EMANATE_OT_mirror_def_skeleton,), NAMES_DEF_MIRROR)
    naming.check_classes((EMANATE_OT_add_all_drivers,), NAMES_ADD_DRIVERS)
    naming.check_classes((EMANATE_OT_organize_bone_collections,), NAMES_ORGANIZE_COLLECTIONS)
    naming.check_classes((EMANATE_PT_rigging_tools,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
