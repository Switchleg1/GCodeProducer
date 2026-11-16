"""Material boundaries are live operation/height references, distinct from mesh ids."""
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from gcodeproducer.core.cam import (CAMSetup, Depth, Operation, Reference, ToolGroup, Topology,
                                     generate, highlight_geometry, pick_geometry)
from gcodeproducer.core.stock import Stock
from gcodeproducer.core.stock_geometry import vertices, polylines
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import stepped_part, floor_ref, job_for


def stock():
    return Stock(x=-5,y=-7,top=2,width=10,depth=14,height=8)


@pytest.mark.parametrize("axis,sign,face", [(2,1,1),(2,-1,0),(0,-1,4),(0,1,5),(1,-1,2),(1,1,3)])
def test_pick_all_stock_faces(axis,sign,face):
    s=stock();lo,hi=s.bounds
    origin=(lo+hi)/2;origin[axis]=(hi[axis]+10 if sign>0 else lo[axis]-10)
    direction=np.zeros(3);direction[axis]=-sign
    result=pick_geometry((None,"stock_face",origin,direction,np.eye(4),[100,100],[50,50],s))
    assert result["reference"]==Reference("stock_face",[face])
    p=polylines(s,result["reference"])[0]
    assert result["z_min"]==p[:,2].min() and result["z_max"]==p[:,2].max()


def test_stock_edge_pick_prefers_near_edge_in_top_view():
    mvp=np.diag([.05,.04,-.01,1.])
    result=pick_geometry((None,"stock_edge",[0,0,10],[0,0,-1],mvp,[100,100],[50,64],stock()))
    assert result["reference"]==Reference("stock_edge",[4])  # top Y-min edge, not the hidden bottom edge
    assert result["z_min"]==2
    assert pick_geometry((None,"stock_edge",[0,0,10],[0,0,-1],mvp,[100,100],[0,0],stock())) is None
    assert "error" in pick_geometry((None,"stock_face",[0,0,10],[0,0,-1],mvp,[100,100],[50,50],Stock()))


def test_live_depth_and_highlight_after_blank_resize():
    mesh=stepped_part();topo=Topology(mesh);s=stock()
    side=Reference("stock_face",[4])
    assert Depth("geometry",reference=side,extreme="min").resolve(mesh,topo,stock=s)==-6
    assert Depth("geometry",reference=side,extreme="max").resolve(mesh,topo,stock=s)==2
    refs=[Reference("stock_edge",[4]),Reference("stock_edge",[0])]
    assert Depth("selection",extreme="min").resolve(mesh,topo,refs,s)==-6
    s.height=12;s.top=3;s.width=20
    assert Depth("selection",extreme="min").resolve(mesh,topo,refs,s)==-9
    op=Operation(geometry=[Reference("stock_face",[1])])
    result=highlight_geometry((mesh,op,s))
    assert len(result["stock_faces"])==6 and result["edges"][:,0].max()==15
    assert not result["faces"]                 # never apply stock ids as mesh triangle ids
    # Use the canonical dataclass serializer to check references round-trip.
    setup=CAMSetup([ToolGroup("t",[op])],stock=s)
    assert CAMSetup.from_dict(setup.to_dict()).groups[0].operations[0].geometry==op.geometry
    s.width=0
    assert "Allocate material" in highlight_geometry((mesh,op,s))["depths"]


@pytest.mark.parametrize("strategy",["contour","raster"])
@pytest.mark.parametrize("selection",["face","edges","face_only"])
def test_material_pocket_protects_part_and_accepts_stock_rim(libset,strategy,selection):
    mesh=stepped_part();job,op=job_for(mesh,[floor_ref(mesh)],libset)
    job.cam_setup.stock.margin=6;job.cam_setup.stock.auto(mesh)
    refs=[Reference("stock_edge",[i]) for i in (4,5,6,7)] if selection=="edges" else [Reference("stock_face",[1])]
    # Mix a material envelope and part face: retain its OUTER footprint, not
    # XOR the nested stock/floor/boss boundaries or silently ignore that face.
    op.geometry=refs if selection=="face_only" else refs+[floor_ref(mesh)]
    op.strategy=strategy
    op.start=Depth("stock_top")
    op.end=Depth("geometry",reference=floor_ref(mesh),extreme="min") if selection=="face_only" else Depth("selection",extreme="min")
    generate(job,StageContext())
    assert min(l.z for l in job.layers)==-4
    points=np.concatenate([p.points for p in job.layers[-1].paths])
    assert abs(points).max()>24                    # clears beyond the part flange, to blank envelope
    inner = 11.4 if selection=="face_only" else 21.4
    assert np.linalg.norm(points,axis=1).min()>inner # explicit part face retains its whole footprint
    for path in job.layers[-1].paths:
        p=path.points
        line=LineString(np.vstack((p,p[0])) if path.closed else p)
        assert line.distance(Point(0,0))>inner
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    assert not [w for w in job.warnings if "rapid motion" in w]


@pytest.mark.parametrize("limit", [-1., 0., 1.])
def test_stock_pocket_uses_material_limit_even_without_overcut(libset,limit):
    mesh=stepped_part();job,op=job_for(mesh,[Reference("stock_face",[1])],libset)
    job.cam_setup.stock.margin=6;job.cam_setup.stock.auto(mesh)
    op.start=Depth("stock_top");op.end=Depth("absolute",-2)
    op.material_limit=limit;op.stock=.3
    generate(job,StageContext())
    points=np.concatenate([p.points for p in job.layers[-1].paths])
    assert abs(points).max()+1.5==pytest.approx(26+limit,abs=1e-6)


def test_facing_stock_above_the_part_has_no_spurious_part_island(libset):
    mesh=stepped_part();job,op=job_for(mesh,[Reference("stock_face",[1])],libset)
    job.cam_setup.stock.top=2;job.cam_setup.stock.height+=2
    op.start=Depth("stock_top");op.end=Depth("absolute",1)
    generate(job,StageContext())
    assert min(np.linalg.norm(p.points,axis=1).min() for p in job.layers[0].paths)<3


@pytest.mark.parametrize("strategy", ["contour", "raster"])
def test_single_material_edge_and_part_rim_clear_only_between_selected_bounds(libset, strategy):
    mesh=stepped_part()
    # The selected part edge is the flange rim (radius 20, Z-4), not the boss
    # (radius 10). At Z-1/-2 the automatic model section alone would protect
    # only the boss, but the explicitly selected flange rim must also be kept.
    job,op=job_for(mesh,[Reference("edge",[96,97]), Reference("stock_edge",[4])],libset)
    job.cam_setup.stock.margin=6;job.cam_setup.stock.auto(mesh)
    op.strategy=strategy;op.start=Depth("stock_top");op.end=Depth("absolute",-2)
    generate(job,StageContext())
    for layer in job.layers:
        for path in layer.paths:
            points=path.points
            line=LineString(np.vstack((points,points[0])) if path.closed else points)
            assert line.distance(Point(0,0))>21.4   # selected 20 mm rim + 1.5 mm cutter radius
    assert abs(np.concatenate([p.points for p in job.layers[-1].paths])).max()>24


def test_material_side_face_is_height_only_and_stock_edges_can_engrave(libset):
    mesh=stepped_part();job,op=job_for(mesh,[Reference("stock_face",[4])],libset)
    op.start=Depth("top");op.end=Depth("absolute",-1)
    with pytest.raises(ValueError,match="horizontal material face"):
        generate(job,StageContext())
    op.geometry=[Reference("stock_edge",[4])]
    op.kind="engrave"
    generate(job,StageContext())
    assert len(job.layers[0].paths[0].points)==2
    assert np.allclose(job.layers[0].paths[0].points[:,1],job.cam_setup.stock.y)
