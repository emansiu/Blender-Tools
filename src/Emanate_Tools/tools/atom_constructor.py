"""Build atoms from real element data.

Type an element symbol and Generate Atom makes a sphere sized by that
element's atomic radius, pulled from PubChem's periodic table. Radii come in
picometres and are divided by ATOM_RADIUS_SCALE, so hydrogen (120 pm) is a
1.2 m sphere -- a comfortable size in Blender units.
"""

import json
import urllib.request

import bpy

from ..helpers import naming_unity as naming

NAMES = naming.register_tool(
    "atom_constructor",
    label="Atom Constructor",
    owner=__name__,
    description="Generate atoms from PubChem element data",
    # Explicit, not auto: auto orders follow import order, and this module
    # imports first alphabetically. 1000 keeps it at the bottom of the stack.
    order=1000,
)

NAMES_GENERATE_ATOM = naming.register_tool(
    "generate_atom",
    label="Generate Atom",
    owner=__name__,
    description=(
        "Create a sphere sized by the element's atomic radius (PubChem), named after "
        "the element, with its own material"
    ),
)

ATOM_SYMBOL_PROP = naming.prop_name("atom_symbol")

PERIODIC_TABLE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/periodictable/JSON"
ATOM_RADIUS_SCALE = 100.0   # picometres -> Blender units

# Column names in PubChem's table. Looked up by name rather than position
# (Name is index 2, AtomicRadius index 7 today) so a reordering on their side
# can't silently swap fields.
COL_SYMBOL = "Symbol"
COL_NAME = "Name"
COL_RADIUS = "AtomicRadius"

_periodic_table = None   # {symbol lower: {column: value}}, fetched once per session


def fetch_periodic_table():
    """{lowercase symbol: {column name: value string}} from PubChem, cached."""
    global _periodic_table
    if _periodic_table is not None:
        return _periodic_table
    with urllib.request.urlopen(PERIODIC_TABLE_URL, timeout=15) as response:
        table = json.load(response)["Table"]
    columns = table["Columns"]["Column"]
    elements = {}
    for row in table["Row"]:
        element = dict(zip(columns, row["Cell"]))
        elements[element[COL_SYMBOL].lower()] = element
    _periodic_table = elements
    return elements


class EMANATE_OT_generate_atom(bpy.types.Operator):
    bl_idname = NAMES_GENERATE_ATOM.operator_idname
    bl_label = NAMES_GENERATE_ATOM.label
    bl_description = NAMES_GENERATE_ATOM.description
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context.scene, ATOM_SYMBOL_PROP, "").strip())

    def execute(self, context):
        symbol = getattr(context.scene, ATOM_SYMBOL_PROP).strip()

        # Extensions must not touch the network unless the user allowed it.
        if not bpy.app.online_access:
            self.report(
                {"WARNING"},
                "Generate Atom: turn on Allow Online Access (Preferences > System > Network) first",
            )
            return {"CANCELLED"}

        try:
            elements = fetch_periodic_table()
        except Exception as exc:  # noqa: BLE001 -- any network/parse failure is reported, not raised
            self.report({"WARNING"}, f"Generate Atom: couldn't reach PubChem ({type(exc).__name__}: {exc})")
            return {"CANCELLED"}

        element = elements.get(symbol.lower())
        if element is None:
            self.report({"WARNING"}, f"Generate Atom: {symbol!r} is not an element symbol")
            return {"CANCELLED"}

        name = element[COL_NAME]
        try:
            radius_pm = float(element[COL_RADIUS])
        except (KeyError, ValueError):
            self.report({"WARNING"}, f"Generate Atom: PubChem has no atomic radius for {name}")
            return {"CANCELLED"}
        radius = radius_pm / ATOM_RADIUS_SCALE

        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=32, ring_count=16, radius=radius, location=context.scene.cursor.location,
        )
        atom = context.object
        atom.name = name
        atom.data.name = name
        for polygon in atom.data.polygons:
            polygon.use_smooth = True

        # One material per element, shared by every atom of it -- a repeat
        # generate reuses it rather than piling up Hydrogen_Material.001s.
        material_name = f"{name}_Material"
        material = bpy.data.materials.get(material_name)
        reused = material is not None
        if material is None:
            material = bpy.data.materials.new(material_name)
        atom.data.materials.append(material)

        self.report(
            {"INFO"},
            f"{atom.name}: radius {radius_pm:g} pm -> {radius:g} m, "
            f"{'reused' if reused else 'new'} material {material.name}",
        )
        return {"FINISHED"}


class EMANATE_PT_atom_constructor(bpy.types.Panel):
    bl_idname = NAMES.panel_idname
    bl_label = NAMES.label
    bl_parent_id = naming.ROOT_PANEL_IDNAME
    bl_space_type = naming.SPACE_TYPE
    bl_region_type = naming.REGION_TYPE
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = NAMES.order

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, ATOM_SYMBOL_PROP)
        layout.operator(NAMES_GENERATE_ATOM.operator_idname, icon="MESH_UVSPHERE")


_classes = (
    EMANATE_OT_generate_atom,
    EMANATE_PT_atom_constructor,
)


def register():
    naming.check_classes((EMANATE_OT_generate_atom,), NAMES_GENERATE_ATOM)
    naming.check_classes((EMANATE_PT_atom_constructor,), NAMES)
    for cls in _classes:
        bpy.utils.register_class(cls)
    setattr(
        bpy.types.Scene,
        ATOM_SYMBOL_PROP,
        bpy.props.StringProperty(
            name="Element",
            description="Element symbol, e.g. H, He, C (case doesn't matter)",
            maxlen=3,
        ),
    )


def unregister():
    delattr(bpy.types.Scene, ATOM_SYMBOL_PROP)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
