import bpy

from . import operators, properties, ui

if "bpy" in locals():
    import importlib

    importlib.reload(operators)

CLASSES = (
    properties.SprueGenProperties,
    operators.SPRUE_OT_BuildSprue,
    ui.SPRUE_PT_BuildFramePanel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.spruegen_properties = bpy.props.PointerProperty(
        type=properties.SprueGenProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "spruegen_properties"):
        del bpy.types.Scene.spruegen_properties

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
