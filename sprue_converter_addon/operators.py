## Operators that are used throughout the conversion process

import bpy
from .priority_brush import utils 

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
