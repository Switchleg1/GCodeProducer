"""Adaptive clearing for the application: wavefront plans as CAM paths for one depth."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString

from gcodeproducer.core.jobs.path import Path
from .planner import clear_pocket
from .wavefront_constants import WAVEFRONT_LEFT_MM2, WAVEFRONT_SIMPLIFY


def contact_limit(op):
    """The contact angle (degrees) of a straight cut as wide as the operation's adaptive engagement."""
    width = op.adaptive_engagement/100
    if not math.isfinite(width) or not .001 <= width <= 1.:
        raise ValueError('Adaptive engagement limit must be between 0.1 and 100%')
    return math.degrees(math.acos(max(-1., 1 - 2*width)))


def plan_level(op, region, diameter, material=None, depth_step=None):
    """Plan one depth: (paths, summary). A plain function of picklable arguments, for worker processes.

    Every stay-down chain of cuts and links is one path. A path that begins at
    a start leads with the last lap of its helix orbit as a closed contour, so
    the lead planner ramps down on the orbit the plan's contact checks
    assumed, and the chain follows it without lifting. Stock to leave
    (op.stock) is kept from every wall.
    """
    radius = diameter/2
    pocket = region.buffer(-op.stock) if op.stock else region
    if pocket.is_empty or pocket.buffer(-radius).is_empty:
        raise ValueError(f'{op.name}: pocket is too small for this tool')
    limit = contact_limit(op)
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
    summary = {'left_mm2': report['reachable_residual_mm2'], 'stop': report['stop'],
               'fronts': report['front_arcs'], 'corner_moves': report['corners']['visits'],
               'limit_deg': limit, 'seconds': report['seconds']}
    return paths, summary


def plan_levels(op, levels, diameter):
    """plan_level for each (region, material, depth step) in levels, in worker processes when there are several.

    Returns the results in order; an exception is returned in place of a
    result, so one level that cannot be planned does not stop the others.
    """
    from functools import partial
    from gcodeproducer.core.fdm.layer_threads import process_pool
    work = partial(_plan_level_safely, op, diameter)
    pool = process_pool() if len(levels) > 1 else None
    if pool is None:
        return [work(level) for level in levels]
    try:
        return list(pool.map(work, levels))
    except Exception:
        return [work(level) for level in levels]  # a broken pool: plan here instead


def _plan_level_safely(op, diameter, level):
    region, material, depth_step = level
    try:
        return plan_level(op, region, diameter, material, depth_step)
    except ValueError as exc:
        return exc


def wavefront_paths(op, region, diameter, direction, log=None, *, material=None, cutting=None,
                    tool_type='endmill', tabs=False, depth_step=None, warn=None, depth_label='', planned=None):
    """XY cut paths for one planar region, for the normal CAM lead, feed and depth planner.

    See plan_level. planned, if given, is plan_level's result for exactly these
    arguments, worked out ahead (several depths at once in worker processes).
    The contact limit is the angle of a straight cut as wide as the sampled width
    limit (op.adaptive_engagement, percent of the cutter diameter). Stock the
    plan cannot reach is reported as an incomplete, debug-only result, never
    silently left.
    """
    if tabs or tool_type != 'endmill' or not op.lead_in or not op.stay_down:
        raise ValueError(f'{op.name}: Adaptive clearing requires a flat endmill, lead-in and stay-down, '
                         'and does not support this tab-protected area. No contour fallback was generated.')
    if direction == 'conventional':
        raise ValueError(f'{op.name}: Adaptive clearing cuts climb only; set the cutting direction to Climb.')
    contact_limit(op)
    if planned is None:
        planned = plan_level(op, region, diameter, material, depth_step)
    if isinstance(planned, Exception):
        raise planned
    paths, summary = planned
    left = summary['left_mm2']
    where = f' at {depth_label}' if depth_label else ''
    if left > WAVEFRONT_LEFT_MM2:
        message = (f'DEBUG ONLY — incomplete adaptive clearing: {op.name}{where} left {left:.3f} mm² of '
                   f'reachable stock ({summary["stop"]}, {summary["fronts"]} fronts). '
                   'Partial toolpath; do not run on a machine.')
        if not paths or warn is None:
            raise ValueError(message)
        warn(message)
    elif log:
        log(f'  {op.name}: Adaptive (wavefront) clearing{where}: {summary["fronts"]} fronts, '
            f'{summary["corner_moves"]} corner moves, {len(paths)} entries or lifts, '
            f'contact limit {summary["limit_deg"]:.0f}°, {left:.2f} mm² left, planned in {summary["seconds"]:.1f} s')
    return paths
