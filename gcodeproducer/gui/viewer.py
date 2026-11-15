"""OpenGL tool path viewer widget."""
from __future__ import annotations

import ctypes
import math

import numpy as np
from OpenGL import GL
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QLabel

from ..core.workflow import FDM
from ..core.toolpath import RETRACT, SOLID_KINDS, Toolpath
from . import shaders
from .bed import BedRenderer
from .camera import Camera
from .view_state import ViewState


def default_surface_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    return fmt


def _compile(sources: dict) -> int:
    prog = GL.glCreateProgram()
    objs = []
    for stype, src in sources.items():
        sh = GL.glCreateShader(stype)
        GL.glShaderSource(sh, src)
        GL.glCompileShader(sh)
        if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
            raise RuntimeError(GL.glGetShaderInfoLog(sh).decode(errors="replace"))
        GL.glAttachShader(prog, sh)
        objs.append(sh)
    GL.glLinkProgram(prog)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        raise RuntimeError(GL.glGetProgramInfoLog(prog).decode(errors="replace"))
    for sh in objs:
        GL.glDeleteShader(sh)
    return prog


class _Mesh:
    """VAO with position(3) [+ info(2) + colour(4)] float attributes."""

    def __init__(self, with_attrs: bool = True):
        self.vao = GL.glGenVertexArrays(1)
        self.count = 0
        self.with_attrs = with_attrs
        n = 3 if with_attrs else 1
        self.vbos = list(np.atleast_1d(GL.glGenBuffers(n)))
        GL.glBindVertexArray(self.vao)
        sizes = (3, 2, 4) if with_attrs else (3,)
        for loc, (vbo, size) in enumerate(zip(self.vbos, sizes)):
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, 16, None, GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE, 0, ctypes.c_void_p(0))
        GL.glBindVertexArray(0)

    def upload(self, pos, info=None, color=None):
        self.count = len(pos)
        arrays = [pos, info, color] if self.with_attrs else [pos]
        for vbo, arr in zip(self.vbos, arrays):
            if arr is None:
                continue
            arr = np.ascontiguousarray(arr, np.float32)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, max(arr.nbytes, 16), arr if arr.nbytes else None,
                            GL.GL_DYNAMIC_DRAW)

    def upload_color(self, color):
        arr = np.ascontiguousarray(color, np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbos[2])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, max(arr.nbytes, 16), arr if arr.nbytes else None, GL.GL_DYNAMIC_DRAW)

    def draw(self, mode):
        if self.count:
            GL.glBindVertexArray(self.vao)
            GL.glDrawArrays(mode, 0, self.count)

    def delete(self):
        GL.glDeleteVertexArrays(1, [self.vao])
        GL.glDeleteBuffers(len(self.vbos), self.vbos)


def _pairs(a0, a1):
    out = np.empty((len(a0) * 2,) + a0.shape[1:], np.float32)
    out[0::2] = a0
    out[1::2] = a1
    return out


class GCodeViewer(QOpenGLWidget):
    lineSelected = pyqtSignal(int)
    glError = pyqtSignal(str)

    def __init__(self, camera: Camera, state: ViewState, title: str = "", parent=None):
        super().__init__(parent)
        self.setFormat(default_surface_format())
        self.camera = camera
        self.state = state
        self.stock = None
        self.bed_rect = None            # machine plate; None = grid around the tool path
        self.tp: Toolpath | None = None
        self.cursor = 1 << 30
        self.selected = -1
        self._geom_dirty = False
        self._color_dirty = False
        self._ready = False
        self._last = QPoint()
        self._buttons = Qt.MouseButton.NoButton
        self.setMinimumSize(200, 150)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.title = QLabel(title, self)
        self.title.setStyleSheet("color:#ddd;background:rgba(0,0,0,110);padding:2px 6px;border-radius:3px;")
        self.title.move(6, 6)
        self.title.setVisible(bool(title))
        self.info = QLabel("", self)
        self.info.setStyleSheet("color:#ccc;background:rgba(0,0,0,90);padding:2px 6px;border-radius:3px;")
        self.info.setVisible(False)
        camera.changed.connect(self.update)
        state.changed.connect(self._on_state)

    # ----------------------------------------------------------------- API
    def set_title(self, text: str) -> None:
        self.title.setText(text)
        self.title.adjustSize()
        self.title.setVisible(bool(text))

    def set_info(self, text: str) -> None:
        self.info.setText(text)
        self.info.adjustSize()
        self.info.move(6, self.height() - self.info.height() - 6)
        self.info.setVisible(bool(text))

    def set_stock(self, stock):
        self.stock = stock
        self._bed_dirty = True
        self.update()

    def set_bed(self, rect) -> None:
        """Machine plate (x0, y0, x1, y1, height) - the same plate the Prepare view shows."""
        rect = tuple(float(v) for v in rect) if rect is not None else None
        if rect != self.bed_rect:
            self.bed_rect = rect
            self._bed_dirty = True
            self.update()

    def set_toolpath(self, tp: Toolpath | None) -> None:
        self.tp = tp
        self._geom_dirty = True
        self.update()

    def set_cursor(self, line: int) -> None:
        self.cursor = line
        self.update()

    def set_selected(self, line: int) -> None:
        self.selected = line
        self.update()

    def _on_state(self, what: str) -> None:
        if what == "colors":
            self._color_dirty = True
        self.update()

    # ------------------------------------------------------------- GL setup
    def initializeGL(self) -> None:
        try:
            self.p_tube = _compile({GL.GL_VERTEX_SHADER: shaders.SEG_VS, GL.GL_GEOMETRY_SHADER: shaders.TUBE_GS,
                                    GL.GL_FRAGMENT_SHADER: shaders.TUBE_FS})
            self.p_line = _compile({GL.GL_VERTEX_SHADER: shaders.SEG_VS, GL.GL_FRAGMENT_SHADER: shaders.LINE_FS})
            self.p_point = _compile({GL.GL_VERTEX_SHADER: shaders.SEG_VS, GL.GL_FRAGMENT_SHADER: shaders.POINT_FS})
            self.p_flat = _compile({GL.GL_VERTEX_SHADER: shaders.FLAT_VS, GL.GL_FRAGMENT_SHADER: shaders.FLAT_FS})
        except Exception as exc:  # pragma: no cover
            self.glError.emit(f"OpenGL shader error: {exc}")
            return
        self.m_solid = _Mesh()
        self.m_thin = _Mesh()
        self.m_events = _Mesh()
        self.m_tool = _Mesh()
        self.m_grid = _Mesh(False)
        self.bed = BedRenderer(_Mesh)
        self._bed_dirty = True
        self.m_plane = _Mesh(False)
        self.m_axes = _Mesh(False)
        self.m_axes.upload(np.array([[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 1, 0], [0, 0, 0], [0, 0, 1]], np.float32))
        self._uniforms = {}
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_PROGRAM_POINT_SIZE)
        GL.glEnable(GL.GL_MULTISAMPLE)
        self._ready = True
        self._geom_dirty = True

    def _u(self, prog, name):
        key = (prog, name)
        loc = self._uniforms.get(key)
        if loc is None:
            loc = GL.glGetUniformLocation(prog, name)
            self._uniforms[key] = loc
        return loc

    def _upload_geometry(self) -> None:
        tp = self.tp
        self._geom_dirty = False
        self._color_dirty = True
        if tp is None or len(tp.kind) == 0:
            for m in (self.m_solid, self.m_thin, self.m_events, self.m_grid):
                m.count = 0
            return
        solid = np.isin(tp.kind, SOLID_KINDS)
        self._solid_idx = np.nonzero(solid)[0]
        self._thin_idx = np.nonzero(~solid)[0]
        info = np.stack([tp.line, tp.layer], axis=1).astype(np.float32)
        for mesh, idx in ((self.m_solid, self._solid_idx), (self.m_thin, self._thin_idx)):
            mesh.upload(_pairs(tp.p0[idx], tp.p1[idx]), _pairs(info[idx], info[idx]), None)
        ecol = np.zeros((len(tp.ev_kind), 4), np.float32)
        ecol[:, 3] = 1
        ecol[tp.ev_kind == RETRACT, :3] = (1.0, 0.2, 0.25)
        ecol[tp.ev_kind != RETRACT, :3] = (0.2, 1.0, 0.35)
        self._ecol = ecol
        self.m_events.upload(tp.ev_pos, np.stack([tp.ev_line, tp.ev_layer], axis=1), ecol)
        # build grid
        lo, hi = tp.bounds()
        step = 10.0
        span = max(hi[0] - lo[0], hi[1] - lo[1])
        if span > 400:
            step = 50.0
        elif span < 40:
            step = 5.0
        x0 = math.floor(min(lo[0], 0) / step) * step - step
        x1 = math.ceil(hi[0] / step) * step + step
        y0 = math.floor(min(lo[1], 0) / step) * step - step
        y1 = math.ceil(hi[1] / step) * step + step
        gz = min(0.0, float(lo[2])) if tp.machine == FDM else float(lo[2])
        pts = []
        for x in np.arange(x0, x1 + 1e-6, step):
            pts += [(x, y0, gz), (x, y1, gz)]
        for y in np.arange(y0, y1 + 1e-6, step):
            pts += [(x0, y, gz), (x1, y, gz)]
        self.m_grid.upload(np.array(pts, np.float32))
        self._bounds = (lo, hi)

    def _upload_colors(self) -> None:
        self._color_dirty = False
        tp = self.tp
        if tp is None or len(tp.kind) == 0:
            return
        col = self.state.segment_colors(tp)
        self.m_solid.upload_color(_pairs(col[self._solid_idx], col[self._solid_idx]))
        self.m_thin.upload_color(_pairs(col[self._thin_idx], col[self._thin_idx]))
        ecol = self._ecol.copy()
        ecol[:, 3] = 1.0 if self.state.show_retracts else 0.0
        self.m_events.upload_color(ecol)

    # ---------------------------------------------------------------- paint
    def _set_common(self, prog, mvp):
        st = self.state
        GL.glUseProgram(prog)
        GL.glUniformMatrix4fv(self._u(prog, "uMVP"), 1, GL.GL_TRUE, mvp)
        GL.glUniform1f(self._u(prog, "uCursor"), float(self.cursor))
        GL.glUniform1f(self._u(prog, "uSel"), float(self.selected))
        GL.glUniform1f(self._u(prog, "uLayerMin"), float(st.layer_min))
        GL.glUniform1f(self._u(prog, "uLayerMax"), float(st.layer_max))
        GL.glUniform1i(self._u(prog, "uDim"), int(st.dim_lower))
        GL.glUniform1i(self._u(prog, "uNoFilter"), 0)
        GL.glUniform1i(self._u(prog, "uClipOn"), int(st.section))
        GL.glUniform4fv(self._u(prog, "uClip"), 1, st.section_plane())
        GL.glUniform1f(self._u(prog, "uSlab"), float(st.section_slab))

    def paintGL(self) -> None:
        GL.glClearColor(0.13, 0.14, 0.16, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        if not self._ready:
            return
        if self._geom_dirty:
            self._upload_geometry()
        if self._color_dirty:
            self._upload_colors()
        dpr = self.devicePixelRatioF()
        w, h = int(self.width() * dpr), int(self.height() * dpr)
        GL.glViewport(0, 0, w, h)
        cam = self.camera
        mvp = (cam.proj_matrix(w / max(h, 1)) @ cam.view_matrix()).astype(np.float32)
        st = self.state
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_TRUE)

        if self._bed_dirty and self.bed_rect is not None:
            self._bed_dirty = False
            self.bed.upload(self.bed_rect)
            self.bed.upload_stock(self.stock)
        below = cam.eye()[2] < 0.0
        if self.bed_rect is not None:
            # the machine's plate, exactly as in the Prepare view
            if not below:
                self.bed.draw_plate(self.p_flat, mvp, 1.0)
            self.bed.draw_lines(self.p_flat, mvp, grid=st.show_grid)
            self.bed.draw_stock(self.p_flat, mvp)
        # grid around the tool path (only when no machine plate is known)
        elif st.show_grid and self.m_grid.count:
            GL.glUseProgram(self.p_flat)
            GL.glUniformMatrix4fv(self._u(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
            GL.glUniform4f(self._u(self.p_flat, "uColor"), 0.28, 0.29, 0.32, 1.0)
            self.m_grid.draw(GL.GL_LINES)

        if self.tp is not None:
            # solid tubes
            self._set_common(self.p_tube, mvp)
            p = self.p_tube
            GL.glUniform3fv(self._u(p, "uEye"), 1, cam.eye().astype(np.float32))
            GL.glUniform3fv(self._u(p, "uViewDir"), 1, cam.view_dir().astype(np.float32))
            GL.glUniform1i(self._u(p, "uOrtho"), int(cam.ortho))
            GL.glUniform1f(self._u(p, "uHalfW"), float(st.width) * 0.5)
            self.m_solid.draw(GL.GL_LINES)
            # thin lines (travel / rapid)
            self._set_common(self.p_line, mvp)
            GL.glUniform1f(self._u(self.p_line, "uAlpha"), 1.0)
            self.m_thin.draw(GL.GL_LINES)
            # retract / unretract points
            if st.show_retracts:
                self._set_common(self.p_point, mvp)
                GL.glUniform1f(self._u(self.p_point, "uPointSize"), 6.0 * self.devicePixelRatioF())
                GL.glUniform1i(self._u(self.p_point, "uNoClip"), 0)
                self.m_events.draw(GL.GL_POINTS)
            # tool head
            if st.show_tool and 0 <= self.cursor < len(self.tp.line_pos):
                pos = self.tp.line_pos[self.cursor][None, :]
                self.m_tool.upload(pos, np.zeros((1, 2), np.float32), np.array([[0.1, 1.0, 1.0, 1.0]], np.float32))
                self._set_common(self.p_point, mvp)
                GL.glUniform1i(self._u(self.p_point, "uNoFilter"), 1)
                GL.glUniform1i(self._u(self.p_point, "uNoClip"), 1)
                GL.glUniform1f(self._u(self.p_point, "uPointSize"), 14.0 * self.devicePixelRatioF())
                GL.glDisable(GL.GL_DEPTH_TEST)
                self.m_tool.draw(GL.GL_POINTS)
                GL.glEnable(GL.GL_DEPTH_TEST)

            # section plane
            if st.section and st.section_show_plane:
                self._draw_plane(mvp)

        if self.bed_rect is not None and below:
            self.bed.draw_plate(self.p_flat, mvp, 0.45)      # see-through from below

        self._draw_axes(w, h)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)

    def _draw_plane(self, mvp):
        lo, hi = self._bounds
        c = (lo + hi) / 2
        size = float(np.linalg.norm(hi - lo)) * 0.6 + 5
        plane = self.state.section_plane()
        n = plane[:3].astype(np.float64)
        d = float(plane[3])
        center = c - n * (np.dot(n, c) - d)
        a = np.cross(n, [0, 0, 1.0])
        if np.linalg.norm(a) < 1e-6:
            a = np.array([1.0, 0, 0])
        a /= np.linalg.norm(a)
        b = np.cross(n, a)
        pts = np.array([center + (-a - b) * size, center + (a - b) * size,
                        center + (a + b) * size, center + (-a + b) * size], np.float32)
        self.m_plane.upload(pts)
        GL.glUseProgram(self.p_flat)
        GL.glUniformMatrix4fv(self._u(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glUniform4f(self._u(self.p_flat, "uColor"), 0.3, 0.7, 1.0, 0.12)
        self.m_plane.draw(GL.GL_TRIANGLE_FAN)
        GL.glUniform4f(self._u(self.p_flat, "uColor"), 0.4, 0.8, 1.0, 0.6)
        self.m_plane.draw(GL.GL_LINE_LOOP)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)

    def _draw_axes(self, w, h):
        size = int(90 * self.devicePixelRatioF())
        GL.glViewport(0, 0, size, size)
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)
        v = self.camera.view_matrix().copy()
        v[:3, 3] = (0, 0, -3.0)
        from .camera import perspective
        mvp = (perspective(30, 1.0, 0.1, 10) @ v).astype(np.float32)
        GL.glUseProgram(self.p_flat)
        GL.glUniformMatrix4fv(self._u(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
        GL.glBindVertexArray(self.m_axes.vao)
        for k, col in enumerate(((1, 0.3, 0.3), (0.3, 1, 0.3), (0.4, 0.5, 1))):
            GL.glUniform4f(self._u(self.p_flat, "uColor"), *col, 1.0)
            GL.glDrawArrays(GL.GL_LINES, k * 2, 2)
        GL.glViewport(0, 0, w, h)

    def resizeGL(self, w, h):
        if self.info.isVisible():
            self.info.move(6, self.height() - self.info.height() - 6)

    # ---------------------------------------------------------------- input
    def mousePressEvent(self, ev):
        self._last = ev.position().toPoint()
        self._buttons = ev.buttons()

    def mouseMoveEvent(self, ev):
        p = ev.position().toPoint()
        dx, dy = p.x() - self._last.x(), p.y() - self._last.y()
        self._last = p
        b = ev.buttons()
        shift = ev.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if b & Qt.MouseButton.LeftButton and not shift:
            self.camera.orbit(dx, dy)
        elif b & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton) or (b & Qt.MouseButton.LeftButton and shift):
            self.camera.pan(dx, dy, self.height())

    def wheelEvent(self, ev):
        self.camera.zoom(ev.angleDelta().y() / 120.0)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_F:
            self.fit()
        elif k == Qt.Key.Key_1:
            self.camera.set_view("iso")
        elif k == Qt.Key.Key_2:
            self.camera.set_view("top")
        elif k == Qt.Key.Key_3:
            self.camera.set_view("front")
        elif k == Qt.Key.Key_4:
            self.camera.set_view("right")
        else:
            super().keyPressEvent(ev)

    def fit(self):
        if self.tp is not None and len(self.tp.kind):
            lo, hi = self.tp.bounds()
            self.camera.fit(lo, hi)

    def mouseDoubleClickEvent(self, ev):
        line = self.pick(ev.position().x(), ev.position().y())
        if line >= 0:
            self.selected = line
            self.lineSelected.emit(line)
            self.update()

    def pick(self, mx: float, my: float, radius: float = 12.0) -> int:
        """Return the program line of the visible segment nearest to the mouse."""
        tp = self.tp
        if tp is None or len(tp.kind) == 0:
            return -1
        st = self.state
        col = st.segment_colors(tp)
        vis = (col[:, 3] > 0.5) & (tp.line <= self.cursor) & (tp.layer >= st.layer_min) & (tp.layer <= st.layer_max)
        mid = (tp.p0 + tp.p1) * 0.5
        if st.section:
            pl = st.section_plane()
            d = mid @ pl[:3] - pl[3]
            vis &= (np.abs(d) <= st.section_slab * 0.5) if st.section_slab > 0 else (d <= 0)
        idx = np.nonzero(vis)[0]
        if len(idx) == 0:
            return -1
        w, h = max(1, self.width()), max(1, self.height())
        mvp = self.camera.proj_matrix(w / h) @ self.camera.view_matrix()
        pts = np.concatenate([mid[idx], np.ones((len(idx), 1), np.float32)], axis=1) @ mvp.T
        wv = pts[:, 3]
        ok = wv > 1e-6
        sx = (pts[:, 0] / np.where(ok, wv, 1) * 0.5 + 0.5) * w
        sy = (1 - (pts[:, 1] / np.where(ok, wv, 1) * 0.5 + 0.5)) * h
        sz = pts[:, 2] / np.where(ok, wv, 1)
        d2 = (sx - mx) ** 2 + (sy - my) ** 2
        d2[~ok] = np.inf
        near = d2 <= radius * radius
        if not near.any():
            return -1
        cand = np.nonzero(near)[0]
        best = cand[np.argmin(sz[cand] + d2[cand] * 1e-4)]   # front-most among close ones
        return int(tp.line[idx[best]])
