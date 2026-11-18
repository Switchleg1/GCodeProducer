"""Build per-instance support on a shared grid and print the union once."""
import numpy as np

from gcodeproducer.core.fdm import support
from gcodeproducer.core.geometry import kernel as geometry
from gcodeproducer.core.jobs.layer import Layer


def plate_columns(job, params, base, width, ctx):
    layers = job.layers
    plate = support.model_masks(layers, base)
    result = [np.zeros_like(mask) for mask in plate]
    for i, (model, mesh) in enumerate(zip(job.plate_models, job.placed_models)):
        ms = model.support
        if not ms.enabled or (ms.mode == 'blocks' and not model.blocks):
            continue
        lo, hi = mesh.bounds
        sliced = []
        for layer in layers:
            z = layer.z - layer.height*.5
            outlines = geometry.slice_z(mesh, z) if lo[2] <= z <= hi[2] else []
            sliced.append(Layer(layer.index, layer.z, layer.height, outline=outlines))
        source = support.model_masks(sliced, base, ms.fill_holes)
        obstacles = [p | s for p, s in zip(plate, source)]
        gap = params['z_gap_layers']
        xy = params['xy_distance']
        bottom = params['bottom_z_gap_layers']
        if ms.mode == 'blocks':
            columns = support.block_columns(obstacles, layers, base, model.blocks, xy, gap,
                                            ms.extend, width, bottom, source_masks=source)
        else:
            over = support.overhangs(source, layers, base.res, ms.overhang_angle, params['min_area'])
            columns = support.auto_columns(obstacles, over, base.res, xy, gap, ms.mode == 'everywhere',
                                           ms.extend, width, bottom)
        for dest, cells in zip(result, columns):
            dest |= cells
        ctx.progress(.6 * (i+1)/len(job.plate_models))
    return result
