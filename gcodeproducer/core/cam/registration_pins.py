"""Registration pins: four reference circles at the corners of a box centred on the stock.

Two-sided machining turns the stock over about its X or its Y axis through
its centre. Four holes at ``centre ± (half width, half height)`` map onto each
other under either turn, so pins in the table through those holes locate the
stock on both sides. The pins are ordinary reference circles (pick them in a
drill, pocket or profile operation to cut the holes) that share a ``group``:
moving or resizing one moves and resizes all four so they stay a box centred
on the stock, and they follow the stock's centre when the stock changes.
"""
from __future__ import annotations
import uuid
import numpy as np

from .cam_constants import PIN_CORNERS
from .reference_shape import ReferenceShape


def stock_centre(setup):
    """XY centre of the allocated stock, or None."""
    stock = getattr(setup, "stock", None)
    if stock is None or not stock.allocated:
        return None
    lo, hi = stock.bounds
    return (np.asarray(lo[:2], float)+np.asarray(hi[:2], float))/2


def next_number(shapes):
    """Number for a new set of pins: one more than the sets there are."""
    return len({s.group for s in shapes if s.group})+1


def make_pins(centre, corner, radius, z, number=1, group=None):
    """Four circles at the corners of the box centred on ``centre`` that reaches ``corner``."""
    centre = np.asarray(centre, float)
    half = np.abs(np.asarray(corner, float)[:2]-centre)
    radius = float(radius)
    if not np.all(half > 0) or not radius > 0 or not np.isfinite(np.r_[half, radius]).all():
        raise ValueError("Registration pins need a box with a width and a height, and a pin size")
    group = group or uuid.uuid4().hex
    shapes = []
    for k, sign in enumerate(PIN_CORNERS):
        at = centre+half*np.asarray(sign, float)
        shapes.append(ReferenceShape("circle", "center", tuple(at), (at[0]+radius, at[1]), z,
                                     f"Pin {number}.{k+1}", group=group))
    return shapes


def members(shapes, group):
    """The shapes of one set of pins, in corner order."""
    return [s for s in shapes if group and s.group == group]


def box_of(pins, centre):
    """(half width, half height, radius) of a set of pins about ``centre``."""
    offsets = np.array([np.abs(np.asarray(s.dimensions()[0], float)-centre) for s in pins])
    return float(offsets[:, 0].mean()), float(offsets[:, 1].mean()), float(pins[0].dimensions()[1])


def sync(shapes, edited, centre):
    """After ``edited`` (one pin) was moved or resized: put its whole set back on a centred box.

    The edited pin decides the half width and height (its distance from the
    centre along X and Y), the diameter and the Z of all four.
    """
    pins = members(shapes, edited.group)
    if len(pins) != len(PIN_CORNERS) or centre is None:
        return
    centre = np.asarray(centre, float)
    at, radius = edited.dimensions()
    half = np.abs(np.asarray(at, float)-centre)
    if not np.all(half > 1e-9):
        raise ValueError("A registration pin cannot sit on the stock's centre line")
    for pin, sign in zip(pins, PIN_CORNERS):
        pin.set_geometry(center=centre+half*np.asarray(sign, float), size=float(radius), z=edited.z)


def recentre(setup):
    """Move every set of pins so its box is centred on the stock again; True if anything moved."""
    centre = stock_centre(setup)
    if centre is None:
        return False
    moved = False
    for group in dict.fromkeys(s.group for s in setup.reference_shapes if s.group):
        pins = members(setup.reference_shapes, group)
        if len(pins) != len(PIN_CORNERS):
            continue
        old = np.mean([s.dimensions()[0] for s in pins], axis=0)
        hx, hy, radius = box_of(pins, old)
        for pin, sign in zip(pins, PIN_CORNERS):
            target = centre+np.array([hx, hy])*np.asarray(sign, float)
            if not np.allclose(pin.dimensions()[0], target, atol=1e-9):
                pin.set_geometry(center=target, size=radius)
                moved = True
    return moved
