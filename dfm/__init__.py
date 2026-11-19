import bpy

from . import operators, properties, ui

if "bpy" in locals():
    import importlib

    importlib.reload(operators)

CLASSES = (
    properties.DFMProperties,
    operators.SPRUE_OT_AnalyzeMesh,
    operators.SPRUE_OT_ClearHeatmap,
    operators.SPRUE_OT_SelectNonManifold,
    ui.SPRUE_PT_DFM,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.dfm_properties = bpy.props.PointerProperty(
        type=properties.DFMProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "dfm_properties"):
        del bpy.types.Scene.dfm_properties

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
