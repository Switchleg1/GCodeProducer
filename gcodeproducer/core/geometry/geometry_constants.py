"""Shared geometry constants and declarative tables."""
from __future__ import annotations
import numpy as np

_STL_RECORD = np.dtype([("normal", "<f4", (3,)), ("v", "<f4", (3, 3)), ("attr", "<u2")])

SLICE_PLANE_BATCH = 16
RASTER_SAMPLE_BATCH = 32_768

PATTERNS = [
    ("rectilinear", "Rectilinear (alternating 90°)"),
    ("grid", "Grid / box (two directions per layer)"),
    ("triangles", "Triangles (three directions, 60°)"),
    ("cubic", "Cubic (3D, shifts with height)"),
    ("lines", "Lines (same direction every layer)"),
]

# Corner order: z, then y, then x (binary XYZ coordinates).
BINARY_BOX_EDGES = ((0,1),(1,3),(3,2),(2,0),(4,5),(5,7),(7,6),(6,4),(0,4),(1,5),(2,6),(3,7))

BINARY_BOX_FACES = ((0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3))

# Width change (mm) still merged by path decimation on variable-width beads.
DECIMATE_WIDTH_TOLERANCE = 0.02

# Rounding (decimal places) that identifies shared medial-axis vertices.
MEDIAL_KEY_DECIMALS = 6
