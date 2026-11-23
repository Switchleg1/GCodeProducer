"""XYZ leads: thin wrappers over the shared lead rule in :mod:`leads` (one rule for flat and surface paths)."""
import math
import numpy as np
from .cam_constants import RAMP_ANGLE


def surface_entry(points, entry_z, length, angle=RAMP_ANGLE):
    """Open-path ramp ending at points[0]: the shared lead-in rule, :func:`leads.path_ramp`."""
    from .leads import path_ramp
    p = np.asarray(points, float)
    if len(p) < 2:
        raise ValueError('3D Contour lead-in requires a nonzero surface path')
    drop = float(entry_z-p[0, 2])
    if not math.isfinite(drop) or drop <= 0:
        raise ValueError('3D Contour lead-in start must be above the surface path')
    lead, kind = path_ramp(p, False, entry_z, length, angle)
    if lead is None:
        raise ValueError('3D Contour lead-in has no usable XY length')
    return lead, kind


def surface_exit(points, length, closed=False):
    """Reverse only as much already-cut XYZ path as exists: the shared exit rule, :func:`leads.exit_path`."""
    from .leads import exit_path
    p = np.asarray(points, float)
    if len(p) < 2:
        return None
    result = exit_path(p, closed, length)
    return result if result is not None and len(result) > 1 else None
