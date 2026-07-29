## This is the main file that blender runs
## contains the methods to register and unregister the other classes and files

# Description for users before downloading the addon
bl_info = {
    "name": "Sprue Tool",
    "author": "Cole Latrace",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Sprue Tool",
    "description": "Convert resin 3D models to injection-mold sprue layout. Suggests cut planes, lays out pieces, and builds a runner frame with gates.",
    "category": "Mesh",
}

# Handles reloading within Blender
# Enables the use of the "Reload Scripts" button
if "bpy" in locals():
    import importlib
    from . import utils
    from . import properties
    from . import operators
    from . import ui
    importlib.reload(utils)
    importlib.reload(operators)
    importlib.reload(properties)
    importlib.reload(ui)
else:
    from . import utils
    from . import properties
    from . import operators
    from . import ui

import bpy

#  REGISTRATION
CLASSES = [
    properties.SprueToolSettings,
    operators.SPRUE_OT_AnalyzeMesh,
    operators.SPRUE_OT_FindSlicePlanes,
    operators.SPRUE_OT_AcceptPlane,
    operators.SPRUE_OT_ClearHeatmap,
    operators.SPRUE_OT_ClearAll,
    operators.SPRUE_OT_BuildSprueFrame,
    operators.SPRUE_OT_SelectNonManifold,
    ui.SPRUE_PT_MainPanel,
]

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sprue_settings = bpy.props.PointerProperty(type=properties.SprueToolSettings)

def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.sprue_settings

if __name__ == "__main__":
    register()
