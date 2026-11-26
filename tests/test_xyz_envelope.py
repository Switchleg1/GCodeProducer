import numpy as np
import pytest
from gcodeproducer.core.cam.wavefront.xyz_envelope import disk_envelope


@pytest.mark.parametrize('dx,dy',[(1.,1.),(.4,.7)])
def test_reach_matches_explicit_disk_placement(dx,dy):
    tips=np.array([[-np.inf,-1.,-2.,0.],[-1.,0.,1.,-2.],[-3.,-2.,0.,1.]])
    allowed=np.ones_like(tips,dtype=bool); allowed[2,0]=False
    z,w=disk_envelope(tips,allowed,-2.,-.1,dx,dy,1.)
    for j,i in np.ndindex(tips.shape):
        options=[max(-2.,tips[b,a]) for b,a in np.ndindex(tips.shape) if allowed[b,a]
                 and tips[b,a]<=-.1 and ((i-a)*dx)**2+((j-b)*dy)**2<=1.]
        assert z[j,i]==min(options,default=np.inf)
        if options:
            b,a=np.unravel_index(w[j,i],tips.shape)
            assert allowed[b,a] and np.hypot((i-a)*dx,(j-b)*dy)<=1.
            assert z[j,i]==max(-2,tips[b,a])
        else: assert w[j,i]==-1
