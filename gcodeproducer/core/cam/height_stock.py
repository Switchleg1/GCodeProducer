"""HeightStock — cam subsystem."""
from __future__ import annotations
import math, numpy as np

class HeightStock:
    def __init__(self,stock,resolution=.2,max_cells=2_000_000):
        self.stock=stock
        self.tabs=[]                         # exact tab boxes, independent of grid sampling
        lo,hi=stock.bounds
        self.requested=max(float(resolution),.02)
        resolution=max(self.requested,math.sqrt(stock.width*stock.depth/max(int(max_cells),10_000)))
        self.coarsened=resolution>self.requested+1e-12
        self.nx=max(1,int(math.ceil(stock.width/resolution)))
        self.ny=max(1,int(math.ceil(stock.depth/resolution)))
        self.dx=stock.width/self.nx;self.dy=stock.depth/self.ny
        self.x=lo[0]+(np.arange(self.nx)+.5)*self.dx
        self.y=lo[1]+(np.arange(self.ny)+.5)*self.dy
        self.bottom=lo[2]
        self.heights=np.full((self.ny,self.nx),stock.top,np.float32)
        self.resolution=max(self.dx,self.dy)

    def _patch(self,a,b,radius):
        xa=max(0,int(math.floor((min(a[0],b[0])-radius-self.stock.x)/self.dx)))
        xb=min(self.nx,int(math.ceil((max(a[0],b[0])+radius-self.stock.x)/self.dx)))
        ya=max(0,int(math.floor((min(a[1],b[1])-radius-self.stock.y)/self.dy)))
        yb=min(self.ny,int(math.ceil((max(a[1],b[1])+radius-self.stock.y)/self.dy)))
        if xa>=xb or ya>=yb:return None
        x,y=np.meshgrid(self.x[xa:xb],self.y[ya:yb])
        d=np.asarray(b[:2])-a[:2]
        length=float(d@d)
        raw=((x-a[0])*d[0]+(y-a[1])*d[1])/max(length,1e-20)
        t=np.clip(raw,0,1)
        distance=(x-a[0]-t*d[0])**2+(y-a[1]-t*d[1])**2
        if length<1e-12:
            z=np.minimum(a[2],b[2])
        else:
            perpendicular=(x-a[0]-raw*d[0])**2+(y-a[1]-raw*d[1])**2
            half=np.sqrt(np.maximum(radius*radius-perpendicular,0)/length)
            lo=np.clip(raw-half,0,1);hi=np.clip(raw+half,0,1)
            # Lowest tip while the cylindrical cutter covers each cell centre,
            # not merely its Z at closest XY projection (important for ramps).
            hit_t=hi if b[2]<a[2] else lo
            z=a[2]+hit_t*(b[2]-a[2])
        return (slice(ya,yb),slice(xa,xb)),distance,z

    def height_at(self,point,radius):
        p=np.r_[np.asarray(point)[:2],0.]
        patch=self._patch(p,p,radius)
        if patch is None:return float(self.bottom)
        region,distance,_=patch
        values=self.heights[region][distance<=radius*radius]
        height=float(values.max()) if len(values) else float(self.heights[region].max())
        from gcodeproducer.core.cam.tabs import top_along
        return top_along(self.tabs,p,p,radius,height)

    def max_height_along(self,a,b,radius):
        """Highest current material within ``radius`` of the XY segment a-b (blank bottom if none)."""
        a=np.r_[np.asarray(a,float)[:2],0.];b=np.r_[np.asarray(b,float)[:2],0.]
        patch=self._patch(a,b,radius)
        if patch is None:return float(self.bottom)
        region,distance,_=patch
        values=self.heights[region][distance<=radius*radius]
        height=float(values.max()) if len(values) else float(self.bottom)
        from gcodeproducer.core.cam.tabs import top_along
        return top_along(self.tabs,a,b,radius,height)

    def tab_contact(self,a,b,radius):
        from gcodeproducer.core.cam.tabs import contact
        return bool(self.tabs) and contact(self.tabs,np.asarray(a),np.asarray(b),radius)

    def contact(self,a,b,radius):
        if self.tab_contact(a,b,radius):return True
        patch=self._patch(np.asarray(a),np.asarray(b),radius)
        if patch is None:return False
        region,distance,z=patch
        return bool(np.any((distance <= radius*radius) & (self.heights[region] > self.bottom+1e-3) & (self.heights[region] > z+1e-3)))

    def cut(self,a,b,radius):
        patch=self._patch(np.asarray(a),np.asarray(b),radius)
        if patch is None:return
        region,distance,z=patch
        h=self.heights[region]
        hit=distance <= radius*radius
        h=np.where(hit,np.minimum(h,np.maximum(z,self.bottom)),h)
        if self.tabs:
            x,y=np.meshgrid(self.x[region[1]],self.y[region[0]])
            for lo,hi in self.tabs:
                keep=(x>=lo[0])&(x<=hi[0])&(y>=lo[1])&(y<=hi[1])
                h=np.where(keep,np.maximum(h,hi[2]),h)
        self.heights[region]=h

    def surface(self):
        """Display mesh bounded to about 100x100 cells; include step/outer walls."""
        sy=max(1,int(math.ceil(self.ny/100)));sx=max(1,int(math.ceil(self.nx/100)))
        ix=np.r_[np.arange(0,self.nx,sx),self.nx]
        iy=np.r_[np.arange(0,self.ny,sy),self.ny]
        # Display samples are not the underlying collision grid.
        h=self.heights[np.ix_(iy[:-1],ix[:-1])]
        x0,y0=np.meshgrid(self.stock.x+ix[:-1]*self.dx,self.stock.y+iy[:-1]*self.dy)
        x1,y1=np.meshgrid(self.stock.x+ix[1:]*self.dx,self.stock.y+iy[1:]*self.dy)
        quads=[]
        def quad(a,b,c,d):
            arr=np.stack((a,b,c,a,c,d),axis=-2).reshape(-1,3)
            quads.append(arr)
        def p(x,y,z):return np.stack((x,y,z),axis=-1)
        alive=h>self.bottom+1e-5
        quad(p(x0[alive],y0[alive],h[alive]),p(x1[alive],y0[alive],h[alive]),
             p(x1[alive],y1[alive],h[alive]),p(x0[alive],y1[alive],h[alive]))
        for axis in (0,1):
            # Positive cell edge, comparing with its neighbour or the bottom outside blank.
            other=np.full_like(h,self.bottom)
            if axis==0:other[:-1]=h[1:]
            else:other[:,:-1]=h[:,1:]
            changed=np.abs(h-other)>1e-5
            if axis==0:
                quad(p(x0[changed],y1[changed],h[changed]),p(x1[changed],y1[changed],h[changed]),
                     p(x1[changed],y1[changed],other[changed]),p(x0[changed],y1[changed],other[changed]))
            else:
                quad(p(x1[changed],y0[changed],h[changed]),p(x1[changed],y1[changed],h[changed]),
                     p(x1[changed],y1[changed],other[changed]),p(x1[changed],y0[changed],other[changed]))
        for x,y,z,u,v in ((x0[0],y0[0],h[0],x1[0],y0[0]),
                           (x0[:,0],y0[:,0],h[:,0],x0[:,0],y1[:,0])):
            bottom=np.full_like(z,self.bottom)
            quad(p(x,y,z),p(u,v,z),p(u,v,bottom),p(x,y,bottom))
        return np.ascontiguousarray(np.concatenate(quads),np.float32)
