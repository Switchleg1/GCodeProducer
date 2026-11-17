"""Application undo/redo, modal histories and face-to-surface placement."""
import copy
import os
import numpy as np
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv('GCODEPRODUCER_LIBRARY', str(tmp_path / 'library'))
    name = 'pytest_history_' + tmp_path.name
    monkeypatch.setenv('GCODEPRODUCER_SETTINGS', name)
    settings = QSettings('GCodeProducer', name)
    settings.clear()
    from gcodeproducer.gui.application.main_window import MainWindow
    w = MainWindow()
    # Geometry/highlight submission isn't relevant to editor history tests.
    w._cam_highlight_timer.start = lambda: None
    yield w
    w.close()
    settings.clear()


def flush(w):
    w.history.scan()
    w.history.flush()


def model(w):
    w.open_model('examples/cube20.stl')
    flush(w)


def cam(w):
    model(w)
    w.cb_workflow.setCurrentIndex(w.cb_workflow.findData('cam'))
    flush(w)
    w.cam_editor.add_tool()
    flush(w)
    w.cam_editor.add_operation()
    flush(w)
    return w.cam_editor


def test_placement_undo_redo_and_branch(win):
    model(win)
    old = win.placement.x
    win.sp_x.setValue(old + 13)
    flush(win)
    win.history.undo()
    assert win.placement.x == old
    assert win.sp_x.value() == old
    win.history.redo()
    assert win.placement.x == old + 13
    win.history.undo()
    win.sp_x.setValue(old + 7)
    flush(win)
    assert not win.history.redo_action.isEnabled()
    assert win.placement.x == old + 7


def test_fdm_process_checkbox_dropdown_and_spin(win):
    from gcodeproducer.gui.editors.param_editor import ParamEditor
    model(win)
    # Generated process forms bind directly to steps, not the placement.
    editor = next(e for e in win.process_editor.findChildren(ParamEditor) if 'layer_height' in e._widgets)
    old = win.pipelines['fdm'].step('fdm_slice').params.get('layer_height', .2)
    editor._widgets['layer_height'].setValue(.31)
    flush(win)
    win.history.undo()
    assert win.pipelines['fdm'].step('fdm_slice').params.get('layer_height', .2) == old
    win.history.redo()
    assert win.pipelines['fdm'].step('fdm_slice').params['layer_height'] == .31
    win.cb_support.setCurrentIndex(win.cb_support.findData('blocks'))
    flush(win)
    win.history.undo()
    assert win.model_support.mode == 'none'
    win.history.redo()
    assert win.model_support.mode == 'blocks'


def test_cam_overrides_lists_and_operation_deletion(win):
    ed = cam(win)
    ed.doc_override.setChecked(True)
    flush(win)
    ed.stepdown.setValue(.37)
    flush(win)
    win.history.undo()
    assert ed.operation().stepdown != .37 and not ed.operation().auto_stepdown
    win.history.undo()
    assert ed.operation().auto_stepdown
    win.history.redo()
    win.history.redo()
    assert ed.operation().stepdown == .37
    ed.delete()
    flush(win)
    assert ed.operation() is None
    win.history.undo()
    assert ed.operation().stepdown == .37
    win.history.redo()
    assert len(ed.setup.groups[0].operations) == 0


def test_geometry_picks_purpose_clear_and_undo(win):
    from gcodeproducer.core.cam.reference import Reference
    ed = cam(win)
    ref = Reference('face', [0])
    ed.accept_pick({'reference': ref, 'z_min': 0., 'z_max': 0.})
    flush(win)
    assert len(ed.operation().geometry) == 1
    item = ed.selections.topLevelItem(0)
    item.setCheckState(1, Qt.CheckState.Unchecked)
    flush(win)
    assert ed.operation().height_references
    win.history.undo()
    assert ed.operation().geometry == [ref] and not ed.operation().height_references
    win.history.undo()
    assert not ed.operation().geometry
    win.history.redo()
    assert ed.operation().geometry == [ref]


def test_reference_stock_tab_and_support_restore(win):
    from gcodeproducer.core.cam.reference_shape import ReferenceShape
    ed = cam(win)
    original = ed.setup.stock.to_dict()
    win.stock_editor.fields['width'].setValue(original['width'] + 5)
    flush(win)
    win.history.undo()
    assert ed.setup.stock.to_dict() == original
    shape = ReferenceShape('circle', 'center', [100, 100], [105, 100], 0)
    ed.setup.reference_shapes.append(shape)
    win.reference_editor.refresh()
    win._cam_changed()
    flush(win)
    win.history.undo()
    assert not ed.setup.reference_shapes
    win.history.redo()
    assert ed.setup.reference_shapes[0].id == shape.id
    assert win.reference_editor.setup is ed.setup
    assert win.stock_editor.tabs.setup is ed.setup


def test_workflow_switch_and_model_import_are_undoable(win):
    model(win)
    win.sp_z.setValue(4)
    flush(win)
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData('cam'))
    flush(win)
    win.history.undo()
    assert win.workflow == 'fdm' and win.placement.z == 4
    win.history.redo()
    assert win.workflow == 'cam' and win.placement.z_anchor == 'top'
    win.history.undo()
    win.history.undo()
    win.history.undo()
    assert win.mesh is None
    win.history.redo()
    assert win.mesh is not None


def test_modal_settings_history(app):
    from gcodeproducer.gui.dialogs.settings_dialog import SettingsDialog
    from gcodeproducer.core.settings.settings_constants import DEFAULTS
    d = SettingsDialog(copy.deepcopy(DEFAULTS))
    try:
        d.editor._widgets['stock_resolution'].setValue(.43)
        flush(d)
        d.history.undo()
        assert d.result_values()['stock_resolution'] == DEFAULTS['stock_resolution']
        d.history.redo()
        assert d.result_values()['stock_resolution'] == .43
        key = next(iter(d.message_checks))
        d.message_checks[key].setChecked(False)
        flush(d)
        d.history.undo()
        assert d.message_checks[key].isChecked() and d.result_values()['messages'][key]
    finally:
        d.close()


def test_modal_library_undo_after_profile_switch(win):
    from gcodeproducer.gui.dialogs.library_dialog import LibraryDialog
    tool = win.libset['tool'].all()[0]
    d = LibraryDialog(win.libset, win, 'tool', tool.id)
    try:
        key = 'soft_wood_pocket_axial'
        old = d._current().get(key)
        d.editor_area.widget()._widgets[key].setValue(39)
        flush(d)
        d.lst.setCurrentRow((d.lst.currentRow() + 1) % d.lst.count())
        flush(d)
        d.history.undo()
        assert d._current().id == tool.id and d._current().get(key) == 39
        d.history.undo()
        assert d._current().get(key) == old
        d.history.redo()
        assert d._current().get(key) == 39
    finally:
        d.close()


def test_library_template_and_multiselect_are_undoable(win):
    from gcodeproducer.gui.dialogs.library_dialog import LibraryDialog
    from PyQt6.QtWidgets import QListWidget
    machine = win.libset.machines.all('fdm')[0]
    d = LibraryDialog(win.libset, win, 'machine', machine.id)
    try:
        editor = d.editor_area.widget()
        template = editor._widgets['start_gcode']
        original = template.text()
        template.edit.setPlainText('G28 ; history test')
        flush(d)                              # before the template debounce would fire
        assert d._current().get('start_gcode') == 'G28 ; history test'
        d.history.undo()
        assert d.editor_area.widget()._widgets['start_gcode'].text() == original
        d.history.redo()
        assert d._current().get('start_gcode') == 'G28 ; history test'
        choices = d.editor_area.widget().findChildren(QListWidget)
        choices = next(c for c in choices if c.count())
        was = choices.item(0).checkState()
        choices.item(0).setCheckState(Qt.CheckState.Unchecked if was == Qt.CheckState.Checked else Qt.CheckState.Checked)
        flush(d)
        d.history.undo()
        choices = next(c for c in d.editor_area.widget().findChildren(QListWidget) if c.count())
        assert choices.item(0).checkState() == was
    finally:
        d.close()


def test_modal_pipeline_add_remove_undo(win):
    from gcodeproducer.gui.editors.pipeline_dialog import PipelineDialog
    d = PipelineDialog(win.pipelines['fdm'], win)
    try:
        n = len(d.pipeline.steps)
        d._add()
        flush(d)
        assert len(d.pipeline.steps) == n + 1
        d.history.undo()
        assert len(d.pipeline.steps) == n
        d.history.redo()
        assert len(d.pipeline.steps) == n + 1
    finally:
        d.close()


@pytest.mark.parametrize('workflow,expected', [('fdm', -1), ('cam', 1)])
def test_face_place_rotation_anchor_and_undo(win, workflow, expected):
    model(win)
    win.cb_workflow.setCurrentIndex(win.cb_workflow.findData(workflow))
    win.placement.rx, win.placement.ry, win.placement.rz = 13, 27, 39
    win._sync_placement_controls()
    win._placement_changed()
    flush(win)
    if workflow == 'fdm':
        win.cb_support.setCurrentIndex(win.cb_support.findData('blocks'))
        win.add_block()
        flush(win)
    blocks_before = [b.to_dict() for b in win.blocks]
    before = win.placement.to_dict()
    normal = np.array([.2, .7, .4])
    normal /= np.linalg.norm(normal)
    local_normal = win.placement.rotation().T @ normal
    win._on_face_clicked(normal)
    flush(win)
    assert np.allclose(win.placement.rotation() @ local_normal, [0, 0, expected], atol=1e-6)
    lo, hi = win.placed.bounds
    assert (lo[2] if workflow == 'fdm' else hi[2]) == pytest.approx(0)
    win.history.undo()
    assert win.placement.to_dict() == before
    assert [b.to_dict() for b in win.blocks] == blocks_before
    win.history.redo()
    assert np.allclose(win.placement.rotation() @ local_normal, [0, 0, expected], atol=1e-6)


def test_shortcuts_override_native_spin_history(win, app):
    model(win)
    win.show()
    win.sp_x.setFocus()
    old = win.sp_x.value()
    win.sp_x.setValue(old + 9)
    flush(win)
    QTest.keyClick(win.sp_x, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert win.placement.x == old
    QTest.keyClick(win.sp_x, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert win.placement.x == old + 9
    assert win.act_place_face.shortcut().toString() == 'Ctrl+L'
    win.act_place_face.trigger()
    assert win.b_face.isChecked() and win.model_viewer.place_on_face
    QTest.keyClick(win.model_viewer, Qt.Key.Key_Escape)
    assert not win.b_face.isChecked()


def test_view_controls_panes_camera_and_messages_undo_without_staling(win):
    from gcodeproducer.gui.editors.section import Section
    model(win)
    # A view-only edit must not invalidate already generated output.
    win.program = object()
    win.stale = False
    win.show_material_cb.setChecked(False)
    flush(win)
    win.history.undo()
    assert win.state.show_material and win.show_material_cb.isChecked()
    assert not win.stale
    pane = win.findChildren(Section)[0]
    expanded = pane.is_expanded()
    pane.set_expanded(not expanded)
    flush(win)
    win.history.undo()
    assert pane.is_expanded() == expanded
    assert pane.content.isHidden() != expanded
    old = (win.camera.yaw, win.camera.pitch)
    win.camera.set_view('front')
    flush(win)
    win.history.undo()
    assert (win.camera.yaw, win.camera.pitch) == old
    win.messages.add('warning', 'Undo clear test', 'Test')
    flush(win)
    win.messages.clear_button.click()
    flush(win)
    assert not win.messages.texts()
    win.history.undo()
    assert win.messages.texts() == ['Undo clear test']
    assert not win.stale


def test_support_block_add_edit_delete_undo(win):
    model(win)
    win.cb_support.setCurrentIndex(win.cb_support.findData('blocks'))
    flush(win)
    win.add_block()
    flush(win)
    before = win.blocks[0].to_dict()
    win.remove_block()
    flush(win)
    assert not win.blocks
    win.history.undo()
    assert win.blocks[0].to_dict() == before
    win.history.undo()
    assert not win.blocks
    win.history.redo()
    assert win.blocks[0].to_dict() == before


def test_global_profile_and_process_save_undo_restore_owned_files(win):
    from gcodeproducer.core.libraries.library_set import LibrarySet
    machine = win.libset.machines.all('fdm')[0]
    original = machine.to_dict()
    machine.values['bed_x'] = 321
    win.libset.save()
    win._reload_machines(machine.id)
    flush(win)
    win.history.undo()
    assert win.libset.machines.get(machine.id).to_dict() == original
    assert LibrarySet(win.libset.root).load().machines.get(machine.id).to_dict() == original
    win.history.redo()
    assert win.libset.machines.get(machine.id).get('bed_x') == 321
    before = set(win.libset.processes.ids())
    win.process_save_as(name='Undoable process')
    flush(win)
    saved = win.process_id['fdm']
    assert saved not in before
    win.history.undo()
    assert saved not in win.libset.processes.ids()
    assert not (win.libset.processes.directory / (saved + '.json')).exists()
    win.history.redo()
    assert saved in win.libset.processes.ids()
    assert (win.libset.processes.directory / (saved + '.json')).exists()


def test_undo_cancels_queued_pick_and_persists_restored_cam(win):
    import json
    ed = cam(win)
    old = ed.setup.to_dict()
    ed.doc_override.setChecked(True)
    flush(win)
    win._cam_pick_task = 123
    old_operation = ed.operation()
    win.history.undo()
    assert win._cam_pick_task is None and ed.operation() is not old_operation
    assert ed.setup.to_dict() == old
    saved = json.loads(win.settings.value(win._model_key('cam', win.model_path)))
    assert saved == old
    # A result for the old request cannot select geometry on the restored operation.
    win._on_compute_done(123, {'error': 'obsolete'})
    assert ed.setup.to_dict() == old


def test_history_is_bounded_and_new_edit_drops_redo(app):
    from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSpinBox
    from gcodeproducer.gui.history.edit_history import EditHistory
    from gcodeproducer.gui.history.history_constants import HISTORY_LIMIT
    root = QWidget()
    spin = QSpinBox()
    spin.setMaximum(1000)
    QVBoxLayout(root).addWidget(spin)
    root.history = EditHistory(root)
    try:
        for value in range(1, HISTORY_LIMIT + 5):
            spin.setValue(value)
            flush(root)
        assert len(root.history.entries) == HISTORY_LIMIT
        root.history.undo()
        assert root.history.redo_action.isEnabled()
        spin.setValue(999)
        flush(root)
        assert not root.history.redo_action.isEnabled()
    finally:
        root.history.dispose()
        root.close()


def test_compute_face_pick_hits_and_misses():
    from gcodeproducer.core.jobs.session import load_mesh
    from gcodeproducer.core.runtime.compute import run_placement_face
    mesh = load_mesh('examples/cube20.stl')
    assert np.allclose(run_placement_face((mesh, [10, 10, 50], [0, 0, -1])), [0, 0, 1])
    assert run_placement_face((mesh, [100, 100, 50], [0, 0, -1])) is None
