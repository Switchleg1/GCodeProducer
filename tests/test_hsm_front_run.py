import pytest
from shapely.geometry import Polygon, box

from tools.hsm_front_run import run_front
from tools.hsm_straight_front import frontier_edges, straight_advance


POCKET = box(0, 0, 24, 12)
STOCK = box(5, 5, 9, 7).union(box(14, 5, 18, 7))
SEED = ((3., 4.25), (1., 0.))


def _run(propose, stock=STOCK, budget=5):
    return run_front(POCKET, stock, SEED, propose, 1., max_cuts=budget,
                     contact_limit=60., sample_step=.05, link_handle=.5)


def _candidates(stock, _pose):
    # Fixture strategy: only advance the original horizontal face of each pad.
    for a, b in frontier_edges(POCKET, stock):
        if a[1] == b[1] == 5. and b[0]-a[0] > 3.:
            yield straight_advance(POCKET, (a, (b[0]+1., b[1])), 1., .25, lead=1.)


def test_runner_advances_from_new_pose_and_reports_live_residual_at_stall():
    snapshots = []

    def propose(stock, pose):
        snapshots.append((stock.area, pose[0]))
        return _candidates(stock, pose)

    choices, remaining, reason = _run(propose)
    assert [xy for _, xy in snapshots] == [SEED[0], (10., 4.25), (19., 4.25)]
    assert [area for area, _ in snapshots] == pytest.approx([16., 15., 14.])
    assert [choice.removed_mm2 for choice in choices] == pytest.approx([1., 1.])
    assert remaining.area == pytest.approx(14.)
    assert reason == 'stalled'


def test_budget_and_empty_stock_do_not_report_a_stall():
    choices, remaining, reason = _run(_candidates, budget=1)
    assert len(choices) == 1 and remaining.area == pytest.approx(15.)
    assert reason == 'cut_budget'
    assert _run(_candidates, Polygon())[2] == 'stock_empty'
