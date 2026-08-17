import fnmatch


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


def move_bones_matching(armature, pattern, collection):
    """Move every edit bone whose name matches `pattern` into `collection`.

    `pattern` uses shell-style wildcards (fnmatch): `*` matches any run of
    characters, `?` matches a single character. Prefix is "MCH_*", suffix is
    "*.L", and text anywhere in the middle is "*_IK_*". `pattern` can also be
    a tuple of patterns, matched as OR, so "MCH_ or ORG_" is
    ("MCH_*", "ORG_*"). Matching is case-sensitive. EDIT mode.
    """
    patterns = (pattern,) if isinstance(pattern, str) else tuple(pattern)
    names = [
        eb.name
        for eb in armature.edit_bones
        if any(fnmatch.fnmatchcase(eb.name, p) for p in patterns)
    ]
    return move_bones_to_collection(armature, names, collection)
