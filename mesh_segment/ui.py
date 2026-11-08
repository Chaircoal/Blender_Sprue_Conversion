import bpy

from . import operators


class VIEW3D_PT_MeshSegment(bpy.types.Panel):
    bl_label = "Mesh Segment Tools"
    bl_idname = "VIEW3D_PT_meshsegment"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sprue Tool"
    bl_order = 2

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        col = layout.column(align=True)
        props = context.scene.meshsegment_properties

        col.operator(operators.MESH_OT_PreprocessMesh.bl_idname, icon="GRID")
        col.operator(operators.VIEW3D_OT_DrawForeground.bl_idname, icon="BRUSH_DATA")

        row = col.row(align=True)
        row.operator(operators.MESH_OT_GenerateBoundaries.bl_idname, icon="VERTEXSEL")
        if props.meshsegment_settings:
            row.prop(props, "meshsegment_settings", text="", icon="DOWNARROW_HLT")
        else:
            row.prop(props, "meshsegment_settings", text="", icon="RIGHTARROW")
        if props.meshsegment_settings:
            box = col.box()
            box.prop(props, "lambda_weight")
            box.prop(props, "beta")

        # Once Blender 5.3 is released, we should use the builtin relax_edge_loops func
        col.operator("meshsegment.looptools_relax")
        col.operator(operators.MESH_OT_SegmentMesh.bl_idname, icon="MOD_BOOLEAN")
