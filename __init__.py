## This is the main file that blender runs
## contains the methods to register and unregister the other classes and files

# Description for users before downloading the addon

# Handles reloading within Blender
# Enables the use of the "Reload Scripts" button
from . import (
    dfm,
    mesh_segment,
    mesh_utils,
    operators,
    priority_brush,
    sprue_gen,
    ui,
)

if "bpy" in locals():
    import importlib

    importlib.reload(mesh_utils)
    importlib.reload(operators)

    importlib.reload(mesh_segment)
    importlib.reload(dfm)
    importlib.reload(priority_brush)
    importlib.reload(sprue_gen)
    importlib.reload(ui)

import bpy

#  REGISTRATION
CLASSES = [
    operators.SPRUE_OT_ClearAll,
    ui.SPRUE_PT_Main,
]

MODULES = [mesh_segment, dfm, priority_brush, sprue_gen]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
