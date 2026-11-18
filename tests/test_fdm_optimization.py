"""Optimized FDM kernels preserve ordering, samples and visibility decisions."""
import numpy as np
from shapely import covers, linestrings
from shapely.geometry import Polygon

from gcodeproducer.core.fdm.travel_router import _visible_edges
from gcodeproducer.core.geometry.infill import split_by_raster
from gcodeproducer.core.geometry.kernel import slice_planes, slice_z
from gcodeproducer.core.geometry.region_mask import RegionMask
from gcodeproducer.core.jobs.session import load_mesh


def test_indexed_planes_match_single_plane_slicing(cube_stl):
    mesh = load_mesh(cube_stl)
    planes = sorted({*np.linspace(-1, 21, 50), *mesh.vertices[:, 2], 22.})
    for z, batch in zip(planes, slice_planes(mesh, planes), strict=True):
        scalar = slice_z(mesh, z)
        assert len(batch) == len(scalar)
        for a, b in zip(batch, scalar):
            np.testing.assert_array_equal(a, b)


def test_raster_batches_match_individual_segments(monkeypatch):
    from gcodeproducer.core.geometry import geometry_constants

    monkeypatch.setattr(geometry_constants, 'RASTER_SAMPLE_BATCH', 110)
    mask = RegionMask([0, 0], [5, 5], .2)
    mask.grid[:, 6:12] = True
    second = mask.like(~mask.grid)
    second.grid[:, :15] = False
    segs = np.array([[[0., y], [5., y+.3]] for y in (0., 1., 2., 3., 4., 6.)])
    expected = np.concatenate([split_by_raster(segs[i:i+1], (mask, second), .4) for i in range(len(segs))])
    np.testing.assert_array_equal(split_by_raster(segs, (mask, second), .4), expected)


def test_visibility_reuse_preserves_edge_order(monkeypatch):
    from gcodeproducer.core.fdm import travel_router

    poly = Polygon([(0, 0), (6, 0), (6, 6), (0, 6)], [[(2, 2), (4, 2), (4, 4), (2, 4)]])
    points = [(1., 1.), (5., 5.), (1., 3.), (5., 3.), (1., 5.)]
    coords = np.asarray(points)
    cache, calls = {}, []

    def count(poly, lines):
        calls.append(len(lines))
        return covers(poly, lines)

    monkeypatch.setattr(travel_router, 'covers', count)
    ids = np.array([1, 3, 4])
    for wanted in (ids, ids[::-1]):
        expected = covers(poly, linestrings(np.stack((np.tile(coords[2], (len(ids), 1)),
                                                    coords[wanted]), axis=1)))
        np.testing.assert_array_equal(_visible_edges(poly, coords, points, 2, wanted, cache), expected)
    assert calls == [3, 1]  # only the changing destination was checked again
