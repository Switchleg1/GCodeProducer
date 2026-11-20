"""Reproduce the seeded, straight-only two-lobe HSM baseline offline."""
import json
import sys
from pathlib import Path

from shapely import from_wkt, union_all
from shapely.geometry import box

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.hsm_center_regions import CENTER_BUFFER_SEGMENTS, center_regions
from tools.hsm_front_run import run_front
from tools.hsm_straight_front import straight_front_candidates


def check_neck():
    fixture = Path(__file__).resolve().parents[1] / 'examples' / 'adaptive-neck-pocket.wkt'
    pocket = from_wkt(fixture.read_text(encoding='utf-8'))
    cleared = union_all([box(5, 16, 22, 30), box(5, 12, 14, 34), box(20, 24, 25, 34)])
    stock = pocket.difference(cleared)
    seed = ((9., 28.5), (1., 0.))
    radius = 2.

    def propose(live, _pose):
        return straight_front_candidates(pocket, live, radius, .5, min_edge=2., lead=2., runoff=2.)

    diagnostics = []
    cuts, remaining, reason = run_front(pocket, stock, seed, propose, radius, max_cuts=12,
                                       contact_limit=60., sample_step=.1, link_handle=1., diagnostics=diagnostics)
    regions = center_regions(pocket, radius)
    reachable = union_all([r.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS) for r in regions])
    return {'stop': reason, 'regions': len(regions), 'cut_count': len(cuts),
            'initial_stock_mm2': stock.area, 'removed_mm2': stock.area - remaining.area,
            'reachable_residual_mm2': remaining.intersection(reachable).area,
            'last_selection_counts': diagnostics[-1] if diagnostics else {},
            'feed_mm': sum(cut.travel_mm for cut in cuts),
            'peak_contact_deg': max((cut.peak_deg for cut in cuts), default=None),
            'last_xy_mm': cuts[-1].cut[-1] if cuts else seed[0]}


if __name__ == '__main__':
    print(json.dumps(check_neck(), indent=2))
