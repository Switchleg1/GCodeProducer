import pytest
from shapely import union_all
from shapely.geometry import Point, box

from gcodeproducer.core.cam.adaptive_entry import AdaptiveEntry
from gcodeproducer.core.cam.adaptive_pocket import plan_pocket


SETTINGS = dict(top=0., depth=-1., lead_angle=4., pitch=.6, tool_radius=1., limit=.18,
                min_loop_radius=.45, max_loop_radius=.85, cut_feed=800, travel_feed=1200,
                z_feed=150, lift=3.)


def test_verified_entry_can_complete_small_region_without_peeling():
    region = box(-.25, -.25, .25, .25)
    stock = Point(0, 0).buffer(1.15)
    job = plan_pocket(region, stock, entry_budget=1, turn_budget=0, **SETTINGS)
    assert job.status == 'covered' and job.residual_area == pytest.approx(0.)
    assert len(job.steps) == 1 and isinstance(job.steps[0], AdaptiveEntry)


def test_pocket_accounts_for_uncut_stock_when_budget_expires():
    blank = box(0, 0, 20, 12)
    region = blank.buffer(-1.)
    job = plan_pocket(region, blank, entry_budget=1, turn_budget=0, **SETTINGS)
    assert job.status == 'turn_budget' and len(job.steps) == 1
    assert 0 < job.residual_area < job.initial_area
    assert job.residual_area == pytest.approx(job.remaining.intersection(region.buffer(1.)).area)


def test_pocket_supplies_only_cut_depth_entry_history(monkeypatch):
    from gcodeproducer.core.cam import adaptive_pocket

    blank = box(0, 0, 20, 12)
    captured = []

    def capture(*args, waypoints, **kwargs):
        captured.extend(waypoints)
        return None

    monkeypatch.setattr(adaptive_pocket, 'choose_frontier_peel', capture)
    result = plan_pocket(blank.buffer(-1), blank, entry_budget=1, turn_budget=1, **SETTINGS)
    entry, = result.steps
    depth_points = {tuple(p[:2]) for p in entry.points if p[2] == SETTINGS['depth']}
    assert captured and {tuple(p) for p in captured} <= depth_points
    assert tuple(entry.points[-1, :2]) in {tuple(p) for p in captured}


def test_pocket_reseeds_in_a_separate_fresh_patch():
    region = union_all([box(x-.25, -.25, x+.25, .25) for x in (0., 6.)])
    stock = union_all([Point(x, 0).buffer(1.15) for x in (0., 6.)])
    result = plan_pocket(region, stock, entry_budget=2, turn_budget=2, **SETTINGS)
    assert len(result.steps) == 2 and all(isinstance(s, AdaptiveEntry) for s in result.steps)
    assert abs(result.steps[0].points[-1, 0] - result.steps[1].points[-1, 0]) > 5.
    assert result.residual_area < result.initial_area/2
    assert result.status in ('entry_budget', 'covered')
