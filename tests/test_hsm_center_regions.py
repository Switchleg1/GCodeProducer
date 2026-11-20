from pathlib import Path

import pytest
from shapely import from_wkt
from shapely.geometry import box

from tools.hsm_center_regions import center_regions, region_at


def test_neck_connects_small_cutter_but_splits_larger_cutter():
    fixture = Path(__file__).resolve().parents[1] / 'examples' / 'adaptive-neck-pocket.wkt'
    pocket = from_wkt(fixture.read_text())
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


@pytest.mark.parametrize('radius, margin', [(0., 0.), (float('nan'), 0.), (1., -.1)])
def test_rejects_invalid_radius_or_margin(radius, margin):
    with pytest.raises(ValueError):
        center_regions(box(0, 0, 6, 6), radius, margin=margin)
