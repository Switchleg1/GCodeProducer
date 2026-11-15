"""Support computation shared by the ``fdm_support`` stage and the GUI's block generator.

Everything works on per-layer boolean rasters on one shared grid
(:class:`~gcodeproducer.core.geometry.RegionMask`):

* :func:`model_masks`    - the model's cross-section on every layer
* :func:`overhangs`      - cells that need support (overhang angle)
* :func:`auto_columns`   - automatic support: columns grown down from overhangs
                           (``buildplate`` or ``everywhere``)
* :func:`block_columns`  - manual support: support inside user :class:`SupportBlock`
                           volumes wherever the model is above
* :func:`blocks_from_columns` / :func:`generate_blocks` - turn automatic support
  into editable blocks (one box per support island)
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass

import numpy as np

from . import geometry


# --------------------------------------------------------------------------
@dataclass
class SupportBlock:
    """An axis-aligned support volume in world (bed) coordinates, mm."""
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float

    def __post_init__(self):
        self.normalize()

    def normalize(self) -> "SupportBlock":
        self.x0, self.x1 = sorted((float(self.x0), float(self.x1)))
        self.y0, self.y1 = sorted((float(self.y0), float(self.y1)))
        self.z0, self.z1 = sorted((float(self.z0), float(self.z1)))
        self.z0 = max(0.0, self.z0)
        return self

    # centre / size view used by the GUI
    @property
    def center(self):
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @property
    def size(self):
        return (self.x1 - self.x0, self.y1 - self.y0, self.z1 - self.z0)

    def set_geometry(self, cx, cy, z0, w, d, h) -> None:
        w, d, h = max(0.1, w), max(0.1, d), max(0.1, h)
        self.x0, self.x1 = cx - w / 2, cx + w / 2
        self.y0, self.y1 = cy - d / 2, cy + d / 2
        self.z0, self.z1 = max(0.0, z0), max(0.0, z0) + h

    def translate(self, dx=0.0, dy=0.0, dz=0.0) -> None:
        self.x0 += dx
        self.x1 += dx
        self.y0 += dy
        self.y1 += dy
        self.z0 = max(0.0, self.z0 + dz)
        self.z1 = max(self.z0 + 0.1, self.z1 + dz)

    def to_dict(self) -> dict:
        return {k: round(v, 4) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict) -> "SupportBlock":
        return cls(*(float(d[k]) for k in ("x0", "y0", "z0", "x1", "y1", "z1")))


# --------------------------------------------------------------------------
def make_grid(lo, hi, line_width: float) -> geometry.RegionMask:
    res = max(0.2, min(0.5, line_width * 0.75))
    return geometry.RegionMask(lo[:2], hi[:2], res)


def model_masks(layers, base: geometry.RegionMask) -> list:
    out = []
    for layer in layers:
        rm = base.like()
        rm.fill([np.asarray(c, float) for c in (layer.outline or layer.contours) if len(c) >= 3])
        out.append(rm.grid)
    return out


def overhangs(masks, layers, res: float, angle_deg: float, min_area: float) -> list:
    tan_a = math.tan(math.radians(angle_deg))
    min_cells = min_area / (res * res)
    over = [np.zeros_like(masks[0])]
    for i in range(1, len(masks)):
        reach = max(1, int(round(layers[i].height * tan_a / res)))
        o = masks[i] & ~geometry.dilate(masks[i - 1], reach)
        o = geometry.dilate(geometry.erode(o, 1), 1)          # drop raster noise
        if o.sum() < min_cells:
            o[:] = False
        over.append(o)
    return over


def auto_columns(masks, over, res: float, xy_distance: float, gap: int, everywhere: bool) -> list:
    n = len(masks)
    xy = max(1, int(math.ceil(xy_distance / res)))
    below_any = [np.zeros_like(masks[0])]
    for i in range(1, n):
        below_any.append(below_any[-1] | masks[i - 1])
    acc = np.zeros_like(masks[0])
    sup = [None] * n
    for i in range(n - 1, -1, -1):
        j = i + 1 + gap
        if j < n:
            acc |= over[j]
        acc &= ~masks[i]                     # a column stops where it meets the model
        s = acc & ~geometry.dilate(masks[i], xy)
        if everywhere:
            if i > 0:
                s &= ~masks[i - 1]           # one layer gap on top of the model
        else:
            s &= ~below_any[i]               # build plate only: nothing of the model underneath
        sup[i] = s
    return sup


def block_cells(base: geometry.RegionMask, blocks, z: float) -> np.ndarray:
    """Cells covered by the blocks that span height ``z``."""
    g = np.zeros((base.ny, base.nx), bool)
    for b in blocks:
        if not (b.z0 - 1e-6 <= z <= b.z1 + 1e-6):
            continue
        i0 = max(0, int(math.floor((b.x0 - base.lo[0]) / base.res)))
        i1 = min(base.nx, int(math.ceil((b.x1 - base.lo[0]) / base.res)))
        j0 = max(0, int(math.floor((b.y0 - base.lo[1]) / base.res)))
        j1 = min(base.ny, int(math.ceil((b.y1 - base.lo[1]) / base.res)))
        if i1 > i0 and j1 > j0:
            g[j0:j1, i0:i1] = True
    return g


def block_columns(masks, layers, base, blocks, xy_distance: float, gap: int) -> list:
    """Support inside the block volumes wherever there is model above (with a Z gap)."""
    n = len(masks)
    xy = max(1, int(math.ceil(xy_distance / base.res)))
    above = np.zeros_like(masks[0])
    sup = [None] * n
    for i in range(n - 1, -1, -1):
        j = i + 1 + gap
        if j < n:
            above |= masks[j]
        mid_z = layers[i].z - layers[i].height * 0.5
        s = block_cells(base, blocks, mid_z) & above & ~geometry.dilate(masks[i], xy)
        for k in range(1, gap + 1):          # keep the top Z gap empty under the model
            if i + k < n:
                s &= ~masks[i + k]
        if i > 0:
            s &= ~masks[i - 1]               # one layer gap on top of the model
        sup[i] = s
    return sup


# --------------------------------------------------------------------------
def block_at(mesh, x: float, y: float, z: float, size: float, facing_down: bool = False,
             eps: float = 1e-3):
    """Pick-and-place: a ``size`` x ``size`` block filling the vertical gap at (x, y).

    * clicked on the bed or on a face pointing up (``facing_down`` False): the block
      runs from ``z`` straight up to the next face of the model above;
    * clicked on a face pointing down (an overhang seen from below): it runs from
      the next surface below (model or bed) up to ``z``.

    Returns a :class:`SupportBlock`, or None when there is nothing to fill
    (e.g. clicking the top of the model).
    """
    tris = np.asarray(mesh.vertices, float)[np.asarray(mesh.triangles)]
    if facing_down:
        t, i = geometry.ray_triangles(np.array([x, y, z - eps]), np.array([0.0, 0.0, -1.0]), tris)
        z0 = max(0.0, z - eps - t) if i >= 0 else 0.0
        z1 = z
    else:
        t, i = geometry.ray_triangles(np.array([x, y, z + eps]), np.array([0.0, 0.0, 1.0]), tris)
        if i < 0:
            return None
        z0, z1 = max(0.0, z), z + eps + t
    if z1 - z0 < 0.05:
        return None
    h = size / 2.0
    return SupportBlock(x - h, y - h, z0, x + h, y + h, z1)


def _components(grid: np.ndarray) -> list:
    """8-connected components of a boolean grid -> list of (rows, cols) index arrays."""
    seen = np.zeros_like(grid)
    ny, nx = grid.shape
    out = []
    for sj, si in zip(*np.nonzero(grid)):
        if seen[sj, si]:
            continue
        q = deque([(sj, si)])
        seen[sj, si] = True
        rows, cols = [], []
        while q:
            j, i = q.popleft()
            rows.append(j)
            cols.append(i)
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    a, b = j + dj, i + di
                    if 0 <= a < ny and 0 <= b < nx and grid[a, b] and not seen[a, b]:
                        seen[a, b] = True
                        q.append((a, b))
        out.append((np.array(rows), np.array(cols)))
    return out


def blocks_from_columns(sup, layers, base, gap: int = 1, min_size: float = 1.0) -> list:
    """One block per support island (bounding box of its footprint and height range)."""
    if not sup:
        return []
    foot = np.zeros_like(sup[0])
    for s in sup:
        foot |= s
    blocks = []
    res = base.res
    for rows, cols in _components(foot):
        comp = np.zeros_like(foot)
        comp[rows, cols] = True
        idx = [i for i, s in enumerate(sup) if (s & comp).any()]
        if not idx:
            continue
        x0 = base.lo[0] + cols.min() * res
        x1 = base.lo[0] + (cols.max() + 1) * res
        y0 = base.lo[1] + rows.min() * res
        y1 = base.lo[1] + (rows.max() + 1) * res
        if x1 - x0 < min_size and y1 - y0 < min_size:
            continue
        lo_l, hi_l = layers[idx[0]], layers[idx[-1]]
        z0 = max(0.0, lo_l.z - lo_l.height)
        z1 = hi_l.z + (gap + 1) * hi_l.height             # reach up to the model surface
        blocks.append(SupportBlock(x0, y0, z0, x1, y1, z1))
    return blocks


def slice_layers(mesh, layer_height: float, first_layer_height: float | None = None) -> list:
    """Every layer from the bed to the top of the mesh (empty ones included)."""
    from .job import Layer
    flh = first_layer_height or layer_height
    top = float(mesh.bounds[1][2])
    layers = []
    z = flh
    while z <= top + 1e-6:
        h = flh if not layers else layer_height
        contours = geometry.slice_z(mesh, z - h * 0.5)
        layers.append(Layer(index=len(layers), z=round(z, 4), height=h,
                            contours=list(contours), outline=list(contours)))
        z += layer_height
    return layers


def generate_blocks(mesh, layer_height: float = 0.2, line_width: float = 0.45, angle: float = 50.0,
                    everywhere: bool = False, xy_distance: float = 0.8, gap: int = 1,
                    min_area: float = 1.0, first_layer_height: float | None = None) -> list:
    """Automatic support for a placed mesh, returned as editable blocks."""
    layers = slice_layers(mesh, layer_height, first_layer_height)
    if len(layers) < 2:
        return []
    lo, hi = mesh.bounds
    base = make_grid(lo, hi, line_width)
    masks = model_masks(layers, base)
    over = overhangs(masks, layers, base.res, angle, min_area)
    sup = auto_columns(masks, over, base.res, xy_distance, gap, everywhere)
    return blocks_from_columns(sup, layers, base, gap)
