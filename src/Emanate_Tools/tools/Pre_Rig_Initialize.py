import bpy
from .. import naming_unity as naming

NAMES = naming.register_tool(
    "pre_rig_initialize",
    label="Initialize Pre-Rigging Settings",
    owner=__name__,
    description="checks settings for armature objects and scene settings to make sure we are working in an environment ready for rigs that can be exported to Unreal Engine",
)

NAMES_BASE_DEF_SKELETON = naming.register_tool(
    "make_base_def_skeleton",
    label="Make Base DEF Skeleton",
    owner=__name__,
    description="Not yet implemented",
)

# ------ Scene settings a rig destined for Unreal Engine expects -------------
TARGET_UNIT_SYSTEM = 'METRIC'
TARGET_SCALE_LENGTH = 0.01
TARGET_LENGTH_UNIT = 'CENTIMETERS'
TARGET_GRID_SCALE = 0.01
TARGET_RENDER_ENGINE = 'CYCLES'
TARGET_CYCLES_DEVICE = 'GPU'
TARGET_PIVOT_POINT = 'INDIVIDUAL_ORIGINS'

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
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                # An area keeps spaces from every type it has previously been,
                # so filter rather than trusting spaces.active.
                if space.type != 'VIEW_3D':
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
    return getattr(addon.preferences, "compute_device_type", 'NONE') != 'NONE'


# ========= THIS IS THE OPERATOR THAT RUNS WHEN THE BUTTON IS CLICKED =========
class EMANATE_OT_pre_rig_initialize(bpy.types.Operator):

    bl_idname = NAMES.operator_idname
    bl_label = "Set Up Scene" # This is the label that will be displayed in the button
    bl_description = NAMES.description
    bl_options = {'REGISTER', 'UNDO'}

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
                {'WARNING'},
                "No GPU backend selected in Preferences > System; "
                "Cycles will fall back to CPU"
            )

        if not changed:
            self.report({'INFO'}, "Scene already initialized")
            return {'FINISHED'}

        # Print every change to the console first, then one summary in the
        # status bar -- report() only keeps the last message it is given.
        for change in changed:
            print(f"[pre-rig] {change}")

        self.report({'INFO'}, f"Fixed: {'; '.join(changed)}")
        return {'FINISHED'}


# ========= NOT YET IMPLEMENTED =========
class EMANATE_OT_make_base_def_skeleton(bpy.types.Operator):

    bl_idname = NAMES_BASE_DEF_SKELETON.operator_idname
    bl_label = NAMES_BASE_DEF_SKELETON.label
    bl_description = NAMES_BASE_DEF_SKELETON.description
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return {'FINISHED'}

# ========= THIS IS THE PANEL THAT OPENS WHEN THE BUTTON IS CLICKED =========
class EMANATE_PT_pre_rig_initialize(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, MATCH_UNREAL_UNITS_PROP)
        layout.operator(NAMES.operator_idname)
        layout.operator(NAMES_BASE_DEF_SKELETON.operator_idname)


_classes = (
    EMANATE_OT_pre_rig_initialize,
    EMANATE_OT_make_base_def_skeleton,
    EMANATE_PT_pre_rig_initialize,
)


def register():
    naming.check_classes((EMANATE_OT_pre_rig_initialize, EMANATE_PT_pre_rig_initialize), NAMES)
    naming.check_classes((EMANATE_OT_make_base_def_skeleton,), NAMES_BASE_DEF_SKELETON)
    for cls in _classes:
        bpy.utils.register_class(cls)

    #------ add the checkbox to the scene properties so it can be accessed by the operator ------
    setattr(bpy.types.Scene, MATCH_UNREAL_UNITS_PROP, bpy.props.BoolProperty(
        name="Change Blender Units to Match Unreal",
        description="Unit System remains metric. Blender scale is set to 0.01 and length unit is set to centimeters. Unreal as of 2025 will multiply rigs up by 100x, so this compensates for that. It is a toggle right now because this may not be an issue anymore in newer versions of blender and unreal",
        default=False,
        update=match_unreal_units_update,
    ))


def unregister():
    delattr(bpy.types.Scene, MATCH_UNREAL_UNITS_PROP)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)