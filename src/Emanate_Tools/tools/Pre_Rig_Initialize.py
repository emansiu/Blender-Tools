import bpy

from .. import naming_unity as naming

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
                # so filter rather than trusting spaces.active.
                if space.type != "VIEW_3D":
                    continue
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
    root.tail = (0, 1, 0)

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
    DEF_Arm_left.use_connect = False
    # --- Left Forearm 01 ---
    DEF_Forearm_01_left = armature_data.edit_bones.new("DEF_Forearm_01.L")
    DEF_Forearm_01_left.head = (0.37, 0, 1.25)
    DEF_Forearm_01_left.tail = (0.53, 0, 1.25)
    DEF_Forearm_01_left.parent = DEF_Arm_left
    DEF_Forearm_01_left.use_connect = True
    # --- Left Forearm 02 ---
    DEF_Forearm_02_left = armature_data.edit_bones.new("DEF_Forearm_02.L")
    DEF_Forearm_02_left.head = (0.53, 0, 1.25)
    DEF_Forearm_02_left.tail = (0.69, 0, 1.25)
    DEF_Forearm_02_left.parent = DEF_Forearm_01_left
    DEF_Forearm_02_left.use_connect = True
    # --- Left Hand ---
    DEF_Hand_Left = armature_data.edit_bones.new("DEF_Hand.L")
    DEF_Hand_Left.head = (0.69, 0, 1.25)
    DEF_Hand_Left.tail = (0.85, 0, 1.25)
    DEF_Hand_Left.parent = DEF_Forearm_02_left
    DEF_Hand_Left.use_connect = False

    # ------- END OF BONE CREATION -------

    # bpy.ops.object.mode_set(mode='OBJECT')
    return armature_obj


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

    # symmetrize warns into the status bar if it is handed an empty selection.
    if not selected:
        return changed

    before = len(edit_bones)
    bpy.ops.armature.symmetrize(direction="POSITIVE_X")
    created = len(armature_obj.data.edit_bones) - before

    if created:
        changed.append(
            f"mirrored {created} bone{'s' if created > 1 else ''} to the right side"
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


_classes = (
    EMANATE_OT_pre_rig_initialize,
    EMANATE_OT_make_def_skeleton,
    EMANATE_OT_mirror_def_skeleton,
    EMANATE_PT_pre_rig_initialize,
)


def register():
    naming.check_classes(
        (EMANATE_OT_pre_rig_initialize, EMANATE_PT_pre_rig_initialize), NAMES
    )
    naming.check_classes((EMANATE_OT_make_def_skeleton,), NAMES_DEF_SKELETON)
    naming.check_classes((EMANATE_OT_mirror_def_skeleton,), NAMES_DEF_MIRROR)
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
