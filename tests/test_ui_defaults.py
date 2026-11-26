"""Generated forms and hand-built CAM controls share backend defaults."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_form_none_values_use_declared_defaults(app):
    from gcodeproducer.core.parameters.param import Param
    from gcodeproducer.gui.editors.param_editor import ParamEditor
    params = [Param("amount", "float", .5), Param("enabled", "bool", True),
              Param("side", "choice", "outside", choices=["inside", "outside"])]
    editor = ParamEditor(params, {p.name: None for p in params})
    assert editor.values == {p.name: p.default for p in params}
    assert editor._widgets["amount"].value() == .5
    assert editor._widgets["enabled"].isChecked()
    assert editor.findChild(QtWidgets.QComboBox).currentData() == "outside"
    editor.close()


def test_form_saved_strings_use_same_coercion_as_backend(app):
    from gcodeproducer.core.parameters.param import Param
    from gcodeproducer.core.parameters.resolution import resolve_params
    from gcodeproducer.gui.editors.param_editor import ParamEditor
    params = [Param("amount", "float", .5), Param("enabled", "bool", True),
              Param("side", "choice", "outside", choices=["inside", "outside"])]
    values = {"amount": "0.75", "enabled": "false", "side": "INSIDE"}
    editor = ParamEditor(params, values)
    assert editor.values == resolve_params(params, values)
    assert editor._widgets["amount"].value() == .75
    assert not editor._widgets["enabled"].isChecked()
    assert editor.findChild(QtWidgets.QComboBox).currentData() == "inside"
    editor.close()


def test_form_does_not_display_first_choice_for_invalid_stored_value(app):
    from gcodeproducer.core.parameters.param import Param
    from gcodeproducer.gui.editors.param_editor import ParamEditor
    with pytest.raises(ValueError, match="not in"):
        ParamEditor([Param("side", "choice", "outside", choices=["inside", "outside"])], {"side": "unknown"})


def test_new_cam_operation_uses_shared_preference_and_rate_defaults(app, monkeypatch):
    from gcodeproducer.core.cam.operation import Operation
    from gcodeproducer.core.libraries.profile import Profile
    from gcodeproducer.core.settings.settings_constants import DEFAULTS
    from gcodeproducer.gui.editors.cam_editor import CAMEditor
    editor = CAMEditor()
    for key, (_unlock, value) in editor.rate_controls.items():
        assert value.value() == getattr(Operation(), key)
    monkeypatch.setitem(DEFAULTS, "default_area_order", "depth")
    monkeypatch.setitem(DEFAULTS, "default_material_limit", -.5)
    monkeypatch.setitem(DEFAULTS, "default_overcut", 1.5)
    editor.set_tools([Profile("tool", "Illustrative cutter")])
    editor.add_tool()
    editor.add_operation()
    operation = editor.operation()
    assert operation.area_order == "depth"
    assert operation.material_limit == -.5
    assert operation.overcut == 1.5
    assert operation.auto_stepdown
    editor.close()


@pytest.mark.parametrize("arguments, expected", [([], None), (["example.stl"], "example.stl")])
def test_legacy_gui_module_entry_point_is_preserved(monkeypatch, arguments, expected):
    import runpy
    import sys
    from gcodeproducer.gui.application import app as implementation
    calls = []
    monkeypatch.setattr(implementation, "run_gui", lambda path=None: calls.append(path) or 7)
    monkeypatch.setattr(sys, "argv", ["gcodeproducer.gui.app", *arguments])
    monkeypatch.delitem(sys.modules, "gcodeproducer.gui.app", raising=False)
    with pytest.raises(SystemExit) as result:
        runpy.run_module("gcodeproducer.gui.app", run_name="__main__")
    assert result.value.code == 7
    assert calls == [expected]


def test_pick_purpose_is_per_reference_and_survives_save(app):
    from PyQt6.QtCore import Qt
    from gcodeproducer.core.cam import CAMSetup, Reference
    from gcodeproducer.core.profiles import Profile
    from gcodeproducer.gui.cam_editor import CAMEditor
    editor = CAMEditor()
    editor.set_tools([Profile("tool", "Test cutter")])
    editor.add_tool(); editor.add_operation()
    first, second = Reference("edge", [0, 1]), Reference("stock_edge", [2])
    for ref in (first, second):
        editor.accept_pick({"reference": ref, "z_min": -5, "z_max": 0})
    editor.selections.currentItem().setCheckState(1, Qt.CheckState.Unchecked)
    editor.use_depth("end")
    op = editor.operation()
    assert op.geometry == [first] and op.height_references == [second]
    assert op.end.reference == second
    restored = CAMSetup.from_dict(editor.setup.to_dict()).groups[0].operations[0]
    assert restored.geometry == [first] and restored.height_references == [second]
    assert restored.end.reference == second
    editor.selections.currentItem().setCheckState(1, Qt.CheckState.Checked)
    assert op.geometry == [first, second] and not op.height_references
    assert op.end.reference == second
    editor.close()


def test_legacy_height_reference_appears_as_unchecked_selection(app):
    from PyQt6.QtCore import Qt
    from gcodeproducer.core.cam import CAMSetup, Depth, Reference
    from gcodeproducer.core.profiles import Profile
    from gcodeproducer.gui.cam_editor import CAMEditor
    editor = CAMEditor()
    editor.set_tools([Profile("tool", "Test cutter")])
    editor.add_tool(); editor.add_operation()
    reference = Reference("edge", [2, 3])
    editor.operation().end = Depth("geometry", reference=reference)
    data = editor.setup.to_dict()
    del data["groups"][0]["operations"][0]["height_references"]
    editor.setup = CAMSetup.from_dict(data)
    editor.rebuild((0, 0))
    item = editor.selections.topLevelItem(0)
    assert item.data(0, Qt.ItemDataRole.UserRole) == reference
    assert item.checkState(1) == Qt.CheckState.Unchecked
    editor.close()


def test_direction_unlock_is_below_the_feeds_and_preserves_legacy_override(app):
    from gcodeproducer.core.profiles import Profile
    from gcodeproducer.gui.cam_editor import CAMEditor
    editor = CAMEditor()
    editor.set_tools([Profile("tool", "Test cutter")])
    editor.add_tool(); editor.add_operation()
    form = editor.direction.parentWidget().layout()
    assert form.getWidgetPosition(editor.direction)[0] == form.getWidgetPosition(editor.rate_controls["plunge_feed"][1])[0] + 1
    assert not editor.direction_override.isChecked() and not editor.direction.isEnabled()
    editor.set_calculated({"cut_direction": "meander"})
    assert editor.direction.currentData() == "meander" and editor.operation().cut_direction == "machine"
    editor.direction_override.setChecked(True)
    assert editor.operation().cut_direction == "meander"
    editor.direction.setCurrentIndex(editor.direction.findData("conventional"))
    assert editor.operation().cut_direction == "conventional"
    editor._selected()
    assert editor.direction_override.isChecked() and editor.direction.currentData() == "conventional"
    editor.direction_override.setChecked(False)
    assert editor.operation().cut_direction == "machine" and not editor.direction.isEnabled()
    editor.close()


@pytest.mark.parametrize("method", range(4))
def test_reference_drawing_two_clicks_are_saved_not_machining_picks(app, method):
    from gcodeproducer.core.cam import CAMSetup
    from gcodeproducer.gui.editors.reference_geometry_editor import ReferenceGeometryEditor
    setup = CAMSetup()
    editor = ReferenceGeometryEditor(setup)
    modes = []
    editor.modeRequested.connect(modes.append)
    editor.method.setCurrentIndex(method)
    editor.z.setValue(-3)
    editor.start()
    editor.accept_ray([2,3,10], [0,0,-1])
    assert not setup.reference_shapes and editor.first == (2.,3.)
    editor.accept_ray([6,8,10], [0,0,-1])
    assert len(setup.reference_shapes) == 1 and not setup.groups
    assert setup.reference_shapes[0].z == -3 and editor.first is None
    assert editor.drawing and modes[-1].startswith("sketch_draw_") and editor.draw.isChecked()
    assert editor.current() is setup.reference_shapes[0]              # the new shape is selected
    editor.draw.click()                                                 # the highlighted button toggles off
    assert modes[-1] == "" and not editor.drawing and not editor.draw.isChecked()
    editor.close()


@pytest.mark.parametrize("kind,construction", [("circle", "center"), ("circle", "edge"),
                                               ("rectangle", "center"), ("rectangle", "edge")])
def test_reference_set_geometry_keeps_identity_and_construction(kind, construction):
    import numpy as np
    from gcodeproducer.core.cam.reference_shape import ReferenceShape
    shape = ReferenceShape(kind, construction, (1, 2), (-3, 6), z=-1, name="A")
    ident = shape.id
    size = 2.5 if kind == "circle" else (2.5, 1.5)
    shape.set_geometry((10, 20), size, -4)
    center, got = shape.dimensions()
    assert np.allclose(center, (10, 20)) and np.allclose(got, size) and shape.z == -4
    assert (shape.id, shape.kind, shape.construction, shape.name) == (ident, kind, construction, "A")
    shape.set_geometry(center=(0, 0))
    assert np.allclose(shape.dimensions()[0], (0, 0)) and np.allclose(shape.dimensions()[1], size)
    before = (shape.first, shape.second, shape.z)
    for bad in (0 if kind == "circle" else (0, 1), float("nan") if kind == "circle" else (1, float("inf"))):
        with pytest.raises(ValueError):
            shape.set_geometry(size=bad)
        assert (shape.first, shape.second, shape.z) == before
    with pytest.raises(ValueError):
        shape.set_geometry(z=float("nan"))
    assert (shape.first, shape.second, shape.z) == before


def test_reference_tools_are_exclusive_and_need_a_selection(app):
    from gcodeproducer.core.cam import CAMSetup
    from gcodeproducer.core.cam.reference_shape import ReferenceShape
    from gcodeproducer.gui.editors.reference_geometry_editor import ReferenceGeometryEditor
    from gcodeproducer.gui.editors.section import Section
    setup = CAMSetup()
    editor = ReferenceGeometryEditor(setup)
    assert isinstance(editor, Section) and editor.title() == "Reference geometry"
    assert not editor.buttons["move"].isEnabled() and not editor.editor.isEnabled() and not editor.delete.isEnabled()
    setup.reference_shapes.append(ReferenceShape("circle", "center", (0, 0), (2, 0)))
    editor.refresh(setup.reference_shapes[0].id)
    assert editor.buttons["move"].isEnabled() and editor.size_label.text() == "Diameter"
    assert editor.fields["a"].value() == 4 and editor.fields["b"].isHidden()
    modes = []
    editor.modeRequested.connect(modes.append)
    editor.buttons["move"].click()
    editor.draw.click()
    assert editor.mode == "draw" and modes[-1].startswith("sketch_draw")
    assert [k for k, b in editor.buttons.items() if b.isChecked()] == ["draw"]
    editor.buttons["resize"].click()
    assert editor.mode == "resize" and modes[-1] == "sketch_resize"
    editor.accept_ray([0, 5, 10], [0, 0, -1])
    assert setup.reference_shapes[0].dimensions()[1] == pytest.approx(5)
    editor.end_mode()                                   # Esc path: no signal, buttons released
    assert editor.mode == "" and not any(b.isChecked() for b in editor.buttons.values())
    editor.items.setCurrentRow(-1)
    assert not editor.buttons["resize"].isEnabled()
    editor.close()


def test_reference_drawing_invalid_click_and_cancel_do_not_save_partial_shape(app):
    from gcodeproducer.core.cam import CAMSetup
    from gcodeproducer.gui.editors.reference_geometry_editor import ReferenceGeometryEditor
    setup = CAMSetup()
    editor = ReferenceGeometryEditor(setup)
    editor.start()
    editor.accept_ray([0,0,10], [1,0,0])
    assert editor.first is None and "edge-on" in editor.status.text()
    editor.accept_ray([0,0,10], [0,0,-1])
    editor.accept_ray([0,0,10], [0,0,-1])
    assert not setup.reference_shapes and editor.first is not None
    editor.z.setValue(-2)
    assert editor.first is None and not editor.drawing and not setup.reference_shapes
    assert not editor.draw.isChecked()
    editor.close()


def test_reference_used_in_operations_cannot_be_deleted(app, monkeypatch):
    from gcodeproducer.core.cam import CAMSetup, Operation, Reference, ToolGroup, Depth
    from gcodeproducer.core.cam.reference_shape import ReferenceShape
    from gcodeproducer.gui.editors.reference_geometry_editor import ReferenceGeometryEditor
    shape = ReferenceShape()
    ref = Reference("drawing", [shape.id])
    operation = Operation(end=Depth("geometry", reference=ref))
    setup = CAMSetup(groups=[ToolGroup("tool", [operation])], reference_shapes=[shape])
    editor = ReferenceGeometryEditor(setup)
    editor.items.setCurrentRow(0)
    editor.remove()
    assert setup.reference_shapes == [shape] and "used" in editor.status.text()
    operation.end = Depth("bottom")
    editor.confirm = lambda *args: False
    editor.remove()
    assert setup.reference_shapes == [shape]
    def picked_during_confirmation(*args):
        operation.geometry.append(ref)
        return True
    editor.confirm = picked_during_confirmation
    editor.remove()
    assert setup.reference_shapes == [shape] and "now used" in editor.status.text()
    operation.geometry.clear()
    # The stand-alone default asks with No as the default answer.
    from gcodeproducer.gui.editors.reference_geometry_editor import default_confirm
    editor.confirm = default_confirm
    asked = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        lambda *args: asked.append(args[-1]) or QtWidgets.QMessageBox.StandardButton.Yes)
    editor.remove()
    assert asked == [QtWidgets.QMessageBox.StandardButton.No]
    assert not setup.reference_shapes
    editor.close()


def test_3d_operation_kinds_labels_defaults_and_model_surface_option(app):
    from gcodeproducer.core.cam import CAMSetup
    from gcodeproducer.core.cam.cam_constants import KINDS, KIND_LABELS
    from gcodeproducer.core.profiles import Profile
    from gcodeproducer.gui.cam_editor import CAMEditor
    editor = CAMEditor()
    assert [editor.kind.itemText(i) for i in range(editor.kind.count())] == [KIND_LABELS[k] for k in KINDS]
    editor.set_tools([Profile("tool", "Test cutter")])
    editor.add_tool()
    for kind in ("waterfall", "contour3d", "pocket"):
        editor.kind.setCurrentIndex(editor.kind.findData(kind))
        editor.add_operation()
        op = editor.operation()
        assert op.kind == kind and op.name == KIND_LABELS[kind]
        assert (op.start.source, op.start.extreme, op.end.source, op.end.extreme) == ("selection", "max", "selection", "min")
        assert KIND_LABELS[kind] in editor.tree.currentItem().text(0)
        assert not editor.b_selection_depths.isHidden()
        assert editor.stepover.isEnabled()
        assert editor.direction_override.isEnabled()          # 3D Contour too: Meander is a direction
        assert editor.area_order.isHidden()
        assert editor.strategy.isEnabled()
        assert not hasattr(editor, "protect_model")
        assert not op.protect_model
    restored = CAMSetup.from_dict(editor.setup.to_dict())
    assert [o.kind for o in restored.groups[0].operations] == ["waterfall", "contour3d", "pocket"]
    assert not restored.groups[0].operations[2].protect_model
    editor.close()


def test_section_is_the_shared_collapsible_pane_and_remembers_state(app, monkeypatch):
    from PyQt6.QtCore import QSettings
    from gcodeproducer.gui.editors.section import Section
    monkeypatch.setenv("GCODEPRODUCER_SETTINGS", "pytest_sections")
    QSettings("GCodeProducer", "pytest_sections").clear()
    pane = Section("Feeds & speeds", key="test.pane")
    assert pane.header.objectName() == "sectionHeader" and pane.content.objectName() == "sectionBody"
    assert pane.title() == "Feeds & speeds" and pane.header.text() == "Feeds && speeds"
    assert pane.is_expanded() and pane.body is pane.content.layout()
    pane.set_title("Walls", "2 loops")
    assert pane.header.text() == "Walls   — 2 loops"
    seen = []
    pane.toggled.connect(seen.append)
    pane.header.click()
    assert seen == [False] and not pane.is_expanded() and pane.content.isHidden()
    again = Section("Feeds & speeds", key="test.pane")             # reopened: stays collapsed
    assert not again.is_expanded()
    assert Section("Unkeyed", expanded=False).is_expanded() is False
    assert Section("Unkeyed").is_expanded()
    QSettings("GCodeProducer", "pytest_sections").clear()


def test_every_pane_in_the_window_uses_the_shared_section(app, tmp_path, monkeypatch):
    monkeypatch.setenv("GCODEPRODUCER_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setenv("GCODEPRODUCER_SETTINGS", f"pytest_{tmp_path.name}")
    from gcodeproducer.gui.main_window import MainWindow
    from gcodeproducer.gui.editors.section import Section
    win = MainWindow()
    try:
        assert not win.findChildren(QtWidgets.QGroupBox)
        titles = {s.title() for s in win.findChildren(Section)}
        for title in ("Setup", "Model", "Support", "Material / stock", "Holding tabs", "Reference geometry",
                      "Process", "Show", "Features (click to toggle)", "Camera", "Tool changes & operations",
                      "Operation", "Engagement feeds (% of tool feed)", "Layers", "Walls"):
            assert title in titles, title
        # Support block list actions sit directly under the list, as in the other panes.
        layout = win.blocks_box.layout()
        assert layout.itemAt(0).widget() is win.lst_blocks
        assert any(isinstance(w, QtWidgets.QPushButton) and w.text() == "+ Add"
                   for w in (layout.itemAt(1).layout().itemAt(i).widget() for i in range(layout.itemAt(1).layout().count())))
    finally:
        win.dirty = {k: False for k in win.dirty}
        win.close()
