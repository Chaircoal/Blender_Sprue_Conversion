import bpy
from . import operators

class VIEW3D_PT_mesh_slicing(bpy.types.Panel):
    bl_label = "Mesh Slicing Tools"
    bl_idname = "VIEW3D_PT_mesh_slicing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mesh Slicing"

    def draw(self, context):
        layout = self.layout
        layout.operator(operators.MESH_OT_get_sdf.bl_idname, icon='GRID')
        layout.operator(operators.VIEW3D_OT_draw_foreground.bl_idname, icon='BRUSH_DATA')
        layout.operator(operators.MESH_OT_generate_slice_boundaries.bl_idname, icon='VERTEXSEL')
        layout.operator(operators.MESH_OT_slice_mesh.bl_idname, icon='MOD_BOOLEAN')
