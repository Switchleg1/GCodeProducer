[Documentation](../README.md) / [CAM](README.md)

# Pocket, Profile, Slot, Drill and Engrave

These are tree operations (`core.cam.Operation`), not independent pipeline
stage presets. They share a tool group, selection system, start/end depth
sources and execution order. Geometry is generated from the placed STL;
cutting faces must be horizontal and selected edge chains constant-Z.

## Shared fields and defaults

| Field | New-operation behaviour | Meaning |
|---|---|---|
| Kind | Chosen in Add operation menu | Pocket, Profile, Slot, Drill or Engrave |
| Name | Kind's title | Human-readable tree/log/output label; rename for clarity |
| Enabled | On | Off skips the operation |
| Geometry | Empty | Operation-owned face/edge references; generation requires a selection |
| Start | Pocket: Material surface + 0; others: Model top + 0 | Pocket falls back to model top until stock is allocated; not safe approach height |
| End | Pocket: machining selection minimum Z + 0; Profile/Slot/Drill: Model bottom + 0 | **Engrave defaults to Model top - 0.2 mm** |
| Tool/material axial depth default | On for new GUI operations | Material-specific Slot 15%, Pocket 25%, Profile 40% of diameter; configurable per tool and capped by max depth/pass |
| Stepdown | Explicit value when automatic depth is off | Existing operations retain saved explicit depths |
| RPM / normal feed / lead feed unlocks | Off | Calculated or legacy tool bases unless independently unlocked |
| Lead-in / lead-out | On | Contour-constrained ramp/cleared exit; checked against current material |
| Lead length | 0 (auto) | Automatic length respects a 10° ramp slope when enough contour exists |
| Pocket stepover | 40% | Offset/raster spacing as percentage of cutter diameter; wall-parallel spacing is limited to 50% for meeting-front coverage |
| Pocket strategy | Wall-parallel contours | Topology-aware offsets; Raster lines remains available |
| Cutting direction | Machine default | Inherit Climb/Conventional/Meander, or override per operation |
| Stay down between contours | On | Wall-parallel pockets: nearby loops use checked same-depth cutting-feed links; unsafe/disconnected links retract |
| HSM / Cut / High engagement / Slot feed | Inherited (0) | HSM/Cut use tool defaults; High/Slot use machine defaults; thresholds are machine settings (High above 80% initially) |
| Profile side | Outside | Outside, Inside or On |
| Roughing clearance / stock to leave | 0 mm | Radial allowance left on every selected wall/island by Pocket/Profile; not axial depth allowance |
| Pocket overcut into void | 0 mm (global default) | Pocket only: grows the removal region outward into material that is not part of the model at any pass depth, so the pocket overlaps the next operation and leaves no thin wall between them; see below |
| Material boundary limit | 0 mm (global default) | Pocket only: where the region reaches the blank edge, the cutter's outer edge goes to blank edge + this value. 0 touches the edge, −1 leaves 1 mm of material, +1 passes 1 mm beyond it |

Choose realistic end depths explicitly; an automatically created operation
is not a safe default machining plan. For stepdown `s`, generation uses up to
`ceil((start-end)/s)` passes, shortening the last one to reach End. More than
10,000 passes is rejected. Empty paths, invalid depths, nonpositive tool
radius/stepdown, unsupported geometry and missing tools fail instead of
silently switching to another strategy.

The emitter begins each depth pass with a safe-Z XY position and vertical
plunge. Wall-parallel pockets can then stay down between nearby contours when
the full cutter-centre link is inside the permitted region. Other paths or
blocked/disconnected links retract before re-entry. Enabled leads follow the
selected contour while ramping in or exiting through calculated cleared stock.
If a ramp cannot fit, a vertical fallback is explicitly warned. No helical
macro or controller cutter-compensation cycle is inserted.

Tool RPM/feed can be calculated from material SFM/chip load, with tool/machine
RPM ceilings and independent operation unlocks. Cutting feed receives the
estimated engagement modifier; positive machine `max_feed` caps cut/link and
plunge G1 requests. These calculations still need calibrated tool/material data.
See [cutting data](cutting-data.md), [leads/material state](material-state-and-leads.md)
and [engagement/feed controls](engagement-and-feeds.md).

## Pocket

**Purpose:** clear a selected closed XY region to an end depth.

Select a horizontal face boundary or a closed set of feature edges. Include
island/hole boundaries when they should remain excluded from clearing; the
kernel determines nesting from the supplied loops, not from an unselected
whole CAD solid.

### Bounds and automatic removal height

![Pocket limits marked around the flange and raised boss](../pictures/cam-pocket-bounds-example.png)

The red lines are annotations in the supplied example, not the app's selection
colour. The intended pocket is the annular region **between the outer flange
rim and the boss**, from the material surface down to the flange top—not
through to the part's bottom.

Two ways to select it:

1. **Faces:** click the exposed annular floor face. Its outside boundary limits
   the pocket; the raised boss is retained as an island.
2. **Edges:** choose Select edges, click the outer flange's top rim and the
   boss's outer rim. Closed projected loops bound the annulus, even when the
   rims have different Z heights. Do not select the boss's whole top face as
   a substitute for its outer edge: a face contributes all its boundaries.

New Pocket operations start at **Material surface** and end at **Machining
selection → Minimum Z**. For a boss top at Z0, flange top at Z-15 and part
bottom at Z-30, the selected region is cleared only to **Z-15**. Depths update
as the selection or placement changes. Numeric offsets allow axial allowance;
changing to an explicit source allows a deliberate manual override. Existing
saved operations retain their original sources rather than silently changing
cutting depths; click **Use pocket selection depths** to set both sources at
once, or choose the new sources individually. This button replaces both depth
definitions and resets their offsets to zero.

![The annular floor selected in the current application](../pictures/cam-pocket-floor-selected.png)

The actual selected floor is yellow. The blue boss remains an island; the
amber outline is the original stock. Here the lowest selected Z is -15.

![One generated pocket pass between the outer boundary and the boss](../pictures/cam-pocket-generated-pass.png)

A generated wall-parallel pass clears the annulus and retains its centre.
Green shows concentric cutting loops; entry/retract and linking moves are
hidden in this image for clarity. The final pass is at Z-15, leaving the base
down to Z-30 intact. This is a path preview, not a
stock-removal or fixture simulation.

For a selected horizontal floor face, hole boundaries descending **below** the
floor do not create stock islands above those holes. Raised boundaries (such
as the boss) remain protected. This avoids leaving uncut stock columns above
bolt holes during floor clearing. Explicit edge loops remain user-defined
island boundaries. This is a limited 2.5D boundary rule, not general retained-
solid collision detection; inspect islands and entries carefully.

The cutter-centre region is inset by **radius + Stock to leave**. The default
**Wall-parallel contours** strategy repeatedly offsets the complete region,
including island walls. On the illustrated circular flange/boss this creates
concentric closed paths rather than straight raster lines. On a square pocket
with a circular island, fronts change shape and split into mixed straight/curved
contours where they meet the other wall. Paths are clipped by the region's
changing topology, not allowed to continue blindly through the island.

Nominal spacing is `diameter × stepover / 100`: a 6 mm tool at 40% uses 2.4 mm.
Contour spacing is capped at 50% diameter (with a log message) so two advancing
fronts cannot leave a wide uncut strip when they disappear between offsets.
Each depth repeats the XY contours. Nearby loops are ordered together and
connected at cutting feed when Stay down is enabled and the complete link
passes clearance checks. Depth/operation/tool changes and blocked/disconnected
links retain safe-Z entries. These are not a continuous spiral or fitted
`G2/G3` controller arcs.

**Raster lines** retains straight-line clearing plus wall boundary passes.
It honours its full stepover range. Operation-driven scan lines are oriented
using estimated remaining material, rather than assuming fixed +X is always
climb. Meander alternates successive one-sided cutting hands; neutral slots do
not set the hand.
See [toolpath strategy and direction](toolpaths.md) for the full rules.

Restrictions and checks:

- All required boundaries must be closed; open chains are rejected.
- Insetting that leaves no region produces a “pocket too small” error.
- Stepover must be >0 and ≤100% (the GUI offers 1–100%).
- Pocket offsets use Shapely/GEOS so fronts can merge, split and disappear.
  Invalid/self-intersecting loops or overlapping non-nested selections are
  rejected rather than silently repaired into a different removal region.
  Very narrow regions can disappear after cutter compensation; inspect output.
- An offset region existing does not prove the cutter can access it with safe
  entry or that the retained material/fixtures are collision-free.

**Example:** Start 0, End -6, stepdown 1.5, radial stock 0.2 with a 6 mm tool
leaves the cutter centre 3.2 mm from the selected retained boundaries and
uses four depth passes. It does not reserve an axial 0.2 mm floor allowance;
set End to -5.8 if that is required.

### Overcut into void material

**Pocket overcut into void** grows the pocket region outward by the given
distance, then removes every part cross-section sampled just above each pass
depth from the growth and limits it at the allocated blank. The result is:
the pocket extends into stock that will be removed anyway, never into the
model. The grown region is cleared with the operation's own strategy
(wall-parallel contours or raster, same stepover, direction, stay-down links
and engagement planning) — there is no separate overcut path.

Two different allowances apply at the two kinds of boundary:

- **Part walls and islands** keep the *roughing clearance* (stock to leave):
  the cutter edge stays that far from the model.
- **The blank edge** uses the *Material boundary limit* instead. Roughing
  clearance is not applied there, because there is no part to protect. With
  limit 0 the cutter edge reaches exactly the blank edge; −1 mm leaves a 1 mm
  skin of material; +1 mm lets the cutter pass 1 mm beyond the blank (useful
  when the blank is slightly oversize or its edge must be cleaned up). For a
  3 mm tool and limit 0 the outermost tool-centre contour is 1.5 mm inside the
  blank edge.

The limit is applied to the blank's XY rectangle, offset with sharp corners,
so the region follows the blank corners rather than rounding them; the
cutter radius still rounds the cut corner itself. Without an allocated blank
there is no limit to apply. The limit also trims an ordinary (non-overcut)
pocket whose selected region extends past the blank edge.

![Overcut stopped by the material boundary limit](../pictures/cam-overcut-material-limit.png)

Actual capture, top view of the deepest pass: flange-floor pocket, 3 mm tool,
6 mm overcut, 0.3 mm roughing clearance, 4 mm blank margin, limit 0. The
outer contours grow round the flange until they meet the blank, where they
run straight along it with the cutter edge on the blank edge; the boss side
keeps its 0.3 mm clearance. Yellow segments are Conflict highlights. On the annular flange example an
overcut of 3 mm pushes the outer contours past the flange rim into the blank
while the boss side is unchanged, so a following outside Profile does not
meet a thin standing wall where the two operations abut. The added area is
logged. This is a planar, per-operation feature: it does not sequence
operations, and the cross-sections are conservative unions over the sampled
depths, so a part that widens below the floor blocks the overcut at that
width for the whole operation. Invalid STL sections fall back to their convex
hull, which only ever protects more material.

Not implemented: adaptive clearing, trochoidal motion, rest machining,
automatic rough/finish stock tracking, helical entry or machining from a full
3D stock-removal simulation. Air-cut removal across operations is described
in [selection and depths](selection-and-depths.md#start-and-end-depth-fields) and
[global settings](../settings.md).

## Profile

**Purpose:** follow closed boundaries with optional radial cutter compensation.

| Side | Centreline behaviour |
|---|---|
| Outside | Away from material by radius + radial stock; outer boundaries grow, holes shrink |
| Inside | Into material by radius + radial stock; outer boundaries shrink, holes grow |
| On | Follow selected line directly; radial stock is not applied |

The outside/inside meaning is based on loop nesting/material, not merely
clockwise versus counterclockwise input. Multiple selected cube edges can
join into a closed contour. A single open edge does not become a complete
outside profile automatically; use constant-Z Engrave when following an open
line is appropriate.

The generator copies the compensated XY path to each depth pass. It does not
derive a new wall surface at every Z from a general 3D part. Thus tapered,
undercut or changing-width geometry is not a general supported profiling case.

**Example:** an outside square boundary and 6 mm endmill use a centreline about
3 mm outside each retained straight wall at zero stock allowance. A 0.3 mm
allowance increases that offset to 3.3 mm. That can still place the cutter
inside the allocated raw blank: the vertical entry must be evaluated, not
assumed to be in air.

Climb/conventional/meander requests follow the machine default or operation
override; actual clearing hand is chosen from estimated remaining material.
Full-slot paths do not define the cutting hand. The assumed spindle is M3. See [direction rules](toolpaths.md).

Not implemented: holding tabs, bridges,
controller G41/G42 compensation, and
fixture-aware routing. Breaking through the bottom may release the part;
workholding is your responsibility.

## Slot

**Purpose:** follow a selected constant-Z open/closed edge chain with the full
tool diameter, stepping down to the selected end depth. There is no radial
Profile compensation; choose a tool/centreline that defines the intended slot.
A horizontal face contributes its boundary lines, not a filled pocket.

Slot is distinct from a Pocket operation whose first pass happens to be full
width. Automatic axial defaults use the tool/material **Slot % D** (initially
15%), while a Pocket still uses its Pocket axial default. Estimated Slot/High
feed modifiers apply to the actual contact, not merely the operation's name.
Full-width contact is hand-neutral. Contour-constrained leads are available
when the chain has sufficient length; drilling and non-centre-cutting
capability are not certified by this operation type.

## Drill

**Purpose:** drill at the centres of selected circular horizontal rims.

Each selected loop is fit to a circle in XY. It must contain at least eight
points. The radial spread tolerance is the greater of 0.01 mm and roughly
1% of mean radius. A rectangular face is not a hole just because it has a
centroid. The cutter diameter may not exceed the selected hole diameter by
more than the small numeric tolerance; a smaller pilot drill is allowed.

At each depth step, output rapids to safe Z, positions XY and plunges at the
tool plunge feed. Subsequent steps repeat with safe-height retracts. These
are explicit straight moves, not `G81/G83` canned cycles. With multiple holes,
execution is pass-major: holes at the current depth are visited before the
next depth step.

Check that the tool is truly suitable for drilling. A stored type label alone
does not validate centre-cutting capability, runout, flute length or material
parameters. A coarse or irregular STL circle may fail fitting; repair/refine
the source rather than bypassing the shape check.

Not implemented: helical boring, tapping, automatic spot drilling, dwell,
controller-specific peck cycles or exact analytic hole selection from STEP.

## Engrave

**Purpose:** follow open/closed constant-Z edge chains or horizontal face
boundaries at user-defined cutting depths.

Engrave follows the selected XY line without radial compensation. A V-bit
label and V angle do not automatically calculate carving depth or width;
this is line-following engraving, not variable-depth V-carving. Selection
must have constant Z, but depth sources/offsets determine where the copied
XY line is actually cut.

New Engrave operations default to a shallow **-0.2 mm relative to model top**.
Verify this for your cutter/material. Deeper End values can create multiple
stepdown passes. To trace only a single open edge, select that feature chain;
selecting a whole face engraves all its boundary loops.

Not implemented: text/font import, projected curves over 3D surfaces,
variable-Z engraving, ballnose surface following or collision-aware linking.

## Output and safety checklist

For every operation, verify geometry, side, actual tool diameter, resolved
start/end Z, entry depth, max DOC, feeds/RPM, safe height, retained material,
and whether through-cutting releases the part. Toolpath generation is not a
substitute for independent machine-aware simulation and an air cut.

[Depth selection](selection-and-depths.md) · [Stock checks](stock-and-safety.md)
