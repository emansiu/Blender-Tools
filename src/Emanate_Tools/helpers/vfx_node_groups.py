"""Compositor node groups used by render_tools' Add VFX button.

Transcribed one to one from the hand-built "Vignette" and "Rounded Square
Mask" groups in Teaching_File.blend (Ice Nucleation presentation), so the
button reproduces that look exactly. Build them with ensure_vignette_group();
it reuses the groups if the file already has them, so tweaks made to them by
hand survive a re-run.

Table format, per group:
  *_INTERFACE  (in_out, name, socket_type, panel name or None, {attr: value})
  *_NODES      (name, bl_idname, location, {property: value}, {input identifier: default})
  *_LINKS      (from node, from socket, to node, to socket)

Sockets on Group Input / Group Output / group nodes are named by their
interface *name* (a fresh group hands out new Socket_N identifiers); every
other socket is named by its identifier, which is stable per node type.
"""

import bpy

ROUNDED_SQUARE_MASK_GROUP = "Emanate_Rounded_Square_Mask"
VIGNETTE_GROUP = "Emanate_Vignette"

# Group node -> which of our groups it points at (keys are the names the
# tables use, which are the original names in Teaching_File.blend).
_GROUP_ALIASES = {"Rounded Square Mask": ROUNDED_SQUARE_MASK_GROUP}
_NAMED_SOCKET_NODES = {"NodeGroupInput", "NodeGroupOutput", "CompositorNodeGroup"}

ROUNDED_SQUARE_MASK_INTERFACE = (
    ('OUTPUT', 'Mask', 'NodeSocketFloat', None, {'default_value': 0.0}),
    ('INPUT', 'Image', 'NodeSocketColor', None, {'default_value': (0.8, 0.8, 0.8, 1.0), 'hide_value': True}),
    ('INPUT', 'Scale', 'NodeSocketVector', None, {'dimensions': 2, 'default_value': (1.0, 1.0), 'min_value': -10000.0, 'max_value': 10000.0}),
    ('INPUT', 'Corner Roundness', 'NodeSocketFloat', None, {'default_value': 0.0, 'min_value': 0.0, 'max_value': 1.0, 'subtype': 'FACTOR'}),
    ('INPUT', 'Feather', 'NodeSocketFloat', None, {'default_value': 0.0, 'min_value': 0.0, 'max_value': 1.0, 'subtype': 'FACTOR'}),
    ('INPUT', 'Offset', 'NodeSocketVector', None, {'dimensions': 2, 'default_value': (0.0, 0.0), 'subtype': 'XYZ'}),
    ('INPUT', 'Angle', 'NodeSocketFloat', None, {'default_value': 0.0, 'subtype': 'ANGLE'}),
)
ROUNDED_SQUARE_MASK_NODES = (
    # (name, bl_idname, location, properties, unlinked input defaults by identifier)
    ('Group Output', 'NodeGroupOutput', (2028.4, 231.5), {}, {}),
    ('Group Input', 'NodeGroupInput', (-2359.2, 0.1), {}, {}),
    ('Image Coordinates', 'CompositorNodeImageCoordinates', (-1505.1, 176.1), {}, {}),
    ('Vector Math.001', 'ShaderNodeVectorMath', (-74.2, 42.5), {'operation': 'ABSOLUTE'}, {}),
    ('Vector Math.002', 'ShaderNodeVectorMath', (384.1, -61.9), {'operation': 'SUBTRACT'}, {}),
    ('Vector Math.003', 'ShaderNodeVectorMath', (570.3, -120.4), {'operation': 'ADD'}, {}),
    ('Separate XYZ.001', 'ShaderNodeSeparateXYZ', (752.2, -146.9), {}, {}),
    ('Math.005', 'ShaderNodeMath', (969.8, -74.2), {'operation': 'MAXIMUM', 'use_clamp': False}, {}),
    ('Math.006', 'ShaderNodeMath', (1181.5, -89.3), {'operation': 'MINIMUM', 'use_clamp': False}, {'Value_001': 0.0}),
    ('Vector Math.004', 'ShaderNodeVectorMath', (755.1, -305.8), {'operation': 'MAXIMUM'}, {'Vector_001': (0.0, 0.0, 0.0)}),
    ('Vector Math.005', 'ShaderNodeVectorMath', (946.8, -268.2), {'operation': 'LENGTH'}, {}),
    ('Math.007', 'ShaderNodeMath', (1168.2, -378.2), {'operation': 'SUBTRACT', 'use_clamp': False}, {}),
    ('Math.008', 'ShaderNodeMath', (1403.2, -139.5), {'operation': 'ADD', 'use_clamp': False}, {}),
    ('Map Range.001', 'ShaderNodeMapRange', (1742.3, 253.5), {'clamp': True, 'interpolation_type': 'SMOOTHSTEP', 'data_type': 'FLOAT'}, {'To Min': 1.0, 'To Max': 0.0}),
    ('Map Range.002', 'ShaderNodeMapRange', (1257.0, 394.8), {'clamp': True, 'interpolation_type': 'LINEAR', 'data_type': 'FLOAT'}, {'From Min': 1.0, 'From Max': 0.0, 'To Min': -0.5, 'To Max': 0.0}),
    ('Map Range.003', 'ShaderNodeMapRange', (1259.9, 152.9), {'clamp': True, 'interpolation_type': 'LINEAR', 'data_type': 'FLOAT'}, {'From Min': 1.0, 'To Min': 1.0, 'To Max': 0.0}),
    ('Reroute', 'NodeReroute', (1096.2, 182.8), {'socket_idname': 'NodeSocketFloat'}, {}),
    ('Reroute.002', 'NodeReroute', (-25.2, 162.1), {'socket_idname': 'NodeSocketFloatFactor'}, {}),
    ('Math', 'ShaderNodeMath', (378.7, 261.9), {'operation': 'ADD', 'use_clamp': False}, {'Value_001': 0.0001}),
    ('Vector Rotate', 'ShaderNodeVectorRotate', (-340.3, 114.9), {'rotation_type': 'Z_AXIS', 'invert': False}, {'Center': (0.0, 0.0, 0.0)}),
    ('Vector Math', 'ShaderNodeVectorMath', (-674.1, 284.7), {'operation': 'SUBTRACT'}, {}),
    ('Vector Math.010', 'ShaderNodeVectorMath', (304.7, -221.7), {'operation': 'SCALE'}, {'Vector': (1.0, 1.0, 0.0)}),
    ('Separate XYZ', 'ShaderNodeSeparateXYZ', (-852.5, -549.6), {}, {}),
    ('Math.003', 'ShaderNodeMath', (-669.2, -532.1), {'operation': 'MINIMUM', 'use_clamp': False}, {}),
    ('Clamp', 'ShaderNodeClamp', (-406.6, -461.6), {'clamp_type': 'MINMAX'}, {'Min': 0.0}),
    ('Reroute.001', 'NodeReroute', (-729.3, -395.0), {'socket_idname': 'NodeSocketFloatFactor'}, {}),
    ('Switch', 'GeometryNodeSwitch', (-152.8, -347.4), {'input_type': 'RGBA'}, {'Switch': True}),
    ('Math.001', 'ShaderNodeMath', (736.1, 163.5), {'operation': 'MULTIPLY', 'use_clamp': False}, {'Value_001': 0.5}),
    ('Image Info', 'CompositorNodeImageInfo', (-2326.4, -285.1), {}, {}),
    ('Separate XYZ.002', 'ShaderNodeSeparateXYZ', (-2168.2, -250.5), {}, {}),
    ('Reroute.003', 'NodeReroute', (-1169.6, -69.6), {'socket_idname': 'NodeSocketVector'}, {}),
    ('Vector Math.006', 'ShaderNodeVectorMath', (-1363.0, -2.0), {'operation': 'MULTIPLY'}, {}),
    ('Combine XYZ', 'ShaderNodeCombineXYZ', (-1612.3, -170.4), {}, {'X': 1.0, 'Z': 0.0}),
    ('Math.002', 'ShaderNodeMath', (-1943.7, -157.6), {'operation': 'DIVIDE', 'use_clamp': False}, {'Value': 1.0}),
    ('Math.004', 'ShaderNodeMath', (-1948.0, -322.7), {'operation': 'DIVIDE', 'use_clamp': False}, {'Value': 1.0}),
    ('Math.009', 'ShaderNodeMath', (-1778.7, -214.4), {'operation': 'MULTIPLY', 'use_clamp': False}, {}),
    ('Math.010', 'ShaderNodeMath', (-1781.3, -396.7), {'operation': 'MULTIPLY', 'use_clamp': False}, {}),
    ('Combine XYZ.001', 'ShaderNodeCombineXYZ', (-1612.3, -312.2), {}, {'Y': 1.0, 'Z': 0.0}),
    ('Switch.001', 'GeometryNodeSwitch', (-1421.0, -188.2), {'input_type': 'RGBA'}, {}),
    ('Math.011', 'ShaderNodeMath', (-1810.8, 14.8), {'operation': 'GREATER_THAN', 'use_clamp': False}, {}),
)
ROUNDED_SQUARE_MASK_LINKS = (
    ('Reroute', 'Output', 'Map Range.003', 'Value'),
    ('Map Range.002', 'Result', 'Map Range.001', 'From Min'),
    ('Math.006', 'Value', 'Math.008', 'Value'),
    ('Reroute', 'Output', 'Map Range.002', 'Value'),
    ('Math.008', 'Value', 'Map Range.001', 'Value'),
    ('Math.005', 'Value', 'Math.006', 'Value'),
    ('Vector Math.003', 'Vector', 'Separate XYZ.001', 'Vector'),
    ('Vector Math.003', 'Vector', 'Vector Math.004', 'Vector'),
    ('Math.007', 'Value', 'Math.008', 'Value_001'),
    ('Map Range.003', 'Result', 'Map Range.001', 'From Max'),
    ('Vector Math.001', 'Vector', 'Vector Math.002', 'Vector'),
    ('Separate XYZ.001', 'X', 'Math.005', 'Value'),
    ('Vector Math.005', 'Value', 'Math.007', 'Value'),
    ('Vector Math.002', 'Vector', 'Vector Math.003', 'Vector'),
    ('Separate XYZ.001', 'Y', 'Math.005', 'Value_001'),
    ('Vector Math.004', 'Vector', 'Vector Math.005', 'Vector'),
    ('Group Input', 'Image', 'Image Coordinates', 'Image'),
    ('Map Range.001', 'Result', 'Group Output', 'Mask'),
    ('Math', 'Value', 'Reroute', 'Input'),
    ('Group Input', 'Feather', 'Reroute.002', 'Input'),
    ('Reroute.002', 'Output', 'Math', 'Value'),
    ('Vector Rotate', 'Vector', 'Vector Math.001', 'Vector'),
    ('Vector Math', 'Vector', 'Vector Rotate', 'Vector'),
    ('Group Input', 'Angle', 'Vector Rotate', 'Angle'),
    ('Image Coordinates', 'Uniform', 'Vector Math', 'Vector'),
    ('Group Input', 'Offset', 'Vector Math', 'Vector_001'),
    ('Reroute.003', 'Output', 'Vector Math.002', 'Vector_001'),
    ('Vector Math.010', 'Vector', 'Vector Math.003', 'Vector_001'),
    ('Reroute.003', 'Output', 'Separate XYZ', 'Vector'),
    ('Separate XYZ', 'X', 'Math.003', 'Value'),
    ('Separate XYZ', 'Y', 'Math.003', 'Value_001'),
    ('Reroute.001', 'Output', 'Clamp', 'Value'),
    ('Math.003', 'Value', 'Clamp', 'Max'),
    ('Group Input', 'Corner Roundness', 'Reroute.001', 'Input'),
    ('Reroute.001', 'Output', 'Switch', 'False'),
    ('Clamp', 'Result', 'Switch', 'True'),
    ('Switch', 'Output', 'Vector Math.010', 'Scale'),
    ('Switch', 'Output', 'Math.007', 'Value_001'),
    ('Math.001', 'Value', 'Map Range.003', 'From Max'),
    ('Math', 'Value', 'Math.001', 'Value'),
    ('Group Input', 'Image', 'Image Info', 'Image'),
    ('Image Info', 'Dimensions', 'Separate XYZ.002', 'Vector'),
    ('Vector Math.006', 'Vector', 'Reroute.003', 'Input'),
    ('Group Input', 'Scale', 'Vector Math.006', 'Vector_001'),
    ('Separate XYZ.002', 'X', 'Math.002', 'Value_001'),
    ('Separate XYZ.002', 'Y', 'Math.004', 'Value_001'),
    ('Math.002', 'Value', 'Math.009', 'Value'),
    ('Separate XYZ.002', 'Y', 'Math.009', 'Value_001'),
    ('Math.004', 'Value', 'Math.010', 'Value'),
    ('Separate XYZ.002', 'X', 'Math.010', 'Value_001'),
    ('Math.009', 'Value', 'Combine XYZ', 'Y'),
    ('Math.010', 'Value', 'Combine XYZ.001', 'X'),
    ('Combine XYZ', 'Vector', 'Switch.001', 'False'),
    ('Combine XYZ.001', 'Vector', 'Switch.001', 'True'),
    ('Switch.001', 'Output', 'Vector Math.006', 'Vector'),
    ('Separate XYZ.002', 'Y', 'Math.011', 'Value'),
    ('Math.011', 'Value', 'Switch.001', 'Switch'),
    ('Separate XYZ.002', 'X', 'Math.011', 'Value_001'),
)

VIGNETTE_INTERFACE = (
    ('OUTPUT', 'Image', 'NodeSocketColor', None, {'default_value': (0.8, 0.8, 0.8, 1.0)}),
    ('OUTPUT', 'Mask', 'NodeSocketFloat', None, {'default_value': 0.0}),
    ('INPUT', 'Image', 'NodeSocketColor', None, {'default_value': (0.0, 0.0, 0.0, 1.0)}),
    ('INPUT', 'Factor', 'NodeSocketFloat', None, {'default_value': 1.0, 'min_value': 0.0, 'max_value': 1.0, 'subtype': 'FACTOR'}),
    ('INPUT', 'Feather', 'NodeSocketFloat', None, {'default_value': 0.4, 'min_value': 0.0, 'max_value': 1.0, 'subtype': 'FACTOR'}),
    ('INPUT', 'Corner Roundness', 'NodeSocketFloat', 'Transform', {'default_value': 1.0, 'min_value': 0.0, 'max_value': 1.0, 'subtype': 'FACTOR'}),
    ('INPUT', 'Scale', 'NodeSocketVector', 'Transform', {'dimensions': 2, 'default_value': (0.8, 0.8)}),
    ('INPUT', 'Offset', 'NodeSocketVector', 'Transform', {'dimensions': 2, 'default_value': (0.0, 0.0), 'subtype': 'XYZ'}),
    ('INPUT', 'Angle', 'NodeSocketFloat', 'Transform', {'default_value': 0.0, 'subtype': 'ANGLE'}),
)
VIGNETTE_NODES = (
    # (name, bl_idname, location, properties, unlinked input defaults by identifier)
    ('Group Output', 'NodeGroupOutput', (1189.8, 165.4), {}, {}),
    ('Group Input', 'NodeGroupInput', (-1025.9, 31.3), {}, {}),
    ('Group.004', 'CompositorNodeGroup', (-359.8, 44.2), {'node_tree': 'Rounded Square Mask'}, {}),
    ('Mix', 'ShaderNodeMix', (644.8, 109.5), {'data_type': 'RGBA', 'blend_type': 'MULTIPLY', 'clamp_factor': True, 'clamp_result': False, 'factor_mode': 'UNIFORM'}, {}),
    ('Reroute', 'NodeReroute', (-538.2, 16.9), {'socket_idname': 'NodeSocketColor'}, {}),
    ('Reroute.001', 'NodeReroute', (103.8, 182.7), {'socket_idname': 'NodeSocketColor'}, {}),
    ('Separate Color', 'CompositorNodeSeparateColor', (303.8, 332.0), {'mode': 'HSV'}, {}),
    ('Combine Color', 'CompositorNodeCombineColor', (959.9, 369.6), {'mode': 'HSV'}, {}),
    ('Math', 'ShaderNodeMath', (984.7, 159.4), {'operation': 'SUBTRACT', 'use_clamp': True}, {'Value': 1.0}),
)
VIGNETTE_LINKS = (
    ('Group Input', 'Corner Roundness', 'Group.004', 'Corner Roundness'),
    ('Group Input', 'Feather', 'Group.004', 'Feather'),
    ('Group Input', 'Angle', 'Group.004', 'Angle'),
    ('Group Input', 'Image', 'Reroute', 'Input'),
    ('Reroute', 'Output', 'Group.004', 'Image'),
    ('Reroute', 'Output', 'Reroute.001', 'Input'),
    ('Reroute.001', 'Output', 'Separate Color', 'Image'),
    ('Separate Color', 'Red', 'Combine Color', 'Red'),
    ('Separate Color', 'Green', 'Combine Color', 'Green'),
    ('Separate Color', 'Alpha', 'Combine Color', 'Alpha'),
    ('Separate Color', 'Blue', 'Mix', 'A_Color'),
    ('Mix', 'Result_Color', 'Combine Color', 'Blue'),
    ('Combine Color', 'Image', 'Group Output', 'Image'),
    ('Group Input', 'Offset', 'Group.004', 'Offset'),
    ('Math', 'Value', 'Group Output', 'Mask'),
    ('Group Input', 'Scale', 'Group.004', 'Scale'),
    ('Group.004', 'Mask', 'Mix', 'B_Color'),
    ('Group Input', 'Factor', 'Mix', 'Factor_Float'),
    ('Group.004', 'Mask', 'Math', 'Value_001'),
)



def _socket(node, key, outputs):
    sockets = node.outputs if outputs else node.inputs
    attr = "name" if node.bl_idname in _NAMED_SOCKET_NODES else "identifier"
    # Prefer an enabled match: several node types keep disabled sockets that
    # share a name/identifier pattern with the live one.
    matches = [s for s in sockets if getattr(s, attr) == key]
    for socket in matches:
        if socket.enabled:
            return socket
    if matches:
        return matches[0]
    raise KeyError(f"{node.name}: no {'output' if outputs else 'input'} socket {key!r}")


def _build_group(name, interface, nodes, links):
    tree = bpy.data.node_groups.new(name, "CompositorNodeTree")

    panels = {}
    for in_out, socket_name, socket_type, panel_name, attrs in interface:
        parent = None
        if panel_name is not None:
            parent = panels.get(panel_name)
            if parent is None:
                parent = panels[panel_name] = tree.interface.new_panel(panel_name)
        item = tree.interface.new_socket(socket_name, in_out=in_out, socket_type=socket_type, parent=parent)
        # dimensions first: it reshapes default_value (2D vs 3D vectors), and the
        # Python handle keeps the old shape, so look the item up again after.
        if "dimensions" in attrs and hasattr(item, "dimensions"):
            identifier = item.identifier
            item.dimensions = attrs["dimensions"]
            item = next(i for i in tree.interface.items_tree
                        if i.item_type == "SOCKET" and i.identifier == identifier)
        for attr, value in attrs.items():
            if attr != "dimensions" and hasattr(item, attr):
                setattr(item, attr, value)

    built = {}
    for node_name, bl_idname, location, props, inputs in nodes:
        node = tree.nodes.new(bl_idname)
        node.name = node_name
        node.location = location
        for attr, value in props.items():
            if attr == "node_tree":
                value = _ensure(_GROUP_ALIASES.get(value, value))
            if hasattr(node, attr):
                setattr(node, attr, value)
        for identifier, value in inputs.items():
            _socket(node, identifier, outputs=False).default_value = value
        built[node_name] = node

    for from_node, from_socket, to_node, to_socket in links:
        tree.links.new(
            _socket(built[from_node], from_socket, outputs=True),
            _socket(built[to_node], to_socket, outputs=False),
        )
    return tree


_SPECS = {
    ROUNDED_SQUARE_MASK_GROUP: (ROUNDED_SQUARE_MASK_INTERFACE, ROUNDED_SQUARE_MASK_NODES, ROUNDED_SQUARE_MASK_LINKS),
    VIGNETTE_GROUP: (VIGNETTE_INTERFACE, VIGNETTE_NODES, VIGNETTE_LINKS),
}


def _ensure(name):
    tree = bpy.data.node_groups.get(name)
    if tree is not None and tree.bl_idname == "CompositorNodeTree":
        return tree
    return _build_group(name, *_SPECS[name])


def ensure_vignette_group():
    """The Emanate_Vignette compositor group (and the mask group it nests), built if missing."""
    return _ensure(VIGNETTE_GROUP)
