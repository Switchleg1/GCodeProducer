import numpy as np
from shapely.geometry import box
from gcodeproducer.core.cam.hybrid_stock import HybridStock
from gcodeproducer.core.cam.wavefront.xyz_junction import join_front
from gcodeproducer.core.cam.wavefront.xyz_residual import fit_residual_depth


def test_elevation_fit_clears_partial_depth_stock_without_relaxing_width():
    s=HybridStock((-8,-6,18,12),-5,0,4,.5)
    s.cut((-4,2,-1.5),(14,2,-1.5),2)
    s.cut((-4,3,-1.5),(14,3,-1.5),2)
    a=np.array([0.,2.05,-1.9]); b=np.array([1.,1.86,-1.85]); zone=box(-6,-4,16,10)
    def verify(a,b):
        return join_front(s,zone,[*a[:2],1],[(a,b)],2,.4,'climb')
    assert verify(a,b) is None
    assert fit_residual_depth(s,a,b,2,.4,'climb',-1.6) is None
    p,q=fit_residual_depth(s,a,b,2,.4,'climb',0.)
    assert np.allclose(q-p,b-a) and p[2]>=-1.5
    res=verify(p,q)
    assert res is not None and 0<res[2]<=.4
