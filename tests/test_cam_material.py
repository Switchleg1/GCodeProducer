"""Ordered removal, current-material collision checks, leads and operation outputs."""
import numpy as np
import pytest
from shapely.geometry import box

from gcodeproducer.core.cam_material import HeightStock,PlanarStock,simulate_material
from gcodeproducer.core.cam_leads import ramp,walk
from gcodeproducer.core.cam import generate,Operation,Depth
from gcodeproducer.core.stock import Stock
from gcodeproducer.core.job import Path,Job
from gcodeproducer.core.profiles import Profile
from gcodeproducer.core.builder import GCodeBuilder
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import stepped_part,floor_ref,job_for


def test_height_field_removes_and_keeps_state():
    stock=Stock(width=20,depth=20,height=5)
    state=HeightStock(stock,.25)
    a=np.array([2.,10.,-2.]);b=np.array([18.,10.,-2.])
    assert state.contact(a,b,1)
    state.cut(a,b,1)
    assert not state.contact(a,b,1)
    assert state.contact(a,b-.5,1)
    assert state.height_at([10,10],.1)==-2
    assert state.height_at([10,15],.1)==0
    surface=state.surface()
    assert surface.shape[1]==3 and np.isfinite(surface).all()
    assert surface[:,2].min()>=-5 and surface[:,2].max()==0


def test_diagonal_sweep_checks_lowest_tip_during_cell_contact():
    state=HeightStock(Stock(x=0,y=4.9,width=.25,depth=.2,height=2),.1)
    a=np.array([-2.,5.,3.]);b=np.array([2.,5.,-1.])
    assert state.contact(a,b,2)  # nearest-XY Z alone is above stock and would miss this
    state.cut(a,b,2)
    assert state.heights.min()<0


def test_planar_history_applies_only_to_depths_already_removed():
    stock=Stock(width=20,depth=20,height=5)
    history=PlanarStock(stock)
    paths=[Path("cut",np.array([[2.,10.],[18.,10.]]))]
    history.remove(paths,-2,1)
    assert history.at(-1).area < history.blank.area
    assert history.at(-3).area == history.blank.area


def test_current_material_allows_cleared_rapid_but_warns_uncleared_contact():
    stock=Stock(width=20,depth=20,height=5)
    from gcodeproducer.core.cam import CAMSetup
    tool=Profile("tool","2mm",values={"diameter":2,"max_doc":2})
    job=Job("cam",Profile("machine","mill",workflow="cam"),tools=[tool],cam_setup=CAMSetup(stock=stock))
    b=GCodeBuilder();b.raw("G0 Z10\nT1 M6\nM3 S12000\nG0 X2 Y10")
    b.op="1 pocket";b.set_feature("plunge");b.command("G1 Z-2 F100")
    b.set_feature("cut");b.command("G1 X18 F800")
    b.set_feature("rapid");clear=b.command("G0 X2")
    bad=b.command("G0 Y15")
    b.op="2 process";b.set_feature("cut");b.command("G1 Z-3 F100")
    program=b.program()
    warnings,outputs=simulate_material(job,program)
    clear_line=program.lines.index(clear)+1;bad_line=program.lines.index(bad)+1
    assert not any(f"Line {clear_line}:" in w and "rapid motion" in w for w in warnings)
    assert any(f"Line {bad_line}:" in w and "CURRENT" in w for w in warnings)
    assert [o["label"] for o in outputs]==["Initial material","1 pocket","2 process"]
    assert not np.array_equal(outputs[0]["heights"],outputs[1]["heights"])
    assert not np.shares_memory(outputs[1]["heights"],outputs[2]["heights"])


def test_leads_stay_on_contour_and_limit_ramp_slope():
    square=np.array([[0.,0.],[30.,0.],[30.,30.],[0.,30.]])
    lead=ramp(square,True,-1,2,3)
    assert lead is not None and np.allclose(lead[-1],[0,0,-1])
    distance=np.linalg.norm(np.diff(lead[:,:2],axis=0),axis=1)
    slope=np.abs(np.diff(lead[:,2]))/distance
    assert slope.max()<=np.tan(np.deg2rad(10))+1e-9
    assert walk(square,True,10000,True) is None
    assert ramp(np.array([[0.,0.]]),False,-5,5,1) is None          # only a single point cannot ramp


def _on_segments(xy,path,closed):
    """Every ramp vertex lies on the original path (within numerical tolerance)."""
    from shapely.geometry import LineString,Point
    line=LineString(np.vstack((path,path[0])) if closed else path)
    return all(line.distance(Point(q))<1e-6 for q in xy)


def test_short_closed_contour_helixes_along_itself():
    from gcodeproducer.core.cam_leads import ramp_entry
    circle=np.column_stack((2*np.cos(np.linspace(0,2*np.pi,24,endpoint=False)),2*np.sin(np.linspace(0,2*np.pi,24,endpoint=False))))
    lead,kind=ramp_entry(circle,True,-6,1,0)                     # 7 mm drop needs ~39.7 mm; perimeter ~12.5 mm
    assert kind=="helix" and np.allclose(lead[-1],[circle[0][0],circle[0][1],-6]) and lead[0,2]==1
    distance=np.linalg.norm(np.diff(lead[:,:2],axis=0),axis=1)
    assert (np.abs(np.diff(lead[:,2]))<=np.tan(np.deg2rad(10))*distance+1e-9).all()
    assert distance.sum()>3*11.9 and _on_segments(lead[:,:2],circle,True)
    # Direction: arriving at the seam the ramp moves the same way the cut will start.
    assert np.dot(lead[-1,:2]-lead[-2,:2],circle[1]-circle[0])>0


def test_short_open_path_zigzags_along_itself():
    from gcodeproducer.core.cam_leads import ramp_entry
    slot=np.array([[0.,0.],[3.,0.],[5.,1.]])
    lead,kind=ramp_entry(slot,False,-4,1,0)
    assert kind=="zigzag" and np.allclose(lead[-1],[0,0,-4])
    distance=np.linalg.norm(np.diff(lead[:,:2],axis=0),axis=1)
    assert (np.abs(np.diff(lead[:,2]))<=np.tan(np.deg2rad(10))*distance+1e-9).all()
    assert _on_segments(lead[:,:2],slot,False)
    assert lead[:,0].max()>4.9                                    # uses the whole path length per leg
    long_enough,kind=ramp_entry(np.array([[0.,0.],[100.,0.]]),False,-1,1,0)
    assert kind=="linear" and long_enough[:,0].max()<12


def test_emitted_leads_and_calculated_process_surfaces(libset):
    mesh=stepped_part()
    job,op=job_for(mesh,[floor_ref(mesh)],libset)
    generate(job,StageContext())
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    assert any(l.feature=="lead_in" and l.cmd=="G1" for l in job.program.lines)
    assert any(l.feature=="lead_out" and l.cmd=="G1" for l in job.program.lines)
    assert len(job.material_results)==2
    assert job.material_results[-1]["last_layer"]==len(job.layers)-1
    assert job.material_results[-1]["heights"].min()<0


def test_later_operation_uses_prior_removal_in_engagement(libset):
    mesh=stepped_part()
    job,op=job_for(mesh,[floor_ref(mesh)],libset)
    op.end=Depth("top",-2)
    second=Operation(kind="pocket",name="previously cleared",geometry=[floor_ref(mesh)],
                     start=Depth("top"),end=Depth("top",-1))
    job.cam_setup.groups[0].operations.append(second)
    ctx=StageContext()
    generate(job,ctx)   # default: remove air cutting -> fully cleared operation is skipped
    assert not [l for l in job.layers if l.cam_operation==second.name]
    job.preferences={"skip_air_cuts":False}
    generate(job,StageContext())
    later=[l for l in job.layers if l.cam_operation==second.name]
    assert later
    conditions=[c for p in later[0].paths for c in p.cut_conditions]
    assert all(c.regime not in ("slot","high") for c in conditions)
    assert np.mean([c.engagement for c in conditions])<.1


def test_short_section_exit_is_shortened_not_skipped():
    from gcodeproducer.core.cam_leads import exit_path
    short = np.array([[0.,0.], [1.,0.]])
    out = exit_path(short, False, 3)
    assert out is not None and np.allclose(out, [[1,0], [0,0]])
    assert exit_path(short[:1], False, 3) is None


def test_excessive_ramp_never_silently_falls_back_to_plunge():
    from gcodeproducer.core.cam_leads import ramp_entry
    with pytest.raises(ValueError, match="Lead-in would exceed"):
        ramp_entry(np.array([[0.,0.], [.0001,0.]]), False, -10, 1, 0)


def test_ramp_length_is_exactly_what_the_slope_needs():
    from gcodeproducer.core.cam_leads import ramp_entry
    square=np.array([[0.,0.],[2.,0.],[2.,2.],[0.,2.]])
    lead,_=ramp_entry(square,True,-3,0,0)
    needed=3/np.tan(np.deg2rad(10))
    assert np.linalg.norm(np.diff(lead[:,:2],axis=0),axis=1).sum()==pytest.approx(needed,rel=1e-9)


def test_entry_depth_check_distinguishes_helix_ramp_from_plunge():
    """A <=10 degree helix beside an uncut wall is side contact, not an uncleared plunge."""
    from gcodeproducer.core.cam import CAMSetup
    from gcodeproducer.core.cam_leads import ramp_entry
    stock=Stock(x=-10,y=-10,width=20,depth=20,height=10)
    tool=Profile("tool","3mm",values={"diameter":3,"max_doc":1})
    job=Job("cam",Profile("machine","mill",workflow="cam"),tools=[tool],cam_setup=CAMSetup(stock=stock))
    circle=np.column_stack((2*np.cos(np.linspace(0,2*np.pi,32,endpoint=False)),2*np.sin(np.linspace(0,2*np.pi,32,endpoint=False))))
    lead,kind=ramp_entry(circle,True,-5,1,0)
    assert kind=="helix"
    b=GCodeBuilder();b.raw(f"G0 Z10\nT1 M6\nM3 S12000\nG0 X{lead[0,0]:.4f} Y{lead[0,1]:.4f}\nG0 Z1")
    b.op="1 pocket";b.set_feature("lead_in")
    for q in lead[1:]:b.command(f"G1 X{q[0]:.4f} Y{q[1]:.4f} Z{q[2]:.4f} F200")
    b.set_feature("rapid");b.command("G0 Z10");b.command("G0 X6 Y6")
    b.set_feature("plunge");plunge=b.command("G1 Z-4 F100")
    program=b.program()
    warnings,_=simulate_material(job,program)
    entry=[w for w in warnings if "entry depth" in w]
    plunge_line=program.lines.index(plunge)+1
    assert entry==[w for w in entry if w.startswith(f"Line {plunge_line}:")] and entry   # only the plunge
    assert "plunge" in entry[0]
