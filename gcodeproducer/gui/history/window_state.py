"""Application mementos: model ownership, both workflows, libraries and preferences."""
import copy
import numpy as np
from PyQt6.QtCore import QByteArray
from gcodeproducer.core.cam.cam_setup import CAMSetup
from gcodeproducer.core.jobs.placement import Placement
from gcodeproducer.core.fdm.support_block import SupportBlock
from gcodeproducer.core.fdm.model_support import ModelSupport
from gcodeproducer.core.fdm.plate_model import PlateModel
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.libraries.libraries_constants import KINDS
from gcodeproducer.core.libraries.profile import Profile
from gcodeproducer.core.libraries.process_preset import ProcessPreset
from gcodeproducer.core.settings import preferences
from . import widget_state


class WindowState:
    def __init__(self, window):
        self.window = window
        self.meshes = {}                  # immutable source meshes shared, never copied per keystroke

    def capture(self):
        w = self.window
        mesh_key = id(w.mesh) if w.mesh is not None else None
        if mesh_key is not None:
            self.meshes[mesh_key] = w.mesh
        w._remember_plate_model()
        plate = []
        for model in w.plate_models:
            key = id(model.mesh)
            self.meshes[key] = model.mesh
            plate.append((key, model.path, model.placement.to_dict(), [b.to_dict() for b in model.blocks],
                          model.support.to_dict(), model.persistent))
        return {
            'plate': plate, 'plate_row': w.plate_row,
            'mesh': mesh_key, 'path': w.model_path, 'workflow': w.workflow,
            'machine': w.cb_machine.currentData(),
            'consumables': {k: cb.currentData() for k, (_, _, cb) in w.cons_rows.items()},
            'placement': w.placement.to_dict(), 'blocks': [b.to_dict() for b in w.blocks],
            'support': w.model_support.to_dict(), 'block_row': w.sel_block,
            'cam': w.cam_editor.setup.to_dict(), 'cam_row': w.cam_editor.indices(),
            'pipelines': {k: p.to_dict() for k, p in w.pipelines.items()},
            'process_id': dict(w.process_id), 'dirty': dict(w.dirty),
            'session_process_names': dict(w.session_process_names),
            'libraries': {k: [p.to_dict() for p in w.libset[k].all()] for k in KINDS},
            'processes': [p.to_dict() for p in w.libset.processes.all()],
            'preferences': w.preferences,
            'settings': {k: w.settings.value(k) for k in w.settings.allKeys()
                         if k not in ('geometry', 'windowState', 'messagesDockPlaced')},
            'view': {k: copy.deepcopy(v) for k, v in vars(w.state).items() if k != 'changed'},
            'mode': w.mode,
            'camera': {k: (tuple(v) if isinstance(v, np.ndarray) else v) for k, v in vars(w.camera).items()},
            'reference_tool': (w.reference_editor.mode, w.reference_editor.first),
            'pick_mode': w.model_viewer.cam_pick_mode,
            'cursor': w.playback.cursor, 'selected_line': w.viewer.selected,
            'layout': bytes(w.saveState()), 'messages': w.messages.snapshot(),
        }

    @staticmethod
    def restore_library(lib, records, factory, *, save=True):
        before = {p.id: p.to_dict() for p in lib.all()}
        after = {p['id']: p for p in records}
        if before == after:
            return
        # Only application-owned IDs absent from the target are removed; unrelated files stay intact.
        for pid in before.keys() - after.keys():
            if save and lib.directory:
                (lib.directory / f'{pid}.json').unlink(missing_ok=True)
        lib._items.clear()
        for record in records:
            lib.add(factory.from_dict(record))
        if save:
            lib.save_all()

    def restore_controls(self, state, controls):
        w = self.window
        w.messages.restore(state['messages'])
        widget_state.restore(w, controls, emit=True, selections_only=True)
        widget_state.restore(w, controls)
        for k, v in state['view'].items():
            setattr(w.state, k, copy.deepcopy(v))
        w.state.changed.emit('colors')
        for k, v in state['camera'].items():
            setattr(w.camera, k, np.array(v) if k == 'target' else v)
        w.camera.changed.emit()
        w._on_place_on_face(w.b_face.isChecked())
        w._on_place_block_mode(w.b_place_block.isChecked())
        w._on_remove_block_mode(w.b_remove_block.isChecked())
        w.reference_editor.mode, w.reference_editor.first = state['reference_tool']
        first = w.reference_editor.first
        w.model_viewer.set_reference_anchor(None if first is None else (*first, w.reference_editor.z.value()))
        w.model_viewer.set_cam_mode(state['pick_mode'])
        if w.playback.program is not None:
            w.playback._on_speed(w.playback.speed_slider.value())
            w.playback.layer_min = state['view']['layer_min']
            w.playback.layer_max = state['view']['layer_max']
            w.playback._apply_layers(update_cursor=False)
            w.playback.set_cursor(state['cursor'], follow=False)
        w.viewer.set_selected(state['selected_line'])
        if bytes(w.saveState()) != state['layout']:
            w.restoreState(QByteArray(state['layout']))
        w.set_mode(state['mode'])

    def prune(self, history):
        def mesh_keys(snapshot):
            state = snapshot[0]
            return {state['mesh'], *(model[0] for model in state['plate'])}
        keys = mesh_keys(history.current)
        for before, after in history.entries:
            keys.update(mesh_keys(before) | mesh_keys(after))
        self.meshes = {k: mesh for k, mesh in self.meshes.items() if k in keys}

    def restore(self, state, controls):
        w = self.window
        current = self.capture()
        content_changed = any(current[k] != state[k] for k in (
            'plate', 'plate_row', 'mesh', 'path', 'workflow', 'machine', 'consumables', 'placement', 'blocks', 'support',
            'cam', 'pipelines', 'process_id', 'dirty', 'session_process_names', 'libraries', 'processes', 'preferences'))
        w.playback.stop_play()
        if not content_changed:
            self.restore_controls(state, controls)
            return
        w._cam_highlight_timer.stop()
        # Ignore queued results based on an undone mesh, operation or placement.
        if w.compute.busy:
            w.compute.cancel()
        w._worker = w._face_task = w._cam_pick_task = w._cam_highlight_task = w._blocks_task = None
        w._cam_pick_operation = None
        w.progress.setVisible(False)
        old_model = (id(w.mesh) if w.mesh is not None else None, w.model_path)
        w.mesh = w.model_path = None       # switching workflow must not save outgoing placement
        w.plate_models, w.plate_row = [], -1
        for k in KINDS:
            self.restore_library(w.libset[k], state['libraries'][k], Profile)
        self.restore_library(w.libset.processes, state['processes'], ProcessPreset)
        for k in w.settings.allKeys():
            if k not in ('geometry', 'windowState', 'messagesDockPlaced') and k not in state['settings']:
                w.settings.remove(k)
        for k, value in state['settings'].items():
            w.settings.setValue(k, value)
        w.preferences = copy.deepcopy(state['preferences'])
        preferences.save(w.preferences, w.libset.root)
        w.cam_editor.defaults = w.preferences
        w.pipelines = {k: SlicePipeline.from_dict(p) for k, p in state['pipelines'].items()}
        w.process_id, w.dirty = dict(state['process_id']), dict(state['dirty'])
        w.session_process_names = dict(state['session_process_names'])
        w._loading = True
        w.cb_workflow.setCurrentIndex(w.cb_workflow.findData(state['workflow']))
        w._loading = False
        w._on_workflow()
        w.mesh, w.model_path = self.meshes.get(state['mesh']), state['path']
        w.placement = Placement.from_dict(state['placement'])
        w._pl_prev = copy.deepcopy(w.placement)
        w.blocks = [SupportBlock.from_dict(b) for b in state['blocks']]
        w.model_support = ModelSupport.from_dict(state['support'])
        w.plate_models = [PlateModel(path, self.meshes[key], Placement.from_dict(pose),
                                     [SupportBlock.from_dict(b) for b in blocks], ModelSupport.from_dict(support), original)
                          for key, path, pose, blocks, support, original in state['plate']]
        w.plate_row = state['plate_row']
        w._remember_plate_model()
        w._refresh_model_list()
        w.sel_block = state['block_row']
        setup = CAMSetup.from_dict(state['cam'])
        w.cam_editor.set_setup(setup)
        w.cam_editor.rebuild(tuple(state['cam_row']))
        w.reference_editor.set_setup(setup)
        w.stock_editor.set_stock(setup.stock)
        w.stock_editor.tabs.set_setup(setup)
        w._sync_placement_controls()
        w._sync_support_controls()
        w._refresh_block_list(keep=True)
        if w.mesh is not None:
            from pathlib import Path
            w.lbl_model.setText(f'<b>{Path(w.model_path).name}</b><br>{len(w.mesh.triangles):,} triangles')
            w.lbl_model.setToolTip(w.model_path)
        else:
            w.lbl_model.setText('No model loaded')
        w.place_box.setEnabled(w.mesh is not None)
        # Selection handlers rebuild dependent forms; data itself was restored above.
        self.restore_controls(state, controls)
        if old_model != (state['mesh'], state['path']):
            w.program = w.tp = None
            w.playback.clear()
            w.viewer.set_toolpath(None)
            w.text_panel.set_program(None)
            w.feature_list.clear()
        w._save_placement()
        w._save_selection()
        w._update_dirty()
        w._refresh_recent()
        w._update_blocks_busy()
        w._update_scene()
        w._cam_changed()                 # saves restored CAM and invalidates generated material/output
        w.set_mode(state['mode'])
        w._update_enabled()
