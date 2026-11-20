from pathlib import Path

import pytest
from shapely import from_wkt
from shapely.geometry import Point, box

from tools.hsm_center_regions import center_regions, map_region_work, region_at


NECK_POCKET = Path(__file__).resolve().parents[1] / 'examples' / 'adaptive-neck-pocket.wkt'


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
