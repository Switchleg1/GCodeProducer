"""Headless GUI tests (offscreen Qt platform, no modal dialogs)."""
import os
import time

import numpy as np

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
    assert titles == ["Layers", "Skirt / brim", "Support", "Walls", "Top / bottom shells", "Infill",
                      "Travel & output"]
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


def _bracket(tmp_path):
    from conftest import write_boxes
    return write_boxes(tmp_path / "bracket.stl", [(10, 10, 0, 20, 20, 15), (0, 0, 15, 30, 30, 18)])


def _wait(win, app):
    t = time.time()
    while win._worker is not None and time.time() - t < 60:
        app.processEvents()
        time.sleep(0.02)


def test_prepare_preview_modes(win, app, tmp_path):
    assert win.mode == "prepare" and not win.act_preview.isEnabled()
    win.open_model(_bracket(tmp_path))
    assert win.stack.currentIndex() == 0 and win.placed is not None
    win.set_mode("preview")                       # nothing sliced yet -> stays in prepare
    assert win.mode == "prepare"
    win.run_slice()
    _wait(win, app)
    assert win.mode == "preview" and win.stack.currentIndex() == 1 and not win.stale
    win.set_mode("prepare")
    win.set_mode("preview")
    assert win.mode == "preview"
    # editing the placement goes back to prepare and marks the preview stale
    win.sp_x.setValue(win.sp_x.value() + 15)
    assert win.mode == "prepare" and win.stale and "out of date" in win.stale_lbl.text()
    # editing the process marks it stale too (after a fresh slice)
    win.run_slice()
    _wait(win, app)
    win.pipelines["fdm"].step("fdm_infill").params["density"] = 30.0
    win.process_editor.changed.emit()
    assert win.stale


def test_placement_controls(win, tmp_path):
    win.open_model(_bracket(tmp_path))
    assert win.sp_x.value() == 110 and win.sp_y.value() == 110          # bed centre
    win.rotate_model("x", 90)
    assert win.sp_rot["x"].value() == 90
    lo, hi = win.placed.bounds
    assert hi[2] - lo[2] == 30                                         # was 30 deep, now 30 tall
    win.reset_placement()
    assert win.sp_rot["x"].value() == 0
    win.sp_scale.setValue(200)
    lo, hi = win.placed.bounds
    assert hi[2] - lo[2] == 36
    win._on_model_dragged(80.0, 90.0)
    win.model_viewer.moveFinished.emit()                               # end of the drag saves it
    assert (win.sp_x.value(), win.sp_y.value()) == (80, 90)
    # placement is remembered per model
    path = win.model_path
    win.open_model(path)
    assert (win.placement.x, win.placement.scale) == (80, 200)
    win._on_face_clicked(np.array([0.0, 0.0, 1.0]))                  # top face down = upside down
    assert abs(win.placement.rx) == 180 or abs(win.placement.ry) == 180


def test_support_controls_follow_process(win):
    step = win.pipelines["fdm"].step("fdm_support")
    assert win.cb_support.currentData() == "none" and not step.enabled
    win.cb_support.setCurrentIndex(win.cb_support.findData("everywhere"))
    assert step.enabled and step.params["placement"] == "everywhere" and win.dirty["fdm"]
    win.sp_overhang.setValue(40)
    assert step.params["overhang_angle"] == 40
    # and the other way: the process editor's switch drives the combo
    step.enabled = False
    win.process_editor.changed.emit()
    assert win.cb_support.currentData() == "none"
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    assert not win.support_box.isVisibleTo(win) or not win.support_box.isEnabled()


def test_z_position_and_drop(win, tmp_path):
    win.open_model(_bracket(tmp_path))
    win.sp_z.setValue(6.0)
    assert win.placement.z == 6.0 and win.placed.bounds[0][2] == 6.0
    win.drop_model()
    assert win.sp_z.value() == 0 and win.placed.bounds[0][2] == 0


def test_manual_support_blocks(win, app, tmp_path):
    win.open_model(_bracket(tmp_path))
    win.cb_support.setCurrentIndex(win.cb_support.findData("blocks"))
    assert win._support_mode() == "blocks" and win.blocks_box.isVisibleTo(win)
    win.sp_place_size.setValue(6.0)
    win.generate_blocks()
    n = len(win.blocks)
    assert n > 1 and win.lst_blocks.count() == n
    assert all(b.size[0] == pytest.approx(6.0) for b in win.blocks)
    assert win.model_viewer.show_blocks and len(win.model_viewer.blocks) == n
    win.sp_place_size.setValue(12.0)
    win.generate_blocks()
    assert 0 < len(win.blocks) < n
    win.clear_blocks()
    win.sp_place_size.setValue(40.0)                  # one tile covers the whole support area
    win.generate_blocks()
    assert len(win.blocks) == 1
    # add / resize / remove
    win.add_block()
    assert len(win.blocks) == 2 and win.sel_block == 1
    win.sp_block["w"].setValue(4.0)
    assert win.blocks[1].size[0] == pytest.approx(4.0)
    win.remove_block()
    assert len(win.blocks) == 1
    # drag a block in the view
    x0 = win.blocks[0].x0
    win._on_block_pressed(0)
    win._on_block_dragged(0, 5.0, 0.0)
    win._on_block_released(0)
    assert win.blocks[0].x0 == pytest.approx(x0 + 5)
    # blocks follow the model when it moves...
    win.sp_x.setValue(win.sp_x.value() + 10)
    assert win.blocks[0].x0 == pytest.approx(x0 + 15)
    win.sp_z.setValue(3)
    assert win.blocks[0].z0 == pytest.approx(3)
    # ...are remembered with the model...
    path = win.model_path
    win.open_model(path)
    assert len(win.blocks) == 1 and win.blocks[0].x0 == pytest.approx(x0 + 15)
    # ...and are used when slicing
    win.run_slice()
    _wait(win, app)
    assert any(ln.feature == "support" for ln in win.program.lines)
    # rotating the model removes them (they no longer match)
    win.rotate_model("z", 90)
    assert win.blocks == []


def _click_world(win, app, point):
    """Send a real left click to the Prepare view at the pixel showing world ``point``."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    mv = win.model_viewer
    w, h = mv.width(), mv.height()
    m = (mv.camera.proj_matrix(w / h) @ mv.camera.view_matrix()).astype(float)
    c = m @ np.array([*point, 1.0])
    px = (c[0] / c[3] + 1) / 2 * w
    py = (1 - c[1] / c[3]) / 2 * h
    QTest.mouseClick(mv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(round(px)), int(round(py))))
    app.processEvents()


def test_pick_and_place_blocks(win, app, tmp_path):
    win.resize(1400, 900)
    win.show()
    win.open_model(_bracket(tmp_path))                 # T: pillar 105..115, plate 95..125 at Z 15..18
    win.cb_support.setCurrentIndex(win.cb_support.findData("blocks"))
    win.sp_place_size.setValue(4.0)
    win.b_place_block.setChecked(True)
    assert win.model_viewer.place_block
    app.processEvents()
    cam = win.camera
    # from below: click the plate's underside -> block from the bed up to it
    cam.target, cam.distance, cam.yaw, cam.pitch = np.array([110.0, 110.0, 8.0]), 120.0, -60.0, -55.0
    _click_world(win, app, (120.0, 120.0, 15.0))
    assert len(win.blocks) == 1
    b = win.blocks[0]
    assert b.size[0] == pytest.approx(4.0) and b.z0 == pytest.approx(0) and b.z1 == pytest.approx(15, abs=0.01)
    assert b.center == pytest.approx((120, 120), abs=0.3)
    # from above: the top of the plate has nothing above it -> no block
    cam.pitch = 60.0
    _click_world(win, app, (100.0, 120.0, 18.0))
    assert len(win.blocks) == 1 and "no block" in win.statusBar().currentMessage()
    # from the side, just above the bed: click the bed under the plate -> block up to the plate
    cam.target, cam.yaw, cam.pitch = np.array([110.0, 110.0, 2.0]), 0.0, 4.0
    _click_world(win, app, (123.0, 98.0, 0.0))
    assert len(win.blocks) == 2
    b = win.blocks[1]
    assert b.z0 == pytest.approx(0) and b.z1 == pytest.approx(15, abs=0.01)
    # at a 4 degree grazing angle one pixel spans ~0.7 mm of bed along the view direction
    assert b.center == pytest.approx((123, 98), abs=1.5)
    # Esc leaves the mode; leaving manual-blocks mode switches it off too
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    QTest.keyClick(win.model_viewer, Qt.Key.Key_Escape)
    assert not win.b_place_block.isChecked() and not win.model_viewer.place_block
    win.b_place_block.setChecked(True)
    win.cb_support.setCurrentIndex(win.cb_support.findData("buildplate"))
    assert not win.b_place_block.isChecked()
