## Settings for gate priority painting

from bpy.props import IntProperty
from bpy.types import PropertyGroup


class PriorityBrushProperties(PropertyGroup):
    last_priority_painted: IntProperty(
        default=0,
        description="Number of vertices with a painted priority weight > 0, updated when painting finishes",
    )
