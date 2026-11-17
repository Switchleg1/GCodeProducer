"""Shared CAM motion planner: feed policy, phases, entries/exits and links for every operation."""
import copy
import numpy as np
import pytest
from gcodeproducer.core.cam import Operation, ToolGroup, generate
from gcodeproducer.core.cam.planner import FeedPolicy, EntryExitPlanner, LinkPlanner, MotionPlan
from gcodeproducer.core.cam.planner.planner_constants import PHASES, LEAD_BASE_PHASES, FACTOR_PHASES
from gcodeproducer.core.cam.height_stock import HeightStock
from gcodeproducer.core.cam.stock import Stock
from gcodeproducer.core.jobs.cut_condition import CutCondition
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import stepped_part, floor_ref, job_for

SLOT = CutCondition(1., "slot", "neutral", .5)
HSM = CutCondition(.2, "hsm", "climb", 1.1)
AIR = CutCondition(0., "air", "air", 1.)


def test_feed_policy_phase_base_band_factor_and_cap():
    policy = FeedPolicy(0)
    assert set(LEAD_BASE_PHASES) | set(FACTOR_PHASES) <= set(PHASES)
    # A lead-in is a lead-base move AND (normally) slotting: both apply.
    assert policy.rate("lead_in", 1000, 300, SLOT) == 150
    assert policy.rate("lead_in", 1000, 300, AIR) == 300
    assert policy.rate("cut", 1000, 300, SLOT) == 500
    assert policy.rate("cut", 1000, 300, HSM) == 1100
    assert policy.rate("link", 1000, 300, SLOT) == 500
    # A vertical plunge keeps its plunge rate; a verified-air approach is unscaled.
    assert policy.rate("plunge", 1000, 300, SLOT) == 300
    assert policy.rate("approach", 1000, 300, AIR) == 300
    # Engaged steep surface descent uses the slower base before the band factor.
    assert policy.rate("cut", 1000, 300, SLOT, steep=True) == 150
    assert policy.rate("cut", 1000, 300, AIR, steep=True) == 1000
    capped = FeedPolicy(400)
    assert capped.rate("cut", 1000, 300, HSM) == 400 and capped.capped == {(1100, 400)}
    with pytest.raises(ValueError, match="nonnegative"):
        FeedPolicy(-1)
    with pytest.raises(ValueError, match="positive"):
        policy.rate("cut", 0, 300)


def test_feed_policy_features_keep_phase_and_engagement_apart():
    policy = FeedPolicy(0)
    assert policy.feature("lead_in", SLOT) == "lead_in"
    assert policy.feature("plunge", SLOT) == "plunge"
    assert policy.feature("approach", AIR) == "air"
    assert policy.feature("cut", SLOT) == "slot"
    assert policy.feature("cut", HSM) == "hsm"
    conflict = CutCondition(.5, "cut", "conventional", 1., conflict=True)
    assert policy.feature("cut", conflict) == "conflict"
    assert FeedPolicy(0, highlight_conflicts=False).feature("cut", conflict) == "cut"


def cleared_state():
    stock = Stock(x=0, y=0, top=0, width=40, depth=40, height=10)
    state = HeightStock(stock, .1)
    state.heights[:] = 0
    state.heights[(state.y[:, None] > 10) & (state.y[:, None] < 30) & (state.x[None, :] > 10) & (state.x[None, :] < 30)] = -5
    return state


def test_entry_planner_ramps_only_into_material():
    state = cleared_state()
    planner = EntryExitPlanner(10, .5, 2)
    square = np.array([[15, 15], [25, 15], [25, 25], [15, 25.]])
    # Inside the cleared pocket the start column is clear down to Z-5: no lead.
    assert not planner.enters_material(state, (20, 20), -5)
    assert planner.planar(state, square, True, -5, 4) == (None, None)
    # Below the cleared floor the descent meets material: a ramp along the path.
    lead, kind = planner.planar(state, square, True, -6, 4)
    assert lead is not None and kind in ("linear", "helix")
    assert np.allclose(lead[-1], [15, 15, -6]) and lead[0, 2] == pytest.approx(-4.5)
    # Unknown material (no stock) is conservatively treated as entering material.
    assert planner.enters_material(None, (20, 20), -5)
    assert planner.planar(None, square, True, -5, 4) == (None, None)    # but no ramp without a state
    assert planner.planar(state, square[:1], True, -6, 4) == (None, "degenerate")


def test_link_planner_heights_and_stay_down():
    state = cleared_state()
    links = LinkPlanner(10, 1, .5, True, 2)
    position = np.array([20, 20, -5.])
    assert links.stay_at_depth(state, position, (22, 22), -6)
    assert not links.stay_at_depth(state, position, (5, 5), -6)      # material at the target
    assert not LinkPlanner(10, 1, .5, False, 2).stay_at_depth(state, position, (22, 22), -6)
    assert links.travel_height(state, position, (22, 22), -5) == pytest.approx(-4)
    assert links.travel_height(state, position, (5, 5), -5) == pytest.approx(1)
    assert links.travel_height(None, position, (5, 5), -5) == 10
    assert links.descent_height(state, 1, (22, 22), -6, lead=True) == pytest.approx(-4.5)
    assert links.descent_height(state, 1, (22, 22), -6, lead=False) == pytest.approx(-4)


def emitted(libset, **fields):
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    for key, value in fields.items():
        setattr(op, key, value)
    generate(job, StageContext())
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    return job, op


def test_every_feed_move_is_a_planned_segment_with_a_phase(libset):
    job, _ = emitted(libset)
    plan = job.motion_plan
    assert isinstance(plan, MotionPlan)
    feeds = [l for l in job.program.lines if l.cmd == "G1"]
    planned = [s for s in plan.segments if s.motion and s.phase != "rapid"]
    assert len(feeds) == len(planned)
    assert {s.phase for s in plan.segments if s.motion} <= set(PHASES)
    # Non-motion program lines (layer markers, spindle / tool change) are planned too.
    assert {s.phase for s in plan.segments if not s.motion} == {"comment", "command"}
    assert plan.of("lead_in") and plan.of("cut") and plan.of("link")
    # Lead-ins that contact material carry their measured band (normally slot).
    regimes = plan.regimes(("lead_in",))
    assert regimes["slot"] > 0


def test_planar_lead_in_uses_measured_band_and_operation_override(libset):
    job, op = emitted(libset, slotting_feed=30, unlock_lead_feed=True, lead_feed=300)
    sim = simulate(job.program)
    slot_leads = [s for s in job.motion_plan.of("lead_in") if s.condition.regime == "slot"]
    assert slot_leads and all(s.rate == pytest.approx(90) for s in slot_leads)      # 300 x operation 30 %
    air_leads = [s for s in job.motion_plan.of("lead_in") if s.condition.regime == "air"]
    assert all(s.rate == pytest.approx(300) for s in air_leads)
    rows = [i for i, l in enumerate(job.program.lines) if l.cmd == "G1" and l.feature == "lead_in"]
    assert set(np.round(sim.feed[rows], 6)) <= {90., 300.} | {s.rate for s in job.motion_plan.of("lead_in")}


def test_planar_reentry_into_cleared_material_skips_the_ramp(libset):
    job, op = emitted(libset)
    first = len(job.motion_plan.of("lead_in"))
    # Repeat the same operation: every entry now descends into material the first one removed.
    repeat = copy.deepcopy(op)
    repeat.name = "Repeat"
    job.cam_setup.groups.append(ToolGroup(job.tools[0].id, [repeat]))
    job.preferences["skip_air_cuts"] = False
    generate(job, StageContext())
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    second_layers = {l.index for l in job.layers if l.cam_operation == "Repeat"}
    lines = job.program.lines
    assert not any(l.cmd == "G1" and l.feature in ("lead_in", "plunge") and l.layer in second_layers for l in lines)
    assert any(l.cmd == "G1" and l.feature == "air" and l.layer in second_layers for l in lines)
    assert len(job.motion_plan.of("lead_in")) == first


def test_lead_out_follows_only_cleared_geometry(libset):
    job, _ = emitted(libset)
    outs = job.motion_plan.of("lead_out")
    assert outs and all(s.condition is not None and s.condition.regime == "air" for s in outs)
