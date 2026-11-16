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
