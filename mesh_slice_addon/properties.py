## Settings for the Addon
## contains settings for the UI, Sprue creation and slicing

import bpy
from bpy.props import IntProperty

class MeshSlicingProperties(bpy.types.PropertyGroup):
    num_samples: IntProperty(
        name="GMM Samples",
        default=1000,
        min=10,
        max=5000,
        description="Number of background samples for GMM fitting",
    )
