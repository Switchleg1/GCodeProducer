from pathlib import Path

import pytest
from shapely import from_wkt
from shapely.geometry import Point, box

from tools.hsm_center_regions import center_regions, cleared_start_intervals, map_region_work, nearby_frontier, region_at


NECK_POCKET = Path(__file__).resolve().parents[1] / 'examples' / 'adaptive-neck-pocket.wkt'


def test_start_intervals_split_at_stock_and_keep_guide_order():
    pocket = box(0, 0, 20, 10)
    stock = box(8, 3, 11, 7)
    intervals = cleared_start_intervals(pocket, stock, (20, 5), (0, 5), 1., margin=.25)
    assert len(intervals) == 2
    assert intervals[0] == pytest.approx((1.25, 7.75), abs=.001)
    assert intervals[1] == pytest.approx((13.25, 18.75), abs=.001)
    assert cleared_start_intervals(pocket, stock, (0, .9), (20, .9), 1.) == ()


def test_start_intervals_exclude_protected_island_even_without_stock():
    pocket = box(0, 0, 20, 10).difference(box(8, 3, 11, 7))
    empty_stock = pocket.difference(pocket)
    intervals = cleared_start_intervals(pocket, empty_stock, (0, 5), (20, 5), 1.)
    assert intervals == ((1., 7.), (12., 19.))
    assert cleared_start_intervals(pocket, empty_stock, (2, 5), (2, 5), 1.) == ()


def test_nearby_frontier_only_reports_seed_side_of_stock_barrier():
    pocket = box(0, 0, 20, 10)
    stock = box(8, 0, 11, 10)
    front = nearby_frontier(pocket, stock, (3, 5), 1., extra_reach=.25)
    assert not front.is_empty
    assert front.bounds[0] == front.bounds[2] == 8.
    assert nearby_frontier(pocket, stock, (9, 5), 1., extra_reach=.25).is_empty


def test_neck_connects_small_cutter_but_splits_larger_cutter():
    pocket = from_wkt(NECK_POCKET.read_text())
    left, right = (17., 23.), (96., 32.)
    connected = center_regions(pocket, 2.)
    assert len(connected) == 1
    assert region_at(connected, left) == region_at(connected, right) == 0
    split = center_regions(pocket, 7.)
    assert len(split) == 2
    assert (region_at(split, left), region_at(split, right)) == (0, 1)
    assert region_at(split, (36., 23.)) is None
    assert center_regions(pocket, 30.) == ()


def test_margin_can_close_neck_even_with_same_tool():
    left, right = box(0, 0, 6, 6), box(10, 0, 16, 6)
    pocket = left.union(box(6, 2, 10, 4)).union(right)
    assert len(center_regions(pocket, .9)) == 1
    assert len(center_regions(pocket, .9, margin=.1)) == 2
    assert len(center_regions(pocket, .9, margin=.2)) == 2


def test_split_lobe_with_stock_requires_its_own_seed():
    pocket = from_wkt(NECK_POCKET.read_text())
    left, right = (17., 23.), (96., 32.)
    stock = pocket.difference(Point(left).buffer(7.5))
    split = map_region_work(pocket, stock, 7., [left, right, (36., 23.)])
    assert [region.seeds for region in split] == [(left,), ()]
    assert [region.needs_entry for region in split] == [False, True]
    assert all(region.stock.area > 0 for region in split)
    connected = map_region_work(pocket, stock, 2., [left])
    assert len(connected) == 1 and not connected[0].needs_entry
    assert connected[0].stock.covers(Point(right))


def test_empty_region_needs_no_entry_and_margin_rechecks_seed():
    left, right = box(0, 0, 8, 8), box(12, 0, 20, 8)
    stock = box(4.05, 0, 8, 8)
    seed = (3., 4.)
    work = map_region_work(left.union(right), stock, 1., [seed])
    assert [region.needs_entry for region in work] == [False, False]
    work = map_region_work(left.union(right), stock, 1., [seed], margin=.1)
    assert [region.seeds for region in work] == [(), ()]
    assert [region.needs_entry for region in work] == [True, False]


@pytest.mark.parametrize('radius, margin', [(0., 0.), (float('nan'), 0.), (1., -.1)])
def test_rejects_invalid_radius_or_margin(radius, margin):
    with pytest.raises(ValueError):
        center_regions(box(0, 0, 6, 6), radius, margin=margin)
