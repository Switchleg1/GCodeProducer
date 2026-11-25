from types import SimpleNamespace
import numpy as np
from shapely.geometry import box
from gcodeproducer.core.cam.hybrid_stock import HybridStock
from gcodeproducer.core.cam.wavefront.xyz_front import front_proposals
from gcodeproducer.core.cam.wavefront.xyz_junction import join_front


def test_residual_edge_and_model_slope_generate_a_checked_cut():
    s=HybridStock((-12,-12,12,12),-5,0,4,.5)
    s.cut((-10,2,-3),(10,2,-3),2)
    s.cut((-10,3,-3),(10,3,-3),2)
    area=box(-10,-10,10,10)
    # Exact upper height of linear plane under the lookup disk.
    surface=SimpleNamespace(heights=lambda xy,r: -1.25+.02*(xy[:,0]+r))
    spans=front_proposals(s,surface,area,np.array([0,2,-2]),-2,0,2,.4,'climb')
    result=next((res for a,b in spans if abs(a[2]-b[2])>.001 and
                 (res:=join_front(s,area,[*a[:2],1],[(a,b)],2,.4,'climb')) is not None),None)
    assert result is not None
    a,b,w=result
    for t in np.linspace(0,1,101):
        x,y,z=a+t*(b-a)
        assert z>=-1.25+.02*(x+2)
    assert 0<w<=.4
    from gcodeproducer.core.cam.wavefront.xyz_chain import extend_chain
    chain=extend_chain(s,surface,area,result,2,.4,'climb',-2,0,0,budget=8)
    assert len(chain)>1
    for (_,end,_),(start,next_end,width) in zip(chain,chain[1:]):
        assert np.array_equal(end,start) and 0<width<=.4
        assert next_end[2]>=-1.25+.02*(next_end[0]+2)
