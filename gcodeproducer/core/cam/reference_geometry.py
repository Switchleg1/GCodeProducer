"""Scalar plane construction and compute-process picking for reference outlines."""
import numpy as np
from .reference import Reference


def plane_point(origin, direction, z):
    origin, direction = np.asarray(origin, float), np.asarray(direction, float)
    if not np.isfinite(np.r_[origin,direction,z]).all() or abs(direction[2]) < 1e-10:
        return None
    distance = (z-origin[2])/direction[2]
    return origin+distance*direction if distance >= 0 else None


def line_segments(shapes):
    segments = []
    for shape in shapes:
        p = shape.polyline()
        segments.extend(np.stack((p[:-1],p[1:]),axis=1).reshape(-1,3))
    return np.asarray(segments, float).reshape(-1,3)


def filled_shapes(shapes):
    """Triangle fans for the supported convex circle/rectangle reference shapes."""
    triangles = []
    for shape in shapes:
        p = shape.polyline()
        center = p[:-1].mean(axis=0)
        triangles.extend(np.stack((np.tile(center, (len(p)-1, 1)), p[:-1], p[1:]), axis=1).reshape(-1, 3))
    return np.asarray(triangles, float).reshape(-1, 3)


def pick(shapes, mode, origin, direction, mvp, viewport, mouse):
    best, result = 10., None
    for shape in shapes:
        points = shape.polyline()
        if mode == "face":
            point = plane_point(origin,direction,shape.z)
            if point is None or not shape.contains(point[:2]):
                continue
            distance = float(np.linalg.norm(point-np.asarray(origin)))
            if result is not None and distance >= result["pick_distance"]:
                continue
        elif mode == "edge":
            clip = np.column_stack((points,np.ones(len(points)))) @ np.asarray(mvp).T
            if np.any(clip[:,3] <= 1e-12):
                continue
            screen = (clip[:,:2]/clip[:,3:4]*[1,-1]+1)*np.asarray(viewport)/2
            a,b = screen[:-1],screen[1:]
            delta = b-a
            u = np.clip(((np.asarray(mouse)-a)*delta).sum(axis=1)/np.maximum((delta*delta).sum(axis=1),1e-20),0,1)
            distance = float(np.linalg.norm(a+u[:,None]*delta-np.asarray(mouse),axis=1).min())
            if distance >= best:
                continue
            best = distance
        else:
            return None
        result = {"reference":Reference("drawing",[shape.id]), "z_min":shape.z, "z_max":shape.z,
                  "pick_distance":distance}
    return result
