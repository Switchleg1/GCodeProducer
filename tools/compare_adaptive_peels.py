"""Compare four local turns in the broad lobe of the research outline."""
from pathlib import Path
import sys

import numpy as np
from shapely import from_wkt
from shapely.geometry import LineString, Point, box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gcodeproducer.core.cam.adaptive_frontier import trace_frontier
from gcodeproducer.core.cam.adaptive_link import choose_link
from gcodeproducer.core.cam.adaptive_peel import _turn, choose_peel, evaluate_peel, trace_peels


def main():
    pocket = from_wkt((ROOT / 'examples/adaptive-neck-pocket.wkt').read_text())
    start = np.array([103., 30.])
    heading = np.array([-1., 0.])
    seam = np.array([0., -2.])
    radius, pitch, limit = 1., 1., .14
    region = pocket.buffer(-radius)
    initial = pocket.difference(Point(start).buffer(3.01, quad_segs=32))
    print('Mode       Turns  Peak width  Advance [mm]  Removed [mm²]  Path [mm]')
    for adaptive in (False, True):
        centre, material = start.copy(), initial
        peaks, removed, distance = [], 0., 0.
        for _ in range(4):
            if adaptive:
                choice = choose_peel(centre, seam, heading, pitch, radius, limit, region, material)
                if choice is None:
                    break
                peak, area, length = choice.peak_engagement, choice.removed_area, choice.length
                centre, material = choice.centre, choice.remaining
            else:
                points = _turn(centre, seam, heading*pitch, 1, radius)
                if not region.covers(LineString(points)):
                    break
                peak, area, length, material = evaluate_peel(points, material, radius)
                centre += heading*pitch
            peaks.append(peak)
            removed += area
            distance += length
        print(f'{"Adaptive" if adaptive else "Fixed":<10} {len(peaks):>5} {max(peaks, default=0):>11.1%} '
              f'{np.linalg.norm(centre-start):>13.2f} {removed:>14.2f} {distance:>10.2f}')
    print('Local turns only; unequal removal. No cycle-time or whole-pocket comparison.')

    trace = trace_frontier(start+seam, region, pocket.difference(Point(start).buffer(3.1, quad_segs=32)),
                           turns=4, pitch=pitch, tool_radius=radius, limit=.18,
                           min_loop_radius=1.5, max_loop_radius=2., cut_feed=800,
                           travel_feed=1200, z_feed=150, lift=3)
    print(f'Discovered course: {len(trace)} turns, {sum(c.peel.removed_area for c in trace):.2f} mm² removed, '
          f'{max((c.peel.peak_engagement for c in trace), default=0):.1%} peak sampled engagement, '
          f'{sum(c.link.minutes > 0 for c in trace)} transfer(s).')

    # A tight wall makes the straight course infeasible without steering and
    # shrinking. Keep the local experiment distinct from the lobe benchmark.
    region = box(2, 2, 12.04, 18)
    centre = np.array([10., 10.])
    stock = box(0, 0, 40, 20).difference(Point(centre).buffer(3.01, quad_segs=32))
    seam, heading = (0., 2.), (1., 0.)
    fixed = choose_peel(centre, seam, heading, pitch, radius, limit, region, stock)
    steered = trace_peels(centre, seam, heading, pitch, radius, limit, region, stock,
                          min_loop_radius=1.4, max_loop_radius=2.5, turns=8)
    print(f'Wall case: {int(fixed is not None)} fixed start(s), {len(steered)} continuous steered turns; '
          f'{sum(p.removed_area for p in steered):.2f} mm² removed.')

    blank = box(0, 0, 30, 30)
    start, via, end = (5, 5), (5, 20), (20, 20)
    region = blank.buffer(-radius)
    material = blank.difference(LineString([start, via, end]).buffer(1.5))
    print('Cleared corridor, 3 mm lift:')
    for feed in (150, 1200):
        link = choose_link(start, end, region, material, radius, travel_feed=1200, z_feed=feed,
                           lift=3, waypoints=[via])
        print(f'  Z feed {feed:>4} mm/min: {link.kind}, {link.minutes*60:.2f} s estimated.')


if __name__ == '__main__':
    main()
