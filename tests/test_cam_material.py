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
    assert ramp(np.array([[0.,0.],[1.,0.]]),False,-5,5,1) is None


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
