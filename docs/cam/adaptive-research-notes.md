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
