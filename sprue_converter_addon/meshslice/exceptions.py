class MeshSliceError(Exception):
    """Base exception for all slice generation errors."""
    pass

class TooFewVerticesSelected(MeshSliceError):
    def __init__(self, min_selected: int = 2):
        super().__init__(
            f"Vertex selection too small. Please select at least {min_selected} vertices."
        )

class TooManyVerticesSelected(MeshSliceError):
    def __init__(self, min_unselected: int = 4):
        super().__init__(
            f"Vertex selection too large. Please ensure at least {min_unselected} vertices are NOT selected."
        )

class MeshNotTriangulated(MeshSliceError):
    def __init__(self):
        super().__init__(
            f"All polygons must be triangles. Please use the Triangulate modifier."
        )

class InvalidSDFValues(MeshSliceError):
    def __init__(self):
        super().__init__(
            f"SDF values are invalid. Please ensure the mesh is manifold and that all normals are facing outwards."
        )
