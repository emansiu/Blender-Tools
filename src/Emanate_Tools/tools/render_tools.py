"""Render-engine presets.

Buttons that stamp a whole Cycles configuration onto the scene in one click,
the way pre_rig_tools.fix_render_settings stamps the unit/device basics onto a
fresh rig scene.
"""

import difflib
import os
import re

import bpy
import bpy.utils.previews

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

NAMES_HDRI_LIGHTING = naming.register_tool(
    "hdri_lighting",
    label="HDRI Lighting",
    owner=__name__,
    description=(
        "Light the scene with the picked HDRI (full-range .hdr), hidden from the "
        "camera via Film > Transparent"
    ),
)

NAMES_HDRI_REFRESH = naming.register_tool(
    "hdri_refresh",
    label="Refresh HDRIs",
    owner=__name__,
    description="Rescan the HDRI folder and rebuild the thumbnails",
)

HDRI_CHOICE_PROP = naming.prop_name("hdri_choice")

NAMES_COMPOSITOR_SETUP = naming.register_tool(
    "compositor_setup",
    label="Compositor Setup",
    owner=__name__,
    description=(
        "Enable the production Cycles passes and build a compositor that rebuilds the "
        "beauty from light passes, with Cryptomatte, utility passes, light groups and EXR output"
    ),
)

COMP_DENOISE_PROP = naming.prop_name("comp_denoise")
COMP_OUTPUT_MODE_PROP = naming.prop_name("comp_output_mode")

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


# ------ HDRI Lighting ----------------------------------------------------------
# The world is lit from the full-range .hdr in each category's hdri_versions/
# folder. The matching JPEGs one folder up are 8-bit and clip the sun to plain
# white -- flat light, no real sun shadows -- so they are only used as picker
# thumbnails. Sampling cost per ray is the same either way; the .hdr only costs
# load time and VRAM, which Persistent Data (set by Cinema Base) pays once.
#
# The camera never sees the HDRI: Film > Transparent turns the background into
# alpha while diffuse/glossy/transmission rays still hit the world, so it
# lights and reflects in everything. Works the same in Cycles and EEVEE.

HDRI_COLLECTION_DIRNAME = "HDRI_COLLECTION"
HDRI_VERSIONS_DIRNAME = "hdri_versions"
HDRI_EXTENSIONS = (".hdr", ".exr")
THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png")
HDRI_WORLD_NAME = "Emanate_HDRI_World"

# Node names inside HDRI_WORLD_NAME, so a re-run can find and reuse them.
NODE_TEXCOORD = "EMANATE_HDRI_TexCoord"
NODE_MAPPING = "EMANATE_HDRI_Mapping"
NODE_ENVIRONMENT = "EMANATE_HDRI_Environment"
NODE_BACKGROUND = "EMANATE_HDRI_Background"
NODE_OUTPUT = "EMANATE_HDRI_Output"

# The add-on's top-level package (what AddonPreferences.bl_idname must be):
# this module is <package>.tools.render_tools.
ADDON_PACKAGE = __package__.rpartition(".")[0]

_previews = None      # bpy.utils.previews collection, live between register/unregister
_hdri_items = None    # cached EnumProperty items; Blender needs these strings kept alive


class EMANATE_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_PACKAGE

    hdri_library_dir: bpy.props.StringProperty(
        name="HDRI Collection Folder",
        description=(
            "Folder holding the HDRI categories (each with an hdri_versions subfolder). "
            "Leave empty to find HDRI_COLLECTION inside a registered asset library"
        ),
        subtype="DIR_PATH",
        default="",
        update=lambda self, context: clear_hdri_cache(),
    )

    def draw(self, context):
        self.layout.prop(self, "hdri_library_dir")
        found = find_hdri_collection_dir()
        self.layout.label(text=f"Using: {found}" if found else "No HDRI folder found", icon="WORLD")


def find_hdri_collection_dir():
    """The HDRI_COLLECTION folder, or None.

    Order: the add-on preference, then any asset library (Preferences > File
    Paths) that contains HDRI_COLLECTION, then the repo layout this add-on is
    developed in (src/Emanate_Tools/ next to assets/), for running from source.
    """
    # The preference may point straight at any folder of HDRI categories, so
    # it's trusted as-is when it exists.
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    if addon is not None and addon.preferences is not None:
        pref_dir = bpy.path.abspath(addon.preferences.hdri_library_dir)
        if pref_dir and os.path.isdir(pref_dir):
            return os.path.normpath(pref_dir)

    candidates = []
    for library in bpy.context.preferences.filepaths.asset_libraries:
        library_dir = bpy.path.abspath(library.path)
        candidates.append(os.path.join(library_dir, HDRI_COLLECTION_DIRNAME))
        candidates.append(library_dir)

    addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(addon_dir, "..", "..", "assets", HDRI_COLLECTION_DIRNAME))

    for candidate in candidates:
        candidate = os.path.normpath(candidate)
        # An asset library root only counts if it's literally HDRI_COLLECTION.
        if os.path.basename(candidate) == HDRI_COLLECTION_DIRNAME and os.path.isdir(candidate):
            return candidate
    return None


def _normalized_stem(filename):
    """'FlowerField_White_HDRIConversion.hdr' -> 'flowerfield_white', for pairing with JPEGs."""
    stem = os.path.splitext(filename)[0].lower()
    stem = re.sub(r"conversion|_?hdri|_?hdr", "", stem)
    return stem.strip("_")


def _pair_thumbnails(hdr_files, thumbnail_files):
    """{hdr filename: thumbnail filename or None}.

    The JPEG and .hdr names drifted apart over time (typos, renames), so: exact
    normalized matches claim their JPEG first, then the rest pick the closest
    unclaimed one. Doing exact first keeps e.g. LivingRoom_DayTime's JPEG from
    being stolen by LivingRoom_Afternoon.
    """
    unclaimed = {_normalized_stem(name): name for name in thumbnail_files}
    pairs = {}
    leftovers = []
    for hdr in hdr_files:
        key = _normalized_stem(hdr)
        if key in unclaimed:
            pairs[hdr] = unclaimed.pop(key)
        else:
            leftovers.append(hdr)
    for hdr in leftovers:
        match = difflib.get_close_matches(_normalized_stem(hdr), list(unclaimed), n=1, cutoff=0.6)
        pairs[hdr] = unclaimed.pop(match[0]) if match else None
    return pairs


def scan_hdris(collection_dir):
    """[(label, hdr path, thumbnail path)] for every hdri_versions/ under collection_dir."""
    found = []
    for root, dirs, files in os.walk(collection_dir):
        dirs.sort()
        if os.path.basename(root).lower() != HDRI_VERSIONS_DIRNAME:
            continue
        hdr_files = sorted(f for f in files if f.lower().endswith(HDRI_EXTENSIONS))
        category_dir = os.path.dirname(root)
        thumbnail_files = [
            f for f in os.listdir(category_dir)
            if f.lower().endswith(THUMBNAIL_EXTENSIONS) and os.path.isfile(os.path.join(category_dir, f))
        ]
        pairs = _pair_thumbnails(hdr_files, thumbnail_files)
        for hdr in hdr_files:
            hdr_path = os.path.join(root, hdr)
            thumb = pairs[hdr]
            # No JPEG twin: Blender can thumbnail the .hdr itself, just slowly.
            thumb_path = os.path.join(category_dir, thumb) if thumb else hdr_path
            label = os.path.splitext(hdr)[0].replace("_", " ")
            found.append((label, hdr_path, thumb_path))
    return found


def hdri_enum_items(self, context):
    global _hdri_items
    if _hdri_items is not None:
        return _hdri_items

    collection_dir = find_hdri_collection_dir()
    entries = scan_hdris(collection_dir) if collection_dir else []
    if not entries:
        _hdri_items = [("NONE", "No HDRIs found", "Set the HDRI folder in the add-on preferences", "ERROR", 0)]
        return _hdri_items

    items = []
    for index, (label, hdr_path, thumb_path) in enumerate(entries):
        icon_id = 0
        if _previews is not None:
            preview = _previews.get(hdr_path) or _previews.load(hdr_path, thumb_path, "IMAGE")
            icon_id = preview.icon_id
        items.append((hdr_path, label, hdr_path, icon_id, index))
    _hdri_items = items
    return _hdri_items


def clear_hdri_cache():
    global _hdri_items
    _hdri_items = None
    if _previews is not None:
        _previews.clear()


def _build_hdri_nodes(world):
    """(Re)build the HDRI node chain in world.node_tree. Returns the Environment node."""
    tree = world.node_tree
    tree.nodes.clear()

    texcoord = tree.nodes.new("ShaderNodeTexCoord")
    texcoord.name = NODE_TEXCOORD
    texcoord.location = (-900, 0)

    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.name = NODE_MAPPING
    mapping.vector_type = "POINT"
    mapping.location = (-700, 0)

    environment = tree.nodes.new("ShaderNodeTexEnvironment")
    environment.name = NODE_ENVIRONMENT
    environment.location = (-450, 0)

    background = tree.nodes.new("ShaderNodeBackground")
    background.name = NODE_BACKGROUND
    background.inputs["Strength"].default_value = 1.0
    background.location = (-150, 0)

    output = tree.nodes.new("ShaderNodeOutputWorld")
    output.name = NODE_OUTPUT
    output.location = (100, 0)

    tree.links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
    tree.links.new(environment.outputs["Color"], background.inputs["Color"])
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    return environment


def apply_hdri_lighting(scene, hdr_path):
    """Light `scene` from hdr_path, invisible to the camera. Returns (changed, missing)."""
    changed = []
    missing = []

    world = bpy.data.worlds.get(HDRI_WORLD_NAME)
    if world is None:
        world = bpy.data.worlds.new(HDRI_WORLD_NAME)
        changed.append(f"created world {HDRI_WORLD_NAME!r}")
    # use_nodes is deprecated (always on) in newer Blender; only flip it where it matters.
    if hasattr(world, "use_nodes") and not world.use_nodes:
        world.use_nodes = True

    if scene.world != world:
        previous = scene.world.name if scene.world else None
        changed.append(f"scene.world {previous!r} -> {HDRI_WORLD_NAME!r}")
        scene.world = world

    nodes = world.node_tree.nodes
    environment = nodes.get(NODE_ENVIRONMENT)
    if not all(nodes.get(name) for name in (NODE_TEXCOORD, NODE_MAPPING, NODE_ENVIRONMENT, NODE_BACKGROUND, NODE_OUTPUT)):
        environment = _build_hdri_nodes(world)
        changed.append("built HDRI world node graph")

    old_image = environment.image
    image = bpy.data.images.load(hdr_path, check_existing=True)
    if old_image != image:
        environment.image = image
        changed.append(f"environment image {old_image.name if old_image else None!r} -> {image.name!r}")
        # A float 11K HDRI is ~1 GB in memory; don't keep the old one around.
        if old_image is not None and old_image.users == 0:
            bpy.data.images.remove(old_image)

    _set(scene.render, "film_transparent", True, changed, missing)

    # Importance-sample the world so the HDR's sun casts real shadows (Cycles),
    # and let EEVEE extract a shadowing sun from it too.
    world_cycles = getattr(world, "cycles", None)
    if world_cycles is not None:
        _set(world_cycles, "sampling_method", "AUTOMATIC", changed, missing)
    _set(world, "use_sun_shadow", True, changed, missing)

    return changed, missing


def get_hdri_world_nodes():
    """(background node, mapping node) of the HDRI world, or (None, None)."""
    world = bpy.data.worlds.get(HDRI_WORLD_NAME)
    if world is None or world.node_tree is None:
        return None, None
    nodes = world.node_tree.nodes
    return nodes.get(NODE_BACKGROUND), nodes.get(NODE_MAPPING)


# ------ Compositor Setup -------------------------------------------------------
# Rebuilds the beauty from Cycles light passes:
#
#   (DiffDir + DiffInd) * DiffCol
# + (GlossDir + GlossInd) * GlossCol
# + (TransDir + TransInd) * TransCol
# + VolumeDir + VolumeInd + Emission + Environment      == Combined
#
# There is no Subsurface term: since Blender 3.0 Cycles folds subsurface into
# the Diffuse passes (the use_pass_subsurface_* flags still exist, but Cycles
# never produces the sockets). Volume and Environment are what make the sum
# match Combined. Alpha is copied back from the render at the end, since the
# sum has none -- HDRI Lighting relies on a transparent background.
#
# Denoising: scene.cycles.use_denoising (the render denoiser) is never touched.
# denoising_store_passes only *saves* albedo/normal guide passes. The per-pass
# Denoise nodes are built muted -- a muted node passes its input straight
# through -- and the "Denoise in Compositor" checkbox unmutes them.

COMP_TREE_NAME = "Emanate_Compositor"
COMP_EXR_DIR = "//render/exr/"
COMP_MOVIE_DIR = "//render/movie/"
COMP_FILE_OUTPUT_NODE = "EMANATE_EXR_Passes"
COMP_DENOISE_TAG = "EMANATE_Denoise"   # node name prefix, so the checkbox can find them

PRODUCTION_VIEW_LAYER_PASSES = (
    "use_pass_combined",
    "use_pass_diffuse_direct", "use_pass_diffuse_indirect", "use_pass_diffuse_color",
    "use_pass_glossy_direct", "use_pass_glossy_indirect", "use_pass_glossy_color",
    "use_pass_transmission_direct", "use_pass_transmission_indirect", "use_pass_transmission_color",
    "use_pass_emit", "use_pass_environment",
    "use_pass_z", "use_pass_normal", "use_pass_vector",
    "use_pass_cryptomatte_object", "use_pass_cryptomatte_material", "use_pass_cryptomatte_asset",
)
PRODUCTION_CYCLES_PASSES = (
    "use_pass_volume_direct", "use_pass_volume_indirect",
    "denoising_store_passes",
)

# (frame label, direct socket, indirect socket, color socket or None)
LIGHT_PASS_GROUPS = (
    ("Diffuse", "Diffuse Direct", "Diffuse Indirect", "Diffuse Color"),
    ("Glossy", "Glossy Direct", "Glossy Indirect", "Glossy Color"),
    ("Transmission", "Transmission Direct", "Transmission Indirect", "Transmission Color"),
    ("Volume", "Volume Direct", "Volume Indirect", None),
)

# Node layout, copied from the hand-arranged tree in Ice Demonstrations.blend.
# Frame positions are absolute; every child position is RELATIVE to its frame
# (Blender 4.4+ stores parented node locations that way), so a child's parent
# must be set before its location. Frames are shrink-wrapped, so their size
# follows from the children.
COMP_LAYOUT = {
    "render_layers": (-3600.5178, -1019.1476),
    "group_output": (3087.05, 292.8671),
    "viewer": (3087.05, 92.8671),
    "file_output": (3133.4519, -945.5295),
    # light-pass frames: frame, denoise direct, denoise indirect, add, multiply
    "Diffuse": {
        "frame": (-719.6667, 847.1333),
        "direct": (28.7549, -35.6348), "indirect": (28.7549, -215.6347),
        "add": (340.5689, -68.8115), "multiply": (570.5688, -68.8115),
    },
    "Glossy": {
        "frame": (-733.0, 411.8),
        "direct": (29.27, -35.8735), "indirect": (29.27, -215.8736),
        "add": (542.4879, -65.6458), "multiply": (772.4879, -65.6458),
    },
    "Transmission": {
        "frame": (-733.6667, -33.5333),
        "direct": (28.7445, -35.8024), "indirect": (28.7445, -215.8024),
        "add": (510.2255, -68.0647), "multiply": (740.2255, -68.0647),
    },
    "Volume": {
        "frame": (-639.0, -488.2),
        "direct": (28.6697, -46.1978), "indirect": (28.6697, -226.1978),
        "add": (642.9468, -35.5069),
    },
    "beauty": {
        "frame": (1413.6666, 258.4667),
        "first_add": (28.9119, -35.8658),   # each further Add steps +200 in x
        "set_alpha": (1028.9117, -35.8658),
    },
    "cryptomatte": {
        "frame": (-3864.3333, -209.5333),
        "nodes": ((28.6731, -35.9412), (288.6731, -35.9412), (548.6731, -35.9412)),
    },
    # Not in the reference file (it had no light groups): parked under Volume.
    "lightgroups": {
        "frame": (-639.0, -1000.0),
        "first_add": (28.7, -35.9),
    },
}
COMP_ADD_STEP_X = 200.0

# Render Layers sockets saved by the EXR Passes node, besides the beauty and light groups.
EXR_PASS_SOCKETS = (
    "Image", "Alpha",
    "Diffuse Direct", "Diffuse Indirect", "Diffuse Color",
    "Glossy Direct", "Glossy Indirect", "Glossy Color",
    "Transmission Direct", "Transmission Indirect", "Transmission Color",
    "Volume Direct", "Volume Indirect", "Emission", "Environment",
    "Depth", "Normal", "Vector",
    "Denoising Albedo", "Denoising Normal", "Denoising Depth",
)
CRYPTO_PREFIXES = ("CryptoObject", "CryptoMaterial", "CryptoAsset")


def enable_production_passes(view_layer):
    """Turn on every pass the compositor uses. Returns (changed, missing)."""
    changed = []
    missing = []
    for attr in PRODUCTION_VIEW_LAYER_PASSES:
        _set(view_layer, attr, True, changed, missing)
    cycles = getattr(view_layer, "cycles", None)
    if cycles is None:
        missing.append("view_layer.cycles (Cycles add-on not enabled)")
    else:
        for attr in PRODUCTION_CYCLES_PASSES:
            _set(cycles, attr, True, changed, missing)
    return changed, missing


def _output(node, name):
    """An enabled output socket by name, or None (passes can be switched off)."""
    socket = node.outputs.get(name)
    return socket if socket is not None and socket.enabled else None


def _mix(tree, blend, location, parent=None, label=""):
    """A color Mix node (factor 1, no clamping). Returns (node, A, B, Result)."""
    node = tree.nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = blend
    node.clamp_factor = False
    node.clamp_result = False
    node.label = label or blend.title()
    _place(node, location, parent)
    node.inputs["Factor"].default_value = 1.0
    a = next(s for s in node.inputs if s.identifier == "A_Color")
    b = next(s for s in node.inputs if s.identifier == "B_Color")
    a.default_value = (0.0, 0.0, 0.0, 1.0)
    b.default_value = (0.0, 0.0, 0.0, 1.0)
    result = next(s for s in node.outputs if s.identifier == "Result_Color")
    return node, a, b, result


def _place(node, location, parent=None):
    """Parent first, then position -- a parented node's location is frame-relative."""
    if parent is not None:
        node.parent = parent
    node.location = location


def _frame(tree, label, location):
    frame = tree.nodes.new("NodeFrame")
    frame.label = label
    frame.location = location
    frame.label_size = 20
    return frame


def _sum_chain(tree, sockets, start, parent=None, label="Add"):
    """ADD the sockets together left to right, one Add per COMP_ADD_STEP_X.

    Returns the final output socket, or None.
    """
    sockets = [s for s in sockets if s is not None]
    if not sockets:
        return None
    total = sockets[0]
    x, y = start
    for index, socket in enumerate(sockets[1:]):
        _node, a, b, result = _mix(tree, "ADD", (x + index * COMP_ADD_STEP_X, y), parent, label)
        tree.links.new(total, a)
        tree.links.new(socket, b)
        total = result
    return total


def _get_comp_tree(scene):
    """The add-on's compositor node group, assigned to `scene`. Returns (tree, changed)."""
    changed = []
    tree = bpy.data.node_groups.get(COMP_TREE_NAME)
    if tree is None or tree.bl_idname != "CompositorNodeTree":
        tree = bpy.data.node_groups.new(COMP_TREE_NAME, "CompositorNodeTree")
        changed.append(f"created compositor node group {tree.name!r}")

    current = getattr(scene, "compositing_node_group", None)
    if current != tree:
        if current is not None:
            # Keep the user's own tree alive in the file rather than orphaning it.
            current.use_fake_user = True
            changed.append(f"kept previous compositor {current.name!r} (fake user)")
        scene.compositing_node_group = tree
        changed.append(f"scene compositor -> {tree.name!r}")
    return tree, changed


def build_compositor(scene, view_layer):
    """Rebuild the Emanate compositor tree. Returns (changed, missing, lightgroup names)."""
    tree, changed = _get_comp_tree(scene)
    missing = []
    denoise_on = bool(getattr(scene, COMP_DENOISE_PROP, False))

    tree.nodes.clear()
    tree.interface.clear()
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")

    render_layers = tree.nodes.new("CompositorNodeRLayers")
    render_layers.scene = scene
    render_layers.layer = view_layer.name
    render_layers.location = COMP_LAYOUT["render_layers"]

    guide_normal = _output(render_layers, "Denoising Normal")

    # ---- light-pass groups: denoise -> add -> multiply by color ----
    beauty_terms = []
    for label, direct_name, indirect_name, color_name in LIGHT_PASS_GROUPS:
        layout = COMP_LAYOUT[label]
        frame = _frame(tree, label, layout["frame"])
        summed = []
        for slot, pass_name in (("direct", direct_name), ("indirect", indirect_name)):
            source = _output(render_layers, pass_name)
            if source is None:
                missing.append(f"{pass_name} pass")
                summed.append(None)
                continue
            denoise = tree.nodes.new("CompositorNodeDenoise")
            denoise.name = f"{COMP_DENOISE_TAG}_{pass_name.replace(' ', '_')}"
            denoise.label = f"Denoise {pass_name}"
            _place(denoise, layout[slot], frame)
            denoise.mute = not denoise_on
            denoise.inputs["HDR"].default_value = True
            tree.links.new(source, denoise.inputs["Image"])
            # No Albedo: light passes carry no albedo, so feeding it would make
            # the denoiser treat texture as signal it has to put back.
            if guide_normal is not None:
                tree.links.new(guide_normal, denoise.inputs["Normal"])
            summed.append(denoise.outputs["Image"])

        light = _sum_chain(tree, summed, layout["add"], frame, f"{label} Direct + Indirect")
        color = _output(render_layers, color_name) if color_name else None
        if color_name and color is None:
            missing.append(f"{color_name} pass")
        if light is not None and color is not None:
            _node, a, b, result = _mix(tree, "MULTIPLY", layout["multiply"], frame, f"{label} x Color")
            tree.links.new(light, a)
            tree.links.new(color, b)
            light = result
        beauty_terms.append(light)

    for extra in ("Emission", "Environment"):
        socket = _output(render_layers, extra)
        if socket is None:
            missing.append(f"{extra} pass")
        beauty_terms.append(socket)

    beauty_layout = COMP_LAYOUT["beauty"]
    beauty_frame = _frame(tree, "Beauty (rebuilt)", beauty_layout["frame"])
    beauty = _sum_chain(tree, beauty_terms, beauty_layout["first_add"], beauty_frame, "Beauty Add")

    set_alpha = tree.nodes.new("CompositorNodeSetAlpha")
    _place(set_alpha, beauty_layout["set_alpha"], beauty_frame)
    # Replace, not Apply Mask: the light-pass sum carries no alpha of its own,
    # so the render's alpha is attached as-is rather than multiplied in.
    try:
        set_alpha.inputs["Type"].default_value = "Replace Alpha"
    except (TypeError, ValueError):
        missing.append("Set Alpha 'Replace Alpha' mode")
    if beauty is not None:
        tree.links.new(beauty, set_alpha.inputs["Image"])
    alpha = _output(render_layers, "Alpha")
    if alpha is not None:
        tree.links.new(alpha, set_alpha.inputs["Alpha"])

    group_output = tree.nodes.new("NodeGroupOutput")
    group_output.location = COMP_LAYOUT["group_output"]
    tree.links.new(set_alpha.outputs["Image"], group_output.inputs["Image"])

    viewer = tree.nodes.new("CompositorNodeViewer")
    viewer.location = COMP_LAYOUT["viewer"]
    tree.links.new(set_alpha.outputs["Image"], viewer.inputs["Image"])

    # ---- Cryptomatte: ready-to-pick matte nodes ----
    crypto_layout = COMP_LAYOUT["cryptomatte"]
    crypto_frame = _frame(tree, "Cryptomatte", crypto_layout["frame"])
    for prefix, location in zip(CRYPTO_PREFIXES, crypto_layout["nodes"]):
        crypto = tree.nodes.new("CompositorNodeCryptomatteV2")
        crypto.label = prefix
        _place(crypto, location, crypto_frame)
        crypto.source = "RENDER"
        crypto.scene = scene
        # layer_name is a dynamic enum of "<view layer>.<Crypto type>".
        try:
            crypto.layer_name = f"{view_layer.name}.{prefix}"
        except TypeError:
            missing.append(f"Cryptomatte layer {view_layer.name}.{prefix}")
        tree.links.new(render_layers.outputs["Image"], crypto.inputs["Image"])

    # ---- Light groups (only ones the user made) ----
    lightgroup_names = [group.name for group in view_layer.lightgroups]
    lightgroup_sockets = []
    if lightgroup_names:
        lg_layout = COMP_LAYOUT["lightgroups"]
        lg_frame = _frame(tree, "Light Groups", lg_layout["frame"])
        sockets = []
        for name in lightgroup_names:
            socket = _output(render_layers, f"Combined_{name}")
            if socket is None:
                missing.append(f"light group pass Combined_{name}")
            else:
                sockets.append(socket)
                lightgroup_sockets.append((f"LG_{name}", socket))
        lg_sum = _sum_chain(tree, sockets, lg_layout["first_add"], lg_frame, "LightGroup Sum")
        if lg_sum is not None:
            reroute = tree.nodes.new("NodeReroute")
            reroute.label = "LightGroup Sum"
            first_x, first_y = lg_layout["first_add"]
            # One step past the last Add (or where the first would be, for a single group).
            _place(reroute, (first_x + max(len(sockets) - 1, 0) * COMP_ADD_STEP_X, first_y), lg_frame)
            tree.links.new(lg_sum, reroute.inputs[0])

    # ---- EXR Passes file output (used in Movie mode) ----
    file_output = tree.nodes.new("CompositorNodeOutputFile")
    file_output.name = COMP_FILE_OUTPUT_NODE
    file_output.label = "EXR Passes (Movie mode)"
    file_output.location = COMP_LAYOUT["file_output"]
    file_output.directory = COMP_EXR_DIR
    _set(file_output.format, "media_type", "MULTI_LAYER_IMAGE", [], missing)
    _set(file_output.format, "color_depth", "32", [], missing)
    _set(file_output.format, "exr_codec", "ZIP", [], missing)

    def add_input(name, socket, socket_type="RGBA"):
        file_output.file_output_items.new(socket_type, name)
        tree.links.new(socket, file_output.inputs[name])

    add_input("Beauty", set_alpha.outputs["Image"])
    for name in EXR_PASS_SOCKETS:
        socket = _output(render_layers, name)
        if socket is not None:
            kind = "FLOAT" if socket.type == "VALUE" else ("VECTOR" if socket.type == "VECTOR" else "RGBA")
            add_input(name.replace(" ", ""), socket, kind)
    for socket in render_layers.outputs:
        if socket.enabled and socket.name.startswith(CRYPTO_PREFIXES):
            add_input(socket.name, socket)
    for name, socket in lightgroup_sockets:
        add_input(name, socket)

    changed.append("rebuilt compositor tree")
    return changed, missing, lightgroup_names


def _comp_tree_nodes(scene):
    tree = getattr(scene, "compositing_node_group", None)
    if tree is None or tree.name != COMP_TREE_NAME:
        return None
    return tree.nodes


def apply_output_mode(scene, mode):
    """Point the main render output at multilayer EXR or an H.264 movie. Returns (changed, missing).

    EXR: the main output already saves every pass + the composite, so the
    EXR Passes node is muted (no double write). MOVIE: the main output can only
    hold the beauty, so the EXR Passes node is unmuted to keep the passes.
    """
    changed = []
    missing = []
    render = scene.render
    image_settings = render.image_settings

    if mode == "MOVIE":
        _set(image_settings, "media_type", "VIDEO", changed, missing)
        _set(image_settings, "file_format", "FFMPEG", changed, missing)
        _set(render.ffmpeg, "format", "MPEG4", changed, missing)
        _set(render.ffmpeg, "codec", "H264", changed, missing)
        _set(render.ffmpeg, "constant_rate_factor", "HIGH", changed, missing)
        _set(render, "filepath", COMP_MOVIE_DIR, changed, missing)
    else:
        _set(image_settings, "media_type", "MULTI_LAYER_IMAGE", changed, missing)
        _set(image_settings, "file_format", "OPEN_EXR_MULTILAYER", changed, missing)
        _set(image_settings, "color_depth", "32", changed, missing)
        _set(image_settings, "exr_codec", "ZIP", changed, missing)
        _set(render, "filepath", COMP_EXR_DIR, changed, missing)

    nodes = _comp_tree_nodes(scene)
    file_output = nodes.get(COMP_FILE_OUTPUT_NODE) if nodes is not None else None
    if file_output is not None:
        _set(file_output, "mute", mode != "MOVIE", changed, missing)
    return changed, missing


def apply_comp_denoise(scene, enabled):
    """Mute/unmute every compositor Denoise node. Returns how many were touched."""
    nodes = _comp_tree_nodes(scene)
    if nodes is None:
        return 0
    count = 0
    for node in nodes:
        if node.name.startswith(COMP_DENOISE_TAG):
            node.mute = not enabled
            count += 1
    return count


def _comp_denoise_update(self, context):
    apply_comp_denoise(self, getattr(self, COMP_DENOISE_PROP))


def _comp_output_mode_update(self, context):
    apply_output_mode(self, getattr(self, COMP_OUTPUT_MODE_PROP))


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


class EMANATE_OT_hdri_lighting(bpy.types.Operator):
    bl_idname = NAMES_HDRI_LIGHTING.operator_idname
    bl_label = NAMES_HDRI_LIGHTING.label
    bl_description = NAMES_HDRI_LIGHTING.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        hdr_path = getattr(context.scene, HDRI_CHOICE_PROP, "NONE")
        if hdr_path in ("", "NONE") or not os.path.isfile(hdr_path):
            self.report(
                {"WARNING"},
                "HDRI Lighting: HDRI folder not found -- set it in the add-on preferences, then Refresh",
            )
            return {"CANCELLED"}

        changed, missing = apply_hdri_lighting(context.scene, hdr_path)

        if missing:
            self.report(
                {"WARNING"},
                f"HDRI Lighting: {len(missing)} setting(s) not found on this Blender "
                f"version, skipped: {', '.join(missing)}",
            )
        for line in changed:
            print(f"[hdri-lighting] {line}")

        name = os.path.basename(hdr_path)
        if not changed:
            self.report({"INFO"}, f"HDRI Lighting already set to {name}")
        else:
            self.report({"INFO"}, f"HDRI Lighting: {name} ({len(changed)} setting(s) changed)")
        return {"FINISHED"}


class EMANATE_OT_compositor_setup(bpy.types.Operator):
    bl_idname = NAMES_COMPOSITOR_SETUP.operator_idname
    bl_label = NAMES_COMPOSITOR_SETUP.label
    bl_description = NAMES_COMPOSITOR_SETUP.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        view_layer = context.view_layer

        changed, missing = enable_production_passes(view_layer)
        comp_changed, comp_missing, lightgroups = build_compositor(scene, view_layer)
        out_changed, out_missing = apply_output_mode(scene, getattr(scene, COMP_OUTPUT_MODE_PROP))
        changed += comp_changed + out_changed
        missing += comp_missing + out_missing

        if missing:
            self.report(
                {"WARNING"},
                f"Compositor Setup: {len(missing)} item(s) not found, skipped: {', '.join(missing)}",
            )
        if scene.render.use_motion_blur:
            self.report({"WARNING"}, "Compositor Setup: motion blur is on, so Cycles leaves the Vector pass empty")
        for line in changed:
            print(f"[compositor-setup] {line}")

        groups = f"{len(lightgroups)} light group(s) wired" if lightgroups else "no light groups found"
        self.report({"INFO"}, f"Compositor Setup applied ({len(changed)} change(s), {groups})")
        return {"FINISHED"}


class EMANATE_OT_hdri_refresh(bpy.types.Operator):
    bl_idname = NAMES_HDRI_REFRESH.operator_idname
    bl_label = NAMES_HDRI_REFRESH.label
    bl_description = NAMES_HDRI_REFRESH.description
    bl_options = {"REGISTER"}

    def execute(self, context):
        clear_hdri_cache()
        count = len([item for item in hdri_enum_items(None, context) if item[0] != "NONE"])
        self.report({"INFO"}, f"Found {count} HDRI(s)")
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

        box = layout.box()
        header = box.row(align=True)
        header.label(text="HDRI Lighting", icon="WORLD")
        header.operator(NAMES_HDRI_REFRESH.operator_idname, text="", icon="FILE_REFRESH")
        box.template_icon_view(context.scene, HDRI_CHOICE_PROP, show_labels=True, scale=6.0, scale_popup=6.0)
        box.operator(NAMES_HDRI_LIGHTING.operator_idname, icon="WORLD")

        # Live controls, drawn straight off the world's nodes -- only while the
        # scene is actually using the HDRI world.
        world = context.scene.world
        if world is not None and world.name == HDRI_WORLD_NAME:
            background, mapping = get_hdri_world_nodes()
            col = box.column(align=True)
            if background is not None:
                col.prop(background.inputs["Strength"], "default_value", text="Strength")
            if mapping is not None:
                col.prop(mapping.inputs["Rotation"], "default_value", index=2, text="Rotation")
            col.prop(context.scene.render, "film_transparent", text="Hide from Camera")

        box = layout.box()
        box.label(text="Compositor", icon="NODE_COMPOSITING")
        box.operator(NAMES_COMPOSITOR_SETUP.operator_idname, icon="NODE_COMPOSITING")
        box.prop(context.scene, COMP_DENOISE_PROP)
        box.row().prop(context.scene, COMP_OUTPUT_MODE_PROP, expand=True)


_classes = (
    EMANATE_AP_preferences,
    EMANATE_OT_cinema_base,
    EMANATE_OT_fast_clean_static,
    EMANATE_OT_hdri_lighting,
    EMANATE_OT_hdri_refresh,
    EMANATE_OT_compositor_setup,
    EMANATE_PT_render_tools,
)


def register():
    global _previews
    naming.check_classes((EMANATE_OT_cinema_base,), NAMES_CINEMA_BASE)
    naming.check_classes((EMANATE_OT_fast_clean_static,), NAMES_FAST_CLEAN_STATIC)
    naming.check_classes((EMANATE_OT_hdri_lighting,), NAMES_HDRI_LIGHTING)
    naming.check_classes((EMANATE_OT_hdri_refresh,), NAMES_HDRI_REFRESH)
    naming.check_classes((EMANATE_OT_compositor_setup,), NAMES_COMPOSITOR_SETUP)
    naming.check_classes((EMANATE_PT_render_tools,), NAMES)
    # EMANATE_AP_preferences isn't checked: naming_unity has no AddonPreferences tag.
    for cls in _classes:
        bpy.utils.register_class(cls)

    _previews = bpy.utils.previews.new()
    clear_hdri_cache()
    setattr(
        bpy.types.Scene,
        HDRI_CHOICE_PROP,
        bpy.props.EnumProperty(
            name="HDRI",
            description="HDRI to light the scene with (the full-range .hdr is what gets loaded)",
            items=hdri_enum_items,
        ),
    )
    setattr(
        bpy.types.Scene,
        COMP_DENOISE_PROP,
        bpy.props.BoolProperty(
            name="Denoise in Compositor",
            description=(
                "Unmute the per-pass Denoise nodes (Direct/Indirect light passes, guided by "
                "Denoising Normal). The render itself stays undenoised"
            ),
            default=False,
            update=_comp_denoise_update,
        ),
    )
    setattr(
        bpy.types.Scene,
        COMP_OUTPUT_MODE_PROP,
        bpy.props.EnumProperty(
            name="Output",
            items=(
                ("EXR", "Multilayer EXR", "Every pass + the rebuilt beauty in one 32-bit EXR per frame"),
                ("MOVIE", "Movie (MP4)", "Beauty encoded to H.264 MP4; passes still saved to EXR by the compositor"),
            ),
            default="EXR",
            update=_comp_output_mode_update,
        ),
    )


def unregister():
    global _previews
    delattr(bpy.types.Scene, COMP_OUTPUT_MODE_PROP)
    delattr(bpy.types.Scene, COMP_DENOISE_PROP)
    delattr(bpy.types.Scene, HDRI_CHOICE_PROP)
    clear_hdri_cache()
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
