"""Render-engine presets.

Buttons that stamp a whole Cycles configuration onto the scene in one click,
the way pre_rig_tools.fix_render_settings stamps the unit/device basics onto a
fresh rig scene.
"""

import difflib
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile

import bpy
import bpy.utils.previews

from ..helpers import naming_unity as naming
from ..helpers import vfx_node_groups

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

NAMES_HDRI_DOWNLOAD = naming.register_tool(
    "hdri_download",
    label="Download HDRIs",
    owner=__name__,
    description=(
        "Download the HDRI collection from this add-on's GitHub release into the "
        "extension's user folder (needs Allow Online Access)"
    ),
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

NAMES_GRADIENT_BG = naming.register_tool(
    "gradient_bg",
    label="Create Gradient BG",
    owner=__name__,
    description=(
        "Composite a linear or radial gradient behind everything, at the end of the "
        "rebuilt beauty (needs a transparent render, which this turns on)"
    ),
)

NAMES_GRADIENT_BG_REMOVE = naming.register_tool(
    "gradient_bg_remove",
    label="Remove Gradient BG",
    owner=__name__,
    description="Take the gradient background out of the compositor",
)

GRADIENT_ENABLED_PROP = naming.prop_name("gradient_enabled")
GRADIENT_TYPE_PROP = naming.prop_name("gradient_type")
GRADIENT_COLOR_1_PROP = naming.prop_name("gradient_color_1")
GRADIENT_COLOR_2_PROP = naming.prop_name("gradient_color_2")
GRADIENT_ANGLE_PROP = naming.prop_name("gradient_angle")
GRADIENT_SIZE_PROP = naming.prop_name("gradient_size")

NAMES_VFX_ADD = naming.register_tool(
    "vfx_add",
    label="Add VFX",
    owner=__name__,
    description=(
        "Finish the composite with bloom, blue-tinted streaks, lens dispersion and a "
        "rounded vignette, after the gradient background"
    ),
)

NAMES_VFX_REMOVE = naming.register_tool(
    "vfx_remove",
    label="Remove VFX",
    owner=__name__,
    description="Take the VFX stack out of the compositor",
)

VFX_ENABLED_PROP = naming.prop_name("vfx_enabled")

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

# The collection itself is ~3 GB, so it lives on a GitHub release (one zip per
# category, built by scripts/package_hdris.py) rather than in git or the
# extension zip. Download HDRIs pulls it into the extension's user folder.
HDRI_RELEASE_URL = "https://github.com/emansiu/Blender-Tools/releases/download/hdris-v1/"
HDRI_MANIFEST_NAME = "hdri_manifest.json"

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
        draw_hdri_download(self.layout)


def user_hdri_dir(create=False):
    """HDRI_COLLECTION inside the extension's user folder, or None.

    That folder survives extension updates. It only exists for an add-on
    installed as an extension; running from source or as a legacy add-on has none.
    """
    try:
        return bpy.utils.extension_path_user(ADDON_PACKAGE, path=HDRI_COLLECTION_DIRNAME, create=create)
    except (ValueError, AttributeError):
        return None


def find_hdri_collection_dir():
    """The HDRI_COLLECTION folder, or None.

    Order: the add-on preference, then the folder Download HDRIs fills, then any
    asset library (Preferences > File Paths) that contains HDRI_COLLECTION, then
    the repo layout this add-on is developed in (src/Emanate_Tools/ next to
    assets/), for running from source.
    """
    # The preference may point straight at any folder of HDRI categories, so
    # it's trusted as-is when it exists.
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    if addon is not None and addon.preferences is not None:
        pref_dir = bpy.path.abspath(addon.preferences.hdri_library_dir)
        if pref_dir and os.path.isdir(pref_dir):
            return os.path.normpath(pref_dir)

    # Only once a download has actually put a category in it; an empty folder
    # would hide an asset-library copy below.
    downloaded = user_hdri_dir()
    if downloaded and os.path.isdir(downloaded) and os.listdir(downloaded):
        return os.path.normpath(downloaded)

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
        _hdri_items = [(
            "NONE", "No HDRIs found",
            "Click Download HDRIs, or set the HDRI folder in the add-on preferences", "ERROR", 0,
        )]
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


# ------ HDRI download ----------------------------------------------------------
# Runs on a worker thread so Blender stays responsive through ~3 GB; the modal
# operator polls _download from a timer. bpy is never touched off the main thread.

_download = {"thread": None, "status": "", "error": None, "cancel": False}


def _hdri_url(name):
    return HDRI_RELEASE_URL + urllib.parse.quote(name)


def _fetch_manifest():
    with urllib.request.urlopen(_hdri_url(HDRI_MANIFEST_NAME), timeout=30) as response:
        return json.load(response)


def _download_file(url, dest, size, label):
    """Stream url to dest, updating the status line. Returns the sha256 hex digest."""
    digest = hashlib.sha256()
    done = 0
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:
        while True:
            if _download["cancel"]:
                raise InterruptedError
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            _download["status"] = f"{label}: {done / 2**20:.0f} / {size / 2**20:.0f} MB"
    return digest.hexdigest()


def _download_worker(target_dir):
    """Fetch every category in the manifest that isn't already in target_dir."""
    try:
        _download["status"] = "Fetching HDRI list..."
        entries = _fetch_manifest()
        # A category counts as present once its folder exists; extraction goes
        # through a temp folder and is moved in last, so a half-done one never is.
        todo = [e for e in entries if not os.path.isdir(os.path.join(target_dir, e["category"]))]
        for index, entry in enumerate(todo, start=1):
            label = f"[{index}/{len(todo)}] {entry['category']}"
            with tempfile.TemporaryDirectory(dir=target_dir, prefix=".download_") as tmp:
                zip_path = os.path.join(tmp, entry["file"])
                sha = _download_file(_hdri_url(entry["file"]), zip_path, entry["size"], label)
                if sha != entry["sha256"]:
                    raise ValueError(f"{entry['file']} is corrupt (checksum mismatch), try again")
                _download["status"] = f"{label}: unpacking"
                unpack_dir = os.path.join(tmp, "unpacked")
                with zipfile.ZipFile(zip_path) as archive:
                    archive.extractall(unpack_dir)
                shutil.move(os.path.join(unpack_dir, entry["category"]), target_dir)
        _download["status"] = f"Downloaded {len(todo)} categor{'y' if len(todo) == 1 else 'ies'}"
    except InterruptedError:
        _download["error"] = "Download cancelled"
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user by the operator
        _download["error"] = f"{type(exc).__name__}: {exc}"


def draw_hdri_download(layout):
    """The Download HDRIs button, or the progress line while one is running."""
    thread = _download["thread"]
    if thread is not None and thread.is_alive():
        layout.label(text=_download["status"] or "Downloading...", icon="IMPORT")
    else:
        layout.operator(NAMES_HDRI_DOWNLOAD.operator_idname, icon="IMPORT")


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
#   ( (DiffDir + DiffInd) * DiffCol
#   + (GlossDir + GlossInd) * GlossCol
#   + (TransDir + TransInd) * TransCol
#   + VolumeDir + VolumeInd + Emission ) * AO
#
# then mixed toward a fog color by depth:
#
#   mix(beauty, FogColor, Density * MapRange(Mist))
#
# There is no Subsurface term: since Blender 3.0 Cycles folds subsurface into
# the Diffuse passes (the use_pass_subsurface_* flags still exist, but Cycles
# never produces the sockets). The Environment pass is switched OFF, so the
# camera-visible world is not in the sum -- with Film > Transparent on (what
# HDRI Lighting uses) that matches Combined; with it off the background comes
# out black. AO is multiplied over the whole sum by the "Ambient Occlusion"
# Mix node; drop its Factor to fade it out. Alpha is copied back from the
# render at the end, since the sum has none.
#
# Mist fog: the Mist pass is 0 at World > Mist Pass Start and 1 at Start +
# Depth (shaped by Falloff) -- those need a re-render. Everything after is
# live in the compositor: "Mist Range" reshapes that 0-1 ramp, "Fog Density"
# scales it (built at 0, so the fog is wired but invisible until raised) and
# "Fog Color" is the haze it mixes toward. With Film > Transparent the
# background has no alpha, so fog only shows on geometry.
#
# Denoising: scene.cycles.use_denoising (the render denoiser) is never touched.
# denoising_store_passes only *saves* albedo/normal guide passes. The per-pass
# Denoise nodes are built muted -- a muted node passes its input straight
# through -- and the "Denoise in Compositor" checkbox unmutes them.

COMP_TREE_NAME = "Emanate_Compositor"
COMP_EXR_DIR = "//render/exr/"
COMP_MOVIE_DIR = "//render/movie/"
COMP_FINAL_DIR = "//render/final/"
COMP_FILE_OUTPUT_NODE = "EMANATE_EXR_Passes"
COMP_DENOISE_TAG = "EMANATE_Denoise"   # node name prefix, so the checkbox can find them
COMP_SET_ALPHA_NODE = "EMANATE_SetAlpha"
COMP_GROUP_OUTPUT_NODE = "EMANATE_GroupOutput"
COMP_VIEWER_NODE = "EMANATE_Viewer"
COMP_GRADIENT_TAG = "EMANATE_Gradient"  # node name prefix for everything the gradient adds
COMP_AO_NODE = "EMANATE_AO"
COMP_MIST_TAG = "EMANATE_Mist"  # node name prefix for the fog nodes, so the panel can find them
COMP_MIST_RANGE_NODE = f"{COMP_MIST_TAG}_Range"
COMP_MIST_DENSITY_NODE = f"{COMP_MIST_TAG}_Density"
COMP_MIST_COLOR_NODE = f"{COMP_MIST_TAG}_Color"
COMP_MIST_MIX_NODE = f"{COMP_MIST_TAG}_Mix"
FOG_DEFAULT_COLOR = (0.6, 0.65, 0.7, 1.0)
COMP_VFX_TAG = "EMANATE_VFX"  # node name prefix for everything Add VFX adds
COMP_VFX_BLOOM_NODE = f"{COMP_VFX_TAG}_Bloom"
COMP_VFX_STREAKS_NODE = f"{COMP_VFX_TAG}_Streaks"
COMP_VFX_LENS_NODE = f"{COMP_VFX_TAG}_LensDist"
COMP_VFX_VIGNETTE_NODE = f"{COMP_VFX_TAG}_Vignette"
# The Render Layers socket for the AO pass; older builds named it in full.
AO_SOCKET_NAMES = ("AO", "Ambient Occlusion")

PRODUCTION_VIEW_LAYER_PASSES = (
    "use_pass_combined",
    "use_pass_diffuse_direct", "use_pass_diffuse_indirect", "use_pass_diffuse_color",
    "use_pass_glossy_direct", "use_pass_glossy_indirect", "use_pass_glossy_color",
    "use_pass_transmission_direct", "use_pass_transmission_indirect", "use_pass_transmission_color",
    "use_pass_emit", "use_pass_ambient_occlusion", "use_pass_mist",
    "use_pass_z", "use_pass_normal", "use_pass_vector",
    "use_pass_cryptomatte_object", "use_pass_cryptomatte_material", "use_pass_cryptomatte_asset",
)
# Passes Compositor Setup actively switches off.
DISABLED_VIEW_LAYER_PASSES = (
    "use_pass_environment",
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
    # Outputs sit past the VFX frame's slot, so Add VFX never overlaps them.
    "group_output": (4050.0, 292.8671),
    "viewer": (4050.0, 92.8671),
    "file_output": (4096.4, -945.5295),
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
        "ao": (828.9117, -35.8658),          # one step past the last Beauty Add
        "fog": (1028.9117, -35.8658),
        "set_alpha": (1228.9117, -35.8658),
    },
    # Mist fog controls: frame above Beauty; the Fog mix itself sits in Beauty.
    "mist": {
        "frame": (1413.6666, 700.0),
        "range": (28.9, -35.9),
        "density": (260.0, -35.9),
        "color": (28.9, -300.0),
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
    # Gradient BG: frame under Beauty; Alpha Over in the gap before Group Output.
    "gradient": {
        "frame": (1413.6666, -150.0),
        "coords": (28.9, -35.9),
        "lin_center": (260.0, -35.9),
        "lin_dot": (460.0, -35.9),
        "lin_flip": (660.0, -35.9),
        "rad_length": (260.0, -235.9),
        "rad_range": (460.0, -235.9),
        "type_mix": (880.0, -135.9),
        "clamp": (1080.0, -135.9),
        "color_mix": (1280.0, -135.9),
        "alpha_over": (2800.0, 292.8671),   # absolute, not in the frame
    },
    # VFX: frame between the gradient's Alpha Over and the outputs. Child
    # positions copied from the "vfx" frame in Teaching_File.blend.
    "vfx": {
        "frame": (3000.0, 499.1333),
        "bloom": (28.9085, -47.6697),
        "streaks": (288.0898, -47.0198),
        "lens": (509.1237, -45.7229),
        "vignette": (704.1417, -35.8932),
    },
}
COMP_ADD_STEP_X = 200.0

# Render Layers sockets saved by the EXR Passes node, besides the beauty and light groups.
EXR_PASS_SOCKETS = (
    "Image", "Alpha",
    "Diffuse Direct", "Diffuse Indirect", "Diffuse Color",
    "Glossy Direct", "Glossy Indirect", "Glossy Color",
    "Transmission Direct", "Transmission Indirect", "Transmission Color",
    "Volume Direct", "Volume Indirect", "Emission",
    "Depth", "Mist", "Normal", "Vector",
    "Denoising Albedo", "Denoising Normal", "Denoising Depth",
)
CRYPTO_PREFIXES = ("CryptoObject", "CryptoMaterial", "CryptoAsset")


def enable_production_passes(view_layer):
    """Turn on every pass the compositor uses, off the ones it doesn't. Returns (changed, missing)."""
    changed = []
    missing = []
    for attr in PRODUCTION_VIEW_LAYER_PASSES:
        _set(view_layer, attr, True, changed, missing)
    for attr in DISABLED_VIEW_LAYER_PASSES:
        _set(view_layer, attr, False, changed, missing)
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


def _ao_output(render_layers):
    """The enabled AO socket on a Render Layers node, under whichever name this build uses."""
    for name in AO_SOCKET_NAMES:
        socket = _output(render_layers, name)
        if socket is not None:
            return socket
    return None


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
    # Drivers live on the tree, not the nodes -- trees built by older versions
    # carry an Environment-gate driver; drop it so it doesn't linger dead.
    if tree.animation_data is not None:
        tree.animation_data_clear()
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

    beauty_layout = COMP_LAYOUT["beauty"]
    beauty_frame = _frame(tree, "Beauty (rebuilt)", beauty_layout["frame"])

    emission = _output(render_layers, "Emission")
    if emission is None:
        missing.append("Emission pass")
    beauty_terms.append(emission)

    beauty = _sum_chain(tree, beauty_terms, beauty_layout["first_add"], beauty_frame, "Beauty Add")

    # ---- Ambient Occlusion: multiplied over the whole beauty ----
    ao = _ao_output(render_layers)
    if ao is None:
        missing.append("Ambient Occlusion pass")
    elif beauty is not None:
        ao_node, a, b, result = _mix(tree, "MULTIPLY", beauty_layout["ao"], beauty_frame, "Ambient Occlusion")
        ao_node.name = COMP_AO_NODE
        tree.links.new(beauty, a)
        tree.links.new(ao, b)
        beauty = result

    # ---- Mist fog: beauty mixed toward Fog Color by Density * remapped Mist ----
    mist = _output(render_layers, "Mist")
    if mist is None:
        missing.append("Mist pass")
    elif beauty is not None:
        mist_layout = COMP_LAYOUT["mist"]
        mist_frame = _frame(tree, "Mist Fog", mist_layout["frame"])

        mist_range = tree.nodes.new("ShaderNodeMapRange")
        mist_range.name = COMP_MIST_RANGE_NODE
        mist_range.label = "Mist Range"
        _place(mist_range, mist_layout["range"], mist_frame)
        mist_range.clamp = True
        tree.links.new(mist, mist_range.inputs["Value"])

        density = tree.nodes.new("ShaderNodeMath")
        density.name = COMP_MIST_DENSITY_NODE
        density.label = "Fog Density"
        _place(density, mist_layout["density"], mist_frame)
        density.operation = "MULTIPLY"
        density.use_clamp = True
        density.inputs[1].default_value = 0.0
        tree.links.new(mist_range.outputs["Result"], density.inputs[0])

        fog_color = tree.nodes.new("CompositorNodeRGB")
        fog_color.name = COMP_MIST_COLOR_NODE
        fog_color.label = "Fog Color"
        _place(fog_color, mist_layout["color"], mist_frame)
        fog_color.outputs[0].default_value = FOG_DEFAULT_COLOR

        fog_mix, a, b, result = _mix(tree, "MIX", beauty_layout["fog"], beauty_frame, "Mist Fog")
        fog_mix.name = COMP_MIST_MIX_NODE
        tree.links.new(density.outputs["Value"], fog_mix.inputs["Factor"])
        tree.links.new(beauty, a)
        tree.links.new(fog_color.outputs[0], b)
        beauty = result

    set_alpha = tree.nodes.new("CompositorNodeSetAlpha")
    set_alpha.name = COMP_SET_ALPHA_NODE
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
    group_output.name = COMP_GROUP_OUTPUT_NODE
    group_output.location = COMP_LAYOUT["group_output"]
    tree.links.new(set_alpha.outputs["Image"], group_output.inputs["Image"])

    viewer = tree.nodes.new("CompositorNodeViewer")
    viewer.name = COMP_VIEWER_NODE
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

    # ---- EXR Passes file output: always on, in both output modes ----
    # Blender 5.x's main multilayer output only holds the composite while the
    # compositor runs, so this node is the ONLY thing that writes the passes.
    file_output = tree.nodes.new("CompositorNodeOutputFile")
    file_output.name = COMP_FILE_OUTPUT_NODE
    file_output.label = "EXR Passes"
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
    if ao is not None:
        add_input("AO", ao, "FLOAT" if ao.type == "VALUE" else "RGBA")
    for socket in render_layers.outputs:
        if socket.enabled and socket.name.startswith(CRYPTO_PREFIXES):
            add_input(socket.name, socket)
    for name, socket in lightgroup_sockets:
        add_input(name, socket)

    if getattr(scene, GRADIENT_ENABLED_PROP, False):
        missing += insert_gradient_bg(tree, scene)
        changed.append("restored gradient background")
    if getattr(scene, VFX_ENABLED_PROP, False):
        missing += insert_vfx(tree)
        changed.append("restored VFX")

    changed.append("rebuilt compositor tree")
    return changed, missing, lightgroup_names


def _comp_tree_nodes(scene):
    tree = getattr(scene, "compositing_node_group", None)
    if tree is None or tree.name != COMP_TREE_NAME:
        return None
    return tree.nodes


def apply_output_mode(scene, mode):
    """Point the main render output at the final picture: EXR or H.264 movie. Returns (changed, missing).

    The main output only ever carries the composite in Blender 5.x (a
    multilayer main output drops the passes while the compositor runs), so it
    is set to the final picture alone -- //render/final/ or //render/movie/.
    The passes always come from the EXR Passes node, in both modes.
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
        _set(image_settings, "media_type", "IMAGE", changed, missing)
        _set(image_settings, "file_format", "OPEN_EXR", changed, missing)
        _set(image_settings, "color_mode", "RGBA", changed, missing)
        _set(image_settings, "color_depth", "32", changed, missing)
        _set(image_settings, "exr_codec", "ZIP", changed, missing)
        _set(render, "filepath", COMP_FINAL_DIR, changed, missing)

    # Trees built before the passes node went always-on had it muted in EXR mode.
    nodes = _comp_tree_nodes(scene)
    file_output = nodes.get(COMP_FILE_OUTPUT_NODE) if nodes is not None else None
    if file_output is not None:
        _set(file_output, "mute", False, changed, missing)
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


# ------ Gradient BG --------------------------------------------------------------
# A gradient Alpha-Overed behind the rebuilt beauty, between Set Alpha and the
# Group Output / Viewer. The factor t runs 0 at Color 1 to 1 at Color 2:
#
#   linear: t = 0.5 - dot(Normalized - (0.5, 0.5), (sin a, cos a))
#           (a = 0 puts Color 1 at the top)
#   radial: t = smoothstep(0, size, |Uniform|)   (Uniform is centered and
#           aspect-correct, so the falloff is a circle, not an ellipse)
#
# Both are always built; a float Mix picks one, so switching type, colors,
# angle or size only writes node values -- no rebuild. The settings live on
# the scene, so a Compositor Setup rebuild puts the same gradient back.
#
# The EXR Passes "Beauty" stays wired to Set Alpha -- the clean transparent
# beauty for external comp; only the final composite gets the gradient.

def _gradient_node(tree, bl_idname, key, location, parent=None, label=""):
    node = tree.nodes.new(bl_idname)
    node.name = f"{COMP_GRADIENT_TAG}_{key}"
    node.label = label
    _place(node, location, parent)
    return node


def _gradient_nodes(tree):
    return [node for node in tree.nodes if node.name.startswith(COMP_GRADIENT_TAG)]


def _beauty_endpoints(tree):
    """(Set Alpha, Group Output, Viewer). Falls back to node type for trees built before these were named."""
    def find(name, bl_idname):
        node = tree.nodes.get(name)
        if node is None:
            node = next((n for n in tree.nodes if n.bl_idname == bl_idname and not n.name.startswith(COMP_GRADIENT_TAG)), None)
        return node
    return (
        find(COMP_SET_ALPHA_NODE, "CompositorNodeSetAlpha"),
        find(COMP_GROUP_OUTPUT_NODE, "NodeGroupOutput"),
        find(COMP_VIEWER_NODE, "CompositorNodeViewer"),
    )


GRADIENT_EXR_LAYER = "GradientBG"
# The finished picture (gradient and/or VFX); "Beauty" stays the clean transparent beauty.
FINAL_EXR_LAYER = "Final"


def _remove_exr_layer(tree, name):
    file_output = tree.nodes.get(COMP_FILE_OUTPUT_NODE)
    if file_output is None:
        return
    # Look it up fresh: removing an item invalidates Python references to the
    # items after it, so one collected earlier may be stale.
    item = next((i for i in file_output.file_output_items if i.name == name), None)
    if item is not None:
        file_output.file_output_items.remove(item)


def _set_exr_layer(tree, name, socket):
    """Add (if needed) an RGBA layer to the EXR Passes node and feed it `socket`. False if there's no node."""
    file_output = tree.nodes.get(COMP_FILE_OUTPUT_NODE)
    if file_output is None:
        return False
    if not any(item.name == name for item in file_output.file_output_items):
        file_output.file_output_items.new("RGBA", name)
    tree.links.new(socket, file_output.inputs[name])
    return True


# ------ Beauty tail ----------------------------------------------------------
# The end of the picture is a chain, each stage optional:
#
#   Set Alpha -> [Gradient Alpha Over] -> [VFX] -> Group Output / Viewer / EXR Final
#
# Adding or removing any stage calls _rewire_outputs, which re-links
# everything after the gradient, so the stages never bypass each other.

def _beauty_tail(tree):
    """The picture before VFX: the gradient composite if there is one, else Set Alpha. Or None."""
    alpha_over = tree.nodes.get(f"{COMP_GRADIENT_TAG}_AlphaOver")
    if alpha_over is not None:
        return alpha_over.outputs["Image"]
    set_alpha = _beauty_endpoints(tree)[0]
    return set_alpha.outputs["Image"] if set_alpha is not None else None


def _rewire_outputs(tree):
    """Link the beauty tail through VFX (if present) into the outputs. Returns a list of what was missing."""
    tail = _beauty_tail(tree)
    if tail is None:
        return ["Set Alpha node (run Compositor Setup first)"]

    end = tail
    bloom = tree.nodes.get(COMP_VFX_BLOOM_NODE)
    vignette = tree.nodes.get(COMP_VFX_VIGNETTE_NODE)
    if bloom is not None and vignette is not None:
        tree.links.new(tail, bloom.inputs["Image"])
        end = vignette.outputs["Image"]

    missing = []
    _set_alpha, group_output, viewer = _beauty_endpoints(tree)
    if group_output is not None:
        tree.links.new(end, group_output.inputs["Image"])
    else:
        missing.append("Group Output node")
    if viewer is not None:
        tree.links.new(end, viewer.inputs["Image"])

    # "Final" only exists while something sits on top of the clean beauty.
    has_extras = end is not tail or tree.nodes.get(f"{COMP_GRADIENT_TAG}_AlphaOver") is not None
    if has_extras:
        if not _set_exr_layer(tree, FINAL_EXR_LAYER, end):
            missing.append("EXR Passes node (Final layer not saved)")
    else:
        _remove_exr_layer(tree, FINAL_EXR_LAYER)
    return missing


def remove_gradient_bg(tree):
    """Delete the gradient nodes and its EXR layer, and wire Set Alpha straight back into the chain."""
    _remove_exr_layer(tree, GRADIENT_EXR_LAYER)
    for node in _gradient_nodes(tree):
        tree.nodes.remove(node)
    _rewire_outputs(tree)


def apply_gradient_settings(scene):
    """Push the scene's gradient props into the existing nodes (no rebuild)."""
    tree = getattr(scene, "compositing_node_group", None)
    if tree is None:
        return
    nodes = tree.nodes
    type_mix = nodes.get(f"{COMP_GRADIENT_TAG}_TypeMix")
    if type_mix is None:
        return
    type_mix.inputs["Factor"].default_value = 1.0 if getattr(scene, GRADIENT_TYPE_PROP) == "RADIAL" else 0.0

    angle = getattr(scene, GRADIENT_ANGLE_PROP)
    dot = nodes.get(f"{COMP_GRADIENT_TAG}_LinDot")
    if dot is not None:
        dot.inputs[1].default_value = (math.sin(angle), math.cos(angle), 0.0)

    rad_range = nodes.get(f"{COMP_GRADIENT_TAG}_RadRange")
    if rad_range is not None:
        rad_range.inputs["From Max"].default_value = max(getattr(scene, GRADIENT_SIZE_PROP), 1e-4)

    color_mix = nodes.get(f"{COMP_GRADIENT_TAG}_ColorMix")
    if color_mix is not None:
        a = next(s for s in color_mix.inputs if s.identifier == "A_Color")
        b = next(s for s in color_mix.inputs if s.identifier == "B_Color")
        a.default_value = (*getattr(scene, GRADIENT_COLOR_1_PROP), 1.0)
        b.default_value = (*getattr(scene, GRADIENT_COLOR_2_PROP), 1.0)


def insert_gradient_bg(tree, scene):
    """(Re)build the gradient behind the beauty in `tree`. Returns a list of what was missing."""
    missing = []
    remove_gradient_bg(tree)
    set_alpha = _beauty_endpoints(tree)[0]
    if set_alpha is None:
        return ["Set Alpha node (run Compositor Setup first)"]

    layout = COMP_LAYOUT["gradient"]
    frame = _frame(tree, "Gradient BG", layout["frame"])
    frame.name = f"{COMP_GRADIENT_TAG}_Frame"
    links = tree.links

    coords = _gradient_node(tree, "CompositorNodeImageCoordinates", "Coords", layout["coords"], frame, "Image Coordinates")
    links.new(set_alpha.outputs["Image"], coords.inputs["Image"])

    # linear: 0.5 - dot(Normalized - 0.5, direction)
    center = _gradient_node(tree, "ShaderNodeVectorMath", "LinCenter", layout["lin_center"], frame, "Center")
    center.operation = "SUBTRACT"
    center.inputs[1].default_value = (0.5, 0.5, 0.0)
    links.new(coords.outputs["Normalized"], center.inputs[0])

    dot = _gradient_node(tree, "ShaderNodeVectorMath", "LinDot", layout["lin_dot"], frame, "Direction (Angle)")
    dot.operation = "DOT_PRODUCT"
    links.new(center.outputs["Vector"], dot.inputs[0])

    flip = _gradient_node(tree, "ShaderNodeMath", "LinFlip", layout["lin_flip"], frame, "Linear")
    flip.operation = "SUBTRACT"
    flip.inputs[0].default_value = 0.5
    links.new(dot.outputs["Value"], flip.inputs[1])

    # radial: smoothstep(0, size, |Uniform|)
    length = _gradient_node(tree, "ShaderNodeVectorMath", "RadLength", layout["rad_length"], frame, "Distance")
    length.operation = "LENGTH"
    links.new(coords.outputs["Uniform"], length.inputs[0])

    rad_range = _gradient_node(tree, "ShaderNodeMapRange", "RadRange", layout["rad_range"], frame, "Radial (Size)")
    rad_range.interpolation_type = "SMOOTHSTEP"
    rad_range.clamp = True
    rad_range.inputs["From Min"].default_value = 0.0
    links.new(length.outputs["Value"], rad_range.inputs["Value"])

    # pick linear/radial, clamp, color
    type_mix = _gradient_node(tree, "ShaderNodeMix", "TypeMix", layout["type_mix"], frame, "Linear / Radial")
    type_mix.data_type = "FLOAT"
    type_mix.clamp_factor = True
    links.new(flip.outputs["Value"], next(s for s in type_mix.inputs if s.identifier == "A_Float"))
    links.new(rad_range.outputs["Result"], next(s for s in type_mix.inputs if s.identifier == "B_Float"))

    clamp = _gradient_node(tree, "ShaderNodeMapRange", "Clamp", layout["clamp"], frame, "Clamp 0-1")
    clamp.clamp = True
    links.new(next(s for s in type_mix.outputs if s.identifier == "Result_Float"), clamp.inputs["Value"])

    color_mix, _a, _b, color = _mix(tree, "MIX", layout["color_mix"], frame, "Color 1 -> Color 2")
    color_mix.name = f"{COMP_GRADIENT_TAG}_ColorMix"
    links.new(clamp.outputs["Result"], color_mix.inputs["Factor"])

    # composite: beauty over gradient. Straight Alpha off -- the rebuilt
    # beauty is premultiplied (light passes are already coverage-weighted).
    alpha_over = _gradient_node(tree, "CompositorNodeAlphaOver", "AlphaOver", layout["alpha_over"], None, "Over Gradient BG")
    alpha_over.inputs["Straight Alpha"].default_value = False
    links.new(color, alpha_over.inputs["Background"])
    links.new(set_alpha.outputs["Image"], alpha_over.inputs["Foreground"])

    # Passes file: Beauty stays the clean transparent beauty; the gradient goes
    # in on its own (to rebuild/swap the BG in comp), and _rewire_outputs puts
    # the finished picture in "Final".
    if not _set_exr_layer(tree, GRADIENT_EXR_LAYER, color):
        missing.append("EXR Passes node (gradient layer not saved)")
    missing += _rewire_outputs(tree)

    apply_gradient_settings(scene)
    return missing


def _gradient_settings_update(self, context):
    apply_gradient_settings(self)


# ------ VFX ----------------------------------------------------------------------
# The finishing stack from the "vfx" frame in Teaching_File.blend, applied to
# the whole finished picture (after the gradient background):
#
#   Glare Bloom -> Glare Streaks (blue tint) -> Lens Distortion (dispersion only)
#   -> Emanate_Vignette (rounded-rectangle darkening of HSV value, alpha kept)
#
# Values below are exactly what that file used. Inputs are keyed by socket
# name; MENU sockets take their item identifier ("Bloom", "Medium", ...).

VFX_BLOOM_SETTINGS = (
    ("Type", "Bloom"), ("Quality", "Medium"),
    ("Threshold", 1.0), ("Smoothness", 0.1), ("Clamp", False), ("Maximum", 10.0),
    ("Strength", 0.25), ("Saturation", 1.0), ("Tint", (1.0, 1.0, 1.0, 1.0)), ("Size", 0.5),
)
VFX_STREAKS_SETTINGS = (
    ("Type", "Streaks"), ("Quality", "Medium"),
    ("Threshold", 1.0), ("Smoothness", 0.1), ("Clamp", False), ("Maximum", 10.0),
    ("Strength", 0.25), ("Saturation", 1.0), ("Tint", (0.7895829677581787, 0.9648768901824951, 1.0, 1.0)),
    ("Size", 0.25), ("Streaks", 2), ("Streaks Angle", 0.0), ("Iterations", 3),
    ("Fade", 0.75), ("Color Modulation", 0.25),
)
VFX_LENS_SETTINGS = (
    ("Type", "Radial"), ("Distortion", 0.0), ("Dispersion", 0.05), ("Jitter", False), ("Fit", True),
)
VFX_VIGNETTE_SETTINGS = (
    ("Factor", 0.37569060921669006), ("Feather", 1.0), ("Corner Roundness", 1.0),
    ("Scale", (0.95, 0.95)), ("Offset", (0.0, 0.0)), ("Angle", 0.0),
)


def _apply_inputs(node, settings, missing):
    for name, value in settings:
        socket = node.inputs.get(name)
        if socket is None:
            missing.append(f"{node.label} input {name!r}")
            continue
        try:
            socket.default_value = value
        except (TypeError, ValueError):
            missing.append(f"{node.label} {name} = {value!r}")


def _vfx_node(tree, bl_idname, name, label, location, parent):
    node = tree.nodes.new(bl_idname)
    node.name = name
    node.label = label
    _place(node, location, parent)
    return node


def _vfx_nodes(tree):
    return [node for node in tree.nodes if node.name.startswith(COMP_VFX_TAG)]


def remove_vfx(tree):
    """Delete the VFX nodes and wire the beauty tail straight back to the outputs."""
    for node in _vfx_nodes(tree):
        tree.nodes.remove(node)
    _rewire_outputs(tree)


def insert_vfx(tree):
    """(Re)build the VFX stack at the end of `tree`. Returns a list of what was missing."""
    remove_vfx(tree)
    if _beauty_tail(tree) is None:
        return ["Set Alpha node (run Compositor Setup first)"]

    missing = []
    layout = COMP_LAYOUT["vfx"]
    frame = _frame(tree, "VFX", layout["frame"])
    frame.name = f"{COMP_VFX_TAG}_Frame"

    bloom = _vfx_node(tree, "CompositorNodeGlare", COMP_VFX_BLOOM_NODE, "Bloom", layout["bloom"], frame)
    _apply_inputs(bloom, VFX_BLOOM_SETTINGS, missing)

    streaks = _vfx_node(tree, "CompositorNodeGlare", COMP_VFX_STREAKS_NODE, "Streaks", layout["streaks"], frame)
    _apply_inputs(streaks, VFX_STREAKS_SETTINGS, missing)

    lens = _vfx_node(tree, "CompositorNodeLensdist", COMP_VFX_LENS_NODE, "Lens Dispersion", layout["lens"], frame)
    _apply_inputs(lens, VFX_LENS_SETTINGS, missing)

    vignette = _vfx_node(tree, "CompositorNodeGroup", COMP_VFX_VIGNETTE_NODE, "Vignette", layout["vignette"], frame)
    vignette.node_tree = vfx_node_groups.ensure_vignette_group()
    _apply_inputs(vignette, VFX_VIGNETTE_SETTINGS, missing)

    links = tree.links
    links.new(bloom.outputs["Image"], streaks.inputs["Image"])
    links.new(streaks.outputs["Image"], lens.inputs["Image"])
    links.new(lens.outputs["Image"], vignette.inputs["Image"])

    missing += _rewire_outputs(tree)
    return missing


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
        self.report(
            {"INFO"},
            f"Compositor Setup applied ({len(changed)} change(s), {groups}) -- raise Fog Density to add mist",
        )
        return {"FINISHED"}


class EMANATE_OT_gradient_bg(bpy.types.Operator):
    bl_idname = NAMES_GRADIENT_BG.operator_idname
    bl_label = NAMES_GRADIENT_BG.label
    bl_description = NAMES_GRADIENT_BG.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        changed = []
        missing = []

        tree = getattr(scene, "compositing_node_group", None)
        if tree is None or tree.name != COMP_TREE_NAME:
            # No Emanate compositor yet -- build it, exactly as Compositor Setup would.
            pass_changed, pass_missing = enable_production_passes(context.view_layer)
            comp_changed, comp_missing, _groups = build_compositor(scene, context.view_layer)
            out_changed, out_missing = apply_output_mode(scene, getattr(scene, COMP_OUTPUT_MODE_PROP))
            changed += pass_changed + comp_changed + out_changed
            missing += pass_missing + comp_missing + out_missing
            tree = scene.compositing_node_group

        # The gradient only shows where the render is transparent.
        _set(scene.render, "film_transparent", True, changed, missing)
        setattr(scene, GRADIENT_ENABLED_PROP, True)
        missing += insert_gradient_bg(tree, scene)
        changed.append(f"gradient background ({getattr(scene, GRADIENT_TYPE_PROP).lower()})")

        if missing:
            self.report({"WARNING"}, f"Create Gradient BG: skipped {', '.join(missing)}")
        for line in changed:
            print(f"[gradient-bg] {line}")
        self.report({"INFO"}, "Gradient background added behind the beauty")
        return {"FINISHED"}


class EMANATE_OT_gradient_bg_remove(bpy.types.Operator):
    bl_idname = NAMES_GRADIENT_BG_REMOVE.operator_idname
    bl_label = NAMES_GRADIENT_BG_REMOVE.label
    bl_description = NAMES_GRADIENT_BG_REMOVE.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        setattr(scene, GRADIENT_ENABLED_PROP, False)
        tree = getattr(scene, "compositing_node_group", None)
        if tree is not None and tree.name == COMP_TREE_NAME:
            remove_gradient_bg(tree)
        self.report({"INFO"}, "Gradient background removed")
        return {"FINISHED"}


class EMANATE_OT_vfx_add(bpy.types.Operator):
    bl_idname = NAMES_VFX_ADD.operator_idname
    bl_label = NAMES_VFX_ADD.label
    bl_description = NAMES_VFX_ADD.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        changed = []
        missing = []

        tree = getattr(scene, "compositing_node_group", None)
        if tree is None or tree.name != COMP_TREE_NAME:
            # No Emanate compositor yet -- build it, exactly as Compositor Setup would.
            # build_compositor restores VFX itself once the prop is on, so set it first.
            setattr(scene, VFX_ENABLED_PROP, True)
            pass_changed, pass_missing = enable_production_passes(context.view_layer)
            comp_changed, comp_missing, _groups = build_compositor(scene, context.view_layer)
            out_changed, out_missing = apply_output_mode(scene, getattr(scene, COMP_OUTPUT_MODE_PROP))
            changed += pass_changed + comp_changed + out_changed
            missing += pass_missing + comp_missing + out_missing
        else:
            setattr(scene, VFX_ENABLED_PROP, True)
            missing += insert_vfx(tree)
            changed.append("VFX stack")

        if missing:
            self.report({"WARNING"}, f"Add VFX: skipped {', '.join(missing)}")
        for line in changed:
            print(f"[vfx] {line}")
        self.report({"INFO"}, "VFX added: bloom, streaks, lens dispersion, vignette")
        return {"FINISHED"}


class EMANATE_OT_vfx_remove(bpy.types.Operator):
    bl_idname = NAMES_VFX_REMOVE.operator_idname
    bl_label = NAMES_VFX_REMOVE.label
    bl_description = NAMES_VFX_REMOVE.description
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        setattr(scene, VFX_ENABLED_PROP, False)
        tree = getattr(scene, "compositing_node_group", None)
        if tree is not None and tree.name == COMP_TREE_NAME:
            remove_vfx(tree)
        self.report({"INFO"}, "VFX removed")
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


class EMANATE_OT_hdri_download(bpy.types.Operator):
    bl_idname = NAMES_HDRI_DOWNLOAD.operator_idname
    bl_label = NAMES_HDRI_DOWNLOAD.label
    bl_description = NAMES_HDRI_DOWNLOAD.description
    bl_options = {"REGISTER"}

    _timer = None

    def execute(self, context):
        # Extensions must not touch the network unless the user allowed it.
        if not bpy.app.online_access:
            self.report(
                {"WARNING"},
                "Download HDRIs: turn on Allow Online Access (Preferences > System > Network) first",
            )
            return {"CANCELLED"}
        if _download["thread"] is not None and _download["thread"].is_alive():
            self.report({"INFO"}, "Download HDRIs: already running")
            return {"CANCELLED"}
        target_dir = user_hdri_dir(create=True)
        if target_dir is None:
            self.report(
                {"WARNING"},
                "Download HDRIs: only available when installed as an extension -- "
                "set the HDRI folder in the add-on preferences instead",
            )
            return {"CANCELLED"}

        _download.update(status="", error=None, cancel=False)
        _download["thread"] = threading.Thread(target=_download_worker, args=(target_dir,), daemon=True)
        _download["thread"].start()
        self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            _download["cancel"] = True
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        if context.workspace is not None:
            context.workspace.status_text_set(f"Download HDRIs -- {_download['status']}  (Esc to cancel)")
        for area in context.screen.areas if context.screen else ():
            if area.type in ("VIEW_3D", "PREFERENCES"):
                area.tag_redraw()
        if _download["thread"].is_alive():
            return {"PASS_THROUGH"}

        context.window_manager.event_timer_remove(self._timer)
        if context.workspace is not None:
            context.workspace.status_text_set(None)
        clear_hdri_cache()
        if _download["error"]:
            self.report({"WARNING"}, f"Download HDRIs: {_download['error']}")
            return {"CANCELLED"}
        self.report({"INFO"}, _download["status"])
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
        scene = context.scene
        render = scene.render
        # Collapsible sections are layout panels rather than panel classes of
        # their own -- same reasoning as tech_tools' "Colors" section: naming_unity
        # wants every registered panel parented to the root.
        self._draw_presets(layout)
        self._draw_hdri(layout, scene)
        nodes = _comp_tree_nodes(scene)
        self._draw_compositor(layout, scene, render, nodes)
        self._draw_vfx(layout, scene, nodes)

    @staticmethod
    def _draw_presets(layout):
        header, body = layout.panel("emanate_render_presets", default_closed=True)
        header.label(text="Presets", icon="PRESET")
        if not body:
            return
        body.operator(NAMES_CINEMA_BASE.operator_idname, icon="SHADING_RENDERED")
        body.operator(NAMES_FAST_CLEAN_STATIC.operator_idname, icon="RENDER_STILL")

    @staticmethod
    def _draw_hdri(layout, scene):
        header, body = layout.panel("emanate_render_hdri", default_closed=True)
        header.label(text="HDRI Lighting", icon="WORLD")
        # In the header, so a rescan works with the section collapsed.
        header.operator(NAMES_HDRI_REFRESH.operator_idname, text="", icon="FILE_REFRESH")
        if not body:
            return
        if getattr(scene, HDRI_CHOICE_PROP) == "NONE":
            body.label(text="No HDRIs found", icon="ERROR")
            draw_hdri_download(body)
        else:
            body.template_icon_view(scene, HDRI_CHOICE_PROP, show_labels=True, scale=6.0, scale_popup=6.0)
            body.operator(NAMES_HDRI_LIGHTING.operator_idname, icon="WORLD")

        # Live controls, drawn straight off the world's nodes -- only while the
        # scene is actually using the HDRI world.
        world = scene.world
        if world is not None and world.name == HDRI_WORLD_NAME:
            background, mapping = get_hdri_world_nodes()
            col = body.column(align=True)
            if background is not None:
                col.prop(background.inputs["Strength"], "default_value", text="Strength")
            if mapping is not None:
                col.prop(mapping.inputs["Rotation"], "default_value", index=2, text="Rotation")
            col.prop(scene.render, "film_transparent", text="Hide from Camera")

    @staticmethod
    def _draw_compositor(layout, scene, render, nodes):
        header, body = layout.panel("emanate_render_compositor", default_closed=True)
        header.label(text="Compositor", icon="NODE_COMPOSITING")
        if not body:
            return
        body.operator(NAMES_COMPOSITOR_SETUP.operator_idname, icon="NODE_COMPOSITING")
        body.prop(scene, COMP_DENOISE_PROP)
        body.row().prop(scene, COMP_OUTPUT_MODE_PROP, expand=True)

        row = body.row(align=True)
        row.prop(render, "use_motion_blur", text="Motion Blur")
        if render.use_motion_blur:
            row.prop(render, "motion_blur_shutter", text="Shutter")

        # Live fog controls, drawn straight off the nodes Compositor Setup built.
        density = nodes.get(COMP_MIST_DENSITY_NODE) if nodes is not None else None
        if density is not None:
            body.separator()
            body.label(text="Mist Fog", icon="FORCE_TURBULENCE")
            col = body.column(align=True)
            col.prop(density.inputs[1], "default_value", text="Density")
            fog_color = nodes.get(COMP_MIST_COLOR_NODE)
            if fog_color is not None:
                col.prop(fog_color.outputs[0], "default_value", text="")
            mist_range = nodes.get(COMP_MIST_RANGE_NODE)
            if mist_range is not None:
                row = body.row(align=True)
                row.prop(mist_range.inputs["From Min"], "default_value", text="Range Min")
                row.prop(mist_range.inputs["From Max"], "default_value", text="Max")
            mist_settings = scene.world.mist_settings if scene.world is not None else None
            if mist_settings is not None:
                col = body.column(align=True)
                col.prop(mist_settings, "start", text="Mist Start")
                col.prop(mist_settings, "depth", text="Mist Depth")
                col.prop(mist_settings, "falloff", text="")
        body.separator()
        if not getattr(scene, GRADIENT_ENABLED_PROP):
            body.operator(NAMES_GRADIENT_BG.operator_idname, icon="IMAGE_BACKGROUND")
        else:
            header = body.row(align=True)
            header.label(text="Gradient BG", icon="IMAGE_BACKGROUND")
            header.operator(NAMES_GRADIENT_BG.operator_idname, text="", icon="FILE_REFRESH")
            header.operator(NAMES_GRADIENT_BG_REMOVE.operator_idname, text="", icon="X")
            body.row().prop(scene, GRADIENT_TYPE_PROP, expand=True)
            col = body.column(align=True)
            radial = getattr(scene, GRADIENT_TYPE_PROP) == "RADIAL"
            col.prop(scene, GRADIENT_COLOR_1_PROP, text="Center" if radial else "Top")
            col.prop(scene, GRADIENT_COLOR_2_PROP, text="Edge" if radial else "Bottom")
            col.prop(scene, GRADIENT_SIZE_PROP if radial else GRADIENT_ANGLE_PROP)

    @staticmethod
    def _draw_vfx(layout, scene, nodes):
        enabled = getattr(scene, VFX_ENABLED_PROP)
        header, body = layout.panel("emanate_render_vfx", default_closed=True)
        header.label(text="VFX", icon="SHADERFX")
        if enabled:
            header.operator(NAMES_VFX_ADD.operator_idname, text="", icon="FILE_REFRESH")
            header.operator(NAMES_VFX_REMOVE.operator_idname, text="", icon="X")
        if not body:
            return
        if not enabled:
            body.operator(NAMES_VFX_ADD.operator_idname, icon="SHADERFX")
            return
        # Live controls, drawn straight off the nodes Add VFX built.
        if nodes is not None:
            col = body.column(align=True)
            for node_name, socket_name, text in (
                (COMP_VFX_BLOOM_NODE, "Strength", "Bloom"),
                (COMP_VFX_STREAKS_NODE, "Strength", "Streaks"),
                (COMP_VFX_LENS_NODE, "Dispersion", "Dispersion"),
                (COMP_VFX_VIGNETTE_NODE, "Factor", "Vignette"),
                (COMP_VFX_VIGNETTE_NODE, "Feather", "Vignette Feather"),
            ):
                node = nodes.get(node_name)
                socket = node.inputs.get(socket_name) if node is not None else None
                if socket is not None:
                    col.prop(socket, "default_value", text=text)


_classes = (
    EMANATE_AP_preferences,
    EMANATE_OT_cinema_base,
    EMANATE_OT_fast_clean_static,
    EMANATE_OT_hdri_lighting,
    EMANATE_OT_hdri_refresh,
    EMANATE_OT_hdri_download,
    EMANATE_OT_compositor_setup,
    EMANATE_OT_gradient_bg,
    EMANATE_OT_gradient_bg_remove,
    EMANATE_OT_vfx_add,
    EMANATE_OT_vfx_remove,
    EMANATE_PT_render_tools,
)

_GRADIENT_PROPS = (
    GRADIENT_ENABLED_PROP, GRADIENT_TYPE_PROP, GRADIENT_COLOR_1_PROP,
    GRADIENT_COLOR_2_PROP, GRADIENT_ANGLE_PROP, GRADIENT_SIZE_PROP,
)


def _register_gradient_props():
    scene = bpy.types.Scene
    setattr(scene, GRADIENT_ENABLED_PROP, bpy.props.BoolProperty(
        name="Gradient BG Enabled",
        description="Set by Create Gradient BG; a Compositor Setup rebuild puts the gradient back while this is on",
        default=False,
    ))
    setattr(scene, GRADIENT_TYPE_PROP, bpy.props.EnumProperty(
        name="Gradient Type",
        items=(
            ("LINEAR", "Linear", "Straight gradient from Color 1 to Color 2 across the frame"),
            ("RADIAL", "Radial", "Circular gradient from Color 1 in the center to Color 2 at the edge"),
        ),
        default="LINEAR",
        update=_gradient_settings_update,
    ))
    setattr(scene, GRADIENT_COLOR_1_PROP, bpy.props.FloatVectorProperty(
        name="Color 1", description="Top (linear) or center (radial) color",
        subtype="COLOR", size=3, min=0.0, soft_max=1.0, default=(0.30, 0.30, 0.32),
        update=_gradient_settings_update,
    ))
    setattr(scene, GRADIENT_COLOR_2_PROP, bpy.props.FloatVectorProperty(
        name="Color 2", description="Bottom (linear) or edge (radial) color",
        subtype="COLOR", size=3, min=0.0, soft_max=1.0, default=(0.02, 0.02, 0.025),
        update=_gradient_settings_update,
    ))
    setattr(scene, GRADIENT_ANGLE_PROP, bpy.props.FloatProperty(
        name="Angle", description="Direction of a linear gradient; 0 puts Color 1 at the top",
        subtype="ANGLE", default=0.0, min=-math.pi, max=math.pi,
        update=_gradient_settings_update,
    ))
    setattr(scene, GRADIENT_SIZE_PROP, bpy.props.FloatProperty(
        name="Size", description="Radius of a radial gradient, where it fully reaches Color 2",
        default=1.0, min=0.01, soft_max=3.0,
        update=_gradient_settings_update,
    ))


def register():
    global _previews
    naming.check_classes((EMANATE_OT_cinema_base,), NAMES_CINEMA_BASE)
    naming.check_classes((EMANATE_OT_fast_clean_static,), NAMES_FAST_CLEAN_STATIC)
    naming.check_classes((EMANATE_OT_hdri_lighting,), NAMES_HDRI_LIGHTING)
    naming.check_classes((EMANATE_OT_hdri_refresh,), NAMES_HDRI_REFRESH)
    naming.check_classes((EMANATE_OT_hdri_download,), NAMES_HDRI_DOWNLOAD)
    naming.check_classes((EMANATE_OT_compositor_setup,), NAMES_COMPOSITOR_SETUP)
    naming.check_classes((EMANATE_OT_gradient_bg,), NAMES_GRADIENT_BG)
    naming.check_classes((EMANATE_OT_gradient_bg_remove,), NAMES_GRADIENT_BG_REMOVE)
    naming.check_classes((EMANATE_OT_vfx_add,), NAMES_VFX_ADD)
    naming.check_classes((EMANATE_OT_vfx_remove,), NAMES_VFX_REMOVE)
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
                ("EXR", "EXR", "Final picture to a 32-bit EXR in //render/final/; all passes always saved to //render/exr/"),
                ("MOVIE", "Movie (MP4)", "Final picture to H.264 MP4 in //render/movie/; passes still saved to //render/exr/"),
            ),
            default="EXR",
            update=_comp_output_mode_update,
        ),
    )
    _register_gradient_props()
    setattr(
        bpy.types.Scene,
        VFX_ENABLED_PROP,
        bpy.props.BoolProperty(
            name="VFX Enabled",
            description="Set by Add VFX; a Compositor Setup rebuild puts the VFX stack back while this is on",
            default=False,
        ),
    )


def unregister():
    global _previews
    delattr(bpy.types.Scene, VFX_ENABLED_PROP)
    for prop in reversed(_GRADIENT_PROPS):
        delattr(bpy.types.Scene, prop)
    delattr(bpy.types.Scene, COMP_OUTPUT_MODE_PROP)
    delattr(bpy.types.Scene, COMP_DENOISE_PROP)
    delattr(bpy.types.Scene, HDRI_CHOICE_PROP)
    clear_hdri_cache()
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
