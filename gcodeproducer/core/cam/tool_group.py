"""ToolGroup — cam subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from gcodeproducer.core.cam.operation import Operation

@dataclass
class ToolGroup:
    tool_id: str
    operations: list[Operation] = field(default_factory=list)
