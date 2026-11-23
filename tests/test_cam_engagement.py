"""Climb must follow remaining stock, not the first full-width slot/final wall."""
import numpy as np
import pytest
from shapely.geometry import box

from gcodeproducer.core.cam_engagement import measure_segments, engagement_band, feed_factor
from gcodeproducer.core.cam import generate, CAMSetup, ToolGroup, Operation
from gcodeproducer.core.geometry import area
from gcodeproducer.core.job import CutCondition, Layer, Path, Job
from gcodeproducer.core.profiles import Profile
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import stepped_part, floor_ref, job_for


@pytest.mark.parametrize("direction,sign", [("climb",-1),("conventional",1)])
def test_first_slot_is_neutral_subsequent_passes_follow_uncut_side(libset,direction,sign):
    mesh=stepped_part()
    job,op=job_for(mesh,[floor_ref(mesh)],libset)
    op.cut_direction=direction
    generate(job,StageContext())
    paths=job.layers[0].paths
    assert all(c.hand=="neutral" and c.regime=="slot" for c in paths[0].cut_conditions)
    assert len(paths)>2
    for path in paths[1:]:
        assert area(path.points)*sign>0
        assert all(c.hand in (direction,"neutral","air") for c in path.cut_conditions)
    assert job.warnings==[]


def test_meander_counts_one_sided_passes_not_neutral_slot(libset):
    mesh=stepped_part()
    job,op=job_for(mesh,[floor_ref(mesh)],libset)
    op.cut_direction="meander"
    generate(job,StageContext())
    paths=job.layers[0].paths
    assert all(c.hand=="neutral" for c in paths[0].cut_conditions)
    hands=[]
    for path in paths[1:]:
        labels=[c.hand for c in path.cut_conditions if c.hand in ("climb","conventional")]
        if labels:
            hands.append(max(set(labels),key=labels.count))
    assert hands[:4]==["climb","conventional","climb","conventional"]


def test_radial_measurement_and_forward_slot_entry():
    points=np.array([[-5.,0.],[5.,0.]])
    # A 1 mm radius cutter: 0.8 mm occupied radial width = 40% diameter.
    measured=measure_segments(points,False,box(-100,-100,100,-.2),1)
    assert measured[2][0]==pytest.approx(.4)
    assert measured[0][0]==0 and measured[1][0]>0   # uncut material to right: climb
    assert engagement_band(measured[2][0])=="cut"
    # Centreline stays in air, but the cutter's leading edge enters full stock.
    front=measure_segments(np.array([[-1.,0.],[-.1,0.]]),False,box(0,-100,100,100),1)
    assert front[2][0]>.95
    assert engagement_band(front[2][0])=="slot"


@pytest.mark.parametrize("value,band", [(0,"air"),(.1,"hsm"),(.15,"cut"),(.4,"cut"),(.7,"cut"),(.8,"cut"),(.9,"high"),(.99,"slot")])
def test_engagement_bands(value,band):
    assert engagement_band(value)==band


def test_feed_defaults_overrides_and_persistence():
    tool=Profile("tool","tool")
    op=Operation(kind="pocket")
    assert feed_factor("slot",op,tool)==.5
    assert feed_factor("high",op,tool)==.75
    assert feed_factor("standard",op,tool)==1
    tool.values["standard_engagement_feed"]=125
    assert feed_factor("standard",op,tool)==1.25
    op.standard_engagement_feed=150
    assert feed_factor("standard",op,tool)==1.5
    op.slotting_feed=60
    setup=CAMSetup([ToolGroup(tool.id,[op])])
    restored=CAMSetup.from_dict(setup.to_dict()).groups[0].operations[0]
    assert restored.standard_engagement_feed==150 and restored.slotting_feed==60
    assert Profile.from_dict(tool.to_dict()).get("standard_engagement_feed")==125


def test_emitted_slot_high_standard_feeds_and_machine_cap():
    tool=Profile("tool","mill",values={"feed":800,"plunge_feed":300})
    machine=Profile("machine","router",workflow="cam",values={"max_feed":1000})
    path=Path("cut",np.array([[0.,0.],[1.,0.],[2.,0.],[3.,0.]]),cut_conditions=[
        CutCondition(1,"slot","neutral",.5),
        CutCondition(.8,"high","climb",.75),
        CutCondition(.6,"cut","climb",1.5)])
    layer=Layer(0,-1,1,paths=[path])
    layer.cam_operation="test"
    job=Job("cam",machine,tools=[tool],layers=[layer])
    job.preferences={"cam_feed_smoothing":0}   # each band's own feed (smoothing may only lower them)
    context=StageContext()
    CAMEmit().run(job,CAMEmit.resolve({}),context)
    cuts=[ln for ln in job.program.lines if ln.cmd=="G1" and "X" in ln.params]
    assert [ln.params["F"] for ln in cuts]==[400,600,1000]
    assert [ln.feature for ln in cuts]==["slot","high_engagement","cut"]
    assert [ln.engagement for ln in cuts]==[1,.8,.6]
    assert "neutral" in cuts[0].note and "climb" in cuts[1].note
    assert any("CAM feed capped" in s for s in context.messages)
    from gcodeproducer.core.toolpath import build_toolpath
    tp=build_toolpath(job.program)
    wanted={i for i,ln in enumerate(job.program.lines) if ln.cmd=="G1" and "X" in ln.params}
    assert np.allclose(tp.engagement[np.isin(tp.line,list(wanted))],[1,.8,.6])


def test_mixed_hand_warning_survives_emission_and_stock_checks():
    from tests.test_cam_paths import circle
    from gcodeproducer.core.cam_engagement import plan_engagement
    from gcodeproducer.core.stock import Stock
    tool=Profile("tool","mill",values={"diameter":2})
    machine=Profile("machine","router",workflow="cam")
    op=Operation(kind="profile",name="mixed")
    path=Path("cut",circle(5),closed=True,width=2)
    layer=Layer(0,-1,1,paths=[path])
    layer.cam_operation=op.name
    setup=CAMSetup(stock=Stock(x=-10,y=-.2,width=20,depth=.4,height=2))
    job=Job("cam",machine,tools=[tool],cam_setup=setup,layers=[layer])
    job.warnings=plan_engagement([path],job,op,tool)
    assert any("not every non-slot segment" in w for w in job.warnings)
    before=list(job.warnings)
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    assert all(w in job.warnings for w in before)


def test_small_positive_effective_feed_is_not_rounded_to_zero():
    tool=Profile("tool","slow",values={"feed":1})
    path=Path("cut",np.array([[0.,0.],[1.,0.]]),cut_conditions=[CutCondition(.1,"hsm","climb",.01)])
    job=Job("cam",Profile("machine","mill",workflow="cam"),tools=[tool],layers=[Layer(0,-1,1,paths=[path])])
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    line=next(ln for ln in job.program.lines if ln.cmd=="G1" and "X" in ln.params)
    assert line.params["F"]==pytest.approx(.01)


def test_stay_down_entries_are_classified_and_slowed(libset):
    mesh=stepped_part()
    job,op=job_for(mesh,[floor_ref(mesh)],libset)
    op.standard_engagement_feed=150
    generate(job,StageContext())
    links=[p.link_condition for p in job.layers[0].paths[1:] if p.stay_down]
    assert links and all(c is not None for c in links)
    assert any(c.regime in ("slot","high") and c.feed_factor<1 for c in links)
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    emitted=[ln for ln in job.program.lines if ln.comment=="stay-down link"]
    assert emitted and all(np.isfinite(ln.engagement) for ln in emitted)
    assert job.warnings==[]
