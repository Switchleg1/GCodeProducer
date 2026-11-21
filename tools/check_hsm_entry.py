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
from tools.hsm_front_choice import choose_front_cut
from tools.hsm_straight_front import straight_front_candidates


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


def check_first_cut(*, review=None, second=False):
    """Check only the planar motion following the modeled helix floor sweep."""
    pocket, _ = neck_fixture()
    radius = 2.
    entry = seed_entry(neck_entry_region(pocket, radius), pocket, radius=radius, top=0., depth=-2., lead_angle=2.5)
    if entry is None:
        return {'stop': 'no_entry_candidate'}
    a, b = entry.points[-2:, :2]
    pose = tuple(b), tuple(b-a)
    orbit = math.dist(a, b)
    stock = entry.remaining
    straight = list(straight_front_candidates(pocket, stock, radius, .5, min_edge=2., lead=2., runoff=2.))
    counts = Counter()
    gates = dict(contact_limit=60., sample_step=.025, link_handle=1., require_clear_exit=True, min_departure=.25)
    choice = choose_front_cut(pocket, stock, pose, seed_arc_candidates(pose[0], orbit), radius,
                              diagnostics=counts, **gates)
    report = {'stop': 'first_cut_checked' if choice else 'no_checked_cut', 'straight_proposals': len(straight),
              'gates': dict(counts), 'entry_removed_mm2': pocket.area-stock.area}
    if choice is not None:
        report.update(removed_mm2=choice.removed_mm2, peak_deg=choice.peak_deg, feed_mm=choice.travel_mm)
        accepted = [choice]
        if second:
            a, b = choice.cut[-2:]
            next_pose = b, tuple(y-x for x, y in zip(a, b))
            live = choice.remaining
            contact_zone = live.buffer(radius, quad_segs=32)
            counts = Counter()
            following = choose_front_cut(pocket, live, next_pose,
                                         seed_arc_candidates(pose[0], orbit, contact_zone=contact_zone), radius,
                                         diagnostics=counts, **gates)
            report['second'] = {'gates': dict(counts)}
            if following is not None:
                report['stop'] = 'two_cuts_checked'
                report['second'].update(removed_mm2=following.removed_mm2, peak_deg=following.peak_deg,
                                        feed_mm=following.travel_mm)
                accepted.append(following)
            else:
                report['stop'] = 'second_cut_stalled'
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
    args = parser.parse_args()
    cut_audit = args.first_cut or args.second_cut
    if (cut_audit and args.compare_pitch) or (args.review_gcode and not cut_audit):
        parser.error('select one audit; review output requires a cut audit')
    result = (check_first_cut(review=args.review_gcode, second=args.second_cut) if cut_audit else
              compare_pitch() if args.compare_pitch else check_entry())
    print(json.dumps(result, indent=2))
