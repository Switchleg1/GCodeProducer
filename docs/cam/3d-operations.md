[Documentation](../README.md) / [CAM](README.md)

# 3-axis surface operations: 3D Waterfall and 3D Contour

Both operations clear material in **depth-limited passes**, stopping at the
model surface. They use a vertical flat-endmill footprint: no undercuts,
ball-nose compensation, fixtures or holder simulation.

| Operation | What it produces | Typical use |
|---|---|---|
| **Pocket** | Planar clearing to a flat End Z; level boundaries required | Ordinary 2.5D pockets |
| **3D Waterfall** | Full-area clearing at successive Z levels, with the model protected at each level | Roughing sloped, stepped or curved floors and walls |
| **3D Contour** | Successive surface-following raster passes, each limited to the next depth band | Clearing and refining sloped or gently curved surfaces |

A useful sequence is **3D Waterfall → 3D Contour**: Waterfall clears terraces;
Contour refines the surface. Contour also works on its own: it no longer makes
a single finishing pass straight through uncleared material.

## Depth of cut and material above Start

Both kinds use the resolved **depth of cut**, including the operation unlock
and the tool's positive **Max depth/pass** cap. Waterfall automatic depth uses
the active material's **Pocket** axial percentage; Contour uses **Slot**.

If the selected Start is below the original stock/model surface, clearing
begins at that surface so the material above Start is not skipped. For example,
Start −4, End −10, stock top 0 and depth/pass 1 require passes starting at −1,
not a first entry at −5. Waterfall can omit passes already cleared by earlier
operations when **Remove air cutting** is enabled. Contour conservatively
revisits upper material rather than assuming it was cleared.

Every depth is visited across all reachable areas before descending: the
reachable area changes with depth, so surface operations do not use
*each area to full depth* ordering. Safe Z must still clear the stock/model.

## 3D Waterfall

**Full-area surface-limited clearing.**

![Waterfall clearing in depth bands](../pictures/cam-waterfall-clearing.png)

At each depth, Waterfall subtracts the XY shadow of all model material above
that depth from the selected area. It then clears the **whole remaining
cutter-accessible region**, not just one contour along its wall.

1. Add **3D Waterfall** and select closed part/material/reference outlines.
   Sloped edge boundaries are allowed. A selected horizontal material edge
   identifies its complete stock rim, as in Pocket.
2. Set Start/End. Selection-linked defaults use the selection's extrema. A
   flat rim needs End linked to a lower feature or set explicitly.
3. Choose **Cutting strategy → Wall-parallel contours / Raster lines X / Raster lines Y**, stepover, radial
   stock to leave and depth of cut. Stay-down links, lead ramps, cutting hand,
   engagement feeds and the material boundary limit work as for clearing.
4. Generate and inspect each depth and the calculated material outputs.

Nested selected outlines alternate between boundary and island. Overlapping
outlines merge. Exact projected upper triangles protect overhangs; undercuts
are left uncut. Model material within 0.001 mm above a level counts as floor.
Tabs are protected below their roofs; up to one depth of cut may remain over
a tab because this planner does not insert an extra tab-roof pass.

A cutter-sized region may disappear before End on a slope; those levels are
skipped. A smaller tool or Contour can reach more of the surface, but neither
can reach below an overhang or into corners tighter than the cutter.
Pocket overcut into void is not a Waterfall setting.

## Pocket migration

The **Stop at model surface** checkbox has been removed from Pocket. Its old
behaviour is now **3D Waterfall**, with full-area depth-limited clearing.
Saved Pocket operations with that flag enabled reopen as Waterfall, preserving
their name, selections, depths and other settings. Pocket without the flag
remains a flat-floor operation; old nonlevel Pocket boundaries must be changed
to Waterfall explicitly rather than silently choosing a different strategy.

## 3D Contour

**Depth-limited surface passes.**

![Contour with multiple depth passes](../pictures/cam-contour-depth-passes.png)

The final reachable tool-tip height is the highest model point under its
footprint, plus axial stock to leave, never below End. Intermediate passes
clamp that height upward to each successive depth floor. With 0.5 mm depth/pass,
no intermediate band starts directly at a surface several millimetres below
uncleared stock.

- **Area:** selected closed XY outlines; the cutter centre stays inside them.
- **Stepover:** raster spacing as a percentage of cutter diameter.
- **Cutting strategy:** **Meander** zigzags along the longer side with short
  in-region surface links. **Raster lines X / Y** cuts separate single-direction
  lines along the chosen work-coordinate axis, with retract/travel between them.
  Climb/conventional is not a selectable hand for these XYZ paths.
- **Ceiling:** stretches resting at or above the original material surface
  are omitted. Raised model surfaces and tabs still constrain every band.
- **Feeds:** normal cutting feed; descents steeper than 10° use lead/plunge
  feed. Engagement feed modifiers are not applied to these XYZ paths.
- **Entries:** checked short retract/travel, then a fed descent to the next
  depth-limited path. There is no contour lead ramp on an XYZ raster.

Heights use a conservative upper-surface grid: the smaller of global material
resolution and diameter/40, no finer than 0.05 mm. The cell cap may coarsen it
with a warning. Slopes retain extra stock (roughly one to four cells times
slope); paths are simplified to 0.005 mm. Smaller stepover/resolution improves
surface detail but increases computation and output size.

## Limits and safety

These are not adaptive or rest-machining algorithms. Waterfall uses planar
removal history across operations for air removal and engagement; Contour XYZ
removal updates emitted height-field material but not planar history. Later
operations therefore cannot assume a Contour pass cleared their planar region.
Contour may repeat already-cleared passes, including when roughing precedes it.

All tools are treated as flat cutters of their diameter. Tool type and V angle
do not provide cutter-shape compensation. Preview, grid checks and warnings
remain approximate; independently verify reach, shanks, holders, fixtures and
workholding. A warning-free program is not collision certification.

Older captures `cam-3d-pocket-terraces.png`, `cam-3d-waterfall.png`,
`cam-3d-contour.png` and `cam-3d-rough-and-finish.png` predate this change:
they show the old Pocket toggle, wall-only Waterfall or single-pass Contour,
and are retained as historical pictures, not current workflow instructions.
