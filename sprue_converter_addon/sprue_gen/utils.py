import math
import bpy
import bmesh
import numpy as np
from mathutils import Vector
from ..priority_brush.utils import get_priority_values
from .. import mesh_utils

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
    Find the face on obj that is best suited for a gate:
      - high painted gate-priority (from the SpruePriority weight-paint map)
      - low curvature (flat / least detailed)
      - facing roughly toward toward_direction (outward toward the nearest frame edge)

    Weighting: priority 70%, curvature 20%, alignment 10%.
    If no priority has been painted, every face has priority 0 and the
    scoring falls back to curvature/alignment only.

    Returns (face_center_world, face_normal_world) or None.
    toward_direction is a Vector in world space.
    """
    mesh = obj.data
    mat = obj.matrix_world

    # Recompute curvatures if available, else treat all as 0
    bm = bmesh.new()
    bm.from_mesh(mesh)
    curvatures = mesh_utils.compute_face_curvature(bm)
    bm.faces.ensure_lookup_table()

    # Painted gate-priority, per vertex (0.0 for every vertex if unpainted)
    priority_values = get_priority_values(obj)

    best_score = None
    best_center = None
    best_normal = None

    toward_dir = toward_direction.normalized()

    for poly in mesh.polygons:
        curv = curvatures[poly.index] if poly.index < len(curvatures) else 0.5

        # Face priority = average of its vertices' painted weights
        if priority_values:
            vert_priorities = [priority_values[vi] for vi in poly.vertices]
            priority = sum(vert_priorities) / len(vert_priorities)
        else:
            priority = 0.0

        # World-space normal
        world_normal = (mat.to_3x3() @ poly.normal).normalized()

        # How much does this face point toward the frame edge?
        alignment = world_normal.dot(toward_dir)

        # Only consider faces that point at least somewhat outward (> 30°)
        if alignment < 0.5:
            continue

        # Score: lower curvature + better alignment + higher priority = better gate location
        # Weight priority 70%, curvature 20%, alignment 10%
        score = (curv * 0.2) - (alignment * 0.1) - (priority * 0.7)

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
