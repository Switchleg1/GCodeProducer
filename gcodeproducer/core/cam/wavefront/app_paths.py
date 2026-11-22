"""Adaptive clearing for the application: wavefront plans as CAM paths for one depth."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString

from gcodeproducer.core.jobs.path import Path
from .planner import clear_pocket
from .wavefront_constants import WAVEFRONT_LEFT_MM2, WAVEFRONT_SIMPLIFY


def wavefront_paths(op, region, diameter, direction, log=None, *, material=None, cutting=None,
                    tool_type='endmill', tabs=False, depth_step=None, warn=None, depth_label=''):
    """XY cut paths for one planar region, for the normal CAM lead, feed and depth planner.

    Every stay-down chain of cuts and links is one path. A path that begins at
    a start leads with the last lap of its helix orbit, so the lead planner
    ramps down on the orbit the plan's contact checks assumed. Stock to leave
    (op.stock) is kept from every wall. The sampled width limit
    (op.adaptive_engagement, percent of the cutter diameter) becomes the
    contact angle of a straight cut that wide. Stock the plan cannot reach is
    reported as an incomplete, debug-only result, never silently left.
    """
    if tabs or tool_type != 'endmill' or not op.lead_in or not op.stay_down:
        raise ValueError(f'{op.name}: Adaptive clearing requires a flat endmill, lead-in and stay-down, '
                         'and does not support this tab-protected area. No contour fallback was generated.')
    if direction == 'conventional':
        raise ValueError(f'{op.name}: Adaptive clearing cuts climb only; set the cutting direction to Climb.')
    width = op.adaptive_engagement/100
    if not math.isfinite(width) or not .001 <= width <= 1.:
        raise ValueError('Adaptive engagement limit must be between 0.1 and 100%')
    radius = diameter/2
    pocket = region.buffer(-op.stock) if op.stock else region
    if pocket.is_empty or pocket.buffer(-radius).is_empty:
        raise ValueError(f'{op.name}: pocket is too small for this tool')
    limit = math.degrees(math.acos(max(-1., 1 - 2*width)))
    strokes, residual, report = clear_pocket(pocket, radius, limit=limit, material=material,
                                             top=0., depth=-(depth_step or op.stepdown), lead_angle=op.lead_angle)
    leads = {entry['stroke']: np.asarray(entry['helix_xyz'], float) for entry in report['entries']}
    paths, chain, after = [], [], [None]

    def flush():
        if len(chain) > 1:
            line = LineString(chain).simplify(WAVEFRONT_SIMPLIFY)
            path = Path('cut', np.asarray(line.coords, float), width=diameter)
            if after[0] is not None:
                path.stay_down, path.stay_down_from = True, after[0]
            paths.append(path)
        chain.clear()
        after[0] = None

    for index, stroke in enumerate(strokes):
        points = [tuple(q) for q in stroke.points]
        if not chain or math.dist(chain[-1], points[0]) > 1e-6 or index in leads:
            flush()
            helix = leads.get(index)
            if helix is not None and len(helix):
                # The last lap of the helix, as a closed contour the lead planner ramps down on;
                # the cuts then follow at depth without lifting.
                lap = helix[np.isclose(helix[:, 2], helix[-1, 2]), :2]
                if len(lap) > 2 and math.dist(lap[0], lap[-1]) < 1e-6:
                    lap = lap[:-1]
                if len(lap) > 2:
                    paths.append(Path('cut', np.asarray(lap, float), closed=True, width=diameter))
                    after[0] = tuple(float(v) for v in lap[0])
                    if math.dist(lap[0], points[0]) > 1e-6:
                        chain.append(tuple(lap[0]))
        if chain and math.dist(chain[-1], points[0]) < 1e-9:
            points = points[1:]
        chain.extend(points)
    flush()
    left = report['reachable_residual_mm2']
    where = f' at {depth_label}' if depth_label else ''
    if left > WAVEFRONT_LEFT_MM2:
        message = (f'DEBUG ONLY — incomplete adaptive clearing: {op.name}{where} left {left:.3f} mm² of '
                   f'reachable stock ({report["stop"]}, {report["front_arcs"]} fronts). '
                   'Partial toolpath; do not run on a machine.')
        if not paths or warn is None:
            raise ValueError(message)
        warn(message)
    elif log:
        log(f'  {op.name}: Adaptive (wavefront) clearing{where}: {report["front_arcs"]} fronts, '
            f'{report["corners"]["visits"]} corner moves, {len(paths)} entries or lifts, '
            f'contact limit {limit:.0f}°, {left:.2f} mm² left')
    return paths
