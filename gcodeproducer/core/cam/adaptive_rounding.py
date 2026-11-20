"""Tangent circular blends for adaptive finish candidates."""
from __future__ import annotations

import math

import numpy as np

from .cam_constants import ADAPTIVE_BLEND_MAX_CHORD_ANGLE, ADAPTIVE_BLEND_TURN_THRESHOLD, ADAPTIVE_PEEL_CHORD_ERROR


def rounded_loop(points, radius):
    """Round abrupt vertices without changing winding or the intervening lines.

    Adjacent blends never overlap. The caller must check containment, stock
    engagement and coverage on the result; a concave blend can be out of bounds.
    """
    path = np.asarray(points, float)
    edges = np.roll(path, -1, axis=0)-path
    lengths = np.linalg.norm(edges, axis=1)
    if len(path) < 3 or np.any(lengths <= 1e-9):
        return None
    unit = edges/lengths[:, None]
    parts = []
    for i, p in enumerate(path):
        u, v = unit[i-1], unit[i]
        cross = u[0]*v[1]-u[1]*v[0]
        angle = math.atan2(cross, float(u@v))
        if abs(angle) <= ADAPTIVE_BLEND_TURN_THRESHOLD:
            parts.append(p[None, :])
            continue
        if abs(angle) >= math.pi-1e-6:
            return None
        tangent = math.tan(abs(angle)/2)
        trim = min(radius*tangent, .45*min(lengths[i-1], lengths[i]))
        r = trim/tangent
        if r <= 1e-8:
            return None
        start, end = p-trim*u, p+trim*v
        origin = start + math.copysign(r, angle)*np.array([-u[1], u[0]])
        radial = start-origin
        phi = math.atan2(radial[1], radial[0])
        chord_angle = 4*math.asin(math.sqrt(min(1., ADAPTIVE_PEEL_CHORD_ERROR/(2*r))))
        n = math.ceil(abs(angle)/min(chord_angle, ADAPTIVE_BLEND_MAX_CHORD_ANGLE))
        theta = phi + np.linspace(0., angle, n+1)
        arc = origin + r*np.column_stack((np.cos(theta), np.sin(theta)))
        arc[0], arc[-1] = start, end
        parts.append(arc)
    return np.vstack(parts)
