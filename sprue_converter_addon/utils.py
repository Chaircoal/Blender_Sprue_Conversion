## Utility functions used throughout the addon
## Note: (""" Are documentation strings for Blender's auto-doc system, not comments """)

import bpy
import bmesh
from mathutils import Vector

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


def apply_heatmap_vertex_colors(obj, curvatures):
    """
    Write per-face curvature into a vertex colour attribute so it's
    visible in the viewport (Material Preview or Rendered mode).
    """
    mesh = obj.data

    # Blender 3.x uses attributes for vertex colours
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

    # Tell Blender to display this colour attribute
    mesh.color_attributes.render_color_index = mesh.color_attributes.find(color_layer_name)
    mesh.color_attributes.active_color_index = mesh.color_attributes.find(color_layer_name)


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