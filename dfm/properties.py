## Settings for the DFM (design for manufacturing) analysis
## contains the UI state and the results of the last mesh analysis

from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import PropertyGroup


class DFMProperties(PropertyGroup):
    curvature_threshold: FloatProperty(
        name="Detail threshold",
        description="Curvature value above which faces are considered 'high detail' (avoid cutting)",
        default=0.25,
        min=0.0,
        max=1.0,
        step=1,
    )
    num_candidates: IntProperty(
        name="Max slice planes",
        description="How many candidate cut planes to suggest",
        default=6,
        min=1,
        max=20,
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
        default=False,
    )

    # Model manifold results
    is_watertight: BoolProperty(
        name="Watertight",
        description="Indicates whether the mesh is closed and fully manifold",
        default=False,
    )
    open_edge_count: IntProperty(
        name="Open Edges",
        description="Number of boundary/hole edges present on the mesh",
        default=0,
        min=0,
    )
    non_manifold_edge_count: IntProperty(
        name="Non-Manifold Edges",
        description="Number of edges connected to more than two faces",
        default=0,
        min=0,
    )
    non_manifold_vert_count: IntProperty(
        name="Non-Manifold Vertices",
        description="Number of non-manifold vertices present on the mesh",
        default=0,
        min=0,
    )
    incontiguous_edge_count: IntProperty(
        name="Incontiguous Edges",
        description="Number of incontiguous edges present on the mesh",
        default=0,
        min=0,
    )
    zero_edge_count: IntProperty(
        name="Zero Distance Edges",
        description="Number of edges where the distance between the two endpoints is virtually zero",
        default=0,
        min=0,
    )
    zero_face_count: IntProperty(
        name="Zero Face Areas",
        description="Number of zero faces areas present on the mesh",
        default=0,
        min=0,
    )
    overhang_face_count: IntProperty(
        name="Overhanging Faces",
        description="Number of overhanging faces present on the mesh",
        default=0,
        min=0,
    )
    thin_wall_count: IntProperty(
        name="Thin Walls",
        description="Number of thin walls present on the mesh",
        default=0,
        min=0,
    )
    nonplanar_face_count: IntProperty(
        name="Non-planar Faces",
        description="Number of non-planar faces present on the mesh",
        default=0,
        min=0,
    )
