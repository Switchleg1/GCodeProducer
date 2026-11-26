"""Experimental short tangent cuts aimed at measured excess on a slope."""
import numpy as np
from shapely.geometry import LineString


def residual_proposals(surface, zone, xy, excess, floor, ceiling, radius, width, hand, allowance, budget=96, witnesses=None, skip_sites=0):
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
        if len(sites)<=skip_sites: continue
        # Approach the target from a lower part of the slope. Searching
        # headings also handles sharp transitions where no gradient exists.
        angles=np.arange(12)*np.pi/6
        if witnesses is not None:
            # Rotate the fan toward the legal cutter centre that demonstrated
            # reach, rather than hoping a fixed heading passes through it.
            delta=witnesses[i]-pos
            angles=angles+np.arctan2(delta[1],delta[0])
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
        if len(sites)>=skip_sites+budget: break
    return candidates


def fit_residual_depth(stock, a, b, radius, width, hand, ceiling, tol=.002):
    """Find a common Z raise that clears the entry disk and the non-cutting
    part of the capsule. Limit fresh contact to a strip at the cutter side.
    This only proposes elevations; join_front must still verify the move.
    """
    from shapely.geometry import Point, Polygon
    v=b[:2]-a[:2]; length=np.linalg.norm(v)
    if length<=0 or hand not in ('climb','conventional'): return None
    tangent=v/length; side=np.array([tangent[1],-tangent[0]])*(1 if hand=='climb' else -1)
    mid=(a[:2]+b[:2])/2
    # Cover rather than inscribe the tip; a small margin avoids bisection
    # landing on a polygon-approximation sliver at the entry point.
    r=radius+3*tol
    cap=LineString([a[:2],b[:2]]).buffer(r,quad_segs=32)
    points=[mid+t*tangent+s*side for t,s in ((-length-r,-r),(length+r,-r),
             (length+r,radius-width+tol),(-length-r,radius-width+tol))]
    protected=cap.intersection(Polygon(points)).union(Point(a[:2]).buffer(r,quad_segs=32))
    def clear(shift):
        z=min(a[2],b[2])+shift
        return stock.remaining(z,tol,protected).is_empty
    available=ceiling-max(a[2],b[2]); lo=0.; hi=available
    if available<0: return None
    if clear(0): return a,b
    if not clear(hi): return None
    while hi-lo>.002:
        test=(lo+hi)/2
        if clear(test): hi=test
        else: lo=test
    shift=np.ceil(hi*1000)/1000
    if shift>available+1e-9: return None
    return a+[0,0,shift], b+[0,0,shift]
