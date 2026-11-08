import bpy

from . import looptools_relax, operators, properties, ui

if "bpy" in locals():
    import importlib

    importlib.reload(properties)
    importlib.reload(operators)
    importlib.reload(looptools_relax)
    importlib.reload(ui)


CLASSES = (
    properties.MeshSegmentProperties,
    operators.MESH_OT_PreprocessMesh,
    operators.VIEW3D_OT_DrawForeground,
    operators.MESH_OT_GenerateBoundaries,
    operators.MESH_OT_SegmentMesh,
    looptools_relax.MESH_OT_SegmentLoopToolsRelax,
    ui.VIEW3D_PT_MeshSegment,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.meshsegment_properties = bpy.props.PointerProperty(
        type=properties.MeshSegmentProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "meshsegment_properties"):
        del bpy.types.Scene.meshsegment_properties

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
