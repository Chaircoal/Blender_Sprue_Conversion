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
        name="Sensitivity",
        default=100,
        min=1,
        max=500,
        step=5,
        description="Affects how sensitive the algorithm is to vertex selection.",
    )
    beta: FloatProperty(
        name="Edge Length Weight",
        default=0.05,
        min=0.01,
        max=1,
        description="Balance between surface curvature and edge length when placing the cut. "
        "Low values favour creases and sharp surface changes, "
        "high values favour shorter edges.",
    )
