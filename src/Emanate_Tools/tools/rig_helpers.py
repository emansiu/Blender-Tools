"""Quick-access controls for a rig that already exists.

Unlike rig_creation_tools.py, nothing here builds bones -- it only pokes
values on bones a rig generator already made. Buttons for day-to-day posing
convenience belong here; anything that adds/removes/reparents bones belongs
in rig_creation_tools.py instead.
"""

import bpy

from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "rig_helpers",
    label="Rig Helpers",
    owner=__name__,
    description="Posing shortcuts for an already-built rig",
)

NAMES_FK_MODE = naming.register_tool(
    "fk_mode",
    label="FK Mode",
    owner=__name__,
    description="Sends every IK/FK properties controller to its leftmost (FK) position",
)
NAMES_IK_MODE = naming.register_tool(
    "ik_mode",
    label="IK Mode",
    owner=__name__,
    description="Sends every IK/FK properties controller to its rightmost (IK) position",
)

# The sliders these buttons drive are LIMIT_LOCATION-constrained to local X
# only, 0..PROPERTIES_CONTROLLER_TRAVEL (see rig_creation_tools.py) -- 0 is
# the FK end of the slider, PROPERTIES_CONTROLLER_TRAVEL is the IK end. Kept
# as a literal here rather than imported so this file has no dependency on
# rig_creation_tools.py; if that travel distance ever changes, update both.
IK_FK_TRAVEL = 0.2

# Side-ful and spelled out in full -- these are named controller bones, not a
# chain FINGER_SEGMENTS-style code can build a name for, and there are only
# ever these four.
IK_FK_CONTROLLER_BONES = (
    "PRPT_Right_Leg_Controller",
    "PRPT_Left_Leg_Controller",
    "PRPT_Left_Hand_Controller",
    "PRPT_Right_Hand_Controller",
)


def set_ik_fk_controllers_x(armature_obj, x):
    """Set pose-space location.x on every controller bone that exists.

    Only X moves -- these bones may carry an unrelated Y/Z value from other
    properties, so this never touches those. Missing bones are skipped rather
    than raising, since not every rig has both sides mirrored on yet; the
    caller reports whatever this returns.
    """
    pose_bones = armature_obj.pose.bones
    changed = []
    for name in IK_FK_CONTROLLER_BONES:
        controller_bone = pose_bones.get(name)
        if controller_bone is None:
            continue
        controller_bone.location.x = x
        changed.append(name)
    return changed


class EMANATE_OT_fk_mode(bpy.types.Operator):
    bl_idname = NAMES_FK_MODE.operator_idname
    bl_label = NAMES_FK_MODE.label
    bl_description = NAMES_FK_MODE.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context):
        armature_obj = context.object

        if armature_obj is None or armature_obj.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature first")
            return {"CANCELLED"}

        changed = set_ik_fk_controllers_x(armature_obj, 0.0)

        if not changed:
            self.report({"WARNING"}, f"{armature_obj.name} has none of the IK/FK properties controllers")
            return {"CANCELLED"}

        self.report({"INFO"}, f"{armature_obj.name}: FK mode -- {', '.join(changed)}")
        return {"FINISHED"}


class EMANATE_OT_ik_mode(bpy.types.Operator):
    bl_idname = NAMES_IK_MODE.operator_idname
    bl_label = NAMES_IK_MODE.label
    bl_description = NAMES_IK_MODE.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context):
        armature_obj = context.object

        if armature_obj is None or armature_obj.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature first")
            return {"CANCELLED"}

        changed = set_ik_fk_controllers_x(armature_obj, IK_FK_TRAVEL)

        if not changed:
            self.report({"WARNING"}, f"{armature_obj.name} has none of the IK/FK properties controllers")
            return {"CANCELLED"}

        self.report({"INFO"}, f"{armature_obj.name}: IK mode -- {', '.join(changed)}")
        return {"FINISHED"}


class EMANATE_PT_rig_helpers(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        layout.operator(NAMES_FK_MODE.operator_idname)
        layout.operator(NAMES_IK_MODE.operator_idname)


_classes = (
    EMANATE_OT_fk_mode,
    EMANATE_OT_ik_mode,
    EMANATE_PT_rig_helpers,
)


def register():
    naming.check_classes((EMANATE_OT_fk_mode,), NAMES_FK_MODE)
    naming.check_classes((EMANATE_OT_ik_mode,), NAMES_IK_MODE)
    naming.check_classes((EMANATE_PT_rig_helpers,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
