"""Persistent 2.5D material state: exact planar sweeps for planning, a height
field for progress display and motion checks. Neither models fixtures/holders.
"""
import math
import re

import numpy as np
from shapely.geometry import box, LineString, Point
from shapely.ops import unary_union


RAMP_ANGLE=10.0                       # matches the lead-in planner (core.cam_leads)
RAMP_TAN=math.tan(math.radians(RAMP_ANGLE))


class PlanarStock:
    def __init__(self, stock):
        lo,hi=stock.bounds
        self.blank=box(lo[0],lo[1],hi[0],hi[1])
        self.top=float(hi[2])
        self.removed={}

    def at(self,z):
        if z>=self.top-1e-9:return self.blank.difference(self.blank)
        cuts=[g for depth,g in self.removed.values() if depth <= z+1e-6]
        return self.blank.difference(unary_union(cuts)) if cuts else self.blank

    def top_within(self,geom,start,end):
        """Highest Z in [end, start] where ``geom`` still meets material, else None.

        Material is piecewise constant between recorded removal depths, so only
        ``start`` and the depths just below each recorded removal need testing.
        """
        if geom.is_empty:return None
        candidates=[min(start,self.top)]+sorted({d for d,_ in self.removed.values() if end<d<start},reverse=True)
        for z in candidates:
            # ``at`` applies a 1e-6 tolerance of its own; probe clearly below a recorded depth.
            probe=z-1e-4 if z<start or z>=self.top-1e-9 else z
            if self.at(probe).intersection(geom).area>1e-9:
                return float(min(z,start))
        return None

    @staticmethod
    def sweep(paths,radius):
        sweeps=[]
        previous=None
        for path in paths:
            p=np.asarray(path.points)[:,:2]
            if path.stay_down and previous is not None:
                sweeps.append(LineString((previous,p[0])).buffer(radius))
            if len(p)==1:
                sweeps.append(Point(p[0]).buffer(radius))
            else:
                q=np.vstack((p,p[0])) if path.closed else p
                sweeps.append(LineString(q).buffer(radius))
            previous=p[0] if path.closed else p[-1]
        return unary_union(sweeps).normalize()

    def remove(self,paths,z,radius):
        swept=self.sweep(paths,radius)
        key=swept.wkb
        old=self.removed.get(key)
        self.removed[key]=(min(z,old[0]) if old else z,swept)


class HeightStock:
    def __init__(self,stock,resolution=.2,max_cells=2_000_000):
        self.stock=stock
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
        return float(values.max()) if len(values) else float(self.heights[region].max())

    def contact(self,a,b,radius):
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
        self.heights[region]=np.where(hit,np.minimum(h,np.maximum(z,self.bottom)),h)

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


def height_stock_for(job,stock):
    from .app_settings import pref
    return HeightStock(stock,pref(job,"stock_resolution"),pref(job,"stock_max_cells"))


def simulate_material(job,program,log=None):
    """Execute emitted moves in order, preserving material across all operations."""
    from .sim import simulate
    stock=getattr(job.cam_setup,"stock",None)
    if stock is None or not stock.allocated:return [],[]
    state=height_stock_for(job,stock)
    sim=simulate(program)
    by_id={t.id:t.resolved() for t in job.tools}
    tools={int(by_id[t.id].get("tool_number",1)):by_id[t.id] for t in job.tools}
    layer_tools={layer.index:by_id.get(getattr(layer,"cam_tool_id",None)) for layer in job.layers}
    fallback=by_id[job.tools[0].id] if job.tools else None
    snapshots=[{"label":"Initial material","last_layer":-1,"positions":state.surface(),
                "resolution":state.resolution,"heights":state.heights.copy()}]
    warnings=[];spindle=False;last_op=None;last_layer=-1
    from .features import CAM_CUT_FEATURES
    intended=CAM_CUT_FEATURES|{"plunge","lead_in","lead_out"}
    def warn(text):
        if len(warnings)<100 and text not in warnings:warnings.append(text)
    if state.coarsened:
        warn(f"Material grid coarsened from {state.requested:g} to {state.resolution:g} mm by the global cell limit; raise it in Settings for finer checks.")
    def snapshot(label):
        snapshots.append({"label":label,"last_layer":last_layer,"positions":state.surface(),
                          "resolution":state.resolution,"heights":state.heights.copy()})
    for i,line in enumerate(program.lines):
        if line.op and line.op!=last_op:
            if last_op is not None:snapshot(last_op)
            last_op=line.op
        if line.op:last_layer=max(last_layer,line.layer)
        if line.cmd in ("M3","M4"):spindle=line.params.get("S",1)>0
        elif line.cmd=="M5":spindle=False
        if not sim.motion[i] or not sim.moved[i]:continue
        tool=(layer_tools.get(line.layer) if line.op else None) or tools.get(int(sim.tool[i]),fallback)
        if tool is None:continue
        radius=float(tool.get("diameter",0))/2
        if 2*radius<2*state.resolution:
            warn("Tool diameter is below twice the material grid resolution; small contacts/removal may be missed. Use a finer grid.")
        a=np.array([sim.px[i],sim.py[i],sim.pz[i]])
        b=np.array([sim.x[i],sim.y[i],sim.z[i]])
        contact=state.contact(a,b,radius)
        up=np.linalg.norm(a[:2]-b[:2])<1e-6 and b[2]>a[2]
        label=f"Line {i+1}"
        if min(a[2],b[2])<state.bottom-1e-3:warn(f"{label}: motion below material bottom; table/spoilboard risk.")
        if sim.motion_cmd[i]=="G0" and contact and not up:
            warn(f"{label}: rapid motion contacts CURRENT remaining material (grid {state.resolution:g} mm).")
        elif sim.motion_cmd[i] in ("G1","G2","G3") and contact and not up:
            if line.feature not in intended or not line.op:
                warn(f"{label}: unclassified feed contacts current material.")
            if not spindle:warn(f"{label}: material contact with spindle stopped.")
        if contact and line.feature in ("plunge","lead_in") and b[2]<a[2]:
            horizontal=float(np.linalg.norm(b[:2]-a[:2]))
            drop=float(a[2]-b[2])
            if horizontal>1e-6 and drop<=horizontal*RAMP_TAN+1e-6:
                pass  # ramped entry within the ramp angle: the tool tip descends gradually; walls beside it are side cutting
            else:
                # Plunge (or over-steep ramp): material under the tool that this move itself descends
                # through. Material above the move's start height is side contact, not axial entry.
                doc=float(tool.get("max_doc",0) or 0)
                uncleared=min(state.height_at(b[:2],radius),float(a[2]))-b[2]
                if doc>0 and uncleared>doc+state.resolution:
                    kind="plunge" if horizontal<=1e-6 else f"ramp steeper than {RAMP_ANGLE:g}°"
                    warn(f"{label}: estimated uncleared entry depth {uncleared:g} mm ({kind}) exceeds tool depth/pass {doc:g}; verify prior clearing.")
        if sim.motion_cmd[i]=="G1" and spindle and line.feature in intended and line.op:
            state.cut(a,b,radius)
    if last_op is not None:snapshot(last_op)
    if log:log(f"  current material: {state.nx} x {state.ny} cells, {state.resolution:g} mm, {len(snapshots)-1} operation outputs")
    return warnings,snapshots
