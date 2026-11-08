class MeshSegmentError(Exception):
    """Base exception for all mesh segmentation errors."""


class TooFewVerticesSelected(MeshSegmentError):
    def __init__(self, min_selected: int = 2):
        super().__init__(
            f"Vertex selection too small. Please select at least {min_selected} vertices."
        )


class TooManyVerticesSelected(MeshSegmentError):
    def __init__(self, min_unselected: int = 4):
        super().__init__(
            f"Vertex selection too large. Please ensure at least {min_unselected} vertices are NOT selected."
        )


class MeshNotTriangulated(MeshSegmentError):
    def __init__(self):
        super().__init__(
            "All polygons must be triangles. Please use the Triangulate modifier."
        )


class InvalidSDFValues(MeshSegmentError):
    def __init__(self):
        super().__init__(
            "SDF values are invalid. Please ensure the mesh is manifold and that all normals are facing outwards."
        )
