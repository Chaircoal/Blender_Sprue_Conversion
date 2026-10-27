import bpy
import bmesh
from mathutils import Vector
from . import utils

class SPRUE_OT_BuildSprue(bpy.types.Operator):
    bl_idname = "sprue.build_sprue_layout"
    bl_label = "Build the layout of the sprue"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        has_meshes = any(utils.is_usable_part(o, context.view_layer) for o in context.view_layer.objects)
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
        feeder_clearance = 1.0 # how close a feeder may get to a part
        runner_objects = [] # kept so we can join them later
        feeder_jobs = [] # (gate_base, side_y, extend_dir_x) for every gate

        gate_volume_step = 1000.0 # part volume (mm^3) needed for each extra gate
        max_gates_per_part = 4
        min_gate_gap_ratio = 0.35 # closest two gates may be, as a fraction of the part's bounding box diagonal
        min_painted_gate_gap = 10.0 # closest a gate may be (mm) to another when it goes on a different painted region

        min_gate_fit = 0.75 # how much of the gate's end must sit on flat surface (1.0 = all of it)
        max_gate_slope = 1.0 # steepest a gate may be, as rise over run (1.0 = 45 degrees)
        fallback_gate_fit = 0.5 # extra gates settle for this if nothing fits as well as min_gate_fit
        gate_embed_depth = 0.5 # how far (mm) gates sink into the part so they are fully "on" it
        gate_radius = settings.gate_diameter / 2
        poor_fit_parts = [] # (part name, fit) for parts where gate 1 doesn't sit flat
        missing_gate_parts = [] # (part name, extra gates wanted, extra gates placed)

        gate_extend_max_distance = 15.0 # a gate this close (mm) to the Y trunk or outer frame runs straight into it
        gate_extend_overlap = 1.0 # how far (mm) the link bar goes into the wall so the two meshes overlap

        # Get all parts sorted by volume, largest first
        parts_list = utils.get_all_part_volume()

        # Create the central injection point
        injection_obj = utils.add_gate_cylinder(
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

                # Where the part's bounding box sits in world space
                world_min_x = mn.x + part_obj.location.x
                world_max_x = mx.x + part_obj.location.x
                world_min_y = mn.y + part_obj.location.y
                world_max_y = mx.y + part_obj.location.y

                # remember where this part ended up (used for the frame and for feeders)
                placed_bounds.append((world_min_x, world_max_x, world_min_y, world_max_y))

                # Which edge of the part faces the injection point depends on the quadrant
                if sign.x > 0:
                    near_edge_x = world_min_x
                    far_edge_x = world_max_x
                else:
                    near_edge_x = world_max_x
                    far_edge_x = world_min_x

                # ---------------------------------------------------------
                # Gate 1: runs from just outside the near edge (in the gap
                # between parts) to the painted spot on the part
                # ---------------------------------------------------------
                gate_base_x = near_edge_x + face_dir.x * gate_length
                context.view_layer.update()

                # This point is the average of every painted vertex. It isn't guaranteed to
                # be on the surface (with two paint blobs it lands between them, inside the part)
                gate_tip = painted_point + part_obj.location

                if has_priority:
                    # Look through the painted faces for a spot where the gate really sits flat
                    painted_faces = utils.get_painted_faces(part_obj, min_weight)
                    better_tip, _best_fit = utils.find_best_gate_tip(
                        part_obj,
                        gate_base_x,
                        painted_faces,
                        gate_radius,
                        min_gate_fit,
                        max_gate_slope
                    )
                    if better_tip is not None:
                        gate_tip = better_tip

                gate_base = Vector((gate_base_x, gate_tip.y, 0.0))

                # How much of the gate's end actually sits on the part
                gate_fit = utils.gate_fit_score(part_obj, gate_base, gate_tip, gate_radius)
                utils.debug(f"part '{part_obj.name}': gate 1 fit = {gate_fit:.2f}")
                if gate_fit < min_gate_fit:
                    poor_fit_parts.append((part_obj.name, gate_fit))

                gate_obj = utils.add_gate_cylinder(
                    context.collection,
                    gate_base,
                    gate_tip,
                    settings.gate_diameter,
                    f"_gate_{part_obj.name}",
                    embed=gate_embed_depth
                )
                if gate_obj:
                    gate_objects.append(gate_obj)

                # Every gate needs to be connected to the runners. Gate 1 sits on the near
                # side, so it would extend toward the injection point
                feeder_jobs.append((gate_base, sign.y, face_dir.x))

                # ---------------------------------------------------------
                # Extra gates: one more for every gate_volume_step of volume
                # ---------------------------------------------------------
                extra_wanted = int(volume // gate_volume_step)
                if extra_wanted > max_gates_per_part - 1:
                    extra_wanted = max_gates_per_part - 1

                if extra_wanted > 0:
                    # Where a gate coming in from the far side of the part would start
                    far_base_x = far_edge_x - face_dir.x * gate_length

                    # Closest two gate tips on the same part are allowed to be
                    part_height = mx.z - mn.z
                    part_diagonal = Vector((dim_x, dim_y, part_height)).length
                    min_gate_gap = min_gate_gap_ratio * part_diagonal

                    extra_gates = utils.find_extra_gates(
                        part_obj,
                        [gate_tip],
                        extra_wanted,
                        face_dir,
                        min_weight,
                        gate_base.x,
                        far_base_x,
                        gate_radius,
                        min_gate_fit,
                        fallback_gate_fit,
                        min_gap=min_gate_gap,
                        min_painted_gap=min_painted_gate_gap,
                        max_slope=max_gate_slope
                    )

                    if len(extra_gates) < extra_wanted:
                        missing_gate_parts.append((part_obj.name, extra_wanted, len(extra_gates)))

                    for gate_number, (extra_tip, side) in enumerate(extra_gates, start=2):
                        if side > 0:
                            extra_base_x = gate_base.x
                            extend_dir_x = face_dir.x
                        else:
                            extra_base_x = far_base_x
                            extend_dir_x = -face_dir.x
                        extra_base = Vector((extra_base_x, extra_tip.y, 0.0))

                        extra_gate = utils.add_gate_cylinder(
                            context.collection,
                            extra_base,
                            extra_tip,
                            settings.gate_diameter,
                            f"_gate_{part_obj.name}_{gate_number}",
                            embed=gate_embed_depth
                        )
                        if extra_gate:
                            gate_objects.append(extra_gate)
                        feeder_jobs.append((extra_base, sign.y, extend_dir_x))

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

        # Build the runners (trunks and feeders) inside the frame
        # Runners overlap the frame bars by half their width so they join them
        frame_left = x_min - frame_width / 2
        frame_right = x_max + frame_width / 2
        frame_bottom = y_min - frame_width / 2
        frame_top = y_max + frame_width / 2

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
            "_runner_trunk_x"
        )
        if x_trunk:
            runner_objects.append(x_trunk)

        # ---------------------------------------------------------------
        # Gates that are close to the Y trunk or the outer frame don't need
        # their own feeder. Instead a short bar links the gate straight to
        # that wall. Every other gate goes on to get a feeder below.
        # ---------------------------------------------------------------
        # X positions of the faces a gate (which runs along X) could run into:
        # both faces of the Y trunk, and the inner faces of the left/right frame bars
        wall_faces_x = [-runner_width / 2, runner_width / 2, x_min, x_max]

        feeders_needed = []
        link_count = 0
        for gate_base, side_y, extend_dir_x in feeder_jobs:
            wall_x = utils.find_wall_for_gate(
                gate_base,
                extend_dir_x,
                wall_faces_x,
                gate_extend_max_distance,
                placed_bounds,
                runner_width / 4,
                feeder_clearance
            )

            if wall_x is None:
                # Nothing close enough (or a part is in the way), so this gate needs a feeder
                feeders_needed.append((gate_base, side_y))
                continue

            # The bar goes a little way into the wall so the two meshes overlap
            wall_end_x = wall_x + extend_dir_x * gate_extend_overlap
            gate_end_x = gate_base.x - extend_dir_x * (runner_width / 4)

            link_obj = utils.add_runner_bar(
                context.collection,
                Vector((wall_end_x, gate_base.y, 0.0)),
                Vector((gate_end_x, gate_base.y, 0.0)),
                runner_width / 2,
                runner_height / 2,
                f"_runner_link_{link_count:02d}"
            )
            if link_obj:
                runner_objects.append(link_obj)
                link_count += 1

        # Feeders: one bar per remaining gate, from the X trunk out to the frame,
        # passing through the gate base and stopping short of any part in the way
        # Two gates can share one feeder (a part's far gate and the next part's
        # near gate sit in the same gap), so only keep one job per X position
        # and side, otherwise we would build two bars on top of each other
        unique_feeder_jobs = []
        seen_feeders = set()
        for gate_base, side_y in feeders_needed:
            key = (round(gate_base.x, 2), side_y)
            if key in seen_feeders:
                continue
            seen_feeders.add(key)
            unique_feeder_jobs.append((gate_base, side_y))

        for feeder_num, (gate_base, side_y) in enumerate(unique_feeder_jobs):
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
                f"_runner_feeder_{feeder_num:02d}"
            )
            if feeder_obj:
                runner_objects.append(feeder_obj)

        # Join the injection sprue, outer frame, runners and gates into one final Sprue_Frame object
        to_join = runner_objects + gate_objects

        bpy.ops.object.select_all(action="DESELECT")
        frame_obj.select_set(True)
        injection_obj.select_set(True)
        for obj in to_join:
            obj.select_set(True)
        context.view_layer.objects.active = frame_obj
        bpy.ops.object.join()
        frame_obj = context.active_object
        frame_obj.name = "Sprue_Frame"

        if missing_priority:
            self.report({'WARNING'}, "Some parts had no painted gate priority.")

        if poor_fit_parts:
            descriptions = []
            for part_name, fit in poor_fit_parts:
                descriptions.append(f"{part_name} ({fit * 100:.0f}% fit)")
            self.report({'WARNING'}, "Gate does not sit flat on: " + ", ".join(descriptions))

        if missing_gate_parts:
            descriptions = []
            for part_name, wanted, placed in missing_gate_parts:
                descriptions.append(f"{part_name} (wanted {wanted + 1} gates, placed {placed + 1})")
            self.report({'WARNING'}, "Fewer gates than the volume called for: " + ", ".join(descriptions))
        self.report(
            {'INFO'},
            f"Sprue built: {len(gate_objects)} gate(s), {len(runner_objects)} runner(s), "
            f"{link_count} gate(s) linked straight to a wall"
        )
        return {'FINISHED'}


# TODO List
# - add constants to the settings/properties file instead to allow for dials in UI
# - run dfm tests after sprue creation to make sure that it is ready for print/injection
# - update UI to look nicer with what we have now
