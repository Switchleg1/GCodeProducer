# Adaptive clearing restart plan

**Decision:** Replace the experimental adaptive path generator, not the CAM
application. Do not spend another iteration tuning its local-turn search or
raising its point guard. Keep that implementation available as a diagnostic
baseline until a replacement passes the same jobs. Do not change generated
motion in this planning step.

The 40,000-point Stormtrooper run stalled at the **first** Waterfall depth:
257 peels, 15 entries, and 238.594 mm² of reference stock still present. It
stopped before the resource limit. The current search can rank individual
turns, but it does not ensure that the remaining pocket is reachable by later
turns. Its sampled occupied-width percentage is also not a tool engagement
angle or a guarantee about cutter load.

## Research and choice

See the [follow-up research notes](adaptive-research-notes.md) for what
FreeCAD measures, the cornering evidence, and the offline comparison gate.

- [FreeCAD Adaptive2d API](https://freecad.github.io/SourceDoc/d6/d4d/classAdaptivePath_1_1Adaptive2d.html), [source](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/CAM/libarea/Adaptive.cpp), and [standalone bindings](https://github.com/kirberich/freecad-adaptive-clearing): the first baseline to try. The API accepts stock and separate machining boundaries; the bindings distinguish cuts and links. Compare raw geometry off-line, not FreeCAD-posted machine code. Do not assume its stepover factor equals our engagement setting or that a backend-labeled clear link is clear in our stock model. Check licensing, Windows packaging, and cancellation before deciding whether to ship a dependency.
- [Fusion Adaptive Roughing](https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/GUID09E44604-DAD8-47D6-ADC6-C100869DE724.htm): a useful product reference for separate controls for optimal load, minimum corner radius, stepdown, and verified stay-down travel. Its published performance claims are not targets for this machine.
- [Held and Pfeiffer, engagement-controlled pocket machining](https://doi.org/10.14733/cadaps.2025.731-747) and [Salzburg pocket decomposition research](https://www.cosy.sbg.ac.at/~held/projects/hsm/hsm.html): local machining circles and smooth transitions can advance from the cleared boundary. Decomposing a pocket at narrow necks gives each lobe a route and explicit coverage obligation. The engagement-control paper's construction is for pockets without holes; it is not a drop-in island solution.
- [Bieterman and Sandstrom, curvilinear pocket machining](https://doi.org/10.1115/1.1596579): smooth paths that morph toward the boundary are a useful second geometry approach, but smoothness alone is not an engagement or coverage test.

**Recommendation:** benchmark FreeCAD's geometry first. If it passes independent
checks and packaging is practical, adapt its geometry output. If not, write a
replacement around a cleared-stock front and explicit subregions, not a search
for the next complete loop. Allow long straight cuts where engagement is stable;
blend cutting corners tangentially, change advance at corners and necks, and
verify the blended geometry before accepting it. Track leftover reachable
stock by subregion, rather than assuming a locally productive cut will enable
complete coverage.

## Milestones and acceptance gates

1. **Make the failure observable.** Export diagnostic stock, reachable target,
   residual and ordered path geometry per depth from the read-only session
   harness. Pin the two-lobe fixture and first saved Waterfall depth. Preserve
   cutter, stock, allowance, lead angle and stepdown in comparisons. Save the
   old planner's output as a comparison artifact, not machine-ready code.
2. **Build an independent verifier.** Replay swept geometry in execution order.
   Validate occupied cutter-periphery angle against analytical straight-cut,
   slot, corner and air cases; define how simultaneous contact patches are
   counted and document tolerance. Report entry and cutting engagement
   separately. Verify rounded cutting transitions, protected geometry, and
   actual emitted/rounded coordinates. Do not silently reinterpret old
   percentage settings as degrees. A chewed-through corner or an unverified
   shortcut is a failure even if average engagement is low.
3. **Run the backend comparison offline.** Compare identical stock and targets
   on rectangle, concave corner, narrow neck/two-lobe, island, disconnected
   regions, and the saved Waterfall first depth. Use a declared geometric
   tolerance for remaining reachable stock; measure rather than ignore
   unmachinable corners. Score coverage first, then peak/P95 cutting engagement
   and slot distance, then cut/link/retract time and planning time. An incomplete
   path never wins on cycle time. Use serial timing runs on this machine.
4. **Integrate only after the gates pass.** Keep the existing CAM operation,
   selection, stock and tab constraints, lead angle, tool changes, motion
   planner, and independent emitted-program replay. Treat backend paths as
   proposals, not permissions for links. If the replacement stalls, retain
   debug-only output and do not start deeper passes. Do not silently switch
   to conventional contours at adaptive depth.
5. **Validate the complete saved session.** Require every enabled depth and
   operation to complete, no unchecked fallback, and a coverage/engagement
   report. Compare whole jobs at equal coverage. First compare at identical
   stepdown and feeds; then separately compare a qualified adaptive depth
   against a qualified conventional depth. That second comparison measures
   the intended benefit of deeper passes. Do not increase stepdown merely to
   meet a time target. Report slicing time separately from estimated machine
   time and hardware validation.

**Status:** the application still runs the old generator. Milestones 1 and 2
have offline tooling: the CamBam replay and contact verifier
(`tools/check_cambam_pocket.py`, `tools/hsm_contact_replay.py`) and pinned
fixtures, including `examples/adaptive-neck-pocket.wkt` and the shapes in
`examples/hsm-shapes/`. FreeCAD was not benchmarked: no reproducible build was
available. For milestone 3, the replacement under trial is the
[wavefront](wavefront-clearing.md), which advances from the cleared region
as planned above. It clears the two-lobe fixture and the open test shapes with
even peels under the contact limit. Narrow channels and pockets with a boss
are not yet acceptable, and it has no Z motion, so milestones 4 and 5 have
not started.
