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

## Proposed design decisions

1. **Separate coverage, load, and linking.** Use stock area removed per path length as a ranking aid; use occupied cutter-periphery angle during ordered stock replay to assess engagement. Neither is a force estimate. Keep legacy percentages separate. A diagnostic circle that straddles a straight stock face before a sweep measures all contact; an actual steady side cut has a previously cleared side. Test both so the metrics aren't accidentally conflated.
2. **Plan the entire reachable region, not the next isolated loop.** Compare FreeCAD on identical input first. If a native replacement is necessary, connect the regions that survive tool-radius erosion, identify necks and isolated lobes, and keep an explicit list of what remains to clear. Long straight cuts are allowed; use smooth roll-on/roll-off and tangent corner transitions where cutting continues. If a corner cannot be rounded within the region and limit, reduce local advance, choose another approach, or leave a reported residual. Never insert a slot just to connect paths.
3. **Keep geometry and machine motion separate.** The offline comparison accepts ordered XY stroke proposals tagged cut, candidate link, or entry. No imported controller G-code. A backend's clear-link label is only a proposal: independently check the full cutter sweep against protected geometry and the stock left before that move. Compare verified stay-down time against retract/re-entry time. No unchecked fallback at adaptive depth.
4. **Pin the backend experiment.** Record FreeCAD and wrapper revisions, geometry tolerance, cutter radius, allowance, ring/hole convention, and how stock and boundaries are passed to the backend. Check the installed Clipper generation and bindings against the source examined here; do not assume they are identical. Check reproducible Windows builds, cancellation and license notices before considering a production dependency. Keep the comparison out of the installed app initially.

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
