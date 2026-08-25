## Settings for the Addon
## contains settings for the UI, Sprue creation and slicing

from bpy.types import PropertyGroup
from bpy.props import IntProperty, FloatProperty, BoolProperty

class MeshSlicerProperties(PropertyGroup):
    mesh_slicer_settings: BoolProperty(
        name="Mesh Slicer settings expanded",
        default=False,
    )
    # num_samples: IntProperty(
    #     name="GMM Samples",
    #     default=1000,
    #     min=10,
    #     max=5000,
    #     description="Number of background samples for GMM fitting",
    # )

    lambda_weight: IntProperty(
        name="Lambda weight",
        default=100,
        min=10,
        max=1000,
        step=5,
        description="Turn this up if slice generation is creating more than 2 slices.",
    )


