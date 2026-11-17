"""XYZ leads constrained to the validated surface path, never free tangent extensions."""
import math
import numpy as np
from .cam_constants import MAX_POINTS, RAMP_TAN


def _prefix(points, distance, depth=None, slope=None):
    p = np.asarray(points, float)
    result = [p[0]]
    walked = 0.
    for a, b in zip(p, p[1:]):
        length = float(np.linalg.norm(b[:2]-a[:2]))
        if length < 1e-9:
            if abs(b[2]-a[2]) > 1e-6:
                break
            continue
        fraction = min(1., max(0., (distance-walked)/length))
        if slope is not None:
            fa = a[2]-depth-slope*walked
            fb = b[2]-depth-slope*(walked+length)
            if fb > 1e-9:
                fraction = min(fraction, max(0., -fa/(fb-fa)))
        if fraction <= 1e-9:
            break
        result.append(a+fraction*(b-a))
        walked += fraction*length
        if fraction < 1.-1e-9 or walked >= distance-1e-9:
            break
    return np.asarray(result)


def surface_entry(points, entry_z, length):
    """Return an open-path ramp ending at points[0], with <=10-degree descent.

    Follow a safe prefix backwards, zigzagging when short. A prefix which rises
    too steeply toward its interior cannot be approached downhill at <=10 degrees
    from that side; shorten before that rise. Fail explicitly if no safe prefix
    remains instead of silently plunging or dipping below the model surface.
    """
    p = np.asarray(points, float)
    if len(p) < 2:
        raise ValueError('3D Contour lead-in requires a nonzero surface path')
    drop = float(entry_z-p[0, 2])
    if not math.isfinite(drop) or drop <= 0:
        raise ValueError('3D Contour lead-in start must be above the surface path')
    needed = max(float(length), drop/RAMP_TAN, .01)
    prefix = _prefix(p, needed, p[0, 2], drop/needed)
    if len(prefix) < 2:
        raise ValueError('3D Contour lead-in cannot fit a <=10 degree ramp along this surface path; '
                         'choose another entry/direction or explicitly disable lead-in')
    cycle = np.vstack((prefix, prefix[-2::-1]))
    lengths = np.linalg.norm(np.diff(cycle[:, :2], axis=0), axis=1)
    total = float(lengths.sum())
    if total < 1e-9:
        raise ValueError('3D Contour lead-in has no usable XY length')
    laps = int(math.floor(needed/total))
    if (laps+1)*len(cycle) > MAX_POINTS:
        raise ValueError(f'3D Contour lead-in would exceed {MAX_POINTS} points; revise the entry')
    walked = np.vstack([cycle[:1]]+[cycle[1:]]*laps)
    remainder = needed-laps*total
    if remainder > 1e-9:
        walked = np.vstack((walked, _prefix(cycle, remainder)[1:]))
    base = walked[::-1].copy()
    keep = np.r_[True, np.linalg.norm(np.diff(base[:, :2], axis=0), axis=1) > 1e-9]
    base = base[keep]
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(base[:, :2], axis=0), axis=1))]
    lead = base.copy()
    lead[:, 2] = entry_z-drop*distance/distance[-1]
    if np.any(lead[:, 2] < base[:, 2]-1e-6):
        raise ValueError('3D Contour lead-in would enter the protected surface; revise the entry')
    lead[-1] = p[0]
    return lead, 'zigzag' if needed > total/2+1e-9 else 'linear'


def surface_exit(points, length):
    """Reverse only as much already-cut XYZ path as exists; no lowered shortcuts."""
    p = np.asarray(points, float)
    if len(p) < 2:
        return None
    result = _prefix(p[::-1], max(0., float(length)))
    return result if len(result) > 1 else None
