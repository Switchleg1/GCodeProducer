"""Stay-down links must reduce air moves without crossing islands or region gaps."""
import pytest
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


def entries(program):
    """First descending move of each entry: a vertical plunge or the first lead-in ramp segment."""
    out=[];previous=None
    for ln in program.lines:
        if ln.feature in ("plunge","lead_in") and "Z" in ln.params and previous not in ("plunge","lead_in"):
            out.append(ln)
        if ln.cmd in ("G0","G1"):previous=ln.feature
    return out


def test_emitter_uses_one_entry_per_connected_depth_pass(libset):
    mesh = stepped_part()
    job,op = job_for(mesh,[floor_ref(mesh)],libset)
    generate(job,StageContext())
    paths=job.layers[0].paths
    assert len(paths)>2 and all(p.stay_down for p in paths[1:])
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    plunges=entries(job.program)
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
    assert len(entries(job.program))==len(job.layers)*len(paths)


def test_stale_link_endpoint_metadata_forces_retract(libset):
    mesh=stepped_part()
    job,_=job_for(mesh,[floor_ref(mesh)],libset)
    generate(job,StageContext())
    target=job.layers[0].paths[1]
    target.stay_down_from=(999,999)
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    first=[ln for ln in entries(job.program) if ln.layer==0]
    assert len(first)>=2


@pytest.mark.parametrize('short_retracts', [True, False])
def test_unlinked_paths_travel_at_cut_depth_only_if_enabled(libset, short_retracts):
    from gcodeproducer.core.jobs.path import Path
    from gcodeproducer.core.sim import simulate

    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    op.lead_out = True
    generate(job, StageContext())
    job.layers = job.layers[:1]
    layer = job.layers[0]
    # The first path clears a strip twice; the long move to the second start
    # lies inside the cleared strip, but carries no planned cutting-link tag.
    layer.paths = [Path('cut', np.array([[-12., 0.], [12., 0.], [12., .5], [-12., .5], [-10., .25]])),
                   Path('cut', np.array([[10., .25], [10., 1.]]))]
    job.preferences = {'short_retracts': short_retracts}
    job.warnings.clear()
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    sim = simulate(job.program)
    moves = [i for i, ln in enumerate(job.program.lines) if ln.comment and 'stay at depth' in ln.comment]
    if short_retracts:
        i, = moves
        assert job.program.lines[i].cmd == 'G1'
        assert sim.pz[i] == sim.z[i] == pytest.approx(layer.z)
        assert sim.x[i] - sim.px[i] == pytest.approx(20.)
        assert job.program.lines[i-1].feature != 'lead_out'
    else:
        assert not moves
    assert not any('contacts current material' in w.lower() for w in job.warnings)


def test_later_depth_entries_start_just_above_the_previous_floor(libset):
    from gcodeproducer.core.sim import simulate
    mesh=stepped_part()
    job,_=job_for(mesh,[floor_ref(mesh)],libset)
    generate(job,StageContext())
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    safe=float(job.m("safe_z",15)); clearance=1.0            # global "Short retract clearance" default
    sim=simulate(job.program)
    z_of={l.index:l.z for l in job.layers}
    for i,ln in enumerate(job.program.lines):
        if ln.layer<=0 or not sim.motion[i] or ln.feature=="retract":continue   # end-of-program park is expected
        if ln.cmd=="G0":
            assert sim.z[i]<safe-1e-6                       # no return to safe Z between depth passes
        if ln.feature in ("plunge","lead_in") and sim.z[i]<sim.pz[i]:
            # Feed descent never begins far above the floor left by the previous pass.
            assert sim.pz[i]<=z_of[ln.layer-1]+clearance+1e-6
    assert job.warnings==[]                                  # short rapids are clear of current material
    job.preferences={"short_retracts":False}
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    sim=simulate(job.program)
    assert any(ln.cmd=="G0" and ln.layer>0 and ln.feature!="retract" and abs(sim.z[i]-safe)<1e-6
               for i,ln in enumerate(job.program.lines))


def test_next_depth_starts_from_previous_floor_without_going_up(libset):
    from gcodeproducer.core.sim import simulate
    mesh=stepped_part()
    job,op=job_for(mesh,[floor_ref(mesh)],libset)
    op.lead_out_angle=0     # a level lead-out: this checks the links (a climbing exit rises by design)
    generate(job,StageContext())
    CAMEmit().run(job,CAMEmit.resolve({}),StageContext())
    sim=simulate(job.program)
    z_of={l.index:l.z for l in job.layers}
    lines=job.program.lines
    for i,ln in enumerate(lines):
        if ln.layer>0 and sim.motion[i] and ln.feature!="retract":
            assert sim.z[i]<=sim.pz[i]+1e-9          # after the first pass the tool never goes up
    stays=[ln for ln in lines if ln.comment and "stay at depth" in ln.comment]
    assert len(stays)==len(job.layers)-1
    for ln in stays:
        i=lines.index(ln)
        assert ln.cmd=="G1" and sim.z[i]==pytest.approx(z_of[ln.layer-1])     # moved at the previous floor
        nxt=next(l for l in lines[i+1:] if l.cmd=="G1" and "Z" in l.params)
        assert nxt.feature=="lead_in"                                         # then ramps down from there
    assert job.warnings==[]
