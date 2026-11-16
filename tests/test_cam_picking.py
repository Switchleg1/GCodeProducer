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
    assert op.start.source == "selection" and op.start.extreme == "max" and op.end.source == "selection"
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


@pytest.mark.parametrize("mode", ["face", "edge"])
def test_mouse_selects_material_boundaries_instead_of_part(win, cube_stl, app, mode):
    from gcodeproducer.core.cam import CAMSetup, Depth, Topology
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    win._auto_stock()
    ed = win.cam_editor
    ed.add_tool(); ed.add_operation()
    win.show_material_cb.setChecked(False)
    ed.pick_source.setCurrentIndex(ed.pick_source.findData("stock"))
    assert win.show_material_cb.isChecked()  # material targeting makes boundaries visible
    ed.pick.setCurrentIndex(ed.pick.findData(mode))
    assert win.model_viewer.cam_pick_mode == "stock_"+mode
    view = win.model_viewer
    view.resize(800,600)
    win.camera.set_view("top"); view.fit()
    lo,hi = ed.setup.stock.bounds
    point = (lo+hi)/2; point[2] = hi[2]
    if mode == "edge":point[1] = lo[1]
    mvp = win.camera.proj_matrix(view.width()/view.height()) @ win.camera.view_matrix()
    clip = mvp @ np.r_[point,1]
    xy = (clip[:2]/clip[3]*[1,-1]+1)*[view.width()/2,view.height()/2]
    p = QPointF(*xy)
    view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress,p,p,Qt.MouseButton.LeftButton,
                                    Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease,p,p,Qt.MouseButton.LeftButton,
                                      Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
    wait(app, lambda: win._cam_pick_task is None)
    op = ed.operation()
    assert len(op.geometry)==1 and op.geometry[0].kind=="stock_"+mode
    assert Depth("geometry",reference=op.geometry[0]).resolve(win.placed,Topology(win.placed),stock=ed.setup.stock)==hi[2]
    ed.set_setup(CAMSetup.from_dict(ed.setup.to_dict()))
    assert ed.operation().geometry[0].kind=="stock_"+mode


@pytest.mark.parametrize("mode", ["edge", "face"])
def test_mixed_picker_selects_part_and_material_without_switching(win, cube_stl, app, mode):
    import copy
    from gcodeproducer.core.cam import Depth, generate
    from gcodeproducer.core.session import build_job
    from gcodeproducer.stages.base import StageContext
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData("cam"))
    win.open_model(cube_stl)
    win.cam_editor.setup.stock.margin=6
    win._auto_stock()
    ed=win.cam_editor;ed.add_tool();ed.add_operation()
    assert ed.pick_source.currentData()=="both"
    ed.pick.setCurrentIndex(ed.pick.findData(mode))
    view=win.model_viewer;view.resize(800,600)
    win.camera.set_view("top");view.fit()
    for index,bounds in enumerate((win.placed.bounds, ed.setup.stock.bounds)):
        lo,hi=bounds
        point=(lo+hi)/2;point[2]=hi[2]
        if mode=="edge":point[1]=lo[1]
        elif index==1:point[0]=lo[0]+1  # exposed stock face outside the part
        mvp=win.camera.proj_matrix(view.width()/view.height()) @ win.camera.view_matrix()
        clip=mvp @ np.r_[point,1]
        p=QPointF(*((clip[:2]/clip[3]*[1,-1]+1)*[view.width()/2,view.height()/2]))
        view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress,p,p,Qt.MouseButton.LeftButton,
                                        Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
        view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease,p,p,Qt.MouseButton.LeftButton,
                                          Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
        wait(app,lambda: win._cam_pick_task is None)
    assert [r.kind for r in ed.operation().geometry]==[mode,"stock_"+mode]
    assert ed.pick_source.currentData()=="both"      # no target changes between clicks
    op=ed.operation();op.start=Depth("stock_top");op.end=Depth("absolute",-2)
    job=build_job("cam",win._machine(),mesh=win.placed,
                  tools=win.libset.consumables_for(win._machine(),"tool"),cam_setup=copy.deepcopy(ed.setup))
    generate(job,StageContext())                    # one straight cube edge expands to its horizontal rim
    assert job.layers and min(l.z for l in job.layers)==-2


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
    assert ed.operation().start.source == "selection" and ed.operation().start.extreme == "max"
    assert ed.operation().end.source == "selection"
    assert ed.operation().end.extreme == "min"
