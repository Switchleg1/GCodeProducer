import numpy as np
import pytest
from shapely.geometry import LineString, box

from gcodeproducer.core.cam.adaptive_entry import seed_entry
from gcodeproducer.core.cam.adaptive_frontier import trace_frontier
from gcodeproducer.core.cam.cam_constants import RAMP_TAN


def test_entry_respects_slope_and_credits_only_the_flat_lap():
    stock = box(0, 0, 20, 12)
    region = stock.buffer(-1).difference(box(11, 4, 16, 8))
    entry = seed_entry(region, stock, radius=1., top=0., depth=-1.5, sense=-1)
    assert entry is not None
    p = entry.points
    assert region.covers(LineString(p[:, :2]))
    assert p[0, 2] == 0 and p[-1, 2] == -1.5
    dz = -np.diff(p[:, 2])
    assert np.all(dz >= 0) and np.all(dz <= np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1)*RAMP_TAN+1e-12)
    flat = p[p[:, 2] == -1.5, :2]
    np.testing.assert_array_equal(flat[0], flat[-2])
    assert len(flat) > 20
    assert stock.difference(LineString(flat[:-1]).buffer(1.)).symmetric_difference(entry.remaining).area < 1e-8


def test_entry_declines_when_no_orbit_fits_or_depth_exceeds_budget():
    stock = box(0, 0, 20, 12)
    assert seed_entry(box(1, 1, 2, 1.01), stock, radius=1., top=0., depth=-1.) is None
    assert seed_entry(stock.buffer(-1), stock, radius=1., top=0., depth=-1e6) is None
    assert seed_entry(stock.buffer(-1), stock.difference(stock), radius=1., top=0., depth=-1.) is None


def test_fresh_stock_entry_hands_off_to_continuous_peeling():
    stock = box(0, 0, 20, 12)
    region = stock.buffer(-1.)
    entry = seed_entry(region, stock, radius=1., top=0., depth=-1.)
    trace = trace_frontier(entry.points[-1, :2], region, entry.remaining, turns=2, pitch=.6,
                           tool_radius=1., limit=.18, min_loop_radius=.45, max_loop_radius=.85,
                           cut_feed=800, travel_feed=1200, z_feed=150, lift=3.)
    assert len(trace) == 2 and all(c.link.kind == 'stay_down' for c in trace)
    assert trace[1].link.minutes == 0
    assert entry.remaining.area - trace[-1].peel.remaining.area == pytest.approx(sum(c.peel.removed_area for c in trace))
