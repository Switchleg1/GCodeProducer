"""Exercise the actual widget event -> worker -> operation selection path."""
from tests.test_gui import app, win
import time
import numpy as np
import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent


def wait(app, condition):
    deadline = time.monotonic() + 15
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


@pytest.mark.parametrize("mode", ["face", "edge"])
def test_mouse_click_selects_geometry(win, cube_stl, app, mode):
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    ed = win.cam_editor
    ed.add_tool()
    ed.add_operation()
    assert ed.operation() is not None
    assert win.model_viewer.cam_pick_mode == "face"   # usable immediately, not navigation
    from gcodeproducer.core.cam import CAMSetup
    ed.set_setup(CAMSetup.from_dict(ed.setup.to_dict()))  # reopening restores an operation
    op = ed.operation()
    assert op is not None and win.model_viewer.cam_pick_mode == "face"
    assert op.start.source == "stock_top" and op.end.source == "selection"
    ed.pick.setCurrentIndex(ed.pick.findData(mode))
    ed._edit()  # Editing settings must not silently leave selection mode.
    assert win.model_viewer.cam_pick_mode == mode
    view = win.model_viewer
    view.resize(800, 600)
    win.camera.set_view("top")
    view.fit()
    lo, hi = win.placed.bounds
    point = (lo + hi) / 2
    point[2] = hi[2]
    if mode == "edge":
        point[1] = lo[1]
    mvp = win.camera.proj_matrix(view.width()/view.height()) @ win.camera.view_matrix()
    clip = mvp @ np.r_[point, 1]
    ndc = clip[:2]/clip[3]
    xy = (ndc * [1, -1] + 1) * [view.width()/2, view.height()/2]
    if mode == "edge":
        xy += [0, 3]   # near the edge, over the face: exercise edge visibility tolerance
    p = QPointF(*xy)
    view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, p, p, Qt.MouseButton.LeftButton,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, p, p, Qt.MouseButton.LeftButton,
                                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    wait(app, lambda: win._cam_pick_task is None)
    assert len(op.geometry) == 1
    assert op.geometry[0].kind == mode
    assert view.cam_pick_mode == mode
    ed.accept_pick(None)
    assert "Nothing selectable" in ed.pick_status.text()


def test_saved_pocket_can_explicitly_switch_to_selection_depths(win, cube_stl):
    from gcodeproducer.core.cam import CAMSetup, Depth
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    ed = win.cam_editor
    ed.add_tool()
    ed.add_operation()
    ed.operation().start, ed.operation().end = Depth("top"), Depth("bottom")
    ed.set_setup(CAMSetup.from_dict(ed.setup.to_dict()))
    assert ed.operation().end.source == "bottom"  # no silent migration of existing cuts
    ed.b_selection_depths.click()
    assert ed.operation().start.source == "stock_top"
    assert ed.operation().end.source == "selection"
    assert ed.operation().end.extreme == "min"
