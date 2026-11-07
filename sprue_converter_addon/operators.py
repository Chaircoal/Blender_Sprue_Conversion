## Operators that are used throughout the conversion process

import bpy
from .priority_brush import utils
from .sprue_gen import utils as sprue_utils

GENERATED_PREFIXES = tuple(sprue_utils.GENERATED_NAME_PREFIXES)


class SPRUE_OT_ClearAll(bpy.types.Operator):
    """Remove the built sprue, visualisation objects and all stored sprue data"""
    bl_idname = "sprue.clear_all"
    bl_label = "Clear all"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Can't safely delete objects / vertex groups while in Edit or Weight Paint mode
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Bring back the original parts that BuildSprue hid after copying them into the sprue
        restored = 0
        for obj in bpy.data.objects:
            if "_sprue_hidden_by_build" in obj:
                if obj.name in context.view_layer.objects:
                    obj.hide_set(False)
                del obj["_sprue_hidden_by_build"]
                restored += 1

        # Clear stored paint / analysis data from every part
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            for key in ("_sprue_curvatures", "_sprue_candidates", "_sprue_priority"):
                if key in obj:
                    del obj[key]
            if "SprueCurvature" in obj.data.attributes:
                obj.data.attributes.remove(obj.data.attributes["SprueCurvature"])
            priority_vg = obj.vertex_groups.get(utils.PRIORITY_VG_NAME)
            if priority_vg is not None:
                obj.vertex_groups.remove(priority_vg)

        # Remove everything the sprue build generated
        removed = 0
        for ob in list(bpy.data.objects):
            if ob.name.startswith(GENERATED_PREFIXES):
                bpy.data.objects.remove(ob, do_unlink=True)
                removed += 1

        # Joining objects in BuildSprue leaves their meshes behind with zero users
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0 and mesh.name.startswith(GENERATED_PREFIXES):
                bpy.data.meshes.remove(mesh)

        # Reset the UI state
        settings = context.scene.sprue_settings
        settings.last_island_count = 0
        settings.last_candidate_count = 0
        settings.last_priority_painted = 0

        self.report(
            {'INFO'},
            f"All sprue data cleared ({removed} generated object(s) removed, {restored} part(s) restored)."
        )
        return {'FINISHED'}
