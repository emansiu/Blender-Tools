# Blender-Tools
wide array of Blender scripts and tools primarily focused on rigging and animation.

building for extensions:
blender --command extension build --source-dir src/Emanate_Tools --output-dir extensions

use new build to make index.json
blender --command extension server-generate --repo-dir=extensions

index.json lives at:
https://emansiu.github.io/Blender-Tools/extensions/index.json

assets live at:
https://emansiu.github.io/Blender-Tools/assets/

generate asset folders, jsons and meta:
blender -b --factory-startup --command asset_listing generate assets