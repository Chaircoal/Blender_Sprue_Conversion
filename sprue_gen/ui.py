import bpy

from . import operators


class SPRUE_PT_SprueGen(bpy.types.Panel):
    bl_label = "Build Frame"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sprue Tool"
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        settings = context.scene.spruegen_properties

        # Build sprue frame
        box = layout.box()
        box.label(text="Build Sprue Frame", icon="MESH_GRID")

        col = box.column(align=True)
        col.prop(settings, "piece_spacing")
        col.prop(settings, "frame_padding")
        col.separator()
        col.prop(settings, "frame_diameter")
        col.separator()
        col.prop(settings, "gate_diameter")
        col.prop(settings, "gate_length")
        col.prop(settings, "gate_volume_step")
        col.prop(settings, "max_gates_per_piece")

        box.label(text="Organize Parts", icon="ERROR")
        col = box.column(align=True)
        col.operator(operators.SPRUE_OT_BuildSprue.bl_idname, icon="MOD_BUILD")

        col.separator()
        col.label(text="Re-run Analyze Mesh after building", icon="INFO")
