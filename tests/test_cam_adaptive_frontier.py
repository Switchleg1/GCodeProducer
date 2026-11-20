from pathlib import Path

import numpy as np
import pytest
from shapely import from_wkt, union_all
from shapely.geometry import LineString, Point, box

from gcodeproducer.core.cam.adaptive_frontier import discover_starts, trace_frontier


GEOMETRY = dict(pitch=1., tool_radius=1., min_loop_radius=1.5, max_loop_radius=2.)
RATES = dict(limit=.18, cut_feed=800, travel_feed=1200, z_feed=150, lift=3)


def test_frontier_discovers_both_cleared_patches_but_not_virgin_stock():
    blank = box(0, 0, 45, 25)
    region = blank.buffer(-1.)
    assert discover_starts((10, 12), region, blank, **GEOMETRY) == []
    material = blank.difference(union_all([Point(x, 10).buffer(3.1) for x in (10, 30)]))
    starts = discover_starts((10, 12), region, material, **GEOMETRY)
    assert starts[0][0][0] < 15 and starts[1][0][0] > 25
    for centre, seam, heading in starts:
        assert material.distance(Point(centre+seam)) > 1.
        np.testing.assert_allclose([-seam[1], seam[0]], heading*np.linalg.norm(seam))


def test_frontier_uses_half_turn_only_as_recovery(monkeypatch):
    from gcodeproducer.core.cam import adaptive_frontier

    centre, seam, heading = (10., 10.), (0., 2.), (-1., 0.)
    region = box(2., 2., 10.1, 18.)
    stock = box(0., 0., 30., 20.).difference(Point(centre).buffer(3.01, quad_segs=32))
    monkeypatch.setattr(adaptive_frontier, 'discover_starts', lambda *a, **k: [])
    args = ((10., 12.), region, stock)
    opts = dict(pitch=1., tool_radius=1., min_loop_radius=2., max_loop_radius=2.,
                continuation=(centre, seam, heading), **RATES)
    assert adaptive_frontier.choose_frontier_peel(*args, **opts) is None
    recovered = adaptive_frontier.choose_frontier_peel(*args, half_turns=True, **opts)
    assert recovered is not None and recovered.link.minutes == 0
    np.testing.assert_array_equal(recovered.peel.seam, (0., -2.))
    broad = (args[0], box(2., 2., 28., 18.), stock)
    normal = adaptive_frontier.choose_frontier_peel(*broad, **opts)
    enabled = adaptive_frontier.choose_frontier_peel(*broad, half_turns=True, **opts)
    assert normal is not None and enabled is not None
    np.testing.assert_array_equal(enabled.peel.points, normal.peel.points)


def test_frontier_trace_continues_without_reentry_from_a_cleared_seed():
    example = Path(__file__).resolve().parents[1] / 'examples/adaptive-neck-pocket.wkt'
    pocket = from_wkt(example.read_text())
    material = pocket.difference(Point(103, 30).buffer(3.1, quad_segs=32))
    region = pocket.buffer(-1.)
    trace = trace_frontier((103, 28), region, material, turns=4, **GEOMETRY, **RATES)
    assert len(trace) == 4
    assert all(choice.link.kind == 'stay_down' for choice in trace)
    assert all(choice.link.minutes == 0 for choice in trace[1:])
    for choice in trace:
        peel = choice.peel
        assert region.buffer(1e-7).covers(LineString(peel.points))
        assert 0 < peel.peak_engagement <= .18
        np.testing.assert_array_equal(choice.link.points[-1], peel.points[0])
    assert material.area - trace[-1].peel.remaining.area == pytest.approx(sum(c.peel.removed_area for c in trace))
