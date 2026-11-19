"""Support computation shared by the ``fdm_support`` stage and the GUI's block generator.

Everything works on per-layer boolean rasters on one shared grid
(:class:`~gcodeproducer.core.geometry.RegionMask`):

* :func:`model_masks`    - the model's cross-section on every layer (small holes
                           filled, so support continues under them)
* :func:`overhangs`      - cells that need support (overhang angle)
* :func:`auto_columns`   - automatic support: columns grown down from overhangs
                           (``buildplate`` or ``everywhere``)
* :func:`block_columns`  - manual support: support inside user :class:`SupportBlock`
                           volumes wherever the model is above
* :func:`blocks_from_columns` / :func:`generate_blocks` - turn automatic support
  into editable blocks (one box per support island)
"""
from __future__ import annotations

from gcodeproducer.core.fdm.model_support import ModelSupport
from gcodeproducer.core.fdm.support_block import SupportBlock
from gcodeproducer.core.fdm.fdm_constants import SUPPORT_MODES
import math, numpy as np, gcodeproducer.core.geometry.kernel as geometry
from collections import deque


def make_grid(lo, hi, line_width: float, margin: float = 0.0) -> geometry.RegionMask:
    """Shared support raster; padded so support can extend ``margin`` past the model."""
    res = max(0.2, min(0.5, line_width * 0.75))
    # whole cells of padding: the grid stays aligned the same way whatever the margin
    pad = math.ceil((2.0 + max(0.0, margin)) / res) * res
    return geometry.RegionMask(lo[:2], hi[:2], res, pad=pad)


def support_polys(layer, fill_holes: float = 0.0) -> list:
    """The layer's slice polygons with holes up to ``fill_holes`` mm² filled in.

    For support purposes a small hole counts as solid: the support below runs
    on under it (so the hole's perimeters are supported) and never climbs up
    inside it.  Larger openings - e.g. a pocket opening downward - stay open and
    are supported like any other overhang.
    """
    polys = [np.asarray(c, float) for c in (layer.outline or layer.contours) if len(c) >= 3]
    if fill_holes <= 0 or len(polys) < 2:
        return polys
    inside = [[j for j, q in enumerate(polys) if j != i and geometry.point_in_polygon(p[0], q)]
              for i, p in enumerate(polys)]
    drop = {i for i, p in enumerate(polys)
            if len(inside[i]) % 2 == 1 and abs(geometry.area(p)) <= fill_holes}
    if not drop:
        return polys
    # also drop anything nested inside a filled hole (it lies in solid area now)
    return [p for i, p in enumerate(polys) if i not in drop and not any(k in drop for k in inside[i])]


def model_masks(layers, base: geometry.RegionMask, fill_holes: float = 0.0) -> list:
    out = []
    for layer in layers:
        rm = base.like()
        rm.fill(support_polys(layer, fill_holes))
        out.append(rm.grid)
    return out


def margin_cells(edge_margin: float, res: float, line_width: float = 0.45) -> int:
    """Cells to grow the support by so the printed support ends ``edge_margin`` mm past
    the model's edge.

    With no growth the support bead already reaches about a quarter line width
    past the edge (support lines stop a quarter width inside their cells, the
    bead adds half a width), so that is subtracted; the result is accurate to
    half a raster cell (~0.17 mm for a 0.45 mm line)."""
    if edge_margin <= 0:
        return 0
    return max(0, int(round((edge_margin - line_width * 0.25) / res)))


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


def _gap_free(s, masks, i, gap, grow):
    """Clear the top Z gap: no support within ``gap`` layers under the model (or its margin)."""
    n = len(masks)
    for k in range(1, gap + 1):
        if i + k < n and masks[i + k].any():
            s &= ~(geometry.dilate_round(masks[i + k], grow) if grow else masks[i + k])
    return s


def _with_margin(core, reach, grow, masks, i, xy, gap):
    """Grow existing support ``core`` by ``grow`` cells - only where the model above
    (``reach``) is within the margin, clear of the model's sides and of the Z gap.
    The margin never creates support on its own, it only widens real support so
    the perimeters along the model's edges (and around holes) sit fully on it."""
    if not grow or not core.any():
        return core
    s = geometry.dilate_round(core, grow) & geometry.dilate_round(reach, grow) & ~geometry.dilate(masks[i], xy)
    return _gap_free(s, masks, i, gap, grow) | core


def _bottom_gap(s, masks, i, bottom_gap, xy=0):
    """Keep ``bottom_gap`` empty layers between the model below and support standing on it.

    Applies within the XY distance of the model too, so a column next to the
    model's edge does not start early in the air beside it."""
    for k in range(1, bottom_gap + 1):
        if i - k >= 0 and masks[i - k].any():
            s &= ~(geometry.dilate(masks[i - k], xy) if xy else masks[i - k])
    return s


def auto_columns(masks, over, res: float, xy_distance: float, gap: int, everywhere: bool,
                 edge_margin: float = 0.0, line_width: float = 0.45, bottom_gap: int = 1) -> list:
    """Columns grown down from the overhangs.  ``edge_margin`` (mm) widens the
    support past the overhang's edges so its perimeters sit fully on support."""
    n = len(masks)
    xy = max(1, int(math.ceil(xy_distance / res)))
    grow = margin_cells(edge_margin, res, line_width)
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
            s = _bottom_gap(s, masks, i, bottom_gap, xy)    # gap on top of the model
        else:
            s &= ~below_any[i]               # build plate only: nothing of the model underneath
        if grow and s.any():
            s = _with_margin(s, acc, grow, masks, i, xy, gap)
            if everywhere:
                s = _bottom_gap(s, masks, i, bottom_gap, xy)
            else:
                s &= ~below_any[i]
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


def block_columns(masks, layers, base, blocks, xy_distance: float, gap: int,
                  edge_margin: float = 0.0, line_width: float = 0.45, bottom_gap: int = 1,
                  *, source_masks=None) -> list:
    """Support inside the block volumes wherever there is model above (with a Z gap).

    ``edge_margin`` (mm) widens that support past the model's edges (also into
    holes too large to fill) so the perimeters along every edge sit on support.
    """
    n = len(masks)
    xy = max(1, int(math.ceil(xy_distance / base.res)))
    grow = margin_cells(edge_margin, base.res, line_width)
    above = np.zeros_like(masks[0])
    sup = [None] * n
    for i in range(n - 1, -1, -1):
        j = i + 1 + gap
        if j < n:
            above |= masks[j] if source_masks is None else source_masks[j]
        mid_z = layers[i].z - layers[i].height * 0.5
        s = block_cells(base, blocks, mid_z) & above & ~geometry.dilate(masks[i], xy)
        s = _gap_free(s, masks, i, gap, 0)
        if grow and s.any():
            s = _with_margin(s, above, grow, masks, i, xy, gap)
        sup[i] = _bottom_gap(s, masks, i, bottom_gap, xy)  # gap on top of the model
    return sup


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


def tiled_blocks_from_columns(sup, layers, base, tile: float, gap: int = 1) -> list:
    """Cover the support with ``tile`` x ``tile`` blocks on a regular grid.

    Every grid square that contains support becomes one block, with its own
    height range (lowest to highest support layer inside it, up to the model).
    Uniform small blocks are easy to delete / resize one by one.
    """
    if not sup or tile <= 0:
        return []
    foot = np.zeros_like(sup[0])
    for s in sup:
        foot |= s
    if not foot.any():
        return []
    res = base.res
    rows, cols = np.nonzero(foot)
    x_start = base.lo[0] + cols.min() * res
    y_start = base.lo[1] + rows.min() * res
    ny, nx = foot.shape
    # tile index of every cell (by cell centre)
    tx = np.floor((base.lo[0] + (np.arange(nx) + 0.5) * res - x_start) / tile).astype(int)
    ty = np.floor((base.lo[1] + (np.arange(ny) + 0.5) * res - y_start) / tile).astype(int)
    first: dict = {}
    last: dict = {}
    for k, s in enumerate(sup):
        if not s.any():
            continue
        r, c = np.nonzero(s)
        for key in set(zip(tx[c].tolist(), ty[r].tolist())):
            first.setdefault(key, k)
            last[key] = k
    blocks = []
    for (i, j) in sorted(first, key=lambda t: (t[1], t[0])):
        lo_l, hi_l = layers[first[(i, j)]], layers[last[(i, j)]]
        x0 = x_start + i * tile
        y0 = y_start + j * tile
        z0 = max(0.0, lo_l.z - lo_l.height)
        z1 = hi_l.z + (gap + 1) * hi_l.height
        blocks.append(SupportBlock(x0, y0, z0, x0 + tile, y0 + tile, z1))
    return blocks


def slice_layers(mesh, layer_height: float, first_layer_height: float | None = None, *,
                 merge_shells=False, overlap_layers=None) -> list:
    """Every layer from the bed to the top of the mesh (empty ones included)."""
    from gcodeproducer.core.jobs.layer import Layer
    flh = first_layer_height or layer_height
    top = float(mesh.bounds[1][2])
    heights, planes = [], []
    z = flh
    while z <= top + 1e-6:
        h = flh if not heights else layer_height
        heights.append((round(z, 4), h))
        planes.append(z - h * 0.5)
        z += layer_height
    if merge_shells or overlap_layers is not None:
        from .shell_merge import slice_with_shell_check
        contours_by_layer = slice_with_shell_check(mesh, planes, merge_shells,
                                                  overlap_layers if overlap_layers is not None else [])
    else:
        contours_by_layer = geometry.slice_planes(mesh, planes)
    return [Layer(index=i, z=z, height=h, contours=list(contours), outline=list(contours))
            for i, ((z, h), contours) in enumerate(zip(heights, contours_by_layer))]


def generate_blocks(mesh, layer_height: float = 0.2, line_width: float = 0.45, angle: float = 50.0,
                    everywhere: bool = False, xy_distance: float = 0.8, gap: int = 1, bottom_gap: int = 1,
                    min_area: float = 1.0, first_layer_height: float | None = None,
                    block_size: float | None = None, fill_holes: float = 0.0,
                    edge_margin: float = 0.0, merge_shells: bool = False) -> list:
    """Automatic support for a placed mesh, returned as editable blocks.

    ``block_size`` tiles the support with blocks of that size; None gives one
    bounding block per support island.
    """
    layers = slice_layers(mesh, layer_height, first_layer_height, merge_shells=merge_shells)
    if len(layers) < 2:
        return []
    lo, hi = mesh.bounds
    base = make_grid(lo, hi, line_width, edge_margin)
    masks = model_masks(layers, base, fill_holes)
    over = overhangs(masks, layers, base.res, angle, min_area)
    sup = auto_columns(masks, over, base.res, xy_distance, gap, everywhere, edge_margin, line_width,
                       bottom_gap)
    if block_size:
        return tiled_blocks_from_columns(sup, layers, base, float(block_size), gap)
    return blocks_from_columns(sup, layers, base, gap)
