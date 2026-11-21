# HSM/adaptive rewrite — until verified

Replace the adaptive generator for Pocket and Waterfall. Keep CAM scheduling,
postprocessing, feed policy and other strategies outside the replacement.
Incomplete paths stay debug-only. Do not qualify output for a physical machine.

## Milestones

1. `tools/check_cambam_pocket.py`: verify progressive planar coverage and
   sampled cutter-periphery contact against analytical air, slot and side-cut
   fixtures. Plot numbered moves and stock/residuals. Characterize refinement
   at short corners and distinguish unmodeled entry from at-depth engagement.
2. Pin fixture inputs and numerical/coverage acceptance before comparing
   proposals: closed and open pockets, rounded and sharp corners, two lobes,
   an off-center island, and previous-tool stock. Use CamBam as a measured
   reference; compare FreeCAD offline if a reproducible build is available.
3. Offline replacement: the wavefront in `tools/hsm_wavefront.py`
   ([guide](docs/cam/wavefront-clearing.md)). It must clear the two-lobe
   fixture and every shape in `examples/hsm-shapes/` with an even peel (few
   arcs at the smallest stepovers) under the contact limit and without a wall
   pass. It must join cuts with checked stay-down links and lift only between
   islands. Then add Z motion: helix entries, lifts and re-entry.
4. Integrate the tested replacement behind the existing Adaptive selection.
   Verify emitted, quantized paths, stop on unreachable residual or a resource
   limit, and preserve the incomplete-output guard.
5. Run relevant adaptive, linking, strategy, and documentation tests plus a
   read-only saved Stormtrooper session. Require full depth/operation coverage,
   no unsafe rapids/tab contacts, and no unchecked slot/cleanup fallback.
   Document coverage, engagement, and clearance evidence before reporting
   timing. Compare at equal coverage, same tool/stepdown/settings; keep
   slicing time, Preview estimate and machine time separate.

`LOOP_DONE` requires milestone 5, not merely a passing verifier or an offline
prototype. Record results in `PROGRESS.md` and assumptions in `ASSUMPTIONS.md`.
