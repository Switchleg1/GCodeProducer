"""Two-sided 3-axis machining: Side A and Side B in one setup, the stock turned over between them."""
import numpy as np
import pytest

from gcodeproducer.core.cam import CAMSetup, Depth, Operation, ToolGroup, generate
from gcodeproducer.core.cam.two_sided import flip_mesh, flip_point, side_label, side_mesh
from gcodeproducer.core.session import place_mesh
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import floor_ref, job_for, stepped_part


def test_turning_the_stock_over_keeps_its_box_and_the_models_place_in_it():
    mesh = stepped_part()
    setup = CAMSetup()
    setup.stock.margin = 3
    setup.stock.auto(mesh)
    lo, hi = setup.stock.bounds
    before = np.asarray(mesh.vertices, float)
    for axis, mirrored in (("x", 1), ("y", 0)):
        turned = flip_mesh(mesh, setup.stock, axis)
        after = np.asarray(turned.vertices, float)
        assert np.array_equal(turned.triangles, mesh.triangles)          # same faces, by index
        assert np.allclose(after[:, 1-mirrored], before[:, 1-mirrored])  # along the axis: unchanged
        assert np.allclose(after[:, mirrored], lo[mirrored]+hi[mirrored]-before[:, mirrored])
        assert np.allclose(after[:, 2], lo[2]+hi[2]-before[:, 2])        # upside down inside the same box
        assert np.all(after >= lo-1e-9) and np.all(after <= hi+1e-9)
        # The model's top was at the stock's top; its underside, 3 mm above the bed, is now 3 mm below the top.
        assert after[:, 2].max() == pytest.approx(hi[2]-3) and after[:, 2].min() == pytest.approx(lo[2])
        normal = lambda m: np.cross(*(np.asarray(m.vertices)[m.triangles[0, 1:]]-np.asarray(m.vertices)[m.triangles[0, 0]]))
        assert np.allclose(normal(turned)[2], -normal(mesh)[2])           # a rotation: what faced up faces down
        assert np.allclose(flip_mesh(turned, setup.stock, axis).vertices, before)       # twice is back
        assert np.allclose(flip_point(flip_point(before[0], mesh, setup.stock, axis), mesh, setup.stock, axis), before[0])
    with pytest.raises(ValueError):
        flip_mesh(mesh, setup.stock, "z")


def test_setup_holds_both_sides_and_switching_swaps_their_operations():
    a, b = Operation(name="top pocket"), Operation(name="underside pocket")
    setup = CAMSetup([ToolGroup("tool", [a])])
    assert side_label(setup) == "" and side_mesh("mesh", setup) == "mesh"
    setup.set_two_sided(True)
    assert side_label(setup) == "Side A"
    setup.switch_side("b")
    assert setup.groups == [] and side_label(setup) == "Side B"
    setup.groups.append(ToolGroup("tool", [b]))
    restored = CAMSetup.from_dict(setup.to_dict())
    assert (restored.two_sided, restored.side, restored.flip_axis) == (True, "b", "x")
    assert restored.groups[0].operations[0].name == "underside pocket"
    assert restored.other_groups[0].operations[0].name == "top pocket"
    restored.switch_side("a")
    assert restored.groups[0].operations[0].name == "top pocket"
    restored.switch_side("b")
    restored.set_two_sided(False)                                        # back to one side: Side A, B kept
    assert restored.side == "a" and restored.groups[0].operations[0].name == "top pocket"
    assert restored.other_groups[0].operations[0].name == "underside pocket"
    assert CAMSetup.from_dict({"groups": []}).two_sided is False          # older saved setups
    with pytest.raises(ValueError):
        setup.switch_side("c")


def test_side_b_is_planned_and_emitted_on_the_turned_model_in_the_same_stock(libset):
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    setup = job.cam_setup
    setup.stock.margin = 3
    setup.stock.auto(mesh)
    lo, hi = setup.stock.bounds
    setup.set_two_sided(True)
    generate(job, StageContext())
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    side_a = job.program.to_text()
    assert "Side A of 2" in side_a
    # Side B: face off the 3 mm left under the part, on the model as it lies turned over.
    setup.switch_side("b")
    setup.groups.append(ToolGroup(job.tools[0].id, [Operation(
        kind="pocket", name="Face underside", geometry=[floor_ref(mesh)],
        start=Depth("stock_top"), end=Depth("absolute", float(hi[2])-3), stepdown=1)]))
    job.mesh = mesh
    job.placement = None
    place_mesh(job)
    turned = np.asarray(job.mesh.vertices, float)
    assert turned[:, 2].max() == pytest.approx(hi[2]-3)                  # the old underside, 3 mm under the top
    job.layers.clear(); job.warnings.clear()
    generate(job, StageContext())
    assert job.layers and min(layer.z for layer in job.layers) == pytest.approx(hi[2]-3)
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    side_b = job.program.to_text()
    assert "Side B of 2: stock turned over about its X axis" in side_b and "Face underside" in side_b
    assert "Face underside" not in side_a
