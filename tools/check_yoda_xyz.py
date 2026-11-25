"""Read-only first-depth model/stock junction probe for the saved Mini Yoda fixture."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
from PyQt6.QtCore import QSettings
from shapely.geometry import box
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.compare_yoda_stock import moves
from gcodeproducer.core.jobs.session import load_mesh
from gcodeproducer.core.jobs.placement import Placement
from gcodeproducer.core.cam.drop_surface import DropSurface
from gcodeproducer.core.cam.hybrid_stock import HybridStock
from gcodeproducer.core.cam.wavefront.xyz_front import front_proposals
from gcodeproducer.core.cam.wavefront.xyz_junction import join_front


def probe(nc, passes=4):
    session=json.loads(QSettings('GCodeProducer','GCodeProducer').value('workSession/default'))
    model,=session['models']; assert Path(model['path']).stem.lower()=='mini_yoda'
    mesh=Placement.from_dict(model['placement']).apply(load_mesh(model['path']),auto_xy=None)
    data=session['cam']['setup']; blank=data['stock']; op=next(o for g in data['groups'] for o in g['operations'] if o['enabled'])
    assert op['kind']=='waterfall' and op['geometry']==[{'kind':'stock_face','indices':[1]}]
    lo=np.array([blank['x'],blank['y']]); hi=lo+[blank['width'],blank['depth']]; top=blank['top']; radius=2.
    stock=HybridStock((*lo,*hi),top-blank['height'],top,4.,.5)
    area=box(*lo,*hi).buffer(min(op['overcut'],op['material_limit']),join_style='mitre').buffer(-radius)
    surface=DropSurface(mesh,lo-10,hi+10,.12,1000000)
    from gcodeproducer.core.cam.height_stock import HeightStock
    from gcodeproducer.core.cam.stock import Stock
    replay=HeightStock(Stock.from_dict(blank),.1)
    for a,b in moves(nc):
        stock.cut(a,b,radius); replay.cut(a,b,radius)
    x,y=np.meshgrid(replay.x,replay.y)
    target=surface.heights(np.column_stack((x.ravel(),y.ravel())),radius+op['stock']).reshape(x.shape)+op['stock']
    slope=(target>-2)&(target<0)
    def slope_excess():
        return float(np.maximum(0,replay.heights[slope]-target[slope]).sum()*replay.dx*replay.dy)
    initial=slope_excess(); air_hits=0
    # Branch from the last cutting endpoint, before the existing layer retract.
    here=np.array(b); assert abs(here[2]+2)<.01, here
    width=radius*2*op['adaptive_engagement']/100
    proposals=front_proposals(stock,surface,area,here,-2.,0.,radius,width,'climb',op['stock'],90.)
    print('start',here,'proposals',len(proposals), 'non-flat',sum(a[2]!=b[2] for a,b in proposals),flush=True)
    # Attempt all nonflat proposals; every decision sees all preceding cuts.
    # The retract is a modeled vertical ascent, traverse above the top, then
    # a checked vertical descent. No links or NC are exported by this probe.
    accepted=[]; lifts=0
    from gcodeproducer.core.cam.wavefront.xyz_chain import extend_chain
    from gcodeproducer.core.cam.wavefront.xyz_residual import residual_proposals
    for pass_index in range(passes+1):
        before=len(accepted)
        targeted=pass_index==passes
        if targeted:
            live=slope & (replay.heights>target+.001)
            proposals=residual_proposals(surface,area,np.column_stack((x[live],y[live])),
                replay.heights[live]-target[live],-2.,0.,radius,width,'climb',op['stock'],budget=24)
            print('residual-targeted candidates',len(proposals),flush=True)
        elif pass_index:
            proposals=front_proposals(stock,surface,area,here,-2.,0.,radius,width,'climb',op['stock'],120.)
        for a,b in proposals:
            if not targeted and abs(a[2]-b[2])<.001: continue
            source=here
            result=join_front(stock,area,here,[(a,b)],radius,width,'climb')
            if result is None:
                result=join_front(stock,area,np.r_[a[:2],top+1],[(a,b)],radius,width,'climb')
                if result is not None:
                    lifts+=1; source=np.r_[a[:2],top+1]
            if result is not None:
                chain=extend_chain(stock,surface,area,result,radius,width,'climb',-2.,0.,op['stock'])
                air_hits+=int(replay.contact(source,a,radius))
                for p,q,_ in chain: replay.cut(p,q,radius)
                accepted.extend(chain); here=chain[-1][1]
        print('pass',pass_index+1,'segments',len(accepted)-before,'residual proxy',slope_excess(),flush=True)
        if targeted and len(accepted)==before: break
    print('accepted',len(accepted),'retracts',lifts,'XYZ cut mm',sum(np.linalg.norm(b-a) for a,b,_ in accepted),
          'peak width',max((w for _,_,w in accepted),default=0))
    print('slope-excess proxy mm3 before/after',initial,slope_excess(),'sampled entry/link hits',air_hits)
    return accepted


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('nc',type=Path); probe(p.parse_args().nc)
