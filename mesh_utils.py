## Utility functions used throughout the addon

import math

import bmesh
import bpy
import numpy as np


def get_bmesh(obj):
    """Return a BMesh from the object (in edit or object mode)."""
    if obj.mode == "EDIT":
        return bmesh.from_edit_mesh(obj.data)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


def bmesh_to_object(name, bm):
    """
    Uses bmesh to create a new mesh object.
    """
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def merge_objects(
    target_obj: bpy.types.Object,
    objs_to_merge: list[bpy.types.Object],
    solver: str = "EXACT",
):
    """
    Applies boolean union modifier to target_obj and objs_to_merge, merging them.
    Does not make a copy of target_obj.

    Solver can be: "FLOAT", "EXACT", or "MANIFOLD"

    Returns target_obj.
    """
    if solver not in ["FLOAT", "EXACT", "MANIFOLD"]:
        raise ValueError("Solver must be 'FLOAT', 'EXACT', or 'MANIFOLD'")

    if not objs_to_merge:
        return target_obj

    # Add a Boolean Union modifier for each object in the list
    added_mods = []
    for i, obj in enumerate(objs_to_merge):
        if obj == target_obj:
            continue
        mod = target_obj.modifiers.new(name=f"BoolUnion_{i}", type="BOOLEAN")
        mod.operation = "UNION"
        mod.solver = solver
        mod.object = obj
        added_mods.append(mod)

    # Apply modifiers to get the combined mesh
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = target_obj.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(eval_obj)

    # Swap mesh data
    old_mesh = target_obj.data
    target_obj.data = new_mesh
    bpy.data.meshes.remove(old_mesh)

    # Remove the Boolean modifiers added
    for mod in added_mods:
        target_obj.modifiers.remove(mod)

    return target_obj


def get_v_coords(mesh):
    """Returns the vertex coordinates of a mesh as an ndarray with shape (num_verts, 3)."""
    num_verts = len(mesh.vertices)
    coords_flat = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords_flat)
    v_coords = coords_flat.reshape(num_verts, 3)
    return v_coords


def get_face_verts(mesh):
    """Returns the face vertex indices of a triangular mesh as an ndarray with shape (num_faces, 3)."""
    num_faces = len(mesh.loop_triangles)
    faces_flat = np.empty(num_faces * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", faces_flat)
    return faces_flat.reshape(num_faces, 3)


def get_edge_verts(num_edges, mesh):
    """Returns the edge vertex indices of a mesh as an ndarray with shape (num_edges, 2)."""
    edge_verts = np.zeros(num_edges * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", edge_verts)
    return edge_verts.reshape(-1, 2)


def get_selected_vertices(mesh):
    """Returns a boolean ndarray of selected vertices of a mesh."""
    selected = np.empty(len(mesh.vertices), dtype=bool)
    mesh.vertices.foreach_get("select", selected)
    return selected


def compute_face_curvature(bm):
    """
    Estimate per-face curvature as the average angular deviation
    between a face normal and its neighbours' normals.

    Returns a list of floats (one per face, same order as bm.faces),
    where 0.0 = perfectly flat and 1.0 = very high curvature.
    """
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    curvatures = []
    for face in bm.faces:
        neighbour_angles = []
        for edge in face.edges:
            for linked_face in edge.link_faces:
                if linked_face.index != face.index:
                    dot = face.normal.dot(linked_face.normal)
                    # clamp for numerical safety
                    dot = max(-1.0, min(1.0, dot))

                    angle = math.acos(dot) / math.pi  # normalise 0–1
                    neighbour_angles.append(angle)

        curvatures.append(
            sum(neighbour_angles) / len(neighbour_angles) if neighbour_angles else 0.0
        )

    # Normalise to 0–1 range
    if curvatures:
        mn, mx = min(curvatures), max(curvatures)
        if mx > mn:
            curvatures = [(c - mn) / (mx - mn) for c in curvatures]

    return curvatures
