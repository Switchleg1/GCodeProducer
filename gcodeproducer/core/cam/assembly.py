"""Combined CAM mesh identity and reference maintenance for model instances."""
from gcodeproducer.core.fdm.plate import combine_meshes
from gcodeproducer.core.cam.planning import fingerprint


def assembly_fingerprint(models):
    if not models:
        return ''
    if len(models) == 1:
        return fingerprint(models[0].mesh)
    return fingerprint(combine_meshes(m.mesh for m in models))


def remove_model_references(setup, models, row):
    """Reject deletion of a used model; shift surviving mesh indices in place."""
    vertex = sum(len(m.mesh.vertices) for m in models[:row])
    face = sum(len(m.mesh.triangles) for m in models[:row])
    mesh = models[row].mesh
    ranges = {'face': (face, len(mesh.triangles)), 'edge': (vertex, len(mesh.vertices))}
    edits = []
    seen = set()
    for group in setup.groups:
        for op in group.operations:
            for ref in (*op.geometry, *op.height_references, op.start.reference, op.end.reference):
                if ref is None or ref.kind not in ranges or id(ref) in seen:
                    continue
                seen.add(id(ref))
                start, count = ranges[ref.kind]
                if any(start <= i < start+count for i in ref.indices):
                    return False
                edits.append((ref, [i-count if i >= start+count else i for i in ref.indices]))
    count = len(mesh.triangles)
    if any(face <= tab.triangle < face+count for tab in setup.tabs):
        return False
    for ref, indices in edits:
        ref.indices = indices
    for tab in setup.tabs:
        if tab.triangle >= face+count:
            tab.triangle -= count
    return True
