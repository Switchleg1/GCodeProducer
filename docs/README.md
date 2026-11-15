# GCodeProducer documentation

[Project overview](../README.md)

This is the user and developer manual for the current implementation. It covers
what each feature does, where its settings live, how to use it, its output, and
its limitations. Defaults in examples are starting points, not recommendations
for a particular printer, material, cutter, or machine.

## Read the manual

- **On GitHub:** open any link below; Markdown tables, images and code are rendered there.
- **Locally:** open this file (`docs/README.md`) in a Markdown-capable editor/viewer
  and follow relative links. Source files are ordinary UTF-8 text.
- No documentation server, package installation, website build, or internet
  connection is needed to read the local manual. Linked external projects may
  require internet access.
- Search the `docs/` directory for a UI label or setting key. If a tooltip and a
  guide disagree, consult the reference and source; report the discrepancy.

## Start here

1. [Installation and first jobs](getting-started.md)
2. [GUI, placement, preview and keyboard controls](gui.md)
3. [Settings ownership, libraries and saved state](profiles-and-state.md)
4. Choose [FDM printing](fdm/README.md) or [CAM machining](cam/README.md).
5. Before machining, read [stock checks and their limitations](cam/stock-and-safety.md).

## FDM processes and support

| Guide | Coverage |
|---|---|
| [FDM workflow](fdm/README.md) | Pipeline, presets, tuning order, first print checklist |
| [Layers](fdm/layers.md) | Normal/first layer heights, lifted models, resolution |
| [Skirt and brim](fdm/adhesion.md) | Priming, adhesion, widths, gaps, lifted parts |
| [Walls](fdm/walls.md) | Perimeters, line widths, holes, thin features |
| [Solid shells and sparse infill](fdm/infill.md) | Surface detection, patterns, density, overlap, ordering |
| [Support](fdm/support.md) | Automatic modes, manual blocks, gaps, interfaces, edge/hole handling |
| [Speed, travel and output](fdm/speed-and-output.md) | Feature speeds, caps, flow, seams, retraction, temperatures, fan |

## CAM processes, material and geometry

| Guide | Coverage |
|---|---|
| [CAM workflow](cam/README.md) | Tool-change tree, negative-Z convention, generation and export |
| [Selecting geometry and depths](cam/selection-and-depths.md) | Planar faces, feature chains, selection purpose, live Z references |
| [Engagement, cutting hand and feeds](cam/engagement-and-feeds.md) | Neutral slots, remaining-material direction, Low/Standard/High/Slotting factors and feed caps |
| [Toolpath strategy and direction](cam/toolpaths.md) | Wall-parallel offsets, square/circle transitions, climb/conventional/meander and machine defaults |
| [Pocket, Profile, Drill and Engrave](cam/operations.md) | Every operation field, algorithms, defaults, examples and restrictions |
| [Stock allocation and safety](cam/stock-and-safety.md) | Material properties, Auto margin, bounds, warning interpretation, verification |

## Cross-workflow topics

- [Start/end G-code templates](gcode-templates.md): editing, expressions,
  conditionals, dictionary values, errors and default behaviour.
- [Command-line interface](cli.md): commands, options, precedence, FDM examples,
  legacy CAM scope and library isolation.
- [Troubleshooting and limitations](troubleshooting.md): diagnosis by symptom,
  migration issues, geometry problems, missing settings and recovery.
- [Development and extensions](development.md): architecture, stages/importers,
  compute tasks, tests and documentation maintenance rules.

## Exact reference

[Reference index](reference/README.md): generated tables of all built-in stage
parameters, profile settings, template variables and literal default templates.
Handwritten guides explain interactions and implementation caveats that schema
tables alone cannot express.

## Status and safety

The application supports one STL model at a time. STL/FDM geometry uses a
minimal NumPy kernel; CAM pocket offsets use Shapely/GEOS. FDM and 2.5D CAM are implemented; robust general polygon operations,
general 3D machining and CAD topology are not. Preview is an inspection aid,
not a machine-accurate material-removal simulator. Time estimates omit machine
acceleration and controller effects. Never interpret a successful generation,
an empty warning list, or a green-looking preview as certification that output
is physically safe.

Screenshots illustrate UI concepts and may show older labels or layouts:
[Prepare](pictures/prepare.jpg), [Preview](pictures/preview.jpg),
[Support panel](pictures/support_panel.jpg). All documentation images live in
[`docs/pictures/`](pictures/README.md); add feature illustrations there and link
them from the relevant guide.

To contribute or update this manual, follow the
[documentation contract](development.md#documentation-contract).
