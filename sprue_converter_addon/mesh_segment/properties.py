## Settings for the Addon
## contains settings for the UI, Sprue creation and slicing

from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import PropertyGroup


class MeshSegmentProperties(PropertyGroup):
    meshsegment_settings: BoolProperty(
        name="Mesh Segment settings expanded",
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
