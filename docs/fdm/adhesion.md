[Documentation](../README.md) / [FDM](README.md)

# Skirt and brim

**Where:** Process → Skirt / brim. **Stage:** `fdm_skirt_brim` (optional).
Adhesion paths are inserted before other paths on their layer and tagged
`skirt` in Preview and output, including brim paths.

## Modes

- **None:** no adhesion paths.
- **Skirt:** detached loops around the convex hull of the outer contours. This
  primes extrusion and helps inspect first-layer behaviour; it does not trace
  every concavity or attach the model to the bed.
- **Brim:** loops adjacent to first-layer outer contours. Intended to increase
  bed attachment; hole interiors are not brimmed.
- **Skirt + brim:** both; skirt distance is measured beyond the brim's extent.

## Settings and defaults

| Setting | Default | Effect |
|---|---|---|
| Type | Skirt | Which mode generates paths |
| Skirt loops | 1 | Concentric priming loops |
| Skirt distance | 3 mm | Gap from part, or from brim when both are active |
| Skirt layers | 1 | Repeat skirt on this many layer indices; tall skirts can act as a draft shield |
| Brim width | 5 mm | Desired radial attachment width; rounded up to a whole number of lines |
| Brim gap | 0 mm | Separation between brim and part; larger gaps may ease removal but reduce attachment |
| Line width | `auto` | Nozzle/job line width unless explicitly overridden |

The generator uses `ceil(brim_width / line_width)` loops. For 5 mm width and
0.45 mm lines, 12 lines give a nominal 5.4 mm extent before any brim gap.
Outermost loops are ordered first, ending near the model. Rounded widths and
a detached skirt can extend well beyond the model's bounding box.

## Lifted models

If the model does not touch the first layer, a brim is skipped and logged.
There is no part contact on the bed to attach it to. A skirt can still be
placed on early layers using the model's lowest available outline. This is
not a brim for the support base and does not automatically surround all
support extents.

## Workflow and checks

1. Place the model and choose normal/first-layer heights.
2. Select mode, gaps and width; re-slice after each change.
3. Inspect both the complete first layer and isolated feature `skirt`.
4. Check extra paths against the machine plate; model fit alone does not prove
   a wide brim or skirt fits.
5. Review first-layer temperatures, first-layer speed and bed preparation.

A brim cannot fix an unlevel bed, contaminated surface, wrong Z offset, poor
first-layer extrusion or a material/profile mismatch. Large gaps can make it
look like a second skirt. Missing brim in holes is intentional.

[Exact parameter reference](../reference/stage-settings.md#fdm_skirt_brim)
