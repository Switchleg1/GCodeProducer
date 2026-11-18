"""Depth — cam subsystem."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from gcodeproducer.core.cam.reference import Reference

@dataclass
class Depth:
    source: str = "top"  # top, bottom, absolute, geometry
    value: float = 0.0   # absolute Z, or offset from source
    reference: Reference | None = None
    extreme: str = "max"

    def resolve(self, mesh, topology, references=(), stock=None):
        if self.source == "stock_top":
            return float(stock.top if stock is not None and stock.allocated else mesh.bounds[1][2]) + self.value
        if self.source == "selection":
            if not references:
                raise ValueError("Select pocket bounds to resolve machining depth")
            points = np.concatenate([topology.points(ref, stock) for ref in references])
            z = points[:, 2].min() if self.extreme == "min" else points[:, 2].max()
            return float(z) + self.value
        if self.source == "absolute":
            return self.value
        if self.source == "geometry":
            if self.reference is None:
                raise ValueError("Depth has no geometry reference")
            points = topology.points(self.reference, stock)
            z = points[:, 2].min() if self.extreme == "min" else points[:, 2].max()
        else:
            z = mesh.bounds[0 if self.source == "bottom" else 1][2]
        return float(z) + self.value
