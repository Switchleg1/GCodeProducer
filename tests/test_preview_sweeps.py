import numpy as np
import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from gcodeproducer.core.cam.preview_sweeps import arc_segments, profile
from gcodeproducer.core.cam.sweep_stock import SweepStock
from gcodeproducer.core.cam.sweep_surface import surface


@pytest.mark.parametrize('cw',[True,False])
def test_full_circle_helix_and_signed_radius(cw):
    a=np.array([4.,0.,0.]); b=np.array([4.,0.,-2.])
    pieces=arc_segments(a,b,{'I':-4},cw,1.)
    assert len(pieces)>8 and np.allclose(pieces[-1][1],b)
    assert all(abs(np.linalg.norm(q[:2])-4)<1e-8 and error<=.0051 for _,q,error in pieces)
    assert all(q[2]<p[2] for p,q,_ in pieces)
    end=np.array([0.,4.,-2.]); short,long=(arc_segments(a,end,{'R':r},cw,1.) for r in (4,-4))
    assert len(long)>len(short)
    assert arc_segments(a,end,{'R':1},cw,1.) is None


def test_ball_v_and_tab_do_not_make_flat_grooves():
    for kind in ('ballnose','vbit'):
        s=SweepStock((-5,-5,5,5),-5,0,2)
        for h,r in profile({'type':kind,'vangle':90},2):
            s.cut((-3,0,-2+h),(3,0,-2+h),r)
        assert s.height(0,0)<s.height(0,1.5)<0
        mesh=surface(s,[-1,-2],.005,[(np.array([-1,-1,-5]),np.array([1,1,-.25]))]).reshape(-1,3,3)
        roof=unary_union([Polygon(t[:,:2]) for t in mesh if np.all(t[:,2]==-.25)])
        assert roof.covers(Point(0,0)) and not roof.covers(Point(2,0))
    assert profile({'type':'drill'},2) is None
