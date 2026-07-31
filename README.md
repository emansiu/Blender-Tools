# Blender-Tools

**A wide array of Blender scripts and tools primarily focused on rigging and animation.**

<p>
  <img alt="Blender" src="https://img.shields.io/badge/Blender-4.2%2B-orange?logo=blender&logoColor=white">
  <img alt="Type" src="https://img.shields.io/badge/type-extension-blue">
  <img alt="License" src="https://img.shields.io/badge/license-GPL--3.0--or--later-green">
</p>

---

## 🚀 Quick Reference

### Build the extension

```bash
blender --command extension build --source-dir src/Emanate_Tools --output-dir extensions
```

### Generate `index.json` from the new build

```bash
blender --command extension server-generate --repo-dir=extensions
```

### Generate asset folders, JSONs and meta

```bash
blender -b --factory-startup --command asset_listing generate assets
```

---

## 🌐 Hosted Endpoints

| What | Where |
| --- | --- |
| Extension repo index | <https://emansiu.github.io/Blender-Tools/extensions/index.json> |
| Asset library | <https://emansiu.github.io/Blender-Tools/assets/> |

> Add the `index.json` URL in Blender under **Preferences → Get Extensions → Repositories** to install and receive updates automatically.

---

## 📖 About This Project

**Blender-Tools** (shipped as the **Emanate Studios Tools** add-on) is a self-hosted Blender
extension repository. It bundles a growing set of rigging and animation utilities into a single
add-on, and pairs it with an online asset library — both served straight from GitHub Pages, so
Blender can install and update them without any manual `.zip` handling.

The project has two halves that are published independently:

| Half | Source | Published to |
| --- | --- | --- |
| **The add-on** — panels, operators, rigging tools | `src/Emanate_Tools/` | `extensions/` |
| **The asset library** — `.blend` assets + thumbnails | `assets/` | `assets/_v1/` |

### 🧰 What's in the toolkit

| Tool | Description |
| --- | --- |
| **Stretchy FK** | Builds a full stretchy FK chain from a selected root bone — duplicates the chain into FK and tweak layers, wires up `STRETCH_TO` constraints, and generates custom bone shape icons. |
| **UV Checker** | Reports which UDIM tiles the current selection occupies. |

All tools appear as collapsible sub-panels under a single **Emanate** tab in the 3D Viewport
sidebar (<kbd>N</kbd>).

---

## ⚙️ How It Works

### Auto-discovering tool modules

The add-on's root `__init__.py` registers one parent panel (`EMANATE_PT_root`) and then walks
the `tools/` package with `pkgutil.iter_modules`. Every module it finds is imported and its
`register()` is called.

```
src/Emanate_Tools/
├── __init__.py            # root panel + auto-loader
├── blender_manifest.toml  # extension metadata
├── naming_unity.py        # single source of truth for identifiers
└── tools/
    ├── __init__.py
    ├── Stretchy_FK.py
    └── uv_checker.py
```

**Adding a tool means dropping a file into `tools/`.** There is no central list to edit and no
import to wire up. Modules already in `sys.modules` are *reloaded* rather than re-imported, so
Blender's **Reload Scripts** works cleanly during development. Unregistration runs in reverse
order, so panels tear down before the operators they reference.

### `naming_unity.py` — one place for every name

Blender's identifier rules are strict and fail in unhelpful ways: an operator `bl_idname` with a
capital letter is a hard error, while a sub-panel whose `bl_space_type` disagrees with its parent
simply *never appears* and reports nothing at all.

So no module in this add-on types an identifier by hand. Each tool claims a key and gets every
name it needs back:

```python
NAMES = naming.register_tool(
    "uv_checker",
    label="UV Checker",
    owner=__name__,
    description="Report which UDIM tiles the selection uses",
)
```

From the key `uv_checker`, the registry derives:

| Derived value | Result |
| --- | --- |
| `NAMES.operator_idname` | `emanate.uv_checker` |
| `NAMES.operator_classname` | `EMANATE_OT_uv_checker` |
| `NAMES.panel_idname` | `EMANATE_PT_uv_checker` |
| `NAMES.order` | auto-assigned in steps of 10 |

The registry also guards against collisions — two different modules claiming the same key raises
immediately, while a module re-claiming *its own* key (the reload case) passes harmlessly. Since
Python can't compute a `class` statement's name, `check_classes()` runs at register time and
prints any mismatch between the literal class name and what the registry expected. `naming_unity.py`
itself carries a full write-up of Blender's naming rules and a copy-paste template for new tools.

### Panel structure

```
Emanate  (sidebar tab)
└── Emanate Tools            EMANATE_PT_root
    ├── Stretchy FK          bl_parent_id → EMANATE_PT_root
    └── UV Checker           bl_parent_id → EMANATE_PT_root
```

Every child panel points at `naming.ROOT_PANEL_IDNAME` and mirrors the root's `SPACE_TYPE` and
`REGION_TYPE`. `bl_category` is set on the root only — children inherit their location.

Panels draw conditionally: **Stretchy FK** checks that an armature is in Edit Mode with a bone
chain of more than one bone selected, and otherwise shows a hint instead of a dead button.

### Distribution

`blender_manifest.toml` declares the extension `id`, version and minimum Blender version. The
build command packages `src/Emanate_Tools/` into a versioned `.zip` under `extensions/`, and
`server-generate` scans that folder to produce the `index.json` that Blender polls for updates.

The asset library follows the same pattern: `asset_listing generate` scans `assets/` and writes
`_asset-library-meta.json` plus a paged, SHA256-hashed index under `assets/_v1/`, which Blender's
asset browser reads directly over HTTP.

> ⚠️ The extension `id` must match its containing folder name, and changing it after publishing
> orphans every existing install — Blender treats a new `id` as an entirely different extension.

---

## 📄 License

GPL-3.0-or-later — see [LICENSE](LICENSE).
