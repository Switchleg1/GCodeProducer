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
from tools.check_hsm_neck import clearance_sections, neck_fixture, widest_span, write_opening_review, write_review_gcode
from tools.hsm_center_regions import center_regions, connected_clearance
from tools.hsm_contact_replay import indexed_contact
from tools.hsm_front_choice import choose_front_cut
from tools.hsm_front_corner import parallel_face_candidates, turned_straight_candidates
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


def cut_efficiency(choice):
    cut_mm = sum(math.dist(a, b) for a, b in zip(choice.cut, choice.cut[1:]))
    return {'removed_mm2': choice.removed_mm2, 'cut_mm': cut_mm, 'link_mm': choice.travel_mm-cut_mm,
            'removed_per_feed_mm': choice.removed_mm2/choice.travel_mm}


def probe_parallel_face(pocket, body, after_cut, seed_xy, radius, gates):
    """Check a parallel return from an actual prior cut's remaining stock and pose."""
    live = after_cut.remaining
    a, b = after_cut.cut[-2:]
    next_pose = b, tuple(y-x for x, y in zip(a, b))
    component = connected_clearance(pocket, live, seed_xy, radius)
    counts = Counter()
    following = choose_front_cut(pocket, live, next_pose, parallel_face_candidates(body, component), radius,
                                 diagnostics=counts, **gates)
    audit = {'gates': dict(counts), 'prior_body_mm': math.dist(*body)}
    if following is not None:
        i = max(range(len(following.cut)-1), key=lambda k: math.dist(*following.cut[k:k+2]))
        body_line = LineString(following.cut[i:i+2])
        prefix = LineString(following.cut[:i+1]).buffer(radius, quad_segs=32)
        body_stock = live.difference(prefix).intersection(body_line.buffer(radius, quad_segs=32)).area
        audit.update(cut_efficiency(following), peak_deg=following.peak_deg,
                     body_mm=body_line.length, approximate_body_removal_mm2=body_stock)
    return following, audit


def search_face_neighbor(pocket, body, neighbors, seed_xy, radius, gates, *, eastward=False):
    """Evaluate each checked neighbor and its checked return as a two-cut pair."""
    best = None
    shortest = None
    count = 0
    for neighbor in neighbors:
        returning, audit = probe_parallel_face(pocket, body, neighbor, seed_xy, radius, gates)
        if returning is None:
            continue
        count += 1
        removed = neighbor.removed_mm2 + returning.removed_mm2
        travel = neighbor.travel_mm + returning.travel_mm
        key = (removed/travel, -audit['link_mm'])
        if eastward:
            clearance = connected_clearance(pocket, returning.remaining, seed_xy, radius)
            east = -math.inf if clearance.is_empty else round(clearance.bounds[2], 6)
            key = (east, *key)
        if best is None or key > best[0]:
            best = key, neighbor, returning, audit
        if shortest is None or audit['link_mm'] < shortest:
            shortest = audit['link_mm']
    report = {'checked_neighbors': len(neighbors), 'checked_pairs': count, 'shortest_return_link_mm': shortest}
    if best is None:
        return [], report
    key, neighbor, returning, audit = best
    report.update(neighbor=cut_efficiency(neighbor), returning=audit, pair_removed_per_feed_mm=key[-2])
    return [neighbor, returning], report


def extend_face_pairs(pocket, seed_xy, radius, gates, propose, prefix, count):
    """Resume from each checked return and fit the next pair against its live stock."""
    accepted = list(prefix)
    trace = []
    for _ in range(count):
        last = accepted[-1]
        body = max(zip(last.cut, last.cut[1:]), key=lambda edge: math.dist(*edge))
        a, b = last.cut[-2:]
        pose = b, tuple(y-x for x, y in zip(a, b))
        live = last.remaining
        options = []
        choose_front_cut(pocket, live, pose, propose(live, pose), radius,
                         on_eligible=lambda _, choice: options.append(choice), **gates)
        pair, record = search_face_neighbor(pocket, body, options, seed_xy, radius, gates, eastward=True)
        if not pair:
            return accepted, trace, 'no_checked_pair'
        accepted.extend(pair)
        component = connected_clearance(pocket, accepted[-1].remaining, seed_xy, radius)
        record.update(cut_count=len(accepted), east_x_mm=None if component.is_empty else component.bounds[2])
        trace.append(record)
    return accepted, trace, 'pair_budget'


def neck_facing_straight(path):
    """Require a straight body whose stock-left normal points predominantly east."""
    a, b = max(zip(path, path[1:]), key=lambda edge: math.dist(*edge))
    length = math.dist(a, b)
    return length >= .75-1e-9 and a[1]-b[1] >= .7*length


def east_opening_profile(regions, initial, current):
    """Measure contiguous center-clearance spans at fixed stations relative to the seed edge."""
    if initial.is_empty:
        return []
    east = initial.bounds[2]
    offsets = (-.5, -.25, 0., .125, .25, .375, .5)
    sections = clearance_sections(regions, current, [east+d for d in offsets])
    return [{'offset_mm': offset, 'x_mm': section['x_mm'], 'width_mm': widest_span(section),
             'connected_y_mm': section['connected_y_mm']} for offset, section in zip(offsets, sections)]


def check_first_cut(*, review=None, second=False, max_cuts=None, fitted_straights=False, turned_straights=False, live_focus=False, longer_straights=False, face_probe=False, face_after_neighbor=False, fit_face_neighbor=False, neck_face_pair=False, repeat_face_pairs=0):
    """Check only the planar motion following the modeled helix floor sweep."""
    if repeat_face_pairs < 0 or (repeat_face_pairs and not neck_face_pair):
        raise ValueError('repeating face pairs requires a nonnegative budget and a neck-facing pair')
    if neck_face_pair and not fit_face_neighbor:
        raise ValueError('neck-facing pair requires fitted neighbors')
    if fit_face_neighbor and not face_after_neighbor:
        raise ValueError('fitting a neighbor requires the neighbor return probe')
    if face_after_neighbor and not face_probe:
        raise ValueError('neighbor return requires the face probe')
    if face_probe and (not turned_straights or not second or max_cuts is not None):
        raise ValueError('face probe requires the two-cut turned-straight audit')
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
    best_long = {}
    neighbors = []
    mapped_long = None

    def note_long_variant(path, mapped):
        nonlocal mapped_long
        long_counts['endpoint_mapped' if mapped else 'endpoint_blocked'] += 1
        if mapped:
            mapped_long = path

    def note_outcome(path, outcome):
        if path is mapped_long:
            long_outcomes[outcome] += 1

    def note_ranked(index, key, choice):
        if fit_face_neighbor and index == 1:
            neighbors.append(choice)
        if choice.cut is mapped_long and (index not in best_long or key > best_long[index][0]):
            best_long[index] = key, cut_efficiency(choice)

    def propose_straight(live, _pose, *, audit=True):
        aim = neck_face_pair and live is stock
        if not aim:
            yield from straight_front_candidates(pocket, live, radius, .5, min_edge=2., lead=2., runoff=2.)
        component = connected_clearance(pocket, live, pose[0], radius) if turned_straights or live_focus else None
        search = seed_search_focus(focus, component, radius, follow=live_focus)
        if fitted_straights and not aim:
            yield from fitted_front_candidates(pocket, live, radius, focus=search)
        if turned_straights:
            paths = turned_straight_candidates(pocket, live, radius, component, focus=search, longer=longer_straights,
                                               on_long_variant=note_long_variant if audit else None)
            yield from filter(neck_facing_straight, paths) if neck_face_pair and live is stock else paths

    def propose_bow(live, _pose):
        if neck_face_pair and live is stock:
            return ()
        occupied = None if live is stock else live.buffer(radius, quad_segs=32)
        return seed_arc_candidates(pose[0], orbit, contact_zone=occupied)

    diagnostics = []
    budget = max_cuts if max_cuts is not None else 2 if second else 1
    gates = dict(contact_limit=60., sample_step=.025, link_handle=1., min_departure=.25, require_clear_exit=True)
    accepted, remaining, stop = run_front(pocket, stock, pose, propose_straight, radius, max_cuts=budget,
                                          diagnostics=diagnostics, propose_on_stall=propose_bow, **gates,
                                          on_outcome=note_outcome if longer_straights else None,
                                          on_ranked=note_ranked if longer_straights or fit_face_neighbor else None)
    longest_chords = [max(math.dist(a, b) for a, b in zip(c.cut, c.cut[1:])) for c in accepted]
    regions = center_regions(pocket, radius)
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
              clearance.bounds[2]-initial_clearance.bounds[2],
              'east_opening_profile': east_opening_profile(regions, initial_clearance, clearance)}
    if longer_straights:
        report['long_variant_counts'] = long_counts
        report['long_variant_outcomes'] = dict(long_outcomes)
        report['long_rank_comparisons'] = [
            {'cut': i+1, 'best_long': data, 'selected': cut_efficiency(accepted[i])}
            for i, (_, data) in sorted(best_long.items()) if i < len(accepted)]
    if max_cuts is None:
        report['stop'] = ('no_checked_cut' if not accepted else 'first_cut_checked' if not second else
                          'two_cuts_checked' if len(accepted) == 2 else 'second_cut_stalled')
    for i, cut in enumerate(accepted[:2]):
        row = report if not i else report.setdefault('second', {})
        row.update(removed_mm2=cut.removed_mm2, peak_deg=cut.peak_deg, feed_mm=cut.travel_mm, gates=diagnostics[i])
    if accepted:
        report['peak_contact_deg'] = max(c.peak_deg for c in accepted)
        choice = accepted[0]
        preview = accepted
        if face_probe:
            body = max(zip(choice.cut, choice.cut[1:]), key=lambda edge: math.dist(*edge))
            following, report['parallel_face_probe'] = probe_parallel_face(pocket, body, choice, pose[0], radius, gates)
            preview = [choice] if following is None else [choice, following]
            if face_after_neighbor:
                preview = list(accepted)
                if len(accepted) == 2:
                    returning, report['face_after_neighbor'] = probe_parallel_face(pocket, body, accepted[1],
                                                                                   pose[0], radius, gates)
                    if returning is not None:
                        preview.append(returning)
                    if fit_face_neighbor:
                        pair, report['fitted_face_neighbor'] = search_face_neighbor(pocket, body, neighbors,
                                                                                    pose[0], radius, gates, eastward=neck_face_pair)
                        preview = [choice, *pair]
                        if repeat_face_pairs and pair:
                            preview, trace, pair_stop = extend_face_pairs(pocket, pose[0], radius, gates,
                                                                          propose_straight, preview, repeat_face_pairs)
                            report['repeated_face_pairs'] = {'stop': pair_stop, 'trace': trace,
                                                             'peak_contact_deg': max(c.peak_deg for c in preview)}
                        final_stock = preview[-1].remaining
                        final_clear = connected_clearance(pocket, final_stock, pose[0], radius)
                        east = None if final_clear.is_empty else final_clear.bounds[2]
                        report['fitted_face_neighbor'].update(
                            connected_east_x_mm=east,
                            east_opening_profile=east_opening_profile(regions, initial_clearance, final_clear),
                            connected_east_gain_mm=None if east is None else east-initial_clearance.bounds[2],
                            preview_cut_count=len(preview), preview_removed_mm2=stock.area-final_stock.area,
                            preview_feed_mm=sum(c.travel_mm for c in preview))
        if review is not None:
            opening = review.with_suffix('.opening.svg')
            if opening.exists():
                raise FileExistsError(f'review companion already exists: {opening}')
            label = ('repeated neck-facing pair probe; helix omitted' if repeat_face_pairs else
                     'neck-facing pair probe; helix omitted' if neck_face_pair else
                     'fitted neighbor then parallel-face probe; helix omitted' if fit_face_neighbor else
                     'neighbor then parallel-face probe; helix omitted' if face_after_neighbor else
                     'parallel-face probe; helix omitted' if face_probe else 'cuts after modeled floor sweep; helix omitted')
            write_review_gcode(review, preview, pose[0], label)
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
    parser.add_argument('--follow-straight-face', action='store_true', help='probe a parallel continuation of the first straight')
    parser.add_argument('--face-after-neighbor', action='store_true', help='probe the parallel return after the greedy neighbor')
    parser.add_argument('--fit-face-neighbor', action='store_true', help='test each eligible neighbor before returning')
    parser.add_argument('--neck-face-pair', action='store_true', help='form an east-facing first face and prioritize pair reach')
    parser.add_argument('--repeat-face-pairs', type=int, default=0, help='probe this many extra live neck-facing pairs')
    args = parser.parse_args()
    if args.repeat_face_pairs < 0 or (args.repeat_face_pairs and not args.neck_face_pair):
        parser.error('a positive repeat budget requires --neck-face-pair')
    if args.neck_face_pair and not args.fit_face_neighbor:
        parser.error('neck-facing pair requires --fit-face-neighbor')
    if args.fit_face_neighbor and not args.face_after_neighbor:
        parser.error('fitting a neighbor requires --face-after-neighbor')
    if args.face_after_neighbor and not args.follow_straight_face:
        parser.error('neighbor return requires --follow-straight-face')
    if args.follow_straight_face and (not args.turned_straights or not args.second_cut or args.seed_cut_budget is not None):
        parser.error('face probe requires --second-cut --turned-straights without a cut budget')
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
                              live_focus=args.live_seed_focus, longer_straights=args.longer_straights, face_probe=args.follow_straight_face,
                              face_after_neighbor=args.face_after_neighbor, fit_face_neighbor=args.fit_face_neighbor,
                              neck_face_pair=args.neck_face_pair, repeat_face_pairs=args.repeat_face_pairs) if cut_audit else
              compare_pitch() if args.compare_pitch else check_entry())
    print(json.dumps(result, indent=2))
