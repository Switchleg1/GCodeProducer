"""Compare offline two-lobe front proposals on the same seeded pocket."""
import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from shapely import from_wkt, union_all
from shapely.geometry import Point, box

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.hsm_center_regions import CENTER_BUFFER_SEGMENTS, center_regions, connected_clearance, nearby_frontier
from tools.hsm_front_corner import (clearance_tapers, filleted_corner, frontier_corner_poses, roll_off, roll_on,
                                    shifted_roll_ons, tapered_roll_on)
from tools.hsm_front_run import run_front
from tools.hsm_live_waypoints import live_waypoints
from tools.hsm_tangent_link import forward_clearance
from tools.hsm_straight_front import eased_front_bite, frontier_edges, straight_advance, straight_front_candidates


def check_neck(*, with_corners=False, corner_runoff=0., with_detours=False,
               with_live_detours=False, with_shallow_fronts=False, shallow_runoff=2., shallow_rolloff=0.,
               shallow_rollon=0., with_shifted_joins=False, max_cuts=12, with_taper=False,
               with_clearance_tapers=False, with_early_exits=False, require_clear_exit=False,
               with_neck_front=False, with_three_leg_links=False, min_departure=0., prioritize_neck=False, with_front_bites=False, trace_clearance=False,
               prioritize_clearance=False, with_wide_bites=False):
    if not math.isfinite(corner_runoff) or corner_runoff < 0 or (corner_runoff and not with_corners):
        raise ValueError('corner runoff must be nonnegative and requires corner proposals')
    if not math.isfinite(shallow_runoff) or shallow_runoff < 0:
        raise ValueError('shallow runoff must be nonnegative')
    if not math.isfinite(shallow_rolloff) or shallow_rolloff < 0 or (shallow_rolloff and not with_shallow_fronts):
        raise ValueError('shallow roll-off must be nonnegative and requires shallow proposals')
    if not math.isfinite(shallow_rollon) or shallow_rollon < 0 or (shallow_rollon and not with_shallow_fronts):
        raise ValueError('shallow roll-on must be nonnegative and requires shallow proposals')
    if with_shifted_joins and not shallow_rollon:
        raise ValueError('shifted joins require a shallow roll-on radius')
    if (with_taper or with_clearance_tapers) and not with_shallow_fronts:
        raise ValueError('tapered approaches require shallow proposals')
    if with_early_exits and not (with_clearance_tapers and shallow_rolloff):
        raise ValueError('early exits require clearance tapers and a roll-off radius')
    if with_neck_front and not (with_shallow_fronts and shallow_rolloff):
        raise ValueError('neck-front proposals require shallow fronts and roll-off')
    if (with_front_bites or with_wide_bites) and not with_neck_front:
        raise ValueError('front bites require neck-front proposals')
    fixture = Path(__file__).resolve().parents[1] / 'examples' / 'adaptive-neck-pocket.wkt'
    pocket = from_wkt(fixture.read_text(encoding='utf-8'))
    cleared = union_all([box(5, 16, 22, 30), box(5, 12, 14, 34), box(20, 24, 25, 34)])
    stock = pocket.difference(cleared)
    seed = ((9., 28.5), (1., 0.))
    radius = 2.

    def propose(live, _pose):
        yield from straight_front_candidates(pocket, live, radius, .5, min_edge=2., lead=2., runoff=2.)
        if with_corners:
            for poses in frontier_corner_poses(pocket, live, radius, .5, lead=2., runoff=corner_runoff):
                path = filleted_corner(*poses, 3., .0025)
                if path is not None:
                    yield path

    taper_candidate = None
    taper_chords = 0
    overload_phases = defaultdict(Counter)

    def report_overload(round_index, path, segment, _angle):
        if path is taper_candidate:
            phase = 'approach' if segment < taper_chords else 'straight' if segment == taper_chords else 'exit'
            overload_phases[round_index][phase] += 1

    def propose_shallow(live, pose):
        nonlocal taper_candidate, taper_chords
        for path in straight_front_candidates(pocket, live, radius, .25, min_edge=2., lead=2., runoff=shallow_runoff):
            cut = roll_off(path, shallow_rolloff, .0025) if shallow_rolloff else path
            yield cut
            if shallow_rollon:
                yield roll_on(cut, shallow_rollon, .0025)
                if with_shifted_joins:
                    yield from shifted_roll_ons(cut, shallow_rollon, .0025, (2., 4.))
            if with_taper:
                yield tapered_roll_on(cut, 1.5, 4., .0025)
            if with_clearance_tapers:
                variants = [cut]
                start, end = path
                length = math.dist(start, end)
                if with_early_exits:
                    for trim in (1., 2.):
                        if length - trim <= radius:
                            continue
                        early_end = tuple(b - (b-a)*trim/length for a, b in zip(start, end))
                        variants.append(roll_off([start, early_end], shallow_rolloff, .0025))
                for variant in variants:
                    for taper in clearance_tapers(pocket, live, variant, radius, offset=1.5, run=4., chord_error=.0025):
                        taper_candidate = taper
                        taper_chords = len(taper) - len(variant)
                        yield taper
                        taper_candidate = None

        if with_neck_front:
            front = nearby_frontier(pocket, live, pose[0], radius, extra_reach=.25)
            if not front.is_empty:
                _, y0, x1, y1 = front.bounds
                focus = front.intersection(box(x1-3., y0-1., x1+1., y1+1.))
                for edge in frontier_edges(pocket, live, focus=focus):
                    if math.dist(*edge) < 2.:
                        continue
                    if with_front_bites:
                        yield eased_front_bite(edge, radius, .25, .25, .0025)
                    if with_wide_bites:
                        yield eased_front_bite(edge, radius, .25, .25, .0025, ramp_fraction=.25)
                    path = straight_advance(pocket, edge, radius, .25)
                    if path is not None:
                        cut = roll_off(path, shallow_rolloff, .0025)
                        yield from clearance_tapers(pocket, live, cut, radius, offset=1.5, run=4., chord_error=.0025)

    waypoints = tuple((xy, heading) for xy in ((10., 20.), (10., 27.), (17., 23.), (18., 28.))
                      for heading in ((1., 0.), (0., 1.), (-1., 0.), (0., -1.))) if with_detours else ()
    def propose_waypoints(live, pose):
        return live_waypoints(pocket, live, pose[0], radius, spacing=3., rings=4, limit=8)

    neck_target = pocket.intersection(box(24., 0., 134., 61.))
    def clearance_score(live):
        component = connected_clearance(pocket, live, seed[0], radius)
        return round(component.bounds[2], 6) if not component.is_empty else -math.inf

    diagnostics = []
    cuts, remaining, reason = run_front(pocket, stock, seed, propose, radius, max_cuts=max_cuts,
                                       contact_limit=60., sample_step=.1, link_handle=1., diagnostics=diagnostics,
                                       waypoints=waypoints,
                                       propose_waypoints=propose_waypoints if with_live_detours else None,
                                       propose_on_stall=propose_shallow if with_shallow_fronts else None,
                                       on_overload=report_overload if with_clearance_tapers else None,
                                       require_clear_exit=require_clear_exit, with_three_leg_links=with_three_leg_links,
                                       min_departure=min_departure, priority_region=neck_target if prioritize_neck else None,
                                       priority_score=clearance_score if prioritize_clearance else None)
    regions = center_regions(pocket, radius)
    reachable = union_all([r.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS) for r in regions])
    last_xy = cuts[-1].cut[-1] if cuts else seed[0]
    last_heading = seed[1]
    if cuts:
        previous = next(xy for xy in reversed(cuts[-1].cut[:-1]) if xy != last_xy)
        last_heading = tuple(b-a for a, b in zip(previous, last_xy))
    departure = forward_clearance(pocket, remaining, radius, last_xy, last_heading, 2*radius)
    point = Point(last_xy)
    initial_clearance = connected_clearance(pocket, stock, seed[0], radius)
    clearance = connected_clearance(pocket, remaining, seed[0], radius)
    frontier = nearby_frontier(pocket, remaining, last_xy, radius, extra_reach=.25)
    report = {'stop': reason, 'regions': len(regions), 'cut_count': len(cuts),
            'corner_cut_count': sum(len(cut.cut) > 2 for cut in cuts),
            'initial_stock_mm2': stock.area, 'removed_mm2': stock.area - remaining.area,
            'reachable_residual_mm2': remaining.intersection(reachable).area,
            'last_selection_counts': diagnostics[-1] if diagnostics else {},
            'last_taper_contact_failures': dict(overload_phases.get(len(diagnostics)-1, {})),
            'neckward_removed_mm2': stock.intersection(neck_target).difference(remaining).area,
            'seed_clearance_gain_mm2': clearance.difference(initial_clearance).area,
            'seed_clearance_east_x_mm': None if clearance.is_empty else clearance.bounds[2],
            'seed_clearance_reaches_neck_probe': clearance.covers(Point(36., 23.)),
            'feed_mm': sum(cut.travel_mm for cut in cuts),
            'peak_contact_deg': max((cut.peak_deg for cut in cuts), default=None),
            'last_xy_mm': last_xy,
            'last_forward_clearance_mm': departure,
            'nearby_frontier_mm': frontier.length,
            'nearby_frontier_bounds_mm': None if frontier.is_empty else frontier.bounds,
            'last_stock_distance_mm': None if remaining.is_empty else point.distance(remaining),
            'last_wall_distance_mm': point.distance(pocket.boundary)}
    if trace_clearance:
        probe = Point(36., 23.)
        trace = []
        travel = 0.
        for index, cut in enumerate((None, *cuts)):
            if cut is None:
                component = initial_clearance
            else:
                travel += cut.travel_mm
                component = connected_clearance(pocket, cut.remaining, seed[0], radius)
            trace.append({'cut': index, 'feed_mm': travel, 'area_mm2': component.area,
                          'east_x_mm': None if component.is_empty else component.bounds[2],
                          'reaches_probe': component.covers(probe)})
        report['clearance_trace'] = trace
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-corners', action='store_true', help='also propose 3 mm tangent corner blends')
    parser.add_argument('--corner-runoff', type=float, default=0., metavar='MM',
                        help='extend the tangent exit and check it as part of the cut')
    parser.add_argument('--with-detours', action='store_true', help='try fixed seed-area waypoints after failed direct links')
    parser.add_argument('--with-live-detours', action='store_true', help='sample waypoints from current clearance')
    parser.add_argument('--with-shallow-fronts', action='store_true', help='retry with 0.25 mm straight immersion when the main proposals fail')
    parser.add_argument('--shallow-runoff', type=float, default=2., metavar='MM',
                        help='tangent exit distance for shallow retries')
    parser.add_argument('--shallow-rolloff', type=float, default=0., metavar='MM',
                        help='append a checked tangent quarter turn of this radius to shallow cuts')
    parser.add_argument('--shallow-rollon', type=float, default=0., metavar='MM',
                        help='also try a tangent quarter-turn approach at this radius')
    parser.add_argument('--with-shifted-joins', action='store_true', help='also shift shallow joins by 2 and 4 mm')
    parser.add_argument('--max-cuts', type=int, default=12, help='maximum accepted cuts in the offline trial')
    parser.add_argument('--with-taper', action='store_true', help='try tapered entries on shallow cuts')
    parser.add_argument('--with-clearance-tapers', action='store_true', help='sample tapered starts from live clearance')
    parser.add_argument('--with-early-exits', action='store_true', help='try rolling off clearance tapers 1 or 2 mm earlier')
    parser.add_argument('--require-clear-exit', action='store_true',
                        help='reject cuts that end without planar link clearance')
    parser.add_argument('--with-neck-front', action='store_true', help='also try the east side of mapped live frontier')
    parser.add_argument('--with-three-leg-links', action='store_true', help='try two waypoints after direct and one-waypoint links fail')
    parser.add_argument('--min-departure', type=float, default=0., metavar='MM',
                        help='require a checked straight departure before ranking cuts')
    parser.add_argument('--prioritize-neck', action='store_true', help='rank checked cuts by removal east of X24 first')
    parser.add_argument('--with-front-bites', action='store_true', help='try eased side cuts on the neck-facing frontier')
    parser.add_argument('--trace-clearance', action='store_true', help='include connected clearance after each cut')
    parser.add_argument('--prioritize-clearance', action='store_true', help='rank verified cuts by seed-connected eastward extent first')
    parser.add_argument('--with-wide-bites', action='store_true', help='also try a straight plateau between eased ramps')
    args = parser.parse_args()
    try:
        result = check_neck(with_corners=args.with_corners, corner_runoff=args.corner_runoff,
                            with_detours=args.with_detours, with_live_detours=args.with_live_detours,
                            with_shallow_fronts=args.with_shallow_fronts, shallow_runoff=args.shallow_runoff,
                            shallow_rolloff=args.shallow_rolloff, shallow_rollon=args.shallow_rollon,
                            with_shifted_joins=args.with_shifted_joins, max_cuts=args.max_cuts, with_taper=args.with_taper,
                            with_clearance_tapers=args.with_clearance_tapers, with_early_exits=args.with_early_exits,
                            require_clear_exit=args.require_clear_exit, with_neck_front=args.with_neck_front,
                            with_three_leg_links=args.with_three_leg_links, min_departure=args.min_departure, prioritize_neck=args.prioritize_neck, with_front_bites=args.with_front_bites,
                            trace_clearance=args.trace_clearance, prioritize_clearance=args.prioritize_clearance,
                            with_wide_bites=args.with_wide_bites)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
