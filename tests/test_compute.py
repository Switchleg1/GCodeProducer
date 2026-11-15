"""The compute process: slicing etc. outside the GUI process."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt6.QtCore")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def svc(app):
    from gcodeproducer.gui.compute_service import ComputeService
    s = ComputeService()
    s.results = {}
    s.logs = []
    s.done.connect(lambda t, r: s.results.__setitem__(t, ("done", r)))
    s.failed.connect(lambda t, e: s.results.__setitem__(t, ("error", e)))
    s.log.connect(lambda t, m: s.logs.append(m))
    yield s
    s.shutdown()


def _wait(app, svc, tid, limit=60):
    t0 = time.time()
    while tid not in svc.results and time.time() - t0 < limit:
        app.processEvents()
        time.sleep(0.005)
    return svc.results[tid]


def test_runs_in_another_process(app, svc):
    tid = svc.submit("ping", {"x": 1})
    assert _wait(app, svc, tid) == ("done", {"x": 1})
    assert svc._proc.pid != os.getpid() and svc._proc.is_alive()
    assert not svc.busy


def test_slice_result_and_chunked_program(app, svc, libset, cube_stl):
    from gcodeproducer.core import workflow as wf
    from gcodeproducer.core.compute import CHUNK, run_slice
    from gcodeproducer.core.pipeline import SlicePipeline
    from gcodeproducer.core.session import build_job, load_mesh

    def job():
        return build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                         nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(cube_stl))
    tid = svc.submit("slice", (job(), SlicePipeline.default(wf.FDM)))
    kind, r = _wait(app, svc, tid)
    assert kind == "done"
    local = run_slice(job(), SlicePipeline.default(wf.FDM))           # same job in this process
    assert len(local["program"].lines) > CHUNK                        # big enough to be chunked
    assert [ln.text for ln in r["program"].lines] == [ln.text for ln in local["program"].lines]
    assert r["filament_mm"] == pytest.approx(local["filament_mm"])
    assert len(r["toolpath"].p0) == len(local["toolpath"].p0)
    assert any("Layers" in m for m in svc.logs)                        # stage log messages forwarded
    import gc
    assert gc.isenabled()


def test_error_is_reported(app, svc):
    tid = svc.submit("slice", ("not a job", None))
    kind, tb = _wait(app, svc, tid)
    assert kind == "error" and "Traceback" in tb
    tid = svc.submit("ping", 1)                                        # still usable afterwards
    assert _wait(app, svc, tid) == ("done", 1)


def test_cancel_and_restart(app, svc):
    tid = svc.submit("ping", 1)
    _wait(app, svc, tid)
    pid = svc._proc.pid
    svc.submit("ping", 2)
    svc.cancel()
    assert not svc.busy and svc._proc is None
    tid = svc.submit("ping", 3)
    assert _wait(app, svc, tid) == ("done", 3)
    assert svc._proc.pid != pid                                        # a fresh process
