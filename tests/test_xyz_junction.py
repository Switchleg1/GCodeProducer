import numpy as np
import pytest
from shapely.geometry import box
from gcodeproducer.core.cam.hybrid_stock import HybridStock
from gcodeproducer.core.cam.wavefront.xyz_junction import join_front


def fixture(gap):
    s=HybridStock((-8,-6,18,12),-5,0,4,.5)
    # Two previously roughed strips approach from opposite ends on a slope.
    # Their horizontal footprints overlap even in the failing case, but the
    # right strip may not have reached the elevation needed for the link.
    s.cut((-6,2,-3),(3,2,-2.8),2)
    s.cut((14,2,-2.4),(1,2,-.5 if gap else -2.7),2)
    s.cut((-4,4,-3),(14,4,-2.4),2)
    s.cut((6,3,-2.4),(6,1.7,-2.4),2.12)
    return s


def test_merge_advancing_fronts_on_slope():
    s=fixture(False); allowed=box(-6,-4,16,10)
    history=list(s.sweeps)
    a,b,w=join_front(s,allowed,(-4,2.1,-2.1),[
        ((-3,1.7,-2.1),(1,1.7,-2.0)), # closer, but link would cut
        ((6,1.7,-2.1),(11,1.7,-2.0)), # diagonal also crosses the edge
        ((6,2.02,-2.1),(11,1.7,-2.0))],2,.4,'climb')
    assert np.allclose(a,[6,2.02,-2.1]) and b[2]>a[2] and 0<w<=.4
    # Independent chronological height-column replay, including the rejected
    # link's alternative and the full end caps (not sparse chords).
    axis=np.arange(-7,17,.04)+.02; y,x=np.meshgrid(axis,axis,indexing='ij'); h=np.zeros_like(x)
    def replay(start,end,r):
        p,q=np.array(start),np.array(end); dx,dy,dz=q-p; ll=dx*dx+dy*dy
        u,v=x-p[0],y-p[1]; t=(u*dx+v*dy)/ll; disc=r*r-(u*dy-v*dx)**2/ll
        dt=np.sqrt(np.maximum(disc,0)/ll); hit=(disc>=0)&(t+dt>=0)&(t-dt<=1)
        z=p[2]+dz*np.clip(t-dt if dz>=0 else t+dt,0,1)
        fresh=hit&(h>z+1e-8); np.minimum(h,z,out=h,where=hit); return fresh
    for p,q,r in history: replay(p,q,r)
    assert not replay((-4,2.1,-2.1),a,2).any()
    fresh=replay(a,b,2); assert fresh.any()
    transverse=((x-a[0])*(a[1]-b[1])+(y-a[1])*(b[0]-a[0]))/np.linalg.norm(b[:2]-a[:2])
    assert transverse[fresh].max()<0 and np.ptp(transverse[fresh])<=w


@pytest.mark.parametrize('gap,hand',[(True,'climb'),(False,'conventional')])
def test_reject_shallow_previous_cut_or_wrong_hand(gap,hand):
    s=fixture(gap); n=len(s.sweeps)
    assert join_front(s,box(-6,-4,16,10),(-4,2.1,-2.1),
                      [((6,2.02,-2.1),(11,1.7,-2.0))],2,.4,hand) is None
    assert len(s.sweeps)==n
