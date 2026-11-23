from gcodeproducer.core.cam.cutting_data import CuttingData
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


def test_saved_axial_values_follow_active_material_and_operation_kind(tmp_path):
    from gcodeproducer.core.profiles import LibrarySet
    machine,tool,stock=fixture()
    tool.values.update(diameter=4, max_doc=2, soft_wood_pocket_axial=10,
                       soft_wood_profile_axial=30, non_iron_metal_pocket_axial=17,
                       non_iron_metal_profile_axial=35)
    lib=LibrarySet(tmp_path);lib["tool"].add(tool);lib.save()
    saved=LibrarySet(tmp_path).load()["tool"].get(tool.id)
    for category,kind,percent in (("soft_wood","pocket",10),("soft_wood","profile",30),
                                   ("non_iron_metal","pocket",17),("non_iron_metal","profile",35)):
        stock.category=category
        data=resolve_cutting(machine,saved,stock,Operation(kind=kind,auto_stepdown=True))
        assert data.stepdown==pytest.approx(4*percent/100)
        assert data.depth_source==f"{kind.title()} {percent}% D"
        assert category==data.material
        assert f"{percent}% D" in data.summary()
    tool.values["max_doc"]=.5
    stock.category="non_iron_metal"
    data=resolve_cutting(machine,tool,stock,Operation(kind="profile",auto_stepdown=True))
    assert "Profile 35% D" in data.summary() and "capped from 1.400" in data.summary()
    manual=resolve_cutting(machine,tool,stock,Operation(auto_stepdown=False,stepdown=.3))
    assert "Operation depth override" in manual.summary() and manual.stepdown==.3


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


def test_plunge_from_machine_lead_in_from_tool_operation_percent_then_unlock_overrides():
    machine,tool,stock=fixture()
    data=resolve_cutting(machine,tool,stock)
    assert data.lead_feed==pytest.approx(data.feed*.35)        # tool lead-in default
    assert data.plunge==pytest.approx(data.feed*.30)           # machine plunge default
    machine.values["plunge_feed_modifier"]=20
    assert resolve_cutting(machine,tool,stock).plunge==pytest.approx(data.feed*.2)
    tool.values["auto_cutting_data"]=False; tool.values.update(feed=1000,plunge_feed=250)
    data=resolve_cutting(machine,tool,stock)
    assert (data.feed,data.lead_feed,data.plunge)==(1000,250,200)   # fixed lead-in; machine plunge %
    # Operation engagement feeds: percentages of the tool feed, 0 = the defaults above.
    op=Operation(lead_in_feed_modifier=40,plunge_feed_modifier=15)
    data=resolve_cutting(machine,tool,stock,op)
    assert (data.lead_feed,data.plunge)==(400,150)
    # Unlocked feeds override what was calculated.
    op.unlock_lead_feed,op.lead_feed,op.unlock_plunge_feed,op.plunge_feed=True,321,True,90
    assert (resolve_cutting(machine,tool,stock,op).lead_feed,resolve_cutting(machine,tool,stock,op).plunge)==(321,90)
    restored=CAMSetup.from_dict(CAMSetup([ToolGroup(tool.id,[op])]).to_dict()).groups[0].operations[0]
    assert (restored.lead_in_feed_modifier,restored.plunge_feed_modifier,restored.plunge_feed)==(40,15,90)
    assert CuttingData(1,2,3,4,"soft_wood").plunge==3           # older saved data


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
    assert engagement_band(.1,machine)=="hsm"
    assert engagement_band(.15,machine)=="cut"      # default HSM / Cut boundary 15%
    assert engagement_band(.4,machine)=="cut"
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
