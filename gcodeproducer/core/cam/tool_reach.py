"""How deep a tool can work: its flutes, how far it sticks out of the chuck, and the chuck itself.

* **Flute length** (tool ``length``): the depth below the material around the
  cut that the cutter may work at. Deeper, the shank above the flutes rubs or
  is forced into the wall.
* **Stickout** (tool ``stickout``): from the chuck's face to the tip.
* **Chuck** (machine ``chuck_diameter`` and ``chuck_stickout``, the length the
  chuck or collet nut stands out below the spindle body).

Without a chuck diameter the chuck's width is unknown, so it may not go below
the top of the stock at all: the depth below that top is limited to the tool's
stickout. With one, the chuck may go down into the part as far as its own
stickout (then the spindle body would meet the top of the stock), provided the
chuck, a cylinder of its diameter whose face is a tool stickout above the
tip, never meets material: the motion planner checks that move by move
against the material as it stands (``chuck_contact``).

0 for the flute length or the tool's stickout means "not set": that check is
skipped.
"""
from __future__ import annotations
import numpy as np


def chuck_of(machine):
    """(chuck radius, chuck stickout) of a machine, or None when no chuck diameter is set."""
    if machine is None:
        return None
    diameter = float(machine.get("chuck_diameter", 0) or 0)
    return (diameter/2, max(0., float(machine.get("chuck_stickout", 0) or 0))) if diameter > 0 else None


def reach_problems(tool, name, depth_below_material, depth_below_top, machine=None):
    """Messages for the limits a cut exceeds: (flute, stickout); None for one that is fine."""
    flute = float(tool.get("length", 0) or 0)
    stickout = float(tool.get("stickout", 0) or 0)
    too_long = (f"{name}: cuts {depth_below_material:g} mm below the material around it, but the tool's flute "
                f"length is {flute:g} mm: the shank above the flutes would rub the wall. Use a tool with longer "
                f"flutes, or cut less deep.") if flute > 0 and depth_below_material > flute+1e-3 else None
    too_deep = None
    chuck = chuck_of(machine)
    if stickout > 0 and chuck is None and depth_below_top > stickout+1e-3:
        too_deep = (f"{name}: reaches {depth_below_top:g} mm below the top of the stock, but the tool sticks out of "
                    f"the chuck only {stickout:g} mm: the chuck would hit the stock. Extend the tool's stickout "
                    f"(and its Stickout length), cut less deep, or set the machine's Chuck diameter so the chuck "
                    f"is checked against the material instead.")
    elif stickout > 0 and chuck is not None and depth_below_top > stickout+chuck[1]+1e-3:
        too_deep = (f"{name}: reaches {depth_below_top:g} mm below the top of the stock, but the tool sticks out "
                    f"{stickout:g} mm and the chuck {chuck[1]:g} mm below the spindle: the spindle body would hit "
                    f"the stock. Extend the tool's stickout or cut less deep.")
    return too_long, too_deep


def chuck_contact(state, a, b, stickout, chuck):
    """Whether the chuck meets material while the tip moves from a to b (XYZ) through ``state``.

    The chuck's face is ``stickout`` above the tip and ``chuck[0]`` in radius.
    ``state`` is the height-field material (HeightStock) as it stands now.
    """
    if state is None or chuck is None or stickout <= 0:
        return False
    a, b = np.asarray(a, float), np.asarray(b, float)
    lift = np.array([0., 0., stickout])
    if min(a[2], b[2])+stickout >= state.stock.top-1e-9:
        return False                      # the chuck stays above the top of the stock
    return bool(state.contact(a+lift, b+lift, chuck[0]))
