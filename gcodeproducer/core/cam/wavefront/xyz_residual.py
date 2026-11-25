"""Experimental short tangent cuts aimed at measured excess on a slope."""
import numpy as np
from shapely.geometry import LineString


def residual_proposals(surface, zone, xy, excess, floor, ceiling, radius, width, hand, allowance, budget=96):
    """Sample spaced targets in descending excess order. Heights are model bounds;
    proposals are not cuts until join_front checks live stock, link and hand.
    """
    if hand not in ('climb','conventional'): raise ValueError('one-sided cuts only')
    sites=[]; candidates=[]
    for i in np.argsort(-excess,kind='stable'):
        if excess[i]<=.001: break
        pos=xy[i]
        if any(np.linalg.norm(pos-site)<width for site in sites): continue
        sites.append(pos)
        # Approach the target from a lower part of the slope. Searching
        # headings also handles sharp transitions where no gradient exists.
        angles=np.arange(12)*np.pi/6
        out=np.column_stack((np.cos(angles),np.sin(angles)))
        ends=pos+(radius-.07*width)*out
        tangent=np.column_stack((out[:,1],-out[:,0]))*(1 if hand=='climb' else -1)
        starts=ends-tangent*(radius/3)+out*(.4*width)
        starts,ends=np.round(starts,3),np.round(ends,3); mids=(starts+ends)/2
        span=np.linalg.norm(ends-starts,axis=1).max()
        req=surface.heights(np.vstack(((starts+mids)/2,(ends+mids)/2)),radius+allowance+span/4+.002)+allowance
        low,high=np.maximum(req.reshape(2,-1),floor)
        # Both endpoints of each half segment must bound that half's surface.
        dz=high-low
        az=np.ceil((low+np.maximum(-dz,0))*1000)/1000
        bz=np.ceil((high+np.maximum(dz,0))*1000)/1000
        for j in np.argsort(np.maximum(az,bz)):
            if max(az[j],bz[j])>ceiling: continue
            if zone.covers(LineString((starts[j],ends[j]))):
                candidates.append((np.r_[starts[j],az[j]],np.r_[ends[j],bz[j]]))
        if len(sites)>=budget: break
    return candidates
