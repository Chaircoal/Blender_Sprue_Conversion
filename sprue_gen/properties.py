## Settings for sprue generation
## All lengths are in millimetres and are read by SPRUE_OT_BuildSprue.

from bpy.props import FloatProperty, IntProperty
from bpy.types import PropertyGroup


class SprueGenProperties(PropertyGroup):
    frame_padding: FloatProperty(
        name="Frame padding",
        description="Gap between the outermost piece and the inner edge of the runner frame (mm)",
        default=5.0,
        min=1.0,
        max=30.0,
        step=50,
    )
    frame_diameter: FloatProperty(
        name="Frame diameter",
        description="Diameter of the round bars that make up the runner frame (mm)",
        default=4.0,
        min=1.0,
        max=20.0,
        step=50,
    )
    gate_diameter: FloatProperty(
        name="Gate diameter",
        description="Diameter of the cylinder stub connecting each piece to the frame (mm)",
        default=1.0,
        min=0.5,
        max=10.0,
        step=50,
    )
    gate_length: FloatProperty(
        name="Gate length",
        description="How far a gate sticks out past the edge of its piece, in the gap between pieces (mm)",
        default=2.5,
        min=0.5,
        max=20.0,
        step=50,
    )
    piece_spacing: FloatProperty(
        name="Piece spacing",
        description="Gap between pieces in the grid layout (mm). Must stay larger than the runner width (3 mm)",
        default=5.0,
        min=4.0,
        max=30.0,
        step=50,
    )
    piece_wall_padding: FloatProperty(
        name="Piece wall padding",
        description="Gap between a piece and its own individual runner wall ring (Blender units)",
        default=0.15,
        min=0.02,
        max=2.0,
        step=1,
    )
    piece_wall_width: FloatProperty(
        name="Piece wall width",
        description="Width (thickness in XY) of each piece's individual runner wall ring",
        default=0.15,
        min=0.02,
        max=1.0,
        step=1,
    )
    piece_wall_height: FloatProperty(
        name="Piece wall height",
        description="Height (Z thickness) of each piece's individual runner wall ring",
        default=0.15,
        min=0.02,
        max=1.0,
        step=1,
    )
    gate_priority_min_weight: FloatProperty(
        name="Gate priority threshold",
        description="Minimum painted weight for a vertex to count as a preferred gate location",
        default=0.05,
        min=0.0,
        max=1.0,
        step=1,
    )
    max_gates_per_piece: IntProperty(
        name="Max gates per piece",
        description="Cap on how many separate painted gate regions can become gates on a single piece",
        default=4,
        min=1,
        max=12,
    )
    gate_volume_step: FloatProperty(
        name="Gate volume step",
        description="part volume (mm^3) needed for each extra gate",
        default=1000.0,
        min=200.0,
        max=2000.0,
        step=100.0,
    )
