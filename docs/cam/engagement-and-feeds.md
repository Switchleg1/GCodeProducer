[Documentation](../README.md) / [CAM](README.md)

# Remaining-material direction, engagement and feed adjustment

Climb/conventional describes the interaction with **uncut material**, not a
universal CW/CCW winding for every loop. A full-width first slot cuts on both
sides and has **no unique cutting hand**. Its chosen traversal cannot establish
the hand of later clearing passes.

## Correct clearing direction

The previous wall-based contour winding was only appropriate when the named
wall was the active material side. For an outside-to-inside annular clearing
sequence, the first perimeter cuts a slot; the next inner loop encounters
uncut material **toward the centre**, even though the final outside wall is
on its other side.

The planner now maintains a planar material estimate and subtracts each
completed path and accepted feed-link cutter sweep. For each next path it:

1. Measures material on the left and right of travel, including frontal tool
   contact during entry.
2. Treats full-slot paths as neutral instead of using their winding as a
   climb/conventional decision. A path dominated by near-full-width cutting
   (at least 75% of its length) is neutral as a whole, so short entry/closure
   portions cannot incorrectly establish its overall hand.
3. Chooses the next one-sided pass's direction from its remaining material.
4. Preserves the seam of reversed closed contours so stay-down links remain
   valid; an open path can reverse with a fresh entry.

For the current **clockwise M3 spindle**, uncut material on the **right of
travel** is climb; material on the left is conventional. Thus the annular
outside-to-inside example uses a neutral first slot followed by **CW climb
clearing loops**. Conventional reverses those one-sided passes. A different
clearing order/material side can require the opposite winding. Do not judge
all loops by an inside-wall or outside-wall rule alone.

Meander alternates the requested hand between successive one-sided passes.
Full-width neutral slots do not advance that alternation. Engrave receives
engagement/feed estimates but has no requested-hand override; Drill uses its
plunge feed rather than XY engagement factors.

If material switches sides within one contour, reversing the whole loop may
not make every local segment climb. Significant mismatched/mixed sections
produce an **ENGAGEMENT WARNING** rather than a claim that the whole path is
pure climb. Inspect the path and consider another strategy/selection. There
is no general local re-routing or curve splitting guarantee yet.

## Engagement bands

Engagement is an estimated occupied cutter width divided by tool diameter.
The planner samples chords at several positions and forward offsets along
each move. Forward chords matter: a connector's centreline can be in cleared
space while the front of the cutter enters a heavy cut. Peak sampled contact
is used conservatively. Regime boundaries use rounded whole-percentage values
so tiny STL/offset differences do not constantly switch a nominal 40% cut.

| Regime | Estimated engagement | Default feed factor |
|---|---|---:|
| Air | No detected contact | 100% of base feed, not a G0 |
| Low | Below 40% | 100% |
| Standard | 40–70% | 100% |
| High | Above 70%, below slotting | 75% |
| Slotting | Approximately 95–100% | 50% |

A balanced two-sided frontal entry is hand-neutral even if its engagement
falls in the High band rather than full-slot band. It still receives the
High/Slotting reduction as measured. A one-sided feed connector that would
oppose the requested hand is replaced with a retract/position/plunge; balanced
neutral entries remain admissible when their geometric clearance is valid.

These defaults are starting values, **not calibrated chip loads or safety
limits**. Full-slot entry need not use the same feed as a 40% radial pass.
Likewise, a tested cutter/material setup may allow the Standard band to run
faster than the base feed.

## Where to adjust feeds

**Libraries → Tool → Engagement feeds** stores reusable defaults:

- `low_engagement_feed` — default 100%.
- `standard_engagement_feed` — default 100%.
- `high_engagement_feed` — default 75%.
- `slotting_feed` — default 50%.

**CAM operation → Engagement feeds (% of tool feed)** can override each
independently. **Tool default** (numeric 0) inherits the tool profile. Explicit
values are 1–300%. Tool profile factors cannot use 0. These are multipliers
of the tool's **cutting feed in mm/min**, not the plunge feed or spindle RPM.

Example with base tool feed 800 mm/min:

| Setting | Result before machine cap |
|---|---:|
| Slotting 50% | 400 mm/min |
| High 75% | 600 mm/min |
| Standard 150% | 1,200 mm/min |
| Low 100% | 800 mm/min |

Setting Standard to 150% does not increase slotting or High feed. This enables
independent tuning of the requested 40–70% range. There is no automatic
chip-thinning feed increase: choose increases from cutter/material guidance
and calibrated tests.

A positive **CAM machine `max_feed`** now caps emitted cutting, connecting
feed and plunge requests, including increases above 100%. Caps are logged.
Zero disables this particular cap; it does not establish physical capability.
XY G0 rapid requests and spindle RPM are separate settings and are not these
engagement multipliers.

## Inspecting the output

- **Colour by feature:** Slot is orange, High engagement red/orange, ordinary
  Low/Standard cutting green, and estimated Air grey.
- **Colour by Tool engagement (CAM):** shows normalized estimated contact,
  not a live sensor reading.
- **Colour by speed:** shows the actual emitted feed after factors/caps.
- G-code contains feature annotations and comments such as
  `slot 100% engagement; neutral` or `standard 40% engagement; climb` at
  condition changes. Stay-down lines keep their link comment; in-memory
  engagement/note metadata still records their conditions.
- The log summarizes bands, neutral slot paths, direction reversals, retained
  stay-down entries and warnings. A successful loop reversal is not proof of
  every tool contact being physically correct.

### Illustrated annular example

![Feature colouring: neutral slot and subsequent cutting passes](../pictures/cam-pocket-engagement-features.png)

The outer orange loop is the initial full-width slot, not a conventional
clearing pass. Subsequent green passes are oriented CW against the remaining
inner material for Climb. Short entry links receive their own heavier-cut
classification. Direction is established by the generated order/metadata,
not by line colour alone. Entry/rapid moves are hidden in this capture.

![Estimated radial engagement colouring of the same pass](../pictures/cam-pocket-engagement-estimate.png)

The outer red loop is approximately 100% engaged. Most subsequent passes are
around 40%; thinner residual cuts and entry transitions have different values.
The example uses a 3 mm tool with base feed 800 mm/min, Slotting 50% and an
operation Standard override of 150%. These are demonstration values, not a
calibrated machining recipe. The images are real application captures with
isolated settings, not sensor measurements or physical simulation results.

## Scope of the estimate

This is **planar, path-granular in-operation removal**, not a full 3D stock
simulation. The estimated XY plan is reused at each depth, starting fresh for
each operation. It subtracts completed path/link tool sweeps; it does not
track removal along every tooth or preserve cleared volume from earlier
operations. Within-path re-tracing/overlap is conservatively represented by
the pre-path material state. If stock is unallocated, a conservative XY blank
is assumed and logged; configure real stock for meaningful estimates.

Tool shape is treated as a constant-diameter planar cutter. Ballnose contact,
V-bit effective width, axial engagement, runout, chatter, deflection,
workholding, holders, fixtures and controller offsets are not simulated.
The convention still assumes M3; a custom M4 post does not automatically
invert engagement-hand logic.

The existing [stock checks](stock-and-safety.md) remain separate. Engagement
analysis does not certify clearance or replace independent simulation and an
air cut. Mixed-hand warnings survive stock checking and require review before
CAM export.

## Existing projects

Old tool profiles resolve the new factors to 100/100/75/50%. Operations
without overrides inherit them. This deliberately changes effective feed for
High/Slotting moves; inspect regenerated output. To preserve a previously
calibrated uniform cutting feed, explicitly set all four factors to 100%,
then evaluate direction and engagement separately.

Legacy CLI silhouette paths do not have the operation-level removal plan and
therefore retain uniform tool feed (now machine-capped), rather than pretending
to have measured engagement. Use operation-driven CAM for these classifications.

[Strategies and linking](toolpaths.md) · [Operation settings](operations.md) ·
[Tool profile reference](../reference/profile-settings.md#cam-tool)
