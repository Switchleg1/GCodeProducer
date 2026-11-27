"""CAMSetup — cam subsystem."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from gcodeproducer.core.cam.stock import Stock
from gcodeproducer.core.cam.holding_tab import HoldingTab
from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.depth import Depth
from gcodeproducer.core.cam.operation import Operation
from gcodeproducer.core.cam.tool_group import ToolGroup
from .reference_shape import ReferenceShape

@dataclass
class CAMSetup:
    groups: list[ToolGroup] = field(default_factory=list)
    fingerprint: str = ""
    stock: Stock = field(default_factory=Stock)
    tabs: list[HoldingTab] = field(default_factory=list)
    reference_shapes: list[ReferenceShape] = field(default_factory=list)

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
                d.pop('adaptive_peels', None)  # retired per-depth planning cutoff
                # Adaptive's engagement limit was its own field until 0.2.71; it is now the stepover.
                engagement = d.pop('adaptive_engagement', None)
                if engagement is not None:
                    from .strategy import cutting_strategy
                    if cutting_strategy(d.get('kind', 'pocket'), d.get('strategy', 'contour')) == 'adaptive':
                        d['stepover'] = float(engagement)
                d["geometry"] = [Reference(**r) for r in d.get("geometry", [])]
                d["height_references"] = [Reference(**r) for r in d.get("height_references", [])]
                d["start"], d["end"] = depth(d["start"]), depth(d["end"])
                ops.append(Operation(**d))
            groups.append(ToolGroup(g["tool_id"], ops))
        shapes = [ReferenceShape(**s) for s in data.get("reference_shapes", [])]
        if len({s.id for s in shapes}) != len(shapes):
            raise ValueError("Reference geometry IDs must be unique")
        return cls(groups, data.get("fingerprint", ""), Stock.from_dict(data.get("stock", {})),
                   [HoldingTab(**t) for t in data.get("tabs", [])], shapes)
