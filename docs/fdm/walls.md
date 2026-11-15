[Documentation](../README.md) / [FDM](README.md)

# Walls and hole boundaries

**Where:** Process → Walls. **Stage:** `fdm_perimeters` (core).
Walls are generated from each slice contour before solid and sparse infill.
The innermost wall loops become the working fill boundary for later stages.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| Wall loops (`perimeters`) | 2 | Requested contour loop count; 1–20 |
| Wall line width (`line_width`) | `auto` | Nozzle/job width, or an explicit 0.05–3 mm width |

The nozzle profile normally supplies 0.45 mm width. Job width falls back to
1.1 × nozzle diameter when the nozzle's numeric width is nonpositive. The
process setting's `auto` means use that job width; it does not perform an
adaptive thin-wall width calculation.

## How contours are offset

A wall centreline must lie inside material, half a bead width away from its
boundary. Outer contours therefore move **inward**, while contours around
holes move **outward into the surrounding part**. Moving a hole wall inward
into the empty hole would shrink the opening and create unsupported paths;
that is not the intended behaviour.

Inner loops print before the outer loop for the corresponding contour. Paths
are tagged `inner_perimeter` or `outer_perimeter`; the Output stage assigns
their requested speeds independently. Changing support reach cannot correct
a wall placed on the wrong side of a hole, so inspect hole geometry directly.

Two 0.45 mm walls have approximately 0.9 mm nominal combined bead width, but
curvature, offsets and thin-feature clipping affect the exact result. This
is not a dimensional-tolerance guarantee.

## Thin features and interaction with fill

Requested loops may not all fit around a narrow rim or between a hole and the
outside boundary. The geometry kernel stops/reduces invalid loops rather than
providing a complete variable-width gap-fill strategy. Adding more loops may
remove all remaining infill area; increasing overlap does not recover missing
wall geometry.

After changing wall count or width, inspect:

- outside dimensional shape and hole sizes;
- rims around internal openings;
- narrow webs that may disappear;
- the interface between innermost walls and solid/sparse fill;
- volumetric caps when wider lines are requested.

If the model contains open contours, duplicate faces or intersecting geometry,
repair the STL before relying on offsets. The kernel is minimal and is not a
robust CAD offset/boolean engine.

[Exact parameter reference](../reference/stage-settings.md#fdm_perimeters)
