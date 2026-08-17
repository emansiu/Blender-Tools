import bpy
import sys
import pkgutil
import importlib

from . import tools
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


def _load_tool_modules():
    found = []
    for info in pkgutil.iter_modules(tools.__path__):
        name = f"{tools.__name__}.{info.name}"
        if name in sys.modules:
            found.append(importlib.reload(sys.modules[name]))
        else:
            found.append(importlib.import_module(name))
    return found


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