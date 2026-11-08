## Operators used to segment the meshes

import traceback

import bpy
from numpy import asarray

from . import exceptions, utils


class MESH_OT_PreprocessMesh(bpy.types.Operator):
    """Prepare selected mesh for slicing."""

    bl_idname = "meshsegment.get_sdf"
    bl_label = "Preprocess Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        obj = context.active_object

        try:
            obj["_sdf"] = utils.get_sdf(obj.data)
        except exceptions.MeshSegmentError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        except Exception as e:
            traceback.print_exc()
            self.report({"ERROR"}, f"{type(e).__name__}: {e!s}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Calculated SDF for {len(obj['_sdf'])} vertices.")

        return {"FINISHED"}


class VIEW3D_OT_DrawForeground(bpy.types.Operator):
    """Select vertices of the part you want to extract from the mesh."""

    bl_idname = "view3d.draw_foreground"
    bl_label = "Select Part to Extract"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context) -> set[str]:
        bpy.ops.object.mode_set(mode="EDIT")
        return {"FINISHED"}


class MESH_OT_GenerateBoundaries(bpy.types.Operator):
    """Assigns materials to segments based on the selected seed vertices."""

    bl_idname = "meshsegment.generate_segment_boundaries"
    bl_label = "Generate Segments"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context) -> set[str]:
        obj = context.active_object

        try:
            mesh = obj.data
            if obj.get("_sdf") is None:
                obj["_sdf"] = utils.get_sdf(mesh)

            sdf_array = asarray(obj["_sdf"])
            lambda_weight = context.scene.meshsegment_properties.lambda_weight
            beta = context.scene.meshsegment_properties.beta

            bpy.ops.object.mode_set(mode="OBJECT")  # ensure vertex selection updated

            vertex_labels = utils.get_vertex_labels(
                mesh, sdf_array, lambda_weight, beta
            )

            mat_fg = utils.get_or_create_material("Foreground", (1.0, 0.2, 0.2, 1.0))
            mat_bg = utils.get_or_create_material("Background", (0.2, 0.4, 1.0, 1.0))

            utils.assign_segment_materials(mesh, vertex_labels, mat_fg, mat_bg)
        except exceptions.MeshSegmentError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        except Exception as e:
            traceback.print_exc()
            self.report({"ERROR"}, f"{type(e).__name__}: {e!s}")
            return {"CANCELLED"}

        return {"FINISHED"}


class MESH_OT_SegmentMesh(bpy.types.Operator):
    """Segments the mesh, by material, into separate objects."""

    bl_idname = "meshsegment.segment_mesh"
    bl_label = "Segment Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = context.active_object

        if len(obj.material_slots) < 2:
            self.report({"ERROR"}, "Object must have 2 or more materials to separate.")
            return {"CANCELLED"}

        original_mode = obj.mode
        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # clear sdf for future segmentations
        if "_sdf" in obj:
            del obj["_sdf"]

        pre_segment_objs = set(bpy.context.scene.objects)

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.separate(type="MATERIAL")
        bpy.ops.object.mode_set(mode="OBJECT")

        post_segment_objs = set(bpy.context.scene.objects)
        new_objs = list(post_segment_objs - pre_segment_objs)
        new_objs.append(obj)  # add original obj

        for o in new_objs:
            utils.fill_mesh(o.data)

        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=original_mode)
        return {"FINISHED"}
