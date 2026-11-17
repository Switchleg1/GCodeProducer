"""Compatibility exports for XYZ engagement.

Measurement: :class:`gcodeproducer.core.cam.planner.height_sampler.HeightSampler`.
Classification: :class:`gcodeproducer.core.cam.planner.engagement_model.EngagementModel`.
"""
import math
import numpy as np
from .cam_constants import SURFACE_MOVE_STEP_RADIUS, SURFACE_MAX_POINTS


def condition(state, a, b, radius, operation, tool, machine):
    from .planner.height_sampler import HeightSampler
    from .planner.engagement_model import EngagementModel
    return EngagementModel(operation, tool, machine).condition(HeightSampler(state), a, b, radius)


def split_move(a, b, radius, resolution):
    """Bound the XY/Z span over which one cutting classification is applied."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    step = max(resolution, radius*SURFACE_MOVE_STEP_RADIUS)
    count = max(1, int(math.ceil(max(np.linalg.norm(b[:2]-a[:2]), abs(b[2]-a[2]))/step)))
    if count > SURFACE_MAX_POINTS:
        raise ValueError('3D Contour move requires too many engagement samples')
    for i in range(1, count+1):
        yield a+(b-a)*(i/count)
