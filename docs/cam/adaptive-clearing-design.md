[Documentation](../README.md) / [CAM](README.md) / [Clearing toolpaths](toolpaths.md)

# Adaptive clearing: design and comparison cases

The target is **consistent cutter engagement during cutting, with as little
non-cutting time as practicable**. A recognizably curved toolpath is not
sufficient. The current **Trochoidal** option is still a clipped spiral with
local cleanup and checked links; it does not choose the next cutting move to
control engagement. The experimental local peel selector below is not wired
into the CAM operations and does not change the generated toolpath.

## What to take from the examples

The reference screenshot shows groups of sweeping passes around different
lobes of a pocket and short transitions between them. The broad area gets
broad curves; the neck and ends get tighter ones. It is not one ellipse
centered on the entire pocket. The screenshot alone does not identify the
CAM package, the link heights, or which colored moves actually touch stock.

- [Held and Pfeiffer, *Trochoidal Tool Paths for Pocket Machining with Full Control of the Engagement Angle* (2025)](https://doi.org/10.14733/cadaps.2025.731-747): the closest research reference. Figure 3 shows local machining circles and tangent transitions; Figures 5 and 7 compare paths and engagement distributions. The algorithm adjusts the advance based on the material left to cut and maintains the swept boundary. Its published construction assumes no islands; island handling would need independent validation here.
- [Elber, Cohen and Drake, *MATHSM* (2005)](https://gershon.cs.technion.ac.il/papers/hsm.pdf): places circular sweeps using local pocket clearance and connects them tangentially. It explains why one global spiral is a poor fit for a pocket with a narrow neck. Its fixed spacing is not an engagement bound.
- [Autodesk Fusion Adaptive Roughing reference](https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/GUID09E44604-DAD8-47D6-ADC6-C100869DE724.htm): treats optimal load, minimum cutting radius, horizontal leads, stay-down clearance/distance and no-engagement feed as separate controls. Toolpath geometry and link decisions both affect cycle time.
- [FreeCAD Adaptive Clearing](https://robertmassaioli.github.io/freecad-docs/cam/tools/adaptive-clearing/) and the [standalone bindings](https://github.com/kirberich/freecad-adaptive-clearing): a practical comparison candidate. The bindings expose cutting, clear-link and not-clear-link moves separately. They are not a GCodeProducer dependency; their clear-link classification would still need independent verification before producing stay-down moves here.

## Replacement direction

1. Track the remaining material at the active depth. Bootstrap with a deliberate
   entry cut; do not count its unavoidable engagement as steady-state peeling.
2. Advance along the exposed stock edge with overlapping local sweeps and
   tangent transitions. Choose the radius and advance from local clearance and
   remaining material. Reduce advance or choose a tighter sweep before a corner
   or neck overloads the cutter. Measuring engagement only after the path is
   drawn can change feed and warnings, but cannot eliminate a bad cut.
3. Separate cutting and repositioning. Favor the next nearby peel if it cuts
   useful stock without an engagement spike. For a reposition, check the full
   cutter sweep through already cleared material and compare **time**, not just
   distance or number of retracts, with lifting and re-entering. Use a small
   controlled roll-on from the cleared side if the next peel needs entry. Don't
   use a fresh-stock shortcut to keep the tool down or insist on long retraces
   just to avoid a retract.
4. Preserve the existing model, tab and stock boundary checks, and replay the
   actual emitted G-code independently. Handle residual corners locally; if the
   planner cannot verify a cut or link, report the fallback rather than calling
   an unverified path adaptive.

## Local peel prototype

`gcodeproducer/core/cam/adaptive_peel.py` advances the center during each
curved turn, keeping the seam and tangent continuous between successive
turns. For a supplied heading and loop radius it tests a bounded set of
advances against the cutter-centre region and updates simulated stock after
each chord. It chooses the legal candidate that removes the most area per
millimetre traveled without exceeding the sampled engagement limit. If no
candidate fits or cuts usefully, it returns no cut. This uses the existing
occupied-width proxy, not an analytical engagement-angle bound.

Run `python tools/compare_adaptive_peels.py` for a reproducible four-turn
comparison inside the broad lobe of the synthetic pocket. It starts in a
pre-cleared patch. The adaptive case peaks at 13.5% sampled engagement versus
17.3% for fixed advance, but removes less material in those four turns. This
is a test of stock-driven advance, not a demonstration of steady engagement,
equal coverage, or time savings.

The selector can also try a bounded fan of headings and change the radius
smoothly during a turn. The local trace carries forward the exact endpoint,
tangent direction and remaining stock; if no useful turn fits, it stops
rather than inventing a connector. In the wall test, fixed heading and
radius cannot advance; the steered trace shrinks from 2 to 1.4 mm and makes
two connected turns before stopping. It removes only 0.30 mm², so this is
not yet a practical whole-corner result.

`adaptive_branch.py` now ranks **supplied** branch starts by useful area
removed per estimated minute, including the whole candidate turn and its
transfer. Each trial starts from the same material; only the winner returns
updated stock. `adaptive_link.py` checks the full planar cutter sweep (with
a rounding margin) for straight and one-waypoint routes. It compares a
verified route against an XY transfer at a caller-qualified safe plane plus
the Z lift and return. A destination with no verified clear landing is not
eligible, even via retract. This does not certify fixtures or a safe plane,
and the time estimate excludes acceleration.

In the cleared corridor example, a 30 mm stay-down detour takes 1.50 s and
beats the retract at 150 mm/min Z feed; at 1,200 mm/min the retract is faster
(1.36 s). Both cases preserve the same coverage because travel removes no
stock.

`adaptive_frontier.py` discovers candidate turns along the edges of existing
cleared patches, allowing separate patches to compete rather than spending
all trials in the nearest one. It also offers an exact continuation at the
last turn's endpoint, with no repositioning cost. In a four-turn test in the
broad lobe of the example pocket, starting in a pre-cleared patch, it removes
20.73 mm² at 17.5% peak sampled engagement with one short initial transfer
and no transfer between turns. This does not yet establish whole-pocket
coverage or faster machining.

`adaptive_entry.py` can now start from fresh stock in the offline prototype.
It picks an orbit inside the cutter-centre region, limits the descent using
the actual chord lengths and the supplied lead-in angle (10° by default), and finishes a full
lap at cutting depth before moving to the cleared center. Only the flat lap
is credited as removed material at that depth. The caller must qualify the
flat cutter for ramping, flute reach, and safe approach to the stock surface.
A 20 × 12 mm test cleared 11.29 mm² at depth with the entry and another
2.79 mm² with two stay-down peels. The bounded two-lobe benchmark starts
from fresh stock at 4° and removes 11.29 mm² with the entry lap and 7.94 mm²
with four peels; 99.54% of the cutter-centre area still contains stock at
that cutoff. This is an entry-to-peel test, not a full-pocket result. The
adaptive prototype is still not wired into CAM output.

## Comparison cases and gates

[adaptive-neck-pocket.wkt](../../examples/adaptive-neck-pocket.wkt) is a
synthetic planar outline in millimetres, inspired by the screenshot rather
than copied from an original CAD file. At this scale a 4 mm cutter can traverse
its narrow neck. Use it along with a square corner, a pocket with an island,
separated areas and the saved three-depth Waterfall case. The WKT is geometry
for Shapely or test scripts, not a GUI import format.

Geometry-only baseline on the synthetic pocket, with a 4 mm cutter, no
allowance, climb and 40% stepover:

| Generator | Centreline length | Output groups before travel planning |
|---|---:|---:|
| Wall-parallel contours | 2,559 mm | 21 closed contours |
| Current Trochoidal | 4,150 mm | 26 paths; 25 gaps without a cleared route |

Both nominal cutter sweeps cover the cutter-centre region in this check.
Contour count is **not** retract count, and centreline length is **not** cycle
time. The saved Waterfall baseline gave approximately 5:46 for wall-parallel
and 7:50 for the current spiral heuristic in Preview, not on hardware.

Judge a replacement at equal coverage, depth limits, tools, feed inputs and
clearance rules. Record the length-weighted engagement spread around the
cutting target, high-percentile/peak engagement and distance in full-slot cuts.
Keep entry, deliberate finishing and air moves separate in the report; air
must not make engagement look more consistent. Also report time spent cutting,
in clear travel and in retract/re-entry, along with total estimated time and
replay warnings. Inspect the path by the neck and in each corner. A candidate
is not ready simply because it has fewer rapids or looks more like the reference.
