## Settings for the Addon
## contains settings for the UI, Sprue creation and slicing

from bpy.types import PropertyGroup
from bpy.props import IntProperty, FloatProperty, BoolProperty

class MeshSliceProperties(PropertyGroup):
    meshslice_settings: BoolProperty(
        name="Mesh Slicer settings expanded",
        default=False,
    )
    lambda_weight: IntProperty(
        name="Lambda Weight",
        default=100,
        min=1,
        max=500,
        step=5,
        description="Sensitivity of the slicing algorithm",
    )
    beta: FloatProperty(
        name="Beta",
        default=0.05,
        min=0.01,
        max=1,
        description="beta..",
    )


