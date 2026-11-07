import bpy
import bmesh
from . import utils
from .. import mesh_utils

class SPRUE_OT_AnalyzeMesh(bpy.types.Operator):
    """Analyse the selected mesh: compute problem areas and detect islands"""
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

        bm = mesh_utils.get_bmesh(obj)
        curvatures = mesh_utils.compute_face_curvature(bm)

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


class SPRUE_OT_SelectNonManifold(bpy.types.Operator):
    """Select the non-manifold elements of highlighted part"""
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
        bm = mesh_utils.get_bmesh(obj)
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
