## User interface for the addon
## This is what the end user will see and use to interact with the addon

import bpy


class SPRUE_PT_Main(bpy.types.Panel):
    bl_label = "Sprue Tool"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sprue Tool"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # Object status
        box = layout.box()
        box.label(text="Active object", icon="MESH_DATA")
        if obj and obj.type == "MESH":
            box.label(text=obj.name, icon="CHECKMARK")
            row = box.row()
            row.label(text=f"Verts: {len(obj.data.vertices)}")
            row.label(text=f"Faces: {len(obj.data.polygons)}")
        else:
            box.label(text="Select a mesh object", icon="ERROR")

        # Utilities
        box = layout.box()
        box.label(text="Utilities", icon="TOOL_SETTINGS")
        box.operator("sprue.clear_all", icon="TRASH")
