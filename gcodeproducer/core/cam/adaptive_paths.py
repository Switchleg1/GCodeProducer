"""CAM adapter: bounded stock-driven peeling followed by contour cleanup."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString
from shapely.prepared import prep

from .adaptive_branch import BranchChoice
from .adaptive_entry import AdaptiveEntry
from .adaptive_pocket import plan_pocket
from .cam_constants import ADAPTIVE_CAM_COMPONENTS, ADAPTIVE_CAM_LIMIT, ADAPTIVE_CAM_MAX_TURNS, ADAPTIVE_LINK_BUFFER_QUADS
from .paths import contour_pocket, link_contours
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.jobs.path import Path


def adaptive_paths(op, region, diameter, direction, log=None, *, material=None, cutting=None,
                   tool_type='endmill', tabs=False, depth_step=None):
    """Use the normal CAM lead and feed planner for every emitted XY path.

    The trial helix only supplies an orbit and simulated bottom footprint;
    its Z motion is not emitted. Contour cleanup is retained unless its
    entire sweep has already been covered by the emitted adaptive path.
    """
    radius = diameter/2
    contours = contour_pocket([], radius, op.stock, op.stepover, direction, region=region)
    centre = region.buffer(-(radius+op.stock))
    starters, swept = [], []
    budget = op.adaptive_peels
    if not isinstance(budget, int) or not 1 <= budget <= ADAPTIVE_CAM_MAX_TURNS:
        raise ValueError(f'Adaptive peel budget must be between 1 and {ADAPTIVE_CAM_MAX_TURNS}')
    left, accepted = budget, 0
    stops = []
    if not tabs and tool_type == 'endmill' and op.lead_in and op.stay_down:
        for component in sorted(polygons(centre), key=lambda p: (-p.area, p.bounds))[:ADAPTIVE_CAM_COMPONENTS]:
            if not left:
                break
            stock = component.buffer(diameter)
            if material is not None:
                stock = stock.intersection(material)
            if stock.is_empty:
                continue
            trial = plan_pocket(component, stock, top=0., depth=-(depth_step or op.stepdown),
                                lead_angle=op.lead_angle, entry_budget=1, turn_budget=left,
                                pitch=diameter*min(op.stepover, 50.)/100, tool_radius=radius,
                                limit=ADAPTIVE_CAM_LIMIT, min_loop_radius=.4*radius,
                                max_loop_radius=3*radius, cut_feed=cutting.feed if cutting else op.feed,
                                travel_feed=cutting.feed if cutting else op.feed,
                                z_feed=cutting.lead_feed if cutting else op.lead_feed, lift=radius,
                                sense=-1 if direction == 'conventional' else 1,
                                expand=True, half_turns=True, stay_down_only=True)
            stops.append(trial.status)
            if not trial.steps or not isinstance(trial.steps[0], AdaptiveEntry):
                continue
            entry = trial.steps[0].points
            xy = entry[entry[:, 2] == entry[-1, 2], :2]
            points = [xy]
            count = 0
            for step in trial.steps[1:]:
                if not isinstance(step, BranchChoice) or step.link.kind != 'stay_down':
                    break
                points.extend((step.link.points[1:], step.peel.points[1:]))
                count += 1
            left -= len(trial.steps)-1
            accepted += count
            if count:
                path = np.vstack(points)
                starters.append(Path('cut', path, width=diameter))
                swept.append(LineString(path).buffer(radius, quad_segs=ADAPTIVE_LINK_BUFFER_QUADS))
    if swept:
        from shapely import union_all
        covered = prep(union_all(swept))
        # Circumscribed contour sweep; if unsure, keep the cleanup contour.
        quads = ADAPTIVE_LINK_BUFFER_QUADS
        reach = radius / math.cos(math.pi/(2*quads)) + 1e-7
        contours = [p for p in contours if not covered.covers(
            LineString(np.vstack((p, p[0]))).buffer(reach, quad_segs=quads))]
    cleanup = link_contours(contours, [], radius, op.stock, direction, op.stay_down, region=region)
    if log:
        reasons = {
            'turn_budget': f'{budget}-peel planning budget reached',
            'entry_budget': 'no further stay-down peel met the stock, boundary and engagement checks',
            'no_entry': 'no entry orbit fits',
            'stalled': 'no useful cut found',
            'covered': 'trial stock cleared',
        }
        if tabs:
            why = 'holding tabs require contour planning'
        elif tool_type != 'endmill' or not op.lead_in or not op.stay_down:
            why = 'adaptive peels require a flat endmill, lead-in and stay-down'
        else:
            why = '; '.join(dict.fromkeys(reasons[s] for s in stops)) or 'no candidate stock'
        log(f'  {op.name}: Adaptive clearing: {accepted} peels, {len(cleanup)} cleanup contours ({why})')
    return starters + [Path('cut', p, closed=True, width=diameter, stay_down=link,
                            stay_down_from=tuple(cleanup[i-1][0][0]) if link else None)
                       for i, (p, link) in enumerate(cleanup)]
