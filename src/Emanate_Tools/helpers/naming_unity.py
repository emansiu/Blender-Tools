"""
naming_unity.py
===============
Single source of truth for every Blender identifier used by this add-on.

Nothing in this add-on should ever type an identifier string by hand. Ask this
module for it instead. That way a name can only be wrong in one place, and if
it is wrong it is wrong everywhere consistently, which is easy to spot.

Place this file at the package root:

    emanate_tools/
    |-- __init__.py
    |-- blender_manifest.toml
    |-- naming_unity.py          <- this file
    `-- tools/
        |-- __init__.py
        `-- uv_checker.py


-------------------------------------------------------------------------------
BLENDER'S NAMING RULES  (the ones that will actually bite you)
-------------------------------------------------------------------------------

1. OPERATOR bl_idname
   Format is "namespace.operator_name" -- exactly one dot.
   Lowercase ASCII letters, digits and underscores only. Each half must start
   with a letter. Uppercase, spaces, hyphens or a second dot are a HARD ERROR:
   register_class() raises and the add-on fails to load.
   Keep the whole string under 64 characters.
   This is what you call at runtime: bpy.ops.emanate.uv_checker()

2. CLASS NAME CONVENTION
   Blender expects UPPERCASEPREFIX_XX_lowercase_name, where XX is the type tag:
       _OT_  Operator        _PT_  Panel          _MT_  Menu
       _UL_  UIList          _HT_  Header         _PG_  PropertyGroup
   Break this and Blender prints a warning to the console. It usually still
   registers, but do not rely on that -- the warning is telling you that some
   internal lookups will not behave.

   The class NAME itself must be typed literally in the `class` statement.
   Python cannot compute it. So the class name is the one string this module
   cannot generate for you. Use check_class() below to catch typos.

3. PANEL bl_idname
   If you omit it, Blender derives it from the class name. Set it explicitly
   anyway -- an explicit value is what makes bl_parent_id reliable.

4. bl_parent_id  <-- the one people get wrong
   A CHILD panel's bl_parent_id must equal its PARENT panel's bl_idname.
   It is not a self-reference. It points at a different class.
   The child must ALSO declare the same bl_space_type and bl_region_type as
   the parent. If any of those three disagree, the sub-panel does not appear
   and Blender reports nothing at all. Silent failure.

5. REGISTRATION ORDER
   Register the parent panel BEFORE any child that points at it.
   Unregister in reverse order. Panels reference operators, so tearing down
   forwards can leave dangling references.

6. UNIQUENESS
   Two registered classes may not share a bl_idname. This namespace is global
   across every add-on the user has installed, not just yours -- which is the
   whole reason for the prefix.

7. bl_category
   The sidebar tab label. Only meaningful when bl_region_type == 'UI'.
   Set it on the ROOT panel only. Child panels inherit their location from the
   parent; setting it on a child is ignored at best and confusing at worst.

8. bl_label
   Human-readable UI text. No constraints. Spaces and capitals are fine.
   This is the only string here meant for humans to read.

9. CUSTOM PROPERTIES
   Anything you attach to bpy.types.Scene / Object / etc. lives in a global
   namespace shared with every other add-on. Always prefix. Use prop_name().

10. EXTENSION id
    The `id` in blender_manifest.toml must match the folder name containing it,
    and it becomes a Python module name. Changing it after publishing orphans
    every existing install -- Blender treats it as a different extension.
"""

import re


# -----------------------------------------------------------------------------
# The three strings everything else is derived from.
# Change these once, here, and the whole add-on follows.
# -----------------------------------------------------------------------------

CLASS_PREFIX = "EMANATE"   # uppercase, used in class names and panel idnames
NAMESPACE = "emanate"      # lowercase, used as the operator namespace
CATEGORY = "Emanate"       # the sidebar tab label the user sees

# The root panel every tool panel hangs off. Import this for bl_parent_id.
ROOT_PANEL_IDNAME = f"{CLASS_PREFIX}_PT_root"
ROOT_PANEL_LABEL = "Emanate Tools"

# Shared by the root panel and every child. Children MUST match the parent.
SPACE_TYPE = 'VIEW_3D'
REGION_TYPE = 'UI'


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

# A tool key: lowercase, starts with a letter, letters/digits/underscores only.
# This is deliberately stricter than Blender requires so that one key can be
# safely turned into an operator idname, a panel idname and a property name.
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Blender's actual operator idname rule, for check_class().
_OPERATOR_IDNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

_MAX_OPERATOR_IDNAME = 64


class NamingError(Exception):
    """Raised when a name would be invalid or would collide."""


def _validate_key(key):
    if not isinstance(key, str):
        raise NamingError(f"Tool key must be a string, got {type(key).__name__}")
    if not _KEY_PATTERN.match(key):
        raise NamingError(
            f"Invalid tool key {key!r}. Use lowercase letters, digits and "
            f"underscores, starting with a letter. Example: 'uv_checker'"
        )


# -----------------------------------------------------------------------------
# What a tool gets back
# -----------------------------------------------------------------------------

class ToolNames:
    """Every identifier one tool needs. Built once, read everywhere."""

    __slots__ = (
        "key", "label", "description", "order",
        "operator_idname", "operator_classname",
        "panel_idname", "panel_classname",
        "_owner",
    )

    def __init__(self, key, label, description, order, owner):
        self.key = key
        self.label = label
        self.description = description
        self.order = order
        self._owner = owner

        # What you assign to bl_idname on the Operator.
        self.operator_idname = f"{NAMESPACE}.{key}"

        # What you must type as the Operator's class name.
        self.operator_classname = f"{CLASS_PREFIX}_OT_{key}"

        # What you assign to bl_idname on the Panel.
        self.panel_idname = f"{CLASS_PREFIX}_PT_{key}"

        # What you must type as the Panel's class name.
        self.panel_classname = self.panel_idname

        if len(self.operator_idname) > _MAX_OPERATOR_IDNAME:
            raise NamingError(
                f"Operator idname {self.operator_idname!r} is "
                f"{len(self.operator_idname)} characters; the limit is "
                f"{_MAX_OPERATOR_IDNAME}. Shorten the tool key."
            )

    def __repr__(self):
        return f"<ToolNames {self.key!r} order={self.order}>"


# -----------------------------------------------------------------------------
# The registry
# -----------------------------------------------------------------------------

# key -> ToolNames. This is the "list of names in use" -- the thing that makes
# collisions impossible rather than merely unlikely.
_REGISTRY = {}

_ORDER_STEP = 10


def register_tool(key, *, label, owner, description="", order=None):
    """Claim a name for one tool and get every identifier it needs.

    Call this once, at module level, in each file under tools/.

        NAMES = naming_unity.register_tool(
            "uv_checker",
            label="UV Checker",
            owner=__name__,
        )

    `owner` must be __name__. It is what makes this safe under Reload Scripts:
    re-importing the same module re-claims its own key harmlessly, while a
    genuinely different module claiming a taken key raises immediately.

    `order` controls sub-panel position. Leave it None to auto-assign in
    multiples of 10, which leaves gaps you can slot things into later.
    """
    _validate_key(key)

    existing = _REGISTRY.get(key)
    if existing is not None and existing._owner != owner:
        raise NamingError(
            f"Tool key {key!r} is already claimed by {existing._owner!r}, "
            f"so {owner!r} cannot use it. Pick a different key."
        )

    if order is None:
        order = (existing.order if existing
                 else (len(_REGISTRY) + 1) * _ORDER_STEP)

    names = ToolNames(key, label, description, order, owner)
    _REGISTRY[key] = names
    return names


def get(key):
    """Look up an already-registered tool. Raises if it does not exist."""
    try:
        return _REGISTRY[key]
    except KeyError:
        raise NamingError(
            f"No tool registered under {key!r}. "
            f"Registered: {sorted(_REGISTRY)}"
        ) from None


def all_tools():
    """Every registered tool, in panel display order."""
    return sorted(_REGISTRY.values(), key=lambda n: (n.order, n.key))


def prop_name(suffix):
    """Namespaced name for a custom property on Scene, Object, etc.

        bpy.types.Scene.emanate_target_res = bpy.props.IntProperty(...)
        setattr(bpy.types.Scene, naming_unity.prop_name("target_res"), ...)
    """
    _validate_key(suffix)
    return f"{NAMESPACE}_{suffix}"


# -----------------------------------------------------------------------------
# Typo catcher
# -----------------------------------------------------------------------------

def check_class(cls, names=None):
    """Verify a class conforms, and that its bl_idname matches the registry.

    Class NAMES have to be typed literally in the `class` statement, so this
    is the one thing the registry cannot enforce for you. Call it from your
    tool's register() to catch a mismatch at load time instead of wondering
    later why a sub-panel never appeared.

    Returns a list of problem strings. Empty list means all good.
    """
    problems = []
    cls_name = cls.__name__
    bl_idname = getattr(cls, "bl_idname", None)

    is_operator = "_OT_" in cls_name
    is_panel = "_PT_" in cls_name

    if not cls_name.startswith(f"{CLASS_PREFIX}_"):
        problems.append(
            f"{cls_name}: class name should start with '{CLASS_PREFIX}_'"
        )

    if is_operator:
        if not bl_idname:
            problems.append(f"{cls_name}: operator has no bl_idname")
        elif not _OPERATOR_IDNAME_PATTERN.match(bl_idname):
            problems.append(
                f"{cls_name}: bl_idname {bl_idname!r} is not "
                f"'lowercase.lowercase' with exactly one dot"
            )
        elif names and bl_idname != names.operator_idname:
            problems.append(
                f"{cls_name}: bl_idname {bl_idname!r} does not match the "
                f"registry value {names.operator_idname!r}"
            )
        if names and cls_name != names.operator_classname:
            problems.append(
                f"{cls_name}: class should be named "
                f"{names.operator_classname!r}"
            )

    elif is_panel:
        if names and bl_idname != names.panel_idname:
            problems.append(
                f"{cls_name}: bl_idname {bl_idname!r} does not match the "
                f"registry value {names.panel_idname!r}"
            )
        if getattr(cls, "bl_space_type", None) != SPACE_TYPE:
            problems.append(
                f"{cls_name}: bl_space_type must be {SPACE_TYPE!r} to match "
                f"the root panel, or the sub-panel will not appear"
            )
        if getattr(cls, "bl_region_type", None) != REGION_TYPE:
            problems.append(
                f"{cls_name}: bl_region_type must be {REGION_TYPE!r} to match "
                f"the root panel, or the sub-panel will not appear"
            )
        parent = getattr(cls, "bl_parent_id", None)
        if parent and parent != ROOT_PANEL_IDNAME:
            problems.append(
                f"{cls_name}: bl_parent_id {parent!r} does not match "
                f"ROOT_PANEL_IDNAME {ROOT_PANEL_IDNAME!r}"
            )
        if names and cls_name != names.panel_classname:
            problems.append(
                f"{cls_name}: class should be named {names.panel_classname!r}"
            )

    else:
        problems.append(
            f"{cls_name}: no type tag in the class name "
            f"(expected _OT_, _PT_, _MT_, _UL_, _HT_ or _PG_)"
        )

    return problems


def check_classes(classes, names=None, raise_on_problem=False):
    """Run check_class() over several classes. Prints problems to the console.

    Call from register():

        def register():
            naming_unity.check_classes(_classes, NAMES)
            for cls in _classes:
                bpy.utils.register_class(cls)
    """
    problems = []
    for cls in classes:
        problems.extend(check_class(cls, names))

    if problems:
        header = f"[{CLASS_PREFIX}] naming problems:"
        message = "\n  ".join([header] + problems)
        if raise_on_problem:
            raise NamingError(message)
        print(message)

    return problems


# -----------------------------------------------------------------------------
# Worked example -- copy this shape into tools/your_tool.py
# -----------------------------------------------------------------------------
#
# import bpy
# from .. import naming_unity as naming
#
# NAMES = naming.register_tool(
#     "uv_checker",
#     label="UV Checker",
#     owner=__name__,
#     description="Report which UDIM tiles the selection uses",
# )
#
#
# class EMANATE_OT_uv_checker(bpy.types.Operator):
#     bl_idname = NAMES.operator_idname
#     bl_label = NAMES.label
#     bl_description = NAMES.description
#     bl_options = {'REGISTER', 'UNDO'}
#
#     def execute(self, context):
#         self.report({'INFO'}, "Ran UV checker")
#         return {'FINISHED'}
#
#
# class EMANATE_PT_uv_checker(bpy.types.Panel):
#     bl_idname = NAMES.panel_idname
#     bl_label = NAMES.label
#     bl_parent_id = naming.ROOT_PANEL_IDNAME
#     bl_space_type = naming.SPACE_TYPE
#     bl_region_type = naming.REGION_TYPE
#     bl_options = {'DEFAULT_CLOSED'}
#     bl_order = NAMES.order
#
#     def draw(self, context):
#         self.layout.operator(NAMES.operator_idname)
#
#
# _classes = (EMANATE_OT_uv_checker, EMANATE_PT_uv_checker)
#
#
# def register():
#     naming.check_classes(_classes, NAMES)
#     for cls in _classes:
#         bpy.utils.register_class(cls)
#
#
# def unregister():
#     for cls in reversed(_classes):
#         bpy.utils.unregister_class(cls)