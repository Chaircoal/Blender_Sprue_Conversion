import bpy
import bmesh
from mathutils import Vector
from . import utils
from .. import mesh_utils

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

            bm = mesh_utils.get_bmesh(obj)
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
