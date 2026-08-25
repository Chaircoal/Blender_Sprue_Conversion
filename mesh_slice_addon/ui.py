import bpy
from . import operators

class VIEW3D_PT_mesh_slicing(bpy.types.Panel):
    bl_label = "Mesh Slicing Tools"
    bl_idname = "VIEW3D_PT_mesh_slicing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mesh Slicing"

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        properties = context.scene.mesh_slicer_properties

        layout.operator(operators.MESH_OT_get_sdf.bl_idname, icon='GRID')
        layout.operator(operators.VIEW3D_OT_draw_foreground.bl_idname, icon='BRUSH_DATA')
        layout.operator(operators.MESH_OT_generate_slice_boundaries.bl_idname, icon='VERTEXSEL')

        box = layout.box()
        row = box.row()
        icon = 'TRIA_DOWN' if properties.mesh_slicer_settings else 'TRIA_RIGHT'
        row.prop(properties, "mesh_slicer_settings", icon=icon, emboss=False, text="Slice Generation Settings")
        
        if properties.mesh_slicer_settings:
            col = box.column(align=True)
            col.prop(properties, "lambda_weight")
        
        layout.operator(operators.MESH_OT_slice_mesh.bl_idname, icon='MOD_BOOLEAN')
        layout.operator(operators.OBJECT_OT_lay_flat.bl_idname, icon="TRIA_DOWN")
        layout.operator(operators.MESH_OT_fill_holes.bl_idname),
