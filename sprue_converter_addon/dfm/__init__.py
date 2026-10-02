import bpy

from . import operators

if "bpy" in locals():
    import importlib
    importlib.reload(operators)

CLASSES = (
    operators.SPRUE_OT_AnalyzeMesh,
    operators.SPRUE_OT_ClearHeatmap,
    operators.SPRUE_OT_SelectNonManifold
)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()