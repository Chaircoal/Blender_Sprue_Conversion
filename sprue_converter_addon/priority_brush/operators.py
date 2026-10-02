import bpy
from . import utils

class SPRUE_OT_StartPriorityPaint(bpy.types.Operator):
    """Create the gate-priority vertex group (if needed) and enter Weight Paint mode to brush it on"""
    bl_idname = "sprue.start_priority_paint"
    bl_label = "Paint gate priority"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'OBJECT'

    def execute(self, context):
        obj = context.active_object

        vg = utils.ensure_priority_vertex_group(obj)
        obj.vertex_groups.active_index = vg.index

        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')

        # Sensible brush defaults so the first stroke behaves predictably:
        # full-strength brush, painting toward priority = 1.0.
        # NOTE: as of Blender 5.0, unified_paint_settings lives on the
        # mode-specific Paint struct (tool_settings.weight_paint), not on
        # ToolSettings directly.
        tool_settings = context.scene.tool_settings
        wp = tool_settings.weight_paint
        if wp:
            ups = wp.unified_paint_settings
            ups.use_unified_strength = True
            ups.strength = 1.0
            if wp.brush:
                wp.brush.blend = 'MIX'
                wp.brush.strength = 1.0
        tool_settings.vertex_group_weight = 1.0  # value new strokes paint with

        self.report(
            {'INFO'},
            "Weight Paint mode: brush on gate-priority areas. "
            "Red = high priority, Blue = low. Lower the 'Weight' value in the "
            "tool header (or hold Ctrl to erase) to paint lower-priority areas."
        )
        return {'FINISHED'}


class SPRUE_OT_FinishPriorityPaint(bpy.types.Operator):
    """Leave Weight Paint mode and store the painted priority values"""
    bl_idname = "sprue.finish_priority_paint"
    bl_label = "Finish painting"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'WEIGHT_PAINT'

    def execute(self, context):
        obj = context.active_object
        settings = context.scene.sprue_settings

        bpy.ops.object.mode_set(mode='OBJECT')

        values = utils.get_priority_values(obj)
        obj["_sprue_priority"] = values

        painted = sum(1 for v in values if v > 0.001)
        settings.last_priority_painted = painted

        self.report(
            {'INFO'},
            f"Priority map saved — {painted} of {len(values)} vertex(es) have priority > 0."
        )
        return {'FINISHED'}


class SPRUE_OT_ClearPriorityPaint(bpy.types.Operator):
    """Remove the gate-priority vertex group and stored values"""
    bl_idname = "sprue.clear_priority_paint"
    bl_label = "Clear priority map"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and obj.type == 'MESH'
            and (utils.PRIORITY_VG_NAME in obj.vertex_groups or "_sprue_priority" in obj)
        )

    def execute(self, context):
        obj = context.active_object
        settings = context.scene.sprue_settings

        vg = obj.vertex_groups.get(utils.PRIORITY_VG_NAME)
        if vg is not None:
            obj.vertex_groups.remove(vg)
        if "_sprue_priority" in obj:
            del obj["_sprue_priority"]

        settings.last_priority_painted = 0
        self.report({'INFO'}, "Priority map cleared.")
        return {'FINISHED'}

