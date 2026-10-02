#  GATE-PRIORITY PAINTING (weight paint based)
# Users brush priority values on with Blender's built-in Weight Paint tool.
# We just manage the vertex group and read the weights back out.
PRIORITY_VG_NAME = "SpruePriority"

def ensure_priority_vertex_group(obj):
    """
    Get/create the vertex group to store priority values.
    A freshly created group is zeroed on every vertex so the
    whole mesh shows blue/low priority in Weight Paint mode 
    until the user brushes it, rather than unweighted grey.
    """
    vg = obj.vertex_groups.get(PRIORITY_VG_NAME)
    if vg is None:
        vg = obj.vertex_groups.new(name=PRIORITY_VG_NAME)
        all_indices = list(range(len(obj.data.vertices)))
        vg.add(all_indices, 0.0, 'REPLACE')
    return vg


def get_priority_values(obj):
    """
    Read the priority vertex group out as a plain list of floats,
    one entry per vertex (0.0 for any vertex not in the group).
    Returns [] if the mesh has no priority group yet.
    """
    vg = obj.vertex_groups.get(PRIORITY_VG_NAME)
    if vg is None:
        return []

    values = [0.0] * len(obj.data.vertices)
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == vg.index:
                values[v.index] = g.weight
                break
    return values

