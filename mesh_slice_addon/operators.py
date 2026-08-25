## Operators used to slice the meshes

import bpy
import bmesh
import traceback
from . import properties, utils, exceptions

class MESH_OT_get_sdf(bpy.types.Operator):
    bl_idname = "mesh.get_sdf"
    bl_label = "Calculate Mesh SDF"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh.")
            return {'CANCELLED'}

        try:
            obj["_sdf"] = utils.get_sdf(obj)
        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, f"Unexpected Error ({type(e).__name__}): {str(e)}. Check System Console for details.")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Calculated SDF for {len(obj['_sdf'] )} vertices.")

        return {"FINISHED"}

class VIEW3D_OT_draw_foreground(bpy.types.Operator):
    """Select vertices of the part you want to extract from the mesh."""
    bl_idname = "view3d.draw_foreground"
    bl_label = "Select Part to Extract"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context) -> set[str]:
        bpy.ops.object.mode_set(mode='EDIT')
        return {"FINISHED"}

class MESH_OT_generate_slice_boundaries(bpy.types.Operator):
    """Generates the slice boundaries and assigns each slice a material."""
    bl_idname = "mesh.generate_slice_boundaries"
    bl_label = "Generate Slices"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context) -> set[str]:
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh.")
            return {'CANCELLED'}

        if obj.get("_sdf") is None:
                # TODO: Needs to actually show before sdf has been calculated
                # self.report({'WARNING'}, "SDF not calculated yet, calculating now...")
                obj["_sdf"] = utils.get_sdf(obj)

        bpy.ops.object.mode_set(mode='OBJECT')  # ensure selected vertices are updated

        try:
            utils.compute_mesh_boundaries(obj, props=context.scene.mesh_slicer_properties)
        except exceptions.MeshSliceError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, f"Unexpected Error ({type(e).__name__}): {str(e)}.")
            return {'CANCELLED'}

        return {"FINISHED"}

class MESH_OT_slice_mesh(bpy.types.Operator):
    """Separates the mesh by material into separate objects."""
    bl_idname = "mesh.slice_mesh"
    bl_label = "Slice Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context) -> set[str]:
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh.")
            return {'CANCELLED'}

        if "_sdf" in obj:
            del obj["_sdf"]
                
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.separate(type='MATERIAL')
            bpy.ops.object.mode_set(mode='OBJECT')
            return {"FINISHED"}
        else:
            self.report({'Error'}, "Please calculate the SDF first.")
            return{"CANCELED"}

class OBJECT_OT_lay_flat(bpy.types.Operator):
    """Lays the active object flat along the XY plane"""
    bl_idname = "object.lay_flat"
    bl_label = "Lay Flat"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context) -> set[str]:
        obj = context.active_object

        original_mode = obj.mode
        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        mesh = obj.data
        utils.align_object_along_xy(obj, mesh)

        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=original_mode)
        return {"FINISHED"}

class MESH_OT_fill_holes(bpy.types.Operator):
    """Fills any holes in the mesh, making it watertight"""
    bl_idname = "object.slicer_fill_holes"
    bl_label = "Fill Holes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh.")
            return {'CANCELLED'}
        
        original_mode = obj.mode
        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bm = bmesh.from_edit_mesh(obj.data)

        boundary_edges = [e for e in bm.edges if not e.is_manifold]
        if not boundary_edges:
            self.report({'INFO'}, "No boundary edges (holes) found")
            return {'FINISHED'}

        boundary_loops = utils.loops_from_boundary_edges(boundary_edges)
        count = 0
        for loop in boundary_loops:
            created = bmesh.ops.triangle_fill(bm, edges=loop, use_beauty=True)
            if not created:
                faces = bmesh.ops.holes_fill(bm, edges=loop) # n-gon
                if faces:
                    try:
                        bmesh.ops.triangulate(bm, faces=faces) # here we could fan the n-gon
                    except Exception:
                        pass
            count += 1

        bmesh.update_edit_mesh(obj.data)

        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=original_mode)

        self.report({'INFO'}, f"Holes filled: {count}")
        return {'FINISHED'}