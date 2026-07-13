## Operators that are used throughout the conversion process

import bpy
import bmesh
from mathutils import Vector
from bpy.props import IntProperty
from . import properties, utils

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

        bm = utils.get_bmesh(obj)
        curvatures = utils.compute_face_curvature(bm)

        # Store curvatures in a custom property for later use
        obj["_sprue_curvatures"] = curvatures

        # Island detection
        islands = utils.find_islands(bm)
        settings.last_island_count = len(islands)

        if obj.mode != 'EDIT':
            bm.free()

        # Apply heatmap
        utils.apply_heatmap_vertex_colors(obj, curvatures)
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
        bm = utils.get_bmesh(obj)

        candidates = utils.find_slice_candidates(
            bm, curvatures,
            threshold=settings.curvature_threshold,
            num_planes=settings.num_candidates,
        )

        if obj.mode != 'EDIT':
            bm.free()

        # Check each candidate for island risk and update acceptance
        bm2 = utils.get_bmesh(obj)
        for c in candidates:
            creates_island = utils.simulate_cut_creates_island(bm2, c['value'])
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

        pad = settings.frame_padding
        fw = settings.frame_width
        fh = settings.frame_height

        # Inner edges of the frame (with padding from piece extents)
        x_min = min(xs) - pad
        x_max = max(xs) + pad
        y_min = min(ys) - pad
        y_max = max(ys) + pad

        # Frame centred at Z=0 to align with pieces
        frame_z = 0.0

        # Step 3. Build frame mesh
        frame_bm = bmesh.new()
        utils.make_frame_mesh(frame_bm, x_min, x_max, y_min, y_max, fw, fh)

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

            gate_info = utils.find_best_gate_face(obj, toward)

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
            half_fh = fh / 2.0
            gate_z = max(-half_fh, min(half_fh, face_center_world.z))

            dist_left = fx - x_min
            dist_right = x_max - fx
            dist_bottom = fy - y_min
            dist_top = y_max - fy

            min_dist = min(dist_left, dist_right, dist_bottom, dist_top)

            if min_dist == dist_left:
                gate_base = Vector((x_min, fy, gate_z))
            elif min_dist == dist_right:
                gate_base = Vector((x_max, fy, gate_z))
            elif min_dist == dist_bottom:
                gate_base = Vector((fx, y_min, gate_z))
            else:
                gate_base = Vector((fx, y_max, gate_z))

            gate_tip = face_center_world

            gate_obj = utils.add_gate_cylinder(
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