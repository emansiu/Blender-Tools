DEF_PREFIX = "DEF_"


def sync_deform_flags(armature_obj):
    """Set use_deform on every bone to match whether its name starts with DEF_.

    DEF_ bones are switched on, everything else (Root, MCH_, ORG_, FK_, IK_,
    WGT_, VIS_, tweaks, ...) is switched off, so the rig only ever deforms
    the mesh through its DEF_ chain no matter what other bones a tool created
    along the way -- new bones default to use_deform = True, and most of the
    generator functions never set it explicitly.

    Reads from edit_bones while the armature is in EDIT mode -- the only view
    of bones that accepts changes there -- and from data.bones otherwise, so
    this is safe to call from whatever mode an operator happens to be in.

    Returns a list with one summary string, or an empty list if every bone
    already matched (including when armature_obj is None or not an armature).
    """
    if armature_obj is None or armature_obj.type != 'ARMATURE':
        return []

    bones = (
        armature_obj.data.edit_bones
        if armature_obj.mode == 'EDIT'
        else armature_obj.data.bones
    )

    enabled = 0
    disabled = 0

    for bone in bones:
        should_deform = bone.name.startswith(DEF_PREFIX)
        if bone.use_deform == should_deform:
            continue
        bone.use_deform = should_deform
        if should_deform:
            enabled += 1
        else:
            disabled += 1

    if not enabled and not disabled:
        return []

    return [f"use_deform synced: {enabled} bone(s) -> on, {disabled} bone(s) -> off"]
