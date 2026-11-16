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


def test_direction_unlock_is_below_lead_feed_and_preserves_legacy_override(app):
    from gcodeproducer.core.profiles import Profile
    from gcodeproducer.gui.cam_editor import CAMEditor
    editor = CAMEditor()
    editor.set_tools([Profile("tool", "Test cutter")])
    editor.add_tool(); editor.add_operation()
    form = editor.direction.parentWidget().layout()
    assert form.getWidgetPosition(editor.direction)[0] == form.getWidgetPosition(editor.rate_controls["lead_feed"][1])[0] + 1
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
    assert editor.drawing and modes[-1].startswith("draw_")
    editor.cancel()
    assert modes[-1] == "" and not editor.drawing
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
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args: QtWidgets.QMessageBox.StandardButton.No)
    editor.remove()
    assert setup.reference_shapes == [shape]
    def picked_during_confirmation(*args):
        operation.geometry.append(ref)
        return QtWidgets.QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", picked_during_confirmation)
    editor.remove()
    assert setup.reference_shapes == [shape] and "now used" in editor.status.text()
    operation.geometry.clear()
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args: QtWidgets.QMessageBox.StandardButton.Yes)
    editor.remove()
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
        assert editor.stepover.isEnabled() == (kind != "waterfall")
        assert editor.direction_override.isEnabled() == (kind != "contour3d")
        assert not editor.strategy.isEnabled() or kind == "pocket"
        # The 3D kinds always stop at the model; a pocket chooses (and is forced when its rim is sloped).
        assert editor.protect_model.isEnabled() == (kind == "pocket")
        assert editor.protect_model.isChecked() == (kind != "pocket")
        assert not op.protect_model
    editor.protect_model.setChecked(True)
    assert editor.operation().protect_model
    restored = CAMSetup.from_dict(editor.setup.to_dict())
    assert [o.kind for o in restored.groups[0].operations] == ["waterfall", "contour3d", "pocket"]
    assert restored.groups[0].operations[2].protect_model
    editor.close()
