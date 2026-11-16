"""_TriMesh — rendering subsystem."""
from __future__ import annotations
import numpy as np
from OpenGL import GL

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
