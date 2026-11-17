"""HeightSampler — engagement on the height-field material at the moving tip (XYZ moves).

Occupied transverse cutter chords at several stations / forward offsets give
the peak radial engagement; newly swept area outside the starting cutter disc
keeps short incremental full-slot moves from reading as light cuts. A grid
estimate, not tooth-level or swept-solid simulation.
"""
from __future__ import annotations
import math
from functools import lru_cache
import numpy as np
from gcodeproducer.core.cam.cam_constants import (SURFACE_ENGAGEMENT_STATIONS, SURFACE_ENGAGEMENT_FORWARD,
                                                  SURFACE_CHORD_SAMPLES_MIN, SURFACE_CHORD_SAMPLES_MAX)
from .engagement_sampler import EngagementSampler


@lru_cache(maxsize=32)
def _chord_grid(radius, n):
    """Sampling offsets that depend on the cutter and resolution, not the move."""
    forward = radius*np.asarray(SURFACE_ENGAGEMENT_FORWARD)
    half_width = np.sqrt(np.maximum(radius*radius-forward*forward, 0))
    radial = (np.arange(n)+.5)/n
    return forward, half_width, half_width[:, None]*radial[None, :], np.asarray(SURFACE_ENGAGEMENT_STATIONS)


class HeightSampler(EngagementSampler):
    def __init__(self, state):
        self.state = state                # HeightStock

    def measure_move(self, a, b, radius):
        state = self.state
        a, b = np.asarray(a, float), np.asarray(b, float)
        if radius <= 0 or not math.isfinite(radius):
            raise ValueError('3D engagement requires a positive tool radius')
        delta = b-a
        distance = float(np.linalg.norm(delta[:2]))
        lengths = np.array([distance])
        if not state.contact(a, b, radius):
            return np.zeros(1), np.zeros(1), np.zeros(1), lengths
        if distance < 1e-9:
            return np.array([radius]), np.array([radius]), np.ones(1), lengths
        tangent = delta[:2]/distance
        normal = np.array([-tangent[1], tangent[0]])
        n = max(SURFACE_CHORD_SAMPLES_MIN, min(SURFACE_CHORD_SAMPLES_MAX,
                                             int(math.ceil(radius/state.resolution))))
        forward, half_width, chord_offsets, stations = _chord_grid(radius, n)
        centers = (a[:2]+stations[:, None]*delta[:2])[:, None, :]+forward[None, :, None]*tangent
        offsets = chord_offsets[..., None]*normal
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
        patch = state._patch(a, b, radius)
        if patch is not None:
            region, swept_distance, tip = patch
            x = state.x[region[1]][None, :]
            y = state.y[region[0]][:, None]
            outside_start = (x-a[0])**2+(y-a[1])**2 > radius*radius+1e-9
            fresh = ((swept_distance <= radius*radius) & outside_start
                     & (state.heights[region] > tip+1e-3) & (state.heights[region] > state.bottom+1e-3))
            area_fraction = float(fresh.sum())*state.dx*state.dy/(2*radius*distance)
            engagement = max(engagement, min(1., area_fraction))
        if engagement <= 1e-6:
            # Do not call a sub-cell grazing cap contact air.
            engagement = .01
            left = right = engagement*radius
        return np.array([left]), np.array([right]), np.array([engagement]), lengths

    def remove_move(self, a, b, radius):
        self.state.cut(np.asarray(a, float), np.asarray(b, float), radius)
