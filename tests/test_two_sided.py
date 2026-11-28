"""Two-sided 3-axis machining: Side A and Side B in one setup, the stock turned over between them."""
import numpy as np
import pytest

from gcodeproducer.core.cam import CAMSetup, Depth, Operation, ToolGroup, generate
from gcodeproducer.core.cam.two_sided import flip_mesh, flip_point, side_label, side_mesh
from gcodeproducer.core.session import place_mesh
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import floor_ref, job_for, stepped_part


@pytest.fixture(scope="module")
def app():
    from PyQt6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


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


def _pin_setup():
    setup = CAMSetup()
    setup.stock.x, setup.stock.y, setup.stock.width, setup.stock.depth, setup.stock.height = 10., 20., 80., 60., 20.
    return setup                                      # stock centre X50 Y50


def test_registration_pins_are_four_circles_on_a_box_about_the_stock_centre_that_coincide_after_the_turn():
    from gcodeproducer.core.cam import registration_pins as pins
    from gcodeproducer.core.geometry import Mesh
    setup = _pin_setup()
    centre = pins.stock_centre(setup)
    assert np.allclose(centre, (50, 50))
    made = pins.make_pins(centre, (80, 35), 3., -2., number=1)
    assert [s.name for s in made] == ["Pin 1.1", "Pin 1.2", "Pin 1.3", "Pin 1.4"] and len({s.group for s in made}) == 1
    at = np.array([s.dimensions()[0] for s in made])
    assert np.allclose(sorted(map(tuple, at)), sorted([(20, 35), (80, 35), (80, 65), (20, 65)]))
    assert all(s.dimensions()[1] == 3. and s.z == -2. for s in made)
    # Turned over about either axis, every hole lands on a hole.
    cloud = Mesh(np.column_stack((at, np.zeros(4))), np.array([[0, 1, 2]]))
    for axis in ("x", "y"):
        turned = np.asarray(flip_mesh(cloud, setup.stock, axis).vertices)[:, :2]
        assert np.allclose(sorted(map(tuple, turned)), sorted(map(tuple, at)))
    setup.reference_shapes.extend(made)
    assert pins.next_number(setup.reference_shapes) == 2
    # One pin edited: the set stays a centred box with one diameter.
    made[2].set_geometry(center=(75., 70.), size=4.)
    pins.sync(setup.reference_shapes, made[2], centre)
    at = np.array([s.dimensions()[0] for s in made])
    assert np.allclose(at, [(25, 30), (75, 30), (75, 70), (25, 70)]) and all(s.dimensions()[1] == 4. for s in made)
    with pytest.raises(ValueError):
        made[0].set_geometry(center=(50., 30.))
        pins.sync(setup.reference_shapes, made[0], centre)
    pins.sync(setup.reference_shapes, made[2], centre)             # (put back)
    # The stock moves: the pins follow its centre, keeping their box.
    setup.stock.x += 7
    assert pins.recentre(setup) and not pins.recentre(setup)
    assert np.allclose([s.dimensions()[0] for s in made], [(32, 30), (82, 30), (82, 70), (32, 70)])
    restored = CAMSetup.from_dict(setup.to_dict())
    assert [s.group for s in restored.reference_shapes] == [s.group for s in made]
    with pytest.raises(ValueError):
        pins.make_pins(centre, (50, 35), 3., 0.)                    # no width


@pytest.mark.parametrize('kind', ['drill', 'pocket'])
def test_manual_side_a_operation_cuts_all_four_references_at_chosen_depth(libset, kind):
    from gcodeproducer.core.cam import Reference, registration_pins as pins
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    setup = job.cam_setup
    setup.set_two_sided(True)
    centre = pins.stock_centre(setup)
    shapes = pins.make_pins(centre, centre + (6., 6.), 2.5, setup.stock.top)
    setup.reference_shapes.extend(shapes)
    op.kind = kind
    op.geometry = [Reference('drawing', [s.id]) for s in shapes]
    op.end = Depth('stock_top', -2.)
    generate(job, StageContext())
    floor = min(layer.z for layer in job.layers)
    assert floor == pytest.approx(setup.stock.top - 2.)
    xy = np.vstack([p.points for layer in job.layers if layer.z == floor for p in layer.paths])[:, :2]
    for shape in shapes:
        assert np.min(np.linalg.norm(xy - shape.first, axis=1)) < 2.5
    assert not setup.other_groups


def test_drawing_registration_pins_previews_the_box_then_the_circles(app):
    from gcodeproducer.gui.editors.editors_constants import REFERENCE_DRAW_MODES
    from gcodeproducer.gui.editors.reference_geometry_editor import ReferenceGeometryEditor
    setup = _pin_setup()
    editor = ReferenceGeometryEditor(setup)
    editor.confirm = lambda *_: True
    seen = []
    editor.previewChanged.connect(lambda edges, text: seen.append((np.asarray(edges, float).reshape(-1, 3), text)))
    editor.method.setCurrentIndex(next(i for i, m in enumerate(REFERENCE_DRAW_MODES) if m[1] == "pins"))
    editor.z.setValue(-1)
    editor.start()
    down = [0, 0, -1]
    editor.hover_ray([80, 35, 10], down)
    edges, text = seen[-1]
    assert len(edges) == 8 and "Width 60.000 \u00d7 Height 30.000" in text and "X50.000 Y50.000" in text   # the box
    editor.accept_ray([80, 35, 10], down)
    assert not setup.reference_shapes
    editor.hover_ray([84, 38, 10], down)                             # 5 mm from the (80, 35) corner
    edges, text = seen[-1]
    assert len(edges) > 8*4 and "4 pins" in text and "Diameter 10.000 mm" in text and "Box 60.000 \u00d7 30.000" in text
    editor.accept_ray([84, 38, 10], down)
    shapes = setup.reference_shapes
    assert len(shapes) == 4 and all(s.kind == "circle" and s.dimensions()[1] == pytest.approx(5.) and s.z == -1 for s in shapes)
    assert editor.items.count() == 1 and editor.items.item(0).text() == 'Pins'
    assert editor.current() is shapes[0]
    assert [editor.fields[k].value() for k in ('x','y')] == [60.,30.]
    # Refining one pin's diameter in the form changes all four; so does moving it.
    editor.fields["a"].setValue(6.)
    assert all(s.dimensions()[1] == pytest.approx(3.) for s in shapes)
    editor.fields["x"].setValue(50.)
    assert np.allclose(sorted(s.dimensions()[0][0] for s in shapes), [25, 25, 75, 75])
    assert editor.fields['y'].value() == 30. and editor.fields['x'].minimum() > 0
    editor.start("resize")
    editor.hover_ray([27, 35, 10], down)
    assert "Diameter 4.000 mm" in seen[-1][1] and len(seen[-1][0]) > 8*4
    editor.cancel()
    editor.remove()                                                   # one pin: the whole set goes
    assert not setup.reference_shapes
    # Without stock there is no centre to build on.
    bare = ReferenceGeometryEditor(CAMSetup())
    bare.method.setCurrentIndex(editor.method.currentIndex()); bare.start()
    bare.accept_ray([80, 35, 10], down)
    assert not bare.setup.reference_shapes and bare.first is None and "allocate" in bare.status.text()
    editor.close(); bare.close()
