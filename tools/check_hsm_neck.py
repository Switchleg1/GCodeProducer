"""Compare offline two-lobe front proposals on the same seeded pocket."""
import argparse
import json
import sys
from pathlib import Path

from shapely import from_wkt, union_all
from shapely.geometry import box

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.hsm_center_regions import CENTER_BUFFER_SEGMENTS, center_regions
from tools.hsm_front_corner import filleted_corner, frontier_corner_poses
from tools.hsm_front_run import run_front
from tools.hsm_straight_front import straight_front_candidates


def check_neck(*, with_corners=False):
    fixture = Path(__file__).resolve().parents[1] / 'examples' / 'adaptive-neck-pocket.wkt'
    pocket = from_wkt(fixture.read_text(encoding='utf-8'))
    cleared = union_all([box(5, 16, 22, 30), box(5, 12, 14, 34), box(20, 24, 25, 34)])
    stock = pocket.difference(cleared)
    seed = ((9., 28.5), (1., 0.))
    radius = 2.

    def propose(live, _pose):
        yield from straight_front_candidates(pocket, live, radius, .5, min_edge=2., lead=2., runoff=2.)
        if with_corners:
            for poses in frontier_corner_poses(pocket, live, radius, .5, lead=2.):
                path = filleted_corner(*poses, 3., .0025)
                if path is not None:
                    yield path

    diagnostics = []
    cuts, remaining, reason = run_front(pocket, stock, seed, propose, radius, max_cuts=12,
                                       contact_limit=60., sample_step=.1, link_handle=1., diagnostics=diagnostics)
    regions = center_regions(pocket, radius)
    reachable = union_all([r.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS) for r in regions])
    return {'stop': reason, 'regions': len(regions), 'cut_count': len(cuts),
            'corner_cut_count': sum(len(cut.cut) > 2 for cut in cuts),
            'initial_stock_mm2': stock.area, 'removed_mm2': stock.area - remaining.area,
            'reachable_residual_mm2': remaining.intersection(reachable).area,
            'last_selection_counts': diagnostics[-1] if diagnostics else {},
            'feed_mm': sum(cut.travel_mm for cut in cuts),
            'peak_contact_deg': max((cut.peak_deg for cut in cuts), default=None),
            'last_xy_mm': cuts[-1].cut[-1] if cuts else seed[0]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-corners', action='store_true', help='also propose 3 mm tangent corner blends')
    args = parser.parse_args()
    print(json.dumps(check_neck(with_corners=args.with_corners), indent=2))
