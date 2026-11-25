"""Offline 3D adaptive fixture: one closed rising/falling ledge and a blended next lap.

Entry is synthetic; intended fresh stock is outside the first lap. Width here
is radial band width for this concentric fixture, not general cutter engagement.
"""
import numpy as np


def replay(pitch=.05, guarded=True, span_scale=1.):
    radius, base, step = 2., 8., .30
    axis = np.arange(-11,11,pitch)+pitch/2
    x,y = np.meshgrid(axis,axis)
    radial = np.hypot(x,y)
    # The interior was roughed to depth. The first lap defines the curved ledge.
    stock = np.where(radial < base, -3., 0.)
    def height(t):
        return -2+.5*(1-np.cos(t))

    def sweep(a,b):
        ix,jx = np.searchsorted(axis,[min(a[0],b[0])-radius,max(a[0],b[0])+radius]); iy,jy = np.searchsorted(axis,[min(a[1],b[1])-radius,max(a[1],b[1])+radius]); region=np.s_[iy:jy+1,ix:jx+1]
        u,v=x[region]-a[0],y[region]-a[1]; dx,dy,dz=b-a; ll=dx*dx+dy*dy
        if ll==0:
            mask=u*u+v*v<=radius**2; floor=min(a[2],b[2])
        else:
            t=(u*dx+v*dy)/ll; disc=radius**2-(u*dy-v*dx)**2/ll
            dt=np.sqrt(np.maximum(0,disc)/ll); mask=(disc>=0)&(t+dt>=0)&(t-dt<=1)
            floor=a[2]+dz*np.clip(t-dt if dz>=0 else t+dt,0,1)
        h=stock[region]; delta=np.where(mask,np.maximum(0,h-floor),0); h-=delta
        return region,delta

    angles=np.linspace(0,2*np.pi,361)
    def point(r,t,z):
        return np.round([r*np.cos(t),r*np.sin(t),z],3)
    prior=[point(base,t,height(t)) for t in angles]
    for a,b in zip(prior,prior[1:]): sweep(a,b)
    before=stock.copy(); old=before<0
    # Use the highest prior tip over the neighbouring directions a cutter can
    # reach, not the prior tip at just the centre's polar angle. No inner loop
    # or return chord: rise at the old endpoint, then ease outward while cutting.
    def proposal(t):
        f=min(1,t/(np.pi/3)); r=base+step*f*f*(3-2*f)
        span=span_scale*(2*np.arcsin(radius/(base-radius))+.02)
        guard=max(height(t-span),height(t+span),height(t))
        if abs(t-np.pi)<=span: guard=-1.
        return point(r,t,guard+.002 if guarded else height(t))
    path=[prior[-1],*(proposal(t) for t in angles)]
    worst=width=0.; join_contact=0.
    for i,(a,b) in enumerate(zip(path,path[1:])):
        region,d=sweep(a,b); fresh=d>.001
        worst=max(worst,d[old[region]].max(initial=0))
        rr=radial[region][fresh]
        if rr.size: width=max(width,rr.max()-rr.min()+np.sqrt(2)*pitch)
        if i==0: join_contact=float(d.sum()*pitch**2)
    return dict(old_floor_bite_mm=float(worst), radial_span_mm=float(width), join_removal_mm3=join_contact,
                removed_mm3=float((before-stock).sum()*pitch**2),
                # Compare against a second lap copying the floor, not the air above the new pass.
                max_tip_lift_mm=max(float(q[2]-height(t)) for q,t in zip(path[1:],angles)))


if __name__=='__main__':
    # Select on one grid, then replay the unchanged quantized path on a finer grid.
    for scale in (0., .125, .25, .5, 1.):
        result = replay(.05, bool(scale), scale)
        print('candidate',scale,result)
        if result['old_floor_bite_mm'] <= .001 and result['radial_span_mm'] <= .4:
            print('refinement',scale,replay(.025,bool(scale),scale))
            break
