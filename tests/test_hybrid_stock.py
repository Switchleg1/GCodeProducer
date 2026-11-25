import numpy as np
from gcodeproducer.core.cam.hybrid_stock import HybridStock


def test_whole_cutter_hits_ridge_even_with_centre_in_clear_strip():
    s = HybridStock((-6,-5,6,5),-5,0,4.,.5)
    for y in (-2.02,2.02):
        s.cut((-5,y,-2),(5,y,-2),2.)
    assert not s.occupied(0,.5,-2)
    assert s.occupied(0,0,-2)
    assert not s.clear_at_depth((-2,.5),(2,.5),.6,-2)
    assert s.clear_at_depth((-2,1),(2,1),.2,-2)
    s.cut((0,0,0),(0,0,-3),.3)
    assert not s.occupied(0,0,-2)
    assert s.occupied(1,0,-2)


def test_display_and_travel_both_preserve_subcell_ridge():
    from shapely.geometry import Polygon, Point
    from shapely.ops import unary_union
    from types import SimpleNamespace
    from gcodeproducer.core.cam.planner.link_planner import LinkPlanner
    from gcodeproducer.core.cam.sweep_surface import surface
    s = HybridStock((-6,-5,6,5),-5,0,4.,.5)
    for y in (-2.02,2.02):
        s.cut((-4,y,-2),(4,y,-2),2.)
    mesh = surface(s,[-2],.005).reshape(-1,3,3)
    top = unary_union([Polygon(t[:,:2]) for t in mesh if np.all(t[:,2]==0)])
    assert top.contains(Point(0,0)) and not top.covers(Point(0,.05))
    links = LinkPlanner(15,1,.5,True,.6)
    grid = SimpleNamespace(contact=lambda *args:False,height_at=lambda *args:-2,hybrid=s)
    assert not links.stay_at_depth(grid,np.array([-2,.5,-2]),[2,.5],-2)
    assert links.stay_at_depth(grid,np.array([-2,1,-2]),[2,1],-2)


def test_incremental_bounds_match_sweeps():
    s = HybridStock((-3,-3,3,3),-6,0,1.,.36)
    rng = np.random.default_rng(341)
    xy = rng.uniform(-3,3,(100,2))
    for _ in range(20):
        a,b = rng.uniform([-4,-4,-7],[4,4,1],(2,3))
        s.cut(a,b,rng.uniform(.1,2.))
        for x,y in xy:
            h = s.height(x,y)
            for z in (-3., h, h-.001):
                assert s.occupied(x,y,z) == (h>z)
