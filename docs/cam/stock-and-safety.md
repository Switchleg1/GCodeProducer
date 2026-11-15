[Documentation](../README.md) / [CAM](README.md)

# Material, stock allocation and safety checks

**Where:** Model dock → Material / stock, in the same shared UI slot used by
FDM Support. **Stored on:** model-specific CAM setup.

This panel describes the **raw rectangular blank**, not the final solid model
or the calculated removal result. Results are selected separately in Preview. It is separate from the FDM filament material
library. The amber outline in Prepare/Preview remains the original blank
throughout toolpath inspection.

## Every material/stock field

| Field | Initial value | Meaning |
|---|---:|---|
| Material | Unspecified | Free-text material/alloy description |
| Density | 0 g/cm³ | Optional mass-estimation value; zero means no meaningful mass estimate |
| Auto margin | 2 mm | Added on each XY side and underneath when Auto is pressed |
| Minimum X | 0 mm | Left/minimum X edge of blank, not centre |
| Minimum Y | 0 mm | Front/minimum Y edge of blank |
| Surface Z | 0 mm | Highest Z of blank |
| Width X | 0 mm | Full X size; must be positive to allocate |
| Depth Y | 0 mm | Full Y size; must be positive to allocate |
| Thickness Z | 0 mm | Distance downward from Surface Z; must be positive to allocate |

All numeric stock fields display three decimal places. GUI input ranges are:
density 0–100 g/cm³; margin 0–1,000 mm; X/Y/surface Z -10,000 to +10,000 mm;
width/depth/thickness 0–10,000 mm. All three sizes must be positive and finite
to count as allocated. Zero sizes intentionally represent an unallocated blank.
These UI ranges do not validate physical machine capacity.

The summary shows volume in cm³, approximate mass in grams and bottom Z.
Volume is `width × depth × thickness / 1000`; mass is volume × density.
Neither density nor material text chooses feeds/RPM, stock hardness or tool
compatibility. Tool requests must be set deliberately in the tool library.

Bounds are `[x, y, surface-thickness]` through
`[x+width, y+depth, surface]`. These are job/work coordinates, not commands
for programming controller work offsets.

## Auto allocation

Auto fits the **placed** part, including its current translation, rotation and
scale. For placed bounds `lo`, `hi` and nonnegative margin `m`:

```text
minimum X = lo.x - m
minimum Y = lo.y - m
width     = hi.x - lo.x + 2*m
depth     = hi.y - lo.y + 2*m
surface Z = max(0, hi.z)
thickness = surface Z - lo.z + m   (minimum positive thickness)
```

This deliberately adds **no extra positive-Z margin above a normal Z0 top**.
CAM generally uses raw material surface Z0 and cuts downward. If you want
facing allowance above a recessed final part, place the model below Z0 or
edit Surface Z/Thickness explicitly.

Example: a 20 × 20 × 20 mm part with top Z0 and margin 3 mm produces a
26 × 26 × 23 mm blank, extending 3 mm beyond each XY side and 3 mm beneath
the part. A top at -2 mm produces more blank above that recessed part while
keeping the surface at Z0. A raised part can produce a positive surface.

Changing the margin spinner does **not** resize the existing blank until
Auto is pressed. Editing placement does **not** silently move/resize stock.
That independence lets you position a part inside a real measured blank.
After an intentional re-fit, press Auto again and recheck workholding.

## What generation checks

Checks run after CAM emission in the compute process, updating a current
height-field material model in emitted-move order. Findings include
G-code line numbers where applicable. Only setups with allocated stock can
be checked; otherwise a warning states that checking could not run.

| Check | Interpretation |
|---|---|
| Part outside stock | Model bounds are not fully contained; resize/reposition or use Auto |
| Safe height at/below stock | Unsafe clearance; tree generation also rejects safe Z at/below the stock/model/start heights |
| Rapid (`G0`) contacts current material | Sampled cylindrical cutter sweep reaches remaining height-field stock; cleared regions carry forward |
| Unclassified/custom feed into stock | Contact is not tagged as an intended generated cut/plunge |
| Feed contact with spindle stopped | Spindle state inferred from program commands is off at contact |
| Motion below blank bottom | Possible table/spoilboard contact, including moves outside the blank XY region |
| Excessive uncleared entry depth | A vertical plunge, or a ramp steeper than 10°, descends through more current material than the active tool max DOC. Material above the move's start height (a wall beside a helix) is side contact and does not count; ramps within 10° are not flagged |
| Tool change at/below material | A tool change is requested without sufficient Z clearance |
| Unknown controller effects | Offsets, compensation, cycles or unsupported G commands cannot be fully checked |
| Custom arcs/multiple G commands | Arc clearance or combined-block semantics are not fully simulated |

Current movement checks use a centre-sampled cylindrical cutter/height field,
not an exact solid sweep. Checking resolution can miss or approximate small
features. Cutting length/holder shape is not modelled. Upward withdrawals are
treated as retracts; initial physical machine state still needs independent
clearance. See [current material, resolution and leads](material-state-and-leads.md).

Generated `cut`/`plunge` paths have operation metadata and are considered
intended cutting. That distinction avoids warning about every normal milling
move. It does **not** prove that the intended cut avoids the retained part,
has valid engagement or follows a valid machining strategy.

Current height-field removal persists across paths, passes and operations,
including leads. Entry checks compare with current local material. Planning
also retains depth-tagged planar sweeps for later engagement/direction.
Both representations have 2.5D/resolution limits; uncertainty still requires
independent review.

## Warnings, generation errors and export

Some invalid setups fail before output: missing tool/selection, invalid
start/end ordering, nonhorizontal cutting geometry, invalid stepdown or
insufficient safe Z. Other stock findings are **advisory warnings** attached
to generated output, logged as `STOCK WARNING`, and shown in a dialog. The
dialog displays a limited number; inspect the full Log too. The checker caps
its stored findings to avoid unbounded repetitive output.

A warned program can still be inspected in Preview. Export asks for explicit
confirmation. If model/material/setup changes after generation, CAM export
requires regeneration so it is not silently exporting unchecked stale paths.
Fixing a blank or tool setting requires generating again; acknowledging a
dialog does not recalculate the result.

## What is not verified

- Initial physical machine position, homing, coordinate systems or actual
  controller work/tool-length offsets.
- General 3D stock/undercut state, fixtures, clamps, vises, holders, flute reach,
  shank contact or full machine kinematics. Only documented planar/height-field
  removal state is tracked.
- Retained-part gouging by every intended cut, cutter deflection, chip load,
  cutting forces, chatter, workholding stability or thermal behaviour. The
  separate [engagement estimator](engagement-and-feeds.md) subtracts planar
  depth-tagged sweeps across operations for direction/feed planning, but it is not a
  full 3D stock-removal/collision simulator.
- Exact custom arc/canned-cycle geometry, controller macros, smoothing or
  arbitrary multi-command blocks.
- Complete machine capability validation: positive `max_feed` now caps cutting
  and plunge requests, but RPM/tool/material suitability still require manual
  verification. Feed factors are not calibrated safety guarantees.
- Guaranteed blank fit within every physical machine/fixture boundary just
  because the model's work-volume check passes.

**No warnings is not proof of safety.** Height-field checks can still be
inaccurate at small features or cell boundaries. Never ignore concerns solely
because a display looks cleared; verify real tool/stock/controller geometry.

## Before running on hardware

1. Confirm stock size, surface, part placement and work-coordinate convention.
2. Confirm tool IDs/T numbers, measured diameters, flute reach and offsets.
3. Confirm feeds/RPM against cutter/material/machine limits.
4. Inspect entry/retracts, through cuts, retained walls and operation order.
5. Independently simulate with controller-aware tools and actual fixture/holder
   geometry where available.
6. Establish safe initial clearance, offsets and homing on the machine.
7. Air-cut above material and follow your machine's safe operating procedures.

[G-code template guide](../gcode-templates.md) · [CAM operations](operations.md)
