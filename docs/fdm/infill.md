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
| Fill small gaps with perimeters (`gap_fill`) | On | Extra variable-width perimeters where the pattern cannot fit; see below |
| Fill gaps narrower than (`gap_fill_width`) | `auto` | `auto` = 2 × wall line width |
| Solid small islands (`solid_islands`) | Off | Fill small layer islands solid with concentric perimeters; see below |
| Islands smaller than (`solid_island_area`) | 25 mm² | Island area threshold for Solid small islands |

### Gap fill

Between the innermost wall and the infill there can be thin gaps too narrow
for infill lines: between blade walls, inside gear teeth, along narrow webs.
With **Fill small gaps with perimeters** on, every part of the fill area
narrower than **Fill gaps narrower than** (`auto` = 2 wall line widths; the
area minus its opening at half that width) gets an extra `gap_fill`
perimeter. Its width varies to fill the gap, between the minimum and maximum
bead widths of Process → Walls; gaps narrower than the maximum get one centre
bead. The gap is first grown by half the **Overlap** of a line width into the
walls, so the bead fills the gap plus the same overlap that infill lines use.
Sparse and solid lines are trimmed out of the gap; bridge areas are left to
the bridge fill. Anything wider, such as a fan hub, gets normal infill. Gap
fill prints at **Speed & travel → Gap fill** speed.

### Solid small islands

Thin pillars, pins and posts get little or no sparse infill and can be weak or
soften from the heat of their own small layers. With **Solid small islands**
on, every layer island — a separate piece of the slice, its outer outline
minus its holes — smaller than **Islands smaller than** is filled completely
inside its walls with concentric variable-width perimeters (tagged
`solid_infill`), grown by the same overlap into the walls. Sparse and solid
lines inside such an island are removed. The test is per layer, so a pillar
that joins a larger part higher up becomes normal infill from that layer on.

The base spacing is line width divided by density as a fraction: 0.45 mm at
20% gives a 2.25 mm base period before pattern-family handling. Crossing and
layer-varying families change the visible structure, so do not interpret this
as a guarantee of an exact measured solid-volume fraction.

Sparse and solid lines are clipped to the fill region inset by the overlap
setting, not only trimmed at their ends. A line running nearly parallel
through a narrow channel between walls therefore cannot lie on the walls;
channels narrower than the inset get no lines (gap fill covers them when on).

`connect` orders separate segments; it does **not** join them with extruding
bridges. Output still travels between disconnected paths and applies its
retraction policy. Sparse fill is split against the shell mask so it does not
reprint solid regions. In **Infill → Lines**, **Print nearby infill
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

## Bridging

In **Libraries → Material → Bridging**, set **Minimum unsupported area** above
zero to enable bridge paths. The area is measured in mm² for each connected
unsupported patch before growth. **Anchor growth** extends each qualifying
patch in every direction, clipped to the printable fill region. The slicer
tries straight parallel lines in several directions. Backed endpoints help
choose a direction but are not required: unsupported fill on one-sided
overhangs also gets the bridge settings. Bridge paths replace overlapping
solid or sparse infill and can be inspected by feature in Preview. If the list
shows **Bridge (none in this slice)**, check the selected material in Setup.
The slice log reports that material’s bridge threshold or that bridging is off.

- **Speed mode:** fixed mm/s or a percentage of the requested solid infill speed.
  Machine speed and volumetric flow limits still apply.
- **Cooling mode:** fixed fan percentage or a percentage of the material’s
  normal fan setting, capped at 100%. Normal cooling resumes after the bridge.
- **Flow modifier:** percentage of the material’s normal extrusion flow.
  Coasting is skipped on bridge lines so the end anchor still receives filament.

Detection excludes the previous layer’s model outline and generated support
beneath the patch, including support separated by the configured Z gap. It
estimates coverage rather than modelling individual sparse infill or support
beads, and it does not predict sag. Inspect the resulting paths before printing. Very low infill can still leave long unsupported solid lines. “100%” fill does not guarantee absence of
all voids; wall offsets, overlap, path spacing and geometry quality still matter.

[Shell settings](../reference/stage-settings.md#fdm_top_bottom) ·
[Infill settings](../reference/stage-settings.md#fdm_infill)
