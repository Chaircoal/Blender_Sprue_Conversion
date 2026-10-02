import bpy

from . import properties
from . import operators
from . import looptools_relax
from . import ui

if "bpy" in locals():
    import importlib

    importlib.reload(properties)
    importlib.reload(operators)
    importlib.reload(looptools_relax)
    importlib.reload(ui)
    

CLASSES = (
    properties.MeshSliceProperties,
    operators.MESH_OT_preprocess_mesh,
    operators.VIEW3D_OT_draw_foreground,
    operators.MESH_OT_generate_slice_boundaries,
    operators.MESH_OT_slice_mesh,
    operators.OBJECT_OT_lay_flat,
    looptools_relax.MESH_OT_slice_looptools_relax,
    ui.VIEW3D_PT_meshslice,
)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.meshslice_properties = bpy.props.PointerProperty(
        type=properties.MeshSliceProperties
    )

def unregister():
    if hasattr(bpy.types.Scene, "meshslice_properties"):
        del bpy.types.Scene.meshslice_properties

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()