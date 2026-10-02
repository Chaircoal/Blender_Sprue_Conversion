## Operators used to slice the meshes

import bpy
import traceback
from . import utils, exceptions
from numpy import asarray

class MESH_OT_PreprocessMesh(bpy.types.Operator):
    """Prepare selected mesh for slicing."""
    bl_idname = "meshslice.get_sdf"
    bl_label = "Preprocess Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object

        try:
            obj["_sdf"] = utils.get_sdf(obj.data)
        except exceptions.MeshSliceError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, f"{type(e).__name__}: {str(e)}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Calculated SDF for {len(obj['_sdf'] )} vertices.")

        return {"FINISHED"}

class VIEW3D_OT_DrawForeground(bpy.types.Operator):
    """Select vertices of the part you want to extract from the mesh."""
    bl_idname = "view3d.draw_foreground"
    bl_label = "Select Part to Extract"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context) -> set[str]:
        bpy.ops.object.mode_set(mode='EDIT')
        return {"FINISHED"}

class MESH_OT_GenerateSliceBoundaries(bpy.types.Operator):
    """Assigns materials to slices based on selected seed vertices."""
    bl_idname = "meshslice.generate_slice_boundaries"
    bl_label = "Generate Slices"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context) -> set[str]:
        obj = context.active_object
        
        try:
            mesh = obj.data
            if obj.get("_sdf") is None:
                obj["_sdf"] = utils.get_sdf(mesh)

            sdf_array = asarray(obj["_sdf"])
            lambda_weight = context.scene.meshslice_properties.lambda_weight
            beta = context.scene.meshslice_properties.beta

            bpy.ops.object.mode_set(mode='OBJECT')  # ensure vertex selection updated

            vertex_labels = utils.get_vertex_labels(mesh, sdf_array, lambda_weight, beta)

            mat_fg = utils.get_or_create_material("Foreground", (1.0, 0.2, 0.2, 1.0))
            mat_bg = utils.get_or_create_material("Background", (0.2, 0.4, 1.0, 1.0))

            utils.assign_slice_materials(mesh, vertex_labels, mat_fg, mat_bg)
        except exceptions.MeshSliceError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, f"{type(e).__name__}: {str(e)}")
            return {'CANCELLED'}

        return {"FINISHED"}

class MESH_OT_SliceMesh(bpy.types.Operator):
    """Slices the mesh by material into separate objects."""
    bl_idname = "meshslice.slice_mesh"
    bl_label = "Slice Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = context.active_object

        if len(obj.material_slots) < 2:
            self.report({'ERROR'}, "Object must have 2 or more materials to separate.")
            return {'CANCELLED'}

        original_mode = obj.mode
        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # clear sdf for future segmentations
        if "_sdf" in obj:
            del obj["_sdf"]

        pre_slice_objs = set(bpy.context.scene.objects)      

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.separate(type='MATERIAL')
        bpy.ops.object.mode_set(mode='OBJECT')

        post_slice_objs = set(bpy.context.scene.objects)
        new_objects = list(post_slice_objs - pre_slice_objs)
        new_objects.append(obj) # add original obj

        for o in new_objects:
            utils.fill_mesh(o.data)

        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=original_mode)
        return {"FINISHED"}

class OBJECT_OT_LayFlat(bpy.types.Operator):
    """Lays the active object flat along the XY plane"""
    bl_idname = "object.lay_flat"
    bl_label = "Lay Flat"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context) -> set[str]:
        obj: bpy.types.Object = context.active_object

        original_mode = obj.mode
        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        utils.align_object_along_xy(obj) # lay mesh "flat"

        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')
        x, y, _ = obj.location
        obj.location = (x, y, 0)

        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=original_mode)
        return {"FINISHED"}

