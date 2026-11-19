import bpy

from . import operators, properties, ui

if "bpy" in locals():
    import importlib

    importlib.reload(operators)

CLASSES = (
    properties.PriorityBrushProperties,
    operators.SPRUE_OT_StartPriorityPaint,
    operators.SPRUE_OT_FinishPriorityPaint,
    operators.SPRUE_OT_ClearPriorityPaint,
    ui.VIEW3D_PT_PriorityBrush,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.prioritybrush_properties = bpy.props.PointerProperty(
        type=properties.PriorityBrushProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "prioritybrush_properties"):
        del bpy.types.Scene.prioritybrush_properties
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
