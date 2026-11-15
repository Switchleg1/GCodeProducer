"""Stay-down links must reduce air moves without crossing islands or region gaps."""
import numpy as np
from shapely.geometry import LineString

from gcodeproducer.core.cam_paths import contour_pocket, link_contours, pocket_region
from gcodeproducer.core.cam import generate
from gcodeproducer.core.geometry import area
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_cam_paths import circle
from tests.test_pocket_bounds import stepped_part, floor_ref, job_for


def test_annulus_links_nearby_loops_without_alternating_walls():
    loops = [circle(20), circle(10)]
    contours = contour_pocket(loops, 1.5, 0, 40, "climb")
    linked = link_contours(contours, loops, 1.5, 0, "climb")
    assert not linked[0][1] and all(flag for _, flag in linked[1:])
    distance = [np.linalg.norm(a[0][0]-b[0][0]) for a,b in zip(linked,linked[1:])]
    assert max(distance) < 2.5  # local stepover moves, not full-width outside/inside jumps
    valid = pocket_region(loops).buffer(-1.5).buffer(1e-6)
    for (a,_), (b,flag) in zip(linked,linked[1:]):
        assert flag and valid.covers(LineString((a[0],b[0])))
    # Rephasing does not lose/invert the original closed contours.
    assert sorted(round(area(p),5) for p,_ in linked) == sorted(round(area(p),5) for p in contours)


def test_links_never_cross_a_retained_island():
    outer = np.array([[-10,-10],[10,-10],[10,10],[-10,10]])
    loops = [outer,circle(5)]
    left, right = circle(0.3)+[-7,0], circle(0.3)+[7,0]
    linked = link_contours([left,right],loops,1,0,"climb")
    assert [flag for _,flag in linked] == [False,False]


def test_disconnected_pockets_require_retract():
    a = np.array([[-8,-3],[-2,-3],[-2,3],[-8,3]])
    b = a+[12,0]
    contours = contour_pocket([a,b],1,0,40,"climb")
    linked = link_contours(contours,[a,b],1,0,"climb")
    assert sum(not flag for _,flag in linked) == 2


def test_mixed_shape_links_and_meander_remain_valid():
    square = np.array([[-10,-10],[10,-10],[10,10],[-10,10]])
    loops = [square,circle(3)]
    contours = contour_pocket(loops,1,0,40,"meander")
    linked = link_contours(contours,loops,1,0,"meander")
    valid = pocket_region(loops).buffer(-1).buffer(1e-6)
    for i,(p,flag) in enumerate(linked):
        assert (area(p)>0) == (i%2==0)
        if flag:
            assert valid.covers(LineString((linked[i-1][0][0],p[0])))


def test_emitter_uses_one_entry_per_connected_depth_pass(libset):
    mesh = stepped_part()
    job,op = job_for(mesh,[floor_ref(mesh)],libset)
    generate(job,StageContext())
    paths=job.layers[0].paths
    assert len(paths)>2 and all(p.stay_down for p in paths[1:])
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    plunges=[ln for ln in job.program.lines if ln.feature=="plunge" and "Z" in ln.params]
    links=[ln for ln in job.program.lines if ln.comment=="stay-down link"]
    assert len(plunges)==len(job.layers)
    assert len(links)==(len(paths)-1)*len(job.layers)
    assert all(ln.cmd=="G1" and "F" in ln.params and "Z" not in ln.params for ln in links)
    assert job.warnings == []
    # Every depth begins with an entry: permission cannot leak from a prior layer.
    assert {ln.layer for ln in plunges}==set(range(len(job.layers)))
    op.stay_down=False
    generate(job,StageContext())
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    assert not any(ln.comment=="stay-down link" for ln in job.program.lines)
    assert sum(ln.feature=="plunge" and "Z" in ln.params for ln in job.program.lines)==len(job.layers)*len(paths)


def test_stale_link_endpoint_metadata_forces_retract(libset):
    mesh=stepped_part()
    job,_=job_for(mesh,[floor_ref(mesh)],libset)
    generate(job,StageContext())
    target=job.layers[0].paths[1]
    target.stay_down_from=(999,999)
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    first=[ln for ln in job.program.lines if ln.layer==0 and ln.feature=="plunge" and "Z" in ln.params]
    assert len(first)>=2
