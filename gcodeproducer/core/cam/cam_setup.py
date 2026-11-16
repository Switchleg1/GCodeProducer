"""CAMSetup — cam subsystem."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import gcodeproducer.core.geometry.kernel as geometry
from gcodeproducer.core.cam.stock import Stock
from gcodeproducer.core.cam.holding_tab import HoldingTab
from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.depth import Depth
from gcodeproducer.core.cam.operation import Operation
from gcodeproducer.core.cam.tool_group import ToolGroup

@dataclass
class CAMSetup:
    groups: list[ToolGroup] = field(default_factory=list)
    fingerprint: str = ""
    stock: Stock = field(default_factory=Stock)
    tabs: list[HoldingTab] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        from gcodeproducer.core.cam.planning import fingerprint
        def depth(d):
            d = dict(d)
            if d.get("reference"):
                d["reference"] = Reference(**d["reference"])
            return Depth(**d)
        groups = []
        for g in data.get("groups", []):
            ops = []
            for item in g.get("operations", []):
                d = dict(item)
                d["geometry"] = [Reference(**r) for r in d.get("geometry", [])]
                d["height_references"] = [Reference(**r) for r in d.get("height_references", [])]
                d["start"], d["end"] = depth(d["start"]), depth(d["end"])
                ops.append(Operation(**d))
            groups.append(ToolGroup(g["tool_id"], ops))
        return cls(groups, data.get("fingerprint", ""), Stock.from_dict(data.get("stock", {})),
                   [HoldingTab(**t) for t in data.get("tabs", [])])
