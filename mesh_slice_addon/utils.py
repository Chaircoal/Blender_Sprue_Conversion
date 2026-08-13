## Utility functions used throughout the addon

import bpy
import bmesh
import numpy as np
import pymeshlab
import maxflow
from sklearn.mixture import GaussianMixture
from . import exceptions

def get_sdf(obj):
    obj = bpy.context.active_object
    mesh = obj.data

    num_verts = len(mesh.vertices)
    num_faces = len(mesh.polygons)

    coords_flat = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords_flat)
    vert_coords = coords_flat.reshape(num_verts, 3)
    
    verts_per_face = mesh.polygons[0].loop_total
    faces_flat = np.empty(num_faces * verts_per_face, dtype=np.int32)
    mesh.polygons.foreach_get("vertices", faces_flat)
    face_vertices = faces_flat.reshape(num_faces, verts_per_face)
    
    m = pymeshlab.Mesh(vert_coords, face_vertices)
    ms = pymeshlab.MeshSet()
    ms.add_mesh(m, "sdf_mesh")

    # i spent days trying to write this on my own and it just existed
    # and it runs so much faster... 
    ms.compute_scalar_by_shape_diameter_function_per_vertex(rays=30, cone_amplitude=60)
    
    m = ms.current_mesh()
    sdf_values = m.vertex_scalar_array()

    return sdf_values.tolist()
    
def get_vertex_labels(
        obj,
        mesh,
        fg_indices,
        gmm_bg,
        gmm_fg,
        lambda_weight=10,
        epsilon = 1e-6,
        beta = .05,
        K = 1e12 
    )-> np.array:
    """
    Labels vertices of a mesh as either foreground (1) or background (0).
    Based on the work from Fan et al., 
    """
    sdf_array = np.array(obj['_sdf']).reshape(-1, 1)
    num_verts = len(sdf_array)
    num_edges = len(mesh.edges)
    
    g = maxflow.Graph[float]()  # Used to minimize energy function
    nodes = g.add_nodes(num_verts)

    # --------------------------------------------------
    # 1. DATA TERM: Penalty for assigning label to a vertex
    # --------------------------------------------------
    p_bg = np.exp(gmm_bg.score_samples(sdf_array))
    L_b_v = -np.log(p_bg + epsilon)
    
    p_fg = np.exp(gmm_fg.score_samples(sdf_array))
    L_f_v = -np.log(p_fg + epsilon) 
    
    fg_indices = set(fg_indices) if fg_indices is not None else set() # TODO: handle this...

    for i in range(num_verts):
        if i in fg_indices:
            g.add_tedge(nodes[i], K, 0.0)   # K "sufficiently large" to penalize fg seed verts labeled as bg
        else: 
            g.add_tedge(nodes[i], L_b_v[i], L_f_v[i])

    # --------------------------------------------------
    # 2. SMOOTH TERM: Penalty for different labels to adjacent vertices
    # --------------------------------------------------
    v_coords = np.zeros(num_verts * 3, dtype=np.float64)
    v_normals = np.zeros(num_verts * 3, dtype=np.float64)
    
    mesh.vertices.foreach_get("co", v_coords)
    mesh.vertices.foreach_get("normal", v_normals)
    
    v_coords = v_coords.reshape(-1, 3)
    v_normals = v_normals.reshape(-1, 3)

    # - Calculate geodesic distance across entire mesh
    edge_verts = np.zeros(num_edges * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", edge_verts)
    edge_verts = edge_verts.reshape(-1, 2)

    v_idx = edge_verts[:, 0]
    u_idx = edge_verts[:, 1]

    p1 = v_coords[v_idx]
    p2 = v_coords[u_idx]

    edge_lengths = np.linalg.norm(p1 - p2, axis=1)

    e_min = np.min(edge_lengths)
    e_max = np.max(edge_lengths)
    e_range = (e_max - e_min) if (e_max - e_min) > 0 else 1e-8

    g_vu = (edge_lengths - e_min) / e_range     # geodesic distance

    # - Calculate normal variation across entire mesh
    n_v = v_normals[v_idx]
    n_u = v_normals[u_idx]
    
    dot_products = np.sum(n_v * n_u, axis=1)
    dot_products = np.clip(dot_products, -1.0, 1.0)

    n_vu = (1.0 - dot_products) / 2.0   # normal variation 

    # - Calculate final smoothness term
    combined_metric = (1.0 - beta) * n_vu + beta * g_vu
    es_weight = -np.log(combined_metric + epsilon)
    capacities = lambda_weight * es_weight

    # - Populate the graph
    for i in range(num_edges):
        v = v_idx[i]
        u = u_idx[i]
        cap = float(capacities[i])
        g.add_edge(nodes[v], nodes[u], cap, cap)

    # Get labels
    g.maxflow()
    labels = np.array([1 if g.get_segment(nodes[v]) == 0 else 0 for v in range(num_verts)], dtype=np.int32)

    return labels

def compute_mesh_boundaries(obj):
    mesh = obj.data
    num_verts = len(mesh.vertices)

    fg_indices, bg_indices = get_vertex_indices(mesh, num_verts)

    # Number of samples for each GMM must be >= number of componenets
    if len(fg_indices) < 2:   # fg GMM has 2 components
        raise exceptions.TooFewVerticesSelected(minimum=2)

    if len(bg_indices) < 4:   # bg GMM has 4 components
        raise exceptions.TooManyVerticesSelected(min_unselected=4)

    sdf_array = np.asarray(obj["_sdf"])

    num_bg_samples = min(1000, len(bg_indices))
    bg_sample_indices = np.random.choice(bg_indices, size=num_bg_samples, replace=False)

    # Get SDF values for samples and reshape to column vector (necessary for GMM)
    fg_samples = np.reshape(sdf_array[fg_indices], (-1, 1)) 
    bg_samples = np.reshape(sdf_array[bg_sample_indices], (-1, 1)) 

    gmm_fg: GaussianMixture = GaussianMixture(n_components=2, random_state=0)
    gmm_fg.fit(fg_samples)

    gmm_bg = GaussianMixture(n_components=4, random_state=0)
    gmm_bg.fit(bg_samples)


    vertex_labels = get_vertex_labels(obj, mesh, fg_indices, gmm_bg, gmm_fg)

    # Assign materials to foreground & background
    mat_fg = get_or_create_material("Foreground_Mat", (1.0, 0.2, 0.2, 1.0))
    mat_bg = get_or_create_material("Background_Mat", (0.2, 0.4, 1.0, 1.0))

    assign_materials(obj, mesh, vertex_labels, mat_fg, mat_bg)

    mesh.update()

def get_vertex_indices(mesh, num_verts):
    select_array = np.empty(num_verts, dtype=bool)
    mesh.vertices.foreach_get('select', select_array)
    
    fg_indices = np.flatnonzero(select_array)
    bg_indices = np.flatnonzero(~select_array)
    
    return fg_indices, bg_indices

def get_or_create_material(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        mat.diffuse_color = color
        nodes = mat.node_tree.nodes
        principled = nodes.get("Principled BSDF")
        if principled:
            principled.inputs['Base Color'].default_value = color
    return mat

# TODO: name this so it's more clear that it exists for ONE PURPOSE (my [Kaitlyn's] purpose)
# also may be changed in future so that multiple segments always have different colours :]
def assign_materials(obj, mesh, vertex_labels, mat_fg, mat_bg):
    if len(obj.material_slots) < 1:
        obj.data.materials.append(mat_bg)
    else:
        obj.material_slots[0].material = mat_bg

    if len(obj.material_slots) < 2:
        obj.data.materials.append(mat_fg)
    else:
        obj.material_slots[1].material = mat_fg

    for poly in mesh.polygons:
        fg_count = sum(1 for v_idx in poly.vertices if vertex_labels[v_idx] == 1)
        poly.material_index = 1 if fg_count > 0 else 0