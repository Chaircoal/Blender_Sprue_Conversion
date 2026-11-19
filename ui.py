## User interface for the addon
## This is what the end user will see and use to interact with the addon

import bpy


class SPRUE_PT_MainPanel(bpy.types.Panel):
    bl_label = "Sprue Tool"
    bl_idname = "SPRUE_PT_main"
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


# class SPRUE_PT_AnalysisPanel(bpy.types.Panel):
#     bl_label = "Model Analysis"
#     bl_idname = "SPRUE_PT_analysis"
#     bl_space_type = 'VIEW_3D'
#     bl_region_type = 'UI'
#     bl_category = "Sprue Tool"
#     bl_order = 3

#     def draw(self, context):
#         layout = self.layout
#         settings = context.scene.sprue_settings

#         # Step 1: Analysis
#         box = layout.box()
#         box.operator("sprue.analyze_mesh", icon='HIDE_OFF')

#         # DFM Checks for report
#         check_items = [
#             ("Open Edges", "open_edge_count"),
#             ("Non-manifold Edges", "non_manifold_edge_count"),
#             ("Non-manifold Vertices", "non_manifold_vert_count"),
#             ("Incontiguous Edges", "incontiguous_edge_count"),
#             ("Zero Distance Edges", "zero_edge_count"),
#             ("Zero Area Faces", "zero_face_count"),
#             ("Overhanging Faces", "overhang_face_count"),
#             ("Thin Walls", "thin_wall_count"),
#             ("Nonplanar Faces", "nonplanar_face_count"),
#             ("Islands", "last_island_count"),
#         ]

#         has_issues = False
#         for label, attr_name in check_items:
#             value = getattr(settings, attr_name, 0)
#             if value > 0:
#                 if attr_name != "last_island_count":
#                     has_issues = True
#                     break
#                 elif value > 1:
#                     has_issues = True
#                     break

#         if has_issues:
#             box.alert = True
#             box.label(text="Model not watertight!", icon='ERROR')
#         else:
#             box.label(text="Model is watertight", icon='CHECKMARK')

#         if settings.show_dfm_report:
#             report_icon = 'DOWNARROW_HLT'
#         else:
#             report_icon = 'RIGHTARROW'

#         row = box.row(align=True)
#         row.prop(settings, "show_dfm_report", text="Detailed Issue Report",
#                  icon=report_icon, emboss=False)

#         if settings.show_dfm_report:
#             col = box.column(align=True)
#             for label, attr_name in check_items:
#                 value = getattr(settings, attr_name, 0)
#                 if value > 0:
#                     if attr_name != "last_island_count":
#                         col.label(text=f" - {label}: {value}")
#                     elif value > 1:
#                         col.label(text=f" - {label}: {value}")

#             # call operator to highlight problem edges
#             box.operator("sprue.select_non_manifold", text="Select Non-Manifold Elements", icon='RESTRICT_SELECT_OFF')
