def get_or_create_collection(armature, name):
    """Fetch a bone collection by name, creating it if it is missing.

    Looks in collections_all rather than collections so a collection nested
    under another one is found instead of a second one being made alongside it.

    Returns (collection, was_created).
    """
    collection = armature.collections_all.get(name)
    if collection is not None:
        return collection, False
    return armature.collections.new(name), True


def move_bones_to_collection(armature, bone_names, collection):
    """Put the named bones in this collection and no other. EDIT mode.

    Membership is additive, and a bone stays on screen while ANY collection
    holding it is visible -- so hiding one collection only actually hides its
    bones if they are not also sitting in some other, visible collection.
    That is why this unassigns before it assigns.
    """
    moved = 0

    for name in bone_names:
        bone = armature.edit_bones.get(name)
        if bone is None:
            continue

        # list() because unassigning mutates what we are iterating over.
        for other in list(bone.collections):
            if other.name != collection.name:
                other.unassign(bone)

        collection.assign(bone)
        moved += 1

    return moved


def move_bones_with_prefix(armature, prefix, collection):
    """Move every edit bone whose name starts with `prefix` into `collection`.

    `prefix` can be a single string or a tuple of strings -- str.startswith
    accepts both, so "MCH_ or ORG_" is just ("MCH_", "ORG_"). EDIT mode.
    """
    names = [eb.name for eb in armature.edit_bones if eb.name.startswith(prefix)]
    return move_bones_to_collection(armature, names, collection)


def move_bones_with_suffix(armature, suffix, collection):
    """Move every edit bone whose name ends with `suffix` into `collection`.

    `suffix` can be a single string or a tuple of strings -- str.endswith
    accepts both, so ".L or .R" is just (".L", ".R"). EDIT mode.
    """
    names = [eb.name for eb in armature.edit_bones if eb.name.endswith(suffix)]
    return move_bones_to_collection(armature, names, collection)
