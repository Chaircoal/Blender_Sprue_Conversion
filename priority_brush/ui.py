import bpy

from . import operators


class SPRUE_PT_PriorityBrush(bpy.types.Panel):
    bl_label = "Gate Priority (optional)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sprue Tool"
    bl_order = 4

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        props = context.scene.prioritybrush_properties

        # Gate priority heatmap (Blender's native Weight Paint tool)
        box = layout.box()

        if context.mode == "PAINT_WEIGHT":
            box.label(text="Red = high priority | Blue = low", icon="INFO")
            row = box.row()
            row.scale_y = 1.4
            row.operator(
                operators.SPRUE_OT_FinishPriorityPaint.bl_idname,
                icon="CHECKMARK",
                text="Finish painting",
            )
        else:
            box.label(text="Brush areas that should get gates", icon="INFO")
            row = box.row()
            row.operator(
                operators.SPRUE_OT_StartPriorityPaint.bl_idname,
                icon="BRUSH_DATA",
                text="Paint gate priority",
            )
            if props.last_priority_painted > 0:
                box.label(
                    text=f"{props.last_priority_painted} vertex(es) marked priority"
                )
                box.operator(
                    operators.SPRUE_OT_ClearPriorityPaint.bl_idname,
                    icon="TRASH",
                    text="Clear priority map",
                )
