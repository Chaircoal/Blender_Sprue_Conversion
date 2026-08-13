## Operators used to slice the meshes

import bpy
import bmesh
import time
import traceback
from . import properties, utils, exceptions

class MESH_OT_generate_slice_boundaries(bpy.types.Operator):
    bl_idname = "mesh.generate_slice_boundaries"
    bl_label = "Generate Slices"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        start_time = time.perf_counter()
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh.")
            return {'CANCELLED'}

        if obj.get("_sdf") is None:
                self.report({'WARNING'}, "SDF not calculated yet, calculating now...")
                obj["_sdf"] = utils.calculate_mesh_sdf(obj)

        bpy.ops.object.mode_set(mode='OBJECT')  # ensure selected vertices are updated

        try:
            utils.compute_mesh_boundaries(obj)
        except exceptions.MeshSliceError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, f"Unexpected Error ({type(e).__name__}): {str(e)}.")
            return {'CANCELLED'}

        end_time = time.perf_counter()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time:.6f} seconds")
        return {"FINISHED"}


class MESH_OT_get_sdf(bpy.types.Operator):
    bl_idname = "mesh.get_sdf"
    bl_label = "Calculate Mesh SDF"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        start_time = time.perf_counter()

        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a Mesh Object.")
            return {'CANCELLED'}

        try:
            obj["_sdf"] = utils.get_sdf(obj)
        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, f"Unexpected Error ({type(e).__name__}): {str(e)}. Check System Console for details.")
            return {'CANCELLED'}

        end_time = time.perf_counter()
        execution_time = end_time - start_time
        print(f'SDF Calc Execution Time: {execution_time:.4f} seconds')
        self.report({'INFO'}, f"Calculated SDF for {len(obj['_sdf'] )} vertices.")

        return {"FINISHED"}

class VIEW3D_OT_draw_foreground(bpy.types.Operator):
    """Select vertices of the part to be cut from the mesh."""
    bl_idname = "view3d.draw_foreground"
    bl_label = "Select Part to Cut"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        bpy.ops.object.mode_set(mode='EDIT')
        return {"FINISHED"}

class MESH_OT_slice_mesh(bpy.types.Operator):
    """Confirm cut"""
    bl_idname = "mesh.slice_mesh"
    bl_label = "Slice Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object

        if obj and obj.type == "MESH":
            if "_sdf" in obj:
                del obj["_sdf"]
                
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.separate(type='MATERIAL')
            bpy.ops.object.mode_set(mode='OBJECT')
            return {"FINISHED"}
            
        self.report({'WARNING'}, "Active object is not a mesh")
        return {"CANCELLED"}