import bpy
from . import operators

class VIEW3D_PT_mesh_slice(bpy.types.Panel):
    bl_label = "Mesh Slice Tools"
    bl_idname = "VIEW3D_PT_mesh_slice"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mesh Slice"

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        col = layout.column(align=True)
        props = context.scene.mesh_slice_properties
        
        col.operator(operators.MESH_OT_preprocess_mesh.bl_idname, icon='GRID')
        col.operator(operators.VIEW3D_OT_draw_foreground.bl_idname, icon='BRUSH_DATA')

        row = col.row(align=True)
        row.operator(operators.MESH_OT_generate_slice_boundaries.bl_idname, icon='VERTEXSEL')
        if props.mesh_slice_settings:
            row.prop(props, "mesh_slice_settings", text="", icon='DOWNARROW_HLT')
        else:
            row.prop(props, "mesh_slice_settings", text="", icon='RIGHTARROW')    
        if props.mesh_slice_settings:
            box = col.box()
            box.prop(props, "lambda_weight")
            box.prop(props, "beta")
        
        col.operator(operators.MESH_OT_slice_mesh.bl_idname, icon='MOD_BOOLEAN')
        col.operator(operators.OBJECT_OT_lay_flat.bl_idname, icon="TRIA_DOWN")
        col.operator("mesh_slice.looptools_relax") #Once Blender 5.3 is released, we should use the builtin relax_edge_loops func
