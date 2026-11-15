"""Z placement (models off the bed) and manual support blocks."""
import json

import numpy as np
import pytest

from conftest import model_support, write_boxes
from gcodeproducer.core import workflow as wf
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.placement import Placement, bed_xy, overhang_faces
from gcodeproducer.core.session import build_job, load_mesh, slice_job
from gcodeproducer.core.support import SupportBlock, generate_blocks

T_SHAPE = [(10, 10, 0, 20, 20, 15), (0, 0, 15, 30, 30, 18)]


def _slice(libset, path, mode="buildplate", enabled=True, pl=None, blocks=None):
    pipe = SlicePipeline.default(wf.FDM)
    ms, _ = model_support({"placement": mode}, enabled)
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path), placement=pl,
                    support_blocks=blocks, support=ms)
    res = slice_job(job, pipe)
    sup = [ln for ln in res.program.lines
           if ln.feature.startswith("support") and ln.cmd == "G1" and "E" in ln.params and ln.params["E"] > 0]
    return sup, res


# ------------------------------------------------------------------ Z placement
def test_placement_z_lifts_model(cube_stl):
    m = Placement(z=7.5).apply(load_mesh(cube_stl))
    assert m.bounds[0][2] == pytest.approx(7.5) and m.bounds[1][2] == pytest.approx(27.5)


def test_lifted_underside_is_overhang(cube_stl):
    m = Placement(z=3).apply(load_mesh(cube_stl))
    assert overhang_faces(m.vertices, m.triangles, 50).sum() == 2
    m = Placement(z=0).apply(load_mesh(cube_stl))
    assert overhang_faces(m.vertices, m.triangles, 50).sum() == 0


def test_lifted_model_keeps_empty_layers(libset, cube_stl):
    sup, res = _slice(libset, cube_stl, enabled=False, pl=Placement(z=5))
    z = res.program.layer_z
    assert len(z) == 125 and z[0] == pytest.approx(0.2)          # layers start at the bed
    extr = [ln.layer for ln in res.program.lines
            if ln.feature not in ("skirt",) and ln.cmd == "G1" and ln.params.get("E", 0) > 0]
    assert z[min(extr)] > 5.0                                    # the part itself starts at Z5
    summary = [s.summary for s in res.steps if s.stage == "fdm_slice"][0]
    assert "empty layers below" in summary


def test_lifted_model_supported_from_bed(libset, cube_stl):
    sup, res = _slice(libset, cube_stl, pl=Placement(z=5))
    layers = sorted({ln.layer for ln in sup})
    z = res.program.layer_z
    assert layers[0] == 0 and z[layers[-1]] < 5.0


def test_lifted_model_no_brim(libset, cube_stl):
    pipe = SlicePipeline.default(wf.FDM)
    pipe.step("fdm_skirt_brim").params["type"] = "brim"
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(cube_stl), placement=Placement(z=3))
    res = slice_job(job, pipe)
    assert "no brim" in [s.summary for s in res.steps if s.stage == "fdm_skirt_brim"][0]


# ------------------------------------------------------------------ blocks
def test_block_geometry():
    b = SupportBlock(10, 20, -5, 0, 0, 8)          # unordered / below bed -> normalised
    assert (b.x0, b.y0, b.z0, b.x1, b.y1, b.z1) == (0, 0, 0, 10, 20, 8)
    b.set_geometry(50, 60, 2, 10, 4, 6)
    assert b.center == (50, 60) and b.size == (10, 4, 6) and b.z0 == 2
    b.translate(1, -1, 3)
    assert b.center == (51, 59) and b.z0 == 5
    assert SupportBlock.from_dict(b.to_dict()) == b


def test_generated_blocks_match_auto(libset, tmp_path):
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    machine = libset.machines.get("generic-220-fdm")
    placed = Placement().apply(load_mesh(path), bed_xy(machine, "fdm"))
    blocks = generate_blocks(placed, 0.2)
    assert len(blocks) == 1
    b = blocks[0]
    assert b.x1 - b.x0 == pytest.approx(30, abs=1.5) and b.z0 == 0 and b.z1 >= 15
    auto, _ = _slice(libset, path, "buildplate")
    manual, _ = _slice(libset, path, "blocks", blocks=blocks)
    assert len(manual) == len(auto)
    assert sorted({ln.layer for ln in manual}) == sorted({ln.layer for ln in auto})
    # tiled with a block size: uniform blocks, same support
    for size in (3.0, 5.0, 8.0):
        tiles = generate_blocks(placed, 0.2, block_size=size)
        assert len(tiles) > 1
        assert all(t.size[0] == pytest.approx(size) and t.size[1] == pytest.approx(size) for t in tiles)
        assert len(_slice(libset, path, "blocks", blocks=tiles)[0]) == len(auto)
    assert len(generate_blocks(placed, 0.2, block_size=3.0)) > len(generate_blocks(placed, 0.2, block_size=8.0))


def test_blocks_limit_where_support_goes(libset, tmp_path):
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)        # placed centred on 110,110: plate 95..125
    full, _ = _slice(libset, path, "blocks", blocks=[SupportBlock(95, 95, 0, 125, 125, 15)])
    half, _ = _slice(libset, path, "blocks", blocks=[SupportBlock(95, 95, 0, 110, 125, 15)])
    low, res = _slice(libset, path, "blocks", blocks=[SupportBlock(95, 95, 0, 125, 125, 5)])
    assert 0 < len(half) < len(full)
    assert max(res.program.layer_z[ln.layer] for ln in low) <= 5.2        # only up to the block top
    none, res = _slice(libset, path, "blocks", blocks=[SupportBlock(0, 0, 0, 20, 20, 10)])
    assert not none and "not under the model" in [s.summary for s in res.steps if s.stage == "fdm_support"][0]
    none, res = _slice(libset, path, "blocks", blocks=[])
    assert not none and "no support blocks" in [s.summary for s in res.steps if s.stage == "fdm_support"][0]


def test_block_support_respects_z_gap(libset, tmp_path):
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    sup, res = _slice(libset, path, "blocks", blocks=[SupportBlock(95, 95, 0, 125, 125, 30)])
    top = max(ln.layer for ln in sup)
    assert res.program.layer_z[top] == pytest.approx(14.8)      # plate starts at 15.0: one empty layer


def test_cli_z_and_blocks(tmp_path, monkeypatch):
    from gcodeproducer.cli import main
    monkeypatch.setenv("GCODEPRODUCER_LIBRARY", str(tmp_path / "lib"))
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps([SupportBlock(95, 95, 0, 110, 125, 20).to_dict()]))
    out = tmp_path / "t.gcode"
    assert main(["slice", path, "-o", str(out), "-q", "--z", "3", "--support-blocks", str(blocks),
                 "--support", "blocks"]) == 0
    text = out.read_text()
    assert ";TYPE:support" in text


def test_block_at(tmp_path):
    from gcodeproducer.core.geometry import load_stl
    from gcodeproducer.core.support import block_at
    t = load_stl(write_boxes(tmp_path / "t.stl", T_SHAPE))
    shelf = load_stl(write_boxes(tmp_path / "s.stl", [(0, 0, 0, 30, 30, 4), (0, 0, 4, 10, 10, 20),
                                                      (0, 0, 20, 30, 30, 22)]))
    box = lambda b: (b.x0, b.y0, b.z0, b.x1, b.y1, b.z1)
    assert box(block_at(t, 25, 25, 0.0, 4)) == pytest.approx((23, 23, 0, 27, 27, 15))     # bed -> plate
    assert block_at(t, 50, 50, 0.0, 4) is None                                           # nothing above
    assert block_at(t, 25, 25, 18.0, 4) is None                                          # top of the part
    assert box(block_at(t, 25, 25, 15.0, 4, facing_down=True)) == pytest.approx((23, 23, 0, 27, 27, 15))
    assert box(block_at(shelf, 20, 20, 4.0, 5)) == pytest.approx((17.5, 17.5, 4, 22.5, 22.5, 20))
    assert box(block_at(shelf, 20, 20, 20.0, 5, facing_down=True)) == pytest.approx((17.5, 17.5, 4, 22.5, 22.5, 20))
