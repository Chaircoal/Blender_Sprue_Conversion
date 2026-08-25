## User interface for the addon
## This is what the end user will see and use to interact with the addon

import bpy
from . import properties, utils, operators

class SPRUE_PT_MainPanel(bpy.types.Panel):
    bl_label = "Sprue Tool"
    bl_idname = "SPRUE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Sprue Tool"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sprue_settings
        obj = context.active_object

        # Object status
        box = layout.box()
        box.label(text="Active object", icon='MESH_DATA')
        if obj and obj.type == 'MESH':
            box.label(text=obj.name, icon='CHECKMARK')
            row = box.row()
            row.label(text=f"Verts: {len(obj.data.vertices)}")
            row.label(text=f"Faces: {len(obj.data.polygons)}")
        else:
            box.label(text="Select a mesh object", icon='ERROR')

        layout.separator()

        # Step 1: Analysis
        box = layout.box()
        box.label(text="Step 1 — Analyse", icon='FORCE_MAGNETIC')
        col = box.column(align=True)
        col.prop(settings, "curvature_threshold", slider=True)
        col.operator("sprue.analyze_mesh", icon='HIDE_OFF')

        if settings.last_island_count > 0:
            row = box.row()
            if settings.last_island_count > 1:
                row.alert = True
                row.label(
                    text=f"⚠ {settings.last_island_count} islands detected!",
                    icon='ERROR'
                )
            else:
                row.label(text="✓ 1 connected island (good)", icon='CHECKMARK')

        if settings.heatmap_visible:
            box.operator("sprue.clear_heatmap", icon='HIDE_ON')
            box.label(
                text="Green = safe to cut  |  Red = avoid",
                icon='INFO'
            )

        layout.separator()

        # Step 2: Slice planes
        box = layout.box()
        box.label(text="Step 2 — Slice planes", icon='MOD_BOOLEAN')
        col = box.column(align=True)
        col.prop(settings, "num_candidates")
        has_curvatures = obj is not None and "_sprue_curvatures" in (obj or {})
        col.enabled = has_curvatures
        col.operator("sprue.find_slice_planes", icon='MESH_PLANE')

        if settings.last_candidate_count > 0:
            box.label(text=f"{settings.last_candidate_count} plane(s) shown in scene")
            box.label(text="Green = safe  Yellow = review  Red = risky")

        layout.separator()

        # Step 3: Apply cuts
        import json
        has_candidates = obj is not None and "_sprue_candidates" in (obj or {})
        if has_candidates:
            candidates = json.loads(obj["_sprue_candidates"])
            box = layout.box()
            box.label(text="Step 3 — Apply cuts", icon='MOD_BOOLEAN')
            for i, c in enumerate(candidates):
                row = box.row(align=True)
                if c.get('island_risk'):
                    row.alert = True
                    icon = 'ERROR'
                    label = f"Z={c['value']:.3f}  ISLAND RISK"
                elif c['accepted']:
                    icon = 'CHECKMARK'
                    label = f"Z={c['value']:.3f}  safe"
                else:
                    icon = 'QUESTION'
                    label = f"Z={c['value']:.3f}  review"
                row.label(text=label, icon=icon)
                op = row.operator("sprue.accept_plane", text="Bisect & Separate", icon='MOD_BOOLEAN')
                op.plane_index = i

        layout.separator()
        
        # ── Optional: Gate priority heatmap (Blender's native Weight Paint tool)
        box = layout.box()
        box.label(text="Gate priority (optional)", icon='WPAINT_HLT')

        if context.mode == 'PAINT_WEIGHT':
            box.label(text="Painting — Red = high priority, Blue = low", icon='INFO')
            row = box.row()
            row.scale_y = 1.4
            row.operator("sprue.finish_priority_paint", icon='CHECKMARK', text="Finish painting")
        else:
            box.label(text="Brush on areas that should get a gate.", icon='INFO')
            row = box.row()
            row.operator("sprue.start_priority_paint", icon='BRUSH_DATA', text="Paint gate priority")
            if settings.last_priority_painted > 0:
                box.label(text=f"{settings.last_priority_painted} vertex(es) marked priority")
                box.operator("sprue.clear_priority_paint", icon='TRASH', text="Clear priority map")

        layout.separator()

        # ── Step 4: Build sprue frame
        box = layout.box()
        box.label(text="Step 4 — Build sprue frame", icon='MESH_GRID')
        box.label(text="Select all sliced pieces, then:", icon='INFO')

        col = box.column(align=True)
        col.prop(settings, "piece_spacing")
        col.prop(settings, "frame_padding")
        col.separator()
        col.prop(settings, "frame_width")
        col.prop(settings, "frame_height")
        col.separator()
        col.prop(settings, "gate_diameter")
        col.prop(settings, "gate_length")

        sel_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        row = box.row()
        row.scale_y = 1.4
        if sel_meshes:
            row.operator("sprue.build_frame", icon='MESH_GRID',
                         text=f"Build frame ({len(sel_meshes)} piece(s))")
        else:
            row.enabled = False
            row.operator("sprue.build_frame", icon='MESH_GRID',
                         text="Select pieces first")

        layout.separator()

        # Utilities
        box = layout.box()
        box.label(text="Utilities", icon='TOOL_SETTINGS')
        box.operator("sprue.clear_all", icon='TRASH')