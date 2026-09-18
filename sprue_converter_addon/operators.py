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

        # Check if the active mesh is manifold
        manifold_result = utils.check_mesh_manifold(bm, obj)

        # Store non-manifold results for later use
        settings.is_watertight = manifold_result["is_watertight"]
        settings.open_edge_count = len(manifold_result["open_edge_indices"])
        settings.non_manifold_edge_count = len(manifold_result["non_manifold_edge_indices"])
        settings.non_manifold_vert_count = len(manifold_result["non_manifold_vert_indices"])
        settings.incontiguous_edge_count = len(manifold_result["incontiguous_edge_indices"])
        settings.zero_edge_count = len(manifold_result["zero_edge_indices"])
        settings.zero_face_count = len(manifold_result["zero_face_indices"])
        settings.overhang_face_count = len(manifold_result["overhang_face_indices"])
        settings.thin_wall_count = len(manifold_result["thin_wall_indices"])
        settings.nonplanar_face_count = len(manifold_result["nonplanar_face_indices"])

        obj["_sprue_open_edge_indices"] = manifold_result["open_edge_indices"]
        obj["_sprue_non_manifold_edge_indices"] = manifold_result["non_manifold_edge_indices"]
        obj["_sprue_non_manifold_vert_indices"] = manifold_result["non_manifold_vert_indices"]
        obj["_sprue_incontiguous_edge_indices"] = manifold_result["incontiguous_edge_indices"]
        obj["_sprue_zero_edge_indices"] = manifold_result["zero_edge_indices"]
        obj["_sprue_zero_face_indices"] = manifold_result["zero_face_indices"]
        obj["_sprue_overhang_face_indices"] = manifold_result["overhang_face_indices"]
        obj["_sprue_thin_wall_indices"] = manifold_result["thin_wall_indices"]
        obj["_sprue_nonplanar_face_indices"] = manifold_result["nonplanar_face_indices"]

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


class SPRUE_OT_StartPriorityPaint(bpy.types.Operator):
    """Create the gate-priority vertex group (if needed) and enter Weight Paint mode to brush it on"""
    bl_idname = "sprue.start_priority_paint"
    bl_label = "Paint gate priority"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'OBJECT'

    def execute(self, context):
        obj = context.active_object

        vg = utils.ensure_priority_vertex_group(obj)
        obj.vertex_groups.active_index = vg.index

        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')

        # Sensible brush defaults so the first stroke behaves predictably:
        # full-strength brush, painting toward priority = 1.0.
        # NOTE: as of Blender 5.0, unified_paint_settings lives on the
        # mode-specific Paint struct (tool_settings.weight_paint), not on
        # ToolSettings directly.
        tool_settings = context.scene.tool_settings
        wp = tool_settings.weight_paint
        if wp:
            ups = wp.unified_paint_settings
            ups.use_unified_strength = True
            ups.strength = 1.0
            if wp.brush:
                wp.brush.blend = 'MIX'
                wp.brush.strength = 1.0
        tool_settings.vertex_group_weight = 1.0  # value new strokes paint with

        self.report(
            {'INFO'},
            "Weight Paint mode: brush on gate-priority areas. "
            "Red = high priority, Blue = low. Lower the 'Weight' value in the "
            "tool header (or hold Ctrl to erase) to paint lower-priority areas."
        )
        return {'FINISHED'}


class SPRUE_OT_FinishPriorityPaint(bpy.types.Operator):
    """Leave Weight Paint mode and store the painted priority values"""
    bl_idname = "sprue.finish_priority_paint"
    bl_label = "Finish painting"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'WEIGHT_PAINT'

    def execute(self, context):
        obj = context.active_object
        settings = context.scene.sprue_settings

        bpy.ops.object.mode_set(mode='OBJECT')

        values = utils.get_priority_values(obj)
        obj["_sprue_priority"] = values

        painted = sum(1 for v in values if v > 0.001)
        settings.last_priority_painted = painted

        self.report(
            {'INFO'},
            f"Priority map saved — {painted} of {len(values)} vertex(es) have priority > 0."
        )
        return {'FINISHED'}


class SPRUE_OT_ClearPriorityPaint(bpy.types.Operator):
    """Remove the gate-priority vertex group and stored values"""
    bl_idname = "sprue.clear_priority_paint"
    bl_label = "Clear priority map"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and obj.type == 'MESH'
            and (utils.PRIORITY_VG_NAME in obj.vertex_groups or "_sprue_priority" in obj)
        )

    def execute(self, context):
        obj = context.active_object
        settings = context.scene.sprue_settings

        vg = obj.vertex_groups.get(utils.PRIORITY_VG_NAME)
        if vg is not None:
            obj.vertex_groups.remove(vg)
        if "_sprue_priority" in obj:
            del obj["_sprue_priority"]

        settings.last_priority_painted = 0
        self.report({'INFO'}, "Priority map cleared.")
        return {'FINISHED'}


class SPRUE_OT_ClearAll(bpy.types.Operator):
    """Remove all sprue visualisation objects and stored data"""
    bl_idname = "sprue.clear_all"
    bl_label = "Clear all"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH':
            for key in ["_sprue_curvatures", "_sprue_candidates", "_sprue_priority"]:
                if key in obj:
                    del obj[key]
            if "SprueCurvature" in obj.data.attributes:
                obj.data.attributes.remove(obj.data.attributes["SprueCurvature"])
            priority_vg = obj.vertex_groups.get(utils.PRIORITY_VG_NAME)
            if priority_vg is not None:
                obj.vertex_groups.remove(priority_vg)

        for ob in list(bpy.data.objects):
            if ob.name.startswith(("_SpruePlane_", "_SprueBoolean_", "_SprueWall_", "_SprueBridge_", "_Gate_")):
                bpy.data.objects.remove(ob, do_unlink=True)

        settings = context.scene.sprue_settings
        settings.heatmap_visible = False
        settings.last_island_count = 0
        settings.last_candidate_count = 0
        settings.last_priority_painted = 0
        self.report({'INFO'}, "All sprue data cleared.")
        return {'FINISHED'}


class SPRUE_OT_BuildSprueFrame(bpy.types.Operator):
    """
    Lay selected mesh pieces out in a grid, orienting each one so its painted
    gate-priority vertices land on a shared horizontal plane (preferring the
    rotation that leaves the least surface area vertical), build a rectangular
    outer runner frame, surround each piece with its own individual runner
    wall ring so a gate can be attached from any side, and attach gate stubs
    at each piece's painted priority location.
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

        cols = math.ceil(math.sqrt(len(pieces)))
        spacing = settings.piece_spacing
        min_weight = settings.gate_priority_min_weight

        # Step 1. Orient each piece so its painted gate-priority vertices end
        # up coplanar on a shared horizontal plane (world Z), preferring the
        # rotation that leaves the least surface area vertical. Pieces with
        # no painted priority are just oriented for minimum vertical area.
        piece_info = []
        any_missing_priority = False

        for obj in pieces:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            # Bake any pre-existing rotation/scale so local mesh data reflects
            # the piece's actual current shape.
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

            bm = utils.get_bmesh(obj)
            axis, plane_point_local, has_priority = utils.compute_gate_plane_axis(
                obj, bm, min_weight=min_weight
            )
            if obj.mode != 'EDIT':
                bm.free()

            if not has_priority:
                any_missing_priority = True

            target = Vector((0.0, 0.0, 1.0))
            if axis.dot(target) < 0:
                axis = -axis
            quat = axis.rotation_difference(target)

            # Predict where the gate plane will land in local space once this
            # rotation is baked in, so we can zero it out to Z=0 below.
            rotated_plane_z = (quat @ plane_point_local).z

            obj.rotation_mode = 'QUATERNION'
            obj.rotation_quaternion = quat
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

            piece_info.append({
                'obj': obj,
                'size': (obj.dimensions.x, obj.dimensions.y),
                'plane_z': rotated_plane_z,
            })

        if any_missing_priority:
            self.report(
                {'WARNING'},
                "One or more pieces have no painted gate priority; those were "
                "oriented for minimum vertical area instead."
            )

        # Position each piece in a grid, cancelling out its own Z so every
        # piece's gate plane lands at world Z=0 -- the same plane the runner
        # frame sits on.
        max_cell_x = max(p['size'][0] for p in piece_info)
        max_cell_y = max(p['size'][1] for p in piece_info)
        cell_x = max_cell_x + spacing
        cell_y = max_cell_y + spacing

        for idx, info in enumerate(piece_info):
            obj = info['obj']
            row = idx // cols
            col = idx % cols
            target_x = col * cell_x
            target_y = row * cell_y

            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            obj.location.z = -info['plane_z']

            bbox_centre_x = (obj.bound_box[0][0] + obj.bound_box[6][0]) / 2
            bbox_centre_y = (obj.bound_box[0][1] + obj.bound_box[6][1]) / 2
            obj.location.x = target_x - bbox_centre_x + cell_x / 2
            obj.location.y = target_y - bbox_centre_y + cell_y / 2

        # Step 2. Compute outer frame bounds from the combined world-space
        # bounding box of all pieces.
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
        frame_z = 0.0

        x_min = min(xs) - pad
        x_max = max(xs) + pad
        y_min = min(ys) - pad
        y_max = max(ys) + pad

        # Step 3. Build the outer frame mesh.
        frame_bm = bmesh.new()
        utils.make_frame_mesh(frame_bm, x_min, x_max, y_min, y_max, fw, fh)

        frame_mesh = bpy.data.meshes.new("Sprue_Frame_Mesh")
        frame_bm.to_mesh(frame_mesh)
        frame_bm.free()
        frame_mesh.update()

        frame_obj = bpy.data.objects.new("Sprue_Frame", frame_mesh)
        frame_obj.location = (0, 0, frame_z)
        context.collection.objects.link(frame_obj)

        # Step 4. Surround each piece with its own individual runner wall
        # ring so a gate can be attached from any side, then bridge that ring
        # back into the main outer frame.
        piece_wall_pad = settings.piece_wall_padding
        pw = settings.piece_wall_width
        ph = settings.piece_wall_height

        wall_objects = []
        bridge_objects = []
        piece_bounds = {}

        for idx, obj in enumerate(pieces):
            world_verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
            pxs = [v.x for v in world_verts]
            pys = [v.y for v in world_verts]
            px_min, px_max = min(pxs) - piece_wall_pad, max(pxs) + piece_wall_pad
            py_min, py_max = min(pys) - piece_wall_pad, max(pys) + piece_wall_pad
            piece_bounds[obj.name] = (px_min, px_max, py_min, py_max)

            wall_bm = bmesh.new()
            utils.make_frame_mesh(wall_bm, px_min, px_max, py_min, py_max, pw, ph)
            wall_mesh = bpy.data.meshes.new(f"_SprueWall_{idx:02d}_Mesh")
            wall_bm.to_mesh(wall_mesh)
            wall_bm.free()
            wall_mesh.update()
            wall_obj = bpy.data.objects.new(f"_SprueWall_{idx:02d}_{obj.name}", wall_mesh)
            wall_obj.location = (0, 0, frame_z)
            context.collection.objects.link(wall_obj)
            wall_objects.append(wall_obj)

            # Bridge this ring to whichever outer-frame edge is nearest.
            wx_min, wx_max = px_min - pw, px_max + pw
            wy_min, wy_max = py_min - pw, py_max + pw

            gap_left = wx_min - x_min
            gap_right = x_max - wx_max
            gap_bottom = wy_min - y_min
            gap_top = y_max - wy_max
            min_gap = min(gap_left, gap_right, gap_bottom, gap_top)

            wall_x_mid = (wx_min + wx_max) / 2.0
            wall_y_mid = (wy_min + wy_max) / 2.0

            if min_gap == gap_left:
                bridge_from = Vector((wx_min, wall_y_mid, frame_z))
                bridge_to = Vector((x_min, wall_y_mid, frame_z))
            elif min_gap == gap_right:
                bridge_from = Vector((wx_max, wall_y_mid, frame_z))
                bridge_to = Vector((x_max, wall_y_mid, frame_z))
            elif min_gap == gap_bottom:
                bridge_from = Vector((wall_x_mid, wy_min, frame_z))
                bridge_to = Vector((wall_x_mid, y_min, frame_z))
            else:
                bridge_from = Vector((wall_x_mid, wy_max, frame_z))
                bridge_to = Vector((wall_x_mid, y_max, frame_z))

            bridge_obj = utils.add_runner_bar(
                context.collection, bridge_from, bridge_to, min(pw, fw), min(ph, fh),
                f"_SprueBridge_{idx:02d}_{obj.name}",
            )
            if bridge_obj:
                bridge_objects.append(bridge_obj)

        # Step 5. Attach each piece to its own wall ring with a gate stub at
        # each painted gate-priority region (or the best outward face if
        # nothing was painted).
        gate_objects = []
        max_gates = settings.max_gates_per_piece

        for idx, obj in enumerate(pieces):
            px_min, px_max, py_min, py_max = piece_bounds[obj.name]

            gate_infos = utils.find_gate_faces(
                obj, toward_direction=None, min_weight=min_weight, max_gates=max_gates
            )
            if not gate_infos:
                self.report({'WARNING'}, f"Could not find gate face for '{obj.name}', skipping.")
                continue

            for g, (face_center_world, face_normal_world) in enumerate(gate_infos):
                gate_base = utils.nearest_wall_point(
                    face_center_world, px_min, px_max, py_min, py_max, ph / 2.0
                )
                gate_tip = face_center_world

                gate_obj = utils.add_gate_cylinder(
                    context.collection,
                    gate_base,
                    gate_tip,
                    settings.gate_diameter,
                    f"_Gate_{idx:02d}_{g:02d}_{obj.name}",
                )
                if gate_obj:
                    gate_objects.append(gate_obj)

        # Step 6. Join the outer frame, all wall rings, bridges and gates
        # into one final Sprue_Frame object.
        to_join = wall_objects + bridge_objects + gate_objects
        if to_join:
            bpy.ops.object.select_all(action='DESELECT')
            frame_obj.select_set(True)
            for o in to_join:
                o.select_set(True)
            context.view_layer.objects.active = frame_obj
            bpy.ops.object.join()
            frame_obj = context.active_object
            frame_obj.name = "Sprue_Frame"

        # Step 7. Reselect pieces + frame for visibility.
        bpy.ops.object.select_all(action='DESELECT')
        for obj in pieces:
            obj.select_set(True)
        frame_obj.select_set(True)
        context.view_layer.objects.active = frame_obj

        self.report(
            {'INFO'},
            f"Sprue frame built with {len(pieces)} piece(s), "
            f"{len(wall_objects)} wall ring(s) and {len(gate_objects)} gate(s). "
            f"Object: 'Sprue_Frame'."
        )
        return {'FINISHED'}


class SPRUE_OT_SelectNonManifold(bpy.types.Operator):
    bl_idname = "sprue.select_non_manifold"
    bl_label = "Select Non-Manifold Elements"

    # Check if the object exists and has our custom data
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is not None and obj.type == 'MESH':
            return (
                "_sprue_open_edge_indices" in obj and
                "_sprue_non_manifold_edge_indices" in obj and
                "_sprue_non_manifold_vert_indices" in obj and
                "_sprue_incontiguous_edge_indices" in obj and
                "_sprue_zero_edge_indices" in obj and
                "_sprue_zero_face_indices" in obj and
                "_sprue_overhang_face_indices" in obj and
                "_sprue_thin_wall_indices" in obj and
                "_sprue_nonplanar_face_indices" in obj
            )
        return False

    def execute(self, context):
        obj = context.active_object
        open_edge_indices = obj["_sprue_open_edge_indices"]
        non_manifold_edge_indices = obj["_sprue_non_manifold_edge_indices"]
        non_manifold_vert_indices = obj["_sprue_non_manifold_vert_indices"]
        incontiguous_edge_indices = obj["_sprue_incontiguous_edge_indices"]
        zero_edge_indices = obj["_sprue_zero_edge_indices"]
        zero_face_indices = obj["_sprue_zero_face_indices"]
        overhang_face_indices = obj["_sprue_overhang_face_indices"]
        thin_wall_indices = obj["_sprue_thin_wall_indices"]
        nonplanar_face_indices = obj["_sprue_nonplanar_face_indices"]

        # change the active interaction mode to edit
        bpy.ops.object.mode_set(mode='EDIT')

        # set selection mode to edges and vertices (Verts = True, Edges = True, Faces = True)
        context.tool_settings.mesh_select_mode = (True, True, True)

        # get current bmesh
        bm = utils.get_bmesh(obj)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # deselect everything
        for edge in bm.edges:
            edge.select = False
        for vert in bm.verts:
            vert.select = False
        for face in bm.faces:
            face.select = False

        # loop through the list of problem areas and highlight them
        for idx in open_edge_indices:
            bm.edges[idx].select = True
        for idx in non_manifold_edge_indices:
            bm.edges[idx].select = True
        for idx in non_manifold_vert_indices:
            bm.verts[idx].select = True
        for idx in incontiguous_edge_indices:
            bm.edges[idx].select = True
        for idx in zero_edge_indices:
            bm.edges[idx].select = True
        for idx in zero_face_indices:
            bm.faces[idx].select = True
        for idx in overhang_face_indices:
            bm.faces[idx].select = True
        for idx in thin_wall_indices:
            bm.faces[idx].select = True
        for idx in nonplanar_face_indices:
            bm.faces[idx].select = True

        # update bmesh with new selection
        bmesh.update_edit_mesh(obj.data)

        self.report({'INFO'},"Selected Problem Areas")
        return {'FINISHED'}