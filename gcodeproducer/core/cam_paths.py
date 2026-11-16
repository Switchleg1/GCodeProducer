"""Compatibility exports. Implementation: gcodeproducer.core.cam.paths."""
from gcodeproducer.core.cam.cam_constants import DIRECTIONS
from gcodeproducer.core.cam.paths import (
    direction_for,
    orient_contour,
    pocket_region,
    part_section,
    overcut_region,
    _polygons,
    boundary_paths,
    machining_areas,
    _nearest_seam,
    link_contours,
    contour_pocket,
)
