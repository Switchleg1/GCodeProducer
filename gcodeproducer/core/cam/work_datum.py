"""Convert a placed CAM setup to bed coordinates without editing the saved setup."""
from copy import deepcopy
from dataclasses import replace
import math
import numpy as np


def bed_offset(machine, stock):
    if machine is None or not machine.get('cam_z0_at_bed', False):
        return 0.
    if stock is None or not stock.allocated:
        raise ValueError('CAM Z0 at bed requires allocated stock with a known thickness.')
    return stock.height-stock.top


def _machine_plane(job, key, default):
    clearance = float(job.m(key, default))
    if job.m('cam_z0_at_bed', False):
        stock = getattr(job.cam_setup, 'stock', None)
        bed_offset(job.machine, stock)  # reject an unknown stock thickness
        return stock.height + clearance
    return clearance


def safe_height(job):
    return _machine_plane(job, 'safe_z', 15.)


def clearance_height(job):
    return _machine_plane(job, 'clearance_z', 5.)


def apply_bed_datum(job):
    if not job.m('cam_z0_at_bed', False):
        return
    offset = bed_offset(job.machine, getattr(job.cam_setup, 'stock', None))
    if not math.isfinite(offset):
        raise ValueError('Invalid stock Z for bed datum')
    if not job.cam_setup.stock.height <= clearance_height(job) <= safe_height(job):
        raise ValueError('Bed datum requires Clearance Z between the stock top and Safe Z')
    if safe_height(job) > job.m('work_z', 100.) + 1e-6:
        raise ValueError('Stock thickness plus Safe Z exceeds the machine Z travel')
    setup = deepcopy(job.cam_setup)
    setup.stock.top = setup.stock.height
    job.cam_setup = setup
    shift = np.array([0.,0.,offset])
    job.mesh = replace(job.mesh, vertices=job.mesh.vertices+shift)
    job.placed_models = [replace(m, vertices=m.vertices+shift) for m in job.placed_models]
    for shape in setup.reference_shapes:
        shape.z += offset
    for group in (*setup.groups,*setup.other_groups):
        for op in group.operations:
            for depth in (op.start,op.end):
                if depth.source == 'absolute':
                    depth.value += offset
