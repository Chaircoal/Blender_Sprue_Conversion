## This is the main file that blender runs
## contains the methods to register and unregister the other classes and files

# Description for users before downloading the addon

bl_info = {
    "name": "Sprue Tool",
    "author": "Cole Latrace",
    "version": (0, 1, 1),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Sprue Tool",
    "description": "Convert resin 3D models to injection-mold sprue layout. Suggests cut planes, lays out pieces, and builds a runner frame with gates.",
    "category": "Mesh",
}

# Handles reloading within Blender
# Enables the use of the "Reload Scripts" button
from . import (
    dfm,
    mesh_segment,
    mesh_utils,
    operators,
    priority_brush,
    properties,
    sprue_gen,
    ui,
)

if "bpy" in locals():
    import importlib

    importlib.reload(mesh_utils)
    importlib.reload(operators)
    importlib.reload(properties)

    importlib.reload(mesh_segment)
    importlib.reload(dfm)
    importlib.reload(priority_brush)
    importlib.reload(sprue_gen)
    importlib.reload(ui)

import bpy

#  REGISTRATION
CLASSES = [
    properties.SprueToolSettings,
    operators.SPRUE_OT_ClearAll,
    ui.SPRUE_PT_MainPanel,
    ui.SPRUE_PT_AnalysisPanel,
    ui.SPRUE_PT_BuildFramePanel,
]

MODULES = [mesh_segment, dfm, priority_brush, sprue_gen]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sprue_settings = bpy.props.PointerProperty(
        type=properties.SprueToolSettings
    )

    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.sprue_settings


if __name__ == "__main__":
    register()
