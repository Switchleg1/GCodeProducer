"""Preview playback (shared by FDM and CAM) and compact layout details."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def program(layers=4, moves=5):
    """A small G-code program: per layer a comment, then moves; plus start/end lines."""
    from gcodeproducer.core.gcode.program import GCodeProgram
    from gcodeproducer.core.gcode.toolpath import build_toolpath
    text = ["G21", "G90"]
    for layer in range(layers):
        text.append(f";LAYER:{layer}")
        text.append(f"G0 Z{layer*.2+.2:.1f}")
        text += [f"G1 X{i} Y{layer} F1200" for i in range(moves)]
    text += ["M84"]
    prog = GCodeProgram.from_text(chr(10).join(text))
    layer = 0
    for ln in prog.lines:                      # the slicer's builder tags layers; do it here
        if ln.raw.startswith(";LAYER:"):
            layer = int(ln.raw.split(":")[1])
        ln.layer = layer
    prog.layer_z = [i*.2+.2 for i in range(layers)]
    return prog, build_toolpath(prog)


def fresh_window(tmp_path, monkeypatch):
    """A window with empty, private Qt settings (tmp names repeat between sessions)."""
    from PyQt6.QtCore import QSettings
    name = f"pytest_playback_{tmp_path.name}"
    monkeypatch.setenv("GCODEPRODUCER_SETTINGS", name)
    QSettings("GCodeProducer", name).clear()
    from gcodeproducer.gui.main_window import MainWindow
    return MainWindow()


@pytest.fixture
def bar(app):
    from gcodeproducer.gui.inspection.playback_bar import PlaybackBar
    widget = PlaybackBar()
    yield widget
    widget.stop_play()
    widget.close()


def test_new_program_shows_everything_with_the_cursor_at_the_end(bar):
    prog, tp = program()
    cursors, layers = [], []
    bar.cursorChanged.connect(cursors.append)
    bar.layersChanged.connect(lambda lo, hi: layers.append((lo, hi)))
    bar.set_program(prog, tp)
    n = len(prog.lines)
    assert bar.cursor == n-1 and cursors[-1] == n-1
    assert layers[-1] == (0, prog.num_layers-1)
    assert bar.line_slider.maximum() == n-1 and bar.line_spin.value() == n
    assert bar.layer_max_spin.value() == prog.num_layers


def test_transport_buttons_and_line_steps_skip_non_moves(bar):
    prog, tp = program()
    bar.set_program(prog, tp)
    bar.buttons["start"].click()
    assert bar.cursor == 0
    bar.buttons["next_line"].click()
    assert prog.lines[bar.cursor].cmd is not None and bar.cursor == 1
    # stepping across a layer comment lands on the next real command
    comment = next(i for i, ln in enumerate(prog.lines) if ln.cmd is None and i > 2)
    bar.set_cursor(comment-1)
    bar.step_line(1)
    assert bar.cursor == comment+1
    bar.step_line(-1)
    assert bar.cursor == comment-1
    bar.buttons["end"].click()
    assert bar.cursor == len(prog.lines)-1 and bar.layer_max == prog.num_layers-1


def test_layer_steps_follow_and_single_layer(bar):
    prog, tp = program()
    bar.set_program(prog, tp)
    layers = []
    bar.layersChanged.connect(lambda lo, hi: layers.append((lo, hi)))
    bar.buttons["prev_layer"].click()
    top = prog.num_layers-2
    assert bar.layer_max == top and layers[-1] == (0, top)
    lo, hi = tp.layer_line_range(top)
    assert bar.cursor == hi                                  # cursor at the end of that layer
    assert bar.layer_line_slider.minimum() == lo and bar.layer_line_slider.maximum() == hi
    bar.single_layer.setChecked(True)
    assert layers[-1] == (top, top)
    bar.single_layer.setChecked(False)
    # Follow: moving the cursor into a lower layer moves the top layer with it
    bar.set_cursor(tp.layer_line_range(1)[0]+1)
    assert bar.layer_max == 1
    bar.follow_layer.setChecked(False)
    bar.set_cursor(len(prog.lines)-2)
    assert bar.layer_max == 1
    # the lowest visible layer can be raised; it lifts the top when needed
    bar.layer_min_spin.setValue(3)
    assert bar.layer_min == 2 and bar.layer_max == 2


def test_playback_advances_at_the_chosen_speed_and_stops_at_the_end(bar):
    prog, tp = program(layers=6, moves=20)
    bar.set_program(prog, tp)
    bar.speed_slider.setValue(0)
    assert bar.play_speed == pytest.approx(1) and bar.speed_lbl.text() == "1 lines/s"
    bar.speed_slider.setValue(1000)
    assert bar.play_speed == pytest.approx(10**4.7)
    bar.speed_slider.setValue(500)
    speed = bar.play_speed
    bar.toggle_play()                     # at the end: replay from the start
    assert bar.is_playing() and bar.cursor == 0 and bar.b_play.text() == "\u23f8"
    bar.stop_play()
    bar._play_acc = 0
    assert bar.advance(10/speed) and bar.cursor == 10
    assert bar.layer_max == int(tp.line_layer[10])           # Follow keeps the top layer with the cursor
    assert not bar.advance(1e6) and bar.cursor == len(prog.lines)-1
    bar.toggle_play()
    bar.toggle_play()
    assert not bar.is_playing() and bar.b_play.text() == "\u25b6"


def test_clear_stops_and_empties(bar):
    prog, tp = program()
    bar.set_program(prog, tp)
    bar.toggle_play()
    bar.clear()
    assert not bar.is_playing() and bar.program is None
    bar.step_line(1); bar.step_layer(1); bar.show_all(); bar.toggle_play()     # harmless without a program
    assert not bar.is_playing()


def test_preview_uses_the_shared_playback_in_both_workflows(app, tmp_path, monkeypatch):
    import time
    monkeypatch.setenv("GCODEPRODUCER_LIBRARY", str(tmp_path / "lib"))
    win = fresh_window(tmp_path, monkeypatch)
    try:
        win.open_model(os.path.join(os.path.dirname(__file__), "..", "examples", "cube20.stl"))
        win.run_slice()
        deadline = time.time()+60
        while win._worker is not None and time.time() < deadline:
            app.processEvents(); time.sleep(.02)
        assert win.program is not None, win.log_view.toPlainText()[-3000:]
        assert win.playback.program is win.program
        pb = win.playback
        win.step_layer(-3)                               # PgDown
        assert win.layer_slider.value() == pb.layer_max == win.state.layer_max == win.program.num_layers-4
        win.layer_slider.setValue(2)
        assert pb.layer_max == 2 and win.viewer.cursor == pb.cursor
        pb.step_line(-1)
        assert win.viewer.cursor == pb.cursor and str(pb.cursor+1) in win.status_line.text()
        pb.toggle_play()
        win.set_mode("prepare")                          # leaving Preview stops playback
        assert not pb.is_playing() and not pb.isEnabled()
        line = len(win.program.lines)//2
        win._on_text_activate(line)
        assert pb.cursor == line and pb.layer_max == int(win.tp.line_layer[line])
        win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
        assert win.playback.program is None or win.playback.program is win.program
    finally:
        win.dirty = {k: False for k in win.dirty}
        win.close()
        from PyQt6.QtCore import QSettings
        QSettings("GCodeProducer", f"pytest_playback_{tmp_path.name}").clear()


def test_action_buttons_share_height_and_split_70_30(app, tmp_path, monkeypatch):
    monkeypatch.setenv("GCODEPRODUCER_LIBRARY", str(tmp_path / "lib"))
    win = fresh_window(tmp_path, monkeypatch)
    try:
        win.resize(1600, 950); win.show(); app.processEvents()
        assert win.slice_btn.height() == win.save_btn.height()
        total = win.slice_btn.width()+win.save_btn.width()
        assert win.slice_btn.width()/total == pytest.approx(.7, abs=.03)
        # Status, progress and Clear share the existing bottom status row.
        from PyQt6.QtCore import QPoint
        panel = win.messages
        assert panel.layout().indexOf(panel.tree) == 0
        panel.progress.show()
        app.processEvents()
        assert panel.layout().indexOf(panel.actions) == -1
        assert panel.clear_button.parentWidget() is win.statusBar()
        assert panel.progress.parentWidget() is win.statusBar()
        assert panel.progress.geometry().right() < panel.clear_button.geometry().left()
        centers = [widget.mapTo(win, QPoint(0, 0)).y()+widget.height()/2
                   for widget in (win.status_line, panel.progress, panel.clear_button)]
        assert max(centers)-min(centers) <= 2
        assert win.progress is panel.progress
        win.statusBar().showMessage("Generating paths")
        assert panel.clear_button.isVisible() and panel.progress.isVisible()
        win.statusBar().clearMessage()
        win.status_line.setText('A long G-code status message ' * 100)
        app.processEvents()
        assert panel.clear_button.geometry().right() <= win.statusBar().width()
        assert panel.progress.geometry().right() < panel.clear_button.geometry().left()
        panel.add("warning", "Something to check")
        assert win.dock_messages.windowTitle() == "Messages \u2014 0 errors, 1 warnings"
        panel.clear()
        assert win.dock_messages.windowTitle() == "Messages"
    finally:
        win.dirty = {k: False for k in win.dirty}
        win.close()
        from PyQt6.QtCore import QSettings
        QSettings("GCodeProducer", f"pytest_playback_{tmp_path.name}").clear()


def test_operation_reference_list_is_full_width_with_actions_under_it(app):
    from PyQt6.QtCore import Qt
    from gcodeproducer.core.cam import Depth, Reference
    from gcodeproducer.core.profiles import Profile
    from gcodeproducer.gui.cam_editor import CAMEditor
    editor = CAMEditor()
    editor.set_tools([Profile("tool", "Test cutter")])
    editor.add_tool(); editor.add_operation()
    form = editor.details.layout()
    row, role = form.getWidgetPosition(editor.selections)
    assert role == QtWidgets.QFormLayout.ItemRole.SpanningRole          # no "Pick purpose" label
    actions = form.itemAt(row+1, QtWidgets.QFormLayout.ItemRole.SpanningRole).layout()
    assert [actions.itemAt(i).widget() for i in range(actions.count())][:2] == [editor.pick, editor.b_remove_ref]
    assert not any(isinstance(w, QtWidgets.QLabel) and "Pick purpose" in w.text()
                   for w in editor.findChildren(QtWidgets.QLabel))
    op = editor.operation()
    a, b, c = Reference("edge", [1, 2]), Reference("edge", [3, 4]), Reference("stock_edge", [5])
    for ref in (a, b, c):
        editor.accept_pick({"reference": ref, "z_min": 0, "z_max": 0})
    editor.selections.currentItem().setCheckState(1, Qt.CheckState.Unchecked)     # c: height only
    assert not editor.b_remove_ref.isEnabled() or editor.selections.currentItem() is not None
    editor.selections.setCurrentItem(editor.selections.topLevelItem(0))
    assert editor.b_remove_ref.isEnabled()
    editor.b_remove_ref.click()
    assert op.geometry == [b] and op.height_references == [c]
    # a reference that defines a depth is kept until the depth is unlinked
    op.end = Depth("geometry", reference=c)
    editor._refresh_selections(c)
    editor.b_remove_ref.click()
    assert op.height_references == [c] and "End" in editor.pick_status.text()
    op.end = Depth("bottom")
    editor._refresh_selections(c)
    editor.b_remove_ref.click()
    assert not op.height_references and op.geometry == [b]
    editor.close()
