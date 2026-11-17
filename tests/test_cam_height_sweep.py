"""Height-grid sweep optimizations preserve the pointwise cutter model."""
import numpy as np
import pytest

from gcodeproducer.core.cam.height_stock import HeightStock
from gcodeproducer.core.cam.stock import Stock


@pytest.mark.parametrize('end', [(3.13, 2.12, -0.5), (3.13, 2.12, -1.25),
                                (3.13, 2.12, 1.25), (0.17, -0.31, -1.25),
                                (0.17000001, -0.31, -1.25)])
def test_sweep_matches_dense_grid(end):
    state = HeightStock(Stock(x=-1, y=-1, width=5.13, depth=4.29, height=4), .13)
    a = np.array([.17, -.31, -.5])
    b = np.asarray(end)
    r = .71
    region, distance, z = state._patch(a, b, r)
    x, y = np.meshgrid(state.x, state.y)
    d = b[:2] - a[:2]
    length = float(d @ d)
    raw = ((x - a[0])*d[0] + (y - a[1])*d[1])/max(length, 1e-20)
    t = np.clip(raw, 0, 1)
    expected_distance = (x - a[0] - t*d[0])**2 + (y - a[1] - t*d[1])**2
    if length < 1e-12:
        expected_z = np.full(x.shape, min(a[2], b[2]))
    else:
        perp = (x - a[0] - raw*d[0])**2 + (y - a[1] - raw*d[1])**2
        half = np.sqrt(np.maximum(r*r - perp, 0)/length)
        t = np.clip(raw + half if b[2] < a[2] else raw - half, 0, 1)
        expected_z = a[2] + t*(b[2] - a[2])
    np.testing.assert_array_equal(distance, expected_distance[region])
    np.testing.assert_array_equal(np.broadcast_to(z, distance.shape), expected_z[region])
    state.cut(a, b, r)
    expected_h = np.where(expected_distance <= r*r, np.minimum(0, expected_z), 0)
    np.testing.assert_array_equal(state.heights, expected_h.astype(np.float32))


def test_repeated_sweep_reuses_geometry_but_reads_live_heights(monkeypatch):
    state = HeightStock(Stock(width=5, depth=4, height=4), .1)
    a = np.array([1., 1., -.5])
    b = np.array([3., 2., -1.])
    r = .5
    sweep = state._sweep
    calls = []

    def record(a, b, radius):
        calls.append(radius)
        return sweep(a, b, radius)

    monkeypatch.setattr(state, '_sweep', record)
    assert state.contact(a, b, r)
    state.cut(a, b, r)
    assert not state.contact(a.copy(), b.copy(), r)
    assert calls == [r]
    assert state.contact(a, b, 2*r)
    assert calls == [r, 2*r]
