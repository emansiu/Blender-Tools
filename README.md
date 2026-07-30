# Blender-Tools
wide array of Blender scripts and tools primarily focused on rigging and animation.

building for extensions:
blender --command extension build --source-dir src/Emanate_Tools --output-dir extensions

use new build to make index.json
blender --command extension server-generate --repo-dir=extensions
