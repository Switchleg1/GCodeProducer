[Documentation](../README.md) / [CAM](README.md)

# Pocket, Profile, Slot, Drill, Engrave and the 3D operations

These are tree operations (`core.cam.Operation`), not independent pipeline
stage presets. They share a tool group, selection system, start/end depth
sources and execution order. Geometry is generated from the placed STL;
cutting faces must be horizontal and selected edge chains constant-Z, except
for 3D Waterfall and 3D Contour, which accept sloped boundaries and are
then limited by the model surface; see [3-axis surface operations](3d-operations.md).
[Drawn reference outlines](reference-geometry.md) are also selectable constant-Z
boundaries, or can be retained as per-selection height-only references.

## Shared fields and defaults

| Field | New-operation behaviour | Meaning |
|---|---|---|
| Kind | Chosen in Add operation menu | Pocket, Profile, Drill, Engrave, Slot, 3D Waterfall or 3D Contour |
| Name | Kind's title | Human-readable tree/log/output label; rename for clarity |
| Enabled | On | Off skips the operation |
| Geometry | Empty | Operation-owned face/edge references; generation requires a selection |
| Selection list | New picks checked | One row per pick: uncheck to keep it height-only, outside machining boundaries; select a row to link Start/End or **Remove** it |
| Start | Pocket, 3D Waterfall, 3D Contour: machining selection maximum Z + 0; others: Model top + 0 | A flat Pocket selection falls back to material surface (model top without allocated stock); not safe approach height |
| End | Pocket, 3D Waterfall, 3D Contour: machining selection minimum Z + 0; Profile/Slot/Drill: Model bottom + 0 | **Engrave defaults to Model top - 0.2 mm** |
| Unlock depth of cut | Off for new GUI operations | Beside the normal-feed override. Off inherits material-specific Slot 15%, Pocket 25%, Profile 40% of diameter (Waterfall uses Pocket; Drill, Engrave and Contour use Slot); on requests an independent operation depth in mm/pass. Tool Max depth/pass still caps it |
| Depth of cut (mm/pass) | Calculated while locked; editable while unlocked | Existing manual stepdowns reopen unlocked; automatic depths reopen locked |
| Area order | Each area to full depth | Finish one area before moving to the next, or visit all areas at each depth. New-operation default is in Settings → Default operation settings; saved operations own their choice |
| RPM / normal feed / lead feed unlocks | Off | Calculated or legacy tool bases unless independently unlocked |
| Lead-in / lead-out | On | ≤10° ramp along the path itself — repeated laps (helix) on short closed contours, back-and-forth (zigzag) on short open paths — and a cleared exit; checked against current material |
| Lead length | 0 (auto) | Automatic length respects a 10° ramp slope when enough contour exists |
| Clearing / 3D Contour stepover | 40% | Pocket / Waterfall: offset/raster spacing as percentage of cutter diameter; wall-parallel spacing is limited to 50% for meeting-front coverage. 3D Contour: distance between passes |
| Cutting strategy | Pocket / Waterfall: Wall-parallel contours; 3D Contour: Meander | Pocket / Waterfall also offer Raster lines X/Y. Contour offers Meander or Raster lines X/Y. Hidden for Profile and other operations |
| Unlock cutting direction | Off | Immediately below Unlock Lead / plunge base feed. Off inherits the machine; on enables Climb/Conventional/Meander for this operation |
| Stay down between contours | On | Wall-parallel pockets: nearby loops use checked same-depth cutting-feed links; unsafe/disconnected links retract |
| HSM / Cut / High engagement / Slot feed | Inherited (0) | HSM/Cut use tool defaults; High/Slot use machine defaults; thresholds are machine settings (High above 80% initially) |
| Profile side | Outside | Outside or Inside; row visible only for Profile |
| Roughing clearance / stock to leave | 0 mm | Radial allowance left on every selected wall/island by Pocket/Profile/3D Waterfall; for 3D Contour it is left above the surface (axial) |
| Pocket overcut into void | 0 mm (global default) | Pocket only: grows the removal region outward into material that is not part of the model at any pass depth, so the pocket overlaps the next operation and leaves no thin wall between them; see below |
| Material boundary limit | 0 mm (global default) | Pocket / Waterfall: where the region reaches the blank edge, the cutter's outer edge goes to blank edge + this value. 0 touches the edge, −1 leaves 1 mm of material, +1 passes 1 mm beyond it |

Choose realistic end depths explicitly; an automatically created operation
is not a safe default machining plan. For stepdown `s`, generation uses up to
`ceil((start-end)/s)` passes, shortening the last one to reach End. More than
10,000 passes is rejected. Empty paths, invalid depths, nonpositive tool
radius/stepdown, unsupported geometry and missing tools fail instead of
silently switching to another strategy.

Each depth pass begins with an entry: a short retract above the current
material (or safe Z for the first entry after start-up/tool change), a rapid
to the ramp start just above the material, and a ≤10° lead-in along the path
(helix/zigzag when the path is short) or, with lead-in off, a plunge from the
short clearance. Wall-parallel pockets can then stay down between nearby
contours when the full cutter-centre link is inside the permitted region.
Other paths or blocked/disconnected links retract before re-entry; exits
follow the cut contour through calculated cleared stock. Only a zero-length
path enters vertically with a warning. No G2/G3 helix macro or controller
cutter-compensation cycle is inserted. See
[material state and leads](material-state-and-leads.md#lead-in).

Tool RPM/feed can be calculated from material SFM/chip load, with tool/machine
RPM ceilings and independent operation unlocks. Cutting feed receives the
estimated engagement modifier; positive machine `max_feed` caps cut/link and
plunge G1 requests. These calculations still need calibrated tool/material data.
See [cutting data](cutting-data.md), [leads/material state](material-state-and-leads.md)
and [engagement/feed controls](engagement-and-feeds.md).

Cutting direction now sits directly below the lead/plunge feed unlock. Existing
explicit direction overrides reopen checked; saved `machine` values reopen
unchecked. Its unchecked/disabled control means machine inheritance, not a
forced Climb setting.

![Cutting direction unlock below lead/plunge feed](../pictures/cam-cutting-direction-unlock.png)

This actual capture demonstrates controls and green material-edge selection;
it is not a generated or qualified cutting recipe.

## Multiple machining areas

Choose **Area order** on the operation:

- **Each area to full depth** (default): machine area A at every depth to End,
  then area B at every depth, and so on. This avoids repeatedly travelling
  between separate holes/pockets.
- **Each depth across all areas**: machine A and B at the first depth, then
  A and B at the next depth, until End.

For two pockets from Z0 to Z-3 with 1 mm stepdown, the execution orders are:
`A-1, A-2, A-3, B-1, B-2, B-3` versus
`A-1, B-1, A-2, B-2, A-3, B-3`.

For **Pocket**, an area is a connected removal region: all offset contours,
raster strokes and islands belonging to that region stay together. An annular
pocket is one area, not an area for each contour. Disconnected regions are
visited in spatial order (minimum X, then minimum Y); growing regions together
with overcut makes them a single area. For Profile, Drill, Slot and Engrave,
each independent generated contour/position/path is an area. All areas share
the operation's Start/End definitions and other settings.

Earlier-operation removal and air-cut skipping still apply. Between areas the
emitter checks current material before moving at depth; it retracts if the
move crosses uncut material. Stay-down link permissions never carry across
area/depth boundaries. The Preview depth slider follows **execution order**,
not globally increasing depth: with area-first ordering it returns to the
shallower passes when the next area begins. Calculated material outputs remain
per operation, after **all** its areas have completed.

[Holding tabs](holding-tabs.md) can split paths into further sections below
the tab tops. Those sections follow the same Area order. Upper passes still
cut normally above the rails; an extra tab-top pass is inserted if needed.
Each interrupted section keeps the operation's lead-in/out settings.

Set the default for newly created operations in
[Settings → Default operation settings](../settings.md). Changing the default
never changes saved operations. Older setups without an Area order field use
*Each area to full depth*; choose depth-first explicitly to retain their former
interleaved behaviour.

## Pocket

The [material blank's faces/edges](selection-and-depths.md#selecting-material-boundaries)
can define an outside envelope as well as part geometry. Material-boundary
pockets protect the part's section outlines (including unselected internal
bores), and still use the operation's strategy, allowances, tabs and Area order.
With both part and material geometry selected, the material rim is the outside
envelope and selected part rims/face footprints are retained inner boundaries;
one horizontal material edge can identify the whole blank rim. Mixed picking
is the default. Use height-only picks if a part reference should provide just
End Z rather than another retained boundary.

Pocket is a flat-floor operation. Use **3D Waterfall** for depth-limited
clearing down to a sloped/curved model surface. The old Pocket surface-stop
checkbox is gone; saved operations with it enabled migrate to Waterfall.
See [3D clearing and migration](3d-operations.md#pocket-migration).

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
cutting depths; click **Use selection depths** to set both sources at
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

**Raster lines X / Y** retains straight-line clearing along the chosen axis
plus wall boundary passes.
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

## Cutting strategy

The operation's **Cutting strategy** field has operation-specific choices:

| Operation | Choices |
|---|---|
| Pocket, 3D Waterfall | Wall-parallel contours, Raster lines X, Raster lines Y |
| 3D Contour | Meander, Raster lines X, Raster lines Y |
| Profile, Slot, Drill, Engrave | Row hidden (no strategy control) |

X/Y means the cutting-line axis in CAM work coordinates. Pocket/Waterfall
rasters still use remaining-material hand/feed planning and finish their wall
boundaries. Contour X/Y runs separate lines in +X/+Y, retracting/travelling
between them. Contour **Meander** alternates along the area's longer axis and
uses validated surface links. This motion pattern is distinct from the machine's
Meander *cutting direction*, which alternates one-sided cutting hands.
All Contour strategies retain the same depth bands and model protection.

![Clearing strategy choices](../pictures/cam-cutting-strategy-clearing.png)

![Contour strategy choices](../pictures/cam-cutting-strategy-contour.png)

Old saved clearing `raster` strategies reopen as **Raster lines Y**, preserving
the old scan-line axis. Old Contour `contour`/`raster` values reopen as **Meander**,
which was its previous surface-raster behaviour.

## Profile

**Purpose:** follow closed boundaries with optional radial cutter compensation.

| Side | Centreline behaviour |
|---|---|
| Outside | Away from material by radius + radial stock; outer boundaries grow, holes shrink |
| Inside | Into material by radius + radial stock; outer boundaries shrink, holes grow |

The **Profile side** row is hidden for every other operation. Legacy saved
`On` profiles remain readable and retain their original centreline behaviour;
the field shows a legacy placeholder until Outside or Inside is explicitly
chosen. Editing another field never silently offsets those saved paths.

![Profile side offers Outside and Inside](../pictures/cam-profile-side-choices.png)

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
inside the allocated raw blank: with lead-in on, the entry ramps along the
profile contour at ≤10°; with lead-in off the vertical entry must be
evaluated, not assumed to be in air.

Climb/conventional/meander requests follow the machine default or operation
override; actual clearing hand is chosen from estimated remaining material.
Full-slot paths do not define the cutting hand. The assumed spindle is M3. See [direction rules](toolpaths.md).

[Holding tabs](holding-tabs.md) retain model-owned rectangular bridges to the
stock edge; place them on side walls in Material / stock. Controller G41/G42
compensation and fixture-aware routing are not implemented. Breaking through
the bottom without adequate tabs/workholding may release the part; a generic
tab configuration is not a mechanical holding guarantee.

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

## 3D Waterfall

**Purpose:** clear the full reachable region at each depth while protecting
all model material above that level. This replaces surface-limited Pocket and
the former wall-only Waterfall paths.

Select closed outlines, set Start/End and depth per pass (automatic: the tool's
Pocket axial percentage). Stepover, wall-parallel/raster strategy, stay-down
links, material limit, cutting direction and leads apply. Overcut does not.
Material above a lower selected Start is cleared first. Full description:
[3D Waterfall](3d-operations.md#3d-waterfall).

## 3D Contour

**Purpose:** surface-following clearing in depth-limited bands. Parallel zigzag
lines follow the highest model point under the cutter plus stock to leave,
clamped upward to each successive depth floor before reaching the final surface.

Stepover sets raster spacing; depth of cut sets the vertical increment and is
capped by the tool. Material above a lower selected Start is cleared first.
There are no engagement feed factors on these XYZ paths. Full description:
[3D Contour](3d-operations.md#3d-contour).

## Output and safety checklist

For every operation, verify geometry, side, actual tool diameter, resolved
start/end Z, entry depth, max DOC, feeds/RPM, safe height, retained material,
and whether through-cutting releases the part. Toolpath generation is not a
substitute for independent machine-aware simulation and an air cut.

[Depth selection](selection-and-depths.md) · [Stock checks](stock-and-safety.md)
