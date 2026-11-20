"""Sample progressive planar stock contact, independent of path generation."""
from __future__ import annotations

import math

from shapely.geometry import LineString, box

from gcodeproducer.core.cam.hsm_contact import contact_angle


def sampled_contact(points, remaining, radius, step, quad_segs):
    """Yield (angle in degrees, distance represented) before each sample's sweep.

    The previous stroke's swept geometry must already be removed. The first
    measurement is one substep forward, not an entry assessment. The planar
    disk model and finite step are approximations, not a certified bound.
    """
    if not math.isfinite(step) or step <= 0:
        raise ValueError('contact step must be positive and finite')
    xs, ys = zip(*points)
    local = remaining.intersection(box(min(xs)-radius, min(ys)-radius,
                                       max(xs)+radius, max(ys)+radius))
    for start, end in zip(points, points[1:]):
        distance = math.dist(start, end)
        if not distance:
            continue
        count = math.ceil(distance / step)
        last = start
        for k in range(1, count+1):
            t = k / count
            pose = end if k == count else tuple(a+(b-a)*t for a, b in zip(start, end))
            yield contact_angle(pose, radius, local), distance / count
            if not local.is_empty:
                local = local.difference(LineString([last, pose]).buffer(radius, quad_segs=quad_segs))
            last = pose


def distance_percentile(samples, fraction):
    """Quantile weighted by distance, not by tessellation or block count."""
    if not samples:
        return None
    target = sum(distance for _, distance in samples) * fraction
    weight = 0.
    for angle, distance in sorted(samples):
        weight += distance
        if weight >= target:
            return angle
    return max(angle for angle, _ in samples)
