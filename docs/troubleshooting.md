[Documentation index](README.md)

# Troubleshooting and current limitations

## Start with evidence

Record workflow, model path/size, machine and consumable IDs, process or CAM
operation settings, placement, warnings and the full failing log/traceback.
Reproduce using a simple model and a copy of the library. Preserve the original
settings before deleting state or resetting profiles. Never test an uncertain
G-code fix by immediately running it on hardware.

## Installation and UI

| Symptom | Checks / action |
|---|---|
| Module not found | Install with the same `python` used to launch; use `python -m pip`, activate the intended environment |
| Qt/OpenGL errors or blank viewport | Verify a desktop session, GPU driver and supported OpenGL context; remote/headless environments may not supply one |
| A dock disappeared | Re-enable it through View; check floating windows and remembered monitor positions |
| Prepare/Preview seems differently scaled | Both share camera and machine rectangle; check Fit/view mode and stale paths, not only toolpath extent |
| Model below an opaque plane in CAM | Current CAM uses a negative-Z frame with no opaque plate; verify you're running updated code and the correct workflow |
| Controls moved or labels differ from a screenshot | Screenshots can be older; use current guide text and exact schema reference |
| UI stalls or task never finishes | Check Log, memory and compute-process errors; Cancel and retry with a smaller model; avoid repeated huge queued tasks |

Offscreen Qt is useful for tests, not a guarantee that a real OpenGL viewport
works. CPU tests passing does not validate your graphics driver.

## Library and persistence

- **Missing profile:** confirm root/`--library`/`GCODEPRODUCER_LIBRARY`, kind,
  workflow, valid JSON and the machine's allowed IDs. Malformed JSON can be
  skipped on load. Empty allowed lists intentionally allow nothing.
- **Missing new starter material:** nonempty libraries are not automatically
  reseeded with every new default. Create/import an appropriate profile.
- **Old speeds appear ignored:** legacy FDM machine request fields moved to
  process settings. Re-enter requests in processes and verify machine limits.
- **Model support changed unexpectedly:** support mode/angle/extension/blocks
  should be model state. Old process support placement is not automatically
  reliable migration; select the model mode explicitly. A process still
  changes the support style/gaps and can change the visible result.
- **Reopened model has no setup:** model state is path-keyed Qt settings,
  not in STL/process JSON. Moving files or changing settings namespace can
  produce fresh state. Changed CAM source geometry invalidates references.
- **Copying libraries did not copy placement/stock:** back up Qt settings too;
  profile JSON is only one part of persistent state.

## FDM geometry and output

| Symptom | Likely cause / next inspection |
|---|---|
| Part floats / many empty lower layers | FDM Z is lifted; Drop to bed or enable appropriate support |
| No support | Mode None, no relevant blocks, minimum area, angle, XY distance, gaps or unsupported raster-scale details |
| No brim on lifted part | Intentional: model does not touch the first layer; skirt can still exist |
| Bottom support interfaces missing on old output | Regenerate with current code; bottom interfaces now apply on bed and model |
| Hole rims unsupported | Inspect actual wall side/placement and support extension, not just support density |
| Thin walls disappear | Fixed-width offsets cannot fit requested loops, or invalid mesh/limited kernel; repair and inspect widths/counts |
| Sparse infill overlaps/looks different from solid fill | Verify stage order, shell masks, feature filters and stale output; advanced duplicate stages can reprint paths |
| Requested speed not reached | Read speed/flow caps; line width, height, flow and nozzle/machine limits matter |
| Small layers do not slow down | Material minimum-layer-time is stored but not implemented by the emitter |
| Temperatures differ from requests | Machine cap, unavailable chamber, first-versus-normal temperature semantics, or custom template commands |
| Fan starts in wrong state | Check custom startup, fan-start layer and PWM request; do not assume existing controller state |

## CAM selection and generation

- **Can't select a particular edge:** STL topology uses feature chains and a
  crease threshold; a shallow edge/triangle seam may be absent. Curved CAD
  surfaces are not analytic selectable faces.
- **Open contour error:** select all required connected edges, or a horizontal
  face boundary. One cube edge is not a closed profile. Use Engrave for a
  suitable open line, not to bypass an unsafe profile plan.
- **Horizontal/constant-Z error:** 2.5D cutting requires horizontal faces or
  constant-Z edge chains. A height reference may be nonhorizontal, but that
  does not make it valid cutting geometry.
- **Wrong End Z:** check source, offset sign, selected extreme, live reference,
  top-at-zero placement and whether a pick was applied to the intended field.
- **Pocket too small:** cutter radius plus allowance erased the region; inspect
  tool size, stock-to-leave and the actual selected loops.
- **Drill rejects face/rim:** select circular horizontal rims with at least
  eight segments. A rectangle/irregular STL is not an analytic hole.
- **Missing tool:** the setup uses a library ID unavailable on the machine.
  Restore/reselect it; do not substitute by name without checking dimensions.
- **Unsafe Z error:** safe Z must exceed stock/model/operation start heights.
  Start Z is not safe Z. Change the machine clearance, not just the end depth.
- **No enabled operations:** add/select/enable meaningful operations.

## CAM stock warnings

Use [the full warning guide](cam/stock-and-safety.md). A rapid collision warning
now uses current height-field material, but grid resolution can still miss or
approximate contact. The stock outline alone is not a removal result; select
[calculated operation output](cam/material-state-and-leads.md). Tool radius
can overlap stock when the centreline is outside it. An entry-depth warning
may mean an operation starts below unremoved material. Below-bottom motion
can hit a table even when the cutter is outside the blank XY bounds.

Unclassified custom feed moves, controller offsets/cycles/compensation and
arcs require independent review. A warning-free program still lacks fixture,
holder, full stock-removal and machine-kinematic verification. CAM export
blocked as stale means regenerate after edits; confirming an earlier dialog
does not recheck a changed blank.

For SFM errors, compare material target RPM with both machine/tool ceilings
and the machine minimum. A below-minimum target is not silently increased.
Verify material category, tool-table units, flute count and independent rate
unlocks. Lead-in fallback warnings mean the selected contour cannot fit the
requested ramp; confirm plunge capability or revise the entry.

## Template problems

Unknown variables and arithmetic/format failures can remain as literal brace
tags in output. Never run such output. Use Insert variable, check workflow
availability, inspect all branches and distinguish normal from first-layer
temperatures. Preview uses examples, not actual job values. Reset restores a
generic template, not a verified machine post. See [templates](gcode-templates.md).

## Known scope boundaries

One STL model at a time; minimal contour/offset/raster geometry; no guarantee
for nonmanifold/self-intersecting/thin geometry; no general CAD/STEP support;
no production-quality 3D CAM or general collision certification. Advanced
pipeline editing and custom G-code can invalidate otherwise sensible defaults.
Report reproducible issues with a small model and sanitized settings.
