import bpy
import sys
import pkgutil
import importlib

from . import helpers, tools
from .helpers import naming_unity as naming


class EMANATE_PT_root(bpy.types.Panel):
    bl_label = naming.ROOT_PANEL_LABEL
    bl_idname = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_category = naming.CATEGORY

    def draw(self, context):
        pass


_modules = []


def _load_package_modules(package):
    """Import every module directly under `package`, reloading any already in."""
    found = []
    for info in pkgutil.iter_modules(package.__path__):
        name = f"{package.__name__}.{info.name}"
        if name in sys.modules:
            found.append(importlib.reload(sys.modules[name]))
        else:
            found.append(importlib.import_module(name))
    return found


def _load_tool_modules():
    """Every module under tools/, freshly reloaded, ready to register().

    helpers/ is reloaded first, and deliberately not returned -- helpers carry
    no register(). The pass exists for ordering: the tool modules call into
    helpers, so an edited helper has to be back in sys.modules BEFORE the tools
    that use it are re-executed.

    Skipping it is what made an edit to helpers/widgets.py invisible to Reload
    Scripts while the edit to tools/rig_creation_tools.py landed -- Blender
    kept whatever helper it imported at startup, and the mismatch surfaced as
    a traceback whose line numbers no longer matched the file on disk.

    Reloading helpers/naming_unity.py also empties its _REGISTRY, so a tool key
    that has been renamed leaves no stale entry behind; every tool re-claims
    its key on the tools pass immediately below.
    """
    _load_package_modules(helpers)
    return _load_package_modules(tools)


def register():
    bpy.utils.register_class(EMANATE_PT_root)
    _modules[:] = _load_tool_modules()
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
    _modules.clear()
    bpy.utils.unregister_class(EMANATE_PT_root)