import numpy as np

from gcodeproducer.core import defaults, geometry
from gcodeproducer.core import workflow as wf
from gcodeproducer.core.process import ProcessLibrary, ProcessPreset
from gcodeproducer.core.profiles import LibrarySet
from gcodeproducer.core.session import build_job, load_mesh, slice_job


def test_region_mask_fills_square():
    poly = np.array([[0, 0], [20, 0], [20, 20], [0, 20]], float)
    rm = geometry.RegionMask([0, 0], [20, 20], res=0.5)
    rm.fill([poly])
    # centre filled, far outside not
    assert rm.blocked(np.array([[10, 10]]))[0]
    assert not rm.blocked(np.array([[-1, -1]]))[0]
    # filled fraction ~ area / grid area
    frac = rm.grid.mean()
    assert 0.3 < frac < 0.9


def test_process_preset_roundtrip(tmp_path):
    lib = ProcessLibrary(tmp_path)
    p = ProcessPreset("0.2 Standard", wf.FDM)
    lib.add(p)
    lib.save_all()
    lib2 = ProcessLibrary(tmp_path)
    lib2.load_dir()
    q = lib2.get("0-2-standard")
    assert q.workflow == wf.FDM
    assert q.pipeline["steps"]


def test_libset_seeds_processes(tmp_path):
    ls = LibrarySet(tmp_path)
    defaults.seed(ls, save=False)
    names = [p.name for p in ls.processes.all(wf.FDM)]
    assert "0.20 mm Standard" in names
    assert ls.processes.all(wf.CAM)


def test_top_bottom_solid_present(libset, cube_stl):
    pre = libset.processes.get("0-20-mm-standard")
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"),
                    material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"),
                    mesh=load_mesh(cube_stl))
    prog = slice_job(job, pre.slice_pipeline()).program
    feats = {}
    for ln in prog.lines:
        feats[ln.feature] = feats.get(ln.feature, 0) + 1
    # bottom(solid_infill) and top(top_infill) both generated, plus sparse infill
    assert feats.get("solid_infill", 0) > 0
    assert feats.get("top_infill", 0) > 0
    assert feats.get("infill", 0) > 0


def test_infill_patterns_all_work(libset, cube_stl):
    from gcodeproducer.core import infill_gen
    machine = libset.machines.get("generic-220-fdm")
    for pattern, _ in infill_gen.PATTERNS:
        job = build_job(wf.FDM, machine, material=libset["material"].get("pla"),
                        nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(cube_stl))
        pipe = __import__("gcodeproducer.core.pipeline", fromlist=["SlicePipeline"]).SlicePipeline.default(wf.FDM)
        for s in pipe.steps:
            if s.stage == "fdm_infill":
                s.params.update({"pattern": pattern, "density": 20})
        prog = slice_job(job, pipe).program
        assert any(ln.feature == "infill" for ln in prog.lines), pattern
