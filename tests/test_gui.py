"""Headless GUI tests (offscreen Qt platform, no modal dialogs)."""
import json
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
                      "Speed & travel"]
    rows = {k: win.setup_form.isRowVisible(r) for k, (_l, r, _c) in win.cons_rows.items()}
    assert rows == {"material": True, "nozzle": True, "tool": False}
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    rows = {k: win.setup_form.isRowVisible(r) for k, (_l, r, _c) in win.cons_rows.items()}
    assert rows == {"material": False, "nozzle": False, "tool": False}
    assert win.fdm_process_box.isHidden()
    assert not win.cam_scroll.isHidden()
    assert win.cam_editor.tool_combo.count() > 0
    ei = win.color_combo.findData("engagement")
    assert ei >= 0 and win.color_combo.model().item(ei).isEnabled()
    win.color_combo.setCurrentIndex(ei)
    assert win.state.color_mode == "engagement"
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("fdm"))
    assert not win.color_combo.model().item(ei).isEnabled()
    assert win.state.color_mode == "feature"


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


def test_support_controls_are_model_state(win, tmp_path):
    """Model > Support edits the model's support settings and never the process."""
    win.open_model(_bracket(tmp_path))
    proc_before = json.dumps(win.pipelines["fdm"].to_dict(), sort_keys=True)
    assert win.cb_support.currentData() == "none" and win.model_support.mode == "none"
    win.cb_support.setCurrentIndex(win.cb_support.findData("everywhere"))
    win.sp_overhang.setValue(40)
    win.sp_extend.setValue(2.5)
    win.sp_fill_holes.setValue(150)
    ms = win.model_support
    assert (ms.mode, ms.overhang_angle, ms.extend, ms.fill_holes) == ("everywhere", 40, 2.5, 150)
    assert json.dumps(win.pipelines["fdm"].to_dict(), sort_keys=True) == proc_before
    assert not win.dirty["fdm"]
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
    win.generate_blocks(wait=True)
    n = len(win.blocks)
    assert n > 1 and win.lst_blocks.count() == n
    assert all(b.size[0] == pytest.approx(6.0) for b in win.blocks)
    assert win.model_viewer.show_blocks and len(win.model_viewer.blocks) == n
    win.sp_place_size.setValue(12.0)
    win.generate_blocks(wait=True)
    assert 0 < len(win.blocks) < n
    win.clear_blocks()
    win.sp_place_size.setValue(40.0)                  # one tile covers the whole support area
    win.generate_blocks(wait=True)
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


def test_block_tools_are_exclusive(win, tmp_path):
    win.open_model(_bracket(tmp_path))
    win.cb_support.setCurrentIndex(win.cb_support.findData("blocks"))
    mv = win.model_viewer
    win.b_place_block.setChecked(True)
    assert mv.place_block and not mv.remove_block
    win.b_remove_block.setChecked(True)                 # turns Place off
    assert win.b_remove_block.isChecked() and not win.b_place_block.isChecked()
    assert mv.remove_block and not mv.place_block
    win.b_place_block.setChecked(True)                  # and the other way round
    assert not win.b_remove_block.isChecked() and mv.place_block and not mv.remove_block
    win.b_face.setChecked(True)                         # Place on face ends both
    assert not win.b_place_block.isChecked() and not win.b_remove_block.isChecked()
    win.b_remove_block.setChecked(True)                 # ...and is ended by them
    assert not win.b_face.isChecked() and mv.remove_block


def test_remove_blocks_by_clicking(win, app, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from gcodeproducer.core.support import SupportBlock
    win.resize(1400, 900)
    win.show()
    win.open_model(_bracket(tmp_path))
    win.cb_support.setCurrentIndex(win.cb_support.findData("blocks"))
    win.blocks = [SupportBlock(96, 96, 0, 102, 102, 15), SupportBlock(118, 118, 0, 124, 124, 15)]
    win.sel_block = 0
    win._blocks_changed()
    win.b_remove_block.setChecked(True)
    app.processEvents()
    cam = win.camera
    cam.target, cam.distance, cam.yaw, cam.pitch = np.array([110.0, 110.0, 6.0]), 120.0, -90.0, 10.0
    _click_world(win, app, (110.0, 110.0, 6.0))         # empty space between the blocks: nothing removed
    assert len(win.blocks) == 2
    _click_world(win, app, (121.0, 118.0, 7.0))         # front face of the second block
    assert len(win.blocks) == 1 and win.blocks[0].x0 == 96
    _click_world(win, app, (99.0, 96.0, 7.0))
    assert win.blocks == [] and win.lst_blocks.count() == 0
    QTest.keyClick(win.model_viewer, Qt.Key.Key_Escape)
    assert not win.b_remove_block.isChecked() and not win.model_viewer.remove_block


def test_switching_process_keeps_model_support_and_position(win, tmp_path):
    """Changing process never clears or changes the model (support, blocks, position)."""
    from gcodeproducer.core.support import SupportBlock
    win.open_model(_bracket(tmp_path))
    win.cb_support.setCurrentIndex(win.cb_support.findData("blocks"))
    win.sp_extend.setValue(1.7)
    win.sp_overhang.setValue(55)
    win.sp_x.setValue(80)
    win.sp_z.setValue(3)
    win.blocks = [SupportBlock(90, 90, 0, 100, 100, 10)]
    win._blocks_changed()
    before = (win.model_support.to_dict(), win.placement.to_dict(), [b.to_dict() for b in win.blocks])
    for pid in ("0-30-mm-draft", "0-12-mm-fine", "strong-cubic-40", "0-20-mm-standard"):
        win.select_process(pid)
        after = (win.model_support.to_dict(), win.placement.to_dict(), [b.to_dict() for b in win.blocks])
        assert after == before, pid
        assert win.cb_support.currentData() == "blocks" and win.sp_extend.value() == pytest.approx(1.7)
    win.process_save_as(name="Another")                       # saving a process: same
    assert win.model_support.to_dict() == before[0]
    # and it is used when slicing whatever the process
    assert win.model_support.mode == "blocks"


def test_model_support_saved_per_model(win, tmp_path):
    a = _bracket(tmp_path)
    win.open_model(a)
    win.cb_support.setCurrentIndex(win.cb_support.findData("everywhere"))
    win.sp_extend.setValue(2.0)
    win.open_model(os.path.join(os.path.dirname(__file__), "..", "examples", "cube20.stl"))
    assert win.model_support.mode == "none"                   # a different model has its own settings
    win.open_model(a)
    assert win.model_support.mode == "everywhere" and win.model_support.extend == 2.0



def test_support_section_shows_only_process_settings():
    """Placement, overhang angle, extend and fill holes live in Model > Support, not in the process."""
    from gcodeproducer.gui.widgets import ParamEditor
    from gcodeproducer.stages.fdm_support import FDMSupport
    names = {p.name for p in FDMSupport.parameters()}
    for moved in ("placement", "overhang_angle", "edge_margin", "fill_holes"):
        assert moved not in names
    ed = ParamEditor(FDMSupport.parameters(), FDMSupport.defaults())
    from gcodeproducer.gui.editors.section import Section
    titles = [b.title() for b in ed.findChildren(Section)]
    assert titles and not any("Holes" in t for t in titles) and "Support" not in titles
    assert not FDMSupport.optional                          # no 'Enabled' switch in the process

def test_ampersand_group_titles_render_literally():
    from gcodeproducer.gui.widgets import ParamEditor
    from gcodeproducer.core.params import Param
    ed = ParamEditor([Param("feed","float",800,group="Feeds & speeds")], {})
    from gcodeproducer.gui.editors.section import Section
    section = ed.findChildren(Section)[0]
    assert section.title() == "Feeds & speeds"
    assert section.header.text() == "Feeds && speeds"      # Qt shows '&&' as a literal '&'


def test_slice_button_cancels(win, app):
    win.open_model(os.path.join(os.path.dirname(__file__), "..", "examples", "cube20.stl"))
    win.run_slice()
    assert win._worker is not None and "Cancel" in win.slice_btn.text()
    win.run_slice()                                   # the button now cancels
    assert win._worker is None and "Slice" in win.slice_btn.text() and win.program is None
    win.run_slice()                                   # and slicing again works (fresh process)
    _wait(win, app)
    assert win.program is not None and win._filament_mm > 0


def test_auto_generate_runs_in_background(win, app, tmp_path):
    win.open_model(_bracket(tmp_path))
    win.cb_support.setCurrentIndex(win.cb_support.findData("blocks"))
    win.sp_place_size.setValue(6.0)
    win.generate_blocks()                             # asynchronous
    assert win._blocks_task is not None and not win.b_gen_blocks.isEnabled()
    t = time.time()
    while win._blocks_task is not None and time.time() - t < 60:
        app.processEvents()
        time.sleep(0.01)
    assert win.b_gen_blocks.isEnabled() and len(win.blocks) > 1


def test_preview_uses_machine_plate_and_same_view(win, app):
    """The sliced Preview shows the machine's plate (not a grid around the part), the views have the
    same size, and slicing does not move the shared camera."""
    from gcodeproducer.core.placement import bed_rect
    from gcodeproducer.core.profiles import Profile
    m = Profile("machine", "Wide", workflow="fdm", values={"bed_x": 300, "bed_y": 200, "height": 180})
    win.libset.machines.add(m)
    win._reload_machines(m.id)
    win.resize(1400, 900)
    win.show()
    win.open_model(os.path.join(os.path.dirname(__file__), "..", "examples", "cube20.stl"))
    assert win.viewer.bed_rect == bed_rect(m, "fdm") == win.model_viewer.rect
    cam = (tuple(win.camera.target), win.camera.distance, win.camera.yaw, win.camera.pitch)
    win.run_slice()
    _wait(win, app)
    assert win.mode == "preview"
    assert (tuple(win.camera.target), win.camera.distance, win.camera.yaw, win.camera.pitch) == cam
    app.processEvents()
    preview_size = win.viewer.size()
    assert win.layer_slider.isEnabled()
    win.set_mode("prepare")
    app.processEvents()
    assert win.model_viewer.size() == preview_size        # same area, same framing
    assert not win.layer_slider.isEnabled()


def test_gcode_template_box(app):
    from gcodeproducer.core import gcode_vars as gv
    from gcodeproducer.core.profiles import schema
    from gcodeproducer.gui.gcode_edit import GCodeTemplateEdit
    from gcodeproducer.gui.widgets import ParamEditor
    ed = ParamEditor(schema("machine", "fdm"), {"start_gcode": ""}, context={"workflow": "fdm"})
    box = ed._widgets["start_gcode"]
    assert isinstance(box, GCodeTemplateEdit)
    assert box.text() == gv.DEFAULT_START["fdm"] and box.is_default() and not box.b_reset.isEnabled()
    got = {}
    ed.changed.connect(got.update)
    box.set_text("M109 S{nozzle_temp}\n{if a}")
    assert got["start_gcode"] == "M109 S{nozzle_temp}\n{if a}"
    assert "unknown variable 'a'" in box.problems.text() and "without '{endif}'" in box.problems.text()
    assert box.b_reset.isEnabled()
    box.edit.moveCursor(box.edit.textCursor().MoveOperation.End)
    box.insert_variable("bed_temp")
    assert box.text().endswith("{bed_temp}")
    box.reset()
    assert box.text() == gv.DEFAULT_START["fdm"] and got["start_gcode"] == gv.DEFAULT_START["fdm"]
    assert box.problems.text() == ""
    assert "M109 S210 T0" in box.rendered_example()
    # the CAM editor offers CAM variables and the CAM default
    cam = ParamEditor(schema("machine", "cam"), {}, context={"workflow": "cam"})._widgets["end_gcode"]
    assert cam.text() == gv.DEFAULT_END["cam"]
    menu_text = " ".join(a.text() for m in cam.b_insert.menu().actions() if m.menu() for a in m.menu().actions())
    assert "{spindle_rpm}" in menu_text and "{nozzle_temp}" not in menu_text


def test_draw_reference_geometry_and_pick_it_in_compute_process(win, cube_stl, app):
    from gcodeproducer.core.cam import Reference
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    editor = win.cam_editor
    refs = win.reference_editor
    refs.z.setValue(-3)
    refs.start()
    mode = win.model_viewer.cam_pick_mode
    assert mode == "sketch_draw_circle_center" and refs.draw.isChecked()
    for point in ([150,150,100], [155,150,100]):
        win._cam_pick((mode, point, [0,0,-1], np.eye(4), [200,200], [100,100]))
    assert len(editor.setup.reference_shapes) == 1
    shape = editor.setup.reference_shapes[0]
    editor.add_tool(); editor.add_operation()
    editor.pick_source.setCurrentIndex(editor.pick_source.findData("reference"))
    editor.pick.setCurrentIndex(editor.pick.findData("edge"))
    assert win.model_viewer.cam_pick_mode == "reference_edge" and not refs.draw.isChecked()
    mvp = np.diag([.1,.1,.01,1.]); mvp[0,3] = mvp[1,3] = -15
    win._cam_pick(("reference_edge", [155,150,100], [0,0,-1], mvp, [200,200], [150,100]))
    deadline = time.monotonic()+15
    while win._cam_pick_task is not None and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    assert win._cam_pick_task is None
    assert editor.operation().geometry == [Reference("drawing", [shape.id])]
    win._cam_pick_task = "stale reference pick"
    win.reference_editor.changed.emit()
    assert win._cam_pick_task is None
    editor.use_depth("end")
    saved = editor.setup.to_dict()
    win.open_model(cube_stl)
    assert editor.setup.to_dict() == saved
    assert win.reference_editor.items.count() == 1
    assert win.reference_editor.setup is editor.setup


def test_reference_pane_lives_in_model_dock_and_tools_toggle(win, cube_stl, app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    refs = win.reference_editor
    model_dock = win.dock_prepare.widget().widget()
    assert refs.parentWidget() is model_dock and refs.parentWidget() is not win.cam_editor
    order = [model_dock.layout().itemAt(i).widget() for i in range(model_dock.layout().count())]
    assert order.index(refs) == order.index(win.model_options)+1      # directly under support / material
    assert not refs.isVisibleTo(win)                                  # FDM: CAM construction geometry hidden
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    assert refs.isVisibleTo(win) and refs.isEnabled()
    assert refs.draw.text() == "Draw" and refs.draw.isCheckable()
    assert not [b for b in refs.findChildren(QtWidgets.QPushButton) if "Stop" in b.text()]
    # Buttons sit directly under the list, as in the tabs and support panes.
    body = refs.body
    items = [body.itemAt(i) for i in range(body.count())]
    list_index = next(i for i, it in enumerate(items) if it.widget() is refs.items)
    assert items[list_index+1].layout().indexOf(refs.draw) >= 0
    # Clicking the highlighted Draw button again cancels; Esc in the view cancels too.
    refs.draw.click()
    assert refs.draw.isChecked() and win.model_viewer.cam_pick_mode.startswith("sketch_draw")
    refs.draw.click()
    assert not refs.draw.isChecked() and refs.mode == "" and win.model_viewer.cam_pick_mode == ""
    refs.draw.click()
    win._cam_pick((win.model_viewer.cam_pick_mode, [150,150,100], [0,0,-1], np.eye(4), [200,200], [100,100]))
    assert refs.first is not None
    win.model_viewer.setFocus()
    QTest.keyClick(win.model_viewer, Qt.Key.Key_Escape)
    assert not refs.draw.isChecked() and refs.first is None and win.model_viewer.cam_pick_mode == ""
    assert not win.cam_editor.setup.reference_shapes


def test_reference_move_resize_and_remembered_delete(win, cube_stl, app, monkeypatch):
    from gcodeproducer.core.cam import Depth, Reference
    from gcodeproducer.core.cam.reference_shape import ReferenceShape
    import gcodeproducer.gui.messages.popup as popup
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    refs = win.reference_editor
    setup = win.cam_editor.setup
    setup.reference_shapes.append(ReferenceShape("rectangle", "edge", (140, 140), (150, 146), -2, "Pad"))
    refs.refresh(setup.reference_shapes[0].id)
    shape = setup.reference_shapes[0]
    assert refs.fields["x"].value() == 145 and refs.fields["a"].value() == 10 and refs.fields["b"].value() == 6
    stale = []
    win._set_stale = lambda *a: stale.append(True)
    # Numeric move / resize keep the ID and construction method
    refs.fields["x"].setValue(160)
    refs.fields["b"].setValue(8)
    assert shape.dimensions()[0][0] == 160 and np.allclose(shape.dimensions()[1], (5, 4))
    assert shape.construction == "edge" and stale
    refs.fields["a"].setValue(0.001)           # degenerate width is rejected, nothing changes
    refs.fields["a"].setValue(10)
    assert np.allclose(shape.dimensions()[1], (5, 4))
    # Click tools: Move puts the centre at the click on the shape's Z plane, Resize keeps the centre
    refs.buttons["move"].click()
    assert win.model_viewer.cam_pick_mode == "sketch_move" and refs.buttons["move"].isChecked()
    win._cam_pick(("sketch_move", [150, 150, 50], [0, 0, -1], np.eye(4), [200, 200], [100, 100]))
    assert np.allclose(shape.dimensions()[0], (150, 150)) and shape.z == -2
    refs.buttons["resize"].click()
    assert refs.buttons["resize"].isChecked() and not refs.buttons["move"].isChecked()
    win._cam_pick(("sketch_resize", [153, 157, 50], [0, 0, -1], np.eye(4), [200, 200], [100, 100]))
    assert np.allclose(shape.dimensions()[0], (150, 150)) and np.allclose(shape.dimensions()[1], (3, 7))
    refs.buttons["resize"].click()
    assert refs.mode == ""
    # Deletion asks (default No) and can be remembered in Settings -> Messages
    asked = []

    def answer(parent, prefs, key, level, title, text, question=False, default_no=False):
        asked.append((key, question, default_no))
        prefs.setdefault("messages", {})[key] = False      # "Don't show this again" + Yes
        return True
    monkeypatch.setattr("gcodeproducer.gui.application.main_window.show_message", answer)
    win.cam_editor.add_tool(); win.cam_editor.add_operation()
    win.cam_editor.operation().end = Depth("geometry", reference=Reference("drawing", [shape.id]))
    refs.remove()
    assert setup.reference_shapes == [shape] and not asked          # in use: never asked, never deleted
    win.cam_editor.operation().end = Depth("bottom")
    refs.remove()
    assert asked == [("delete_reference", True, True)] and not setup.reference_shapes
    assert win.preferences["messages"]["delete_reference"] is False
    from gcodeproducer.core.settings.preferences import load
    assert load(win.libset.root)["messages"]["delete_reference"] is False
    setup.reference_shapes.append(ReferenceShape())
    refs.refresh(setup.reference_shapes[0].id)
    refs.remove()                                                     # remembered: no second question
    assert len(asked) == 1 and not setup.reference_shapes


def test_cam_tree_depth_picking_and_persistence(win, cube_stl, app):
    from PyQt6.QtCore import Qt
    from gcodeproducer.core.cam import Reference
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    ed = win.cam_editor
    ed.add_tool()
    ed.add_operation()
    op = ed.operation()
    assert op.kind == "pocket"
    assert ed.feed_controls["standard_engagement_feed"].specialValueText() == "Tool default"
    ed.feed_controls["standard_engagement_feed"].setValue(150)
    assert op.standard_engagement_feed == 150
    ed.pick.setCurrentIndex(ed.pick.findData("face"))
    assert win.model_viewer.cam_pick_mode == "face"
    lo, hi = win.placed.bounds
    xy = (lo[:2] + hi[:2]) / 2
    origin = np.array([*xy, hi[2] + 30])
    win._cam_pick(("face", origin, np.array([0, 0, -1]), np.eye(4), (200, 200), (100, 100)))
    deadline = time.monotonic() + 15
    while win._cam_pick_task is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert win._cam_pick_task is None and len(op.geometry) == 1
    ed.use_depth("start")
    assert op.start.source == "geometry" and op.start.reference == op.geometry[0]
    ed.accept_pick({"reference": Reference("face", [0]), "z_min": 0, "z_max": 0})
    ed.selections.currentItem().setCheckState(1, Qt.CheckState.Unchecked)
    assert len(op.geometry) == 1   # the unchecked reference is excluded from machining
    ed.use_depth("end")
    assert op.end.source == "geometry" and op.end.reference == Reference("face", [0])
    saved = ed.setup.to_dict()
    win.open_model(cube_stl)
    assert ed.setup.to_dict() == saved
    assert ed.feed_controls["standard_engagement_feed"].value() == 150
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("fdm"))
    win.select_process("0-20-mm-standard")
    assert ed.setup.to_dict() == saved
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    ed.rebuild((0, 0))
    ed.kind.setCurrentIndex(ed.kind.findData("profile"))
    ed.add_operation()
    assert [o.kind for o in ed.setup.groups[0].operations] == ["pocket", "profile"]
    ed.move(-1)
    assert [o.kind for o in ed.setup.groups[0].operations] == ["profile", "pocket"]
    ed.delete()
    assert [o.kind for o in ed.setup.groups[0].operations] == ["pocket"]


def test_cam_stock_shared_slot_top_zero_and_workflow_placement(win, cube_stl):
    from gcodeproducer.core.placement import fits, bed_rect
    win.open_model(cube_stl)
    win.sp_z.setValue(7)
    fdm_placement = win.placement.to_dict()
    assert win.model_options.currentWidget() is win.support_box
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    assert win.model_options.currentWidget() is win.stock_editor
    assert win.placed.bounds[1][2] == 0 and win.placed.bounds[0][2] == -20
    assert fits(win.placed, bed_rect(win._machine(), "cam"))
    assert win.sp_z.minimum() < 0 and win.b_drop.text() == "Top to Z0"
    win.stock_editor.fields["margin"].setValue(3)
    win.stock_editor.auto.click()
    stock = win.cam_editor.setup.stock
    assert (stock.width, stock.depth, stock.height, stock.top) == (26, 26, 23, 0)
    win.stock_editor.name.setText("Aluminium")
    win.stock_editor.name.editingFinished.emit()
    assert stock.material == "Aluminium"
    assert win.model_viewer.stock is stock and win.viewer.stock is stock
    win.sp_z.setValue(-2)
    assert win.placed.bounds[1][2] == -2
    win.open_model(cube_stl)
    assert win.cam_editor.setup.stock.to_dict() == stock.to_dict()
    assert win.placement.z == -2
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("fdm"))
    assert win.placement.to_dict() == fdm_placement
    assert win.model_options.currentWidget() is win.support_box
    assert win.model_viewer.stock is None and win.viewer.stock is None
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    assert win.placement.z == -2
    win.drop_model()
    assert win.placed.bounds[1][2] == 0


def test_cam_material_output_and_unlock_controls(win,cube_stl,app,monkeypatch):
    from gcodeproducer.core.cam import Depth,Reference
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox,"warning",lambda *a: QMessageBox.StandardButton.Ok)
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    assert win.show_material_cb.isChecked() and win.state.show_material
    assert win.stock_editor.category.count()==6
    win.stock_editor.category.setCurrentIndex(win.stock_editor.category.findData("hard_plastic"))
    assert win.cam_editor.setup.stock.category=="hard_plastic"
    win._auto_stock()
    ed=win.cam_editor;ed.add_tool();ed.add_operation()
    op=ed.operation()
    assert op.auto_stepdown and not ed.stepdown.isEnabled()
    ed.doc_override.setChecked(True)
    assert not op.auto_stepdown and ed.stepdown.isEnabled()
    unlock,value=ed.rate_controls["feed"]
    unlock.setChecked(True);value.setValue(1200)
    assert op.unlock_feed and op.feed==1200 and value.isEnabled()
    t=win.placed.vertices[win.placed.triangles]
    i=int(np.flatnonzero(np.all(np.isclose(t[:,:,2],0),axis=1))[0])
    op.geometry=[Reference("face",[i])];op.end=Depth("top",-1)
    win.run_slice()
    deadline=time.monotonic()+20
    while win._worker is not None and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert win._worker is None and win.program is not None
    assert win.material_results and win.material_output.isEnabled()
    assert win.material_output.count()==2
    win.material_output.setCurrentIndex(0)
    assert win.state.layer_min>win.state.layer_max>=0  # empty, not GL's -1/unlimited sentinel
    assert win.viewer.cursor==-1 and not win.layer_slider.isEnabled()
    win.material_output.setCurrentIndex(1)
    assert win.layer_slider.isEnabled()
    assert win.viewer.material_positions is win.material_results[1]["positions"]
    win.show_material_cb.setChecked(False)
    assert not win.state.show_material and not win.model_viewer.show_material
    value.setValue(1300)
    assert not win.material_results and not win.material_output.isEnabled()


def test_depth_of_cut_override_is_next_to_feed_and_persists_independently(win):
    from gcodeproducer.core.cam import CAMSetup
    from gcodeproducer.core.cam_cutting import resolve_cutting
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    ed=win.cam_editor;ed.add_tool();ed.add_operation()
    op=ed.operation()
    form=ed.details.layout()
    feed_row,_=form.getWidgetPosition(ed.rate_controls["feed"][0])
    doc_row,_=form.getWidgetPosition(ed.doc_override)
    assert doc_row==feed_row+1
    assert not ed.doc_override.isChecked() and op.auto_stepdown and not ed.stepdown.isEnabled()
    ed.set_calculated({"stepdown":.6})
    ed.doc_override.setChecked(True)
    ed.stepdown.setValue(.4)
    assert not op.auto_stepdown and op.stepdown==.4 and ed.stepdown.isEnabled()
    assert not op.unlock_feed and not op.unlock_rpm and not op.unlock_lead_feed
    ed.set_calculated({"stepdown":.9})
    assert ed.stepdown.value()==.4     # requested override is never replaced by async calculated output
    ed.set_setup(CAMSetup.from_dict(ed.setup.to_dict()))
    assert ed.doc_override.isChecked() and ed.stepdown.value()==.4
    tool=next(t for t in ed.tools if t.id==ed.setup.groups[0].tool_id)
    tool.values["max_doc"]=.3
    assert resolve_cutting(win._machine(),tool,ed.setup.stock,ed.operation()).stepdown==.3
    ed.doc_override.setChecked(False)
    assert ed.operation().auto_stepdown and not ed.stepdown.isEnabled()


def test_new_cam_tool_enables_material_calculation(win,monkeypatch):
    from gcodeproducer.gui.library_dialog import LibraryDialog
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog,"getText",lambda *a,**kw:("Material calculator",True))
    dialog=LibraryDialog(win.libset,win,"tool")
    dialog._new()
    tool=win.libset["tool"].get("material-calculator")
    assert tool.get("auto_cutting_data") is True
    assert tool.get("steel_chip_load")>0 and tool.get("hard_plastic_sfm")>0
    dialog.close()


def test_material_tables_keep_order_mark_active_and_auto_depth_refreshes_after_save(win):
    from gcodeproducer.core.profiles import Profile
    from gcodeproducer.gui.library_dialog import LibraryDialog
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.cam_editor.setup.stock.category="non_iron_metal"
    tool=Profile("tool","Different material depths",values={"diameter":4,"max_doc":2,
                 "soft_wood_pocket_axial":10,"non_iron_metal_pocket_axial":17.5})
    win.libset["tool"].add(tool)
    ed=win.cam_editor;ed.set_tools(win.libset["tool"].all())
    ed.tool_combo.setCurrentIndex(ed.tool_combo.findData(tool.id));ed.add_tool();ed.add_operation()
    assert ed.stepdown.value()==.7
    assert "Non-iron metal" in ed.cutting_summary.text() and "Pocket 17.5% D" in ed.cutting_summary.text()
    dlg=LibraryDialog(win.libset,win,"tool",tool.id)
    editor=dlg.editor_area.widget()
    from gcodeproducer.core.cam_cutting import MATERIALS
    groups=list(dict.fromkeys(p.group for p in editor.params if p.group.startswith("Cut data:")))
    assert [g.split(" — ")[0] for g in groups]==[f"Cut data: {m[1]}" for m in MATERIALS]
    assert "Non-iron metal" in groups[-2] and "active CAM material" in groups[-2]
    assert editor._widgets["soft_wood_pocket_axial"].value()==10  # no copying wood values to metal
    assert "Non-iron metal" in dlg.hint.text()
    editor._widgets["non_iron_metal_pocket_axial"].setValue(12)
    dlg.accept();win.libset.save()
    win._reload_machines(win.cb_machine.currentData())
    assert ed.stepdown.value()==.48
    assert "Pocket 12% D" in ed.cutting_summary.text()
    tool.values["non_iron_metal_profile_axial"]=30
    ed.kind.setCurrentIndex(ed.kind.findData("profile"));ed.add_operation()
    assert ed.stepdown.value()==1.2 and "Profile 30% D" in ed.cutting_summary.text()


def test_tool_pocket_axial_pending_text_saves_before_dialog_closes(win):
    from gcodeproducer.gui.library_dialog import LibraryDialog
    from gcodeproducer.core.profiles import LibrarySet
    tool = win.libset["tool"].all()[0]
    dlg = LibraryDialog(win.libset, win, "tool", tool.id)
    from gcodeproducer.core.cam_cutting import MATERIALS
    expected = {f"{key}_pocket_axial": 37.5+i for i,(key,*_) in enumerate(MATERIALS)}
    for name,value in expected.items():
        spin = dlg.editor_area.widget()._widgets[name]
        spin.lineEdit().setText(str(value))   # keyboard tracking off; no valueChanged/focus-out yet
    dlg.accept()
    win.libset.save()
    loaded = LibrarySet(win.libset.root).load()["tool"].get(tool.id)
    reopened = LibraryDialog(win.libset, win, "tool", tool.id)
    for name,value in expected.items():
        assert loaded.get(name) == value
        assert reopened.editor_area.widget()._widgets[name].value() == value
    reopened.close()


def test_switching_library_profile_or_tab_commits_pending_numeric_text(win):
    from gcodeproducer.gui.library_dialog import LibraryDialog
    from gcodeproducer.core.profiles import KINDS, LibrarySet
    tool = win.libset["tool"].all()[0]
    dlg = LibraryDialog(win.libset, win, "tool", tool.id)
    dlg.editor_area.widget()._widgets["soft_wood_pocket_axial"].lineEdit().setText("42.5")
    row = dlg.lst.currentRow()
    dlg.lst.setCurrentRow((row+1) % dlg.lst.count())
    assert tool.get("soft_wood_pocket_axial") == 42.5
    other = dlg._current()
    dlg.editor_area.widget()._widgets["steel_pocket_axial"].lineEdit().setText("18.5")
    dlg.tabs.setCurrentIndex(KINDS.index("machine"))
    assert other.get("steel_pocket_axial") == 18.5
    dlg.accept();win.libset.save()
    loaded = LibrarySet(win.libset.root).load()
    assert loaded["tool"].get(tool.id).get("soft_wood_pocket_axial") == 42.5
    assert loaded["tool"].get(other.id).get("steel_pocket_axial") == 18.5


def test_settings_dialog_persists_preferences_and_marks_cam_stale(win, monkeypatch, tmp_path):
    from gcodeproducer.core import app_settings
    from gcodeproducer.gui.settings_dialog import SettingsDialog
    assert win.preferences == app_settings.DEFAULTS
    captured = {}

    def fake_exec(self):
        captured["dialog"] = self
        self.editor._set("stock_resolution", 0.1)
        self.editor._set("skip_air_cuts", False)
        return 1
    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.program = object(); win.stale = False
    win.edit_settings()
    assert win.preferences["stock_resolution"] == pytest.approx(0.1)
    assert win.preferences["skip_air_cuts"] is False
    assert app_settings.load(win.libset.root)["stock_resolution"] == pytest.approx(0.1)
    assert win.stale                                   # generated CAM output depends on preferences
    dlg = SettingsDialog(win.preferences, win)
    dlg._defaults()
    assert dlg.result_values() == app_settings.DEFAULTS
    dlg.close()


def test_feature_list_has_hsm_and_conflict_tooltips(win):
    from gcodeproducer.core.features import FEATURE_LABELS, FEATURE_TOOLTIPS
    assert FEATURE_LABELS["hsm"] == "HSM" and "low horizontal" in FEATURE_TOOLTIPS["hsm"]
    assert "conflict" in FEATURE_TOOLTIPS and "collision" in FEATURE_TOOLTIPS
    assert "(low horizontal" not in win.cam_editor.feed_controls["low_engagement_feed"].specialValueText()


def test_messages_dock_records_and_dont_show_again(win, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMessageBox
    from gcodeproducer.core import app_settings
    assert win.dockWidgetArea(win.dock_messages) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert win.dock_messages.toggleViewAction() in win.menuBar().actions()[2].menu().actions()
    shown = []

    def fake_exec(box):
        shown.append(box.text())
        box.checkBox().setChecked(True)            # user ticks "Don't show this again"
        return QMessageBox.StandardButton.Ok
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    win.notify("slice_failed", "error", "Slice failed", "boom")
    assert shown == ["boom"]
    assert win.preferences["messages"]["slice_failed"] is False
    assert app_settings.load(win.libset.root)["messages"]["slice_failed"] is False   # persisted
    win.notify("slice_failed", "error", "Slice failed", "again")
    assert shown == ["boom"]                                     # suppressed pop-up
    assert any("again" in t for t in win.messages.texts())       # still recorded
    assert win.messages.counts["error"] == 2
    win.log("LEAD2 WARNING: something odd")
    assert any("something odd" in t for t in win.messages.texts())


def test_dont_ask_again_never_remembers_no(win, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    def fake_exec(box):
        box.checkBox().setChecked(True)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    assert win.notify("outside_volume", "warning", "Outside", "continue?", question=True) is False
    assert win.preferences["messages"]["outside_volume"] is True


def test_area_order_uses_global_default_and_operation_override(win):
    from gcodeproducer.core.cam import CAMSetup
    from gcodeproducer.gui.settings_dialog import SettingsDialog
    win.preferences["default_area_order"] = "depth"
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    ed = win.cam_editor
    ed.defaults = win.preferences
    ed.add_tool()
    ed.kind.setCurrentIndex(ed.kind.findData("pocket"))
    ed.add_operation()
    assert ed.operation().area_order == "depth"
    assert ed.area_order.currentData() == "depth"
    ed.area_order.setCurrentIndex(ed.area_order.findData("area"))
    saved = CAMSetup.from_dict(ed.setup.to_dict())
    assert saved.groups[0].operations[0].area_order == "area"
    ed.set_setup(saved)
    assert ed.area_order.currentData() == "area"
    dlg = SettingsDialog(win.preferences, win)
    dlg._defaults()
    assert dlg.result_values()["default_area_order"] == "area"
    dlg.close()
    assert ed.operation().area_order == "area"   # global defaults never rewrite saved operations


def test_holding_tabs_click_tools_model_persistence_and_shared_slot(win, cube_stl):
    import json
    import numpy as np
    from gcodeproducer.core.cam_tabs import tab_pick
    from gcodeproducer.core.cam import highlight_geometry
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    win._auto_stock()
    editor = win.stock_editor.tabs
    assert editor.setup is win.cam_editor.setup
    assert win.cam_editor.operation() is None    # tabs do not need an operation selected
    editor.place.click()
    assert win.model_viewer.cam_pick_mode == "tab" and editor.place.isChecked()
    lo, hi = win.placed.bounds
    origin = [hi[0]+10, (lo[1]+hi[1])/2, (lo[2]+hi[2])/2]
    result = tab_pick(win.placed, editor.setup, "tab", origin, [-1,0,0])
    editor.accept_pick(result)
    assert len(editor.setup.tabs) == 1 and editor.list.count() == 1
    saved = json.loads(win.settings.value(win._model_key("cam", cube_stl)))
    assert len(saved["tabs"]) == 1 and saved["groups"] == []
    out = highlight_geometry((win.placed, None, editor.setup.stock, None, editor.setup.tabs))
    assert len(out["tabs"]) == 1    # overlay is available even without any tool groups
    win.open_model(cube_stl)
    assert len(editor.setup.tabs) == 1
    assert editor.setup is win.cam_editor.setup
    editor.list.setCurrentRow(0)
    editor.width.setValue(6)
    assert editor.setup.tabs[0].width == 6
    editor.remove.click()
    assert win.model_viewer.cam_pick_mode == "tab_remove"
    win._cam_selection_exited()
    assert not editor.remove.isChecked() and not win.model_viewer.cam_pick_mode
    editor.delete_selected()
    assert not editor.setup.tabs
    assert json.loads(win.settings.value(win._model_key("cam", cube_stl)))["tabs"] == []


def test_settings_dialog_messages_section(win):
    from gcodeproducer.core import app_settings
    from gcodeproducer.gui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.preferences, win)
    assert set(dlg.message_checks) == set(app_settings.MESSAGES)
    dlg.message_checks["cam_warnings"].setChecked(False)
    assert dlg.result_values()["messages"]["cam_warnings"] is False
    dlg._defaults()
    assert dlg.result_values()["messages"]["cam_warnings"] is True
    dlg.close()
