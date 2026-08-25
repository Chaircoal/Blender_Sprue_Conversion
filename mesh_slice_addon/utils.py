## Utility functions used throughout the addon

import bpy
import numpy as np
import pymeshlab
import maxflow
from mathutils import Matrix
from sklearn.mixture import GaussianMixture
from sklearn.decomposition import PCA
from . import exceptions

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

def get_sdf(obj):
    mesh = obj.data

    v_coords = get_v_coords(mesh)
    face_verts = get_face_verts(mesh)

    m = pymeshlab.Mesh(v_coords, face_verts)
    ms = pymeshlab.MeshSet()
    ms.add_mesh(m, "sdf_mesh")

    ms.compute_scalar_by_shape_diameter_function_per_vertex(rays=30, cone_amplitude=60)
    
    m = ms.current_mesh()
    sdf_values = m.vertex_scalar_array()

    return sdf_values.tolist()
    

def get_vertex_labels(
        mesh,
        sdf_array,
        fg_indices,
        gmm_bg,
        gmm_fg,
        lambda_weight=100,
        epsilon = 1e-6,
        beta = .05,
        K = 1e12 
    )-> np.ndarray:
    """
    Labels vertices of a mesh as either foreground (1) or background (0).
    Based on the work from Fan et al., 
    """
    num_verts = len(sdf_array)
    num_edges = len(mesh.edges)
    
    g = maxflow.Graph[float]()  # Used to minimize energy function
    nodes = g.add_nodes(num_verts)

    # --------------------------------------------------
    # 1. DATA TERM: Penalty for assigning label to a vertex
    # --------------------------------------------------
    L_b_v = -gmm_bg.score_samples(sdf_array)
    L_f_v = -gmm_fg.score_samples(sdf_array)
    
    if fg_indices is not None and len(fg_indices) > 0:
        fg_mask = np.array(list(fg_indices), dtype=np.int32)
        L_b_v[fg_mask] = K
        L_f_v[fg_mask] = 0.0
    
    g.add_grid_tedges(nodes, L_b_v, L_f_v)

    # --------------------------------------------------
    # 2. SMOOTH TERM: Penalty for different labels to adjacent vertices
    # --------------------------------------------------
    v_coords = get_v_coords(mesh)

    # - Calculate geodesic distance
    edge_verts =  get_edge_verts(num_edges, mesh)

    v_idx = edge_verts[:, 0]
    u_idx = edge_verts[:, 1]

    edge_lengths = np.linalg.norm(v_coords[v_idx] - v_coords[u_idx], axis=1)
    e_min, e_max = np.min(edge_lengths), np.max(edge_lengths)
    g_vu = (edge_lengths - e_min) / ((e_max - e_min) if (e_max - e_min) > 0 else 1e-8)  # geodesic distance

    # - Calculate normal variation
    v_normals = np.zeros(num_verts * 3, dtype=np.float64)
    mesh.vertices.foreach_get("normal", v_normals)
    v_normals = v_normals.reshape(-1, 3)

    dot_products = np.clip(np.sum(v_normals[v_idx] * v_normals[u_idx], axis=1), -1.0, 1.0)
    n_vu = (1.0 - dot_products) / 2.0   # normal variation

    # - Calculate final smoothness term
    combined_metric = (1.0 - beta) * n_vu + beta * g_vu
    capacities = (lambda_weight * -np.log(combined_metric + epsilon)).astype(float)

    # - Populate the graph
    add_edge = g.add_edge
    for i in range(num_edges):
        add_edge(v_idx[i], u_idx[i], capacities[i], capacities[i])

    # Get labels
    g.maxflow()
    labels = g.get_grid_segments(nodes).astype(bool)

    return labels

def compute_mesh_boundaries(obj, props):
    mesh = obj.data
    num_verts = len(mesh.vertices)

    fg_indices, bg_indices = get_fg_bg_indices(mesh)

    # Number of samples for each GMM must be >= number of componenets
    if len(fg_indices) < 2:   # fg GMM has 2 components
        raise exceptions.TooFewVerticesSelected(minimum=2)

    if len(bg_indices) < 4:   # bg GMM has 4 components
        raise exceptions.TooManyVerticesSelected(min_unselected=4)

    sdf_array = np.asarray(obj["_sdf"])

    num_bg_samples = min(1000, len(bg_indices)) # paper says 1000 samples works good so we default to that
    bg_sample_indices = np.random.choice(bg_indices, size=num_bg_samples, replace=False)

    # Get SDF values for samples and reshape to column vector (necessary for GMM)
    fg_samples = np.reshape(sdf_array[fg_indices], (-1, 1)) 
    bg_samples = np.reshape(sdf_array[bg_sample_indices], (-1, 1)) 

    gmm_fg: GaussianMixture = GaussianMixture(n_components=2, random_state=0)
    gmm_fg.fit(fg_samples)

    gmm_bg = GaussianMixture(n_components=4, random_state=0)
    gmm_bg.fit(bg_samples)

    sdf_array = np.reshape(sdf_array, shape=(-1, 1))

    vertex_labels = get_vertex_labels(
        mesh, 
        sdf_array, 
        fg_indices, 
        gmm_bg, 
        gmm_fg, 
        lambda_weight=props.lambda_weight
    )

    mat_fg = get_or_create_material("Foreground_Mat", (1.0, 0.2, 0.2, 1.0))
    mat_bg = get_or_create_material("Background_Mat", (0.2, 0.4, 1.0, 1.0))

    assign_slice_materials(obj, mesh, vertex_labels, mat_fg, mat_bg)

    mesh.update()

def get_fg_bg_indices(mesh):
    select_array = np.empty(len(mesh.vertices), dtype=bool)
    mesh.vertices.foreach_get('select', select_array)
    
    fg_indices = np.flatnonzero(select_array)
    bg_indices = np.flatnonzero(~select_array)
    
    return fg_indices, bg_indices

def get_or_create_material(name, color):
    mat: bpy.types.Material | None = bpy.data.materials.get(name)
    if mat is None:
        mat: bpy.types.Material = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        mat.diffuse_color = color
        nodes = mat.node_tree.nodes
        principled = nodes.get("Principled BSDF")
        if principled:
            principled.inputs['Base Color'].default_value = color
    return mat

def assign_slice_materials(obj, mesh: bpy.types.Mesh, vertex_labels, mat_fg, mat_bg):
    """Assigns foreground material to a face if all its vertices are labeled foreground."""
    if len(obj.material_slots) < 1: obj.data.materials.append(mat_bg)
    else: obj.material_slots[0].material = mat_bg

    if len(obj.material_slots) < 2: obj.data.materials.append(mat_fg)
    else: obj.material_slots[1].material = mat_fg

    for poly in mesh.polygons:
        fg_count = sum(1 for v_idx in poly.vertices if vertex_labels[v_idx] == 1)
        poly.material_index = 1 if fg_count > 0 else 0


def align_object_along_xy(obj, mesh):
    mesh = obj.data
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
    if obj.rotation_mode == 'QUATERNION':
        obj.rotation_quaternion = R_mat.to_quaternion()
    else:
        obj.rotation_euler = R_mat.to_euler(obj.rotation_mode)

    obj.select_set(True)
    mesh.update()


def loops_from_boundary_edges(boundary_edges):
    loops = []
    visited = set()
    vert_to_edges = {}
    for e in boundary_edges:
        for v in e.verts:
            vert_to_edges.setdefault(v, []).append(e)

    for e in boundary_edges:
        if e in visited:
            continue
        loop = [e]
        visited.add(e)
        current = e
        while True:
            next_edge = None
            for v in current.verts:
                for cand in vert_to_edges.get(v, []):
                    if cand not in visited and cand is not current:
                        next_edge = cand
                        break
                if next_edge:
                    break
            if not next_edge:
                break
            loop.append(next_edge)
            visited.add(next_edge)
            current = next_edge
        loops.append(loop)
    return loops