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


def check_entry():
    pocket, seeded = neck_fixture()
    radius, top, depth = 2., 0., -2.
    regions = center_regions(pocket, radius)
    left = next(part for part in regions if part.covers(Point(9., 28.5))).intersection(box(0, 0, 24, 60))
    entry = seed_entry(left, pocket, radius=radius, top=top, depth=depth, lead_angle=10.)
    if entry is None:
        return {'stop': 'no_entry_candidate'}
    report = audit_entry(pocket, pocket, entry.points, radius, depth)
    report['synthetic_preclear_mm2'] = pocket.area - seeded.area
    report['entry_end_xy_mm'] = entry.points[-1, :2].tolist()
    report['floor_accounting_delta_mm2'] = report['floor_removed_mm2'] - (pocket.area-entry.remaining.area)
    return report


if __name__ == '__main__':
    print(json.dumps(check_entry(), indent=2))
