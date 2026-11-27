"""How deep a tool can work: its flute length and how far it sticks out of the collet.

* **Flute length** (tool ``length``): the depth below the material around the
  cut that the cutter may work at. Deeper, the shank above the flutes rubs or
  is forced into the wall.
* **Stickout** (tool ``stickout``): from the collet face to the tip. The depth
  below the top of the material may not exceed it, or the collet (and the
  spindle nose) would meet the stock. The holder's width is not modelled, so
  the top of the stock is used, wherever the tool works.

0 for either means "not set": that check is skipped.
"""
from __future__ import annotations


def reach_problems(tool, name, depth_below_material, depth_below_top):
    """Messages for the limits a cut exceeds: (flute, stickout); None for one that is fine."""
    flute = float(tool.get("length", 0) or 0)
    stickout = float(tool.get("stickout", 0) or 0)
    too_long = (f"{name}: cuts {depth_below_material:g} mm below the material around it, but the tool's flute "
                f"length is {flute:g} mm: the shank above the flutes would rub the wall. Use a tool with longer "
                f"flutes, or cut less deep.") if flute > 0 and depth_below_material > flute+1e-3 else None
    too_deep = (f"{name}: reaches {depth_below_top:g} mm below the top of the stock, but the tool sticks out of "
                f"the collet only {stickout:g} mm: the collet would hit the stock. Extend the tool's stickout "
                f"(and its Stickout length) or cut less deep.") if stickout > 0 and depth_below_top > stickout+1e-3 else None
    return too_long, too_deep
