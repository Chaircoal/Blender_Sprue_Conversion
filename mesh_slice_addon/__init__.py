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
from . import looptools_relax
from . import ui

if _needs_reload:
    import importlib
    exceptions = importlib.reload(exceptions)
    utils = importlib.reload(utils)
    properties = importlib.reload(properties)
    operators = importlib.reload(operators)
    looptools_relax = importlib.reload(looptools_relax)
    ui = importlib.reload(ui)


CLASSES = (
    properties.MeshSliceProperties,
    operators.MESH_OT_preprocess_mesh,
    operators.VIEW3D_OT_draw_foreground,
    operators.MESH_OT_generate_slice_boundaries,
    operators.MESH_OT_slice_mesh,
    operators.OBJECT_OT_lay_flat,
    looptools_relax.MESH_OT_slice_looptools_relax,
    ui.VIEW3D_PT_mesh_slice,
)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.mesh_slice_properties = bpy.props.PointerProperty(
        type=properties.MeshSliceProperties
    )

def unregister():
    if hasattr(bpy.types.Scene, "mesh_slice_properties"):
        del bpy.types.Scene.mesh_slice_properties

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()