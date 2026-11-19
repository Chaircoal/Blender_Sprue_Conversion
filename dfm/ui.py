import bpy

from . import operators

# (label, property name) for every check shown in the DFM report
CHECK_ITEMS = (
    ("Open Edges", "open_edge_count"),
    ("Non-manifold Edges", "non_manifold_edge_count"),
    ("Non-manifold Vertices", "non_manifold_vert_count"),
    ("Incontiguous Edges", "incontiguous_edge_count"),
    ("Zero Distance Edges", "zero_edge_count"),
    ("Zero Area Faces", "zero_face_count"),
    ("Overhanging Faces", "overhang_face_count"),
    ("Thin Walls", "thin_wall_count"),
    ("Nonplanar Faces", "nonplanar_face_count"),
    ("Islands", "last_island_count"),
)


def _is_issue(attr_name: str, value: int) -> bool:
    """A single island is expected; any other non-zero count is a problem."""
    if attr_name == "last_island_count":
        return value > 1
    return value > 0


class SPRUE_PT_DFM(bpy.types.Panel):
    bl_label = "Model Analysis"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sprue Tool"
    bl_order = 3

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        props = context.scene.dfm_properties

        box = layout.box()
        box.operator(operators.SPRUE_OT_AnalyzeMesh.bl_idname, icon="HIDE_OFF")

        issues = [
            (label, getattr(props, attr_name, 0))
            for label, attr_name in CHECK_ITEMS
            if _is_issue(attr_name, getattr(props, attr_name, 0))
        ]

        if issues:
            box.alert = True
            box.label(text="Model not watertight!", icon="ERROR")
        else:
            box.label(text="Model is watertight", icon="CHECKMARK")

        if props.show_dfm_report:
            report_icon = "DOWNARROW_HLT"
        else:
            report_icon = "RIGHTARROW"

        row = box.row(align=True)
        row.prop(
            props,
            "show_dfm_report",
            text="Detailed Issue Report",
            icon=report_icon,
            emboss=False,
        )

        if props.show_dfm_report:
            col = box.column(align=True)
            for label, value in issues:
                col.label(text=f" - {label}: {value}")

            # highlight problem elements
            box.operator(
                operators.SPRUE_OT_SelectNonManifold.bl_idname,
                text="Select Non-Manifold Elements",
                icon="RESTRICT_SELECT_OFF",
            )
