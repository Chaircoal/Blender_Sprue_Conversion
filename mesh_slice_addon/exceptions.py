class MeshSliceError(Exception):
    """Base exception for all slice generation errors."""
    pass

class TooFewVerticesSelected(MeshSliceError):
    def __init__(self, minimum: int = 2):
        super().__init__(
            f"Vertex selection too small. Please select at least {minimum} vertices."
        )

class TooManyVerticesSelected(MeshSliceError):
    def __init__(self, min_unselected: int = 4):
        super().__init__(
            f"Vertex selection too large. Please ensure at least {min_unselected} vertices are NOT selected."
        )