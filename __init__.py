bl_info = {
    "name": "Sprue Tool",
    "author": "Cole Latrace",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Sprue Tool",
    "description": "Convert resin 3D models to injection-mold sprue layout. Suggests cut planes, lays out pieces, and builds a runner frame with gates.",
    "category": "Mesh",
}

import bpy
import bmesh
from mathutils import Vector
from bpy.props import (FloatProperty, BoolProperty, IntProperty)

#  Core geometry helpers (""" Are documentation strings for Blender's auto-doc system, not comments """)
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

#  Scene state (stored on the scene) -- UI settings and last analysis results
class SprueToolSettings(bpy.types.PropertyGroup):
    curvature_threshold: FloatProperty(
        name="Detail threshold",
        description="Curvature value above which faces are considered 'high detail' (avoid cutting)",
        default=0.25, min=0.0, max=1.0, step=1,
    )
    num_candidates: IntProperty(
        name="Max slice planes",
        description="How many candidate cut planes to suggest",
        default=6, min=1, max=20,
    )
    heatmap_visible: BoolProperty(
        name="Show heatmap",
        description="Display the curvature heatmap on the mesh",
        default=False,
    )
    last_island_count: IntProperty(default=0)
    last_candidate_count: IntProperty(default=0)

    # SPRUE FRAME SETTINGS (NEEDS TWEAKING MOST LIKELY)
    # - Can't get gates to orient properly yet, so this is a work in progress.
    frame_padding: FloatProperty(
        name="Frame padding",
        description="Gap between the outermost piece and the inner edge of the runner frame (Blender units)",
        default=0.5, min=0.1, max=5.0, step=1,
    )
    frame_width: FloatProperty(
        name="Runner width",
        description="Width (thickness in XY) of the rectangular runner frame bar (Blender units)",
        default=0.3, min=0.05, max=2.0, step=1,
    )
    frame_height: FloatProperty(
        name="Runner height",
        description="Height (Z thickness) of the runner frame bar (Blender units)",
        default=0.2, min=0.05, max=1.0, step=1,
    )
    gate_diameter: FloatProperty(
        name="Gate diameter",
        description="Diameter of the cylinder stub connecting each piece to the frame (Blender units)",
        default=0.12, min=0.02, max=0.5, step=1,
    )
    gate_length: FloatProperty(
        name="Gate length",
        description="Length of the gate stub from frame to piece surface (Blender units)",
        default=0.2, min=0.05, max=1.0, step=1,
    )
    piece_spacing: FloatProperty(
        name="Piece spacing",
        description="Minimum gap between pieces in the grid layout (Blender units)",
        default=0.4, min=0.1, max=3.0, step=1,
    )

#  OPERATORS
class SPRUE_OT_AnalyzeMesh(bpy.types.Operator):
    """Analyse the selected mesh: compute curvature heatmap and detect islands"""
    bl_idname = "sprue.analyze_mesh"
    bl_label = "Analyse mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == 'MESH'
        )

    def execute(self, context):
        obj = context.active_object
        settings = context.scene.sprue_settings

        bm = get_bmesh(obj)
        curvatures = compute_face_curvature(bm)

        # Store curvatures in a custom property for later use
        obj["_sprue_curvatures"] = curvatures

        # Island detection
        islands = find_islands(bm)
        settings.last_island_count = len(islands)

        if obj.mode != 'EDIT':
            bm.free()

        # Apply heatmap
        apply_heatmap_vertex_colors(obj, curvatures)
        settings.heatmap_visible = True

        # Switch viewport to show vertex colours
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'SOLID'
                        space.shading.color_type = 'VERTEX'

        msg = f"Analysis complete. Found {len(islands)} geometry island(s)."
        if len(islands) > 1:
            msg += " WARNING: disconnected geometry detected!"
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)

        return {'FINISHED'}


class SPRUE_OT_FindSlicePlanes(bpy.types.Operator):
    """Find candidate slice planes in low-curvature regions"""
    bl_idname = "sprue.find_slice_planes"
    bl_label = "Find slice planes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and "_sprue_curvatures" in obj
        )

    def execute(self, context):
        obj = context.active_object
        settings = context.scene.sprue_settings

        curvatures = list(obj["_sprue_curvatures"])
        bm = get_bmesh(obj)

        candidates = find_slice_candidates(
            bm, curvatures,
            threshold=settings.curvature_threshold,
            num_planes=settings.num_candidates,
        )

        if obj.mode != 'EDIT':
            bm.free()

        # Check each candidate for island risk and update acceptance
        bm2 = get_bmesh(obj)
        for c in candidates:
            creates_island = simulate_cut_creates_island(bm2, c['value'])
            if creates_island:
                c['accepted'] = False
                c['island_risk'] = True
            else:
                c['island_risk'] = False
        if obj.mode != 'EDIT':
            bm2.free()

        # Store candidates on the object
        # Blender custom props can't store nested dicts directly - flatten to JSON  
        import json
        obj["_sprue_candidates"] = json.dumps(candidates)
        settings.last_candidate_count = len(candidates)

        # Visualise planes as empty objects (plain axes, thin)
        self._clear_visualisers(context)
        for i, c in enumerate(candidates):
            bpy.ops.object.empty_add(
                type='SINGLE_ARROW',
                location=(0, 0, c['value']),
                rotation=(0, 0, 0),
            )
            plane_empty = context.active_object
            plane_empty.name = f"_SpruePlane_{i:02d}"
            plane_empty.empty_display_size = obj.dimensions.x * 0.6

            # Colour by acceptance
            if c.get('island_risk'):
                plane_empty.color = (1.0, 0.2, 0.2, 1.0)   # red
            elif c['accepted']:
                plane_empty.color = (0.2, 0.9, 0.3, 1.0)   # green
            else:
                plane_empty.color = (1.0, 0.8, 0.1, 1.0)   # yellow

            plane_empty.show_name = True
            label = "OK" if c['accepted'] else ("ISLAND RISK" if c.get('island_risk') else "HIGH DETAIL")
            plane_empty.name = f"_SpruePlane_{i:02d}_{label}_z{c['value']:.3f}"

        # Reselect the original object
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        accepted = sum(1 for c in candidates if c['accepted'])
        self.report(
            {'INFO'},
            f"Found {len(candidates)} plane(s). {accepted} safe to cut, "
            f"{len(candidates)-accepted} flagged."
        )
        return {'FINISHED'}

    def _clear_visualisers(self, context):
        for ob in list(bpy.data.objects):
            if ob.name.startswith("_SpruePlane_"):
                bpy.data.objects.remove(ob, do_unlink=True)


class SPRUE_OT_AcceptPlane(bpy.types.Operator):
    """Bisect the mesh at the slice plane and separate into two objects"""
    bl_idname = "sprue.accept_plane"
    bl_label = "Apply cut"
    bl_options = {'REGISTER', 'UNDO'}

    plane_index: IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and "_sprue_candidates" in obj

    def execute(self, context):
        import json
        obj = context.active_object
        candidates = json.loads(obj["_sprue_candidates"])

        if self.plane_index >= len(candidates):
            self.report({'ERROR'}, "Plane index out of range.")
            return {'CANCELLED'}

        c = candidates[self.plane_index]
        z = c['value']
        base_name = obj.name

        # - Step 1: duplicate the object so we end up with two clean halves (As individual objects)
        # Bisect the original to keep the UPPER half,
        # Bisect the duplicate to keep the LOWER half.

        # Duplicate
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.duplicate()
        obj_lower = context.active_object
        obj_lower.name = f"{base_name}_lower"

        # - Step 2: bisect original -> keep ABOVE the plane
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(
            plane_co=(0.0, 0.0, z),
            plane_no=(0.0, 0.0, 1.0),    # Z-axis normal = horizontal cut
            use_fill=True,               # cap the open face so the mesh stays solid
            clear_inner=True,            # remove everything BELOW the plane
            clear_outer=False,
            threshold=0.0001,
        )
        bpy.ops.object.mode_set(mode='OBJECT')
        obj.name = f"{base_name}_upper"

        # - Step 3: bisect duplicate -> keep BELOW the plane
        bpy.ops.object.select_all(action='DESELECT')
        obj_lower.select_set(True)
        context.view_layer.objects.active = obj_lower

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(
            plane_co=(0.0, 0.0, z),
            plane_no=(0.0, 0.0, 1.0),
            use_fill=True,               # cap the open face
            clear_inner=False,
            clear_outer=True,            # remove everything ABOVE the plane
            threshold=0.0001,
        )
        bpy.ops.object.mode_set(mode='OBJECT')

        # Step 4: leave both objects selected so the user can see them
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        obj_lower.select_set(True)
        context.view_layer.objects.active = obj

        self.report(
            {'INFO'},
            f"Cut at Z={z:.3f} — created '{obj.name}' and '{obj_lower.name}'."
        )
        return {'FINISHED'}


class SPRUE_OT_ClearHeatmap(bpy.types.Operator):
    """Remove the curvature heatmap from the mesh"""
    bl_idname = "sprue.clear_heatmap"
    bl_label = "Clear heatmap"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        settings = context.scene.sprue_settings
        if "SprueCurvature" in mesh.attributes:
            mesh.attributes.remove(mesh.attributes["SprueCurvature"])
        settings.heatmap_visible = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.color_type = 'MATERIAL'
        self.report({'INFO'}, "Heatmap cleared.")
        return {'FINISHED'}


class SPRUE_OT_ClearAll(bpy.types.Operator):
    """Remove all sprue visualisation objects and stored data"""
    bl_idname = "sprue.clear_all"
    bl_label = "Clear all"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH':
            for key in ["_sprue_curvatures", "_sprue_candidates"]:
                if key in obj:
                    del obj[key]
            if "SprueCurvature" in obj.data.attributes:
                obj.data.attributes.remove(obj.data.attributes["SprueCurvature"])

        for ob in list(bpy.data.objects):
            if ob.name.startswith("_SpruePlane_") or ob.name.startswith("_SprueBoolean_"):
                bpy.data.objects.remove(ob, do_unlink=True)

        context.scene.sprue_settings.heatmap_visible = False
        context.scene.sprue_settings.last_island_count = 0
        context.scene.sprue_settings.last_candidate_count = 0
        self.report({'INFO'}, "All sprue data cleared.")
        return {'FINISHED'}


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


class SPRUE_OT_BuildSprueFrame(bpy.types.Operator):
    """
    Lay selected mesh pieces flat in a grid, build a rectangular runner frame
    around them, and attach gate stubs at each piece's lowest-curvature outward face.
    Select all pieces you want on the sprue before running.
    """
    bl_idname = "sprue.build_frame"
    bl_label = "Build sprue frame"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        return len(meshes) >= 1

    def execute(self, context):
        import math
        settings = context.scene.sprue_settings

        pieces = [o for o in context.selected_objects if o.type == 'MESH']
        if not pieces:
            self.report({'ERROR'}, "Select at least one mesh object.")
            return {'CANCELLED'}

        # Step 1. Lay pieces flat and tile in a grid
        # Apply rotation so the largest face is Z-up, then tile on the XY plane.

        cols = math.ceil(math.sqrt(len(pieces)))
        spacing = settings.piece_spacing

        # First pass: orient flat and measure max extents per piece
        cell_sizes = []
        for obj in pieces:
            # Apply current transforms so dimensions are accurate
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            dims = obj.dimensions
            cell_sizes.append((dims.x, dims.y))

        # Compute grid cell size (use the largest piece as the cell template)
        max_cell_x = max(c[0] for c in cell_sizes)
        max_cell_y = max(c[1] for c in cell_sizes)
        cell_x = max_cell_x + spacing
        cell_y = max_cell_y + spacing

        # Position each piece
        for idx, obj in enumerate(pieces):
            row = idx // cols
            col = idx % cols
            target_x = col * cell_x
            target_y = row * cell_y

            # Move piece so its bottom (Z min) sits at Z=0, centred in its cell
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            # Centre piece so its Z midpoint sits at Z=0
            zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
            z_center = (min(zs) + max(zs)) / 2.0
            obj.location.z -= z_center

            # Centre in XY cell
            bbox_centre_x = (obj.bound_box[0][0] + obj.bound_box[6][0]) / 2
            bbox_centre_y = (obj.bound_box[0][1] + obj.bound_box[6][1]) / 2
            obj.location.x = target_x - bbox_centre_x + cell_x / 2
            obj.location.y = target_y - bbox_centre_y + cell_y / 2

        # Step 2. Compute frame bounds 
        # After placement, get the world-space bounding box of all pieces combined.

        all_world_verts = []
        for obj in pieces:
            mat = obj.matrix_world
            for v in obj.data.vertices:
                all_world_verts.append(mat @ v.co)

        xs = [v.x for v in all_world_verts]
        ys = [v.y for v in all_world_verts]

        pad  = settings.frame_padding
        fw   = settings.frame_width
        fh   = settings.frame_height

        # Inner edges of the frame (with padding from piece extents)
        x_min = min(xs) - pad
        x_max = max(xs) + pad
        y_min = min(ys) - pad
        y_max = max(ys) + pad

        # Frame centred at Z=0 to align with pieces
        frame_z = 0.0

        # Step 3. Build frame mesh
        frame_bm = bmesh.new()
        make_frame_mesh(frame_bm, x_min, x_max, y_min, y_max, fw, fh)

        frame_mesh = bpy.data.meshes.new("Sprue_Frame_Mesh")
        frame_bm.to_mesh(frame_mesh)
        frame_bm.free()
        frame_mesh.update()

        frame_obj = bpy.data.objects.new("Sprue_Frame", frame_mesh)
        frame_obj.location = (0, 0, frame_z)
        context.collection.objects.link(frame_obj)

        # Step 4. Add gate stubs 
        gate_objects = []
        frame_centre = Vector((
            (x_min + x_max) / 2,
            (y_min + y_max) / 2,
            frame_z,
        ))

        for idx, obj in enumerate(pieces):
            piece_centre = Vector((
                (obj.bound_box[0][0] + obj.bound_box[6][0]) / 2 + obj.location.x,
                (obj.bound_box[0][1] + obj.bound_box[6][1]) / 2 + obj.location.y,
                obj.location.z + obj.dimensions.z / 2,
            ))

            # Direction from piece centre toward nearest frame edge
            toward = piece_centre - frame_centre
            toward.z = 0  # keep horizontal
            if toward.length < 0.001:
                toward = Vector((1, 0, 0))

            gate_info = find_best_gate_face(obj, toward)

            if gate_info is None:
                self.report({'WARNING'}, f"Could not find gate face for '{obj.name}', skipping.")
                continue

            face_center_world, face_normal_world = gate_info

            # Step 5. Find where the gate meets the frame
            # Project face_center_world horizontally to the nearest inner face of the frame bar.  
            # The four inner edges in world XY are at x_min, x_max, y_min, y_max,
            # pick whichever is closest to the face centre so the gate runs the shortest possible path.
             
            fx, fy = face_center_world.x, face_center_world.y

            # Clamp gate Z to the frame's height range so it always touches a face of the bar rather than missing above or below it.
            half_fh  = fh / 2.0
            gate_z   = max(-half_fh, min(half_fh, face_center_world.z))

            dist_left   = fx - x_min
            dist_right  = x_max - fx
            dist_bottom = fy - y_min
            dist_top    = y_max - fy

            min_dist = min(dist_left, dist_right, dist_bottom, dist_top)

            if   min_dist == dist_left:
                gate_base = Vector((x_min, fy,    gate_z))
            elif min_dist == dist_right:
                gate_base = Vector((x_max, fy,    gate_z))
            elif min_dist == dist_bottom:
                gate_base = Vector((fx,    y_min, gate_z))
            else:
                gate_base = Vector((fx,    y_max, gate_z))

            gate_tip = face_center_world

            gate_obj = add_gate_cylinder(
                context.collection,
                gate_base,
                gate_tip,
                settings.gate_diameter,
                f"_Gate_{idx:02d}_{obj.name}",
            )
            if gate_obj:
                gate_objects.append(gate_obj)

        # Step 6. Join gates into the frame object 
        if gate_objects:
            bpy.ops.object.select_all(action='DESELECT')
            frame_obj.select_set(True)
            for g in gate_objects:
                g.select_set(True)
            context.view_layer.objects.active = frame_obj
            bpy.ops.object.join()
            frame_obj = context.active_object
            frame_obj.name = "Sprue_Frame"

        # Step 7. Reselect pieces + frame for visibility
        bpy.ops.object.select_all(action='DESELECT')
        for obj in pieces:
            obj.select_set(True)
        frame_obj.select_set(True)
        context.view_layer.objects.active = frame_obj

        self.report(
            {'INFO'},
            f"Sprue frame built with {len(pieces)} piece(s) and "
            f"{len(gate_objects)} gate(s). Object: 'Sprue_Frame'."
        )
        return {'FINISHED'}


#  PANEL
class SPRUE_PT_MainPanel(bpy.types.Panel):
    bl_label = "Sprue Tool"
    bl_idname = "SPRUE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Sprue Tool"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sprue_settings
        obj = context.active_object

        # Object status
        box = layout.box()
        box.label(text="Active object", icon='MESH_DATA')
        if obj and obj.type == 'MESH':
            box.label(text=obj.name, icon='CHECKMARK')
            row = box.row()
            row.label(text=f"Verts: {len(obj.data.vertices)}")
            row.label(text=f"Faces: {len(obj.data.polygons)}")
        else:
            box.label(text="Select a mesh object", icon='ERROR')

        layout.separator()

        # Step 1: Analysis
        box = layout.box()
        box.label(text="Step 1 — Analyse", icon='FORCE_MAGNETIC')
        col = box.column(align=True)
        col.prop(settings, "curvature_threshold", slider=True)
        col.operator("sprue.analyze_mesh", icon='HIDE_OFF')

        if settings.last_island_count > 0:
            row = box.row()
            if settings.last_island_count > 1:
                row.alert = True
                row.label(
                    text=f"⚠ {settings.last_island_count} islands detected!",
                    icon='ERROR'
                )
            else:
                row.label(text="✓ 1 connected island (good)", icon='CHECKMARK')

        if settings.heatmap_visible:
            box.operator("sprue.clear_heatmap", icon='HIDE_ON')
            box.label(
                text="Green = safe to cut  |  Red = avoid",
                icon='INFO'
            )

        layout.separator()

        # Step 2: Slice planes
        box = layout.box()
        box.label(text="Step 2 — Slice planes", icon='MOD_BOOLEAN')
        col = box.column(align=True)
        col.prop(settings, "num_candidates")
        has_curvatures = obj is not None and "_sprue_curvatures" in (obj or {})
        col.enabled = has_curvatures
        col.operator("sprue.find_slice_planes", icon='MESH_PLANE')

        if settings.last_candidate_count > 0:
            box.label(text=f"{settings.last_candidate_count} plane(s) shown in scene")
            box.label(text="Green = safe  Yellow = review  Red = risky")

        layout.separator()

        # Step 3: Apply cuts
        import json
        has_candidates = obj is not None and "_sprue_candidates" in (obj or {})
        if has_candidates:
            candidates = json.loads(obj["_sprue_candidates"])
            box = layout.box()
            box.label(text="Step 3 — Apply cuts", icon='MOD_BOOLEAN')
            for i, c in enumerate(candidates):
                row = box.row(align=True)
                if c.get('island_risk'):
                    row.alert = True
                    icon = 'ERROR'
                    label = f"Z={c['value']:.3f}  ISLAND RISK"
                elif c['accepted']:
                    icon = 'CHECKMARK'
                    label = f"Z={c['value']:.3f}  safe"
                else:
                    icon = 'QUESTION'
                    label = f"Z={c['value']:.3f}  review"
                row.label(text=label, icon=icon)
                op = row.operator("sprue.accept_plane", text="Bisect & Separate", icon='MOD_BOOLEAN')
                op.plane_index = i

        layout.separator()

        # ── Step 4: Build sprue frame 
        box = layout.box()
        box.label(text="Step 4 — Build sprue frame", icon='MESH_GRID')
        box.label(text="Select all sliced pieces, then:", icon='INFO')

        col = box.column(align=True)
        col.prop(settings, "piece_spacing")
        col.prop(settings, "frame_padding")
        col.separator()
        col.prop(settings, "frame_width")
        col.prop(settings, "frame_height")
        col.separator()
        col.prop(settings, "gate_diameter")
        col.prop(settings, "gate_length")

        sel_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        row = box.row()
        row.scale_y = 1.4
        if sel_meshes:
            row.operator("sprue.build_frame", icon='MESH_GRID',
                         text=f"Build frame ({len(sel_meshes)} piece(s))")
        else:
            row.enabled = False
            row.operator("sprue.build_frame", icon='MESH_GRID',
                         text="Select pieces first")

        layout.separator()

        # Utilities 
        box = layout.box()
        box.label(text="Utilities", icon='TOOL_SETTINGS')
        box.operator("sprue.clear_all", icon='TRASH')


#  REGISTRATION
CLASSES = [
    SprueToolSettings,
    SPRUE_OT_AnalyzeMesh,
    SPRUE_OT_FindSlicePlanes,
    SPRUE_OT_AcceptPlane,
    SPRUE_OT_ClearHeatmap,
    SPRUE_OT_ClearAll,
    SPRUE_OT_BuildSprueFrame,
    SPRUE_PT_MainPanel,
]

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sprue_settings = bpy.props.PointerProperty(type=SprueToolSettings)

def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.sprue_settings

if __name__ == "__main__":
    register()
