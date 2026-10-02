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
    operators.MESH_OT_PreprocessMesh,
    operators.VIEW3D_OT_DrawForeground,
    operators.MESH_OT_GenerateSliceBoundaries,
    operators.MESH_OT_SliceMesh,
    operators.OBJECT_OT_LayFlat,
    looptools_relax.MESH_OT_SliceLoopToolsRelax,
    ui.VIEW3D_PT_MeshSlice,
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