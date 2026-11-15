"""Stock allocation, negative-Z CAM placement, and conservative collision checks."""
import numpy as np
import pytest

from gcodeproducer.core.stock import Stock, check_stock
from gcodeproducer.core.cam import CAMSetup, ToolGroup, Operation, Reference, Depth
from gcodeproducer.core.placement import Placement, bed_rect, fits
from gcodeproducer.core.session import build_job, load_mesh, place_mesh, slice_job
from gcodeproducer.core.profiles import Profile
from gcodeproducer.core.builder import GCodeBuilder


@pytest.fixture
def job(libset, cube_stl):
    tool = libset["tool"].get("6-mm-flat-endmill")
    machine = Profile("machine", "router", workflow="cam", values={"safe_z": 10})
    return build_job("cam", machine, tools=[tool], mesh=load_mesh(cube_stl), cam_setup=CAMSetup())


def test_default_cam_top_zero_fdm_unchanged(job, libset, cube_stl):
    place_mesh(job)
    lo, hi = job.mesh.bounds
    assert (lo[2], hi[2]) == (-20, 0)
    assert fits(job.mesh, bed_rect(job.machine, "cam"))
    pl = Placement(z_anchor="top", z=-3, rx=45)
    placed = pl.apply(load_mesh(cube_stl))
    assert placed.bounds[1][2] == pytest.approx(-3)
    fdm = build_job("fdm", libset.machines.get("generic-220-fdm"), mesh=load_mesh(cube_stl))
    place_mesh(fdm)
    assert fdm.mesh.bounds[0][2] == 0


def test_auto_stock_margin_and_roundtrip(job):
    place_mesh(job)
    stock = job.cam_setup.stock
    stock.margin = 3
    stock.material, stock.density = "Aluminium", 2.7
    stock.auto(job.mesh)
    assert (stock.width, stock.depth, stock.height, stock.top) == (26, 26, 23, 0)
    lo, hi = stock.bounds
    assert np.allclose(lo, [-3, -3, -23]) and np.allclose(hi, [23, 23, 0])
    assert CAMSetup.from_dict(job.cam_setup.to_dict()).stock == stock
    assert Stock.from_dict({}).allocated is False


def checked(job, lines):
    place_mesh(job)
    job.cam_setup.stock.auto(job.mesh)
    b = GCodeBuilder(relative_e=False)
    b.raw(lines)
    return check_stock(job, b.program())


def test_rapid_crossing_stock_warns(job):
    warnings = checked(job, "G0 Z10\nT1 M6\nG0 X-10 Y10\nG0 Z-5\nG0 X30")
    assert any("rapid motion intersects" in w and "Line 5" in w for w in warnings)


def test_radius_near_edge_counts_as_collision(job):
    # Stock starts X=-2, tool radius=3: X=-4 is outside blank but cutter overlaps it.
    warnings = checked(job, "G0 Z10\nT1 M6\nG0 X-4 Y10\nG0 Z-5")
    assert any("Line 4" in w and "rapid motion" in w for w in warnings)


def test_safe_travel_and_retract_not_flagged(job):
    warnings = checked(job, "G0 Z10\nT1 M6\nM3 S18000\nG0 X10 Y10\nG1 Z-2\nG0 Z10\nG0 X30")
    assert any("unclassified" in w for w in warnings)
    assert not any("rapid motion" in w for w in warnings)


def test_custom_entry_spindle_off_bottom_and_tool_change(job):
    warnings = checked(job, "G0 Z10\nT1 M6\nG0 X10 Y10\nG1 Z-30\nT2 M6")
    assert any("spindle stopped" in w for w in warnings)
    assert any("material bottom" in w for w in warnings)
    assert any("tool change" in w for w in warnings)


def test_arc_and_unmodelled_motion_warn(job):
    warnings = checked(job, "G0 Z10\nG2 X10 Y10 I5 J0\nG53 G0 Z0\nG81 X10 Y10 Z-3 R1")
    assert any("arc motion" in w for w in warnings)
    assert any("G53" in w for w in warnings)
    assert any("G81" in w for w in warnings)


def test_generated_cuts_are_intended_not_collisions(job):
    # Configure stock from placed geometry, but pass original mesh into slice_job.
    placed = Placement(z_anchor="top").apply(job.mesh)
    job.cam_setup.stock.auto(placed)
    tris = job.mesh.vertices[job.mesh.triangles]
    face = int(np.flatnonzero(np.all(np.isclose(tris[:, :, 2], 20), axis=1))[0])
    op = Operation(geometry=[Reference("face", [face])], end=Depth("top", -2))
    job.cam_setup.groups = [ToolGroup(job.tools[0].id, [op])]
    result = slice_job(job)
    assert result.program is not None and job.warnings == []
    assert job.layers[-1].z == -2


def test_skipped_material_at_entry_warns(job):
    placed = Placement(z_anchor="top").apply(job.mesh)
    job.cam_setup.stock.auto(placed)
    tris = job.mesh.vertices[job.mesh.triangles]
    face = int(np.flatnonzero(np.all(np.isclose(tris[:, :, 2], 20), axis=1))[0])
    op = Operation(geometry=[Reference("face", [face])], start=Depth("top", -10), end=Depth("top", -11))
    job.cam_setup.groups = [ToolGroup(job.tools[0].id, [op])]
    slice_job(job)
    assert any("uncleared entry depth" in w for w in job.warnings)


def test_missing_stock_and_stock_not_enclosing_part(job):
    b = GCodeBuilder()
    assert "not allocated" in check_stock(job, b.program())[0]
    place_mesh(job)
    job.cam_setup.stock = Stock(width=1, depth=1, height=1)
    assert any("not fully contained" in w for w in check_stock(job, b.program()))
