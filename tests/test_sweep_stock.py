import pytest
from shapely.geometry import Point, box
from gcodeproducer.core.cam.sweep_stock import SweepStock


@pytest.mark.parametrize('tile', [.5, 8])
def test_ridge_survives_until_actually_cut(tile):
    s = SweepStock((-6,-5,6,5), -4, 0, tile)
    for y in (-2.02, 2.02):
        s.cut((-4,y,-2), (4,y,-2), 2)
    window = box(-3,-1,3,1)
    section = s.remaining(-2, .005, window)
    assert section.area == pytest.approx(6*.04)
    for y in (0, -.03, .03):
        assert section.contains(Point(0,y)) == (s.height(0,y) > -2)
    s.cut((0,0,1), (0,0,-3), 1)
    assert s.height(0,0) == -3 and s.height(2,0) == 0
    section = s.remaining(-2,.005,window)
    assert not section.contains(Point(0,0)) and section.contains(Point(2,0))


@pytest.mark.parametrize('reverse', [False, True])
def test_ramp_section_agrees_with_lowest_tip_during_contact(reverse):
    s = SweepStock((-5,-4,20,4), -8, 0, 3)
    a,b = (0,0,-4),(12,0,-1)
    s.cut(*( (b,a) if reverse else (a,b) ), 2)
    assert s.height(6,0) == pytest.approx(-3)  # first reaches X6 when centre is X4
    section = s.remaining(-3,.001)
    for x in (5.99,6.01):
        assert section.contains(Point(x,0)) == (s.height(x,0) > -3)
