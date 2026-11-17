[Documentation](../README.md) / [FDM](README.md)

# Solid shells and sparse infill

Solid and sparse fill are separate stages. Both consume the region inside the
walls; solid regions are identified first so sparse lines can avoid them.

## Top / bottom shells

**Stage:** `fdm_top_bottom` (optional). **Where:** Process → Top / bottom shells.

A region is sparse only when the part covers it through all requested layers
above **and** below. Exposed regions receive solid fill. This detects interior
surface changes, such as the top of a wide base beneath a narrower tower; it
is not simply “make the first and last N layers solid.”

| Setting | Default | Meaning |
|---|---|---|
| Top layers | 4 | Solid depth counted down from exposed top regions; 0 disables top shells |
| Bottom layers | 4 | Solid depth counted up from exposed bottom regions; 0 disables bottom shells |
| Pattern | Rectilinear | Alternating 90° line families; Lines keeps direction; Grid uses crossing families |
| Angle | 45° | Base fill direction |
| Line width | `auto` | Wall line width, falling back to job/nozzle width |
| Overlap | 25% | Percentage of line width used to overlap the innermost wall boundary |
| Minimum length | 0.4 mm | Discard shorter generated segments |

Top regions are tagged `top_infill`; bottom/internal solid regions are
`solid_infill`. A region satisfying both classifications is not printed twice.
Detection uses a shared raster of the wall-bounded interior. Its resolution
is `max(0.25 mm, 0.75 × solid line width)`, so tiny geometric details may be
quantized or disappear.

With uniform 0.2 mm layers, four top layers represent about 0.8 mm of nominal
shell depth. Reducing layer height without increasing the count reduces shell
thickness. Setting both counts to zero disables this stage's fill, but does
not remove walls or force sparse infill to become solid.

## Sparse infill

**Stage:** `fdm_infill` (optional). **Where:** Process → Infill.

| Setting | Default | Meaning |
|---|---|---|
| Density | 20% | Target pattern density; 0 means walls/shells only, not an empty model |
| Pattern | Grid | Rectilinear, grid, triangles, cubic or lines; see live reference for choices |
| Angle | 45° | Base pattern orientation |
| Line width | `auto` | Wall width, or explicit override |
| Overlap | 15% | Wall overlap as percentage of infill line width |
| Minimum length | 0.5 mm | Remove very short segments |
| Shortest travel order (`connect`) | On | Nearest-first line ordering to reduce travel |

The base spacing is line width divided by density as a fraction: 0.45 mm at
20% gives a 2.25 mm base period before pattern-family handling. Crossing and
layer-varying families change the visible structure, so do not interpret this
as a guarantee of an exact measured solid-volume fraction.

`connect` orders separate segments; it does **not** join them with extruding
bridges. Output still travels between disconnected paths and applies its
retraction policy. Sparse fill is split against the shell mask so it does not
reprint solid regions. In **Speed & travel → Travel**, **Print nearby infill
together** (on by default) considers nearby lines from each infill type instead
of printing all top surfaces before all sparse fill. It preserves the original
order if the local search does not shorten XY travel. Walls, support, adhesion,
and the line geometry and speeds of each infill type are unchanged.

## Overlap and patterns

Overlap modifies the line inset near the wall boundary. Excessive overlap can
put extra material at walls; negative overlap deliberately leaves separation.
It is not global expansion of the part and does not repair missing contours.
The accepted range extends from -100% to 100%, but extremes may be impractical.

Rectilinear alternates orientation by layer; Lines does not. Grid and
Triangles combine multiple scan families. Cubic varies its scan families with
layer position to form a 3D-style internal structure. These are generated
line patterns, not analytic lattice solids with guaranteed strength.

## Inspection and diagnosis

1. Isolate the first/last layers and intermediate step surfaces in Preview.
2. Hide sparse infill temporarily to inspect shell coverage.
3. Verify the walls still bound the fill region after width/count changes.
4. Review tiny gaps against raster resolution and minimum segment length.
5. Review actual solid/top/sparse speeds and flow caps separately.

Sparse fill under a roof is not a bridging simulation. Very low infill can
leave long unsupported solid lines. “100%” fill does not guarantee absence of
all voids; wall offsets, overlap, path spacing and geometry quality still matter.

[Shell settings](../reference/stage-settings.md#fdm_top_bottom) ·
[Infill settings](../reference/stage-settings.md#fdm_infill)
