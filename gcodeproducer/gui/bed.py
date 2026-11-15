"""Build plate drawing shared by the Prepare and the Preview view.

Both views draw the same plate from the machine profile (bed / work area size,
origin and build height), so switching views never changes the dimensions:
a filled plate, a 10 mm grid (50 mm on very large beds), the plate outline and
the build-volume frame.
"""
from __future__ import annotations

import math

import numpy as np
from OpenGL import GL

DEFAULT_RECT = (0.0, 0.0, 220.0, 220.0, 250.0)


def bed_geometry(rect):
    """Vertex arrays (plate quad, grid lines, outline loop, volume lines) for ``rect``."""
    x0, y0, x1, y1, h = rect
    plate = np.array([[x0, y0, -0.02], [x1, y0, -0.02], [x1, y1, -0.02], [x0, y1, -0.02]], np.float32)
    outline = np.array([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0]], np.float32)
    step = 10.0 if max(x1 - x0, y1 - y0) <= 600 else 50.0
    pts = []
    for x in np.arange(math.ceil(x0 / step) * step, x1 + 1e-6, step):
        pts += [(x, y0, 0), (x, y1, 0)]
    for y in np.arange(math.ceil(y0 / step) * step, y1 + 1e-6, step):
        pts += [(x0, y, 0), (x1, y, 0)]
    grid = np.array(pts, np.float32).reshape(-1, 3)
    c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    vol = []
    for i in range(4):
        a, b = c[i], c[(i + 1) % 4]
        vol += [(a[0], a[1], h), (b[0], b[1], h), (a[0], a[1], 0), (a[0], a[1], h)]
    return plate, grid, outline, np.array(vol, np.float32)


class BedRenderer:
    """Owns the GL buffers of the plate; create it inside ``initializeGL``."""

    def __init__(self, mesh_cls):
        self.m_plate = mesh_cls(False)
        self.m_grid = mesh_cls(False)
        self.m_outline = mesh_cls(False)
        self.m_volume = mesh_cls(False)
        self.m_stock = mesh_cls(False)
        self.rect = None

    def upload(self, rect) -> None:
        self.rect = tuple(rect)
        plate, grid, outline, vol = bed_geometry(rect)
        self.m_plate.upload(plate)
        self.m_grid.upload(grid)
        self.m_outline.upload(outline)
        self.m_volume.upload(vol)

    def upload_stock(self, stock):
        points = []
        if stock is not None and stock.allocated:
            lo, hi = stock.bounds
            c = np.array([[x, y, z] for z in (lo[2], hi[2]) for y in (lo[1], hi[1]) for x in (lo[0], hi[0])])
            for a, b in ((0,1), (1,3), (3,2), (2,0), (4,5), (5,7), (7,6), (6,4), (0,4), (1,5), (2,6), (3,7)):
                points.extend((c[a], c[b]))
        self.m_stock.upload(np.asarray(points, np.float32).reshape(-1, 3))

    def draw_stock(self, prog, mvp):
        GL.glUseProgram(prog)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(prog, "uMVP"), 1, GL.GL_TRUE, mvp)
        GL.glUniform4f(GL.glGetUniformLocation(prog, "uColor"), 0.95, 0.65, 0.22, 1.0)
        self.m_stock.draw(GL.GL_LINES)

    def draw_plate(self, prog, mvp, alpha: float = 1.0) -> None:
        if self.rect is not None and self.rect[4] < 0:
            return   # CAM surface is Z0, not an opaque plate hiding the part below it
        GL.glUseProgram(prog)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(prog, "uMVP"), 1, GL.GL_TRUE, mvp)
        ucol = GL.glGetUniformLocation(prog, "uColor")
        if alpha < 1.0:
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glDepthMask(GL.GL_FALSE)
        GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
        GL.glPolygonOffset(1.0, 1.0)
        GL.glUniform4f(ucol, 0.19, 0.20, 0.23, alpha)
        self.m_plate.draw(GL.GL_TRIANGLE_FAN)
        GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)

    def draw_lines(self, prog, mvp, grid: bool = True) -> None:
        GL.glUseProgram(prog)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(prog, "uMVP"), 1, GL.GL_TRUE, mvp)
        ucol = GL.glGetUniformLocation(prog, "uColor")
        if grid:
            GL.glUniform4f(ucol, 0.29, 0.30, 0.34, 1.0)
            self.m_grid.draw(GL.GL_LINES)
        GL.glUniform4f(ucol, 0.55, 0.57, 0.62, 1.0)
        self.m_outline.draw(GL.GL_LINE_LOOP)
        GL.glUniform4f(ucol, 0.33, 0.35, 0.40, 1.0)
        self.m_volume.draw(GL.GL_LINES)
