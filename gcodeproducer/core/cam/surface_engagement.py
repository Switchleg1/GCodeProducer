"""Incremental XYZ engagement from current height-field material, not a fixed XY blank.

Occupied transverse cutter chords classify radial engagement at the moving tip
height. This is a grid estimate, not tooth-level or swept-solid simulation.
"""
import math
import numpy as np
from .cam_constants import (SURFACE_ENGAGEMENT_STATIONS, SURFACE_ENGAGEMENT_FORWARD,
                            SURFACE_CHORD_SAMPLES_MIN, SURFACE_CHORD_SAMPLES_MAX,
                            SURFACE_MOVE_STEP_RADIUS, SURFACE_MAX_POINTS)
from .engagement import engagement_band, feed_factor, _hand
from gcodeproducer.core.jobs.cut_condition import CutCondition


def condition(state, a, b, radius, operation, tool, machine):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if radius <= 0 or not math.isfinite(radius):
        raise ValueError('3D engagement requires a positive tool radius')
    contact = state.contact(a, b, radius)
    if not contact:
        return CutCondition(0., 'air', 'air', 1.)
    delta = b-a
    distance = float(np.linalg.norm(delta[:2]))
    left = right = 0.
    if distance < 1e-9:
        engagement = 1.
        left = right = engagement*radius
    else:
        tangent = delta[:2]/distance
        normal = np.array([-tangent[1], tangent[0]])
        forward = radius*np.asarray(SURFACE_ENGAGEMENT_FORWARD)
        half_width = np.sqrt(np.maximum(radius*radius-forward*forward, 0))
        n = max(SURFACE_CHORD_SAMPLES_MIN, min(SURFACE_CHORD_SAMPLES_MAX,
                                             int(math.ceil(radius/state.resolution))))
        radial = (np.arange(n)+.5)/n
        stations = np.asarray(SURFACE_ENGAGEMENT_STATIONS)
        centers = (a[:2]+stations[:, None]*delta[:2])[:, None, :]+forward[None, :, None]*tangent
        offsets = half_width[:, None, None]*radial[None, :, None]*normal
        xy = np.stack((centers[:, :, None, :]+offsets[None],
                       centers[:, :, None, :]-offsets[None]), axis=2)
        ix = np.floor((xy[..., 0]-state.stock.x)/state.dx).astype(int)
        iy = np.floor((xy[..., 1]-state.stock.y)/state.dy).astype(int)
        valid = (ix >= 0) & (ix < state.nx) & (iy >= 0) & (iy < state.ny)
        heights = state.heights[np.clip(iy, 0, state.ny-1), np.clip(ix, 0, state.nx-1)]
        z = a[2]+stations*delta[2]
        occupied = valid & (heights > z[:, None, None, None]+1e-3) & (heights > state.bottom+1e-3)
        widths = occupied.sum(axis=-1)*half_width[None, :, None]/n
        peak = int(np.argmax(widths.sum(axis=-1)))
        left, right = widths.reshape(-1, 2)[peak]
        engagement = float(np.clip((left+right)/(2*radius), 0, 1))
        # A short incremental move in a full slot sees only the leading crescent:
        # its central chord is already cleared by the preceding cutter disc.
        # Measure newly swept area outside that starting disc as well, otherwise
        # subdividing a full slot incorrectly turns it into ordinary/HSM cutting.
        patch = state._patch(a, b, radius)
        if patch is not None:
            region, swept_distance, tip = patch
            x = state.x[region[1]][None, :]
            y = state.y[region[0]][:, None]
            outside_start = (x-a[0])**2+(y-a[1])**2 > radius*radius+1e-9
            fresh = ((swept_distance <= radius*radius) & outside_start
                     & (state.heights[region] > tip+1e-3)
                     & (state.heights[region] > state.bottom+1e-3))
            area_fraction = float(fresh.sum())*state.dx*state.dy/(2*radius*distance)
            engagement = max(engagement, min(1., area_fraction))
        if engagement <= 1e-6:
            # Do not call a sub-cell grazing cap contact air.
            engagement = .01
            left = right = engagement*radius
    band = engagement_band(engagement, machine)
    return CutCondition(engagement, band, _hand(left, right, engagement, machine),
                        feed_factor(band, operation, tool, machine))


def split_move(a, b, radius, resolution):
    """Bound the XY/Z span over which one cutting classification is applied."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    step = max(resolution, radius*SURFACE_MOVE_STEP_RADIUS)
    count = max(1, int(math.ceil(max(np.linalg.norm(b[:2]-a[:2]), abs(b[2]-a[2]))/step)))
    if count > SURFACE_MAX_POINTS:
        raise ValueError('3D Contour move requires too many engagement samples')
    for i in range(1, count+1):
        yield a+(b-a)*(i/count)
