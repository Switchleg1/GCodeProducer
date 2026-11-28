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

from .rendering_constants import (HIGHLIGHT_PASSES, MATERIAL_SELECTION_COLOR, MATERIAL_SELECTION_FILL,
                                  REFERENCE_COLOR, REFERENCE_SELECTION_COLOR, REFERENCE_FOCUS_COLOR, REFERENCE_ANCHOR_OFFSETS,
                                  REFERENCE_SELECTION_FILL, REFERENCE_FOCUS_FILL)
from gcodeproducer.gui.rendering.model_mesh import _TriMesh
from gcodeproducer.gui.rendering.rendering_constants import (
    MODEL_COLOR,
    OVERHANG_COLOR,
    OUTSIDE_COLOR,
    BLOCK_COLOR,
    BLOCK_SEL_COLOR,
    BLOCK_DEL_COLOR,
    _BOX_FACES,
    _BOX_EDGES,
)
import math, numpy as np, gcodeproducer.gui.rendering.rendering_constants as shaders
from OpenGL import GL
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QLabel
from gcodeproducer.core.geometry.kernel import ray_triangles
from gcodeproducer.core.jobs.placement import face_normals, overhang_faces
from gcodeproducer.gui.rendering.bed_renderer import BedRenderer
from gcodeproducer.gui.rendering.camera import Camera, perspective
from gcodeproducer.gui.rendering.gcode_viewer import _compile, default_surface_format
from gcodeproducer.gui.rendering.gl_mesh import _Mesh


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


class ModelViewer(QOpenGLWidget):
    camPickRequested = pyqtSignal(object)
    camHovered = pyqtSignal(object)       # (mode, ray origin, ray direction) while a sketch tool is active
    camSelectionExited = pyqtSignal()
    moved = pyqtSignal(float, float)          # new model centre X, Y while dragging
    moveFinished = pyqtSignal()
    facePickRequested = pyqtSignal(object)    # ray; triangle work runs in compute process
    faceClicked = pyqtSignal(object)          # world-space normal, or None to cancel
    blockPressed = pyqtSignal(int)            # a support block was clicked (selected)
    blockDragged = pyqtSignal(int, float, float)   # block index, total dX, dY since the press
    blockReleased = pyqtSignal(int)
    blockDeleteRequested = pyqtSignal(int)
    placeBlockClicked = pyqtSignal(float, float, float, bool)   # x, y, z, clicked face points down
    placeModeExited = pyqtSignal()
    seamPicked = pyqtSignal(float, float)
    modelPicked = pyqtSignal(int)
    glError = pyqtSignal(str)

    def __init__(self, camera: Camera, parent=None):
        super().__init__(parent)
        self.setFormat(default_surface_format())
        self.camera = camera
        self.vertices = None                  # placed mesh
        self.triangles = None
        self.tris = None                      # (m,3,3) for picking
        self.rect = (0.0, 0.0, 220.0, 220.0, 250.0)
        self.stock = None
        self.tab_bounds = []
        self.show_material = True
        self.overhang_angle = None            # None = do not show overhangs
        self.inside = True
        self.center_xy = (0.0, 0.0)
        self.model_ends = ()
        self.active_model = -1
        self.cam_pick_mode = ""
        self.cam_faces = []
        self.cam_edges = np.empty((0, 3))
        self.cam_stock_faces = np.empty((0, 3))
        self.cam_stock_edges = np.empty((0, 3))
        self.reference_geometry = np.empty((0, 3))
        self.reference_selection = np.empty((0, 3))
        self.reference_anchor = np.empty((0, 3))
        self.reference_preview = np.empty((0, 3))   # outline of the shape being drawn, following the mouse
        self.tool_readout = ""                      # its position and size, shown with the tool hint
        self.reference_focus = np.empty((0, 3))
        self.reference_selection_fill = np.empty((0, 3))
        self.reference_focus_fill = np.empty((0, 3))
        self._reference_dirty = True
        self._cam_dirty = True
        self.place_on_face = False
        self.pick_seam = False
        self.seam_target = None
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
        self.info.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.info.setStyleSheet("color:#ddd;background:rgba(0,0,0,120);padding:3px 8px;border-radius:3px;")
        self.info.move(8, 8)
        self.warn = QLabel("", self)
        self.warn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.warn.setStyleSheet("color:#111;background:rgba(245,160,50,230);padding:3px 8px;border-radius:3px;")
        self.warn.setVisible(False)
        self.seam_marker = QLabel('⊕', self)
        self.seam_marker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.seam_marker.setStyleSheet('color:#5ff4ff;background:#192631;border:1px solid #5ff4ff;'
                                       'border-radius:11px;font-size:18px;font-weight:bold;')
        self.seam_marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.seam_marker.setFixedSize(22, 22)
        self.seam_marker.hide()
        self.info.raise_()
        self.warn.raise_()
        camera.changed.connect(self.update)
        self._update_info()

    # ----------------------------------------------------------------- API
    def set_scene(self, mesh, rect, center_xy, overhang_angle=None, inside=True, *, model_ends=(), active_model=-1):
        self.model_ends = model_ends
        self.active_model = active_model
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

    def set_stock(self, stock):
        self.stock = stock
        self._dirty = True
        self.update()

    def set_tab_bounds(self, bounds):
        self.tab_bounds = list(bounds)
        self._dirty = True
        self.update()

    def set_cam_mode(self, mode):
        self._drag = self._bdrag = self._cam_press = None
        self.cam_pick_mode = mode
        self._tool_cursor()
        self._update_info()

    def set_reference_geometry(self, edges=(), focus=(), selection_fill=(), focus_fill=()):
        self.reference_geometry = np.asarray(edges,float).reshape(-1,3)
        self.reference_focus = np.asarray(focus,float).reshape(-1,3)
        self.reference_selection_fill = np.asarray(selection_fill,float).reshape(-1,3)
        self.reference_focus_fill = np.asarray(focus_fill,float).reshape(-1,3)
        self._reference_dirty = True
        self.update()

    def set_reference_preview(self, edges=(), readout=""):
        """Outline (GL line pairs) and readout of the shape a sketch tool would make at the mouse."""
        edges = np.asarray(edges, float).reshape(-1, 3)
        if len(edges) or len(self.reference_preview):
            self.reference_preview = edges
            self._reference_dirty = True
            self.update()
        if readout != self.tool_readout:
            self.tool_readout = readout
            self._update_info()

    def set_reference_anchor(self, point):
        self.reference_anchor = (np.asarray(REFERENCE_ANCHOR_OFFSETS)+np.asarray(point) if point is not None
                                 else np.empty((0,3)))
        self._reference_dirty = True
        self.update()

    def set_cam_selection(self, faces=(), edges=(), stock_faces=(), stock_edges=(), reference_edges=()):
        self.cam_faces = list(faces)
        self.cam_edges = np.asarray(edges, dtype=float).reshape(-1, 3)
        self.cam_stock_faces = np.asarray(stock_faces, dtype=float).reshape(-1, 3)
        self.cam_stock_edges = np.asarray(stock_edges, dtype=float).reshape(-1, 3)
        self.reference_selection = np.asarray(reference_edges,float).reshape(-1,3)
        self._reference_dirty = True
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

    def set_seam_target(self, xy):
        self.seam_target = xy
        if xy is None and self.pick_seam:
            self.set_seam_pick(False)
        self._position_seam_marker()

    def set_seam_pick(self, on):
        if self.pick_seam == on:
            return
        self.pick_seam = on
        self._seam_press = None
        self._drag = self._bdrag = None
        self._tool_cursor()
        self._update_info()

    def _position_seam_marker(self, mvp=None):
        if self.seam_target is None:
            self.seam_marker.hide()
            return
        w, h = self.width(), self.height()
        if mvp is None:
            mvp = self.camera.proj_matrix(w / max(h, 1)) @ self.camera.view_matrix()
        clip = mvp @ np.array([*self.seam_target, 0., 1.])
        if clip[3] <= 0 or np.any(np.abs(clip[:3]) > clip[3]):
            self.seam_marker.hide()
            return
        x, y = clip[:2] / clip[3]
        self.seam_marker.move(round((x+1)*w/2)-11, round((1-y)*h/2)-11)
        self.seam_marker.show()

    def _tool_cursor(self):
        tool = self.pick_seam or self.cam_pick_mode or self.place_on_face or self.place_block or self.remove_block
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
            lo = np.array([lo[0] - pad, lo[1] - pad, min(0.0, lo[2])])
            hi = np.array([hi[0] + pad, hi[1] + pad, hi[2]])
        else:
            lo, hi = np.array([x0, y0, min(h, 0.0)]), np.array([x1, y1, max(0.0, min(h, 50.0))])
        self.camera.fit(lo, hi)

    @staticmethod
    def _cam_pick_hint(mode):
        if mode in shaders.CAM_PICK_HINTS:
            return shaders.CAM_PICK_HINTS[mode]
        for prefix, hint in shaders.CAM_PICK_PREFIX_HINTS:
            if mode.startswith(prefix):
                return hint.format(suffix=mode.removeprefix(prefix))
        return f"CAM: select {mode}s • Shift-drag to pan, drag to orbit • Esc = navigate"

    def _update_info(self):
        if self.pick_seam:
            txt = "Click the bed to set the perimeter seam target • Esc cancels"
        elif self.vertices is None:
            txt = "Import a model (Ctrl+O) or drop an STL here"
        elif self.cam_pick_mode:
            txt = self._cam_pick_hint(self.cam_pick_mode)
            if self.tool_readout:
                txt = self.tool_readout + "\n" + txt
        elif self.place_on_face:
            txt = "Click a face of the model to place it on the bed  (Esc = cancel)"
        elif self.place_block:
            txt = "Click the bed or the model to place a support block  •  Esc = done"
        elif self.remove_block:
            txt = "Click a support block to remove it  •  Esc = done"
        else:
            txt = "Ctrl+drag the model to move it  \u2022  drag to orbit, right-drag to pan"
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
        self.m_cam_stock = _Mesh(False)
        self.m_cam_stock_edges = _Mesh(False)
        self.m_reference = _Mesh(False)
        self.m_reference_selection = _Mesh(False)
        self.m_reference_focus = _Mesh(False)
        self.m_reference_selection_fill = _Mesh(False)
        self.m_reference_focus_fill = _Mesh(False)
        self._reference_dirty = True
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
        self.bed.upload_stock(self.stock)
        self.bed.upload_tabs(self.tab_bounds)
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
        if self.active_model >= 0:
            start = self.model_ends[self.active_model-1] if self.active_model else 0
            end = self.model_ends[self.active_model]
            col[:start, :3] *= .62
            col[end:, :3] *= .62
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
        self._position_seam_marker(mvp)

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
        if self._cam_dirty:
            self.m_cam_edges.upload(self.cam_edges)
            self.m_cam_stock.upload(self.cam_stock_faces)
            self.m_cam_stock_edges.upload(self.cam_stock_edges)
            self._cam_dirty = False
        if len(self.cam_edges):
            GL.glUseProgram(self.p_flat)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
            GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), 1.0, 0.78, 0.15, 1.0)
            GL.glDisable(GL.GL_DEPTH_TEST)
            self.m_cam_edges.draw(GL.GL_LINES)
            GL.glEnable(GL.GL_DEPTH_TEST)
        if self.show_material:
            self.bed.draw_stock(self.p_flat,mvp)
            self.bed.draw_material(self.p_flat,mvp)
            self.bed.draw_tabs(self.p_flat,mvp)
        if len(self.cam_stock_faces):
            GL.glUseProgram(self.p_flat)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
            GL.glDisable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *MATERIAL_SELECTION_FILL)
            self.m_cam_stock.draw(GL.GL_TRIANGLES)
            GL.glDisable(GL.GL_BLEND)
            GL.glEnable(GL.GL_DEPTH_TEST)
        if len(self.cam_stock_edges):
            # Draw after the stock surface/fill so its own shading cannot hide selection.
            GL.glUseProgram(self.p_flat)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
            GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *MATERIAL_SELECTION_COLOR)
            GL.glDisable(GL.GL_DEPTH_TEST)
            self.m_cam_stock_edges.draw(GL.GL_LINES)
            GL.glEnable(GL.GL_DEPTH_TEST)
        if self._reference_dirty:
            self.m_reference.upload(self.reference_geometry)
            self.m_reference_selection.upload(np.vstack((self.reference_selection, self.reference_anchor,
                                                         self.reference_preview)))
            self.m_reference_focus.upload(self.reference_focus)
            self.m_reference_selection_fill.upload(self.reference_selection_fill)
            self.m_reference_focus_fill.upload(self.reference_focus_fill)
            self._reference_dirty = False
        GL.glUseProgram(self.p_flat)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.p_flat, "uMVP"), 1, GL.GL_TRUE, mvp)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *REFERENCE_SELECTION_FILL)
        self.m_reference_selection_fill.draw(GL.GL_TRIANGLES)
        GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *REFERENCE_FOCUS_FILL)
        self.m_reference_focus_fill.draw(GL.GL_TRIANGLES)
        GL.glDisable(GL.GL_BLEND)
        GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *REFERENCE_COLOR)
        self.m_reference.draw(GL.GL_LINES)
        GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *REFERENCE_SELECTION_COLOR)
        self.m_reference_selection.draw(GL.GL_LINES)
        GL.glUniform4f(GL.glGetUniformLocation(self.p_flat, "uColor"), *REFERENCE_FOCUS_COLOR)
        self.m_reference_focus.draw(GL.GL_LINES)
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
        for depth, alpha in HIGHLIGHT_PASSES:     # hidden edges faint, visible edges solid
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
        if self.pick_seam:
            self._seam_press = (mx, my)
            return
        if self.cam_pick_mode:
            self._cam_press = (mx, my)
            return
        if self.remove_block:
            bi = self.pick_block(mx, my)[0]
            if bi >= 0:
                self.hover_block = -1
                self.blockDeleteRequested.emit(bi)
            return                                   # a miss just orbits
        if self.place_on_face:
            self.facePickRequested.emit(self.ray(mx, my))
            return
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
        if len(self.model_ends):
            self.modelPicked.emit(int(np.searchsorted(self.model_ends, tri, side='right')))
        if not ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return                                   # plain left drag orbits, even over a model
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
        if self.pick_seam and self._seam_press is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            if np.linalg.norm(np.subtract((pos.x(), pos.y()), self._seam_press)) < 4:
                return
            self._seam_press = None
        if self.cam_pick_mode and getattr(self, "_cam_press", None) is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            if np.linalg.norm(np.subtract((pos.x(), pos.y()), self._cam_press)) < 4:
                return   # Do not orbit on ordinary click jitter before hit testing.
            self._cam_press = None
        dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
        self._last = pos
        b = ev.buttons()
        if b & Qt.MouseButton.LeftButton and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.camera.orbit(dx, dy)
        elif b & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton) or \
                (b & Qt.MouseButton.LeftButton and ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.camera.pan(dx, dy, self.height())
        elif not b and self.cam_pick_mode.startswith("sketch_"):
            self.camHovered.emit((self.cam_pick_mode, *self.ray(ev.position().x(), ev.position().y())))
        elif not b and self.remove_block:
            hb = self.pick_block(ev.position().x(), ev.position().y())[0]
            if hb != self.hover_block:
                self.hover_block = hb
                self.update()
        elif not b and self.tris is not None:
            over = self.pick(ev.position().x(), ev.position().y())[1] >= 0
            over = over and bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if over != self._highlight:
                self._highlight = over
                if not (self.pick_seam or self.cam_pick_mode or self.place_on_face or self.place_block):
                    self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, ev):
        if self.pick_seam and ev.button() == Qt.MouseButton.LeftButton:
            xy = (ev.position().x(), ev.position().y())
            start, self._seam_press = self._seam_press, None
            if start is not None and np.linalg.norm(np.subtract(xy, start)) < 4:
                p = self._plane_point(*xy, 0.)
                x0, y0, x1, y1, _ = self.rect
                if p is not None and x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
                    self.set_seam_pick(False)
                    self.seamPicked.emit(float(p[0]), float(p[1]))
            return
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
        if k == Qt.Key.Key_F:
            self.fit()
        elif k in shaders.CAMERA_SHORTCUTS:
            self.camera.set_view(shaders.CAMERA_SHORTCUTS[k])
        elif k == Qt.Key.Key_Escape and self.pick_seam:
            self.set_seam_pick(False)
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
