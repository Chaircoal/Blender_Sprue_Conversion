## Settings for the Addon
## contains settings for the UI, Sprue creation and slicing

import bpy
from bpy.props import (FloatProperty, BoolProperty, IntProperty)

#  Scene state (stored on the scene) -- UI settings and last analysis results
class SprueToolSettings(bpy.types.PropertyGroup):
    curvature_threshold: FloatProperty(
        name="Detail threshold",
        description="Curvature value above which faces are considered 'high detail' (avoid cutting)",
        default=0.25, min=0.0, max=1.0, step=1,
    )
    num_candidates: IntProperty(
        name="Max slice planes",
        description="How many candidate cut planes to suggest",
        default=6, min=1, max=20,
    )
    heatmap_visible: BoolProperty(
        name="Show heatmap",
        description="Display the curvature heatmap on the mesh",
        default=False,
    )
    last_island_count: IntProperty(default=0)
    last_candidate_count: IntProperty(default=0)


    # SPRUE FRAME SETTINGS (NEEDS TWEAKING MOST LIKELY)
    # - Can't get gates to orient properly yet, so this is a work in progress.
    frame_padding: FloatProperty(
        name="Frame padding",
        description="Gap between the outermost piece and the inner edge of the runner frame (Blender units)",
        default=0.5, min=0.1, max=5.0, step=1,
    )
    frame_width: FloatProperty(
        name="Runner width",
        description="Width (thickness in XY) of the rectangular runner frame bar (Blender units)",
        default=0.3, min=0.05, max=2.0, step=1,
    )
    frame_height: FloatProperty(
        name="Runner height",
        description="Height (Z thickness) of the runner frame bar (Blender units)",
        default=0.2, min=0.05, max=1.0, step=1,
    )
    gate_diameter: FloatProperty(
        name="Gate diameter",
        description="Diameter of the cylinder stub connecting each piece to the frame (Blender units)",
        default=0.12, min=0.02, max=0.5, step=1,
    )
    gate_length: FloatProperty(
        name="Gate length",
        description="Length of the gate stub from frame to piece surface (Blender units)",
        default=0.2, min=0.05, max=1.0, step=1,
    )
    piece_spacing: FloatProperty(
        name="Piece spacing",
        description="Minimum gap between pieces in the grid layout (Blender units)",
        default=0.4, min=0.1, max=3.0, step=1,
    )