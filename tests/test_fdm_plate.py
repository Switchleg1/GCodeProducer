"""Multiple FDM instances share a layer stack, not a placement or geometry origin."""
import numpy as np

from gcodeproducer.core.fdm.plate_model import PlateModel
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.core.jobs.placement import Placement
from gcodeproducer.core.jobs.session import build_job, load_mesh, slice_job


def test_two_models_print_to_one_program(libset, cube_stl):
    mesh = load_mesh(cube_stl)
    source = mesh.vertices.copy()
    models = [PlateModel(cube_stl, mesh, Placement(x=x, y=70)) for x in (50, 150)]
    job = build_job('fdm', libset.machines.get('generic-220-fdm'),
                    material=libset['material'].get('pla'), nozzle=libset['nozzle'].get('0-4-mm'),
                    plate_models=models)
    program = slice_job(job).program
    sim = simulate(program)
    walls = np.asarray([line.layer == 2 and line.feature == 'outer_perimeter' for line in program.lines])
    xs = sim.x[walls & (sim.de > 0)]
    assert any(xs < 70) and any(xs > 130)
    assert not any((xs > 70) & (xs < 130))
    assert len(job.layers[2].outline) == 2
    np.testing.assert_array_equal(mesh.vertices, source)


def test_plate_support_uses_each_instances_settings(libset, cube_stl):
    from gcodeproducer.core.fdm.model_support import ModelSupport

    mesh = load_mesh(cube_stl)
    models = [PlateModel(cube_stl, mesh, Placement(x=50, y=70, z=3),
                         support=ModelSupport(mode='buildplate')),
              PlateModel(cube_stl, mesh, Placement(x=150, y=70, z=3))]
    job = build_job('fdm', libset.machines.get('generic-220-fdm'),
                    material=libset['material'].get('pla'), nozzle=libset['nozzle'].get('0-4-mm'),
                    plate_models=models)
    slice_job(job)
    paths = [path for layer in job.layers for path in layer.paths if path.feature.startswith('support')]
    assert paths and all(path.points[:, 0].max() < 70 for path in paths)
