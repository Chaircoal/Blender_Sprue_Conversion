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

    show_dfm_report: BoolProperty(
        name="Show DFM report",
        description="Display the DFM report within the UI panel",
        default=False
    )

    # GATE PRIORITY PAINTING
    last_priority_painted: IntProperty(
        default=0,
        description="Number of vertices with a painted priority weight > 0, updated when painting finishes",
    )


    # SPRUE FRAME SETTINGS (NEEDS TWEAKING MOST LIKELY)
    # - All of these are in millimetres and are read by SPRUE_OT_BuildSprue.
    frame_padding: FloatProperty(
        name="Frame padding",
        description="Gap between the outermost piece and the inner edge of the runner frame (mm)",
        default=5.0, min=1.0, max=30.0, step=50,
    )
    frame_diameter: FloatProperty(
        name="Frame diameter",
        description="Diameter of the round bars that make up the runner frame (mm)",
        default=4.0, min=1.0, max=20.0, step=50,
    )
    gate_diameter: FloatProperty(
        name="Gate diameter",
        description="Diameter of the cylinder stub connecting each piece to the frame (mm)",
        default=1.0, min=0.5, max=10.0, step=50,
    )
    gate_length: FloatProperty(
        name="Gate length",
        description="How far a gate sticks out past the edge of its piece, in the gap between pieces (mm)",
        default=2.5, min=0.5, max=20.0, step=50,
    )
    piece_spacing: FloatProperty(
        name="Piece spacing",
        description="Gap between pieces in the grid layout (mm). Must stay larger than the runner width (3 mm)",
        default=5.0, min=4.0, max=30.0, step=50,
    )
    piece_wall_padding: FloatProperty(
        name="Piece wall padding",
        description="Gap between a piece and its own individual runner wall ring (Blender units)",
        default=0.15, min=0.02, max=2.0, step=1,
    )
    piece_wall_width: FloatProperty(
        name="Piece wall width",
        description="Width (thickness in XY) of each piece's individual runner wall ring",
        default=0.15, min=0.02, max=1.0, step=1,
    )
    piece_wall_height: FloatProperty(
        name="Piece wall height",
        description="Height (Z thickness) of each piece's individual runner wall ring",
        default=0.15, min=0.02, max=1.0, step=1,
    )
    gate_priority_min_weight: FloatProperty(
        name="Gate priority threshold",
        description="Minimum painted weight for a vertex to count as a preferred gate location",
        default=0.05, min=0.0, max=1.0, step=1,
    )
    max_gates_per_piece: IntProperty(
        name="Max gates per piece",
        description="Cap on how many separate painted gate regions can become gates on a single piece",
        default=4, min=1, max=12,
    )
    gate_volume_step: FloatProperty(
        name="Gate volume step",
        description="part volume (mm^3) needed for each extra gate",
        default=1000.0, min=200.0, max=2000.0, step=100.0,
    )

    # Model manifold settings
    is_watertight: BoolProperty(
        name="Watertight",
        description="Indicates whether the mesh is closed and fully manifold",
        default=False,
    )
    open_edge_count: IntProperty(
        name="Open Edges",
        description="Number of boundary/hole edges present on the mesh",
        default=0, min=0
    )
    non_manifold_edge_count: IntProperty(
        name="Non-Manifold Edges",
        description="Number of edges connected to more than two faces",
        default=0, min=0
    )
    non_manifold_vert_count: IntProperty(
        name="Non-Manifold Vertices",
        description="Number of non-manifold vertices present on the mesh",
        default=0, min=0
    )
    incontiguous_edge_count: IntProperty(
        name="Incontiguous Edges",
        description="Number of incontiguous edges present on the mesh",
        default=0, min=0
    )
    zero_edge_count: IntProperty(
        name="Zero Distance Edges",
        description="Number of edges where the distance between the two endpoints is virtually zero",
        default=0, min=0
    )
    zero_face_count: IntProperty(
        name="Zero Face Areas",
        description="Number of zero faces areas present on the mesh",
        default=0, min=0
    )
    overhang_face_count: IntProperty(
        name="Overhanging Faces",
        description="Number of overhanging faces present on the mesh",
        default=0, min=0
    )
    thin_wall_count: IntProperty(
        name="Thin Walls",
        description="Number of thin walls present on the mesh",
        default=0, min=0
    )
    nonplanar_face_count: IntProperty(
        name="Non-planar Faces",
        description="Number of non-planar faces present on the mesh",
        default=0, min=0
    )
