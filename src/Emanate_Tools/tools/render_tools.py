"""Render-engine presets.

Buttons that stamp a whole Cycles configuration onto the scene in one click,
the way pre_rig_tools.fix_render_settings stamps the unit/device basics onto a
fresh rig scene.
"""

import bpy

from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "render_tools",
    label="Rendering",
    owner=__name__,
    description="Render engine presets",
    order=90,
)

NAMES_CINEMA_BASE = naming.register_tool(
    "cinema_base",
    label="Cinema Base",
    owner=__name__,
    description=(
        "Sets up Cycles on GPU with this studio's baseline sampling, light path, "
        "volume and performance settings"
    ),
)

NAMES_FAST_CLEAN_STATIC = naming.register_tool(
    "fast_clean_static",
    label="Fast Clean Static",
    owner=__name__,
    description="Not implemented yet",
)

# ------ Cinema Base preset ---------------------------------------------------
# One (attribute, value) pair per field in Render Properties > Cycles.
# Grouped and ordered the way the panel groups them, so a diff against the UI
# is easy to read. Applied with getattr/hasattr guards -- see apply_cinema_base
# -- because these names have moved between Blender versions before (Light
# Tree, the sampling pattern options) and a renamed one should be skipped and
# reported, not crash the operator.
CINEMA_BASE_CYCLES_SETTINGS = (
    ("device", "GPU"),

    # Sampling > Viewport
    ("use_preview_adaptive_sampling", False),
    ("preview_samples", 256),
    ("use_preview_denoising", False),

    # Sampling > Render
    ("use_adaptive_sampling", True),
    ("adaptive_threshold", 0.03),
    ("samples", 2048),
    ("adaptive_min_samples", 16),
    ("time_limit", 0.0),
    ("use_denoising", False),

    # Sampling > Advanced
    ("sampling_pattern", "AUTOMATIC"),
    ("seed", 0),
    ("sample_offset", 0),
    ("auto_scrambling_distance", False),
    ("preview_scrambling_distance", False),
    ("scrambling_distance", 1.0),
    ("min_light_bounces", 0),
    ("min_transparent_bounces", 0),

    # Light Paths > Light Sampling
    ("use_light_tree", False),
    ("light_sampling_threshold", 0.06),

    # Light Paths > Max Bounces
    ("max_bounces", 2),
    ("diffuse_bounces", 2),
    ("glossy_bounces", 2),
    ("transmission_bounces", 2),
    ("volume_bounces", 0),
    ("transparent_max_bounces", 2),

    # Light Paths > Clamping
    ("sample_clamp_direct", 0.0),
    ("sample_clamp_indirect", 100.0),

    # Light Paths > Caustics
    ("blur_glossy", 1.0),
    ("caustics_reflective", True),
    ("caustics_refractive", True),

    # Light Paths > Fast GI Approximation
    ("use_fast_gi", False),

    # Volumes
    ("volume_step_rate", 1.0),
    ("volume_preview_step_rate", 1.0),
    ("volume_max_steps", 4),
)
# ------------------------------------------------------------------------------


def _set(obj, attr, value, changed, missing):
    """setattr(obj, attr, value), noting what moved and what wasn't there."""
    if not hasattr(obj, attr):
        missing.append(attr)
        return
    current = getattr(obj, attr)
    if current != value:
        changed.append(f"{attr} {current!r} -> {value!r}")
        setattr(obj, attr, value)


def apply_cinema_base(scene):
    """Write the Cinema Base preset onto `scene`. Returns (changed, missing)."""
    changed = []
    missing = []

    _set(scene.render, "engine", "CYCLES", changed, missing)

    # scene.cycles only exists while the Cycles add-on is enabled -- see
    # pre_rig_tools.fix_render_settings for the same guard.
    cycles = getattr(scene, "cycles", None)
    if cycles is None:
        missing.append("cycles (Cycles add-on not enabled)")
        return changed, missing

    for attr, value in CINEMA_BASE_CYCLES_SETTINGS:
        _set(cycles, attr, value, changed, missing)

    # Persistent Data sits in Cycles' Performance panel but is a general render
    # setting, shared with every engine -- it lives on render, not cycles.
    _set(scene.render, "use_persistent_data", True, changed, missing)

    return changed, missing


# ------ Preferences check, shared by every preset below ---------------------
# A preset that sets scene.cycles.device = 'GPU' still renders on the CPU if
# Preferences > System has no compute backend picked, or has one picked with
# every device switched off -- see pre_rig_tools.gpu_backend_is_configured,
# which only warns about this. Every button below goes one further and fixes
# it: point Cycles at the fastest backend this machine actually has, switch on
# every device of that type, and put the UI/viewport backend on Vulkan.
#
# Fastest-to-slowest, matched to whichever vendor's card is actually in the
# machine -- OptiX is Nvidia-only and the fastest of the three Nvidia paths,
# so it wins whenever it's on the list at all.
GPU_COMPUTE_TYPES_BY_SPEED = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")


def ensure_optimal_render_preferences():
    """Configure Preferences > System for fast Cycles renders. Returns (changed, missing).

    Cycles device detection and the Vulkan graphics backend are both dynamic,
    build-dependent enums -- what a machine offers depends on what GPU is in
    it and what this copy of Blender was compiled with -- so both are read
    back from the live API instead of assumed, the same reasoning
    CINEMA_BASE_CYCLES_SETTINGS uses hasattr guards for.
    """
    changed = []
    missing = []

    cycles_addon = bpy.context.preferences.addons.get("cycles")
    if cycles_addon is None:
        missing.append("cycles preferences (Cycles add-on not enabled)")
    else:
        cycles_prefs = cycles_addon.preferences
        # get_device_types actually probes the hardware (via _cycles), unlike
        # a static enum_items lookup, which would just list every backend this
        # Blender build knows how to talk to, hardware or not.
        available = {item[0] for item in cycles_prefs.get_device_types(bpy.context)}
        device_type = next((candidate for candidate in GPU_COMPUTE_TYPES_BY_SPEED if candidate in available), None)

        if device_type is None:
            missing.append("a GPU compute backend (Preferences > System only offers CPU on this machine)")
        else:
            if cycles_prefs.compute_device_type != device_type:
                changed.append(f"compute_device_type {cycles_prefs.compute_device_type!r} -> {device_type!r}")
                cycles_prefs.compute_device_type = device_type

            # get_devices_for_type also appends the CPU entry after the GPUs of
            # the chosen type, so it has to be filtered back down to just the
            # GPUs -- the CPU checkbox is left exactly as the user set it.
            gpu_devices = [device for device in cycles_prefs.get_devices_for_type(device_type) if device.type == device_type]
            if not gpu_devices:
                missing.append(f"a {device_type} device (backend supported but none detected)")
            for device in gpu_devices:
                if not device.use:
                    changed.append(f"device {device.name!r} use False -> True")
                    device.use = True

    system = bpy.context.preferences.system
    if hasattr(system, "gpu_backend"):
        current_backend = system.gpu_backend
        if current_backend != "VULKAN":
            try:
                system.gpu_backend = "VULKAN"
            except TypeError:
                # Raised for an enum identifier this build doesn't compile in
                # -- e.g. a Blender built without the Vulkan backend.
                missing.append("Vulkan graphics backend (not available in this Blender build)")
            else:
                changed.append(f"gpu_backend {current_backend!r} -> 'VULKAN' (takes effect after a restart)")
    else:
        missing.append("system.gpu_backend (not present on this Blender version)")

    return changed, missing


# ---------------------------------------------------------------------------
# Operators and panel
# ---------------------------------------------------------------------------


class EMANATE_OT_cinema_base(bpy.types.Operator):
    bl_idname = NAMES_CINEMA_BASE.operator_idname
    bl_label = NAMES_CINEMA_BASE.label
    bl_description = NAMES_CINEMA_BASE.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        changed, missing = ensure_optimal_render_preferences()
        preset_changed, preset_missing = apply_cinema_base(context.scene)
        changed += preset_changed
        missing += preset_missing

        if missing:
            self.report(
                {"WARNING"},
                f"Cinema Base: {len(missing)} setting(s) not found on this Blender "
                f"version, skipped: {', '.join(missing)}",
            )

        for line in changed:
            print(f"[cinema-base] {line}")

        if not changed:
            self.report({"INFO"}, "Cinema Base already applied")
        else:
            self.report({"INFO"}, f"Cinema Base applied ({len(changed)} setting(s) changed)")
        return {"FINISHED"}


class EMANATE_OT_fast_clean_static(bpy.types.Operator):
    bl_idname = NAMES_FAST_CLEAN_STATIC.operator_idname
    bl_label = NAMES_FAST_CLEAN_STATIC.label
    bl_description = NAMES_FAST_CLEAN_STATIC.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # The preset itself isn't implemented yet, but the device/backend
        # check every render button shares already is -- see
        # ensure_optimal_render_preferences.
        changed, missing = ensure_optimal_render_preferences()

        if missing:
            self.report(
                {"WARNING"},
                f"Fast Clean Static: {len(missing)} setting(s) not found on this Blender "
                f"version, skipped: {', '.join(missing)}",
            )
        for line in changed:
            print(f"[fast-clean-static] {line}")
        if changed:
            self.report({"INFO"}, f"Fast Clean Static: preferences updated ({len(changed)} setting(s) changed); preset not implemented yet")
        else:
            self.report({"WARNING"}, "Fast Clean Static: not implemented yet")
        return {"FINISHED"}


class EMANATE_PT_render_tools(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        layout.operator(NAMES_CINEMA_BASE.operator_idname, icon="SHADING_RENDERED")
        layout.operator(NAMES_FAST_CLEAN_STATIC.operator_idname, icon="RENDER_STILL")


_classes = (EMANATE_OT_cinema_base, EMANATE_OT_fast_clean_static, EMANATE_PT_render_tools)


def register():
    naming.check_classes((EMANATE_OT_cinema_base,), NAMES_CINEMA_BASE)
    naming.check_classes((EMANATE_OT_fast_clean_static,), NAMES_FAST_CLEAN_STATIC)
    naming.check_classes((EMANATE_PT_render_tools,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
