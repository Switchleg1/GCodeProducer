# GCodeProducer

GCodeProducer is a Python / Qt6 desktop and command-line app that **produces
G-code** from geometry. Where its sibling project
[GCodeTools](../GCodeTools) *reads and post-processes* existing G-code,
GCodeProducer runs a **slice pipeline** that turns a model into G-code for
either 3D printing (FDM) or subtractive machining (CAM). It shares GCodeTools'
3D viewer, G-code model, machine simulation and declarative-parameter system,
so produced jobs can be inspected with the same interactive viewer.

> **Status:** early (v0.1.0). The library/profile system, the FDM and CAM slice
> pipelines, the CLI and a Qt6 GUI work and have tests. The geometry kernel is
> minimal (good for prismatic / convex-ish parts); expect rough edges.

---

## Concept

Everything hangs off a **workflow**, a **machine** and the machine's
**consumable libraries**:

```
FDM workflow  ->  machine profile  ->  material library + nozzle library
CAM workflow  ->  machine profile  ->  tool library
```

- **Speeds and feeds live on the machine profile.** A machine runs every
  material / tool at *its* rates.
- **Libraries are stored separately** as folders of JSON files, so materials,
  nozzles and tools can be shared and versioned independently.
- **The machine selects which consumables are available.** Each machine has
  `allowed_materials` / `allowed_nozzles` (FDM) or `allowed_tools` (CAM); the
  slice UI only offers consumables the chosen machine allows.

Libraries live under `~/.gcodeproducer/` by default (override with the
`GCODEPRODUCER_LIBRARY` environment variable):

```
~/.gcodeproducer/
  machines/*.json      machine profiles (each tagged fdm or cam)
  materials/*.json     FDM filaments
  nozzles/*.json       FDM hot-end orifices
  tools/*.json         CAM cutters
  processes/*.json     process presets (saveable workflow options)
```

### Process presets (workflow options)

A **process preset** bundles a whole slice pipeline — which stages run, in what
order, with which parameters (layer height, perimeters, top/bottom layers,
infill density/pattern, …) — for one workflow. Presets are saved / loaded
independently of the machine and consumables, so you can keep e.g. *0.20 mm
Standard*, *0.30 mm Draft*, *0.12 mm Fine* and *Strong (cubic 40%)* and switch
between them. In the GUI the **Process** box has Save / Save As / Delete /
Reset; on the CLI use `--process NAME` (and `gcodeproducer processes` to list).

## The slice pipeline

A pipeline is an ordered list of **stages** — the GCodeProducer analogue of
GCodeTools' processing *modules*. Each stage declares the workflow(s) it
belongs to, has a declarative parameter schema (which generates both the GUI
form and the CLI options), and mutates a shared `Job` as it flows down the
pipeline. A stage never runs in a workflow it doesn't target, so FDM operations
(perimeters, infill, temperature) can't leak into a machining job and vice
versa.

| Workflow | Default stages                                                                     |
|----------|------------------------------------------------------------------------------------|
| FDM      | `fdm_slice` → `fdm_perimeters` → `fdm_top_bottom` → `fdm_infill` → `fdm_emit`       |
| CAM      | `cam_profile` → `cam_emit`                                                          |

- **`fdm_slice`** — positions the mesh on the bed and intersects it into
  per-layer closed contours.
- **`fdm_perimeters`** — offsets each contour inward into wall loops
  (outer + inner). The innermost loop bounds the infill region.
- **`fdm_top_bottom`** — top / bottom **solid** surfaces. A cell is sparse only
  if the part covers it in all `top_layers` above *and* all `bottom_layers`
  below; otherwise it is a solid surface (`top_infill` / `solid_infill`).
  Detection uses shared-grid rasters, so interior top shells (e.g. the top of a
  wide base under a narrow tower) are found, not just the first/last N layers.
- **`fdm_infill`** — fills the remaining interior with a pattern (rectilinear,
  grid, triangles, cubic, lines) at a chosen density, with perimeter overlap,
  angle, min line length and travel-connection options, reusing GCodeTools'
  infill generator. Sparse infill never overlaps the solid shells.
- **`fdm_emit`** — walks the toolpaths into G-code with travels, retraction,
  temperatures (from the material), cooling and start/end blocks.
- **`cam_profile`** — 2.5D contour/profile cut around the part silhouette,
  offset by the tool radius, stepping down by the tool's depth of cut.
- **`cam_emit`** — rapids at safe Z, plunges and cuts with spindle control.

## Install

```bash
pip install -r requirements.txt   # PyQt6, PyOpenGL, numpy
# or
pip install -e .
```

## GUI

```bash
python -m gcodeproducer gui                    # start the GUI
python -m gcodeproducer gui part.stl           # start and import a model
```

On Windows you can double-click `GCodeProducer.bat`.

1. Choose a **workflow** (FDM or CAM) and a **machine**.
2. Pick the **consumables** the machine allows (material + nozzle, or a tool).
3. **Import** an STL model.
4. Choose a **process** preset, then edit the **slice pipeline**: add stages
   (**+ Add**), remove them (**- Remove**), reorder them (**up / down**),
   enable / disable them with the checkbox and tune each stage's parameters.
   Core stages (slice, perimeters, emit) can be moved and tuned but not removed
   or disabled. Edits show an *unsaved* marker; **Save** writes them back to the
   selected process, **Save As** creates a new one.
5. Click **Slice** and inspect the result in the shared 3D viewer, then
   **Save G-code**.

Use **File → Edit libraries…** to add, duplicate, delete and edit machine,
material, nozzle and tool profiles. Machine profiles carry the build volume,
speeds/feeds, start/end G-code and the allowed-consumable lists.

## CLI

```bash
python -m gcodeproducer workflows               # list workflows
python -m gcodeproducer stages -v               # list slice stages + params
python -m gcodeproducer libraries               # list every profile
python -m gcodeproducer processes -v            # list process presets
python -m gcodeproducer describe fdm_infill     # one stage's parameters

# slice with a saved process preset (workflow options)
python -m gcodeproducer slice part.stl -w fdm -o part.gcode \
    --machine "Generic 220 FDM" --material PLA --nozzle "0.4 mm" \
    --process "0.12 mm Fine"

# ...or build the pipeline from scratch and tune stages
python -m gcodeproducer slice part.stl -w fdm -o part.gcode \
    --machine "Generic 220 FDM" --material PLA --nozzle "0.4 mm" \
    --layer-height 0.2 \
    -m "fdm_perimeters:perimeters=3" \
    -m "fdm_top_bottom:top_layers=5,bottom_layers=4" \
    -m "fdm_infill:density=25,pattern=cubic"

# machining
python -m gcodeproducer slice part.stl -w cam -o part.nc \
    --machine "Generic 300 Router" --tool "6 mm flat endmill" \
    -m "cam_profile:side=outside,stepdown=1.5"
```

A pipeline can be saved / loaded as JSON (`--config pipeline.json`).

## Writing a stage (plugin)

Drop a `.py` file in `plugins/`, `~/.gcodeproducer/plugins`, or a directory in
`GCODEPRODUCER_PLUGINS`. Any `SliceStage` subclass with an `id` is registered.

```python
from gcodeproducer.stages.base import SliceStage, Param, FDM

class Brim(SliceStage):
    id = "brim"
    name = "Brim"
    description = "Add N loops around the first layer."
    workflows = (FDM,)                # REQUIRED
    params = [Param("loops", "int", 5)]

    def run(self, job, params, ctx):
        ...                           # read/append job.layers[0].paths
        return f"{params['loops']} brim loops"
```

## Project layout

```
gcodeproducer/
  core/        gcode model + emitter (builder.py), geometry kernel (slicing,
               polygon offset, RegionMask), state simulation, toolpath/features
               (shared with GCodeTools), the profile/library system
               (profiles.py), process presets (process.py), job model, stage
               pipeline, plugin discovery, session driver, starter profiles
  importers/   geometry importers (stl)
  stages/      slice stages (fdm_slice/perimeters/top_bottom/infill/emit,
               cam_profile/emit)
  gui/         Qt6 main window + library editor, OpenGL viewer, widgets
  cli.py       command-line interface
plugins/       drop-in user stages / importers
examples/      sample model (cube20.stl)
tests/         pytest suite
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). Uses PyQt6 (GPL v3).
