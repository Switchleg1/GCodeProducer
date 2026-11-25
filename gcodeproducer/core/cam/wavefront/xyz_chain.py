"""Continue a verified sloping cut at its actual endpoint; no air links."""
import math
import numpy as np
from .xyz_junction import join_front


def extend_chain(stock,surface,zone,first,radius,width,hand,floor,ceiling,allowance,budget=32):
    chain=[first]
    for _ in range(budget):
        a,b,_=chain[-1]; d=b[:2]-a[:2]; d=d/np.linalg.norm(d)
        proposals=[]
        for length in (radius/2,radius/4):
            for deg in (0,8,-8,20,-20,35,-35):
                t=math.radians(deg); h=d*math.cos(t)+np.array([-d[1],d[0]])*math.sin(t)
                end=np.round(b[:2]+length*h,3); q=(b[:2]+end)/2
                # Disk at midpoint enlarged by half span encloses every tip
                # disk, so both endpoint elevations must clear this envelope.
                base=max(floor,float(surface.heights(q[None,:],radius+allowance+np.linalg.norm(end-b[:2])/2+.002)[0])+allowance)
                if b[2]<base: continue
                target=np.ceil(max(base,b[2]+(b[2]-a[2])*length/np.linalg.norm(a[:2]-b[:2]))*1000)/1000
                for z in dict.fromkeys((target,b[2])):
                    if z<=ceiling: proposals.append((b,np.r_[end,z]))
        result=join_front(stock,zone,b,proposals,radius,width,hand)
        if result is None: break
        chain.append(result)
    return chain
