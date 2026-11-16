"""Compatibility exports. Implementation: gcodeproducer.core.geometry.infill."""
from gcodeproducer.core.geometry.geometry_constants import PATTERNS
from gcodeproducer.core.geometry.infill import (
    pattern_families,
    _edges,
    scan_fill,
    split_by_raster,
    order_segments,
)
