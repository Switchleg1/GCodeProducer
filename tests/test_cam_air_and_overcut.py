"""Global settings, air-cut removal from prior material, overcut into void, conflict/collision colouring."""
import json

import numpy as np
import pytest
from shapely.geometry import box, Point, Polygon

from gcodeproducer.core import app_settings
from gcodeproducer.core.cam import Depth, Operation, Reference, generate
from gcodeproducer.core.cam_material import HeightStock, PlanarStock
from gcodeproducer.core.cam_paths import overcut_region, part_section
from gcodeproducer.core.job import CutCondition, Job, Layer, Path
from gcodeproducer.core.profiles import Profile
from gcodeproducer.core.stock import Stock
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit, mark_collisions
from tests.test_pocket_bounds import floor_ref, job_for, stepped_part


class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, text):
        self.lines.append(text)


def ctx_with_log():
    ctx = StageContext()
    log = Log()
    ctx.log = log
    return ctx, log


# ---------------------------------------------------------------- settings
def test_settings_roundtrip_and_validation(tmp_path):
    assert app_settings.load(tmp_path) == app_settings.DEFAULTS
    app_settings.save({"stock_resolution": 0.001, "skip_air_cuts": 0, "stock_max_cells": "abc", "junk": 1}, tmp_path)
    stored = json.loads((tmp_path / "settings.json").read_text())
    assert "junk" not in stored
    loaded = app_settings.load(tmp_path)
    assert loaded["stock_resolution"] == pytest.approx(0.02)       # clamped to schema minimum
    assert loaded["skip_air_cuts"] is False
    assert loaded["stock_max_cells"] == app_settings.DEFAULTS["stock_max_cells"]
    (tmp_path / "settings.json").write_text("{not json")
    assert app_settings.load(tmp_path) == app_settings.DEFAULTS   # corrupt file never blocks start-up


def test_height_stock_reports_coarsening_by_cell_limit():
    state = HeightStock(Stock(width=100, depth=100, height=5), .1, max_cells=10_000)
    assert state.coarsened and state.resolution >= 1.0 - 1e-9
    fine = HeightStock(Stock(width=10, depth=10, height=5), .1, max_cells=100_000)
    assert not fine.coarsened and fine.resolution == pytest.approx(.1)


# ---------------------------------------------------------------- air cutting
def test_top_within_finds_first_depth_with_material():
    history = PlanarStock(Stock(width=20, depth=20, height=10))
    probe = Point(10, 10).buffer(3)
    assert history.top_within(probe, 0, -10) == 0
    history.remove([Path("cut", np.array([[5., 10.], [15., 10.]]), width=6)], -4, 3)
    assert history.top_within(probe, 0, -10) == pytest.approx(-4)
    assert history.top_within(probe, 0, -3) is None            # entirely removed in that range
    assert history.top_within(Point(2, 2).buffer(.5), 0, -10) == 0   # untouched area


def test_second_operation_starts_below_cleared_material(libset):
    mesh = stepped_part()
    job, first = job_for(mesh, [floor_ref(mesh)], libset)
    first.end = Depth("top", -2)
    second = Operation(kind="pocket", name="deeper", geometry=[floor_ref(mesh)],
                       start=Depth("stock_top"), end=Depth("top", -4), stepdown=1)
    job.cam_setup.groups[0].operations.append(second)
    ctx, log = ctx_with_log()
    generate(job, ctx)
    later = [l for l in job.layers if l.cam_operation == "deeper"]
    assert later and max(l.z for l in later) <= -3 + 1e-9        # no passes in the already-cleared Z0..-2
    assert any("start lowered" in line for line in log.lines)
    job.preferences = {"skip_air_cuts": False}
    generate(job, StageContext())
    later = [l for l in job.layers if l.cam_operation == "deeper"]
    assert max(l.z for l in later) > -2                          # user explicitly keeps air passes


def test_flat_floor_selection_starts_at_material_surface(libset):
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    op.start = Depth("selection", extreme="max")                 # GUI default for new pockets
    ctx, log = ctx_with_log()
    generate(job, ctx)
    assert any("material surface" in line for line in log.lines)
    assert max(l.z for l in job.layers) > -4 and min(l.z for l in job.layers) == pytest.approx(-4)


def test_two_rims_start_at_highest_selected_edge(libset):
    mesh = stepped_part()
    refs = [Reference("edge", [2*48, 2*48+1]), Reference("edge", [4*48, 4*48+1])]   # Z-4 and Z0 rims
    job, op = job_for(mesh, refs, libset)
    op.start = Depth("selection", extreme="max")
    generate(job, StageContext())
    assert max(l.z for l in job.layers) <= 0 and min(l.z for l in job.layers) == pytest.approx(-4)


# ---------------------------------------------------------------- overcut
def test_overcut_grows_into_void_but_not_into_part():
    region = box(0, 0, 10, 10)
    part = box(10, 0, 20, 10)               # part body touching the pocket's east wall
    grown = overcut_region(region, 2, part)
    assert grown.area == pytest.approx(region.area + 3*20 + 2*2*2*np.pi/4, rel=.05)  # west/north/south + rounded corners
    assert grown.intersection(part).area < 1e-9
    assert grown.covers(Point(-1.5, 5))     # void side
    assert not grown.covers(Point(11, 5))   # part side
    limited = overcut_region(region, 2, part, limit=box(-1, -1, 11, 11))
    assert not limited.covers(Point(-1.5, 5))
    assert overcut_region(region, 0, part).equals(region)


def test_part_section_samples_each_depth_and_adds_clearance():
    mesh = stepped_part()
    boss = part_section(mesh, [-4], 0)      # just above the floor: the boss only
    assert boss.covers(Point(0, 7)) and not boss.covers(Point(0, 15))
    deep = part_section(mesh, [-4, -8], 0)  # union with the full plate section
    assert deep.covers(Point(0, 15))
    assert part_section(mesh, [-4], 1).covers(Point(0, 10.5))   # clearance ring around the boss


def test_pocket_overcut_only_outward_of_flange(libset):
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    job.cam_setup.stock.margin = 6
    job.cam_setup.stock.auto(mesh)
    generate(job, StageContext())
    plain = max(np.linalg.norm(p.points, axis=1).max() for p in job.layers[-1].paths)
    inner_plain = min(np.linalg.norm(p.points, axis=1).min() for p in job.layers[-1].paths)
    op.overcut = 3
    ctx, log = ctx_with_log()
    generate(job, ctx)
    grown = max(np.linalg.norm(p.points, axis=1).max() for p in job.layers[-1].paths)
    inner_grown = min(np.linalg.norm(p.points, axis=1).min() for p in job.layers[-1].paths)
    assert grown > plain + 2.5                                   # tool centre moves out past the flange rim
    assert inner_grown == pytest.approx(inner_plain, abs=.03)    # boss (part) side untouched (seam points sit on chords)
    assert any("overcut" in line for line in log.lines)
    op.overcut = -1
    with pytest.raises(ValueError, match="overcut"):
        generate(job, StageContext())


# ---------------------------------------------------------------- highlighting
def test_conflict_segments_become_conflict_feature():
    tool = Profile("tool", "t", values={"feed": 500})
    path = Path("cut", np.array([[0., 0.], [1., 0.], [2., 0.]]),
                cut_conditions=[CutCondition(.5, "cut", "climb"), CutCondition(.5, "cut", "conventional", conflict=True)])
    job = Job("cam", Profile("machine", "m", workflow="cam"), tools=[tool], layers=[Layer(0, -1, 1, paths=[path])])
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    features = [ln.feature for ln in job.program.lines if ln.cmd == "G1" and "X" in ln.params]
    assert features == ["cut", "conflict"]
    job.preferences = {"highlight_conflicts": False}
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    features = [ln.feature for ln in job.program.lines if ln.cmd == "G1" and "X" in ln.params]
    assert features == ["cut", "cut"]


def test_mark_collisions_maps_line_findings_only():
    from gcodeproducer.core.builder import GCodeBuilder
    b = GCodeBuilder()
    b.set_feature("rapid"); b.command("G0 X1"); b.command("G0 X2")
    prog = b.program()
    n = mark_collisions(prog, ["Line 2: rapid motion contacts CURRENT remaining material.",
                               "Safe Z is at or below the material surface", "Line 99: nothing"])
    assert n == 1 and prog.lines[1].feature == "collision" and prog.lines[0].feature == "rapid"


def test_emitter_recolours_flagged_rapid_as_collision(libset):
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    generate(job, StageContext())
    machine = job.machine
    machine.values["safe_z"] = 1.0        # above the model but low enough that nothing else breaks
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    collisions = [ln for ln in job.program.lines if ln.feature == "collision"]
    flagged_lines = [w for w in job.warnings if w.startswith("Line ")]
    assert len(collisions) == len({int(w.split()[1][:-1]) for w in flagged_lines})


def test_reach_check_uses_current_material_surface(libset):
    mesh = stepped_part()
    job, first = job_for(mesh, [floor_ref(mesh)], libset)
    first.end = Depth("top", -3)
    tool = job.tools[0]
    tool.values["length"] = 2.5                        # shorter than the 4 mm total floor depth
    second = Operation(kind="pocket", name="finish", geometry=[floor_ref(mesh)],
                       start=Depth("stock_top"), end=Depth("top", -4), stepdown=1)
    job.cam_setup.groups[0].operations.append(second)
    generate(job, StageContext())
    reach = [w for w in job.warnings if "cutting length" in w]
    assert reach and not any(w.startswith("finish") for w in reach)   # first op: 3 mm > 2.5; second: only 1 mm below Z-3
    tool.values["length"] = 20
    generate(job, StageContext())
    assert not [w for w in job.warnings if "cutting length" in w]
