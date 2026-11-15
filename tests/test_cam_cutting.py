"""Machining materials, SFM/chip load, limits, and independent manual unlocks."""
import math
import pytest

from gcodeproducer.core.cam_cutting import MATERIALS,resolve_cutting
from gcodeproducer.core.cam import Operation,CAMSetup,ToolGroup
from gcodeproducer.core.profiles import Profile
from gcodeproducer.core.stock import Stock
from gcodeproducer.core.cam_engagement import engagement_band,feed_factor


def fixture():
    machine=Profile("machine","mill",workflow="cam",values={"spindle_min":100,"spindle_max":16000})
    tool=Profile("tool","6mm",values={"diameter":6,"flutes":3,"auto_cutting_data":True,
        "max_spindle_rpm":12000,"max_doc":10,"steel_sfm":200,"steel_chip_load":.02})
    stock=Stock(category="steel")
    return machine,tool,stock


def test_sfm_chipload_and_tool_machine_caps():
    machine,tool,stock=fixture()
    op=Operation(kind="pocket",auto_stepdown=True)
    data=resolve_cutting(machine,tool,stock,op)
    assert data.rpm==math.floor(200*304.8/(math.pi*6))
    assert data.feed==pytest.approx(.02*3*data.rpm)
    assert data.stepdown==1.5
    tool.values["steel_sfm"]=5000
    assert resolve_cutting(machine,tool,stock,op).rpm==12000
    machine.values["spindle_max"]=10000
    assert resolve_cutting(machine,tool,stock,op).rpm==10000


@pytest.mark.parametrize("kind,step",[("slot",.9),("pocket",1.5),("profile",2.4)])
def test_material_axial_defaults_and_explicit_override(kind,step):
    machine,tool,stock=fixture()
    op=Operation(kind=kind,auto_stepdown=True)
    assert resolve_cutting(machine,tool,stock,op).stepdown==pytest.approx(step)
    tool.values[f"steel_{kind}_axial"]=10
    assert resolve_cutting(machine,tool,stock,op).stepdown==pytest.approx(.6)
    op.auto_stepdown=False;op.stepdown=.3
    assert resolve_cutting(machine,tool,stock,op).stepdown==.3


def test_unlocks_independent_rates_and_rpm_remains_capped():
    machine,tool,stock=fixture()
    op=Operation(unlock_feed=True,feed=1200,unlock_lead_feed=True,lead_feed=180,
                 unlock_rpm=True,rpm=30000)
    data=resolve_cutting(machine,tool,stock,op)
    assert (data.rpm,data.feed,data.lead_feed)==(12000,1200,180)
    restored=CAMSetup.from_dict(CAMSetup([ToolGroup(tool.id,[op])]).to_dict()).groups[0].operations[0]
    assert restored.unlock_feed and restored.unlock_lead_feed and restored.rpm==30000


def test_every_material_has_per_tool_data_and_can_be_tuned():
    machine,tool,stock=fixture()
    assert [m[1] for m in MATERIALS]==["Soft wood","Hard wood","Soft plastic","Hard plastic","Non-iron metal","Steel"]
    for key,_,_,_ in MATERIALS:
        stock.category=key
        data=resolve_cutting(machine,tool,stock,Operation(auto_stepdown=True))
        assert data.feed>0 and data.rpm>0
    tool.values["hard_plastic_chip_load"]=.011
    stock.category="hard_plastic"
    data=resolve_cutting(machine,tool,stock)
    assert data.feed==pytest.approx(data.rpm*3*.011)


def test_unattainably_low_sfm_is_not_silently_oversped():
    machine,tool,stock=fixture()
    machine.values["spindle_min"]=10000
    with pytest.raises(ValueError,match="below machine minimum"):
        resolve_cutting(machine,tool,stock)


def test_emitter_uses_selected_material_rpm_and_requires_cli_category():
    from gcodeproducer.core.job import Job,Layer,Path
    from gcodeproducer.stages.cam_emit import CAMEmit
    from gcodeproducer.stages.base import StageContext
    import numpy as np
    machine,tool,stock=fixture()
    op=Operation()
    layer=Layer(0,-1,1,paths=[Path("cut",np.array([[0.,0.],[1.,0.]]))])
    job=Job("cam",machine,tools=[tool],layers=[layer])
    with pytest.raises(ValueError,match="machining material"):
        CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    job.settings["machining_material"]="steel"
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    expected=resolve_cutting(machine,tool,stock,op).rpm
    spindle=[ln.params["S"] for ln in job.program.lines if ln.cmd=="M3"]
    assert spindle[-1]==pytest.approx(round(expected),abs=1)


@pytest.mark.parametrize("bad",[float("nan"),float("inf"),-1])
def test_invalid_rpm_ceiling_rejected(bad):
    machine,tool,stock=fixture()
    tool.values["max_spindle_rpm"]=bad
    with pytest.raises(ValueError):resolve_cutting(machine,tool,stock)


def test_machine_engagement_thresholds_and_modifiers():
    machine,tool,_=fixture()
    op=Operation()
    assert engagement_band(.2,machine)=="hsm"
    assert engagement_band(.8,machine)=="cut"
    assert engagement_band(.8001,machine)=="high"
    assert engagement_band(.9499,machine)=="high"
    assert engagement_band(.95,machine)=="slot"
    machine.values.update(high_engagement_threshold=70,high_engagement_feed=60,slotting_feed=40)
    assert engagement_band(.75,machine)=="high"
    assert feed_factor("high",op,tool,machine)==.6
    assert feed_factor("slot",op,tool,machine)==.4
    op.high_engagement_feed=90
    assert feed_factor("high",op,tool,machine)==.9
    machine.values["high_engagement_threshold"]=99
    with pytest.raises(ValueError,match="boundaries"):
        engagement_band(.5,machine)
