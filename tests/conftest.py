import struct
from pathlib import Path

import pytest


def _write_cube(path, size=20.0):
    v = [(0, 0, 0), (size, 0, 0), (size, size, 0), (0, size, 0),
         (0, 0, size), (size, 0, size), (size, size, size), (0, size, size)]
    quads = [((0, 1, 2, 3), (0, 0, -1)), ((4, 5, 6, 7), (0, 0, 1)),
             ((0, 1, 5, 4), (0, -1, 0)), ((1, 2, 6, 5), (1, 0, 0)),
             ((2, 3, 7, 6), (0, 1, 0)), ((3, 0, 4, 7), (-1, 0, 0))]
    tris = []
    for (a, b, c, d), n in quads:
        tris.append((n, v[a], v[b], v[c]))
        tris.append((n, v[a], v[c], v[d]))
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for n, a, b, c in tris:
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))
    return path


@pytest.fixture
def cube_stl(tmp_path):
    return str(_write_cube(tmp_path / "cube.stl"))


@pytest.fixture
def libset(tmp_path):
    from gcodeproducer.core import defaults
    from gcodeproducer.core.profiles import LibrarySet
    ls = LibrarySet(tmp_path / "lib")
    defaults.seed(ls, save=False)
    return ls
