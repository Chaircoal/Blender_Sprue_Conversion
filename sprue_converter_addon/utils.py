## Utility functions used throughout the addon
## Note: (""" Are documentation strings for Blender's auto-doc system, not comments """)

import math
import bpy
import bmesh
import random
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


#  Core geometry helpers
# returns the mesh of the selected object
def get_bmesh(obj):
    """Return a BMesh from the object (in edit or object mode)."""
    if obj.mode == 'EDIT':
        return bmesh.from_edit_mesh(obj.data)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


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
                    import math
                    angle = math.acos(dot) / math.pi  # normalise 0–1
                    neighbour_angles.append(angle)

        curvatures.append(
            sum(neighbour_angles) / len(neighbour_angles)
            if neighbour_angles else 0.0
        )

    # Normalise to 0–1 range
    if curvatures:
        mn, mx = min(curvatures), max(curvatures)
        if mx > mn:
            curvatures = [(c - mn) / (mx - mn) for c in curvatures]

    return curvatures


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


def find_slice_candidates(bm, curvatures, threshold=0.25, num_planes=6):
    """
    Propose axis-aligned slice planes that pass through low-curvature regions.

    Strategy:
    1. Score each world-space Z position by the curvature of faces near it.
    2. Pick the N positions with the lowest accumulated curvature score that
       are spaced at least min_gap apart.
    3. Return them as Z-axis cut heights.

    Returns a list of dicts: {'axis': 'Z', 'value': float, 'score': float}
    """
    bm.faces.ensure_lookup_table()

    # Gather (z_centre, curvature) pairs per face
    face_data = []
    for face in bm.faces:
        z = face.calc_center_median().z
        curv = curvatures[face.index] if face.index < len(curvatures) else 0.5
        face_data.append((z, curv))

    if not face_data:
        return []

    z_values = [fd[0] for fd in face_data]
    z_min, z_max = min(z_values), max(z_values)

    if z_max - z_min < 0.001:
        return []

    # Bin the Z range into 100 slices
    bins = 100
    bin_size = (z_max - z_min) / bins
    bin_scores = [0.0] * bins
    bin_counts = [0] * bins

    for z, curv in face_data:
        idx = int((z - z_min) / (z_max - z_min) * (bins - 1))
        idx = max(0, min(bins - 1, idx))
        bin_scores[idx] += curv
        bin_counts[idx] += 1

    # Average score per bin
    avg_scores = [
        bin_scores[i] / bin_counts[i] if bin_counts[i] > 0 else 1.0
        for i in range(bins)
    ]

    # Pick lowest-scoring bins with a minimum spacing
    min_gap = max(1, bins // (num_planes * 2))
    candidates = []
    used = set()

    sorted_bins = sorted(range(bins), key=lambda i: avg_scores[i])
    for b in sorted_bins:
        if len(candidates) >= num_planes:
            break
        if any(abs(b - u) < min_gap for u in used):
            continue
        # Skip the very top and bottom 5% (near model caps)
        if b < bins * 0.05 or b > bins * 0.95:
            continue
        used.add(b)
        z_pos = z_min + (b + 0.5) * bin_size
        candidates.append({
            'axis': 'Z',
            'value': z_pos,
            'score': avg_scores[b],
            'accepted': avg_scores[b] < threshold,
        })

    return sorted(candidates, key=lambda c: c['value'])


def simulate_cut_creates_island(bm, z_cut, margin=0.01):
    """
    Simulate slicing at z_cut and check whether any island becomes disconnected.
    Returns True if the cut would create an isolated island.
    Via: temporarily labelling faces as 'above', 'below', or 'cut' and checking connectivity within the above/below groups.
    """

    bm.faces.ensure_lookup_table()

    above, below, on_cut = [], [], []
    for face in bm.faces:
        z = face.calc_center_median().z
        if z > z_cut + margin:
            above.append(face.index)
        elif z < z_cut - margin:
            below.append(face.index)
        else:
            on_cut.append(face.index)

    def connected_groups(face_indices):
        idx_set = set(face_indices)
        visited = set()
        groups = []

        face_map = {f.index: f for f in bm.faces if f.index in idx_set}

        def flood(start):
            stack = [start]
            group = set()
            while stack:
                fi = stack.pop()
                if fi in visited or fi not in idx_set:
                    continue
                visited.add(fi)
                group.add(fi)
                for edge in face_map[fi].edges:
                    for lf in edge.link_faces:
                        if lf.index in idx_set and lf.index not in visited:
                            stack.append(lf.index)
            return group

        for fi in face_indices:
            if fi not in visited:
                groups.append(flood(fi))
        return groups

    groups_above = connected_groups(above)
    groups_below = connected_groups(below)

    # If either half has more than 1 connected group, we'd create an island
    return len(groups_above) > 1 or len(groups_below) > 1


#  GATE-PRIORITY PAINTING (weight paint based)
# Users brush priority values onto mesh using Blender's built-in Weight Paint tool.
# We save the created vertex group so we can read the weights back out later.

PRIORITY_VG_NAME = "SpruePriority"

def apply_heatmap_vertex_colors(obj, curvatures):
    """
    Write per-face curvature into a vertex colour attribute so it's
    visible in the viewport (while in Object/Rendered mode).
    """
    mesh = obj.data

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
        for _ in poly.loop_indices:
            color_attr.data[loop_index].color = color
            loop_index += 1

    bm_tmp.free()

    # display assigned colour attribute
    mesh.color_attributes.render_color_index = mesh.color_attributes.find(color_layer_name)
    mesh.color_attributes.active_color_index = mesh.color_attributes.find(color_layer_name)
    
    
def ensure_priority_vertex_group(obj):
    """
    Get or create the vertex group used to store gate-priority weights.
    A new group is zeroed on every vertex so the entire mesh
    reads as 'blue' (low priority) in Weight Paint mode until
    the user brushes over it, rather than showing unweighted grey.
    """
    vg = obj.vertex_groups.get(PRIORITY_VG_NAME)
    if vg is None:
        vg = obj.vertex_groups.new(name=PRIORITY_VG_NAME)
        all_indices = list(range(len(obj.data.vertices)))
        vg.add(all_indices, 0.0, 'REPLACE')
    return vg


def get_priority_values(obj):
    #TODO: connect to Cole's find_best_gate_face function
    """
    Read the priority vertex group back out as a list of floats,
    one entry per vertex (0.0 for any vertex not in the group).
    Returns [] if the mesh has no priority group yet.
    """
    vg = obj.vertex_groups.get(PRIORITY_VG_NAME)
    if vg is None:
        return []

    values = [0.0] * len(obj.data.vertices)
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == vg.index:
                values[v.index] = g.weight
                break
    return values


#  GATE-PLANE ORIENTATION
# Rotate each piece so its painted gate-priority vertices end up coplanar
# (on a shared horizontal plane, matching the runner frame's Z), preferring
# whichever valid rotation leaves the least surface area vertical.

def get_weighted_vertices_local(obj, min_weight=0.02):
    """
    Return [(local_position: Vector, weight: float), ...] for every vertex
    whose painted gate-priority weight exceeds min_weight. Local (mesh) space,
    independent of the object's current transform. Empty list if nothing painted.
    """
    weights = get_priority_values(obj)
    if not weights:
        return []
    pts = []
    for v in obj.data.vertices:
        w = weights[v.index] if v.index < len(weights) else 0.0
        if w > min_weight:
            pts.append((v.co.copy(), w))
    return pts


def fit_weighted_plane(points_weights):
    """
    Weighted least-squares plane fit through [(Vector, weight), ...] (needs >= 2 points).

    Returns a dict:
      'centroid'   - weighted centroid (Vector)
      'normal'     - best-fit plane normal (Vector), meaningful when not degenerate
      'plane_axes' - (Vector, Vector) spanning the plane; when degenerate this is
                     the circle of directions the normal could validly be
      'degenerate' - True if the points are (near) collinear, so 'normal' is only
                     one of many valid choices and the caller should search
                     'plane_axes' with best_axis_in_plane() instead of trusting it
    """
    pts = np.array([[p.x, p.y, p.z] for p, w in points_weights])
    wts = np.array([w for p, w in points_weights])
    wsum = wts.sum()
    centroid = (pts * wts[:, None]).sum(axis=0) / wsum

    diff = pts - centroid
    cov = (diff * wts[:, None]).T @ diff / wsum

    eigvals, eigvecs = np.linalg.eigh(cov)  # ascending order
    normal = Vector(eigvecs[:, 0]).normalized()
    axis_b = Vector(eigvecs[:, 1]).normalized()
    axis_c = Vector(eigvecs[:, 2]).normalized()

    spread = max(eigvals[2], 1e-9)
    degenerate = (eigvals[1] / spread) < 0.05

    return {
        'centroid': Vector(centroid),
        'normal': normal,
        'plane_axes': (axis_b, axis_c),
        'degenerate': degenerate,
    }


def face_area_normal_tensor(bm):
    """
    Area-weighted normal structure tensor M = sum(area_f * outer(n_f, n_f)) over
    every face of bm (local mesh space). The eigenvector of M with the LARGEST
    eigenvalue is the axis that, if made vertical, leaves the least surface area
    vertical (i.e. the object's flattest resting axis).
    """
    bm.faces.ensure_lookup_table()
    M = np.zeros((3, 3))
    for f in bm.faces:
        area = f.calc_area()
        if area <= 1e-9:
            continue
        n = f.normal.normalized()
        nv = np.array([n.x, n.y, n.z])
        M += area * np.outer(nv, nv)
    return M


def best_flat_axis(M):
    """Axis (Vector) minimising vertical surface area, given a structure tensor M."""
    eigvals, eigvecs = np.linalg.eigh(M)
    return Vector(eigvecs[:, -1]).normalized()


def best_axis_in_plane(M, axis_b, axis_c, samples=36):
    """
    Among the circle of unit vectors spanned by axis_b/axis_c (the directions a
    degenerate plane-fit's normal could validly be), pick the one minimising
    vertical surface area (maximising axis^T M axis).
    """
    best_axis, best_score = axis_b, None
    for i in range(samples):
        theta = math.pi * i / samples  # 0..180 deg; axis and -axis are equivalent here
        candidate = (axis_b * math.cos(theta) + axis_c * math.sin(theta)).normalized()
        cv = np.array([candidate.x, candidate.y, candidate.z])
        score = float(cv @ M @ cv)
        if best_score is None or score > best_score:
            best_score, best_axis = score, candidate
    return best_axis


def compute_gate_plane_axis(obj, bm, min_weight=0.02):
    """
    Decide which local-space axis of obj should be rotated to point 'up' (world Z)
    so that:
      1. the piece's painted gate-priority vertices end up coplanar (horizontal), and
      2. among rotations satisfying (1), the one with least vertical surface area wins.

    Returns (axis, plane_point_local, has_priority):
      axis             - unit Vector (local space) to align to world Z
      plane_point_local- local-space point that should land at the frame's shared Z
                          after rotation (so every piece's gate plane lines up)
      has_priority      - False if nothing was painted (axis then just minimises
                           vertical surface area for the whole piece, no gate constraint)
    """
    weighted_pts = get_weighted_vertices_local(obj, min_weight=min_weight)
    M = face_area_normal_tensor(bm)
    has_priority = len(weighted_pts) > 0

    if len(weighted_pts) == 0:
        axis = best_flat_axis(M)
        centroid = Vector((0.0, 0.0, 0.0))
        if obj.data.vertices:
            centroid = sum((v.co for v in obj.data.vertices), Vector()) / len(obj.data.vertices)
        return axis, centroid, has_priority

    if len(weighted_pts) == 1:
        # A single point can't define a plane -- orientation is fully free, so
        # just minimise vertical area, but still bring that one point to Z=0.
        axis = best_flat_axis(M)
        return axis, weighted_pts[0][0].copy(), has_priority

    fit = fit_weighted_plane(weighted_pts)
    if fit['degenerate']:
        axis_b, axis_c = fit['plane_axes']
        axis = best_axis_in_plane(M, axis_b, axis_c)
    else:
        axis = fit['normal']

    return axis, fit['centroid'], has_priority


#  SPRUE FRAME GENERATION
def find_best_gate_face(obj, toward_direction):
    """
    Find the face on obj that is:
      - lowest curvature (flattest / least detailed)
      - facing roughly toward toward_direction (outward toward the nearest frame edge)

    Returns (face_center_world, face_normal_world) or None.
    toward_direction is a Vector in world space.
    """
    mesh = obj.data
    mat = obj.matrix_world

    # Recompute curvatures if available, else treat all as 0
    bm = bmesh.new()
    bm.from_mesh(mesh)
    curvatures = compute_face_curvature(bm)
    bm.faces.ensure_lookup_table()

    best_score = None
    best_center = None
    best_normal = None

    toward_dir = toward_direction.normalized()

    for poly in mesh.polygons:
        curv = curvatures[poly.index] if poly.index < len(curvatures) else 0.5

        # World-space normal
        world_normal = (mat.to_3x3() @ poly.normal).normalized()

        # How much does this face point toward the frame edge?
        alignment = world_normal.dot(toward_dir)

        # Only consider faces that point at least somewhat outward (> 30°)
        if alignment < 0.5:
            continue

        # Score: lower curvature + better alignment = better gate location
        # Weight curvature 70%, alignment 30%
        score = (curvatures[poly.index] * 0.7) - (alignment * 0.3)

        if best_score is None or score < best_score:
            best_score = score
            best_center = mat @ poly.center
            best_normal = world_normal

    bm.free()
    return (best_center, best_normal) if best_center else None


def find_gate_points_weighted(obj, min_weight=0.05, max_gates=None):
    """
    Pick gate locations using painted gate-priority weights. Painted faces are
    clustered into connected regions first (a flood-fill over shared edges),
    so several separate paint blobs on the same piece become several separate
    gates rather than being collapsed into one. Each region contributes its
    single highest-weighted face as that region's gate point.

    Returns a list of (face_center_world, face_normal_world), strongest
    region first. Empty list if nothing was painted above min_weight.
    If max_gates is given, only the highest-scoring regions are kept.
    """
    weights = get_priority_values(obj)
    if not weights or max(weights, default=0.0) <= min_weight:
        return []

    mesh = obj.data
    mat = obj.matrix_world

    face_scores = {}
    for poly in mesh.polygons:
        vert_weights = [weights[vi] for vi in poly.vertices if vi < len(weights)]
        if not vert_weights:
            continue
        avg_w = sum(vert_weights) / len(vert_weights)
        if avg_w > min_weight:
            face_scores[poly.index] = avg_w

    if not face_scores:
        return []

    # Flood-fill the qualifying faces (via bmesh edge adjacency) into
    # disconnected clusters -- one gate per cluster.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    qualifying = set(face_scores.keys())
    visited = set()
    clusters = []

    for start in qualifying:
        if start in visited:
            continue
        stack = [start]
        cluster = set()
        while stack:
            fi = stack.pop()
            if fi in visited or fi not in qualifying:
                continue
            visited.add(fi)
            cluster.add(fi)
            for edge in bm.faces[fi].edges:
                for linked in edge.link_faces:
                    if linked.index in qualifying and linked.index not in visited:
                        stack.append(linked.index)
        clusters.append(cluster)

    bm.free()

    gate_points = []
    for cluster in clusters:
        best_fi = max(cluster, key=lambda fi: face_scores[fi])
        poly = mesh.polygons[best_fi]
        center_world = mat @ poly.center
        normal_world = (mat.to_3x3() @ poly.normal).normalized()
        gate_points.append((face_scores[best_fi], center_world, normal_world))

    gate_points.sort(key=lambda g: g[0], reverse=True)
    if max_gates is not None:
        gate_points = gate_points[:max_gates]

    return [(center, normal) for _, center, normal in gate_points]


def find_gate_faces(obj, toward_direction=None, min_weight=0.05, max_gates=None):
    """
    Pick the gate location(s) on obj:
      1. If gate-priority weights were painted, use find_gate_points_weighted --
         one gate per disconnected painted region, that's literally where the
         user painted the gate(s) to go.
      2. Otherwise fall back to the single-gate curvature/alignment heuristic.
         If a toward_direction is given, use it directly; if not (the piece is
         walled on every side, so any outward face is viable) try each
         cardinal direction and keep the first face that qualifies.

    Always returns a list of (face_center_world, face_normal_world) -- empty
    if no gate location could be found at all.
    """
    weighted = find_gate_points_weighted(obj, min_weight=min_weight, max_gates=max_gates)
    if weighted:
        return weighted

    if toward_direction is not None:
        result = find_best_gate_face(obj, toward_direction)
        return [result] if result is not None else []

    for d in (Vector((1, 0, 0)), Vector((-1, 0, 0)), Vector((0, 1, 0)), Vector((0, -1, 0))):
        result = find_best_gate_face(obj, d)
        if result is not None:
            return [result]
    return []



def nearest_wall_point(face_center_world, x_min, x_max, y_min, y_max, half_height):
    """
    Given a gate face centre, find where it should meet a rectangular runner
    wall/frame whose inner edges are at x_min/x_max/y_min/y_max -- the closest
    of the four inner faces, clamped to the bar's Z range.
    """
    fx, fy = face_center_world.x, face_center_world.y
    gate_z = max(-half_height, min(half_height, face_center_world.z))

    dist_left = fx - x_min
    dist_right = x_max - fx
    dist_bottom = fy - y_min
    dist_top = y_max - fy
    min_dist = min(dist_left, dist_right, dist_bottom, dist_top)

    if min_dist == dist_left:
        return Vector((x_min, fy, gate_z))
    elif min_dist == dist_right:
        return Vector((x_max, fy, gate_z))
    elif min_dist == dist_bottom:
        return Vector((fx, y_min, gate_z))
    else:
        return Vector((fx, y_max, gate_z))


def add_runner_bar(collection, p1, p2, width, height, name):
    """
    Build a straight rectangular bridge bar between p1 and p2 (used to connect
    a piece's individual runner wall ring back into the main outer frame).
    p1/p2 must share one axis-aligned coordinate (the bridge runs along the
    other). width is the bar's thickness perpendicular to travel, height is
    its Z thickness. Returns the new object, or None if p1/p2 are too close.
    """
    if (p2 - p1).length < 0.001:
        return None

    half_w = width / 2.0
    half_h = height / 2.0
    z = (p1.z + p2.z) / 2.0

    if abs(p1.x - p2.x) >= abs(p1.y - p2.y):
        x0, x1 = sorted((p1.x, p2.x))
        y0, y1 = p1.y - half_w, p1.y + half_w
    else:
        y0, y1 = sorted((p1.y, p2.y))
        x0, x1 = p1.x - half_w, p1.x + half_w

    bm = bmesh.new()
    verts = [
        bm.verts.new((x0, y0, z - half_h)),
        bm.verts.new((x1, y0, z - half_h)),
        bm.verts.new((x1, y1, z - half_h)),
        bm.verts.new((x0, y1, z - half_h)),
        bm.verts.new((x0, y0, z + half_h)),
        bm.verts.new((x1, y0, z + half_h)),
        bm.verts.new((x1, y1, z + half_h)),
        bm.verts.new((x0, y1, z + half_h)),
    ]
    faces = [
        [verts[0], verts[1], verts[2], verts[3]],
        [verts[4], verts[5], verts[6], verts[7]],
        [verts[0], verts[1], verts[5], verts[4]],
        [verts[2], verts[3], verts[7], verts[6]],
        [verts[0], verts[3], verts[7], verts[4]],
        [verts[1], verts[2], verts[6], verts[5]],
    ]
    for f in faces:
        bm.faces.new(f)
    bm.normal_update()

    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    bar_obj = bpy.data.objects.new(name, mesh)
    bar_obj.location = (0.0, 0.0, 0.0)
    collection.objects.link(bar_obj)
    return bar_obj


def make_frame_mesh(bm, x_min, x_max, y_min, y_max, fw, fh):
    """
    Build the four bars of the rectangular runner frame into bm.
    fw = frame bar width (XY), fh = frame bar height (Z).
    The frame sits centred at Z=0.
    Returns the bmesh (modified in place).
    """
    half_h = fh / 2.0

    def add_bar(ax, ay, bx, by):
        """Add one rectangular bar from (ax,ay) to (bx,by) with height fh."""
        verts = [
            bm.verts.new((ax, ay, -half_h)),
            bm.verts.new((bx, ay, -half_h)),
            bm.verts.new((bx, by, -half_h)),
            bm.verts.new((ax, by, -half_h)),
            bm.verts.new((ax, ay,  half_h)),
            bm.verts.new((bx, ay,  half_h)),
            bm.verts.new((bx, by,  half_h)),
            bm.verts.new((ax, by,  half_h)),
        ]
        faces = [
            [verts[0], verts[1], verts[2], verts[3]],  # bottom
            [verts[4], verts[5], verts[6], verts[7]],  # top
            [verts[0], verts[1], verts[5], verts[4]],  # front
            [verts[2], verts[3], verts[7], verts[6]],  # back
            [verts[0], verts[3], verts[7], verts[4]],  # left
            [verts[1], verts[2], verts[6], verts[5]],  # right
        ]
        for f in faces:
            bm.faces.new(f)

    # Bottom bar
    add_bar(x_min - fw, y_min - fw, x_max + fw, y_min)
    # Top bar
    add_bar(x_min - fw, y_max,      x_max + fw, y_max + fw)
    # Left bar
    add_bar(x_min - fw, y_min,      x_min,      y_max)
    # Right bar
    add_bar(x_max,      y_min,      x_max + fw, y_max)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    return bm


def add_gate_cylinder(collection, base_point, tip_point, diameter, name):
    """
    Build a cylinder stub precisely from base_point to tip_point using bmesh,
    placing all vertices at exact world positions so no rotation transform is needed.
    base_point lives on the frame inner face; tip_point lives on the piece surface.
    Returns the new object, or None if the two points are too close.
    """
    import math

    direction = tip_point - base_point
    length = direction.length
    if length < 0.001:
        return None

    dir_norm = direction.normalized()

    # Build a pair of axes perpendicular to dir_norm so we can fan out the ring of verts
    if abs(dir_norm.x) < 0.9:
        arbitrary = Vector((1.0, 0.0, 0.0))
    else:
        arbitrary = Vector((0.0, 1.0, 0.0))

    perp1 = dir_norm.cross(arbitrary).normalized()
    perp2 = dir_norm.cross(perp1).normalized()

    radius   = diameter / 2.0
    segments = 8

    bm = bmesh.new()
    base_verts = []
    tip_verts  = []

    for i in range(segments):
        angle  = 2.0 * math.pi * i / segments
        offset = perp1 * (radius * math.cos(angle)) + perp2 * (radius * math.sin(angle))
        base_verts.append(bm.verts.new(base_point + offset))
        tip_verts.append(bm.verts.new(tip_point  + offset))

    # Side faces (winding so normals face outward)
    for i in range(segments):
        ni = (i + 1) % segments
        bm.faces.new([base_verts[i], base_verts[ni], tip_verts[ni], tip_verts[i]])

    # End caps
    bm.faces.new(list(reversed(base_verts)))   # base cap (faces away from tip)
    bm.faces.new(tip_verts)                     # tip cap  (faces away from base)

    bm.normal_update()

    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    # Object at world origin — all verts are already in world space
    gate_obj = bpy.data.objects.new(name, mesh)
    gate_obj.location = (0.0, 0.0, 0.0)
    collection.objects.link(gate_obj)

    return gate_obj


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