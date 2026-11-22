"""Per-layer work in worker processes gives the same result as on threads."""
from functools import partial

from gcodeproducer.core.fdm import layer_threads


def _square(offset, x):
    return x * x + offset


def test_layer_map_keeps_order_with_processes_and_closures():
    items = list(range(20))
    assert list(layer_threads.layer_map(partial(_square, 1), items)) == [x * x + 1 for x in items]
    scale = 3
    assert list(layer_threads.layer_map(lambda x: x * scale, items)) == [x * 3 for x in items]   # threads


def test_worker_count_follows_environment(monkeypatch):
    monkeypatch.setenv("GCODEPRODUCER_WORKERS", "1")
    assert layer_threads.worker_count() == 1 and layer_threads.process_pool() is None
    monkeypatch.setenv("GCODEPRODUCER_WORKERS", "nonsense")
    assert layer_threads.worker_count() >= 1


def _slice_cube(libset, cube_stl):
    from gcodeproducer.core import workflow as wf
    from gcodeproducer.core.pipeline import SlicePipeline
    from gcodeproducer.core.session import build_job, load_mesh, slice_job
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(cube_stl))
    return slice_job(job, SlicePipeline.default(wf.FDM)).program.to_text()


def test_processes_and_threads_write_the_same_gcode(libset, cube_stl, monkeypatch):
    monkeypatch.setenv("GCODEPRODUCER_WORKERS", "3")
    parallel = _slice_cube(libset, cube_stl)
    monkeypatch.setenv("GCODEPRODUCER_WORKERS", "1")
    threads = _slice_cube(libset, cube_stl)
    assert parallel == threads
