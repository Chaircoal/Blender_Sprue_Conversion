import bpy
import bmesh
import math
import random
from mathutils import Vector

# Master call function for all manifold checks
def check_mesh_manifold(bm, obj):
    """
    Check the current mesh to ensure that it is manifold.
    This means that is ready and able to be 3D printed without problems
    """
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    open_edge_indices = get_open_edge_indices(bm)
    non_manifold_edge_indices = get_non_manifold_edge_indices(bm)
    non_manifold_vert_indices = get_non_manifold_vert_indices(bm)
    incontiguous_edge_indices = get_incontiguous_edge_indices(bm)
    zero_edge_indices = get_zero_edge_indices(bm)
    zero_face_indices = get_zero_face_indices(bm)
    overhang_face_indices = get_overhang_face_indices(bm)
    thin_wall_indices = get_thin_wall_indices(obj)
    nonplanar_face_indices = get_nonplanar_face_indices(bm)

    # if all are 0 then the model is watertight and manifold
    if (
        len(open_edge_indices) == 0
        and len(non_manifold_edge_indices) == 0
        and len(non_manifold_vert_indices) == 0
        and len(incontiguous_edge_indices) == 0
        and len(zero_edge_indices) == 0
        and len(zero_face_indices) == 0
        and len(overhang_face_indices) == 0
        and len(thin_wall_indices) == 0
        and len(nonplanar_face_indices) == 0
    ):
        print("RESULT: Mesh is Watertight (Manifold)!")
        is_watertight = True
    else:
        print("RESULT: Mesh is NOT Watertight.")
        is_watertight = False

    return dict(
        is_watertight = is_watertight,
        open_edge_indices = open_edge_indices,
        non_manifold_edge_indices = non_manifold_edge_indices,
        non_manifold_vert_indices = non_manifold_vert_indices,
        incontiguous_edge_indices = incontiguous_edge_indices,
        zero_edge_indices = zero_edge_indices,
        zero_face_indices = zero_face_indices,
        overhang_face_indices = overhang_face_indices,
        thin_wall_indices = thin_wall_indices,
        nonplanar_face_indices = nonplanar_face_indices
    )


# DFM and Manifold checks
def get_open_edge_indices(bm):
    """
    Get all open edges or holes that exist on the current mesh.
    """
    open_edge_indices = []

    # Loop through all edges to ensure that each one is not a hole
    for edge in bm.edges:
        if len(edge.link_faces) < 2:
            open_edge_indices.append(edge.index)

    return open_edge_indices


def get_non_manifold_edge_indices(bm):
    """
    Get all non-manifold edges that exist on the current mesh.
    """
    non_manifold_edge_indices = []

    for edge in bm.edges:
        if len(edge.link_faces) > 2:
            non_manifold_edge_indices.append(edge.index)

    return non_manifold_edge_indices


def get_non_manifold_vert_indices(bm):
    """
    Get all non-manifold vertices that exist on the current mesh.
    """
    non_manifold_vert_indices = []

    # Loop through all vertices to ensure that they are manifold
    for vert in bm.verts:
        if not vert.is_manifold:
            non_manifold_vert_indices.append(vert.index)

    return non_manifold_vert_indices


def get_incontiguous_edge_indices(bm):
    """
    Get all incontiguous edges that exist on the current mesh.
    aka edges that have exactly 2 linked faces but conflicting normal orientations
    """
    incontiguous_edge_indices = []

    for edge in bm.edges:
        if len(edge.link_faces) == 2 and not edge.is_contiguous:
            incontiguous_edge_indices.append(edge.index)

    return incontiguous_edge_indices


def get_zero_edge_indices(bm, threshold=0.00001):
    """
    Get all degenerate edges that exist on the current mesh.
    aka Edges where the distance between the two endpoints is virtually zero
    """
    zero_edge_indices = []

    for edge in bm.edges:
        if edge.calc_length() <= threshold:
            zero_edge_indices.append(edge.index)

    return zero_edge_indices


def get_zero_face_indices(bm, threshold=0.00001):
    """
    Get all zero area faces that exist on the current mesh.
    aka Faces that have collapsed into a single line or point.
    """
    zero_face_indices = []

    for face in bm.faces:
        if face.calc_area() <= threshold:
            zero_face_indices.append(face.index)

    return zero_face_indices


def get_overhang_face_indices(bm, angle_overhang=45):
    """
    Get all overhanging faces that exist on the current mesh.
    aka Faces that overhang further than a certain angle
    """
    overhang_face_indices = []
    z_down = Vector((0, 0, -1.0))
    z_angle_down = z_down.angle
    angle_overhang_rad = math.radians(angle_overhang)

    bm.normal_update()

    # 4.0 ignores zero area faces
    for face in bm.faces:
        if z_angle_down(face.normal, 4.0) < angle_overhang_rad:
            overhang_face_indices.append(face.index)

    return overhang_face_indices


def bmesh_copy_from_object(obj, transform=True, triangulate=True):
    """
    Returns a transformed, triangulated copy of the object's mesh
    """
    me = obj.data
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(me).copy()
    else:
        bm = bmesh.new()
        bm.from_mesh(me)

    if transform:
        mat = obj.matrix_world.copy()
        mat.translation.zero()
        if not mat.is_identity:
            bm.transform(mat)
            bm.normal_update()

    if triangulate:
        bmesh.ops.triangulate(bm, faces=bm.faces)

    return bm


def face_points_random(face, num_points=6, margin= 0.05):
    """
    Returns random points within a face
    """
    random.seed(face.index)
    uniform_args = 0.0 + margin, 1.0 - margin
    verts = [v.co for v in face.verts]

    for _ in range(num_points):
        u1 = random.uniform(*uniform_args)
        u2 = random.uniform(*uniform_args)
        if (u1 + u2) > 1.0:
            u1 = 1.0 - u1
            u2 = 1.0 - u2
        side1 = verts[1] - verts[0]
        side2 = verts[2] - verts[0]
        yield verts[0] + u1 * side1 + u2 * side2


def get_thin_wall_indices(obj, min_thickness_mm=1.5):
    """
    Get all too thin walls that exist on the current mesh
    https://docs.blender.org/api/current/mathutils.bvhtree.html
    """
    # get copy of bmesh
    bm = bmesh_copy_from_object(obj, transform=True, triangulate=False)
    bm.faces.ensure_lookup_table()

    # get the origin of opposite face for selecting later
    origin_index_of = {f: i for i, f in enumerate(bm.faces)}

    ret = bmesh.ops.triangulate(bm, faces=bm.faces)
    face_map = ret['face_map']
    bm.faces.ensure_lookup_table()

    context = bpy.context
    layer = context.view_layer
    scene_collection = context.layer_collection.collection

    #Create a copy of mesh for use in calculations (Ew! Optimize later!)
    mesh_temp = bpy.data.meshes.new(name="~thickness_check_tmp~")
    bm.to_mesh(mesh_temp)
    obj_temp = bpy.data.objects.new(name=mesh_temp.name, object_data=mesh_temp)
    scene_collection.objects.link(obj_temp)
    layer.update()

    ray_cast = obj_temp.ray_cast
    eps_bias = 0.0001

    thin_wall_orig_indices = set()
    bm_faces_new = bm.faces[:]

    for face in bm_faces_new:
        norm = face.normal
        norm_start = norm * eps_bias
        norm_end = norm * min_thickness_mm

        for point in face_points_random(face):
            point_a = point - norm_start
            point_b = point - norm_end
            point_dir = point_b - point_a

            hit_found, hit_location, hit_normal, index = ray_cast(point_a, point_dir, distance=point_dir.length)

            if hit_found:
                for f in (face, bm_faces_new[index]):
                    f_org = face_map.get(f, f)
                    thin_wall_orig_indices.add(origin_index_of[f_org])

    # Unlink/remove items to free memory
    bm.free()
    scene_collection.objects.unlink(obj_temp)
    bpy.data.objects.remove(obj_temp)
    bpy.data.meshes.remove(mesh_temp)
    layer.update()

    return list(thin_wall_orig_indices)


def find_islands(bm):
    """
    Find disconnected geometry islands via flood-fill.

    Returns a list of sets, each containing the face indices of one island.
    """
    bm.faces.ensure_lookup_table()
    visited = set()
    islands = []

    def flood(start_face):
        stack = [start_face]
        island = set()
        while stack:
            f = stack.pop()
            if f.index in visited:
                continue
            visited.add(f.index)
            island.add(f.index)
            for edge in f.edges:
                for linked in edge.link_faces:
                    if linked.index not in visited:
                        stack.append(linked)
        return island

    for face in bm.faces:
        if face.index not in visited:
            islands.append(flood(face))

    return islands


# Heat Map Helpers
def get_nonplanar_face_indices(bm, threshold=5):
    """
    Get all nonplanar faces that exist on the current mesh.
    aka non-flat faces or distorted faces (n-gons whose vertices do not lie on the exact same flat plane)
    """
    nonplanar_face_indices = []

    bm.normal_update()
    threshold_angle = math.radians(threshold)

    for face in bm.faces:
        norm = face.normal
        for loop in face.loops:
            loop_norm = loop.calc_normal()

            if loop_norm.dot(norm) < 0.0:
                loop_norm.negate()

            if (norm.angle(loop_norm, 1000.0) * 2.0) > threshold_angle:
                nonplanar_face_indices.append(face.index)
                break

    return nonplanar_face_indices


def apply_heatmap_vertex_colors(obj, curvatures):
    """
    Write per-face curvature into a vertex colour 
    attribute so it's visible in the viewport.
    """
    mesh = obj.data

    # Blender uses attributes for storing vertex colours
    color_layer_name = "SprueCurvature"
    if color_layer_name in mesh.attributes:
        mesh.attributes.remove(mesh.attributes[color_layer_name])

    mesh.attributes.new(
        name=color_layer_name,
        type='FLOAT_COLOR',
        domain='CORNER'
    )
    color_attr = mesh.attributes[color_layer_name]

    # Loop over polygons and their loops
    bm_tmp = bmesh.new()
    bm_tmp.from_mesh(mesh)
    bm_tmp.faces.ensure_lookup_table()

    loop_index = 0
    for poly in mesh.polygons:
        curv = curvatures[poly.index] if poly.index < len(curvatures) else 0.0
        color = curvature_to_color(curv)
        for li in poly.loop_indices:
            color_attr.data[li].color = color

    bm_tmp.free()

    # Tell Blender to display the colour attribute
    mesh.color_attributes.render_color_index = mesh.color_attributes.find(color_layer_name)
    mesh.color_attributes.active_color_index = mesh.color_attributes.find(color_layer_name)


def curvature_to_color(value):
    """
    Map a 0–1 curvature value to an RGB colour for the vertex colour layer.
    Low  (flat)    → green  (safe to cut)
    Mid            → yellow
    High (detailed)→ red    (avoid cutting)
    """
    r = min(1.0, value * 2.0)
    g = min(1.0, (1.0 - value) * 2.0)
    b = 0.1
    return (r, g, b, 1.0)