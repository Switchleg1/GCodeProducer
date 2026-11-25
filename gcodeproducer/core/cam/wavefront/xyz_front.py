"""Experimental model-derived XYZ candidates along the boundary of residual stock."""
import math
import numpy as np
from shapely.geometry import box
from shapely.geometry.polygon import orient
from gcodeproducer.core.geometry.polygon_parts import polygons


def front_proposals(stock, surface, allowed, here, floor, ceiling, radius, width, hand, allowance=0., reach=12.):
    """Generate local tangent bites, entering from the cleared side. No removal credited.

    Stock boundaries at mid-depth seed proposals only. Clearance and width must
    still be checked against the actual cut depth before accepting a proposal.
    """
    window=box(here[0]-reach,here[1]-reach,here[0]+reach,here[1]+reach)
    section=stock.remaining((floor+ceiling)/2,.005,window)
    found=[]
    for poly in polygons(section):
        poly=orient(poly,sign=-1 if hand=='climb' else 1)
        for ring in (poly.exterior,*poly.interiors):
            # Resample by distance, not tessellation vertex count.
            for s in np.arange(0,ring.length,max(.25,radius/2)):
                p=np.array(ring.interpolate(s).coords[0]); q=np.array(ring.interpolate((s+radius*.5)%ring.length).coords[0]); v=q-p
                length=np.linalg.norm(v)
                if length<radius*.4 or window.boundary.distance(ring.interpolate(s))<radius: continue
                outward=np.array([-v[1],v[0]])/length*(1 if hand=='climb' else -1)
                xy=np.round([p+outward*(radius+.03),q+outward*(radius-width*.35)],3)
                # Raise both endpoints above their respective half-segment's
                # conservative footprint envelope; both must also clear the
                # shared midpoint envelope for safe linear interpolation.
                mid=xy.mean(axis=0); span=np.linalg.norm(xy[1]-xy[0]); bound=radius+allowance+span/4+.002
                h=surface.heights((xy+mid)/2,bound)+allowance
                h=np.maximum(h,floor)
                # A linear ramp cannot go below the higher half's envelope on
                # crossing the middle; ensure midpoint height >= max(h).
                h[np.argmax(h)]+=abs(h[1]-h[0]); h=np.ceil(h*1000)/1000
                if h.max()>ceiling or not np.all(np.isfinite(h)): continue
                a,b=np.column_stack((xy,h)); found.append((a,b))
    return sorted(found,key=lambda ab:np.linalg.norm(ab[0]-here))
