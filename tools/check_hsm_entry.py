"""Audit the existing helical entry on intact synthetic neck stock (no export)."""
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, box

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gcodeproducer.core.cam.adaptive_entry import seed_entry
from gcodeproducer.core.cam.hsm_contact import contact_angle
from tools.check_hsm_neck import neck_fixture
from tools.hsm_center_regions import center_regions, connected_clearance
from tools.hsm_contact_replay import indexed_contact


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


def check_entry():
    pocket, seeded = neck_fixture()
    radius, top, depth = 2., 0., -2.
    regions = center_regions(pocket, radius)
    left = next(part for part in regions if part.covers(Point(9., 28.5))).intersection(box(0, 0, 24, 60))
    entry = seed_entry(left, pocket, radius=radius, top=top, depth=depth, lead_angle=10.)
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


if __name__ == '__main__':
    print(json.dumps(check_entry(), indent=2))
