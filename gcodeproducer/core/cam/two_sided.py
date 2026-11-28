"""Two-sided 3-axis machining: the same stock machined from the top, turned over, and machined again.

A two-sided setup holds the operations of **Side A** and **Side B**. For Side
B the stock is turned over about its X or its Y axis and put back in the same
place on the table: it occupies the same box, its old top face now lies on
the bed and its old underside is the new top (same height, so the top of the
material stays where it was). The model keeps its place inside the material,
so it is rotated half a turn about the centre of the stock's box.

Operations refer to faces and edges of the model by index, and a rotation
keeps those, so each side's operations are simply planned on the model as it
lies for that side. Reference shapes are positions on the table: they are the
same for both sides (registration holes placed symmetrically about the
stock's centre therefore coincide after the turn).

The material of Side B is planned as a full, uncut block. That is on the safe
side: what Side A removed can only make Side B's cuts lighter, never heavier.
"""
from __future__ import annotations
import numpy as np

from gcodeproducer.core.geometry.mesh import Mesh
from .cam_constants import FLIP_AXES, SIDES


def flip_centre(mesh, stock):
    """The point the model turns about: the centre of the stock's box (of the model's own, without stock)."""
    if stock is not None and stock.allocated:
        lo, hi = stock.bounds
    else:
        lo, hi = mesh.bounds
    return (np.asarray(lo, float)+np.asarray(hi, float))/2


def flip_mesh(mesh, stock, axis):
    """``mesh`` turned over with the stock: half a turn about the stock centre's X or Y axis."""
    if axis not in FLIP_AXES:
        raise ValueError(f"Unknown flip axis '{axis}'")
    centre = flip_centre(mesh, stock)
    sign = np.array([1., -1., -1.]) if axis == "x" else np.array([-1., 1., -1.])
    vertices = centre + (np.asarray(mesh.vertices, float)-centre)*sign
    return Mesh(vertices, mesh.triangles)       # a rotation: the triangles keep their winding


def flip_point(point, mesh, stock, axis):
    """A work-coordinate point of one side on the other side (the turn is its own inverse)."""
    centre = flip_centre(mesh, stock)
    sign = np.array([1., -1., -1.]) if axis == "x" else np.array([-1., 1., -1.])
    return centre + (np.asarray(point, float)-centre)*sign


def side_mesh(mesh, setup):
    """The placed model as it lies for the setup's active side."""
    if mesh is None or setup is None or not getattr(setup, "two_sided", False) or setup.side != SIDES[1]:
        return mesh
    return flip_mesh(mesh, setup.stock, setup.flip_axis)


def side_label(setup):
    """'' for a one-sided setup, else 'Side A' / 'Side B'."""
    if setup is None or not getattr(setup, "two_sided", False):
        return ""
    return "Side A" if setup.side == SIDES[0] else "Side B"
