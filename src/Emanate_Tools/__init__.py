import bpy
import sys
import pkgutil
import importlib

from . import tools


class EMANATE_STUDIOS_PT_panel(bpy.types.Panel):
    bl_label = "EMANATE STUDIOS Tools"
    bl_idname = "EMANATE_STUDIOS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "EMANATE STUDIOS"

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
    bpy.utils.register_class(EMANATE_STUDIOS_PT_panel)
    _modules[:] = _load_tool_modules()
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
    _modules.clear()
    bpy.utils.unregister_class(EMANATE_STUDIOS_PT_panel)