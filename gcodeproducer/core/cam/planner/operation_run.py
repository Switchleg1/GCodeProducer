"""OperationRun — one enabled operation with its resolved tool, depths and cutting data."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class OperationRun:
    op: object
    tool: object
    group: int
    index: int
    cutting: object
    start: float
    end: float
    step: float
    count: int
    direction: str

    @property
    def diameter(self):
        return float(self.tool.get("diameter", 0))

    @property
    def radius(self):
        return self.diameter/2

    def depth(self, i):
        return max(self.end, self.start-(i+1)*self.step)

    def add_layer(self, planning, planned, z, height, area):
        """Append one depth/area pass of this operation to the job's layers."""
        from gcodeproducer.core.jobs.layer import Layer
        layer = Layer(len(planning.layers), z, height, paths=planned)
        layer.cam_tool_id = self.tool.id
        layer.cam_group = self.group
        layer.cam_operation = self.op.name
        layer.cam_operation_key = (self.group, self.index)
        layer.cam_area = area
        layer.cam_operation_config = self.op
        layer.cam_cutting = self.cutting
        planning.layers.append(layer)
        return layer
