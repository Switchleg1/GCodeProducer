"""Placed mesh aggregation and initial free-space placement for FDM plates."""
import numpy as np

from gcodeproducer.core.geometry.mesh import Mesh


def combine_meshes(meshes):
    meshes = list(meshes)
    offset = 0
    triangles = []
    for mesh in meshes:
        triangles.append(mesh.triangles + offset)
        offset += len(mesh.vertices)
    return Mesh(np.concatenate([mesh.vertices for mesh in meshes]), np.concatenate(triangles))


def free_position(mesh, center, rect, occupied, gap=2.):
    """Find a nearby in-bounds translation using conservative XY bounds."""
    lo, hi = mesh.bounds
    x0, y0, x1, y1, _ = rect
    xs = [center[0], center[0]+x0-lo[0], center[0]+x1-hi[0]]
    ys = [center[1], center[1]+y0-lo[1], center[1]+y1-hi[1]]
    for low, high in occupied:
        xs.extend((center[0]+low[0]-hi[0]-gap, center[0]+high[0]-lo[0]+gap))
        ys.extend((center[1]+low[1]-hi[1]-gap, center[1]+high[1]-lo[1]+gap))
    valid = []
    for x in xs:
        dx = x-center[0]
        if lo[0]+dx < x0-1e-8 or hi[0]+dx > x1+1e-8:
            continue
        for y in ys:
            dy = y-center[1]
            if lo[1]+dy < y0-1e-8 or hi[1]+dy > y1+1e-8:
                continue
            if all(hi[0]+dx <= a[0]-gap+1e-8 or lo[0]+dx >= b[0]+gap-1e-8 or
                   hi[1]+dy <= a[1]-gap+1e-8 or lo[1]+dy >= b[1]+gap-1e-8 for a, b in occupied):
                valid.append((dx*dx+dy*dy, abs(dy), -dx, x, y))
    return min(valid)[-2:] if valid else None


def reanchor_models(models, anchor, auto_xy):
    """Shift the whole assembly to the new Z datum without changing relative poses."""
    if not models or all(m.placement.z_anchor == anchor for m in models):
        return
    bounds = [m.placement.apply(m.mesh, auto_xy).bounds for m in models]
    shift = (-max(hi[2] for _, hi in bounds) if anchor == 'top'
             else -min(lo[2] for lo, _ in bounds))
    for model, (lo, hi) in zip(models, bounds):
        pose = model.placement
        pose.z_anchor = anchor
        pose.z = float((hi if anchor == 'top' else lo)[2] + shift)
        pose.drop = True
        if pose.x is None:
            pose.x = float((lo[0]+hi[0])/2)
        if pose.y is None:
            pose.y = float((lo[1]+hi[1])/2)
        # Manual FDM support blocks stay in bed coordinates, not CAM Z.


def overlapping_bounds(meshes):
    """Conservative indication of intersecting instance envelopes, not a mesh collision check."""
    bounds = [mesh.bounds for mesh in meshes]
    return any(np.all(np.minimum(hi, bh)-np.maximum(lo, bl) > 1e-5)
               for i, (lo, hi) in enumerate(bounds) for bl, bh in bounds[:i])
