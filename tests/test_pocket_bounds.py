"""Stepped part: select a floor or upper/lower rims, never pocket through the base."""
import numpy as np
import pytest

from gcodeproducer.core.geometry import Mesh
from gcodeproducer.core.cam import (CAMSetup, ToolGroup, Operation, Depth, Reference,
                                     Topology, generate, highlight_geometry)
from gcodeproducer.core.session import build_job
from gcodeproducer.stages.base import StageContext


def stepped_part(boss=True):
    angle = np.arange(48) * 2*np.pi/48
    # Rings: bore bottom, outer bottom, outer floor, boss/floor joint,
    # boss top, bore top. No boss case is a simple bored plate.
    specs = [(3, -10), (20, -10), (20, -4)]
    specs += [(10, -4), (10, 0), (3, 0)] if boss else [(3, -4)]
    vertices = np.concatenate([np.column_stack((r*np.cos(angle), r*np.sin(angle), np.full(48,z)))
                               for r, z in specs])
    faces = []
    def connect(a, b):
        for i in range(48):
            j = (i+1)%48
            faces.extend(((a*48+i, b*48+i, b*48+j), (a*48+i, b*48+j, a*48+j)))
    for a, b in ((0,1),(1,2),(2,3)):
        connect(a,b)
    if boss:
        for a,b in ((3,4),(4,5),(5,0)):
            connect(a,b)
    else:
        connect(3,0)
    return Mesh(vertices, np.asarray(faces))


def floor_ref(mesh):
    triangles = mesh.vertices[mesh.triangles]
    i = np.flatnonzero(np.all(np.isclose(triangles[:,:,2], -4), axis=1))[0]
    return Reference("face", [int(i)])


def job_for(mesh, refs, libset):
    tool = libset["tool"].get("3-mm-flat-endmill")
    op = Operation(kind="pocket", geometry=refs, start=Depth("stock_top"),
                   end=Depth("selection", extreme="min"), stepdown=1)
    machine = libset.machines.get("generic-300-router")
    job = build_job("cam", machine, tools=[tool], mesh=mesh,
                    cam_setup=CAMSetup([ToolGroup(tool.id,[op])]))
    job.cam_setup.stock.auto(mesh)
    return job, op


@pytest.mark.parametrize("selection", ["floor", "rims"])
def test_annular_pocket_preserves_boss_and_base(selection, libset):
    mesh = stepped_part()
    topo = Topology(mesh)
    refs = [floor_ref(mesh)]
    if selection == "rims":
        # Upper boss rim is Z0, outer flange rim Z-4; part bottom is Z-10.
        refs = [Reference("edge", [2*48,2*48+1]), Reference("edge", [4*48,4*48+1])]
    job, op = job_for(mesh, refs, libset)
    assert op.end.resolve(mesh, topo, refs, job.cam_setup.stock) == -4
    summary = highlight_geometry((mesh, op, job.cam_setup.stock))["depths"]
    assert "start 0.000, end -4.000" in summary
    generate(job, StageContext())
    assert [l.z for l in job.layers] == [-1,-2,-3,-4]
    for path in job.layers[0].paths:
        pts = path.points
        samples = np.vstack((pts, (pts[:-1]+pts[1:])/2))
        assert np.linalg.norm(samples,axis=1).min() >= 11.4  # boss radius + tool radius
        assert np.linalg.norm(samples,axis=1).max() <= 18.6


def test_floor_does_not_leave_stock_columns_over_downward_holes(libset):
    mesh = stepped_part(boss=False)
    topo = Topology(mesh)
    ref = floor_ref(mesh)
    assert len(topo.polylines(ref)) == 2  # face has an outer rim and bore rim
    from gcodeproducer.core.cam import chains
    assert len(chains(topo.pocket_face_edges(ref.indices[0]))) == 1
    job, _ = job_for(mesh, [ref], libset)
    generate(job, StageContext())
    # Clearing above a hole must include its XY position, not preserve a stock island.
    radius = job.tools[0].get("diameter") / 2
    assert any(np.linalg.norm(p.points,axis=1).min() < radius for p in job.layers[0].paths)


def test_selection_depth_follows_placement_and_requires_geometry():
    mesh = stepped_part()
    ref = floor_ref(mesh)
    depth = Depth("selection", 0.2, extreme="min")
    assert depth.resolve(mesh, Topology(mesh), [ref]) == pytest.approx(-3.8)
    moved = Mesh(mesh.vertices+[0,0,-2],mesh.triangles)
    assert depth.resolve(moved, Topology(moved), [ref]) == pytest.approx(-5.8)
    with pytest.raises(ValueError, match="Select pocket bounds"):
        depth.resolve(mesh, Topology(mesh))
