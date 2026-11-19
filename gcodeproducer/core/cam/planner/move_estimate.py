"""Cheap geometric estimate of cut moves before entry and engagement planning."""
import numpy as np

from gcodeproducer.core.cam.surface_engagement import sample_step


def estimate_cut_segments(layers, tool_map, first_tool, height, spacing=0.):
    count = 0
    tool = first_tool
    radius = 0.
    for layer in layers:
        next_tool = tool_map.get(getattr(layer, 'cam_tool_id', None), tool)
        if next_tool is not tool or not radius:
            tool = next_tool
            radius = float(tool.get('diameter', 0))/2 if tool else 0.
        for path in layer.paths:
            pts = np.asarray(path.points, float)
            if len(pts) < 2:
                continue
            if pts.shape[1] != 3:
                count += len(pts) - (not path.closed)
                continue
            step = sample_step(radius, height.resolution if height is not None else 0., spacing)
            if step <= 0:
                count += len(pts)-1
                continue
            delta = np.diff(pts, axis=0)
            span = np.maximum(np.linalg.norm(delta[:, :2], axis=1), np.abs(delta[:, 2]))
            count += int(np.ceil(span/step).sum())
    return count
