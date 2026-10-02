import bpy, bmesh
import numpy as np
from pymeshlab import Mesh, MeshSet
from maxflow import Graph
from mathutils import Matrix
from sklearn.mixture import GaussianMixture
from sklearn.decomposition import PCA
from . import exceptions

from ..mesh_utils import (
    get_v_coords,
    get_face_verts,
    get_edge_verts,
    get_selected_vertices
)

NUM_BG_SAMPLES = 1000
EPSILON = 1e-6  # prevent math shenanigans like doing log(0)
K = 1e12  # "sufficiently large" constant to prevent seed verts from being labelled bg

def get_sdf(mesh: bpy.types.Mesh) -> list:
    """
    Returns the Shape Diameter Function (SDF) of a mesh's vertices using PyMeshLab.
    
    The SDF measures the neighbourhood diameter of an object at a given point (vertices here).

    References:
    Shapira, L., Shamir, A. & Cohen-Or, D. Consistent mesh partitioning and skeletonisation using the shape diameter function. Visual Comput 24, 249–259 (2008). https://doi.org/10.1007/s00371-007-0197-5
    """
    mesh.calc_loop_triangles()
    if len(mesh.polygons) != len(mesh.loop_triangles):
        raise exceptions.MeshNotTriangulated()

    v_coords = get_v_coords(mesh)
    face_verts = get_face_verts(mesh)

    m = Mesh(v_coords, face_verts)
    ms = MeshSet()
    ms.add_mesh(m, "sdf_mesh")

    ms.compute_scalar_by_shape_diameter_function_per_vertex(rays=30, cone_amplitude=60)
    
    m = ms.current_mesh()
    sdf_values = m.vertex_scalar_array()

    valid = np.isfinite(sdf_values)
    if not np.all(valid):
        raise exceptions.InvalidSDFValues()

    return sdf_values.tolist()

def get_vertex_labels(
        mesh: bpy.types.Mesh, 
        sdf_array: np.ndarray, 
        lambda_weight: int, 
        beta: float) -> np.ndarray:
    """
    Labels vertices of a mesh as either foreground (1) or background (0)

    
    References:

    """
    if len(mesh.polygons) != len(mesh.loop_triangles):
        raise exceptions.MeshNotTriangulated()

    selected = get_selected_vertices(mesh)

    fg_indices = np.flatnonzero(selected)
    bg_indices = np.flatnonzero(~selected)

    # Number of samples for each GMM must be >= number of componenets
    if len(fg_indices) < 2:   # fg GMM has 2 components
        raise exceptions.TooFewVerticesSelected(min_selected=2)

    if len(bg_indices) < 4:   # bg GMM has 4 components
        raise exceptions.TooManyVerticesSelected(min_unselected=4)

    num_bg_samples = min(NUM_BG_SAMPLES, len(bg_indices)) 
    bg_sample_indices = np.random.choice(bg_indices, size=num_bg_samples, replace=False)

    # Get SDF values for samples and reshape to column vector (necessary for GMM)
    fg_samples = np.reshape(sdf_array[fg_indices], (-1, 1)) 
    bg_samples = np.reshape(sdf_array[bg_sample_indices], shape=(-1, 1)) 

    gmm_fg: GaussianMixture = GaussianMixture(n_components=2, random_state=0)
    gmm_fg.fit(fg_samples)

    gmm_bg = GaussianMixture(n_components=4, random_state=0)
    gmm_bg.fit(bg_samples)

    sdf_array = np.reshape(sdf_array, shape=(-1, 1))

    vertex_labels = _energy_minimization(
        mesh, 
        sdf_array, 
        fg_indices, 
        gmm_bg, 
        gmm_fg, 
        lambda_weight=lambda_weight,
        beta=beta
    )
    return vertex_labels

def _calculate_data_term(gmm_bg, samples, gmm_fg, fg_indices):
    L_b_v = -gmm_bg.score_samples(samples)
    L_f_v = -gmm_fg.score_samples(samples)
    
    if fg_indices.size > 0:
        L_b_v[fg_indices] = K
        L_f_v[fg_indices] = 0.0
    
    return L_b_v, L_f_v

def _calculate_smoothness_term(mesh, num_edges, num_verts, beta, lambda_weight):
    """
    """
    v_coords = get_v_coords(mesh)
    
    # Calculate geodesic distance
    edge_verts =  get_edge_verts(num_edges, mesh)
    
    v_idx = edge_verts[:, 0]
    u_idx = edge_verts[:, 1]
    
    edge_lengths = np.linalg.norm(v_coords[v_idx] - v_coords[u_idx], axis=1)
    e_min, e_max = np.min(edge_lengths), np.max(edge_lengths)
    g_vu = (edge_lengths - e_min) / ((e_max - e_min) if (e_max - e_min) > 0 else 1e-8)  # geodesic distance
    
    # Calculate normal variation
    v_normals = np.zeros(num_verts * 3, dtype=np.float64)
    mesh.vertices.foreach_get("normal", v_normals)
    v_normals = v_normals.reshape(-1, 3)
    
    dot_products = np.clip(np.sum(v_normals[v_idx] * v_normals[u_idx], axis=1), -1.0, 1.0)
    n_vu = (1.0 - dot_products) / 2.0   # normal variation
    
    # Calculate smoothness term
    smooth = (1.0 - beta) * n_vu + beta * g_vu
    weighted_smooth = (lambda_weight * -np.log(smooth + EPSILON)).astype(float)

    return v_idx, u_idx, weighted_smooth

def _energy_minimization(
        mesh: bpy.types.Mesh,
        samples: np.ndarray,
        fg_indices: np.ndarray,
        gmm_bg: GaussianMixture,
        gmm_fg: GaussianMixture,
        lambda_weight: int = 100,
        beta = .05
    )-> np.ndarray:
    """
    
    """
    num_verts = len(samples)
    num_edges = len(mesh.edges)
    
    g = Graph[float]() 
    nodes = g.add_nodes(num_verts)

    # Penalty for assigning label to a vertex
    L_b_v, L_f_v = _calculate_data_term(gmm_bg, samples, gmm_fg, fg_indices)
    g.add_grid_tedges(nodes, L_b_v, L_f_v)

    # Penalty for assigning different labels to adjacent vertices
    v_idx, u_idx, weighted_smooth = _calculate_smoothness_term(mesh, num_edges, num_verts, beta, lambda_weight)

    # Populate the graph
    add_edge = g.add_edge
    for i in range(num_edges):
        add_edge(v_idx[i], u_idx[i], weighted_smooth[i], weighted_smooth[i])


    g.maxflow()
    labels = g.get_grid_segments(nodes).astype(bool)

    return labels

def get_or_create_material(name, color):
    mat: bpy.types.Material = bpy.data.materials.get(name)

    if mat is None:
        mat: bpy.types.Material = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        mat.diffuse_color = color
        nodes = mat.node_tree.nodes
        principled = nodes.get("Principled BSDF")
        if principled:
            principled.inputs["Base Color"].default_value = color
    
    return mat

def assign_slice_materials(mesh: bpy.types.Mesh, vertex_labels, mat_fg, mat_bg):
    """Assigns foreground material to a face if all its vertices are labeled foreground."""
    # add materials to object if not present
    fg_idx = mesh.materials.find(mat_fg.name)
    bg_idx = mesh.materials.find(mat_bg.name)
    
    if fg_idx == -1:
        fg_idx = len(mesh.materials)
        mesh.materials.append(mat_fg)
    
    if bg_idx == -1:
        bg_idx = len(mesh.materials)
        mesh.materials.append(mat_bg)

    # assign to face verts
    face_verts = get_face_verts(mesh)
    face_labels: np.ndarray = vertex_labels[face_verts]

    is_fg = face_labels.all(axis=1)

    material_indices = np.where(is_fg, bg_idx, fg_idx).astype(np.int32)
    mesh.polygons.foreach_set("material_index", material_indices)
    mesh.update()

def fill_mesh(mesh: bpy.types.Mesh, use_beauty:bool = False) :
    bm: bmesh.types.BMesh = bmesh.new()

    bm.from_mesh(mesh)

    boundary_edges: list[bmesh.types.BMEdge] = [e for e in bm.edges if len(e.link_faces) == 1]
    if boundary_edges:
        bmesh.ops.triangle_fill(bm, edges=boundary_edges, use_beauty=use_beauty, use_dissolve=False)
        bm.to_mesh(mesh)

    bm.free()
    
    mesh.update()

def align_object_along_xy(obj, mesh):
    v_coords= get_v_coords(mesh)

    pca = PCA(n_components=3)
    pca.fit(v_coords)
    
    # Components array rows: [0]=Widest (X), [1]=Middle (Y), [2]=Thinnest (Z)
    R_np = pca.components_

    # Prevent reflection
    if np.linalg.det(R_np) < 0:
        R_np[2, :] *= -1.0

    R_mat = Matrix(R_np.tolist())

    # rotate object
    if obj.rotation_mode == "QUATERNION":
        obj.rotation_quaternion = R_mat.to_quaternion()
    else:
        obj.rotation_euler = R_mat.to_euler(obj.rotation_mode)

    obj.select_set(True)
    mesh.update()

