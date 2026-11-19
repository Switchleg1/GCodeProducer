"""Ordered CAM setups, STL topology, linked depths, geometry-driven 2.5D paths."""
import copy

import numpy as np
import pytest

from gcodeproducer.core.cam import (CAMSetup, ToolGroup, Operation, Reference, Depth,
                                     Topology, generate, fingerprint, pick_geometry)
from gcodeproducer.core.geometry import Mesh
from gcodeproducer.core.session import load_mesh, build_job, slice_job, place_mesh
from gcodeproducer.core.profiles import Profile
from gcodeproducer.stages.base import StageContext


@pytest.fixture
def mesh(cube_stl):
    return load_mesh(cube_stl)


def face_ref(mesh, z):
    t = mesh.vertices[mesh.triangles]
    idx = np.flatnonzero(np.all(np.isclose(t[:, :, 2], z), axis=1))[0]
    return Reference("face", [int(idx)])


def job_for(libset, mesh, operations, second=None):
    machine = Profile("machine", "router", workflow="cam", values={"safe_z": 30})
    tools = [libset["tool"].get("6-mm-flat-endmill"), libset["tool"].get("3-mm-flat-endmill")]
    groups = [ToolGroup(tools[0].id, operations)]
    if second is not None:
        groups.append(ToolGroup(tools[1].id, second))
    return build_job("cam", machine, mesh=mesh, tools=tools, cam_setup=CAMSetup(groups))


def test_cam_plate_generates_paths_on_both_models(libset, mesh):
    from gcodeproducer.core.cam.assembly import assembly_fingerprint
    from gcodeproducer.core.fdm.plate_model import PlateModel
    from gcodeproducer.core.jobs.placement import Placement

    first = face_ref(mesh, 20)
    second = Reference('face', [first.indices[0] + len(mesh.triangles)])
    job = job_for(libset, mesh, [Operation(geometry=[ref], end=Depth('top', -1))
                                for ref in (first, second)])
    job.plate_models = [PlateModel('', mesh, Placement(x=x, y=80, z_anchor='top')) for x in (70, 150)]
    job.cam_setup.fingerprint = assembly_fingerprint(job.plate_models)
    assert slice_job(job).program is not None
    assert max(path.points[:, 0].max() for path in job.layers[0].paths) < 100
    assert min(path.points[:, 0].min() for path in job.layers[-1].paths) > 120


def test_topology_omits_triangle_seams(mesh):
    topo = Topology(mesh)
    ref = face_ref(mesh, 20)
    assert len(topo.face(ref.indices[0])) == 2
    assert len(topo.face_edges(ref.indices[0])) == 4
    assert len(topo.feature_chains) == 12
    assert all(len(c) == 2 for c in topo.feature_chains)
    poly, = topo.polylines(ref)
    assert len(poly) == 5 and np.array_equal(poly[0], poly[-1])


def test_refs_and_depth_follow_placement(mesh):
    ref = face_ref(mesh, 20)
    depth = Depth("geometry", -0.5, ref)
    assert depth.resolve(mesh, Topology(mesh)) == 19.5
    moved = Mesh(mesh.vertices + [30, -5, 7], mesh.triangles)
    assert depth.resolve(moved, Topology(moved)) == 26.5
    assert Depth("bottom", -1).resolve(moved, Topology(moved)) == 6
    assert Depth("absolute", 9).resolve(moved, Topology(moved)) == 9


def test_setup_roundtrip(mesh):
    setup = CAMSetup([ToolGroup("tool", [Operation(geometry=[face_ref(mesh, 20)],
                      start=Depth("geometry", 0, face_ref(mesh, 20)))])], fingerprint(mesh))
    assert CAMSetup.from_dict(setup.to_dict()) == setup


def test_face_pick(mesh):
    result = pick_geometry((mesh, "face", np.array([10, 10, 50]), np.array([0, 0, -1]),
                            np.eye(4), (100, 100), (50, 50)))
    assert result["reference"].kind == "face"
    assert result["z_min"] == result["z_max"] == 20


def test_edge_pick_screen_tolerance(mesh):
    mvp = np.eye(4)
    mvp[0, 0] = mvp[1, 1] = 0.05
    # Top-front edge projects from (100,100) to (200,100).
    result = pick_geometry((mesh, "edge", np.array([10, -30, 50]), np.array([0, 0, -1]),
                            mvp, (200, 200), (150, 100)))
    assert result and result["reference"].kind == "edge"


@pytest.mark.parametrize("kind", ["profile", "pocket", "engrave"])
def test_operation_generation(libset, mesh, kind):
    op = Operation(kind=kind, geometry=[face_ref(mesh, 20)], start=Depth("top"),
                   end=Depth("top", -2), stepdown=0.75)
    job = job_for(libset, mesh, [op])
    generate(job, StageContext())
    assert [l.z for l in job.layers] == [19.25, 18.5, 18]
    assert all(l.cam_tool_id == job.tools[0].id for l in job.layers)
    assert all(l.paths for l in job.layers)
    if kind == "pocket":
        for path in job.layers[0].paths:
            assert path.points.min() >= 3 - 1e-6
            assert path.points.max() <= 17 + 1e-6


def test_manual_tool_changes_split_one_self_contained_file_per_tool(libset, mesh, tmp_path):
    from pathlib import Path
    from gcodeproducer.core.gcode.program_parts import part_path
    ref = face_ref(mesh, 20)
    first = Operation(name="first", geometry=[ref], end=Depth("top", -1))
    second = Operation(name="second", kind="engrave", geometry=[ref], end=Depth("top", -0.1))
    job = job_for(libset, mesh, [first], [second])
    job.machine.values.update(auto_tool_change=False, start_gcode="; start T{tool} S{spindle_rpm}\nG90",
                              end_gcode="M5\n; end T{tool}\nM30")
    logs = []
    program = slice_job(job, log=logs.append).program
    assert [label for _, label in program.parts] == [f"T{t.get('tool_number')} {t.name}" for t in job.tools]
    text = program.to_text()
    assert " M6" not in text and "spindle off before tool change" not in text
    assert any("one per tool group" in line for line in logs)
    # Material and checks continue across the split: the second file is still a recut-aware program.
    assert not any("Tool number" in warning for warning in job.warnings)
    files = program.save(str(tmp_path / "part.nc"))
    assert files == [part_path(tmp_path / "part.nc", i, label) for i, (_, label) in enumerate(program.parts, 1)]
    assert [Path(f).name[:10] for f in files] == ["part_01_T1", "part_02_T2"]
    contents = [Path(f).read_text() for f in files]
    assert "".join(contents) == text
    for content, tool in zip(contents, job.tools):
        number = tool.get("tool_number")
        assert content.startswith(";GCodeProducer CAM")
        assert f"; start T{number}" in content and content.rstrip().endswith("M30")
        assert f"; end T{number}" in content
    # The second file re-establishes safe Z before moving, then starts its spindle.
    tail = contents[1].splitlines()
    body = [line for line in tail[tail.index("G90")+1:] if not line.startswith(";")]
    assert body[0].startswith("G0 Z30") and body[1].startswith("M3 S")
    # Each file's last layer marker belongs to that file.
    assert not contents[0].splitlines()[-4].startswith(";LAYER")
    assert ";LAYER:" in tail[tail.index("G90")+1]
    assert "Operation: first" in contents[0] and "Operation: second" in contents[1]
    assert "Operation: second" not in contents[0]


def test_tool_change_order_and_template_values(libset, mesh):
    ref = face_ref(mesh, 20)
    op = Operation(name="first", geometry=[ref], end=Depth("top", -1))
    second = Operation(name="second", kind="engrave", geometry=[ref], end=Depth("top", -0.1))
    job = job_for(libset, mesh, [op], [second])
    job.machine.values["end_gcode"] = "G0 Z{safe_z}\nM5\n; last tool {tool}"
    result = slice_job(job)
    text = result.program.to_text()
    assert text.index("T1 M6") < text.index("Operation: first") < text.index("T2 M6") < text.index("Operation: second")
    assert "G0 Z30\nM5 ;spindle off before tool change\nT2 M6" in text
    assert text.rstrip().endswith("; last tool 2")
    cut_layers = {line.layer for line in result.program.lines if line.feature in ("cut", "slot", "high_engagement", "air")}
    assert cut_layers == set(range(len(job.layers)))


def test_first_template_uses_first_group_not_library_order(libset, mesh):
    op = Operation(geometry=[face_ref(mesh, 20)], end=Depth("top", -1))
    job = job_for(libset, mesh, [op])
    job.cam_setup.groups[0].tool_id = job.tools[1].id
    text = slice_job(job).program.to_text()
    assert "T2 M6" in text and "T1 M6" not in text


@pytest.mark.parametrize("change,match", [
    (lambda op: op.geometry.clear(), "select machining geometry"),
    (lambda op: setattr(op, "end", Depth("top", 1)), "end Z"),
    (lambda op: setattr(op, "stepdown", 0), "stepdown"),
    (lambda op: setattr(op, "kind", "drill"), "circular"),
    (lambda op: setattr(op, "enabled", False), "no enabled operations"),
])
def test_invalid_operations_fail(libset, mesh, change, match):
    op = Operation(geometry=[face_ref(mesh, 20)], end=Depth("top", -1))
    change(op)
    with pytest.raises(ValueError, match=match):
        generate(job_for(libset, mesh, [op]), StageContext())


def test_safe_height_and_missing_tool_fail(libset, mesh):
    op = Operation(geometry=[face_ref(mesh, 20)], end=Depth("top", -1))
    job = job_for(libset, mesh, [op])
    job.machine.values["safe_z"] = 15
    with pytest.raises(ValueError, match="Safe Z"):
        generate(job, StageContext())
    job.cam_setup.groups[0].tool_id = "missing"
    with pytest.raises(ValueError, match="missing"):
        generate(job, StageContext())


def test_drill_circular_rim(libset):
    angle = np.arange(32) * 2 * np.pi / 32
    ring = np.column_stack((10 + 3 * np.cos(angle), 10 + 3 * np.sin(angle), np.zeros(32)))
    vertices = np.vstack(([10, 10, 0], ring))
    triangles = np.array([[0, i + 1, (i + 1) % 32 + 1] for i in range(32)])
    mesh = Mesh(vertices, triangles)
    op = Operation(kind="drill", geometry=[Reference("edge", [1, 2])],
                   start=Depth("absolute", 2), end=Depth("absolute", -2), stepdown=1)
    job = job_for(libset, mesh, [op])
    text = slice_job(job).program.to_text()
    assert "X10 Y10" in text and "G1 Z-2" in text
    assert len(job.layers) == 4
    assert all(l.paths[0].feature == "drill" for l in job.layers)


def test_separate_selected_edges_form_closed_profile(libset, mesh):
    edges = Topology(mesh).face_edges(face_ref(mesh, 20).indices[0])
    op = Operation(geometry=[Reference("edge", list(e)) for e in edges], end=Depth("top", -1))
    job = job_for(libset, mesh, [op])
    generate(job, StageContext())
    assert len(job.layers) == 1 and len(job.layers[0].paths) == 1
    assert job.layers[0].paths[0].closed


def test_changed_mesh_rejected(libset, mesh):
    job = job_for(libset, mesh, [Operation(geometry=[face_ref(mesh, 20)])])
    job.cam_setup.fingerprint = "old-geometry"
    with pytest.raises(ValueError, match="geometry changed"):
        slice_job(job)


def test_vertical_face_rejected(libset, mesh):
    tris = mesh.vertices[mesh.triangles]
    ti = np.flatnonzero(np.ptp(tris[:, :, 2], axis=1) > 1)[0]
    op = Operation(geometry=[Reference("face", [int(ti)])])
    with pytest.raises(ValueError, match="horizontal face"):
        generate(job_for(libset, mesh, [op]), StageContext())
