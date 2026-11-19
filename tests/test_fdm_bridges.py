"""Bridge detection, fill exclusion, and material-controlled output."""
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from gcodeproducer.core.fdm.bridges import bridge_fill, exclude_bridges
from gcodeproducer.core.gcode.builder import extrusion_per_mm
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.core.jobs.layer import Layer
from gcodeproducer.core.jobs.session import build_job, load_mesh
from gcodeproducer.core.libraries.profile import Profile
from gcodeproducer.stages.base.stage_context import StageContext
from gcodeproducer.stages.fdm.fdm_emit import FDMEmit
from gcodeproducer.stages.fdm.fdm_infill import FDMInfill
from gcodeproducer.stages.fdm.fdm_top_bottom import FDMTopBottom


def test_bridge_requires_area_but_not_two_supported_ends():
    fill = box(0, 0, 12, 8)
    shore = box(0, 0, 4, 8)
    backing = unary_union([shore, box(8, 0, 12, 8)])
    assert not bridge_fill(fill, backing, .45, 1., 33.)[0]
    cantilever, _ = bridge_fill(fill, shore, .45, 1., 1.)
    assert cantilever
    assert any(not all(shore.covers(Point(p)) for p in segment) for segment in cantilever)
    assert bridge_fill(fill, box(20, 20, 21, 21), .45, 1., 1.)[0]
    small, _ = bridge_fill(fill, backing, .45, .5, 32.)
    large, coverage = bridge_fill(fill, backing, .45, 1., 32.)
    assert small and large
    for (a, b), (c, d) in zip(small, large, strict=True):
        assert backing.covers(Point(c)) and backing.covers(Point(d))
        assert fill.buffer(1e-8).covers(LineString([c, d]))
        assert np.linalg.norm(d-c) == pytest.approx(np.linalg.norm(b-a)+1.)
    ordinary = np.array([[[0., .225], [12., .225]]])
    remaining = exclude_bridges(ordinary, coverage, .1)
    assert len(remaining) == 2
    assert all(LineString(s).intersection(coverage).length < 1e-8 for s in remaining)


def test_generated_support_excludes_bridge_fill_across_configured_gap(libset, cube_stl):
    from gcodeproducer.core.fdm.bridges import support_footprint
    from gcodeproducer.core.geometry.region_mask import RegionMask

    job = build_job('fdm', libset.machines.get('generic-220-fdm'), mesh=load_mesh(cube_stl),
                    material=Profile('material', 'Gap test', values={'bridge_min_area': 1.}))
    slab = box(0, 0, 12, 8)
    base = RegionMask([0, 0], [12, 8], 1.)
    mask = np.zeros_like(base.grid)
    mask[2:10, 2:8] = True
    footprint = support_footprint(base, mask)
    assert footprint.equals(box(0, 0, 6, 8))
    ring = np.asarray(slab.exterior.coords)[:-1]
    job.settings['bridge_support_gap_layers'] = 1
    job.layers = [Layer(0, .2, .2, support_region=footprint), Layer(1, .4, .2),
                  Layer(2, .6, .2, contours=[ring], outline=[ring])]
    FDMTopBottom().run(job, FDMTopBottom.defaults(), StageContext(None, None))
    paths = [p for p in job.layers[2].paths if p.feature == 'bridge']
    assert paths and all(LineString(p.points).intersection(footprint).length < 1e-8 for p in paths)
    assert any(p.feature == 'top_infill' for p in job.layers[2].paths)


@pytest.mark.parametrize('mode, feed, pwm', [('fixed', 1200, 204), ('modifier', 600, 64)])
def test_bridge_stage_and_emission(libset, cube_stl, mode, feed, pwm):
    machine = libset.machines.get('generic-220-fdm')
    material = Profile('material', 'Bridge test', values={
        'bridge_min_area': 2., 'bridge_growth': 1., 'bridge_flow': 80.,
        'bridge_speed_mode': mode, 'bridge_speed': 20., 'bridge_speed_modifier': 25.,
        'bridge_cooling_mode': mode, 'bridge_cooling': 80., 'bridge_cooling_modifier': 50.,
        'fan_speed': 50., 'fan_first_layers': 1,
    })
    job = build_job('fdm', machine, mesh=load_mesh(cube_stl), material=material)
    piers = [np.asarray(box(a, 0, b, 8).exterior.coords)[:-1] for a, b in ((0, 4), (8, 12))]
    slab = np.asarray(box(0, 0, 12, 8).exterior.coords)[:-1]
    job.layers = [Layer(0, .2, .2, contours=piers, outline=piers),
                  Layer(1, .4, .2, contours=[slab], outline=[slab]),
                  Layer(2, .6, .2, contours=[slab], outline=[slab])]
    ctx = StageContext(None, None)
    FDMTopBottom().run(job, FDMTopBottom.defaults(), ctx)
    FDMInfill().run(job, FDMInfill.defaults(), ctx)
    assert [i for i, l in enumerate(job.layers) if any(p.feature == 'bridge' for p in l.paths)] == [1]
    coverage = job.layers[1].bridge_region
    assert all(LineString(p.points).intersection(coverage).length < 1e-7
               for p in job.layers[1].paths if p.feature in ('infill', 'solid_infill', 'top_infill'))
    FDMEmit().run(job, FDMEmit.resolve({'retraction_mode': 'off', 'coast_length': 1.}), ctx)
    sim = simulate(job.program)
    assert any(ln.cmd == 'M106' and ln.params.get('S') == pwm for ln in job.program.lines)
    fan = [ln.params.get('S') for ln in job.program.lines if ln.layer == 1 and ln.cmd == 'M106']
    assert fan == [128, pwm, 128]
    moves = np.array([ln.feature == 'bridge' and ln.cmd == 'G1' and 'E' in ln.params for ln in job.program.lines])
    assert moves.any() and np.all(sim.feed[moves] == feed)
    expected_epm = extrusion_per_mm(job.line_width, .2, 1.75, .8)
    np.testing.assert_allclose(sim.de[moves], expected_epm * sim.dist[moves], atol=3e-5)
    assert not any(ln.feature == 'bridge' and 'coast' in ln.raw for ln in job.program.lines)
