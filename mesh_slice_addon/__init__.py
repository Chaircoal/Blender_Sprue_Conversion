## This is the main file that blender runs
## contains the methods to register and unregister the other classes and files

# Description for users before downloading the addon
bl_info = {
    "name": "Mesh Slicer",
    "author": "Kaitlyn Humphrey",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Mesh Slicer",
    "description": "Slices meshes to prepare for use with Sprue Tool.",
    "category": "Mesh",
}

_needs_reload = "bpy" in locals()

import bpy
from . import exceptions
from . import utils
from . import properties
from . import operators
from . import ui

if _needs_reload:
    import importlib
    exceptions = importlib.reload(exceptions)
    utils = importlib.reload(utils)
    properties = importlib.reload(properties)
    operators = importlib.reload(operators)
    ui = importlib.reload(ui)


CLASSES = (
    properties.MeshSlicingProperties,
    operators.MESH_OT_get_sdf,
    operators.VIEW3D_OT_draw_foreground,
    operators.MESH_OT_generate_slice_boundaries,
    operators.MESH_OT_slice_mesh,
    ui.VIEW3D_PT_mesh_slicing,
)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.mesh_slice_settings = bpy.props.PointerProperty(
        type=properties.MeshSlicingProperties
    )

def unregister():
    if hasattr(bpy.types.Scene, "mesh_slice_settings"):
        del bpy.types.Scene.mesh_slice_settings

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()