[Documentation](../README.md) / [CAM](README.md)

# 3-axis surface operations: 3D Pocket and 3D Contour

(**3D Pocket** was called *3D Waterfall* before 0.2.65; saved operations open
unchanged.)

Both operations clear material in **depth-limited passes**, stopping at the
model surface. They use a vertical flat-endmill footprint: no undercuts,
ball-nose compensation, fixtures or holder simulation.

| Operation | What it produces | Typical use |
|---|---|---|
| **Pocket** | Planar clearing to a flat End Z; level boundaries required | Ordinary 2.5D pockets |
| **3D Pocket** | Full-area clearing at successive Z levels, with the model protected at each level | Roughing sloped, stepped or curved floors and walls |
| **3D Contour** | Successive surface-following raster passes, each limited to the next depth band | Clearing and refining sloped or gently curved surfaces |

A useful sequence is **3D Pocket → 3D Contour**: 3D Pocket clears terraces;
Contour refines the surface. Contour also works on its own: it no longer makes
a single finishing pass straight through uncleared material.

## Depth of cut and material above Start

Both kinds use the resolved **depth of cut**, including the operation unlock
and the tool's positive **Max depth/pass** cap. 3D Pocket automatic depth uses
the active material's **Pocket** axial percentage; Contour uses **Slot**.

If the selected Start is below the original stock/model surface, clearing
begins at that surface so the material above Start is not skipped. For example,
Start −4, End −10, stock top 0 and depth/pass 1 require passes starting at −1,
not a first entry at −5. 3D Pocket can omit passes already cleared by earlier
operations when **Remove air cutting** is enabled. With **Remove air cutting**
on, the motion planner checks each measured sub-move of a 3D Pocket path that
follows the surface against the current material left by all earlier passes
and tools. Stretches that touch nothing are not written: air gaps longer than
two cutter diameters become a retract and re-entry, shorter ones are fed
through, and paths entirely in air are dropped. The remaining pieces of each
depth band are visited nearest-first (each keeps its cutting direction). The
log reports the skipped length. Material only decreases, so skipping cannot
leave material uncut. **3D Contour is never cut short** (0.2.65): each depth
band is one unbroken path the cutter follows from end to end, over cleared
ground or not, line after line in order; only 3D Pocket reorders its paths,
cuts them short or sends the cutter to other places.

Every depth is visited across all reachable areas before descending: the
reachable area changes with depth, so surface operations do not use
*each area to full depth* ordering. Safe Z must still clear the stock/model.

## 3D Pocket

**Full-area surface-limited clearing.**

![3D Pocket clearing in depth bands](../pictures/cam-waterfall-clearing.png)

At each depth, 3D Pocket subtracts the XY shadow of all model material above
that depth from the selected area. It then clears the **whole remaining
cutter-accessible region**, not just one contour along its wall.

1. Add **3D Pocket** and select closed part/material/reference outlines.
   Sloped edge boundaries are allowed. A selected horizontal material edge
   identifies its complete stock rim, as in Pocket.
2. Set Start/End. Selection-linked defaults use the selection's extrema. A
   flat rim needs End linked to a lower feature or set explicitly.
3. Choose **Cutting strategy → Wall-parallel contours / Raster lines X / Raster lines Y / Adaptive clearing**, stepover, radial
   stock to leave and depth of cut. Stay-down links, lead ramps, cutting hand,
   engagement feeds and the material boundary limit work as for clearing.
   Stock to leave is kept on the part only: where the selection reaches the
   blank edge, the cutter edge still meets that edge (plus the material boundary
   limit), so roughing leaves no wall of raw stock around the blank.
4. Optionally tick **Follow the surface within each depth** (below). Generate
   and inspect each depth and the calculated material outputs.

### Follow the surface within each depth

A flat depth stops at the model's shadow and leaves the slope above it as a
step; on the first depth that is the whole slope between the top of the
material and that depth. With **Follow the surface within each depth**
ticked, each depth also works the area that was free at the depth above (the
material top for the first one). Its paths are planned as usual, then every
point rides at the model's height (plus stock to leave) under the cutter
where that is above the current depth, up to the depth above: never below
the current depth, never above the one before. Paths that stay flat are
unchanged; a lifted closed contour is opened at its highest point so its
lead ramps in down the slope. A lifted path follows the surface by the same
rule as 3D Contour (see *Surface heights* below). Lifted paths are 3D moves, so they are entered
and linked like 3D Contour paths rather than with stay-down links. On the
Mini Yoda (4 mm endmill, 2 mm depths, 1 mm stock to leave, wall-parallel
contours) the material left above the model after the 3D Pocket fell from
3,205 to 1,931 mm³, for 147 s more machining (622 to 769 s estimated) and
18 s more compute. A wall that is vertical or overhangs is unchanged: a flat
cutter cannot reach it from above.

With **Adaptive** clearing the slope is taken by **step-up levels**, not by
lifting paths. Adaptive plans its engagement in a plane, so every one of its
paths stays at one height. After each depth, three flat levels are added
between it and the depth above (a quarter of the step apart). At each, passes
start where the cutter is clear of the material actually left at that height
and step in towards the model, one engagement-limit width per pass, over the
stair the lower depth left. A level never cuts deeper than the distance up
to the depth above: stock that still stands at the depth above (crescents the
upper depth left along a wall) is treated as a wall and not approached. The
passes are cut climb; with Conventional no step-up levels are added. Turn
**Follow the surface** off to rough at the fixed depths only.

**No depth cuts stock taller than its step.** Adaptive fronts turn off short
of the walls and leave crescents along them; a round cutter also leaves a
fillet in every concave corner of a depth's wall. Left standing, the next
depth met them at twice its height (Mini Yoda with Overcut 0: 234 mm of feed
through columns 4 mm tall at Z-4, 120 mm through columns 5 mm tall at Z-5).
Now, after each Adaptive depth, passes step in to the walls over what is
actually left there, one engagement-limit width at a time, the last along
the wall itself (climb only). Fillets the depth above could not reach, and
anything else it left standing beyond a trace, are kept out of the next
depth's area as a wall; if a depth still sweeps such stock the job warns.
On the Mini Yoda the deepest stock cut at every level now equals its step
(2, 2 and 1 mm), replayed from the emitted program.

A rapid descent now stops clear of the highest stock the recorded cutter
sweeps still show under the cutter (the height grid cannot see a skin
thinner than one of its cells), and a short retract becomes a full one
where those sweeps do not show the way clear.

Mini Yoda (4 mm cutter, 10 % width, depths Z-2, Z-4, Z-5): 9 step-up levels,
110-320 mm of cutting each, 5-9 entries each; about 250 mm³ of stair removed
(the stairs fall to a quarter of the step); estimated machining 3,008
to 3,178 s. Replayed from the emitted program on a 0.05 mm grid: no stock
met on an air-feed or rapid move, and the deepest stock cut at the step-up
levels is 1.5, 1.0, 0.5 mm (0.75, 0.5, 0.25 mm at the last depth), exactly
the distance to the depth above. Of their cutting moves 2-25 % read as
conventional (mostly the joins between passes) and are highlighted as
Conflict. This is a geometric replay, not a qualification for a machine.

Nested selected outlines alternate between boundary and island. Overlapping
outlines merge. Exact projected upper triangles protect overhangs; undercuts
are left uncut. Model material within 0.001 mm above a level counts as floor.
Tabs are protected below their roofs; up to one depth of cut may remain over
a tab because this planner does not insert an extra tab-roof pass.

A cutter-sized region may disappear before End on a slope; those levels are
skipped. A smaller tool or Contour can reach more of the surface, but neither
can reach below an overhang or into corners tighter than the cutter.
**Overcut** extends the selected removal region into surrounding stock, just
as in Pocket. The added area respects the sampled part sections and the
material boundary limit; each pass still protects the model shadow and tabs.
See [Overcut](operations.md#overcut-into-void-material).

## Pocket migration

The **Stop at model surface** checkbox has been removed from Pocket. Its old
behaviour is now **3D Pocket**, with full-area depth-limited clearing.
Saved Pocket operations with that flag enabled reopen as 3D Pocket, preserving
their name, selections, depths and other settings. Pocket without the flag
remains a flat-floor operation; old nonlevel Pocket boundaries must be changed
to 3D Pocket explicitly rather than silently choosing a different strategy.

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
- **Cutting strategy:** **Raster lines X** or **Raster lines Y**. Every line
  runs the whole width of the area and traces the model under the cutter down
  to the depth of the current pass, without lifting or stopping along it. The
  lines are cut in order across the area, never reordered or skipped. See [Cutting strategy](operations.md#cutting-strategy).
- **Cutting direction** (the machine's, or *Unlock cutting direction*):
  **Meander** cuts the lines both ways, stepping over at the end of each.
  **Climb** / **Conventional** cut every line one way, lifting at its end and
  going back to the start of the next line.
- **Surface heights:** the safe-height grid holds one height per cell, which a
  path crossing a slope would follow as a staircase of tiny plunges. 3D Contour
  and 3D Pocket's *Follow the surface* share one rule (`follow_heights`):
  heights are interpolated between cells of the grid raised to each cell's
  neighbourhood, so never below the grid, on slopes up to about 50°; across a
  steeper step (a wall) the cell height is kept, so the path does not climb
  the wall early. Dips narrower than 0.5 mm are filled by up to 0.05 mm, so
  grid noise does not saw the cutter up and down while real corners are kept.
- **Ceiling:** stretches resting at or above the original material surface
  are omitted. Raised model surfaces and tabs still constrain every band.
- **Feeds:** XYZ moves are classified from current height-field material as
  **Slot / High engagement / Cut / HSM / Air**. Machine thresholds and the
  operation/tool/machine feed modifiers apply. A descent into material is fed by its angle,
  blending from the level rate to the lead-in rate at the lead-in angle and on
  to the plunge feed straight down; steeper than the lead-in angle it shows as
  *Plunge*. Every feed remains machine-capped. Feeds are then smoothed along
  each continuous cut (Settings → *Feed smoothing length*, below).
- **Entries:** **Lead-in** is *Every entry*, *Layer entry* (only the first
  entry of each depth) or *None*. An entry which meets remaining material
  ramps along the path within the operation's lead-in angle, zigzagging along
  a short path, by the same rule as every flat path (see
  [Material state and leads](material-state-and-leads.md)). The ramp never goes
  below the path: where the path rises away from its start faster than the
  lead-in angle allows, the lead follows the path there instead of failing.
  Already-clear entries skip the ramp and descend through verified air;
  entries without a ramp plunge at the plunge feed.
- **Exits:** **Lead-out** is *Every entry* (every exit), *Layer entry* (only
  the last exit of each depth) or *None*. A path that cut material carries on
  forward from its end at the cutting feed, climbing at the **Lead-out angle**
  (0 = level), only over space already cut; where carrying on would meet
  material (a line ending at a wall) the tool retracts straight up. An uncertain exit is omitted in favour
  of retracting; an entirely air-only path has no lead-out.

![Contour leads and material-aware cutting features](../pictures/cam-contour-leads-engagement.png)

Leads never extend an arbitrary tangent through a retained wall. If the usable
surface rises too steeply to fit a protected entry at the configured angle, generation reports an
error instead of silently plunging. Choose another entry/direction or explicitly
turn lead-in off only after checking plunge capability. A shorter requested lead
can help where an unnecessarily long lead crosses a raised surface.

![Contour engagement feed controls are enabled](../pictures/cam-contour-engagement-settings.png)

Classification samples the current tip height and newly swept cutter footprint,
subdividing long XYZ moves so their feed/type can change along the path. It
includes emitted leads, earlier paths/depths and tool changes. Preview feature
colours and radial-engagement colours use this metadata; it is a **grid estimate**,
not measured tooth load. Without allocated stock, the emitter assumes a
conservative model-bounds blank and logs that limitation.

Heights use a conservative upper-surface grid. By default (**3D surface grid**
= 0) it is the smaller of global material resolution and diameter/40, no finer
than 0.05 mm; an explicit value overrides that. The cell cap may coarsen it
with a warning. Slopes retain extra stock (roughly one to four cells times
slope); paths are simplified to **3D path tolerance** (default 0.005 mm).
Smaller stepover/resolution improves surface detail but increases computation
and output size. See [CAM planner resolution](../settings.md#cam-planner-resolution)
for the speed/size trade-offs.

## Limits and safety

These are not adaptive or rest-machining algorithms. 3D Pocket uses planar
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
