import bpy
import bmesh
from mathutils import Vector
from . import utils

class SPRUE_OT_BuildSprueLayout(bpy.types.Operator):
    bl_idname = "sprue.build_sprue_layout"
    bl_label = "Build the layout of the sprue"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        has_meshes = any(o.type == 'MESH' for o in context.scene.objects)
        return context.mode == 'OBJECT' and has_meshes

    def execute(self, context):
        settings = context.scene.sprue_settings
        min_weight = settings.gate_priority_min_weight

        sprue_height = 30 # height in mm
        diameter = 10 # This is a guess but can be adjusted later
        runner_spacing = 5 # Change to settings.piece_spacings later. this is for testing
        max_row_width = 90.0 # how far a row can extend from the sprue before wrapping
        gate_length = runner_spacing / 2 # how far a gate sticks out past the part's edge
        gate_objects = [] # kept so we can join/connect them later
        placed_bounds = [] # world-space (x_min, x_max, y_min, y_max) of every placed part
        runner_width = 3 # runner thickness in X/Y (value must be under runner_spacing)
        runner_height = 3 # runner thickness in Z
        # feeder_width = 1 # feeder thickness in X/Y
        # feeder_height = 1 # runner thickness in Z
        feeder_clearance = 1.0 # how close a feeder may get to a part
        use_row_channels = False # turn on later for quadrants with several rows
        runner_objects = [] # kept so we can join them later
        feeder_jobs = [] # (gate_base, channel_y) for every part
        channels = [] # (side_x, channel_y), one per row channel (no duplicates)

        # Get all parts sorted by volume, largest first
        # Done BEFORE making the cylinder so the cylinder isn't counted as a part
        parts_list = utils.get_all_part_volume()

        # Create the central injection point
        utils.add_gate_cylinder(
            context.collection,
            Vector((0, 0, 0)),
            Vector((0, 0, sprue_height)),
            diameter,
            "Main_Injection_Sprue",
        )

        # signs of each quadrant of the sprue
        quad_signs = {
            1: Vector((1.0, 1.0, 0.0)),
            2: Vector((-1.0, 1.0, 0.0)),
            3: Vector((-1.0, -1.0, 0.0)),
            4: Vector((1.0, -1.0, 0.0)),
        }

        # Sort parts into different quadrants
        # known largest working area is 240x180mm
        distributed = utils.distribute_parts_to_quadrants(parts_list)
        missing_priority = False

        for quad_num, quad_parts in distributed.items():
            sign = quad_signs[quad_num]

            # Start the layout just outside the injection cylinder
            # Offsets are always positive, the sign flips them into the quadrant
            start = diameter / 2 + runner_spacing
            offset_x = start
            offset_y = start
            row_height = 0.0 # tallest part in the current row (used to move to the next row)

            for part_obj, volume in quad_parts:
                # Orient part so painted area is facing along the x-axis
                face_dir = Vector((-sign.x, 0.0, 0.0))
                painted_point, has_priority = utils.orient_part(context, part_obj, min_weight, face_dir)
                plane_z = painted_point.z
                if not has_priority:
                    missing_priority = True

                # Get the part's size and centre from its bounding box
                mn, mx = utils.local_bounds(part_obj)
                dim_x, dim_y = mx.x - mn.x, mx.y - mn.y
                centre_x = (mn.x + mx.x) / 2
                centre_y = (mn.y + mx.y) / 2

                # If this part would go past the work area, start a new row
                # (row_height > 0 stops an empty row from wrapping)
                if offset_x + dim_x > max_row_width and row_height > 0:
                    offset_y += row_height + runner_spacing
                    offset_x = start
                    row_height = 0.0

                # Where the middle of the part should sit, mirrored into this quadrant
                target_x = (offset_x + dim_x / 2) * sign.x
                target_y = (offset_y + dim_y / 2) * sign.y

                # move part and place painted spot at z=0
                part_obj.location = Vector((
                    target_x - centre_x,
                    target_y - centre_y,
                    -plane_z,
                ))

                # remember where this part ended up in world space
                placed_bounds.append((
                    mn.x + part_obj.location.x,
                    mx.x + part_obj.location.x,
                    mn.y + part_obj.location.y,
                    mx.y + part_obj.location.y
                ))

                # create the gate stub from the object from priority location
                gate_tip = painted_point + part_obj.location

                # The edge of the part's bounding box that faces the injection point
                edge_x = (mn.x if sign.x > 0 else mx.x) + part_obj.location.x

                # Gate runs from just outside that edge (in the gap) to the painted spot
                gate_base = Vector((edge_x + face_dir.x * gate_length, gate_tip.y, 0.0))

                print("gate diameter used:", settings.gate_diameter)

                gate_obj = utils.add_gate_cylinder(
                    context.collection,
                    gate_base,
                    gate_tip,
                    settings.gate_diameter,
                    f"_gate_{part_obj.name}"
                )
                if gate_obj:
                    gate_objects.append(gate_obj)

                # The row channel is the free band just before this part's row on the injection points side
                feeder_jobs.append((gate_base, sign.y))

                # Several parts share one channel, so only remember each channel once
                if use_row_channels:
                    channel_y = (offset_y - runner_spacing / 2) * sign.y
                    channel = (sign.x, channel_y)
                    if channel not in channels:
                        channels.append(channel)

                # Move along the row for the next part
                offset_x += dim_x + runner_spacing
                row_height = max(row_height, dim_y)

        # building the outer sprue
        # work out the outer bounds of everything on the sprue
        frame_padding = 5 # gap between the outermost part and the frame (swap for settings.frame_padding later)
        frame_width = 4 # bar thickness in X/Y (swap for settings.frame_width later)
        frame_height = 3 # bar thickness in Z (swap for settings.frame_height later)

        # Start with the injection cylinder so the frame always surrounds it,
        # even if a quadrant is empty
        x_min = -diameter / 2
        x_max = diameter / 2
        y_min = -diameter / 2
        y_max = diameter / 2

        # Grow the bounds to include every part
        for part_x_min, part_x_max, part_y_min, part_y_max in placed_bounds:
            x_min = min(x_min, part_x_min)
            x_max = max(x_max, part_x_max)
            y_min = min(y_min, part_y_min)
            y_max = max(y_max, part_y_max)

        # Push the bounds outward so the frame sits clear of the parts and gates
        x_min -= frame_padding
        x_max += frame_padding
        y_min -= frame_padding
        y_max += frame_padding

        # build the 4 bars of the outer sprue
        frame_bm = bmesh.new()
        utils.make_frame_mesh(frame_bm, x_min, x_max, y_min, y_max, frame_width, frame_height)

        frame_mesh = bpy.data.meshes.new("Sprue_Frame_Mesh")
        frame_bm.to_mesh(frame_mesh)
        frame_bm.free()
        frame_mesh.update()

        frame_obj = bpy.data.objects.new("Sprue_Frame", frame_mesh)
        context.collection.objects.link(frame_obj)

        # Built the runners within the sprue using channels
        # Runners overlap the frame bars by half their width so they join them
        frame_left = x_min - frame_width / 2
        frame_right = x_max + frame_width / 2
        frame_bottom = y_min - frame_height / 2
        frame_top = y_max + frame_height / 2

        # Y trunk: down the middle, between the left and right quadrants
        y_trunk = utils.add_runner_bar(
            context.collection,
            Vector((0.0, frame_bottom, 0.0)),
            Vector((0.0, frame_top, 0.0)),
            runner_width,
            runner_height,
            "_runner_trunk_y"
        )
        if y_trunk:
            runner_objects.append(y_trunk)

        # X trunk: across the middle, between the top and bottom quadrants
        x_trunk = utils.add_runner_bar(
            context.collection,
            Vector((frame_left, 0.0, 0.0)),
            Vector((frame_right, 0.0, 0.0)),
            runner_width,
            runner_height,
            "runner_trunk_x"
        )
        if x_trunk:
            runner_objects.append(x_trunk)

        # Feeders: one bar per part, from the X trunk out to the frame,
        # passing through the gate base and stopping short of any part in the way
        for feeders_num, (gate_base, side_y) in enumerate(feeder_jobs):
            feeder_x = gate_base.x
            start_y = gate_base.y

            # The outer frame edge on this part's side
            if side_y > 0:
                outer_limit = frame_top
            else:
                outer_limit = frame_bottom

            # Outward end (toward the frame)
            outer_end_y = utils.find_feeder_end(
                feeder_x,
                start_y,
                side_y,
                outer_limit,
                placed_bounds,
                runner_width / 2,
                feeder_clearance
            )

            # inner end (toward the x trunk at y = 0)
            centre_end_y = utils.find_feeder_end(
                feeder_x,
                start_y,
                -side_y,
                0.0,
                placed_bounds,
                runner_width / 2,
                feeder_clearance
            )

            feeder_obj = utils.add_runner_bar(
                context.collection,
                Vector((feeder_x, centre_end_y, 0.0)),
                Vector((feeder_x, outer_end_y, 0.0)),
                runner_width / 2,
                runner_height / 2,
                f"_runner_feeder_{feeders_num:02d}"
            )
            if feeder_obj:
                runner_objects.append(feeder_obj)

        # Row channels: from the trunk out to the frame on this quadrant's side
        # off by default
        if use_row_channels:
            for channel_num, (side_x, channel_y) in enumerate(channels):
                if side_x > 0:
                    channel_end_x = frame_right
                else:
                    channel_end_x = frame_left

                channel_obj = utils.add_runner_bar(
                    context.collection,
                    Vector((0.0, channel_y, 0.0)),
                    Vector((channel_end_x, channel_y, 0.0)),
                    runner_width,
                    runner_height,
                    f"_runner_channel_{channel_num:02d}"
                )
                if channel_obj:
                    runner_objects.append(channel_obj)

        if missing_priority:
            self.report({'WARNING'}, "Some parts had no painted gate priority.")
        self.report({'INFO'}, f"Sprue built: {len(gate_objects)} gate(s), {len(runner_objects)} runner(s)")
        return {'FINISHED'}

        # class SPRUE_OT_BuildSprueFrame(bpy.types.Operator):
#     """
#     Lay selected mesh pieces out in a grid, orienting each one so its painted
#     gate-priority vertices land on a shared horizontal plane (preferring the
#     rotation that leaves the least surface area vertical), build a rectangular
#     outer runner frame, surround each piece with its own individual runner
#     wall ring so a gate can be attached from any side, and attach gate stubs
#     at each piece's painted priority location.
#     Select all pieces you want on the sprue before running.
#     """
#     bl_idname = "sprue.build_frame"
#     bl_label = "Build sprue frame"
#     bl_options = {'REGISTER', 'UNDO'}
#
#     @classmethod
#     def poll(cls, context):
#         meshes = [o for o in context.selected_objects if o.type == 'MESH']
#         return len(meshes) >= 1
#
#     def execute(self, context):
#         import math
#         settings = context.scene.sprue_settings
#
#         pieces = [o for o in context.selected_objects if o.type == 'MESH']
#         if not pieces:
#             self.report({'ERROR'}, "Select at least one mesh object.")
#             return {'CANCELLED'}
#
#         cols = math.ceil(math.sqrt(len(pieces)))
#         spacing = settings.piece_spacing
#         min_weight = settings.gate_priority_min_weight
#
#         # Step 1. Orient each piece so its painted gate-priority vertices end
#         # up coplanar on a shared horizontal plane (world Z), preferring the
#         # rotation that leaves the least surface area vertical. Pieces with
#         # no painted priority are just oriented for minimum vertical area.
#         piece_info = []
#         any_missing_priority = False
#
#         for obj in pieces:
#             bpy.ops.object.select_all(action='DESELECT')
#             obj.select_set(True)
#             context.view_layer.objects.active = obj
#
#             # Bake any pre-existing rotation/scale so local mesh data reflects
#             # the piece's actual current shape.
#             bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
#
#             bm = mesh_utils.get_bmesh(obj)
#             axis, plane_point_local, has_priority = utils.compute_gate_plane_axis(
#                 obj, bm, min_weight=min_weight
#             )
#             if obj.mode != 'EDIT':
#                 bm.free()
#
#             if not has_priority:
#                 any_missing_priority = True
#
#             target = Vector((0.0, 0.0, 1.0))
#             if axis.dot(target) < 0:
#                 axis = -axis
#             quat = axis.rotation_difference(target)
#
#             # Predict where the gate plane will land in local space once this
#             # rotation is baked in, so we can zero it out to Z=0 below.
#             rotated_plane_z = (quat @ plane_point_local).z
#
#             obj.rotation_mode = 'QUATERNION'
#             obj.rotation_quaternion = quat
#             bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
#
#             piece_info.append({
#                 'obj': obj,
#                 'size': (obj.dimensions.x, obj.dimensions.y),
#                 'plane_z': rotated_plane_z,
#             })
#
#         if any_missing_priority:
#             self.report(
#                 {'WARNING'},
#                 "One or more pieces have no painted gate priority; those were "
#                 "oriented for minimum vertical area instead."
#             )
#
#         # Position each piece in a grid, cancelling out its own Z so every
#         # piece's gate plane lands at world Z=0 -- the same plane the runner
#         # frame sits on.
#         max_cell_x = max(p['size'][0] for p in piece_info)
#         max_cell_y = max(p['size'][1] for p in piece_info)
#         cell_x = max_cell_x + spacing
#         cell_y = max_cell_y + spacing
#
#         for idx, info in enumerate(piece_info):
#             obj = info['obj']
#             row = idx // cols
#             col = idx % cols
#             target_x = col * cell_x
#             target_y = row * cell_y
#
#             bpy.ops.object.select_all(action='DESELECT')
#             obj.select_set(True)
#             context.view_layer.objects.active = obj
#
#             obj.location.z = -info['plane_z']
#
#             bbox_centre_x = (obj.bound_box[0][0] + obj.bound_box[6][0]) / 2
#             bbox_centre_y = (obj.bound_box[0][1] + obj.bound_box[6][1]) / 2
#             obj.location.x = target_x - bbox_centre_x + cell_x / 2
#             obj.location.y = target_y - bbox_centre_y + cell_y / 2
#
#         # Step 2. Compute outer frame bounds from the combined world-space
#         # bounding box of all pieces.
#         all_world_verts = []
#         for obj in pieces:
#             mat = obj.matrix_world
#             for v in obj.data.vertices:
#                 all_world_verts.append(mat @ v.co)
#
#         xs = [v.x for v in all_world_verts]
#         ys = [v.y for v in all_world_verts]
#
#         pad = settings.frame_padding
#         fw = settings.frame_width
#         fh = settings.frame_height
#         frame_z = 0.0
#
#         x_min = min(xs) - pad
#         x_max = max(xs) + pad
#         y_min = min(ys) - pad
#         y_max = max(ys) + pad
#
#         # Step 3. Build the outer frame mesh.
#         frame_bm = bmesh.new()
#         utils.make_frame_mesh(frame_bm, x_min, x_max, y_min, y_max, fw, fh)
#
#         frame_mesh = bpy.data.meshes.new("Sprue_Frame_Mesh")
#         frame_bm.to_mesh(frame_mesh)
#         frame_bm.free()
#         frame_mesh.update()
#
#         frame_obj = bpy.data.objects.new("Sprue_Frame", frame_mesh)
#         frame_obj.location = (0, 0, frame_z)
#         context.collection.objects.link(frame_obj)
#
#         # Step 4. Surround each piece with its own individual runner wall
#         # ring so a gate can be attached from any side, then bridge that ring
#         # back into the main outer frame.
#         piece_wall_pad = settings.piece_wall_padding
#         pw = settings.piece_wall_width
#         ph = settings.piece_wall_height
#
#         wall_objects = []
#         bridge_objects = []
#         piece_bounds = {}
#
#         for idx, obj in enumerate(pieces):
#             world_verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
#             pxs = [v.x for v in world_verts]
#             pys = [v.y for v in world_verts]
#             px_min, px_max = min(pxs) - piece_wall_pad, max(pxs) + piece_wall_pad
#             py_min, py_max = min(pys) - piece_wall_pad, max(pys) + piece_wall_pad
#             piece_bounds[obj.name] = (px_min, px_max, py_min, py_max)
#
#             wall_bm = bmesh.new()
#             utils.make_frame_mesh(wall_bm, px_min, px_max, py_min, py_max, pw, ph)
#             wall_mesh = bpy.data.meshes.new(f"_SprueWall_{idx:02d}_Mesh")
#             wall_bm.to_mesh(wall_mesh)
#             wall_bm.free()
#             wall_mesh.update()
#             wall_obj = bpy.data.objects.new(f"_SprueWall_{idx:02d}_{obj.name}", wall_mesh)
#             wall_obj.location = (0, 0, frame_z)
#             context.collection.objects.link(wall_obj)
#             wall_objects.append(wall_obj)
#
#             # Bridge this ring to whichever outer-frame edge is nearest.
#             wx_min, wx_max = px_min - pw, px_max + pw
#             wy_min, wy_max = py_min - pw, py_max + pw
#
#             gap_left = wx_min - x_min
#             gap_right = x_max - wx_max
#             gap_bottom = wy_min - y_min
#             gap_top = y_max - wy_max
#             min_gap = min(gap_left, gap_right, gap_bottom, gap_top)
#
#             wall_x_mid = (wx_min + wx_max) / 2.0
#             wall_y_mid = (wy_min + wy_max) / 2.0
#
#             if min_gap == gap_left:
#                 bridge_from = Vector((wx_min, wall_y_mid, frame_z))
#                 bridge_to = Vector((x_min, wall_y_mid, frame_z))
#             elif min_gap == gap_right:
#                 bridge_from = Vector((wx_max, wall_y_mid, frame_z))
#                 bridge_to = Vector((x_max, wall_y_mid, frame_z))
#             elif min_gap == gap_bottom:
#                 bridge_from = Vector((wall_x_mid, wy_min, frame_z))
#                 bridge_to = Vector((wall_x_mid, y_min, frame_z))
#             else:
#                 bridge_from = Vector((wall_x_mid, wy_max, frame_z))
#                 bridge_to = Vector((wall_x_mid, y_max, frame_z))
#
#             bridge_obj = utils.add_runner_bar(
#                 context.collection, bridge_from, bridge_to, min(pw, fw), min(ph, fh),
#                 f"_SprueBridge_{idx:02d}_{obj.name}",
#             )
#             if bridge_obj:
#                 bridge_objects.append(bridge_obj)
#
#         # Step 5. Attach each piece to its own wall ring with a gate stub at
#         # each painted gate-priority region (or the best outward face if
#         # nothing was painted).
#         gate_objects = []
#         max_gates = settings.max_gates_per_piece
#
#         for idx, obj in enumerate(pieces):
#             px_min, px_max, py_min, py_max = piece_bounds[obj.name]
#
#             gate_infos = utils.find_gate_faces(
#                 obj, toward_direction=None, min_weight=min_weight, max_gates=max_gates
#             )
#             if not gate_infos:
#                 self.report({'WARNING'}, f"Could not find gate face for '{obj.name}', skipping.")
#                 continue
#
#             for g, (face_center_world, face_normal_world) in enumerate(gate_infos):
#                 gate_base = utils.nearest_wall_point(
#                     face_center_world, px_min, px_max, py_min, py_max, ph / 2.0
#                 )
#                 gate_tip = face_center_world
#
#                 gate_obj = utils.add_gate_cylinder(
#                     context.collection,
#                     gate_base,
#                     gate_tip,
#                     settings.gate_diameter,
#                     f"_Gate_{idx:02d}_{g:02d}_{obj.name}",
#                 )
#                 if gate_obj:
#                     gate_objects.append(gate_obj)
#
#         # Step 6. Join the outer frame, all wall rings, bridges and gates
#         # into one final Sprue_Frame object.
#         to_join = wall_objects + bridge_objects + gate_objects
#         if to_join:
#             bpy.ops.object.select_all(action='DESELECT')
#             frame_obj.select_set(True)
#             for o in to_join:
#                 o.select_set(True)
#             context.view_layer.objects.active = frame_obj
#             bpy.ops.object.join()
#             frame_obj = context.active_object
#             frame_obj.name = "Sprue_Frame"
#
#         # Step 7. Reselect pieces + frame for visibility.
#         bpy.ops.object.select_all(action='DESELECT')
#         for obj in pieces:
#             obj.select_set(True)
#         frame_obj.select_set(True)
#         context.view_layer.objects.active = frame_obj
#
#         self.report(
#             {'INFO'},
#             f"Sprue frame built with {len(pieces)} piece(s), "
#             f"{len(wall_objects)} wall ring(s) and {len(gate_objects)} gate(s). "
#             f"Object: 'Sprue_Frame'."
#         )
#         return {'FINISHED'}
