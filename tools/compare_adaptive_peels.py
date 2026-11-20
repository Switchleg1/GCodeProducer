"""Compare four local turns in the broad lobe of the research outline."""
from pathlib import Path
import sys

import numpy as np
from shapely import from_wkt
from shapely.geometry import LineString, Point, box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


if __name__ == '__main__':
    main()
