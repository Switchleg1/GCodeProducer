"""Planar clearing with rolling circular loops on parallel lanes."""
from __future__ import annotations

import math

import numpy as np
from shapely import covers, linestrings, prepare

from gcodeproducer.core.cam.cam_constants import (
    TROCHOID_CHORD_ERROR, TROCHOID_MIN_SEGMENTS, TROCHOID_POINT_BUDGET,
)
from gcodeproducer.core.cam.paths import boundary_paths
from gcodeproducer.core.geometry.infill import scan_fill
from gcodeproducer.core.jobs.path import Path


def trochoidal_paths(region, diameter, allowance, stepover, direction, log=None):
    """Fit rolling loops entirely inside the cutter-centre region.

    Each loop starts and ends on its lane as its centre advances by one pitch.
    If it cannot fit, keep the corresponding straight lane interval for coverage.
    The final wall passes clear along the outside boundary and around islands.
    """
    centre = region.buffer(-(diameter / 2 + allowance))
    walls = [points for points, _ in boundary_paths(centre, direction)]
    if not walls:
        raise ValueError("Trochoidal pocket is too small for this tool and stock allowance")
    spacing = diameter * min(stepover, 50.) / 100
    if log and stepover > 50.:
        log("  Trochoidal stepover capped at 50% for clearing coverage")
    radius = diameter / 4
    n = max(TROCHOID_MIN_SEGMENTS, math.ceil(math.pi / math.acos(max(-1., 1 - TROCHOID_CHORD_ERROR / radius))))
    fraction = np.linspace(0., 1., n + 1)
    theta = 2 * math.pi * fraction
    axial = radius * np.sin(theta)
    lateral = radius * (1 - np.cos(theta))
    axial[[0, -1]] = lateral[[0, -1]] = 0.
    lo_x, lo_y, hi_x, hi_y = centre.bounds
    along_x = hi_x - lo_x >= hi_y - lo_y
    extent = (hi_y - lo_y) if along_x else (hi_x - lo_x)
    if extent / spacing > TROCHOID_POINT_BUDGET // n:
        raise ValueError("Trochoidal pocket needs too many lanes; increase stepover")
    spans = scan_fill(walls, math.pi / 2 if along_x else 0., spacing, 0, 0)
    valid = centre.buffer(1e-7)  # numerical tolerance only; never clip loops through a wall
    prepare(valid)
    paths, loops, points = [], 0, sum(len(p) for p in walls)
    tested = points
    for i, (a, b) in enumerate(spans):
        alternate = direction == "meander" and i % 2 == 1
        if alternate:
            a, b = b, a
        length = float(np.linalg.norm(b - a))
        u = (b - a) / length
        v = np.array([-u[1], u[0]]) * (-1 if direction == "conventional" or alternate else 1)
        count = math.ceil(length / spacing)
        pitch = length / count
        tested += count * (n + 1)
        if tested > TROCHOID_POINT_BUDGET:
            raise ValueError("Trochoidal pocket has too many loop samples; increase stepover or split the area")
        local = (pitch * fraction + axial)[:, None] * u + lateral[:, None] * v
        candidates = a + (np.arange(count) * pitch)[:, None, None] * u + local
        # Pin seams to the shared lane points to keep the polyline continuous.
        seams = a + (np.arange(count + 1) * pitch)[:, None] * u
        seams[-1] = b
        candidates[:, 0] = seams[:-1]
        candidates[:, -1] = seams[1:]
        keep = np.flatnonzero(covers(valid, linestrings(candidates)))
        loops += len(keep)
        if len(keep):
            selected = candidates[keep]
            use = np.ones(selected.shape[:2], dtype=bool)
            use[1:, 0] = np.diff(keep) != 1
            use[0, 0] = keep[0] != 0
            chunks = [a[None], selected[use]]
            if keep[-1] != count - 1:
                chunks.append(b[None])
            pts = np.concatenate(chunks)
        else:
            pts = np.stack((a, b))
        points += len(pts)
        paths.append(Path("cut", pts, width=diameter))
    if log:
        log(f"  Trochoidal pocket: {loops:,} rolling loops, straight cuts where loops do not fit, {points:,} points")
    paths.extend(Path("cut", p, closed=True, width=diameter) for p in walls)
    return paths
