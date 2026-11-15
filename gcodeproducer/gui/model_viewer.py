"""Placement view: the build plate with the (placed) model on it.

* left-drag on the model moves it across the bed (the GUI updates the placement)
* *place on face* mode: click a face and it is rotated onto the bed
* left-drag elsewhere orbits, right / middle drag pans, wheel zooms (same camera
  as the sliced preview, so switching views keeps the viewpoint)
* overhangs that need support are tinted red, a model outside the build volume
  is tinted orange
* manual support blocks are drawn as translucent green boxes: click one to
  select it (yellow), drag it to move it, Delete removes it
* *place blocks* mode: clicking the bed or the model places a block there
  (the GUI fills the vertical gap to the next face of the model)
* *remove blocks* mode: the block under the cursor turns red, clicking deletes it
"""
from __future__ import annotations

import math

import numpy as np
from OpenGL import GL
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QLabel

from ..core.geometry import ray_triangles
from ..core.placement import face_normals, overhang_faces
from . import shaders
from .bed import BedRenderer
from .camera import Camera, perspective
from .viewer import _compile, _Mesh, default_surface_format

MODEL_COLOR = (0.30, 0.58, 0.92)
OVERHANG_COLOR = (0.92, 0.30, 0.26)
OUTSIDE_COLOR = (0.95, 0.62, 0.20)
BLOCK_COLOR = (0.25, 0.85, 0.45)
BLOCK_SEL_COLOR = (1.0, 0.85, 0.2)
BLOCK_DEL_COLOR = (1.0, 0.25, 0.25)

_BOX_FACES = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 4, 5), (0, 5, 1),
              (1, 5, 6), (1, 6, 2), (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)]
_BOX_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]


def box_corners(b):
    return np.array([[b.x0, b.y0, b.z0], [b.x1, b.y0, b.z0], [b.x1, b.y1, b.z0], [b.x0, b.y1, b.z0],
                     [b.x0, b.y0, b.z1], [b.x1, b.y0, b.z1], [b.x1, b.y1, b.z1], [b.x0, b.y1, b.z1]], np.float32)


def ray_box(o, d, b):
    """Slab test: distance along the ray to the box, or inf."""
    lo = np.array([b.x0, b.y0, b.z0])
    hi = np.array([b.x1, b.y1, b.z1])
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = (lo - o) / d
        t2 = (hi - o) / d
    tmin = np.nanmax(np.minimum(t1, t2))
    tmax = np.nanmin(np.maximum(t1, t2))
    if tmax < max(tmin, 0.0):
        return math.inf
    return float(tmin if tmin > 0 else tmax)


class _TriMesh:
    """VAO with position(3) + normal(3) + colour(4)."""

    def __init__(self):
        import ctypes
        self.vao = GL.glGenVertexArrays(1)
        self.vbos = list(np.atleast_1d(GL.glGenBuffers(3)))
        self.count = 0
        GL.glBindVertexArray(self.vao)
        for loc, (vbo, size) in enumerate(zip(self.vbos, (3, 3, 4))):
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, 16, None, GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE, 0, ctypes.c_void_p(0))
        GL.glBindVertexArray(0)

    def upload(self, pos, normal, color):
        self.count = len(pos)
        for vbo, arr in zip(self.vbos, (pos, normal, color)):
            arr = np.ascontiguousarray(arr, np.float32)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, max(arr.nbytes, 16), arr if arr.nbytes else None,
                            GL.GL_DYNAMIC_DRAW)

    def upload_color(self, color):
        arr = np.ascontiguousarray(color, np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbos[2])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, max(arr.nbytes, 16), arr if arr.nbytes else None, GL.GL_DYNAMIC_DRAW)

    def draw(self):
        if self.count:
            GL.glBindVertexArray(self.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, self.count)


class ModelViewer(QOpenGLWidget):
    camPickRequested = pyqtSignal(object)
    camSelectionExited = pyqtSignal()
    moved = pyqtSignal(float, float)          # new model centre X, Y while dragging
    moveFinished = pyqtSignal()
    faceClicked = pyqtSignal(object)          # world-space normal of the clicked face
    blockPressed = pyqtSignal(int)            # a support block was clicked (selected)
    blockDragged = pyqtSignal(int, float, float)   # block index, total dX, dY since the press
    blockReleased = pyqtSignal(int)
    blockDeleteRequested = pyqtSignal(int)
    placeBlockClicked = pyqtSignal(float, float, float, bool)   # x, y, z, clicked face points down
    placeModeExited = pyqtSignal()
    glError = pyqtSignal(str)

    def __init__(self, camera: Camera, parent=None):
        super().__init__(parent)
        self.setFormat(default_surface_format())
        self.camera = camera
        self.vertices = None                  # placed mesh
        self.triangles = None
        self.tris = None                      # (m,3,3) for picking
        self.rect = (0.0, 0.0, 220.0, 220.0, 250.0)
        self.overhang_angle = None            # None = do not show overhangs
        self.inside = True
        self.center_xy = (0.0, 0.0)
        self.cam_pick_mode = ""
        self.cam_faces = []
        self.cam_edges = np.empty((0, 3))
        self._cam_dirty = True
        self.place_on_face = False
        self.blocks = []                      # core.support.SupportBlock
        self.sel_block = -1
        self.show_blocks = False
        self.place_block = False
        self.remove_block = False
        self.hover_block = -1
        self._bdrag = None                    # (index, plane z, start point)
        self._ready = False
        self._dirty = True
        self._drag = None                     # (plane z, start point, start centre)
        self._last = QPoint()
        self._buttons = Qt.MouseButton.NoButton
        self._highlight = False
        self.setMinimumSize(200, 150)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.info = QLabel("", self)
        self.info.setStyleSheet("color:#ddd;background:rgba(0,0,0,120);padding:3px 8px;border-radius:3px;")
        self.info.move(8, 8)
        self.warn = QLabel("", self)
        self.warn.setStyleSheet("color:#111;background:rgba(245,160,50,230);padding:3px 8px;border-radius:3px;")
        self.warn.setVisible(False)
        camera.changed.connect(self.update)
        self._update_info()

    # ----------------------------------------------------------------- API
    def set_scene(self, mesh, rect, center_xy, overhang_angle=None, inside=True):
        self.vertices = None if mesh is None else np.asarray(mesh.vertices, np.float64)
        self.triangles = None if mesh is None else np.asarray(mesh.triangles)
        self.tris = None if mesh is None else self.vertices[self.triangles]
        self.rect = rect
        self.center_xy = center_xy
        self.overhang_angle = overhang_angle
        self.inside = inside
        self._dirty = True
        self._update_info()
        self.update()

    def set_cam_mode(self, mode):
        self.cam_pick_mode = mode
        self._tool_cursor()
        self._update_info()

    def set_cam_selection(self, faces=(), edges=()):
        self.cam_faces = list(faces)
        self.cam_edges = np.asarray(edges, dtype=float).reshape(-1, 3)
        self._cam_dirty = True
        self._dirty = True
        self.update()

    def set_blocks(self, blocks, selected: int = -1, visible: bool = True):
        self.blocks = list(blocks)
        self.sel_block = selected
        self.show_blocks = visible
        if self.hover_block >= len(self.blocks):
            self.hover_block = -1
        self._blocks_dirty = True
        self.update()

    def set_place_on_face(self, on: bool):
        self.place_on_face = on
        self._tool_cursor()
        self._update_info()

    def _tool_cursor(self):
        tool = self.cam_pick_mode or self.place_on_face or self.place_block or self.remove_block
        self.setCursor(Qt.CursorShape.CrossCursor if tool else Qt.CursorShape.ArrowCursor)

    def set_place_block(self, on: bool):
        self.place_block = on
        self._tool_cursor()
        self._update_info()

    def set_remove_block(self, on: bool):
        self.remove_block = on
        self.hover_block = -1
        self._tool_cursor()
        self._update_info()
        self.update()

    def fit(self, whole_bed: bool = False):
        """Frame the model with some bed around it (or the whole bed)."""
        x0, y0, x1, y1, h = self.rect
        if self.vertices is not None and len(self.vertices) and not whole_bed:
            lo, hi = self.vertices.min(axis=0), self.vertices.max(axis=0)
            pad = max(float(np.max(hi - lo)) * 0.6, 25.0)
            lo = np.array([lo[0] - pad, lo[1] - pad, 0.0])
            hi = np.array([hi[0] + pad, hi[1] + pad, hi[2]])
        else:
            lo, hi = np.array([x0, y0, 0.0]), np.array([x1, y1, min(h, 50.0)])
        self.camera.fit(lo, hi)

    def _update_info(self):
        if self.vertices is None:
            txt = "Import a model (Ctrl+O) or drop an STL here"
        elif self.cam_pick_mode:
            txt = f"CAM: select {self.cam_pick_mode}s • Shift-drag to pan, drag to orbit • Esc = navigate"
        elif self.place_on_face:
            txt = "Click a face of the model to place it on the bed  (Esc = cancel)"
        elif self.place_block:
            txt = "Click the bed or the model to place a support block  •  Esc = done"
        elif self.remove_block:
            txt = "Click a support block to remove it  •  Esc = done"
        else:
            txt = "Drag the model to move it  \u2022  drag elsewhere to orbit, right-drag to pan"
        self.info.setText(txt)
        self.info.adjustSize()
        out = self.vertices is not None and not self.inside
        self.warn.setText("Model is outside the build volume")
        self.warn.adjustSize()
        self.warn.move(8, 8 + self.info.height() + 6)
        self.warn.setVisible(out)

    # ---------------------------------------------------------------- GL
    def initializeGL(self):
        try:
            self.p_mesh = _compile({GL.GL_VERTEX_SHADER: shaders.MESH_VS, GL.GL_FRAGMENT_SHADER: shaders.MESH_FS})
            self.p_flat = _compile({GL.GL_VERTEX_SHADER: shaders.FLAT_VS, GL.GL_FRAGMENT_SHADER: shaders.FLAT_FS})
        except Exception as exc:  # pragma: no cover
            self.glError.emit(f"OpenGL shader error: {exc}")
            return
        self.m_model = _TriMesh()
        self.m_cam_edges = _Mesh(False)
        self.bed = BedRenderer(_Mesh)
        self.m_bfaces = _Mesh(False)
        self.m_bedges = _Mesh(False)
        self._blocks_dirty = True
        self.m_axes = _Mesh(False)
        self.m_axes.upload(np.array([[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 1, 0], [0, 0, 0], [0, 0, 1]], np.float32))
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_MULTISAMPLE)
        self._ready = True
        self._dirty = True

    def _upload(self):
        self._dirty = False
        self.bed.upload(self.rect)
        if self.vertices is None:
            self.m_model.count = 0
            return
        n, _ = face_normals(self.vertices, self.triangles)
        pos = self.tris.reshape(-1, 3)
        nrm = np.repeat(n, 3, axis=0)
        self.m_model.upload(pos, nrm, self._colors())

    def _colors(self):
        m = len(self.triangles)
        col = np.empty((m, 4), np.float32)
        col[:, :3] = MODEL_COLOR if self.inside else OUTSIDE_COLOR
        col[:, 3] = 1.0
        if self.overhang_angle is not None:
            col[overhang_faces(self.vertices, self.triangles, self.overhang_angle), :3] = OVERHANG_COLOR
        if self.cam_faces:
            indices = [i for i in self.cam_faces if 0 <= i < m]
            col[indices, :3] = (1.0, 0.78, 0.15)
        return np.repeat(col, 3, axis=0)

    def paintGL(self):
        GL.glClearColor(0.13, 0.14, 0.16, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        if not self._ready:
            return
        if self._dirty:
            self._upload()
        dpr = self.devicePixelRatioF()
        w, h = int(self.width() * dpr), int(self.height() * dpr)
        GL.glViewport(0, 0, w, h)
        cam = self.camera
        mvp = (cam.proj_matrix(w / max(h, 1)) @ cam.view_matrix()).astype(np.float32)

        below = cam.eye()[2] < 0.0          # looking from under the bed: make it see-through
        if not below:
            self._draw_bed(mvp, 1.0)
        self._draw_lines(mvp)
        if self.m_model.count:
            p = self.p_mesh
            GL.glUseProgram(p)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(p, "uMVP"), 1, GL.GL_TRUE, mvp)
            GL.glUniform3fv(GL.glGetUniformLocation(p, "uEye"), 1, cam.eye().astype(np.float32))
            GL.glUniform3fv(GL.glGetUniformLocation(p, "uViewDir"), 1, cam.view_dir().astype(np.float32))
            GL.glUniform1i(GL.glGetUniformLocation(p, "uOrtho"), int(cam.ortho))
            GL.glUniform1f(GL.glGetUniformLocation(p, "uHighlight"), 0.12 if self._highlight else 0.0)
            vm = cam.view_matrix()
            right, up, back = vm[0, :3], vm[1, :3], vm[2, :3]
            key = -0.45 * right + 0.75 * up + 0.50 * back      # upper left, in front
            key = (key / np.linalg.norm(key)).astype(np.float32)
            GL.glUniform3fv(GL.glGetUniformLocation(p, "uKey"), 1, key)
            self.m_model.draw()
        if below:
            self._draw_bed(mvp, 0.45)
        if self.show_blocks and self.blocks:
            self._draw_blocks(mvp)
        if len(self.cam_edges):
            if self._cam_dirty:
                self.m_cam_edges.upload(self.cam_edges)
                self._cam_dirty = False
            GL.glUseProgram(self.p_flat)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
            GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), 1.0, 0.78, 0.15, 1.0)
            GL.glDisable(GL.GL_DEPTH_TEST)
            self.m_cam_edges.draw(GL.GL_LINES)
            GL.glEnable(GL.GL_DEPTH_TEST)
        self._draw_axes(w, h)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)

    def _draw_blocks(self, mvp):
        if self._blocks_dirty:
            self._blocks_dirty = False
            faces, edges = [], []
            for b in self.blocks:
                c = box_corners(b)
                faces.append(c[np.array(_BOX_FACES).ravel()])
                edges.append(c[np.array(_BOX_EDGES).ravel()])
            self.m_bfaces.upload(np.concatenate(faces) if faces else np.zeros((0, 3), np.float32))
            self.m_bedges.upload(np.concatenate(edges) if edges else np.zeros((0, 3), np.float32))
        GL.glUseProgram(self.p_flat)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
        ucol = GL.glGetUniformLocation(self.p_flat, "uColor")
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDepthMask(GL.GL_FALSE)
        nf, ne = len(_BOX_FACES) * 3, len(_BOX_EDGES) * 2
        for k in range(len(self.blocks)):
            col = self._block_color(k)
            GL.glUniform4f(ucol, *col, 0.30 if col != BLOCK_COLOR else 0.20)
            GL.glBindVertexArray(self.m_bfaces.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, k * nf, nf)
        GL.glBindVertexArray(self.m_bedges.vao)
        for depth, alpha in ((False, 0.35), (True, 1.0)):     # hidden edges faint, visible edges solid
            (GL.glEnable if depth else GL.glDisable)(GL.GL_DEPTH_TEST)
            for k in range(len(self.blocks)):
                GL.glUniform4f(ucol, *self._block_color(k), alpha)
                GL.glDrawArrays(GL.GL_LINES, k * ne, ne)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)

    def _block_color(self, k):
        if self.remove_block and k == self.hover_block:
            return BLOCK_DEL_COLOR
        return BLOCK_SEL_COLOR if k == self.sel_block else BLOCK_COLOR

    def pick_block(self, mx, my):
        """(index, distance, point) of the nearest support block under the mouse."""
        if not (self.show_blocks and self.blocks):
            return -1, math.inf, None
        o, d = self.ray(mx, my)
        best, bt = -1, math.inf
        for k, b in enumerate(self.blocks):
            t = ray_box(o, d, b)
            if t < bt:
                best, bt = k, t
        return best, bt, (o + d * bt if best >= 0 else None)

    def _draw_bed(self, mvp, alpha):
        self.bed.draw_plate(self.p_flat, mvp, alpha)

    def _draw_lines(self, mvp):
        self.bed.draw_lines(self.p_flat, mvp)

    def _draw_axes(self, w, h):
        size = int(90 * self.devicePixelRatioF())
        GL.glViewport(0, 0, size, size)
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)
        v = self.camera.view_matrix().copy()
        v[:3, 3] = (0, 0, -3.0)
        mvp = (perspective(30, 1.0, 0.1, 10) @ v).astype(np.float32)
        GL.glUseProgram(self.p_flat)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
        GL.glBindVertexArray(self.m_axes.vao)
        for k, col in enumerate(((1, 0.3, 0.3), (0.3, 1, 0.3), (0.4, 0.5, 1))):
            GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *col, 1.0)
            GL.glDrawArrays(GL.GL_LINES, k * 2, 2)
        GL.glViewport(0, 0, w, h)

    # ------------------------------------------------------------- picking
    def ray(self, mx: float, my: float):
        w, h = max(1, self.width()), max(1, self.height())
        m = (self.camera.proj_matrix(w / h) @ self.camera.view_matrix()).astype(np.float64)
        inv = np.linalg.inv(m)
        x, y = 2.0 * mx / w - 1.0, 1.0 - 2.0 * my / h
        a = inv @ np.array([x, y, -1.0, 1.0])
        b = inv @ np.array([x, y, 1.0, 1.0])
        a, b = a[:3] / a[3], b[:3] / b[3]
        d = b - a
        return a, d / np.linalg.norm(d)

    def pick(self, mx, my):
        """(point, triangle index) of the model under the mouse, or (None, -1)."""
        if self.tris is None:
            return None, -1
        o, d = self.ray(mx, my)
        t, i = ray_triangles(o, d, self.tris)
        if i < 0:
            return None, -1
        return o + d * t, i

    def _plane_point(self, mx, my, z):
        o, d = self.ray(mx, my)
        if abs(d[2]) < 1e-9:
            return None
        t = (z - o[2]) / d[2]
        return None if t < 0 else o + d * t

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, ev):
        self._last = ev.position().toPoint()
        self._buttons = ev.buttons()
        if ev.button() != Qt.MouseButton.LeftButton or ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return
        mx, my = ev.position().x(), ev.position().y()
        if self.cam_pick_mode:
            self._cam_press = (mx, my)
            return
        if self.remove_block:
            bi = self.pick_block(mx, my)[0]
            if bi >= 0:
                self.hover_block = -1
                self.blockDeleteRequested.emit(bi)
            return                                   # a miss just orbits
        pt, tri = self.pick(mx, my)
        if self.place_block:
            if tri >= 0:
                n, _ = face_normals(self.vertices, self.triangles[tri:tri + 1])
                self.placeBlockClicked.emit(float(pt[0]), float(pt[1]), float(pt[2]), bool(n[0][2] < -0.1))
                return
            o, _d = self.ray(mx, my)
            p = self._plane_point(mx, my, 0.0) if o[2] > 0 else None
            if p is not None:
                self.placeBlockClicked.emit(float(p[0]), float(p[1]), 0.0, False)
                return
            return                                   # missed everything: plain orbit
        if not self.place_on_face:
            bi, bt, bpt = self.pick_block(mx, my)
            mt = np.linalg.norm(pt - self.ray(mx, my)[0]) if pt is not None else math.inf
            if bi >= 0 and bt <= mt + 1e-6:
                self.blockPressed.emit(bi)
                self._bdrag = (bi, float(bpt[2]), bpt)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        if tri < 0:
            return
        if self.place_on_face:
            n, _ = face_normals(self.vertices, self.triangles[tri:tri + 1])
            self.faceClicked.emit(n[0])
            return
        self._drag = (float(pt[2]), pt, tuple(self.center_xy))
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        if self._bdrag is not None:
            bi, z, start = self._bdrag
            p = self._plane_point(ev.position().x(), ev.position().y(), z)
            if p is not None:
                self.blockDragged.emit(bi, float(p[0] - start[0]), float(p[1] - start[1]))
            self._last = pos
            return
        if self._drag is not None:
            z, start, (cx, cy) = self._drag
            p = self._plane_point(ev.position().x(), ev.position().y(), z)
            if p is not None:
                self.moved.emit(cx + p[0] - start[0], cy + p[1] - start[1])
            self._last = pos
            return
        dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
        self._last = pos
        b = ev.buttons()
        if b & Qt.MouseButton.LeftButton and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.camera.orbit(dx, dy)
        elif b & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton) or \
                (b & Qt.MouseButton.LeftButton and ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.camera.pan(dx, dy, self.height())
        elif not b and self.remove_block:
            hb = self.pick_block(ev.position().x(), ev.position().y())[0]
            if hb != self.hover_block:
                self.hover_block = hb
                self.update()
        elif not b and self.tris is not None:
            over = self.pick(ev.position().x(), ev.position().y())[1] >= 0
            if over != self._highlight:
                self._highlight = over
                if not (self.cam_pick_mode or self.place_on_face or self.place_block):
                    self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, ev):
        if self.cam_pick_mode and ev.button() == Qt.MouseButton.LeftButton:
            xy = (ev.position().x(), ev.position().y())
            start = getattr(self, "_cam_press", None)
            self._cam_press = None
            if start is not None and np.linalg.norm(np.subtract(xy, start)) < 4:
                origin, direction = self.ray(*xy)
                mvp = self.camera.proj_matrix(self.width() / max(1, self.height())) @ self.camera.view_matrix()
                self.camPickRequested.emit((self.cam_pick_mode, origin, direction, mvp,
                                            (self.width(), self.height()), xy))
            return
        if self._bdrag is not None:
            bi = self._bdrag[0]
            self._bdrag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.blockReleased.emit(bi)
            return
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._highlight else Qt.CursorShape.ArrowCursor)
            self.moveFinished.emit()

    def wheelEvent(self, ev):
        self.camera.zoom(ev.angleDelta().y() / 120.0)

    def keyPressEvent(self, ev):
        k = ev.key()
        views = {Qt.Key.Key_1: "iso", Qt.Key.Key_2: "top", Qt.Key.Key_3: "front", Qt.Key.Key_4: "right"}
        if k == Qt.Key.Key_F:
            self.fit()
        elif k in views:
            self.camera.set_view(views[k])
        elif k == Qt.Key.Key_Escape and self.cam_pick_mode:
            self.set_cam_mode("")
            self.camSelectionExited.emit()
        elif k == Qt.Key.Key_Escape and self.place_on_face:
            self.faceClicked.emit(None)
        elif k == Qt.Key.Key_Escape and (self.place_block or self.remove_block):
            self.placeModeExited.emit()
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.show_blocks and self.sel_block >= 0:
            self.blockDeleteRequested.emit(self.sel_block)
        else:
            super().keyPressEvent(ev)
