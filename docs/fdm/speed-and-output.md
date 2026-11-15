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
| Other/unmapped print features | 50 |
| First layer | 20 |
| Travel | 150 |

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

- **Retract on travel:** default On. Amount, speed and Z-hop come from the
  **material**, not this process section.
- **Minimum travel to retract:** 1.5 mm. Shorter XY travels skip retraction.
- **Seam position:** Nearest chooses the closed-loop start nearest the current
  head position. Fixed/Origin preserves the generated loop start; it is not
  necessarily the physical machine origin.

Open paths may reverse to begin at the nearer end. Nearest-first ordering
and seam selection reduce travel but are not obstacle-avoiding routing.
Z-hop is applied through retraction behaviour, not a general collision check.
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
