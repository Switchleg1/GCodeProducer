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
    # Two-sided machining (see two_sided.py). ``groups`` are always the operations of the active
    # ``side``; ``other_groups`` those of the side not shown.
    two_sided: bool = False
    side: str = "a"
    flip_axis: str = "x"
    other_groups: list[ToolGroup] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def switch_side(self, side):
        """Make ``side`` ('a' or 'b') the active one: its operations become ``groups``."""
        from .cam_constants import SIDES
        if side not in SIDES:
            raise ValueError(f"Unknown side '{side}'")
        if side != self.side:
            self.groups, self.other_groups = self.other_groups, self.groups
            self.side = side

    def set_two_sided(self, on):
        """Turn two-sided machining on or off; off shows Side A (Side B's operations are kept)."""
        if not on:
            self.switch_side("a")
        self.two_sided = bool(on)

    @classmethod
    def from_dict(cls, data):
        from gcodeproducer.core.cam.planning import fingerprint
        def depth(d):
            d = dict(d)
            if d.get("reference"):
                d["reference"] = Reference(**d["reference"])
            return Depth(**d)
        def tool_groups(items):
            return [group(g) for g in items]

        def group(g):
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
            return ToolGroup(g["tool_id"], ops)
        groups = tool_groups(data.get("groups", []))
        shapes = [ReferenceShape(**s) for s in data.get("reference_shapes", [])]
        if len({s.id for s in shapes}) != len(shapes):
            raise ValueError("Reference geometry IDs must be unique")
        from .cam_constants import FLIP_AXES, SIDES
        side, axis = data.get("side", "a"), data.get("flip_axis", "x")
        if side not in SIDES or axis not in FLIP_AXES:
            raise ValueError("Unknown side or flip axis in the CAM setup")
        return cls(groups, data.get("fingerprint", ""), Stock.from_dict(data.get("stock", {})),
                   [HoldingTab(**t) for t in data.get("tabs", [])], shapes,
                   bool(data.get("two_sided", False)), side, axis, tool_groups(data.get("other_groups", [])))
