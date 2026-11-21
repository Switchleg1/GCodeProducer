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
not a general entry strategy. `python tools/check_hsm_neck.py` reproduces
the straight-only baseline on the two-lobe WKT with a synthetic pre-cleared
left-side seed: one cut removes 3.00 mm² before stalling at (22, 28.5),
leaving 4,149.56 mm² of geometrically reachable stock. At the stall,
`last_selection_counts` reports six failed links and three cuts that passed
the link check but exceeded the sampled contact limit. Counts record the
first failed gate per candidate passed to the selector; they do not include
paths filtered out during proposal generation. With `--with-corners`, the
same benchmark also tries 3 mm tangent blends. It accepts two corners and
one straight, removing 10.29 mm² at 56.17° peak sampled contact before the
next origin-clearance check stops the run. Reachable residual is 4,142.28
mm². Adding `--corner-runoff 0.5` checks an extended tangent exit as part of
candidate cuts. The final pose clears the 2 mm radius threshold, but the
next selection still stalls: 62 link, 4 contact, and 2 boundary failures.
Residual is 4,141.60 mm². Adding `--with-detours` tries fixed seed-area
waypoints after direct links fail, checking both legs and choosing the
shortest passing detour. It accepts nine cuts rather than three and removes
18.00 mm² more at unchanged sampled peak. It still stalls with 4,123.60 mm²
reachable residual. Replacing fixed points with `--with-live-detours` samples
nearby cleared positions and cardinal headings each round. Both legs still
pass the same checks. It matches coverage and peak contact while reducing
feed from 184.01 to 180.68 mm. This is a distance comparison, not a timing win.
`--with-shallow-fronts` retries at 0.25 mm immersion after the normal
selection fails, keeping previous cuts unchanged. It clears another 2.46 mm²
at the same sampled peak, then stops because the new endpoint fails origin
clearance. Increasing `--shallow-runoff` from 2 to 2.5 mm removes another
0.375 mm² but does not clear the endpoint. At 3, 3.5, and 4.5 mm no shallow
retry passes selection. The extra straight travel is not an exit strategy;
no clearance or contact gate was relaxed. With `--shallow-runoff 1
--shallow-rolloff 1`, the shallow retry follows a checked tangent quarter-turn
away from the frontier. It ends 2.455 mm from stock at unchanged peak sampled
contact. The next selection still stalls: 78 proposals fail clearance at the cut
start, five exceed contact and one fails the cut boundary. None fail along
the link after both endpoints clear. Trying more intermediate waypoints
cannot fix blocked starts. Adding `--shallow-rollon 1` tries a tangent
quarter-turn onto each shallow front from its clearance side. The unchanged
checks accept one additional cut, removing another 2.65 mm² at the same
peak contact; 4,119.04 mm² reachable stock still remains. Adding
`--with-shifted-joins` tries joining 2 or 4 mm farther along the initial
straight. The trial reaches its 12-cut budget at the same 56.17° peak with
4,116.36 mm² reachable stock remaining. With `--max-cuts 48` the same trial
stalls after 19 accepted cuts and leaves 4,103.77 mm² reachable. The final
round rejects 201 starts on clearance and 34 cuts on sampled contact. Raising
the benchmark budget distinguishes a real stall from the 12-cut budget stop;
it does not change production settings or establish coverage. Adding
`--with-taper` tests a parallel-start approach tapering 1.5 mm laterally
over 4 mm. It does not improve this stall: three additional starts fail
clearance and two further candidates exceed the sampled contact limit.
The offline `cleared_start_intervals` helper now clips an approach guide to
live cutter-center clearance. Each returned span passes full-segment
distance checks against remaining stock and the pocket boundary, including
holes. This identifies where an approach can start; it does not verify the
link to that start or the cut that follows. `--with-clearance-tapers` samples
those intervals for the two-lobe trial. Eight additional candidates pass the
access checks but fail sampled contact, leaving the 19-cut stall unchanged.
`last_taper_contact_failures` identifies the first over-limit chord per
rejected taper: four on the straight and four on the curved exit, none on
the approach. The diagnostic does not continue sampling a rejected cut.
`--with-early-exits` tries starting the roll-off 1 or 2 mm earlier. The
trial stalls after 15 accepted cuts on origin clearance, with 4,104.81 mm²
reachable stock remaining versus 4,103.77 mm² without the change. Shorter
travel at unequal coverage is not a timing improvement. Adding
`--require-clear-exit` rejects candidates whose final pose cannot fit the
cutter disk against post-cut stock and the pocket boundary. The gated
trial makes 23 cuts and leaves 4,074.87 mm² reachable, with a 56.64° sampled
peak. A clear exit does not guarantee that another eligible cut exists.
`nearby_frontier_mm` measures exposed stock edges within cutter radius
plus 0.25 mm of the clearance component containing the last pose. This
trial reports 76.37 mm, all between X3.5 and X25 mm. It is a geometric
neighborhood, not verified stay-down travel or proof of machinability.
`--with-neck-front` tries the easternmost 3 mm of this map. On the clear-exit
benchmark, two additional proposals reach the link check but fail it. The
trial still stalls after 23 cuts, leaving 4,074.87 mm² reachable stock.
`--with-three-leg-links` checks paths through two supplied waypoint poses
when direct and one-waypoint links fail. It routes around a protected island
in a separate fixture, but does not get past the current two-lobe stall.
`last_forward_clearance_mm` probes the full disk along the final heading.
The stalled pose fits the disk but has no verified straight departure at
0.0001 mm resolution. That does not rule out a curved departure.
Requiring `--min-departure 0.25` before ranking changes which cuts win: the
neck-facing trial reaches 48 accepted cuts at a 56.17° sampled peak, leaving
4,024.89 mm² reachable. The departure probe checks the terminal chord
heading against post-cut stock and walls; it does not emit that move.
With `--max-cuts 96`, the same variant stalls after 57 cuts with 4,011.53 mm²
reachable. The final selection rejects 578 starts, 38 contact overloads and
10 exits. The last pose still has at least 4 mm of checked forward clearance,
so the stall is no longer caused by a trapped terminal heading.
`--prioritize-neck` ranks already checked cuts by removal per traveled
millimeter east of X24 first. Both runs stall at 57 cuts with the frontier
ending at X27.75 mm. Neckward removal falls from 31.51 to 30.92 mm², so this
ranking alone is not an improvement. All acceptance checks stay unchanged.
`--with-front-bites` adds eased passes that enter and exit on the cleared
side of a neck-facing edge. It adds one checked cut and 0.374 mm² of
neckward removal at unchanged sampled peak. The run still stalls after
58 cuts with 4,011.16 mm² reachable. The seed-connected cutter-center
component gains another 0.229 mm² over the no-bite baseline and reaches
X25.998 instead of X25.750. Neither reaches the neck probe at (36, 23).
These are planar geometric diagnostics, not verified machine routes.
`--trace-clearance` reports seed-connected area, east edge, probe coverage
and cumulative feed after each accepted cut. With eased bites, the edge
is still at X23 after cut 23, reaches X25.998 at cut 54, and stays there
through cut 58 even as connected area grows. `--prioritize-clearance`
ranks already-verified cuts by their post-cut seed-connected east edge
before local efficiency. On this fixture the run still stalls after 58
cuts at X25.998, with the neck probe disconnected. The ranking does not
relax access, contact, or exit checks. `--with-wide-bites` adds a straight
plateau at the same 0.25 mm immersion across the middle half of an eased
pass. On the two-lobe fixture it stalls after 46 cuts at X23.0 with
4,037.98 mm² reachable, worse than the narrow-bite baseline (58 cuts,
X25.998, 4,011.16 mm²). The trial preserves all gates and is opt-in.
`--lookahead-width 2` checks a possible successor for each of the top two
eligible cuts against that cut's resulting stock and pose, then commits only
the first. It avoids a greedy dead end in a controlled fixture. At a 24-cut
neck budget both runs reach X23, but lookahead leaves 4,090.15 mm² instead of
4,087.34 mm². The trace fingerprints link and cut coordinates to locate
the first divergence: cut 2 ends at X22 with lookahead versus X13.5 with
greedy selection, but neither moves the connected edge past X23. Keep
greedy selection as the baseline. Delaying width-two preview until 53 cuts
(`--lookahead-after 53`) still stalls after 58 cuts at X25.998; reachable
residual is 4,011.181 mm² versus 4,011.155 mm² without preview.
Repeat `--section-x` to compare the terminal seed-connected spans with the
wall-limited center domain. In the no-preview baseline, the open span is
Y21.51–23.89 at X25.75 and empty at X26, where the wall-limited span is
Y14.12–30.17. The immediate blockage is live stock, not the pocket wall.
`--with-section-bites` adds shallow eastward bows with endpoints inset in
open spans. Mixing them into shallow retries regresses to a 49-cut stall
at X23.495 with 4,036.97 mm² reachable and 57.07° peak sampled contact.
Existing link, contact, exit and departure checks are unchanged.
`--section-bites-last` preserves the baseline's 58 motions, then adds one
checked bow: the connected edge advances from X25.998 to X26.123 and
reachable residual drops by 0.309 mm². The three remaining bows fail the
post-cut departure check; the neck probe is still disconnected.
Adding `--section-turn-exits` offers quarter-turn retreats with 0.25 and
0.5 mm radii, preserving the same departure gate. The 62-cut run reaches
X26.365 with 4,010.116 mm² remaining. The final bows fail for no removal
(six) or sampled contact (three), and the probe remains disconnected.
`--section-live-depth` proposes additional bows just beyond estimated
midpoint contact. It stalls at 62 cuts, X26.484 and 4,009.843 mm² reachable.
Peak sampled contact rises to 59.25° under the unchanged 60° gate.
`final_section_bite_spans` distinguishes an empty proposal family from
rejected motion. Its terminal insets are only 0.756 and 1.492 mm wide,
below the 1.5 mm proposal gate. At X25.75 the open span is 2.679 mm,
which does not by itself verify a cut or a link. With `--section-search-west`,
two extra checked cuts remove only 0.0035 mm² and do not advance the eastern
edge at 0.001 mm reporting precision. The run stalls at cut 64; 12 final
section candidates exceed the sampled contact gate and six remove nothing.
`--section-follow` samples first contact across each eligible span and eases
in and out. The 72-cut run stalls at X27.269 with 4,006.640 mm² reachable
and 57.91° peak sampled contact. The neck probe remains disconnected.
The terminal `final_section_follow` audit finds zero profiles because
all four spans are too narrow for proposals (widest 1.462 mm against a
1.5 mm minimum). Extending the contact rays alone cannot fix this stall.
`--section-fit-width` searches beyond the fixed insets for an eligible
opening. It adds seven checked cuts relative to the 72-cut run and
reaches X27.607 with 4,005.294 mm² residual. At this stall all 11 contact
rays hit, but all six final contours exceed the sampled contact gate.
`first_overloads` locates the first failing chord, not the path peak.
All six fail on chords 2–3 (zero-based), near the end of the initial
blend. At 0.05 mm advance the first offending sample is 61.47°, with
or without the optional retreat.
`--section-taper-entry` adds variants that hold nominal first-contact
position at the end of the initial blend, then ramp extra penetration.
When mixed with the originals this regresses to 75 cuts, X27.536 and
4,005.612 mm² residual, with all 12 terminal contours exceeding contact.
`--section-taper-at-stall` tests only the tapered variants on unchanged
79-cut baseline stock and pose. All six exceed contact on chords 3–4;
none is committed. `--section-shallow-approach` extends the initial blend
from 25% to 40% or 50% of the span. All 12 probes exceed contact during
entry, with first failing samples of 69.23–93.69°; none is committed.
`--section-nominal-at-stall` sets extra advance to zero for all three
entry lengths. None of the six probes overloads, but even the best
passing probe removes only 4.07e-8 mm², negligible for coverage.
`--section-bracket-at-stall` tests advances of 0.01–0.05 mm independently,
without committing them. At 0.04 mm two of six pass all checks; the best
removes 0.166 mm² at 56.49° peak sampled contact. At 0.05 mm all six fail
contact. This brackets observed candidates, not a continuous limit.
`--section-small-retry` checks smaller advances only after all standard
families fail. It accepts six additional cuts and stalls at X27.792 with
4,004.509 mm² reachable, unchanged 59.97° peak, and no passage to the probe.
`final_small_retry` finds an eligible 1.582 mm span, but two of 11
rays miss stock within the 1.5 mm search distance, so no retry is generated.
`--section-ray-probe` leaves the 85-cut baseline intact. At 1.55 mm one
ray still misses; at 1.65 and 1.8 mm the same 18 candidates pass, with
best removal 0.0632 mm² at 54.09° peak sampled contact.

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
