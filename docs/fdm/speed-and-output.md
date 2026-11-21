[Documentation](../README.md) / [FDM](README.md)

# Speed, travel, extrusion and output

**Where:** Process → Speed & travel. **Stage:** `fdm_emit` (core).
This stage converts geometric paths to G-code. Its speed requests are not
machine capabilities; effective output is limited as described below.

## Requested speeds

All GUI/process speeds below are **mm/s**; emitted G-code F values are **mm/min**.

| Feature | Default request |
|---|---:|
| Outer wall | 30 |
| Inner walls | 45 |
| Sparse infill | 60 |
| Solid infill (bottom/internal) | 40 |
| Top solid infill | 30 |
| Support body | 50 |
| Support interface | 35 |
| Skirt / brim | 30 |
| Gap fill | 30 |
| Other/unmapped print features | 50 |
| First layer | 20 |
| Travel | 150 |

Variable-width walls and gap fill change the extrusion per segment with the
bead width; the feed cap for volumetric flow uses the widest bead of the path.
Before writing, every path is simplified with the global **FDM paths**
settings ([Settings](../settings.md)): segments shorter than the minimum line
segment length are merged while the path stays within the maximum deviation.

First-layer speed overrides normal feature requests for printing moves on
layer index zero. It is not necessarily the first model-bearing layer of a
lifted part. A stage-supplied per-path speed can replace a normal mapped
request on later layers, but machine/flow caps still apply.

Acceleration defaults to **0**, meaning leave firmware acceleration unchanged.
A positive request emits `M204 S…`, capped at a positive machine maximum.
This does not implement an acceleration-aware time estimate or per-axis
motion planner.

## Effective speed and volumetric flow

Print moves are capped by machine maximum print speed. Travel is capped by
machine maximum travel speed. The lowest positive machine/nozzle volumetric
limit additionally restricts print speed according to actual extrusion volume
per path length, including width, height and material flow multiplier.

For an illustrative rectangular bead 0.45 × 0.2 mm, 60 mm/s requires roughly
5.4 mm³/s before bead-shape details and flow multiplier. The implementation
uses its extrusion-area calculation rather than assuming every bead is that
rectangle. Wider/thicker beads often hit a flow cap earlier.

Read Log messages for each cap. Increasing the requested speed above a cap
will not increase effective speed. A disabled/zero flow limit means that cap
is not applied; it does not mean unlimited flow is physically possible.

## Travel, retraction and seams

**Retraction mode** (under **Speed & travel → Travel**) shows only the
thresholds used by the selected mode:

| Mode | When a travel retracts |
|---|---|
| Off | Never. |
| All travels (default) | Any travel at or above **Minimum travel to retract** (default 1.5 mm). |
| Open spaces only | An open-space crossing at or above the minimum. |
| Open spaces + long inside travels | An open-space crossing at or above the minimum, or an inside travel at or above **Inside travel retraction distance** (default 10 mm). |

Thresholds use the full length of the individual XY travel, not cumulative
distance. A detour that stays inside the outline counts as an inside travel.
Retraction amount, speed and Z-hop come from the **material**. Existing presets
keep their prior behavior when loaded.

**Coast length** defaults to 0 mm (off). Set a distance to stop feeding
filament over the last part of each extrusion path while still following the
path at print speed. This can relieve nozzle pressure before travel. Short
paths that cannot fit the coast keep their normal extrusion. Coasting works
independently of retraction; too much can leave gaps.

**Max time to avoid open spaces** defaults to **0 s** (off). A positive value
lets the router detour around holes and concave edges or shorten the open-air
portion of a jump between islands. If no candidate improves the crossing within
the budget, it uses the direct route. The extra-distance budget is this value
times the capped XY travel speed (15 mm for 0.100 s at 150 mm/s).
This is a per-travel estimate, not a print time cap:
it does not model acceleration, corner slowdown or retraction. The Messages
log separates same-island detours, shortened island crossings, unresolved
same-island crossings, and other open transitions. The search retries
dense outlines with more waypoints, but remains bounded. **Settings → FDM
travel → Travel waypoint simplification** controls the candidate outline
(default 0.1 mm; 0 uses detailed waypoints only). The search still checks
against the original outline and retries with detailed waypoints if needed. An island crossing
still passes over open space even when shortened.

Under **Seam → Perimeter start / stop**, **Fastest (nearest start)** puts the
seam at the closest point on the loop to the current head, minimizing the
local approach distance. **Toward XY point** snaps it to the point on the
loop closest to **Target X / Y**, in bed coordinates. A target outside the
part can put seams on a consistent side across layers. A cyan target marks the
point on the Prepare bed. Use **Pick on bed**, then click the bed to update
both coordinates; **Esc** cancels without moving the target. **Fixed (loop start)**
keeps the generated start; it does not mean the physical machine origin.

Open paths may reverse to begin at the nearer end. Detours use the slice
outline, not an exact map of already printed beads. Z-hop is applied through
retraction behaviour; neither feature is a general collision check.
Avoid excessive retraction lengths/speeds, especially on tools/materials
that have not been calibrated for them.

## Temperatures and cooling

Requested normal/first-layer nozzle and bed temperatures and chamber temperature
live on the material. The emitter caps them to machine limits. A chamber
request is ignored with a log message if the machine does not have a heated
chamber. `wait_for_chamber` controls the default template's optional `M191`.

The start template uses **first-layer** temperature variables. At layer index
one, the emitter changes to normal nozzle/bed temperatures without waiting
when they differ. Chamber startup/shutdown commands come from the template;
a custom template must include its own desired chamber handling. The emitter
warns if chamber heating was requested but neither `M141` nor `M191` appears
in the rendered start text.

Material fan percentage is converted to PWM and emitted at the configured
fan-start layer (`fan_first_layers`). Review custom start code to ensure the
fan's initial state is what you intend. Stored `min_layer_time` currently does
**not** implement automatic slowdown or dwell.

## Output sequence and templates

The emitter writes a header, rendered machine start template, optional
acceleration command, extrusion mode (`M83`/`M82`) and an E reset. It then
writes layer/path motion and finally the rendered end template. Extrusion is
computed using bead dimensions, filament cross-sectional area and material
flow multiplier. Invalid filament diameter/flow calibration affects all paths.

Start/end templates and their defaults are described in
[G-code templates](../gcode-templates.md). Blank templates mean “use default,”
not “emit nothing.” Defaults home/heat/shut down generically; they are not
validated for every printer. Review the complete output, especially before
using machine-specific macros or replacing the default sequence.

[Exact parameter reference](../reference/stage-settings.md#fdm_emit)
