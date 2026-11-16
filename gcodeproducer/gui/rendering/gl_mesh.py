"""_Mesh — rendering subsystem."""
from __future__ import annotations
import ctypes, numpy as np
from OpenGL import GL

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
