import struct
from pathlib import Path

import pytest


def _write_cube(path, size=20.0):
    return write_boxes(path, [(0, 0, 0, size, size, size)])


def write_boxes(path, boxes):
    """Binary STL of several (disjoint) axis-aligned boxes (x0, y0, z0, x1, y1, z1)."""
    tris = []
    for x0, y0, z0, x1, y1, z1 in boxes:
        v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        quads = [((0, 3, 2, 1), (0, 0, -1)), ((4, 5, 6, 7), (0, 0, 1)), ((0, 1, 5, 4), (0, -1, 0)),
                 ((1, 2, 6, 5), (1, 0, 0)), ((2, 3, 7, 6), (0, 1, 0)), ((3, 0, 4, 7), (-1, 0, 0))]
        for (a, b, c, d), n in quads:
            tris.append((n, v[a], v[b], v[c]))
            tris.append((n, v[a], v[c], v[d]))
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tris)))
        for n, a, b, c in tris:
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))
    return str(path)


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
