"""CAM adapter: bounded stock-driven peeling with no contour fallback."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely import union_all

from .adaptive_branch import BranchChoice
from .adaptive_entry import AdaptiveEntry
from .adaptive_finish import AdaptiveFinish, checked_finish, finish_geometry
from .adaptive_pocket import plan_pocket
from .cam_constants import (
    ADAPTIVE_CAM_COMPONENTS, ADAPTIVE_CAM_POINT_LIMIT,
    ADAPTIVE_LINK_BUFFER_QUADS, ADAPTIVE_POCKET_AREA_EPS,
)
from .paths import contour_pocket
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.core.cam.operation import Operation


def adaptive_paths(op, region, diameter, direction, log=None, *, material=None, cutting=None,
                   tool_type='endmill', tabs=False, depth_step=None, warn=None, depth_label=''):
    """Use the normal CAM lead and feed planner for every emitted XY path.

    The trial helix only supplies an orbit and simulated bottom footprint;
    its Z motion is not emitted. The conventional contour sweep is used
    as a coverage reference. Finish contours are accepted only after checking
    them against progressive stock at the same engagement limit as the peels.
    """
    if tabs or tool_type != 'endmill' or Operation.lead_mode(op.lead_in) == 'none' or not op.stay_down:
        raise ValueError(f'{op.name}: Adaptive clearing requires a flat endmill, lead-in and stay-down, '
                         'and does not support this tab-protected area. No contour fallback was generated.')
    limit = op.adaptive_engagement/100
    if not math.isfinite(limit) or not .001 <= limit <= 1.:
        raise ValueError('Adaptive engagement limit must be between 0.1 and 100%')
    radius = diameter/2
    contours = contour_pocket([], radius, op.stock, op.stepover, direction, region=region)
    centre = region.buffer(-(radius+op.stock))
    starters, swept = [], []
    accepted = finished = 0
    quads = ADAPTIVE_LINK_BUFFER_QUADS
    references = [(p, LineString(np.vstack((p, p[0]))).buffer(radius, quad_segs=quads)) for p in contours]
    required = union_all([sweep for _, sweep in references])
    if material is not None:
        required = required.intersection(material)
    if required.is_empty:
        return []
    rates = dict(travel_feed=cutting.feed if cutting else op.feed,
                 z_feed=cutting.lead_feed if cutting else op.lead_feed, lift=radius)
    stops = []
    components = sorted(polygons(centre), key=lambda p: (-p.area, p.bounds))
    if contours:
        for component in components[:ADAPTIVE_CAM_COMPONENTS]:
            stock = component.buffer(diameter)
            if material is not None:
                stock = stock.intersection(material)
            if stock.is_empty:
                continue
            local = [(p, sweep) for p, sweep in references if component.distance(Point(p[0])) <= 1e-7]
            target = union_all([sweep for _, sweep in local])

            contours_here = [p for p, _ in reversed(local)]
            finish_candidates = finish_geometry(contours_here, component, radius)

            def finish(position, remaining):
                return checked_finish(position, contours_here, component, remaining,
                                      radius, limit, target=target, candidates=finish_candidates, **rates)

            trial = plan_pocket(component, stock, top=0., depth=-(depth_step or op.stepdown),
                                lead_angle=op.lead_angle, entry_budget=ADAPTIVE_CAM_POINT_LIMIT,
                                point_budget=ADAPTIVE_CAM_POINT_LIMIT,
                                finish=finish,
                                pitch=diameter*min(op.stepover, 50.)/100, tool_radius=radius,
                                limit=limit, min_loop_radius=.4*radius,
                                max_loop_radius=3*radius, cut_feed=cutting.feed if cutting else op.feed,
                                sense=-1 if direction == 'conventional' else 1,
                                expand=True, half_turns=True, stay_down_only=True, recover_heading=True, **rates)
            stops.append(trial.status)
            if not trial.steps or not isinstance(trial.steps[0], AdaptiveEntry):
                continue
            points = []

            def flush():
                if points:
                    path = np.vstack(points)
                    starters.append(Path('cut', path, width=diameter))
                    swept.append(LineString(path).buffer(radius, quad_segs=quads))
                    points.clear()

            for step in trial.steps:
                if isinstance(step, AdaptiveEntry):
                    flush()
                    entry = step.points
                    points.append(entry[entry[:, 2] == entry[-1, 2], :2])
                elif isinstance(step, AdaptiveFinish):
                    points.append(step.points[1:])
                    finished += step.contours
                elif isinstance(step, BranchChoice) and step.link.kind == 'stay_down':
                    points.extend((step.link.points[1:], step.peel.points[1:]))
                    accepted += 1
                else:
                    raise ValueError(f'{op.name}: adaptive plan contains an unsupported transfer')
            flush()
    # Keep checking overall nominal coverage, even for unscheduled components.
    uncovered = required.difference(union_all(swept)).area
    if uncovered > ADAPTIVE_POCKET_AREA_EPS:
        reasons = {
            'point_budget': 'adaptive path point safety limit reached',
            'checked_finish': 'checked finish did not cover all components',
            'entry_budget': 'no further stay-down peel met the stock, boundary and engagement checks',
            'no_entry': 'no entry orbit fits',
            'stalled': 'no useful cut found',
            'covered': 'trial coverage did not satisfy the full coverage check',
        }
        why = '; '.join(dict.fromkeys(reasons[s] for s in stops)) or 'no eligible adaptive cut'
        where = f' at {depth_label}' if depth_label else ''
        message = (f'DEBUG ONLY — incomplete adaptive clearing: {op.name}{where} left '
                   f'{uncovered:.3f} mm² of reference stock after {accepted} peels and {len(starters)} entries ({why}). '
                   'Partial toolpath; do not run on a machine.')
        if not starters or warn is None:
            raise ValueError(message)
        warn(message)
    elif log:
        log(f'  {op.name}: Adaptive clearing: {accepted} peels; {finished} engagement-checked finish contours; nominal coverage verified')
    return starters
