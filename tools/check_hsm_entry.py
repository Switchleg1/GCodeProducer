"""Audit the existing helical entry on intact synthetic neck stock (no export)."""
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, box

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gcodeproducer.core.cam.adaptive_entry import seed_entry
from gcodeproducer.core.cam.hsm_contact import contact_angle
from tools.check_hsm_neck import neck_fixture, write_opening_review, write_review_gcode
from tools.hsm_center_regions import center_regions, connected_clearance
from tools.hsm_contact_replay import indexed_contact
from tools.hsm_front_corner import turned_straight_candidates
from tools.hsm_front_run import run_front
from tools.hsm_straight_front import fitted_front_candidates, straight_front_candidates


def audit_entry(pocket, stock, points, radius, depth):
    """Credit only the contiguous floor sweep and independently check XY containment."""
    points = np.asarray(points)
    floor_index = int(np.argmax(points[:, 2] <= depth))
    if (not 0 < floor_index < len(points)-1 or np.any(points[floor_index:, 2] != depth)
            or np.any(np.diff(points[:, 2]) > 0)):
        raise ValueError('expected descending entry followed by a floor pass')
    route = LineString(points[:, :2])
    floor = LineString(points[floor_index:, :2])
    swept = floor.buffer(radius, quad_segs=32)
    remaining = stock.difference(swept)
    end = Point(points[-1, :2])
    xy_step = np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1)
    z_step = np.abs(np.diff(points[:, 2]))
    tilt = np.degrees(np.arctan2(z_step, xy_step))
    component = connected_clearance(pocket, remaining, end.coords[0], radius)
    return {'contained': pocket.covers(route) and route.distance(pocket.boundary) >= radius,
            'ramp_chords': floor_index, 'floor_chords': len(points)-floor_index-1,
            'max_ramp_deg': float(tilt.max()), 'floor_removed_mm2': stock.area-remaining.area,
            'end_stock_distance_mm': end.distance(remaining) if not remaining.is_empty else None,
            'connected_center_mm2': component.area,
            'floor_start_contact_without_ramp_credit_deg': contact_angle(tuple(floor.coords[0]), radius, stock)}


def entry_plane_contact(stock, points, radius, depth, plane, *, step=.025, limit=60.):
    """Replay only the XY sweep after descending through a fixed Z slice."""
    points = np.asarray(points, dtype=float)
    if not depth <= plane <= points[0, 2] or np.any(np.diff(points[:, 2]) > 0):
        raise ValueError('expected a slice in the descending entry range')
    hits = np.flatnonzero(points[:, 2] <= plane)
    if not len(hits):
        raise ValueError('entry does not reach the slice')
    start = int(hits[0])
    active = points[start:]
    if active[0, 2] < plane:
        a, b = points[start-1:start+1]
        crossing = a + (b-a)*((plane-a[2])/(b[2]-a[2]))
        active = np.vstack((crossing, active))
    arrival = contact_angle(tuple(active[0, :2]), radius, stock)
    phases = {name: {'xy_mm': 0., 'over_limit_xy_mm': 0., 'peak_deg': None} for name in ('descent', 'floor')}
    for chord, angle, distance in indexed_contact(active[:, :2], stock, radius, step, 32):
        segment = phases['descent' if active[chord, 2] > depth else 'floor']
        segment['xy_mm'] += distance
        if angle > limit:
            segment['over_limit_xy_mm'] += distance
        segment['peak_deg'] = max(angle, segment['peak_deg'] or 0.)
    return {'plane_z_mm': plane, 'arrival_xy_mm': active[0, :2].tolist(), 'arrival_contact_deg': arrival, **phases}


def axial_contact(stock, points, radius, *, bands, step=.025, limit=60.):
    """Estimate simultaneous over-limit axial thickness using midpoint Z bands."""
    path = np.asarray(points, dtype=float)
    depth = path[-1, 2]
    if (not isinstance(bands, int) or bands < 1 or not math.isfinite(step) or step <= 0
            or path[0, 2] <= depth or np.any(np.diff(path[:, 2]) > 0)):
        raise ValueError('expected positive sampling and a descending entry')
    band_height = (path[0, 2]-depth)/bands
    planes = [depth+(i+.5)*band_height for i in range(bands)]
    xmin, ymin = path[:, :2].min(axis=0)-radius
    xmax, ymax = path[:, :2].max(axis=0)+radius
    slices = [stock.intersection(box(xmin, ymin, xmax, ymax))]*bands
    phases = {name: {'xy_mm': 0., 'peak_over_limit_height_mm': 0., 'height_times_xy_mm2': 0.}
              for name in ('descent', 'floor')}
    for start, end in zip(path, path[1:]):
        distance = math.dist(start[:2], end[:2])
        count = max(1, math.ceil(distance/step))
        phase = phases['descent' if start[2] > depth else 'floor']
        a = start
        for i in range(1, count+1):
            b = end if i == count else start+(end-start)*(i/count)
            xy = tuple(b[:2])
            heavy = 0
            for j, plane in enumerate(planes):
                if b[2] > plane or slices[j].is_empty:
                    continue
                heavy += contact_angle(xy, radius, slices[j]) > limit
                contact_start = a if a[2] <= plane else a+(b-a)*((plane-a[2])/(b[2]-a[2]))
                start_xy = tuple(contact_start[:2])
                segment = Point(xy) if start_xy == xy else LineString([start_xy, xy])
                slices[j] = slices[j].difference(segment.buffer(radius, quad_segs=32))
            height = heavy*band_height
            phase['peak_over_limit_height_mm'] = max(height, phase['peak_over_limit_height_mm'])
            phase['height_times_xy_mm2'] += height*distance/count
            phase['xy_mm'] += distance/count
            a = b
    for phase in phases.values():
        integral = phase.pop('height_times_xy_mm2')
        phase['mean_over_limit_height_mm'] = integral/phase['xy_mm'] if phase['xy_mm'] else None
    return {'bands': bands, 'band_height_mm': band_height, **phases}


def neck_entry_region(pocket, radius):
    regions = center_regions(pocket, radius)
    return next(part for part in regions if part.covers(Point(9., 28.5))).intersection(box(0, 0, 24, 60))


def check_entry():
    pocket, seeded = neck_fixture()
    radius, top, depth = 2., 0., -2.
    entry = seed_entry(neck_entry_region(pocket, radius), pocket, radius=radius, top=top, depth=depth, lead_angle=10.)
    if entry is None:
        return {'stop': 'no_entry_candidate'}
    report = audit_entry(pocket, pocket, entry.points, radius, depth)
    report['slice_contacts'] = [entry_plane_contact(pocket, entry.points, radius, depth, z)
                                for z in (-.5, -1., -1.5, -2.)]
    report['axial_contacts'] = [axial_contact(pocket, entry.points, radius, bands=n) for n in (8, 16)]
    report['synthetic_preclear_mm2'] = pocket.area - seeded.area
    report['entry_end_xy_mm'] = entry.points[-1, :2].tolist()
    report['floor_accounting_delta_mm2'] = report['floor_removed_mm2'] - (pocket.area-entry.remaining.area)
    return report


def compare_pitch(*, bands=16, step=.025):
    """Compare pitch on intact stock, flagging any change to the final sweep."""
    pocket, _ = neck_fixture()
    radius, top, depth = 2., 0., -2.
    region = neck_entry_region(pocket, radius)
    trials = []
    baseline = None
    for angle in (10., 5., 2.5):
        entry = seed_entry(region, pocket, radius=radius, top=top, depth=depth, lead_angle=angle)
        if entry is None:
            trials.append({'angle_cap_deg': angle, 'stop': 'no_entry_candidate'})
            continue
        audit = audit_entry(pocket, pocket, entry.points, radius, depth)
        floor = entry.points[entry.points[:, 2] == depth]
        if angle == 10.:
            baseline = floor
        trials.append({'angle_cap_deg': angle, 'actual_max_angle_deg': audit['max_ramp_deg'],
                       'same_floor_and_exit': baseline is not None and np.array_equal(floor, baseline),
                       'contained': audit['contained'], 'floor_removed_mm2': audit['floor_removed_mm2'],
                       'contact': axial_contact(pocket, entry.points, radius, bands=bands, step=step)})
    return trials


def seed_arc_candidates(centre, orbit, *, contact_zone=None):
    """Bow beyond the nominal orbit or sampled live contact, then ease back."""
    origin = Point(centre) if contact_zone is not None else None
    for j in range(8):
        start = math.pi*j/4
        rows = []
        for i in range(33):
            t = i/32
            angle = start-math.pi*t/2
            ux, uy = math.cos(angle), math.sin(angle)
            distance = orbit
            if origin is not None:
                reach = orbit+1.2
                ray = LineString([centre, (centre[0]+reach*ux, centre[1]+reach*uy)])
                hit = ray.intersection(contact_zone)
                if hit.is_empty:
                    break
                distance = origin.distance(hit)
            if distance <= .3:
                break
            rows.append((ux, uy, distance-.3, math.sin(math.pi*t)**2))
        if len(rows) != 33:
            continue
        for advance in (.05, .10, .20):
            path = []
            for ux, uy, inner, blend in rows:
                r = inner + (.3+advance)*blend
                path.append((centre[0]+r*ux, centre[1]+r*uy))
            yield path


def seed_search_focus(fixed_focus, component, radius, *, follow=False):
    """Extend proposal search along live connected clearance; not a motion check."""
    if not follow or component.is_empty:
        return fixed_focus
    return fixed_focus.union(component.buffer(radius+.35))


def check_first_cut(*, review=None, second=False, max_cuts=None, fitted_straights=False, turned_straights=False, live_focus=False, longer_straights=False):
    """Check only the planar motion following the modeled helix floor sweep."""
    if longer_straights and not turned_straights:
        raise ValueError('longer straights require turned straights')
    if live_focus and not (fitted_straights or turned_straights):
        raise ValueError('live focus requires fitted or turned straights')
    pocket, _ = neck_fixture()
    radius = 2.
    entry = seed_entry(neck_entry_region(pocket, radius), pocket, radius=radius, top=0., depth=-2., lead_angle=2.5)
    if entry is None:
        return {'stop': 'no_entry_candidate'}
    a, b = entry.points[-2:, :2]
    pose = tuple(b), tuple(b-a)
    orbit = math.dist(a, b)
    stock = entry.remaining
    focus = Point(pose[0]).buffer(orbit + radius + 1.5)
    long_counts = {'endpoint_blocked': 0, 'endpoint_mapped': 0}

    long_outcomes = Counter()
    mapped_long = None

    def note_long_variant(path, mapped):
        nonlocal mapped_long
        long_counts['endpoint_mapped' if mapped else 'endpoint_blocked'] += 1
        if mapped:
            mapped_long = path

    def note_outcome(path, outcome):
        if path is mapped_long:
            long_outcomes[outcome] += 1

    def propose_straight(live, _pose, *, audit=True):
        yield from straight_front_candidates(pocket, live, radius, .5, min_edge=2., lead=2., runoff=2.)
        component = connected_clearance(pocket, live, pose[0], radius) if turned_straights or live_focus else None
        search = seed_search_focus(focus, component, radius, follow=live_focus)
        if fitted_straights:
            yield from fitted_front_candidates(pocket, live, radius, focus=search)
        if turned_straights:
            yield from turned_straight_candidates(pocket, live, radius, component, focus=search, longer=longer_straights,
                                                 on_long_variant=note_long_variant if audit else None)

    def propose_bow(live, _pose):
        occupied = None if live is stock else live.buffer(radius, quad_segs=32)
        return seed_arc_candidates(pose[0], orbit, contact_zone=occupied)

    diagnostics = []
    budget = max_cuts if max_cuts is not None else 2 if second else 1
    accepted, remaining, stop = run_front(pocket, stock, pose, propose_straight, radius, max_cuts=budget,
                                          contact_limit=60., sample_step=.025, link_handle=1., min_departure=.25,
                                          require_clear_exit=True, diagnostics=diagnostics, propose_on_stall=propose_bow,
                                          on_outcome=note_outcome if longer_straights else None)
    longest_chords = [max(math.dist(a, b) for a, b in zip(c.cut, c.cut[1:])) for c in accepted]
    initial_clearance = connected_clearance(pocket, stock, pose[0], radius)
    clearance = connected_clearance(pocket, remaining, pose[0], radius)
    report = {'stop': stop, 'straight_proposals': sum(1 for _ in propose_straight(stock, pose, audit=False)),
              'entry_removed_mm2': pocket.area-stock.area, 'cut_count': len(accepted),
              'straight_cut_count': sum(len(c.cut) == 2 for c in accepted),
              'cuts_with_chord_at_least_075_mm': sum(length >= .75-1e-9 for length in longest_chords),
              'cuts_with_chord_at_least_225_mm': sum(length >= 2.25-1e-9 for length in longest_chords),
              'longest_cut_chord_mm': max(longest_chords, default=None),
              'straight_removed_mm2': sum(c.removed_mm2 for c in accepted if len(c.cut) == 2),
              'last_gates': diagnostics[-1] if diagnostics else {},
              'total_removed_mm2': stock.area-remaining.area,
              'total_feed_mm': sum(c.travel_mm for c in accepted),
              'connected_area_gain_mm2': clearance.difference(initial_clearance).area,
              'search_east_x_mm': seed_search_focus(focus, clearance, radius, follow=live_focus).bounds[2],
              'connected_east_x_mm': None if clearance.is_empty else clearance.bounds[2],
              'connected_east_gain_mm': None if clearance.is_empty or initial_clearance.is_empty else
              clearance.bounds[2]-initial_clearance.bounds[2]}
    if longer_straights:
        report['long_variant_counts'] = long_counts
        report['long_variant_outcomes'] = dict(long_outcomes)
    if max_cuts is None:
        report['stop'] = ('no_checked_cut' if not accepted else 'first_cut_checked' if not second else
                          'two_cuts_checked' if len(accepted) == 2 else 'second_cut_stalled')
    for i, cut in enumerate(accepted[:2]):
        row = report if not i else report.setdefault('second', {})
        row.update(removed_mm2=cut.removed_mm2, peak_deg=cut.peak_deg, feed_mm=cut.travel_mm, gates=diagnostics[i])
    if accepted:
        report['peak_contact_deg'] = max(c.peak_deg for c in accepted)
        choice = accepted[0]
        if review is not None:
            opening = review.with_suffix('.opening.svg')
            if opening.exists():
                raise FileExistsError(f'review companion already exists: {opening}')
            write_review_gcode(review, accepted, pose[0], 'cuts after modeled floor sweep; helix omitted')
            write_opening_review(opening, pocket, stock, choice.link, choice.cut)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-pitch', action='store_true', help='compare shallower pitches at equal floor coverage')
    parser.add_argument('--first-cut', action='store_true', help='audit the first at-depth cut from the modeled floor sweep')
    parser.add_argument('--review-gcode', type=Path, help='save only checked planar first-cut geometry for review')
    parser.add_argument('--second-cut', action='store_true', help='also check a second cut on the updated stock')
    parser.add_argument('--seed-cut-budget', type=int, help='repeat checked live-front cuts up to this count')
    parser.add_argument('--fitted-straights', action='store_true', help='also fit straight cuts across short stock edges')
    parser.add_argument('--turned-straights', action='store_true', help='fit straight bodies with clearance-shaped turns')
    parser.add_argument('--live-seed-focus', action='store_true', help='extend fitted search with live seed clearance')
    parser.add_argument('--longer-straights', action='store_true', help='try longer bodies where the fit and clearance permit')
    args = parser.parse_args()
    if args.longer_straights and not args.turned_straights:
        parser.error('longer straights require turned straights')
    if args.live_seed_focus and not (args.fitted_straights or args.turned_straights):
        parser.error('live seed focus requires fitted or turned straights')
    cut_audit = args.first_cut or args.second_cut or args.seed_cut_budget is not None
    if (args.fitted_straights or args.turned_straights) and not cut_audit:
        parser.error('fitted straights require a cut audit')
    if args.seed_cut_budget is not None and args.seed_cut_budget < 1:
        parser.error('seed cut budget must be positive')
    if (cut_audit and args.compare_pitch) or (args.review_gcode and not cut_audit):
        parser.error('select one audit; review output requires a cut audit')
    result = (check_first_cut(review=args.review_gcode, second=args.second_cut, max_cuts=args.seed_cut_budget,
                              fitted_straights=args.fitted_straights, turned_straights=args.turned_straights,
                              live_focus=args.live_seed_focus, longer_straights=args.longer_straights) if cut_audit else
              compare_pitch() if args.compare_pitch else check_entry())
    print(json.dumps(result, indent=2))
