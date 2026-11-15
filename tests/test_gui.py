"""Headless GUI tests (offscreen Qt platform, no modal dialogs)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv("GCODEPRODUCER_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setenv("GCODEPRODUCER_SETTINGS", f"pytest_{tmp_path.name}")
    from PyQt6.QtCore import QSettings
    QSettings("GCodeProducer", f"pytest_{tmp_path.name}").clear()
    from gcodeproducer.gui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.dirty = {k: False for k in w.dirty}
    w.close()
    QSettings("GCodeProducer", f"pytest_{tmp_path.name}").clear()


def test_sections_and_setup(win):
    titles = [s._title for s in win.process_editor.sections]
    assert titles == ["Layers", "Skirt / brim", "Walls", "Top / bottom shells", "Infill", "Travel & output"]
    rows = {k: win.setup_form.isRowVisible(r) for k, (_l, r, _c) in win.cons_rows.items()}
    assert rows == {"material": True, "nozzle": True, "tool": False}
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    rows = {k: win.setup_form.isRowVisible(r) for k, (_l, r, _c) in win.cons_rows.items()}
    assert rows == {"material": False, "nozzle": False, "tool": True}
    assert [s._title for s in win.process_editor.sections] == ["Profile", "Output"]


def test_edit_save_revert_process(win):
    step = win.pipelines["fdm"].step("fdm_infill")
    step.params["density"] = 55.0
    win.process_editor.changed.emit()
    assert win.dirty["fdm"]
    win.process_revert()
    assert not win.dirty["fdm"]
    assert win.pipelines["fdm"].step("fdm_infill").params.get("density") != 55.0

    win.pipelines["fdm"].step("fdm_infill").params["density"] = 55.0
    win._mark_dirty()
    win.process_save_as(name="Dense")
    assert win.cb_process.currentText() == "Dense" and not win.dirty["fdm"]
    win.select_process("0-20-mm-standard")
    win.select_process("dense")
    assert win.pipelines["fdm"].step("fdm_infill").params["density"] == 55.0
    # persisted to disk
    from gcodeproducer.core.profiles import LibrarySet
    ls = LibrarySet(win.libset.root).load()
    assert ls.processes.get("dense").slice_pipeline().step("fdm_infill").params["density"] == 55.0


def test_section_summary_updates(win):
    from gcodeproducer.gui.process_editor import summary
    step = win.pipelines["fdm"].step("fdm_skirt_brim")
    step.params.update({"type": "brim", "brim_width": 7.0})
    assert summary(step) == "brim 7 mm"
    step.enabled = False
    assert summary(step) == "off"


def test_slice_in_gui(win, app):
    win.open_model(os.path.join(os.path.dirname(__file__), "..", "examples", "cube20.stl"))
    win.run_slice()
    t = time.time()
    while win._worker is not None and time.time() - t < 60:
        app.processEvents()
        time.sleep(0.02)
    assert win.program is not None and win.program.num_layers > 10
    assert win.layer_slider.maximum() == win.program.num_layers - 1
    assert win.feature_list.count() >= 4
    win.step_layer(-5)
    assert win.state.layer_max == win.program.num_layers - 6
