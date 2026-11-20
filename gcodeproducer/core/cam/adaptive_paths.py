"""CAM adapter: bounded stock-driven peeling with no contour fallback."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString
from shapely import union_all

from .adaptive_branch import BranchChoice
from .adaptive_entry import AdaptiveEntry
from .adaptive_pocket import plan_pocket
from .cam_constants import (
    ADAPTIVE_CAM_COMPONENTS, ADAPTIVE_CAM_LIMIT, ADAPTIVE_CAM_MAX_TURNS,
    ADAPTIVE_LINK_BUFFER_QUADS, ADAPTIVE_POCKET_AREA_EPS,
)
from .paths import contour_pocket
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.jobs.path import Path


def adaptive_paths(op, region, diameter, direction, log=None, *, material=None, cutting=None,
                   tool_type='endmill', tabs=False, depth_step=None):
    """Use the normal CAM lead and feed planner for every emitted XY path.

    The trial helix only supplies an orbit and simulated bottom footprint;
    its Z motion is not emitted. The conventional contour sweep is used
    only as a coverage reference, never emitted at adaptive depth.
    """
    if tabs or tool_type != 'endmill' or not op.lead_in or not op.stay_down:
        raise ValueError(f'{op.name}: Adaptive clearing requires a flat endmill, lead-in and stay-down, '
                         'and does not support this tab-protected area. No contour fallback was generated.')
    radius = diameter/2
    contours = contour_pocket([], radius, op.stock, op.stepover, direction, region=region)
    centre = region.buffer(-(radius+op.stock))
    starters, swept = [], []
    budget = op.adaptive_peels
    if not isinstance(budget, int) or not 1 <= budget <= ADAPTIVE_CAM_MAX_TURNS:
        raise ValueError(f'Adaptive peel budget must be between 1 and {ADAPTIVE_CAM_MAX_TURNS}')
    left, accepted = budget, 0
    stops = []
    components = sorted(polygons(centre), key=lambda p: (-p.area, p.bounds))
    if contours:
        for component in components[:ADAPTIVE_CAM_COMPONENTS]:
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
            path = np.vstack(points)
            starters.append(Path('cut', path, width=diameter))
            swept.append(LineString(path).buffer(radius, quad_segs=ADAPTIVE_LINK_BUFFER_QUADS))
    # Check the complete nominal coverage, including regions that exceeded the
    # component budget. Use an enclosing reference sweep; the actual sweep
    # credited above is polygonal and deliberately not enlarged.
    quads = ADAPTIVE_LINK_BUFFER_QUADS
    reach = radius / math.cos(math.pi/(2*quads)) + 1e-7
    required = union_all([LineString(np.vstack((p, p[0]))).buffer(reach, quad_segs=quads)
                          for p in contours])
    if material is not None:
        required = required.intersection(material)
    if required.is_empty:
        return []
    uncovered = required.difference(union_all(swept)).area
    if uncovered > ADAPTIVE_POCKET_AREA_EPS:
        reasons = {
            'turn_budget': f'{budget}-peel planning budget reached',
            'entry_budget': 'no further stay-down peel met the stock, boundary and engagement checks',
            'no_entry': 'no entry orbit fits',
            'stalled': 'no useful cut found',
            'covered': 'trial coverage did not satisfy the full coverage check',
        }
        why = '; '.join(dict.fromkeys(reasons[s] for s in stops)) or 'no eligible adaptive cut'
        raise ValueError(f'{op.name}: Adaptive clearing left {uncovered:.3f} mm² of reference stock '
                         f'at this depth ({why}). No contour fallback was generated. '
                         'If using another strategy, set a suitable depth per pass before regenerating.')
    if log:
        log(f'  {op.name}: Adaptive clearing: {accepted} peels; nominal coverage verified without contour cleanup')
    return starters
