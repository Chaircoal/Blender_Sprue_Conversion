import math
import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix
from ..priority_brush.utils import get_priority_values
from .. import mesh_utils

DEBUG = True  # set to False to silence the [SPRUE] prints in the system console


def debug(*args):
    """Print to the system console when DEBUG is on."""
    if DEBUG:
        print("[SPRUE]", *args)


#  GATE-PLANE ORIENTATION
# Work out which direction the painted gate-priority area faces, so orient_part
# can turn that area toward the injection point. With nothing painted we look
# for the largest flat patch instead (find_flat_gate_region).

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
        if v.index < len(weights):
            w = weights[v.index]
        else:
            w = 0.0

        if w > min_weight:
            pts.append((v.co.copy(), w))
    return pts


def fit_weighted_plane(points_weights):
    """
    Weighted least-squares plane fit through [(Vector, weight), ...] (needs >= 2 points).

    Returns a dict:
      'centroid'   - weighted centroid (Vector)
      'normal'     - best-fit plane normal (Vector), meaningful when not degenerate
      'line_direction'    - the direction the points mostly spread along
      'valid_normal_axes' - (Vector, Vector) at right angles to line_direction.
                            When the points are (near) collinear, any direction in
                            the circle these two span is a valid plane normal
      'degenerate' - True if the points are (near) collinear (a thin strip), so
                     'normal' is only one of many valid choices and the caller
                     has to pick one itself
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
        'line_direction': axis_c,
        'valid_normal_axes': (normal, axis_b),
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


def axis_for_line_shaped_paint(obj, M, fit, min_weight):
    """
    Paint that is a thin strip (or several strips in a row) doesn't define a
    plane: a gate could come from any direction around the strip. So instead of
    guessing, use the direction the painted faces really face, which puts the
    gate on the surface the user painted.

    A gate can't point along the strip, so that part of the direction is removed.
    If the painted faces don't agree on a direction, fall back to the direction
    (around the strip) that leaves the least vertical surface area.
    """
    line_direction = fit['line_direction']
    normal_a, normal_b = fit['valid_normal_axes']

    painted_normal = get_painted_normal(obj, min_weight)
    if painted_normal is not None:
        along_strip = painted_normal.dot(line_direction)
        across_strip = painted_normal - line_direction * along_strip
        if across_strip.length > 0.2:
            debug("paint is a thin strip: gate axis taken from the painted faces' normal")
            return across_strip.normalized()

    debug("paint is a thin strip and its faces disagree: gate axis chosen by flatness")
    return best_axis_in_plane(M, normal_a, normal_b)


def compute_gate_plane_axis(obj, bm, min_weight=0.02):
    """
    Decide which local-space axis of obj the painted gate-priority area faces.
    orient_part later rotates this axis to point at the injection point.
      1. the painted vertices are fitted with a plane, and the plane's normal is the axis
      2. if the paint is a thin strip the plane is ambiguous, so the direction the
         painted faces actually face is used (axis_for_line_shaped_paint)

    Returns (axis, plane_point_local, has_priority):
      axis             - unit Vector (local space) the gate area faces
      plane_point_local- local-space point where the gate should touch the part
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
        axis = axis_for_line_shaped_paint(obj, M, fit, min_weight)
    else:
        axis = fit['normal']

    return axis, fit['centroid'], has_priority

#  SPRUE FRAME GENERATION
def get_face_weights(obj, weights, min_weight):
    """
    Average painted weight of every face that is painted above min_weight.
    Returns {face_index: average_weight}.
    """
    face_weights = {}
    for poly in obj.data.polygons:
        vertex_weights = []
        for vertex_index in poly.vertices:
            if vertex_index < len(weights):
                vertex_weights.append(weights[vertex_index])

        if not vertex_weights:
            continue

        average = sum(vertex_weights) / len(vertex_weights)
        if average > min_weight:
            face_weights[poly.index] = average

    return face_weights


def get_painted_normal(obj, min_weight):
    """
    The direction the painted area faces, in the object's local space: the
    average of the painted faces' normals, weighted by paint strength and face area.
    Returns None if nothing is painted, or if the painted faces point so many
    different ways (for example paint on opposite sides of the part) that an
    average would be meaningless.
    """
    weights = get_priority_values(obj)
    if not weights:
        return None

    face_weights = get_face_weights(obj, weights, min_weight)
    if not face_weights:
        return None

    total_normal = Vector((0.0, 0.0, 0.0))
    total_strength = 0.0
    for face_index, weight in face_weights.items():
        poly = obj.data.polygons[face_index]
        strength = weight * poly.area
        total_normal = total_normal + poly.normal * strength
        total_strength += strength

    if total_strength < 1e-9:
        return None

    # 1.0 means every painted face points the same way, near 0 means they cancel out
    agreement = total_normal.length / total_strength
    if agreement < 0.3:
        return None

    return total_normal.normalized()


def get_painted_faces(obj, min_weight):
    """
    Every painted face of obj as (weight, face_centre_world), strongest first.
    World space, so the part must already be placed and
    context.view_layer.update() called so obj.matrix_world is current.
    """
    weights = get_priority_values(obj)
    if not weights:
        return []

    face_weights = get_face_weights(obj, weights, min_weight)
    matrix = obj.matrix_world

    painted_faces = []
    for face_index, weight in face_weights.items():
        centre_world = matrix @ obj.data.polygons[face_index].center
        painted_faces.append((weight, centre_world))

    painted_faces.sort(key=lambda face: face[0], reverse=True)
    return painted_faces


def find_painted_clusters(obj, min_weight=0.05):
    """
    Group the painted faces into connected regions (a flood-fill over shared
    edges), so separate paint blobs on the same part stay separate.

    Returns a list of regions, strongest first. Each region is a list of
    (weight, face_centre_world), strongest face first. The list is empty if
    nothing was painted above min_weight.
    World space, so the part must already be placed and
    context.view_layer.update() called so obj.matrix_world is current.
    """
    weights = get_priority_values(obj)
    if not weights or max(weights, default=0.0) <= min_weight:
        return []

    face_weights = get_face_weights(obj, weights, min_weight)
    if not face_weights:
        return []

    mesh = obj.data
    matrix = obj.matrix_world

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    qualifying = set(face_weights.keys())
    visited = set()
    clusters = []

    for start in qualifying:
        if start in visited:
            continue
        stack = [start]
        cluster = set()
        while stack:
            face_index = stack.pop()
            if face_index in visited or face_index not in qualifying:
                continue
            visited.add(face_index)
            cluster.add(face_index)
            for edge in bm.faces[face_index].edges:
                for linked in edge.link_faces:
                    if linked.index in qualifying and linked.index not in visited:
                        stack.append(linked.index)
        clusters.append(cluster)

    bm.free()

    regions = []
    for cluster in clusters:
        region = []
        for face_index in cluster:
            centre_world = matrix @ mesh.polygons[face_index].center
            region.append((face_weights[face_index], centre_world))
        region.sort(key=lambda face: face[0], reverse=True)
        regions.append(region)

    # Region with the strongest paint first
    regions.sort(key=lambda region: region[0][0], reverse=True)
    return regions


def add_box(bm, x0, y0, z0, x1, y1, z1):
    """
    Add a rectangular box to bm. (x0, y0, z0) is one corner and
    (x1, y1, z1) is the opposite corner. Used for runner bars and frame bars.
    """
    verts = [
        bm.verts.new((x0, y0, z0)),
        bm.verts.new((x1, y0, z0)),
        bm.verts.new((x1, y1, z0)),
        bm.verts.new((x0, y1, z0)),
        bm.verts.new((x0, y0, z1)),
        bm.verts.new((x1, y0, z1)),
        bm.verts.new((x1, y1, z1)),
        bm.verts.new((x0, y1, z1)),
    ]
    faces = [
        [verts[0], verts[1], verts[2], verts[3]],
        [verts[4], verts[5], verts[6], verts[7]],
        [verts[0], verts[1], verts[5], verts[4]],
        [verts[2], verts[3], verts[7], verts[6]],
        [verts[0], verts[3], verts[7], verts[4]],
        [verts[1], verts[2], verts[6], verts[5]],
    ]
    for face in faces:
        bm.faces.new(face)


# Number of sides on the round runner and frame bars (16 reads as round)
RUNNER_SEGMENTS = 16


def add_round_bar(bm, p1, p2, radius, segments=RUNNER_SEGMENTS):
    """
    Add a straight round bar (a cylinder with flat end caps) to bm, running
    from p1 to p2. p1 and p2 are the centres of the two end caps, in world space.
    """
    direction = p2 - p1
    if direction.length < 0.001:
        return
    dir_norm = direction.normalized()

    # Build a pair of axes perpendicular to the bar so we can fan out the ring of verts
    if abs(dir_norm.x) < 0.9:
        arbitrary = Vector((1.0, 0.0, 0.0))
    else:
        arbitrary = Vector((0.0, 1.0, 0.0))
    perp1 = dir_norm.cross(arbitrary).normalized()
    perp2 = dir_norm.cross(perp1).normalized()

    start_ring = []
    end_ring = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        offset = perp1 * (radius * math.cos(angle)) + perp2 * (radius * math.sin(angle))
        start_ring.append(bm.verts.new(p1 + offset))
        end_ring.append(bm.verts.new(p2 + offset))

    # Side faces (winding so normals face outward)
    for i in range(segments):
        ni = (i + 1) % segments
        bm.faces.new([start_ring[i], start_ring[ni], end_ring[ni], end_ring[i]])

    # End caps
    bm.faces.new(list(reversed(start_ring)))
    bm.faces.new(end_ring)


def add_ball(bm, centre, radius, segments=RUNNER_SEGMENTS):
    """Add a sphere to bm. Used to round off the corners of the frame."""
    bmesh.ops.create_uvsphere(
        bm,
        u_segments=segments,
        v_segments=max(segments // 2, 3),
        radius=radius,
        matrix=Matrix.Translation(centre),
    )


def add_runner_bar(collection, p1, p2, diameter, name, segments=RUNNER_SEGMENTS):
    """
    Build a straight round runner bar between p1 and p2 and link it into the
    collection as a new object. p1/p2 are the centres of the bar's two ends,
    so the bar's axis runs through them (gates start on this axis at Z = 0).
    Returns the new object, or None if p1/p2 are too close.
    """
    if (p2 - p1).length < 0.001:
        return None

    bm = bmesh.new()
    add_round_bar(bm, p1, p2, diameter / 2.0, segments)
    bm.normal_update()

    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    bar_obj = bpy.data.objects.new(name, mesh)
    bar_obj.location = (0.0, 0.0, 0.0)
    collection.objects.link(bar_obj)
    return bar_obj


def make_frame_mesh(bm, x_min, x_max, y_min, y_max, diameter, segments=RUNNER_SEGMENTS):
    """
    Build the rectangular runner frame into bm out of four round bars, with a
    ball at each corner so the corners are round too.
    x_min..y_max is the INSIDE of the frame, so the bars sit just outside it
    (their centre lines are half a diameter further out). The frame is centred at Z=0.
    Returns the bmesh (modified in place).
    """
    radius = diameter / 2.0
    left = x_min - radius
    right = x_max + radius
    bottom = y_min - radius
    top = y_max + radius

    corners = [
        Vector((left, bottom, 0.0)),
        Vector((right, bottom, 0.0)),
        Vector((right, top, 0.0)),
        Vector((left, top, 0.0)),
    ]
    for i in range(4):
        add_round_bar(bm, corners[i], corners[(i + 1) % 4], radius, segments)
        add_ball(bm, corners[i], radius, segments)

    return bm


def add_gate_cylinder(collection, base_point, tip_point, diameter, name, embed=0.0):
    """
    Build a cylinder stub precisely from base_point to tip_point using bmesh,
    placing all vertices at exact world positions so no rotation transform is needed.
    base_point lives on the frame inner face; tip_point lives on the piece surface.
    embed pushes the tip this many mm further along the gate, so the end of the
    gate sinks slightly into the part instead of only touching its surface.
    Returns the new object, or None if the two points are too close.
    """

    direction = tip_point - base_point
    length = direction.length
    if length < 0.001:
        return None

    dir_norm = direction.normalized()
    tip_point = tip_point + dir_norm * embed

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
    bm.faces.new(list(reversed(base_verts)))
    bm.faces.new(tip_verts)

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


# Objects this add-on creates itself. They must never be treated as parts,
# otherwise running the operator a second time would pick them up as parts
GENERATED_NAME_PREFIXES = ("Main_Injection_Sprue", "Sprue_Frame", "_gate_", "_runner_", "_part_copy_")


def is_usable_part(obj, view_layer=None):
    """
    True if obj is a mesh the user can currently see (not hidden, not disabled,
    not in an excluded or hidden collection) and was not built by this add-on.
    """
    if obj.type != 'MESH':
        return False

    if obj.name.startswith(GENERATED_NAME_PREFIXES):
        return False

    return obj.visible_get(view_layer=view_layer)


def get_all_part_volume():
    """
    Get (object, volume) for every visible part in the scene, largest first.
    """
    parts_volume = []
    view_layer = bpy.context.view_layer

    for obj in view_layer.objects:
        if not is_usable_part(obj, view_layer):
            continue

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        mesh_volume = bm.calc_volume()
        bm.free()

        # calc_volume ignores the object's scale, so apply it here
        scale_factor = abs(obj.scale.x * obj.scale.y * obj.scale.z)
        volume = mesh_volume * scale_factor

        parts_volume.append((obj, volume))

    # Largest first
    parts_volume.sort(key=lambda part: part[1], reverse=True)
    return parts_volume


def distribute_parts_to_quadrants(sorted_parts):
    """
    Get a list of parts in their respective quadrants. Using RR approach to place the biggest parts equally.
    """
    quadrants = {1: [], 2: [], 3: [], 4: []}
    current_quadrant = 1

    for part in sorted_parts:
        quadrants[current_quadrant].append(part)
        current_quadrant += 1
        if current_quadrant > 4:
            current_quadrant = 1

    return quadrants


def orient_part(context, obj, min_weight, face_dir):
    """
    Point the painted gate area along face_dir, then spin the part around
    face_dir so it lies flat.
    Returns (Z height of the painted spot after rotating, has_priority)
    """
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj

    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # Read the heatmap
    bm = mesh_utils.get_bmesh(obj)
    axis, plane_point, has_priority = compute_gate_plane_axis(
        obj, bm, min_weight=min_weight
    )

    if not has_priority:
        axis, plane_point = find_flat_gate_region(bm)

    if obj.mode != 'EDIT':
        bm.free()

    # get the centre of the part
    verts = [v.co for v in obj.data.vertices]
    centre = sum(verts, Vector()) / len(verts)

    # pick the sign that points from the part's centre toward the painted spot
    axis = axis.normalized()
    if axis.dot(plane_point - centre) < 0:
        axis = -axis

    target = face_dir.normalized()
    quat = axis.rotation_difference(target)

    # Apply that rotation and bake it into the mesh
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = quat
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

    # Spin around face_dir to lay the part flat
    best_angle = spin_flat(context, obj, face_dir)

    # Track where the painted spot ended up after BOTH rotations,
    # so the layout can put it at Z=0
    spin = Matrix.Rotation(best_angle, 3, target)
    painted_point = spin @ (quat @ plane_point)

    return painted_point, has_priority


def local_bounds(obj):
    """
    Get the smallest and largest corner of the part's bounding box.
    Only accurate once rotation/scale have been baked into the mesh.
    """
    pts = [Vector(c) for c in obj.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def spin_flat(context, obj, face_dir, steps=24):
    """
    Spin obj around face_dir so its bounding box is as short in Z as possible.
    The painted face keeps pointing along face_dir
    Returns the angle that was used.
    """
    mesh_pts = [v.co.copy() for v in obj.data.vertices]
    best_angle, best_height = 0.0, float('inf')

    # Try evenly spaced angles around a full circle and keep the flattest one
    for i in range(steps):
        angle = (2 * math.pi) * i / steps
        rot = Matrix.Rotation(angle, 3, face_dir.normalized())
        zs = [(rot @ p).z for p in mesh_pts]
        height = max(zs) - min(zs) # how tall the part would be at this angle
        if height < best_height:
            best_height, best_angle = height, angle

    # Apply the best angle and bake it into the mesh
    obj.rotation_mode = 'AXIS_ANGLE'
    obj.rotation_axis_angle = (best_angle, *face_dir.normalized())
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

    return best_angle


def find_flat_gate_region(bm, spread_deg=15.0):
    """
    Find the largest connected, flat patch on the part.
    A patch is flat when every face in it points within spread_deg of the
    face the patch started from. Studs, ridges and panel edges change the
    direction quickly, so they stop a patch from growing.
    """
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    all_faces = list(bm.faces)

    # Smallest dot product two normals can have and still count as "the same direction"
    min_dot = math.cos(math.radians(spread_deg))

    # Start patches from the biggest faces first, so patches begin on flat areas
    seed_order = sorted(all_faces, key=lambda f: f.calc_area(), reverse=True)

    visited = set()
    best_patch = []
    best_area = 0.0

    for seed_face in seed_order:
        if seed_face.index in visited:
            continue

        seed_normal = seed_face.normal.copy()
        patch = []
        patch_area = 0.0

        # Flood fill outward from the seed face over shared edges
        to_check = [seed_face]
        visited.add(seed_face.index)

        while len(to_check) > 0:
            face = to_check.pop()
            patch.append(face)
            patch_area += face.calc_area()

            for edge in face.edges:
                for neighbour in edge.link_faces:
                    if neighbour.index in visited:
                        continue

                    # Only join the patch if it points the same way as the seed
                    if neighbour.normal.dot(seed_normal) >= min_dot:
                        visited.add(neighbour.index)
                        to_check.append(neighbour)

        if patch_area > best_area:
            best_area = patch_area
            best_patch = patch

    # if the mesh had no faces at all, give a harmless default
    if len(best_patch) == 0:
        return Vector((0.0, 0.0, 1.0)), Vector((0.0, 0.0, 0.0))

    # Axis: the area-weighted average direction of the patch
    axis_sum = Vector((0.0, 0.0, 0.0))
    for face in best_patch:
        axis_sum += face.normal * face.calc_area()
    axis = axis_sum.normalized()

    # Middle of the patch: the area-weighted average of the face centres
    middle_sum = Vector((0.0, 0.0, 0.0))
    for face in best_patch:
        middle_sum += face.calc_center_median() * face.calc_area()
    patch_middle = middle_sum / best_area

    # Gate point: the face centre closest to that middle, so it sits on the part
    point = best_patch[0].calc_center_median()
    closest_distance = (point - patch_middle).length
    for face in best_patch:
        centre = face.calc_center_median()
        distance = (centre - patch_middle).length
        if distance < closest_distance:
            closest_distance = distance
            point = centre

    return axis, point


def find_wall_for_gate(gate_base, direction_x, wall_faces_x, max_distance,
                       placed_bounds, half_width, clearance):
    """
    Gates run along X. Look from gate_base in direction_x (+1 or -1) for a wall
    (the Y trunk or the outer frame) that the gate could run straight into
    instead of getting its own feeder.

    wall_faces_x   - X positions of every face that counts as a wall
    max_distance   - walls further away than this are ignored
    placed_bounds  - (x_min, x_max, y_min, y_max) of every placed part
    half_width     - half the width of the bar that would be built
    clearance      - extra space to keep between the bar and any part

    Returns the X of the wall face to run into, or None if no wall is close
    enough or a part is in the way.
    """
    # Find the nearest wall in the direction we are travelling
    nearest_wall_x = None
    nearest_distance = None
    for wall_x in wall_faces_x:
        distance = (wall_x - gate_base.x) * direction_x
        if distance <= 0:
            continue  # this wall is behind us
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_wall_x = wall_x

    if nearest_wall_x is None:
        return None
    if nearest_distance > max_distance:
        return None

    # Make sure no part is in the strip between the gate base and that wall
    strip_x_min = min(gate_base.x, nearest_wall_x)
    strip_x_max = max(gate_base.x, nearest_wall_x)
    strip_y_min = gate_base.y - half_width - clearance
    strip_y_max = gate_base.y + half_width + clearance

    for part_x_min, part_x_max, part_y_min, part_y_max in placed_bounds:
        overlaps_x = part_x_max > strip_x_min and part_x_min < strip_x_max
        overlaps_y = part_y_max > strip_y_min and part_y_min < strip_y_max
        if overlaps_x and overlaps_y:
            return None

    return nearest_wall_x


def find_feeder_end(x, start_y, direction, end_y, placed_bounds, half_width, clearance):
    """
    Walk along Y from start_y toward end_y and return where a feeder should stop.
    direction is +1 (toward higher Y) or -1 (toward lower Y).
    The feeder normally goes all the way to end_y, but stops 'clearance' short
    of any part whose bounding box overlaps the feeder's column.
    """
    stop_y = end_y

    for part_x_min, part_x_max, part_y_min, part_y_max in placed_bounds:
        # Skip parts that are completely to the left or completely to the right
        # of the feeder's column. Anything else overlaps the column.
        part_is_left_of_feeder = part_x_max <= x - half_width
        part_is_right_of_feeder = part_x_min >= x + half_width
        if part_is_left_of_feeder or part_is_right_of_feeder:
            continue

        if direction > 0:
            # Part is ahead of us if its near edge is above the start
            if part_y_min > start_y:
                stop_y = min(stop_y, part_y_min - clearance)
        else:
            # Part is ahead of us if its near edge is below the start
            if part_y_max < start_y:
                stop_y = max(stop_y, part_y_max + clearance)

    # If the blocker is so close that we would go backwards, don't extend at all
    if direction * (stop_y - start_y) < 0:
        return start_y

    return stop_y


def is_too_close(point, taken_points, min_gap):
    """True if point is closer than min_gap to any gate tip we already placed."""
    for taken in taken_points:
        distance = (point - taken).length
        if distance < min_gap:
            return True
    return False


def get_face_curvatures(obj):
    """Curvature of every face of obj, as a list indexed by face number."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    curvatures = mesh_utils.compute_face_curvature(bm)
    bm.free()
    return curvatures


# How many points around the rim of the gate's end cap get tested (plus one in the middle)
GATE_FIT_RIM_SAMPLES = 8


def gate_fit_score(obj, base, tip, radius, depth_tolerance=0.5, max_angle_deg=30.0):
    """
    How much of the gate's flat end cap would sit on the part, from 0.0 to 1.0.

    The gate is a cylinder from base to tip. We test the middle of the end cap
    plus GATE_FIT_RIM_SAMPLES points around its rim. Each test shoots a ray
    from the gate's base, parallel to the gate, at the part. A sample passes if:
      1. The ray reaches the part at about the depth of the tip. If it hits
         something sooner, the path is blocked or the surface steps up (a
         ridge, a spike). If it hits later or not at all, the surface falls
         away (an edge, a hole). depth_tolerance is in mm.
      2. The surface there faces the gate to within max_angle_deg, so it is
         not a steep slope or the side of something.

    1.0 means the whole cap sits on flat surface, 0.5 means half of it hangs
    over an edge or step, 0.0 means the gate misses the part.

    base and tip are world space. The part must already be placed and
    context.view_layer.update() called so obj.matrix_world is current.
    """
    gate_vector = tip - base
    gate_length = gate_vector.length
    if gate_length < 1e-6:
        return 0.0
    direction = gate_vector.normalized()

    # Two directions at right angles to the gate, used to place the rim samples
    helper = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(helper)) > 0.9:
        helper = Vector((0.0, 1.0, 0.0))
    side_u = direction.cross(helper).normalized()
    side_v = direction.cross(side_u).normalized()

    # Where each sample ray starts, relative to the middle of the base
    offsets = [Vector((0.0, 0.0, 0.0))]
    for i in range(GATE_FIT_RIM_SAMPLES):
        angle = 2.0 * math.pi * i / GATE_FIT_RIM_SAMPLES
        offsets.append(side_u * (radius * math.cos(angle)) + side_v * (radius * math.sin(angle)))

    # ray_cast works in the object's local space, so convert
    to_local = obj.matrix_world.inverted()
    direction_local = (to_local.to_3x3() @ direction).normalized()
    min_facing = math.cos(math.radians(max_angle_deg))

    passed = 0
    for offset in offsets:
        origin_local = to_local @ (base + offset)

        # Only look a little past the tip: anything deeper than that is a drop-off
        hit, hit_location, hit_normal, hit_index = obj.ray_cast(
            origin_local, direction_local, distance=gate_length + depth_tolerance
        )
        if not hit:
            continue

        hit_distance = (hit_location - origin_local).length
        if abs(hit_distance - gate_length) > depth_tolerance:
            continue

        facing = abs(hit_normal.normalized().dot(direction_local))
        if facing < min_facing:
            continue

        passed += 1

    return passed / len(offsets)


def find_best_gate_tip(obj, base_x, painted_faces, gate_radius, min_fit, max_slope,
                       max_candidates=150):
    """
    Look through the painted faces for the best place to land a gate.
    painted_faces is [(weight, centre_world), ...] from get_painted_faces.
    base_x is where the gate starts (the gap just outside the part's edge).

    A candidate is only considered if the gate to it wouldn't be steeper than
    max_slope. Among candidates where the gate fits (fit >= min_fit) the one
    with the strongest paint wins, with a small preference for flatter gates.
    If none of them fit, the candidate that fits best is returned instead.

    Returns (tip, fit): the tip is a world Vector and fit is its gate_fit_score.
    Returns (None, 0.0) if there was nothing to test.
    """
    # Painted areas can have thousands of faces, so test an evenly spread sample
    candidates = list(painted_faces)
    if len(candidates) > max_candidates:
        step = len(candidates) // max_candidates
        candidates = candidates[::step]

    best_passing_tip = None
    best_passing_quality = None
    best_passing_fit = 0.0
    best_any_tip = None
    best_any_fit = -1.0

    for weight, centre in candidates:
        base = Vector((base_x, centre.y, 0.0))

        # Gates start at Z = 0, so a tip far above or below is a steep gate
        horizontal = abs(centre.x - base_x)
        if horizontal < 1e-6:
            continue
        slope = abs(centre.z) / horizontal
        if slope > max_slope:
            continue

        fit = gate_fit_score(obj, base, centre, gate_radius)

        if fit > best_any_fit:
            best_any_fit = fit
            best_any_tip = centre

        if fit >= min_fit:
            quality = weight - 0.25 * (slope / max_slope)
            if best_passing_quality is None or quality > best_passing_quality:
                best_passing_quality = quality
                best_passing_tip = centre
                best_passing_fit = fit

    debug("gate tip search:", len(candidates), "painted faces tested, best fit =", round(best_any_fit, 2))

    if best_passing_tip is not None:
        return best_passing_tip, best_passing_fit
    if best_any_tip is not None:
        return best_any_tip, best_any_fit
    return None, 0.0


def rank_gate_faces(obj, curvatures, toward_dir, base_x, other_base_x, max_slope):
    """
    Score every face on obj that could take a gate coming in from one side.
    toward_dir is the direction that side faces (world space).
    base_x is where gates on this side start, other_base_x is where gates on
    the opposite side start.

    Returns a list of (score, face_index, face_centre_world), best first.
    A LOWER score is better.
    """
    mesh = obj.data
    matrix = obj.matrix_world
    rotation = matrix.to_3x3()
    side_to_side = base_x - other_base_x

    ranked = []
    for poly in mesh.polygons:
        # The face has to point (roughly) out of this side of the part
        normal_world = (rotation @ poly.normal).normalized()
        alignment = normal_world.dot(toward_dir)
        if alignment < 0.5:
            continue

        centre_world = matrix @ poly.center

        # Gates are straight lines from the base (Z = 0) to the face centre
        # Skip faces that would need a gate steeper than max_slope
        horizontal_distance = abs(centre_world.x - base_x)
        if horizontal_distance < 1e-6:
            horizontal_distance = 1e-6
        slope = abs(centre_world.z) / horizontal_distance
        if slope > max_slope:
            continue

        # How far toward this side the face is: 0 = other side, 1 = this side
        if abs(side_to_side) > 1e-6:
            depth = (centre_world.x - other_base_x) / side_to_side
        else:
            depth = 0.0

        # Curvature of the face (flat faces make better gates)
        if poly.index < len(curvatures):
            curvature = curvatures[poly.index]
        else:
            curvature = 0.5

        # Lower is better: flat, facing the right way, far across the part, gentle slope
        score = (0.20 * curvature) - (0.15 * alignment) - (0.45 * depth) + (0.20 * slope / max_slope)
        ranked.append((score, poly.index, centre_world))

    # Sorts by score first (face_index is unique, so ties never reach the Vector)
    ranked.sort()
    return ranked


def region_has_gate(region, taken_tips, tolerance=0.01):
    """
    True if one of the gate tips we already placed sits on this painted region.
    Gate tips are always the centre of a painted face, so a region "has" a gate
    when one of its face centres is (almost exactly) at a tip.
    """
    for weight, centre in region:
        for tip in taken_tips:
            if (centre - tip).length < tolerance:
                return True
    return False


def find_extra_gates(obj, existing_tips, count, near_dir, min_weight,
                     base_x_near, base_x_far, gate_radius, min_fit, fallback_fit,
                     min_gap=10.0, min_painted_gap=10.0, max_slope=1.0, max_tries=120):
    """
    Pick up to `count` extra gate tips on a part that already has gate(s) at
    existing_tips. Everything is world space, so the part must already be placed
    and context.view_layer.update() called so obj.matrix_world is current.

    Order of preference:
      1. Other painted regions. Each region is searched for the spot where the
         gate fits best (find_best_gate_tip). Regions with no gate on them come
         first, strongest paint first. A region that already has a gate is only
         used again for faces at least min_gap away from every gate.
      2. Unpainted faces on the FAR side of the part (facing away from near_dir).
      3. If the far side has nothing usable, the same search on the near side.

    Every candidate is scored with gate_fit_score for a gate of radius gate_radius
    (which also checks the path to it is clear):
      - fit >= min_fit      -> used straight away
      - fit >= fallback_fit -> kept as a backup, only used if there would
                               otherwise be fewer than `count` gates
      - anything lower      -> rejected

    Spacing between gates:
      - painted regions with no gate yet: faces must be min_painted_gap from every gate
      - everything else: faces must be min_gap from every gate

    Unpainted faces are tested at most max_tries times per side, and only one
    face per small patch of surface (neighbouring faces would all give the same answer).

    base_x_near / base_x_far are the X positions where a gate on that side would
    start (just outside the part's edge, in the gap between parts).

    Returns [(tip_world, side), ...] where side = +1 means the gate comes in from
    the near (injection) side and -1 means it comes in from the far side.
    """
    taken = list(existing_tips)
    picked = []
    backups = []

    debug(f"extra gates for '{obj.name}': want {count}, gate spacing {min_gap:.1f} mm "
          f"({min_painted_gap:.1f} mm for new painted regions)")

    # other painted regions (the user told us where they want gates)
    painted_regions = find_painted_clusters(obj, min_weight)

    # Regions with no gate on them go first
    regions_to_try = []
    for region in painted_regions:
        if not region_has_gate(region, taken):
            regions_to_try.append((region, min_painted_gap, "no gate yet"))
    for region in painted_regions:
        if region_has_gate(region, taken):
            regions_to_try.append((region, min_gap, "already has a gate"))

    debug(len(painted_regions), "painted region(s) found")

    for region_number, (region, gap, description) in enumerate(regions_to_try, start=1):
        if len(picked) >= count:
            break

        # Leave out faces that are too close to a gate we already have
        usable_faces = []
        for weight, centre in region:
            if not is_too_close(centre, taken, gap):
                usable_faces.append((weight, centre))

        debug(f"painted region {region_number} ({description}): {len(region)} faces, "
              f"{len(usable_faces)} at least {gap:.1f} mm from existing gates")
        if not usable_faces:
            continue

        tip, fit = find_best_gate_tip(obj, base_x_near, usable_faces, gate_radius, min_fit, max_slope)
        if tip is None:
            debug("painted region skipped: every face in it needs a gate that is too steep")
            continue

        if fit >= min_fit:
            debug("painted region gate accepted, fit =", round(fit, 2))
            picked.append((tip, +1))
            taken.append(tip)
        elif fit >= fallback_fit:
            debug("painted region gate kept as a backup, fit =", round(fit, 2))
            backups.append((fit, tip, +1))
        else:
            debug("painted region gate rejected, best fit was only", round(fit, 2))

    # unpainted faces, far side first and then the near side
    if len(picked) < count:
        curvatures = get_face_curvatures(obj)

        near_dir = near_dir.normalized()
        far_dir = -near_dir

        # Only test one face per patch of surface this big
        test_spacing = gate_radius * 6.0

        # (side, direction that side faces, where its gates start, where the other side's gates start)
        sides_to_try = [
            (-1, far_dir, base_x_far, base_x_near),
            (+1, near_dir, base_x_near, base_x_far),
        ]

        for side, toward_dir, base_x, other_base_x in sides_to_try:
            if len(picked) >= count:
                break

            ranked = rank_gate_faces(obj, curvatures, toward_dir, base_x, other_base_x, max_slope)

            tries = 0
            best_fit_seen = 0.0
            tested_patches = set()
            for _score, _poly_index, centre in ranked:
                if len(picked) >= count:
                    break
                if tries >= max_tries:
                    break
                if is_too_close(centre, taken, min_gap):
                    continue

                # The best ranked faces are usually neighbours on the same patch,
                # which would all give the same answer, so test one per patch
                patch = (
                    int(centre.x // test_spacing),
                    int(centre.y // test_spacing),
                    int(centre.z // test_spacing),
                )
                if patch in tested_patches:
                    continue
                tested_patches.add(patch)

                tries += 1
                base = Vector((base_x, centre.y, 0.0))
                fit = gate_fit_score(obj, base, centre, gate_radius)
                if fit > best_fit_seen:
                    best_fit_seen = fit

                if fit >= min_fit:
                    picked.append((centre, side))
                    taken.append(centre)
                elif fit >= fallback_fit:
                    backups.append((fit, centre, side))

            if side < 0:
                side_name = "far"
            else:
                side_name = "near"
            debug(f"{side_name} side: {len(ranked)} faces could face the gate, "
                  f"{tries} patches tested, best fit = {best_fit_seen:.2f}")

    # if not enough perfect gates, use the best of the backups
    if len(picked) < count and backups:
        backups.sort(key=lambda backup: backup[0], reverse=True)
        for fit, tip, side in backups:
            if len(picked) >= count:
                break
            if is_too_close(tip, taken, min_gap):
                continue
            debug("using a backup gate, fit =", round(fit, 2))
            picked.append((tip, side))
            taken.append(tip)

    debug(f"extra gates for '{obj.name}': placed {len(picked)} of {count}")
    return picked
