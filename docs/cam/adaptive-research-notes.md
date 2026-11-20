# HSM/adaptive rewrite: research and decision gates

Scope: replace only the adaptive toolpath generator. This is a research and
planning checkpoint. No changes to generated motion, cutting data, or saved
jobs. The previous planner is a failed comparison case, not a release target.

## What the references actually support

- [FreeCAD Adaptive2d source](https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/src/Mod/CAM/libarea/Adaptive.cpp) computes a reference cut area and compares incremental cut area per distance with a target derived from `stepOverFactor`. It also expands a model of the cleared area as it advances. This is a useful working example of stock-driven motion, but the factor is **not** a cutter contact angle and does not certify our limit. The source file identifies itself as LGPL-2.1-or-later; do not infer the license of every dependency or the standalone package from that header.
- [FreeCAD cleared-area API](https://freecad.github.io/SourceDoc/d8/d56/classAdaptivePath_1_1ClearedArea.html) exposes both the accumulated cleared area and bounded queries near the tool. This suggests a useful separation: carry global stock for coverage, use a local stock query for efficient decisions. Don't cache changing stock as if it were static geometry.
- [Sandvik on inside corners](https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-inside-corners) explains why engagement grows in a concave turn even if the straight passes on either side are acceptable. Round the *cutting toolpath* with tangent transitions, then check the resulting cut against remaining stock. A round curve alone is not proof of low engagement. A larger roughing radius can deliberately leave material for a smaller tool; it must not be reported as cleared.
- [MATHSM, Elber, Cohen and Drake](https://doi.org/10.1016/j.cad.2004.05.008) uses a pocket's medial axis and tangent connections to organize circular cuts. [Held and Pfeiffer](https://doi.org/10.14733/cadaps.2025.731-747) adapt advance to bound engagement and track already cut stock. That is relevant to necks and lobes, not evidence that a fixed local-loop search will finish. Their published engagement-control construction does not directly cover islands.
- [FACEOM, Jacsó et al.](https://doi.org/10.1007/s00170-019-03834-8) proposes non-equidistant offsets to control engagement along adjacent passes. The publisher blocked full-text access during this review; only the abstract was available. Treat this as a candidate for advancing along one front, not a demonstrated recipe for covering an entire pocket.
- [Fusion Adaptive Roughing](https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/GUID09E44604-DAD8-47D6-ADC6-C100869DE724.htm) separates load, cutting radius, depth, and linking. Its 3D depth schedule is not our Waterfall schedule and is outside this rewrite. Do not copy advertised material-removal rates or stepdowns into defaults.

## More examples: what the paths are doing

These examples are qualitative references, not downloadable benchmark paths.
Vendor cycle-time claims do not establish a result for our jobs. OPEN MIND
and Cimatron both credit Celeritive, so those two aren't independent evidence
of distinct algorithms.

| Example and source | What to look for | Fixture to add |
|---|---|---|
| [Mastercam Dynamic Milling worked tutorial](https://eng.auburn.edu/~griffgj/training/Dynamic_Milling.pdf), pp. 6–8 and exercises 3–5 | Area Mill starts in a pocket and works out; Core Mill approaches from outside and avoids islands; Rest Mill targets previous-tool stock. Micro-lifts are optional non-cutting moves, not a way to cut through remaining stock. | Pair a closed pocket with an open-edge version; add a third run with a pre-cleared pocket and only corner stock remaining. |
| [Siemens NX adaptive milling interview](https://blogs.sw.siemens.com/nx-manufacturing/manufacturing-engineering-two-roads-to-toolpath-evolution/) and [Planar Mill Adaptive Pattern](https://community.sw.siemens.com/s/article/Planar-mill-adaptive-pattern-in-NX-CAM) | The interview describes changing-radius crescents that advance through stock and warns about leaving thin unsupported pillars or walls. Visual complexity alone is not failure; repeated air sweeps or islands of reachable stock left behind are actionable. | A neck feeding a second lobe and a thin residual strip. Require the preview to show how the cut advances and flag thin residuals for review; don't add an automatic helix based on the interview. |
| [SolidCAM iMachining illustrated examples](https://tj-solution.ch/en/knowledge/imachining/) and [patent figures](https://patents.google.com/patent/EP2681683B1/en) | The diagrams show region-scale spirals paired with local channel and island handling. The lesson is to plan the region topology before committing to strokes, not to force a global spiral into every boundary. Use these as behavior references; don't implement the patented construction without review. | Rectangle with an offset island; verify both sides are visited without crossing the island or trapping reachable stock behind it. |
| [Cimatron VoluMill Rough mold-insert example](https://help.cimatron.com/en/2026/Procedures/Volume/Volume_Milling_Volumill_Rough.htm) and [OPEN MIND hyperMILL HPC demo page](https://www.openmind-tech.com/en/cam/hypermill-maxx-machining/roughing-hpc/high-performance-milling/) | Cimatron shows roughing paths alongside resulting stock and explicitly expects a finish pass. OPEN MIND describes using both spiral and trochoidal motion while avoiding full-width cuts and abrupt changes. | A roughing allowance fixture: distinguish material intentionally left for finish from material the rougher failed to remove. |
| [Sandvik wide-slot application example](https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-holes-cavities-pockets/slicing-trochoidal-milling) | The documented sequence is curved entry, straight side cut at low radial engagement, curved exit, then reposition. For narrow slots Sandvik shows a different strategy and distinguishes programmed pitch from maximum immersion. This is a concrete counterexample to drawing loops everywhere. | A long wide slot: test sustained straight cutting, tangent entry/exit, and no engaged reversal at the end. Use a separate narrow-slot fixture, not the same motion with smaller spacing. |

For review, save a **numbered, stock-overlay plot** per fixture: start,
engaged cuts, air links, lifts and stock remaining after selected passes.
The reviewer should be able to trace what each stroke removes and why the
next entry is there. Flag near reversals under engagement, repeated sweeps
removing negligible material, and long air returns. Plot review complements
swept-stock replay; a smooth-looking plot cannot override it.

### CamBam Trochoidal Pocket & Profile (MatMill)

The supplied DLL reports file version **2.4.0.0**. Static inspection shows
symbols for a medial tree, branch slicing, a spiral, and biarc connectors.
The DLL was not run. The [author's release thread](https://cambamcnc.com/forum/index.php?topic=6209.0)
links to the [MIT-licensed MatMill repository](https://github.com/jkmnt/matmill).
The [source snapshot reviewed](https://github.com/jkmnt/matmill/tree/32179008194151e8cee3ae3635170c89eb15f355)
reports assembly version 2.2.0.0; it is an algorithm reference, not a verified
source match for the supplied binary or a license audit of its dependencies.

MatMill opens a local cleared area with an expanding spiral, then advances
circular cutting slices along a **medial tree**. The tree gives each slice a
reason to be there: it opens more of a known branch toward the pocket ends.
`topo.cs` builds the tree, `slicer.cs` searches along each branch for the next
engagement-limited slice, and `path_gen.cs` can connect slices with biarcs or
chords. This is a concrete alternative to the old planner's local loop search.
Do not equate its slice engagement estimator with independent swept-stock
replay: the reviewed source can stop tracing a branch if no slice meets its
stepover limits. A smooth connector also says nothing about holder clearance.

**Comparison plan:** add MatMill alongside FreeCAD, not behind it. First use
native CamBam output from a closed pocket with a branch and a long straight
side, with the entry, cutter and allowance recorded. Plot the spiral, cuts,
and links separately and replay the actual output against the same stock.
Then try the two-lobe and off-center island fixtures; record any residual,
including stock beyond a branch the tool never reaches. Use the medial tree
as a candidate for organizing local strokes, not as a requirement to slice
long straights into loops. No DLL dependency or source port at this stage.

### Supplied CamBam flame example: measured output

The supplied image shows a flame silhouette, not a dimensioned machining
boundary. The G-code is a one-depth TrochoPock program: 3.175 mm cutter,
Z−0.5 mm, 900 mm/min for the XY feeds. It spirals inward while descending
(24 G2 moves), then reverses direction and winds back out at depth before
branch slicing. There are no intermediate Z lifts. At depth there are 512
G3 moves (about 6,084 mm) and 115 straight G1 moves (about 2,601 mm).

With the XY arcs expanded under the incremental-I/J convention and each
stroke buffered by the cutter radius, all 115 straight segments stayed
inside the prior same-depth sweep in this reconstruction. The two longest
were 92.6 and 74.4 mm. The straight return chords alone made up about 30%
of the at-depth feed distance, even with zero retracts. They are not examples
of long straight **cutting** passes. Report those separately: model each link
against remaining stock and compare its cost with a shorter verified link
or a retract, without penalizing productive straight cuts.

The supplied native `.cb` clarifies the test: the machining boundary is a
six-vertex concave polygon, not a trace of the flame image. The operation
lists zero roughing allowance, a 3.175 mm end mill and target Z−0.5 mm.
No explicit stock dimensions are set. For a closed-pocket benchmark, assume
initial material fills the polygon and use the area a disk can sweep while
remaining inside it as the geometric coverage reference.

An exploratory sweep at Z−0.5 mm gives **6,092.3 mm² geometrically reachable**
out of 6,099.0 mm² nominal. At 0.0025 mm arc chord error about **10.9 mm²** of
reachable area remains, versus 12.3 mm² at 0.01 mm. This is a preliminary
coverage measurement, not a pass tolerance or a clearance check. Reproduce it
with `python tools/check_cambam_pocket.py pocket.cb pocket.gcode`. Run again
with a finer `--chord-error` to inspect sensitivity; `--details replay.json`
creates a new file with residual geometry and each stroke’s newly swept area.
Use `--overlay replay.svg` for a numbered plan view separating new sweeps,
returns through prior sweeps, and reachable residual. Labels show sampled
source line numbers; every stroke has a source line in its SVG tooltip.
Replay uses only constant-depth XY strokes, not descent or lifts. Add
`--contact-step 0.3` to sample contact angle against progressively removed
stock. Peak and distance-weighted P95 include at-depth links. Replay also
reports a separate peak and P95 outside the projected entry footprint. A
whole stroke is tagged uncertain if its sweep overlaps a feed projection
from above the plane that has not already been swept at depth. The projection
only tags uncertainty; it does not remove stock. Repeat at finer spacing
before interpreting a spike.
These are planar diagnostics, not a machine clearance or load guarantee.

## Proposed design decisions

1. **Separate coverage, load, and linking.** Use stock area removed per path length as a ranking aid; use occupied cutter-periphery angle during ordered stock replay to assess engagement. Neither is a force estimate. Keep legacy percentages separate. A diagnostic circle that straddles a straight stock face before a sweep measures all contact; an actual steady side cut has a previously cleared side. Test both so the metrics aren't accidentally conflated.
2. **Plan the entire reachable region, not the next isolated loop.** Compare FreeCAD on identical input first. If a native replacement is necessary, connect the regions that survive tool-radius erosion, identify necks and isolated lobes, and keep an explicit list of what remains to clear. Long straight cuts are allowed; use smooth roll-on/roll-off and tangent corner transitions where cutting continues. If a corner cannot be rounded within the region and limit, reduce local advance, choose another approach, or leave a reported residual. Never insert a slot just to connect paths.
3. **Keep geometry and machine motion separate.** The offline comparison accepts ordered XY stroke proposals tagged cut, candidate link, or entry. No imported controller G-code. A backend's clear-link label is only a proposal: independently check the full cutter sweep against protected geometry and the stock left before that move. Compare verified stay-down time against retract/re-entry time. No unchecked fallback at adaptive depth.
4. **Pin the backend experiment.** Record FreeCAD and wrapper revisions, geometry tolerance, cutter radius, allowance, ring/hole convention, and how stock and boundaries are passed to the backend. Check the installed Clipper generation and bindings against the source examined here; do not assume they are identical. Check reproducible Windows builds, cancellation and license notices before considering a production dependency. Keep the comparison out of the installed app initially.

### Corner handling: circles are optional

A circular slice can be useful for advancing along a branch, but it need
not remain circular as it approaches a wall or corner. Compare two options
from **the same partially cleared stock and incoming tool pose**:

1. **Local profile cleanup.** Stop the roughing pass before engagement
   rises and use a short rounded, boundary-following cut only where stock
   remains. Enter from verified clearance and taper the cut on and off.
   Prefer this simple option if it clears the corner within the limit;
   don't run a full perimeter lap for one small remnant.
2. **Blend into the corner.** Start moving toward the tool-center offset
   of the wall before the circular slice runs out of room. Join the pass
   and the boundary-following section tangentially, using a varying-radius
   blend or tangent lines/arcs. Reduce local advance to hold engagement,
   not just to make the preview look smoother. Follow straight walls with
   straight cuts where appropriate.

Test both on a rounded inside corner with a long approach and on a sharp
nominal corner. In the sharp case, distinguish stock the cutter cannot
reach from reachable stock left because the proposed turn needs more room.
Reject either option if it crosses the protected boundary, has a sharp
engaged turn, exceeds the engagement limit, or misses reachable stock past
frozen tolerances. An overloaded profile isn't a cleanup fallback: take
smaller cuts or report the remaining stock. Compare verified candidates by
cut time and transfer time, including any extra entry, not by arc count.

### Fixed corner and slot inputs

`tools/hsm_corner_fixtures.py` defines four one-plane inputs for a 2 mm
cutter. The corner pair shares a 24 × 14 mm envelope, a local 0.5 mm stock
band, and the same cleared incoming pose. Only the corner radius changes
(0 or 4 mm). The slot pair has 6 mm and 2.4 mm widths and a pre-cleared 5 mm
approach. Tests lock initial and geometrically unreachable areas to 0.001 mm²
for these inputs; that is a fixture regression tolerance, not permission to
leave stock, gouge, or exceed engagement. In particular, do not assume a
slot barely wider than the cutter admits a path at the same engagement as
the wide slot. `replay_strokes` accepts that explicit remaining stock;
newly swept geometry in the pre-cleared approach is travel, not removal.
A reference tangent arc leaves 0.0001 mm² reachable residual in the rounded
fixture but 2.228 mm² in the sharp one. The slot reference separately checks
that a pre-cleared move registers zero contact and a fresh centerline slot
matches the analytical contact for the chosen sampling step.

`tools/hsm_corner_trial.py` compares the 3 mm reference turn with and
without a 0.2 mm tangent local cleanup. The latter leaves 0.095 mm² instead
of 2.228 mm² with no measured outside sweep; both connector strokes remove
no stock in the model. But the cleanup peaks at 136–137° at 0.025 and 0.05 mm
sample spacing. It fails the illustrative 95° trial limit despite improving
coverage. Three staged tangent passes (1.8, 0.8, then 0.2 mm radius)
leave the same 0.095 mm² and peak at 89.1–90.0° across 0.0125–0.05 mm
sampling, with no measured outside sweep. The passes add 44.0 mm of feed
including 27.2 mm of cleared returns after the reference cut. Fixture-specific
cubic tangent returns reduce that to 18.5 mm; their sampled chord chains
remove no stock, and the residual and contact peak are unchanged at both
0.05 and 0.0125 mm contact spacing. This tests shorter links, not a general
replacement or machine-time improvement. The separate offline tangent-link
checker measures the whole chord chain's clearance from stock and pocket
boundaries, including holes. It found the first trial return roughly 0.000021
mm short of cutter-radius clearance in reconstructed stock, even though the
polygonal sweep reported zero removed area. Treat it as a rejected proposal,
not grounds for reducing the clearance requirement. Moving the join 0.1 mm
upstream lets all three returns pass the unchanged planar check with zero
extra margin. Added air travel is 18.65 mm rather than 27.21 mm with the
staged baseline, without changing the measured residual. This is a fixture
result; no machine clearance or positive boundary margin is inferred.

A separate off-center island fixture tests two tangent legs meeting at a
provided waypoint. The direct and narrow-side proposals fail; the 21.90 mm
wide-side detour passes with 0.1 mm extra planar margin. Both legs are
checked against the same stock, and a stock rib blocking either leg rejects
the entire detour. This does not yet find waypoints automatically.

### Connected cutter-center regions

`tools/hsm_center_regions.py` erodes the pocket by cutter radius plus any
clearance margin and maps seed locations to the resulting components. The
saved two-lobe WKT is connected for a 4 mm cutter but split for a 14 mm
cutter. A zero-width neck does not count as a connection. This is a map of
geometric access, not a claim that a stay-down route through live stock is
clear or that either lobe has a valid entry. The offline work map assigns
live stock to each region's sweep envelope and accepts only supplied seeds
whose cutter disk clears the actual pocket boundary and current stock. An
unseeded region with stock needs an entry or another verified seed. Sweep
envelopes can overlap, so use their union for total reachable stock.

`tools/hsm_straight_front.py` extracts exposed stock edges with material
on the left and proposes a straight side cut at a specified radial
immersion. The straight fixture removes 4.61 mm² in a 19 mm stroke at
42.3° sampled peak; the untrimmed stroke into the end wall is rejected.
The offline front-cut gate rejects overload, out-of-bounds sweeps and
zero-removal passes before updating stock. The straight fixture recomputes
the stock edge after each accepted cut and advances it twice by 0.25 mm.
This does not validate travel to the start of either stroke.
`tools/hsm_front_corner.py` joins two straight legs with a tangent fillet
and checks the entire chord chain against progressive stock. In the
rounded fixture the 3 mm turn removes 11.89 mm² at 69.8° sampled peak
(0.05 mm spacing); a too-tight turn or a lower contact limit rejects the
whole proposal rather than committing the first leg. Corner waypoints can
also be derived by offsetting and intersecting adjacent exposed stock edges.
On the rectangular stock fixture a generated candidate removed 4.241 mm²
at 45.14° peak sampled contact, with no hand-specified corner waypoints.
`tools/hsm_front_choice.py` checks travel to each start and then samples
the proposed cut against the same live stock. It ranks accepted options by
stock removed per millimeter of link plus cut, not by a machine-time
estimate. When no checked candidate succeeds, it does not imply a retract.
`tools/hsm_front_run.py` repeats that selection against updated stock and
pose with a bounded cut budget. A deliberately restricted two-pad fixture
removes 2 of 16 mm², then reports a stall and retains the 14 mm² residual.
Empty stock and exhausted cut budget are distinct from a stalled planner.
Trying every sufficiently long exposed edge, with a checked approach and
space to run off the end, then clears both pads in 16 cuts at 42.85° sampled
peak contact. This demonstrates repeated progress on the seeded fixture,
not coverage on the two-lobe pocket or a general entry strategy.

## Gate before another generator attempt

Write and review the verifier/fixture specification first. The benchmark input
must include the initial material, target removable stock and protected
geometry, in mm at one known Z. The output record must include ordered cuts,
links and entries, residual polygons, excess removal outside the allowed
sweep, peak and length-weighted P95 contact angle for cuts, slot distance,
cut/link/retract time, and planning time. Validate the replay on air, a swept
straight side cut, a full slot, a rounded inside corner, and an island link.
Measure after output coordinate quantization as well as on the proposal; a
coarse sample can miss a short overload, so check convergence on a finer
replay before setting acceptance tolerances.

Then compare the two-lobe fixture and the first saved Waterfall plane with
identical stock, tool and target. Freeze tolerances before comparing output.
An incomplete path or one with unsafe transfers cannot win on time. Only
after offline coverage and engagement checks pass should we attempt a
production generator. Compare complete jobs at equal coverage; test qualified
deeper cuts separately from fixed-stepdown comparisons.
