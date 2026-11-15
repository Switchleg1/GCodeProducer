"""Wall-following contours must adapt to mixed walls without cutting islands."""
import numpy as np
import pytest
from shapely.geometry import LineString

from gcodeproducer.core.cam_paths import contour_pocket, pocket_region, direction_for, orient_contour
from gcodeproducer.core.geometry import area
from gcodeproducer.core.profiles import Profile
from gcodeproducer.core.job import Job
from gcodeproducer.core.cam import Operation, CAMSetup, ToolGroup


def circle(radius, n=120):
    angles = np.arange(n)*2*np.pi/n
    return radius*np.column_stack((np.cos(angles), np.sin(angles)))


def line(points):
    return LineString(np.vstack((points,points[0])))


def test_annulus_produces_only_concentric_closed_contours():
    paths = contour_pocket([circle(20),circle(10)], 1.5, 0, 40, "climb")
    assert len(paths) > 4
    for points in paths:
        radii = np.linalg.norm(points,axis=1)
        assert np.ptp(radii) < 0.02
        assert radii.min() >= 11.49 and radii.max() <= 18.51
        assert len(points) > 20
    assert area(paths[0]) > 0 and area(paths[1]) < 0


def test_square_and_circle_fronts_merge_into_mixed_shape_contours():
    square = np.array([[-10,-10],[10,-10],[10,10],[-10,10]])
    loops = [square,circle(3)]
    paths = contour_pocket(loops, 1, 0, 40, "climb")
    centres = pocket_region(loops).buffer(-1)
    assert len(paths) > 10
    # Later fronts split at the wall: curved island arcs join straight wall segments.
    mixed = []
    for p in paths:
        assert centres.buffer(1e-6).covers(line(p))
        delta = np.roll(p,-1,axis=0)-p
        axis_aligned = (np.abs(delta[:,0]) < 1e-7) | (np.abs(delta[:,1]) < 1e-7)
        if axis_aligned.any() and (~axis_aligned).sum() > 8:
            mixed.append(p)
    assert len(mixed) >= 4


def test_direction_and_meander():
    loops = [circle(20),circle(10)]
    climb = contour_pocket(loops,1,0,40,"climb")
    conventional = contour_pocket(loops,1,0,40,"conventional")
    assert len(climb) == len(conventional)
    for a,b in zip(climb,conventional):
        assert area(a)*area(b) < 0
        assert np.allclose(np.sort(a,axis=0),np.sort(b,axis=0))
    meander = contour_pocket([circle(10)],1,0,40,"meander")
    assert [area(p)>0 for p in meander] == [i%2==0 for i in range(len(meander))]
    # Clockwise M3 spindle: climb outside island/profile is CW, pocket wall is CCW.
    assert area(orient_contour(circle(5),"climb",material_inside=True)) < 0
    assert area(orient_contour(circle(5),"climb",material_inside=False)) > 0


def test_machine_default_and_operation_override_persist():
    machine = Profile("machine","router",workflow="cam")
    job = Job("cam",machine)
    op = Operation(kind="pocket")
    assert direction_for(job,op) == "climb"
    machine.values["cut_direction"] = "conventional"
    assert direction_for(job,op) == "conventional"
    op.cut_direction = "meander"
    assert direction_for(job,op) == "meander"
    setup = CAMSetup([ToolGroup("tool",[op])])
    restored = CAMSetup.from_dict(setup.to_dict()).groups[0].operations[0]
    assert restored.cut_direction == "meander" and restored.strategy == "contour"
    assert Profile.from_dict(machine.to_dict()).get("cut_direction") == "conventional"


def test_operation_generator_inherits_machine_and_can_keep_raster(libset):
    from tests.test_pocket_bounds import stepped_part, floor_ref, job_for
    from gcodeproducer.core.cam import generate
    from gcodeproducer.stages.base import StageContext
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    generate(job, StageContext())
    climb = [area(p.points) for p in job.layers[0].paths]
    assert all(p.closed for p in job.layers[0].paths)
    job.machine.values["cut_direction"] = "conventional"
    generate(job, StageContext())
    conventional = [area(p.points) for p in job.layers[0].paths]
    assert all(a*b < 0 for a,b in zip(climb,conventional))
    op.cut_direction = "climb"
    generate(job, StageContext())
    assert np.allclose(climb, [area(p.points) for p in job.layers[0].paths])
    op.strategy = "raster"
    generate(job, StageContext())
    assert any(not p.closed for p in job.layers[0].paths)


def test_large_stepover_is_capped_for_front_coverage():
    messages=[]
    paths=contour_pocket([circle(10)],1,0,100,"climb",messages.append)
    assert paths and any("50%" in m for m in messages)


@pytest.mark.parametrize("loops,match", [
    ([np.array([[0,0],[10,10],[0,10],[10,0]])], "invalid"),
    ([circle(1)],"too small"),
])
def test_invalid_or_unreachable_regions_fail(loops,match):
    with pytest.raises(ValueError,match=match):
        contour_pocket(loops,2,0,40,"climb")
