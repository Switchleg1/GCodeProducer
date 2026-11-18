"""Portable workspace metadata; model files and generated G-code stay external."""
import base64
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QByteArray, QSignalBlocker

from gcodeproducer.core.cam.cam_setup import CAMSetup
from gcodeproducer.core.fdm.model_support import ModelSupport
from gcodeproducer.core.fdm.plate_model import PlateModel
from gcodeproducer.core.fdm.support_block import SupportBlock
from gcodeproducer.core.jobs.placement import Placement
from gcodeproducer.core.jobs.session import load_mesh
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from .application_constants import WORK_SESSION_VERSION


def _model_record(path, placement, blocks, support, persistent=True):
    return dict(path=str(Path(path).resolve()), placement=placement.to_dict(),
                blocks=[b.to_dict() for b in blocks], support=support.to_dict(), persistent=persistent)


def capture(window):
    w = window
    w._remember_plate_model()
    cam = dict(setup=w.cam_editor.setup.to_dict(), selection=list(w.cam_editor.indices())) if w.plate_models else None
    processes = {}
    for workflow, pipeline in w.pipelines.items():
        pid = w.process_id[workflow]
        name = next((p.name for p in w.libset.processes.all(workflow) if p.id == pid),
                    w.session_process_names.get(workflow))
        processes[workflow] = dict(id=pid, name=name, pipeline=pipeline.to_dict(), dirty=w.dirty[workflow])
    return dict(version=WORK_SESSION_VERSION, workflow=w.workflow, processes=processes,
                models=[_model_record(m.path, m.placement, m.blocks, m.support, m.persistent)
                        for m in w.plate_models], selected=w.plate_row, cam=cam,
                geometry=bytes(w.saveGeometry().toBase64()).decode('ascii'),
                layout=bytes(w.saveState().toBase64()).decode('ascii'),
                camera=dict(target=w.camera.target.tolist(), distance=w.camera.distance,
                            yaw=w.camera.yaw, pitch=w.camera.pitch, ortho=w.camera.ortho))


def restore(window, data, *, base=None, skip_missing=False):
    """Load and validate before replacing the workspace. Automatic restore can skip absent files."""
    if not isinstance(data, dict) or data.get('version') not in (1, WORK_SESSION_VERSION):
        raise ValueError('Unsupported work session format.')
    w = window
    workflow = data['workflow']
    if workflow not in w.pipelines:
        raise ValueError(f'Unknown workflow: {workflow}')
    geometry = base64.b64decode(data['geometry'], validate=True)
    layout = base64.b64decode(data['layout'], validate=True)
    camera = data['camera']
    target = np.asarray(camera['target'], float)
    distance, yaw, pitch = (float(camera[k]) for k in ('distance', 'yaw', 'pitch'))
    ortho = bool(camera['ortho'])
    if target.shape != (3,) or not np.isfinite([*target, distance, yaw, pitch]).all() or distance <= 0:
        raise ValueError('Invalid session camera.')

    processes = {}
    for kind in w.pipelines:
        record = data['processes'][kind]
        pipeline = SlicePipeline.from_dict(record['pipeline']).ensure_defaults()
        if pipeline.workflow != kind:
            raise ValueError(f'Process workflow does not match {kind}.')
        pipeline.validate()
        presets = w.libset.processes.all(kind)
        preset = next((p for p in presets if p.id == record['id']), None)
        if preset is None and record['name']:
            preset = next((p for p in presets if p.name == record['name']), None)
        dirty = bool(record['dirty']) or (preset is not None and preset.slice_pipeline().to_dict() != pipeline.to_dict())
        session_name = record['name'] if preset is None else None
        processes[kind] = (preset.id if preset else None, pipeline, dirty or bool(session_name), session_name)

    warnings, meshes = [], {}

    def load(record):
        path = Path(record['path'])
        if not path.is_absolute() and base is not None:
            path = base / path
        path = str(path.resolve())
        if path not in meshes:
            try:
                meshes[path] = load_mesh(path)
            except (OSError, ValueError) as exc:
                if not skip_missing:
                    raise ValueError(f'Cannot load model {path}: {exc}') from exc
                warnings.append(f'Skipped model {path}: {exc}')
                meshes[path] = None
        if meshes[path] is None:
            return None
        return PlateModel(path, meshes[path], Placement.from_dict(record['placement']),
                          [SupportBlock.from_dict(b) for b in record['blocks']],
                          ModelSupport.from_dict(record['support']), bool(record['persistent']))

    cam = data['cam']
    records, selected = data['models'], int(data['selected'])
    if data['version'] == 1 and cam is not None:
        cam_records = cam.get('models', [cam])
        if workflow == 'cam' or not records:
            records, selected = cam_records, int(cam.get('selected', 0))
        elif [m['path'] for m in records] != [m['path'] for m in cam_records]:
            cam = None  # CAM references belonged to a different model list
            warnings.append('Kept the FDM model list; the old CAM setup used different models.')
    plate, row = [], -1
    for i, record in enumerate(records):
        model = load(record)
        if model is not None:
            if i == selected:
                row = len(plate)
            plate.append(model)
    if plate and row < 0:
        row = 0
    setup, cam_selection = CAMSetup(), None
    if plate:
        from gcodeproducer.core.cam.assembly import assembly_fingerprint
        from gcodeproducer.core.fdm.plate import reanchor_models
        current = assembly_fingerprint(plate)
        if cam is not None:
            setup = CAMSetup.from_dict(cam['setup'])
            if len(plate) != len(records) or (setup.fingerprint and setup.fingerprint != current):
                warnings.append('CAM source geometry changed; the saved CAM setup was not restored.')
                setup = CAMSetup()
            else:
                cam_selection = tuple(cam['selection'])
        setup.fingerprint = current
        reanchor_models(plate, 'top' if workflow == 'cam' else 'bottom', None)

    w._cam_highlight_timer.stop()
    w._face_task = w._blocks_task = w._cam_pick_task = w._cam_highlight_task = None
    w.b_face.setChecked(False)
    w._end_block_tools()
    w.model_viewer.set_seam_pick(False)
    w._reset_material_outputs()
    w.program = w.tp = None
    w.playback.clear()
    w.viewer.set_toolpath(None)
    w.text_panel.set_program(None)
    w.feature_list.clear()
    w.stale = False
    w.mesh = w.model_path = None  # don't save old placement during the workflow change
    w.plate_models, w.plate_row = plate, row
    w.session_process_names.clear()
    for kind, (pid, pipeline, dirty, name) in processes.items():
        w.process_id[kind], w.pipelines[kind], w.dirty[kind] = pid, pipeline, dirty
        if name:
            w.session_process_names[kind] = name
    with QSignalBlocker(w.cb_workflow):
        w.cb_workflow.setCurrentIndex(w.cb_workflow.findData(workflow))
    w._on_workflow()
    w._show_cam_setup(setup)
    if cam_selection is not None:
        w.cam_editor.rebuild(cam_selection)
    w._refresh_model_list()
    w.set_mode('prepare')
    w.restoreGeometry(QByteArray(geometry))
    w.restoreState(QByteArray(layout))
    w.camera.target, w.camera.distance, w.camera.yaw, w.camera.pitch, w.camera.ortho = target, distance, yaw, pitch, ortho
    with QSignalBlocker(w.ortho_cb):
        w.ortho_cb.setChecked(ortho)
    w.camera.changed.emit()
    w._update_blocks_busy()
    w._update_scene()
    w._update_enabled()
    return warnings
