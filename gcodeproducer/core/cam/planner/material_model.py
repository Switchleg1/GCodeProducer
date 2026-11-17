"""MaterialModel — one interface over the two current-material representations.

* **planar**: depth-tagged exact XY sweeps (``PlanarStock``) — engagement,
  cutting hand, air removal and reach while generating operation passes.
* **height**: a height field (``HeightStock``) updated by every emitted move —
  entries, links, leads, XYZ engagement and the material display/checks.

Callers ask the model for a *sampler* instead of touching either
representation: ``planar_sampler(z)`` or ``height_sampler()``; both share the
:class:`EngagementSampler` interface and :class:`EngagementModel` classifier.
"""
from __future__ import annotations
from shapely.geometry import box
from .planar_sampler import PlanarSampler
from .height_sampler import HeightSampler


class MaterialModel:
    def __init__(self, job, stock=None, estimate=False, log=None):
        """``estimate``: without allocated stock, use a conservative model-bounds blank
        for the height field (needed for XYZ entries); planar history stays absent."""
        from gcodeproducer.core.cam.planar_stock import PlanarStock
        from gcodeproducer.core.cam.material import height_stock_for
        self.job = job
        self.stock = stock if stock is not None else getattr(job.cam_setup, "stock", None)
        allocated = self.stock is not None and self.stock.allocated
        self.planar = PlanarStock(self.stock) if allocated else None
        self.height = height_stock_for(job, self.stock) if allocated else None
        self._log = log
        self._estimated = False
        if estimate and self.height is None:
            self.estimate_height()

    @property
    def allocated(self):
        return self.planar is not None

    def estimate_height(self):
        """Conservative model-bounds height field when no stock is allocated (logged once)."""
        if self.height is None and self.job.mesh is not None:
            from gcodeproducer.core.cam.stock import Stock
            from gcodeproducer.core.cam.material import height_stock_for
            estimate = Stock()
            estimate.auto(self.job.mesh)
            self.height = height_stock_for(self.job, estimate)
            self._estimated = True
            if self._log:
                self._log("  3D Contour: conservative model-bounds blank for entry/engagement; "
                          "allocate stock for accurate material history")
        return self.height

    # ---------------------------------------------------------------- planar
    def planar_at(self, z):
        return self.planar.at(z) if self.planar is not None else None

    def remove_planar(self, paths, z, radius):
        if self.planar is not None:
            self.planar.remove(paths, z, radius)

    def top_within(self, geom, start, end):
        return self.planar.top_within(geom, start, end) if self.planar is not None else start

    def planar_sampler(self, z=None, material=None, fallback_points=None, radius=0.0):
        """Sampler on the remaining region at depth ``z`` (or an explicit ``material``).

        Without allocated stock the region is a conservative XY box around
        ``fallback_points`` grown by two cutter radii.
        """
        if material is None and z is not None and self.planar is not None:
            material = self.planar.at(z)
        if material is None and self.stock is not None and self.stock.allocated:
            lo, hi = self.stock.bounds
            material = box(lo[0], lo[1], hi[0], hi[1])
        if material is None:
            import numpy as np
            p = np.asarray(fallback_points, float)[:, :2]
            lo, hi = p.min(axis=0)-2*radius, p.max(axis=0)+2*radius
            material = box(lo[0], lo[1], hi[0], hi[1])
        return PlanarSampler(material)

    # ---------------------------------------------------------------- height
    def height_sampler(self):
        return HeightSampler(self.height) if self.height is not None else None
