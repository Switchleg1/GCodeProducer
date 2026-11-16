"""Compatibility exports. Implementation: gcodeproducer.core.geometry.kernel."""
from gcodeproducer.core.geometry.mesh import Mesh
from gcodeproducer.core.geometry.kernel import (
    load_stl,
    _load_binary_stl,
    _load_ascii_stl,
    _weld,
    signed_volume,
    slice_z,
    _interp,
    _chain,
    ray_triangles,
    area,
    signed_orient,
    offset,
    point_in_polygon,
    hole_flags,
    outer_contours,
    offset_into_material,
    convex_hull,
    dilate,
    dilate_round,
    erode,
    raster_lines,
    _norm_left,
    perimeter_loops,
)
from gcodeproducer.core.geometry.geometry_constants import _STL_RECORD
from gcodeproducer.core.geometry.region_mask import RegionMask
