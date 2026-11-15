[Documentation index](../README.md)

# FDM printing and process presets

FDM turns the placed STL into layer contours, adds extrusion paths, and emits
G-code using a machine, a filament material, a nozzle and a process. Support
placement remains attached to the model rather than to that process.

## Process order

| Stage / GUI section | Responsibility | Guide |
|---|---|---|
| `fdm_slice` / Layers | Resolve heights, retain lifted-model empty layers, slice contours | [Layers](layers.md) |
| `fdm_skirt_brim` / Skirt / brim | Prime nozzle and/or add first-layer adhesion loops | [Adhesion](adhesion.md) |
| `fdm_support` / Support | Generate paths according to model support mode and process style | [Support](support.md) |
| `fdm_perimeters` / Walls | Generate wall loops and the interior fill boundary | [Walls](walls.md) |
| `fdm_top_bottom` / Top / bottom shells | Identify solid surface regions per layer | [Shells/infill](infill.md) |
| `fdm_infill` / Infill | Pattern-fill remaining sparse regions | [Shells/infill](infill.md) |
| `fdm_emit` / Speed & travel | Speeds, extrusion, travel, cooling and output | [Output](speed-and-output.md) |

The support stage is **core and always executes**; the model's default mode
None makes it generate no support. A disabled legacy stage flag cannot turn
off model support. Layers, Walls and Output are also core. Adhesion, shells
and infill are optional stages. Their parameters may additionally select an
off/zero behaviour. Exact defaults/ranges are in the
[stage reference](../reference/stage-settings.md).

## Managing recipes

A preset contains an ordered pipeline and stage parameters. Choose one from
the Process combo, then expand the relevant sections; collapsed headers show
summaries. A modified marker means the current working pipeline differs from
the saved preset.

- **Save:** overwrite the selected preset; without a selected saved entry,
  create a new one through Save as.
- **Save as:** name and create a separate reusable recipe.
- **Revert:** discard current recipe edits and reload the saved recipe.
- **More → Import / Export:** read/write a process JSON file.
- **Rename / Delete:** maintain the preset library.
- **Edit pipeline stages:** advanced editing of order, enabled flags and
  duplicate stages. Dependencies still matter; unusual ordering can invalidate
  geometry or create duplicate paths.

Switching away from a modified recipe asks how to handle it. Dirty working
pipelines are remembered across a restart, but they are not a substitute for
saving/exporting a recipe you want to share.

A recipe contains neither filament calibration nor printer dimensions. It
also does not contain model placement, support mode, overhang angle, edge
extension, hole-fill threshold or support blocks. Select/edit those in the
Model dock. See [ownership](../profiles-and-state.md).

## Suggested tuning order

1. Verify STL scale, orientation and plate fit.
2. Calibrate machine/material/nozzle profiles and templates.
3. Choose layer heights and wall width/count; inspect thin sections and holes.
4. Choose solid-shell thickness and sparse infill.
5. Add adhesion as needed; ensure extra paths fit the bed.
6. Enable model support if needed; inspect gaps, interfaces and support reach.
7. Set requested speeds and travel/retraction behaviour. Review actual caps.
8. Slice and inspect the first layer, transitions, overhangs, final surfaces,
   temperature changes and end code before export.

Changing multiple unrelated settings at once makes failures difficult to
attribute. Example numeric settings in this manual explain behaviour, not a
validated print-quality profile.

## Current limits

Contours, offsets and support/shell masks use a minimal geometry kernel.
Very thin, self-intersecting, nonmanifold or densely detailed geometry may
lose features. There is no general variable-width wall strategy or guarantee
of printability. Preview hides/show categories only for inspection; hidden
features are still emitted. See [troubleshooting](../troubleshooting.md).
