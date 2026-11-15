[Documentation index](README.md)

# Development, extensions and documentation maintenance

## Repository map

| Area | Responsibility |
|---|---|
| `gcodeproducer/core/job.py` | Mutable job, layers and paths passed through stages |
| `core/session.py` | Importer selection, job construction, placement, pipeline entry point |
| `core/pipeline.py` | Ordered steps, resolution, workflow checks, results and timing |
| `core/process.py` | Reusable pipeline presets and their JSON library |
| `core/profiles.py`, `core/params.py` | Profile schemas, default/coercion rules, allowed consumables |
| `core/geometry.py` | STL loading/welding, slicing, offsets, raster masks, picking math |
| `core/placement.py`, `core/support.py` | Model transformation, FDM support masks/blocks |
| `core/cam.py`, `core/cam_paths.py`, `core/stock.py` | CAM setup/topology/references, Shapely wall-parallel offsets/direction, and conservative stock checks |
| `core/gcode_template.py`, `core/gcode_vars.py` | Template evaluation, variable registry and defaults |
| `core/builder.py`, `core/gcode.py` | Emission and G-code line/program representation |
| `core/sim.py`, `core/toolpath.py` | Modal state simulation and viewer-ready path arrays |
| `core/compute.py` | Qt-free compute-process tasks and worker loop |
| `gui/compute_service.py` | Process lifecycle, queue reader and Qt signals |
| `gui/main_window.py` | Workflow coordination, persistence, docks and actions |
| `gui/model_viewer.py`, `gui/viewer.py`, `gui/bed.py` | Prepare/Preview and shared plate/stock rendering |
| `gui/process_editor.py`, `cam_editor.py`, `stock_editor.py` | Workflow-specific editing |
| `gui/library_dialog.py`, `widgets.py`, `gcode_edit.py` | Profile and generated/template controls |
| `importers/`, `stages/` | Built-in importer and stage classes |
| `plugins/` | Repository-local optional Python extensions |
| `examples/` | Example geometry |
| `tests/` | Automated regression tests |
| `docs/`, `tools/generate_reference.py` | Handwritten manual and schema-derived reference |

Paths beginning with `core/` or `gui/` above are under `gcodeproducer/`.

## Pipeline and job contract

`build_job()` assembles machine/consumables, original mesh, placement,
model support, optional CAM setup and explicit settings. `slice_job()` checks
CAM source fingerprints where supplied, applies placement, and runs a
`SlicePipeline`. A job is mutated by stages; do not casually reuse the same
already-placed job for another placement pass.

Each step has stage ID, parameters and enabled flag. Stages declare supported
workflows. Incompatible stages are skipped by pipeline execution, while a
direct incompatible execution raises a workflow error. Core stages execute
even when their stored enabled flag is false. Adding default core stages to
an older pipeline is a compatibility mechanism, not a guarantee that any
arbitrary custom stage order is valid.

FDM paths are XY polylines plus layer Z, width, feature and optional speed.
CAM currently copies XY paths across depth passes and tags passes with tool,
group and operation metadata. The emitter marks program lines with layer and
operation information so Preview preserves execution order across tool changes.

## Ownership invariants

- Never place translation, rotation, support mode/blocks or stock in FDM
  process parameters just to reuse a form builder.
- Process selection/editing must not change model placement/support state.
- FDM machine fields define capabilities; process requests speeds; material
  requests temperatures; nozzle supplies geometry/flow limits.
- CAM operations reference library tool IDs and geometry indices. Re-evaluate
  coordinates after placement; invalidate references for changed source meshes.
- Stock is independent of later placement changes unless the user requests
  Auto again. Support/material occupy one shared UI slot.
- Effective output and validation must match documented implementation,
  including reserved/descriptive fields and missing capability checks.

## Adding a stage plugin

Discovery searches repository `plugins/`, `~/.gcodeproducer/plugins`, and
paths in `GCODEPRODUCER_PLUGINS` separated by `os.pathsep` (`;` on Windows,
`:` on typical POSIX systems). Plugins are executable Python; trust matters.
Do not use a plugin search path as a sandbox for untrusted code.

```python
from gcodeproducer.stages.base import SliceStage, Param, FDM

class InspectPaths(SliceStage):
    id = "inspect_paths"
    name = "Inspect paths"
    description = "Report paths without modifying geometry."
    workflows = (FDM,)
    optional = True
    params = [Param("verbose", "bool", False)]

    def run(self, job, params, ctx):
        count = sum(len(layer.paths) for layer in job.layers)
        if params["verbose"]:
            ctx.log(f"There are {count} paths")
        ctx.progress(1.0)
        return f"{count} paths inspected"
```

A nonempty ID and explicit workflow declaration are required. Class discovery
registers subclasses defined in that module. Choose unique IDs; duplicate IDs
can replace registry entries. Plugin load failures are collected and shown in
the GUI log. Add a discovered stage to a pipeline via the advanced editor or
pipeline JSON; CLI `-m` edits an existing step and does not insert one.

Stage `run()` reads/writes the job and returns a summary. Report progress in
[0,1] and useful context through `ctx.log`. Avoid UI objects in stage logic.
Declare Params for generated editors, coercion/ranges, choices, help and
reference coverage. Unknown legacy keys may be ignored by ordinary resolution;
CLI overrides use strict validation to catch typos.

## Importer extensions

An importer derives from `importers.base.Importer`, declares an ID, supported
extensions/handling and a `load(path)` implementation returning compatible
mesh geometry. Follow the built-in STL importer and geometry Mesh contract.
The mesh must support stable indexed vertices/triangles if CAM references are
to survive placement. Do not claim exact CAD topology merely because a new
file format can be triangulated. Document unit conversion, validation and
selection limitations for every importer.

## Background computation

The GUI uses a persistent multiprocessing **spawn** worker, not just a Python
QThread for CPU-heavy loops. A reader thread relays queue messages through Qt
signals. Tasks carry serializable jobs/arrays and return serializable data;
never send widgets or OpenGL contexts into the worker.

Messages contain task ID and log/progress/chunk/done/error kind. Large
programs are sent in chunks (currently 5,000 lines) to limit GUI-side object
construction pauses. Toolpath preparation and filament calculation also run
in the worker. The GUI freezes large completed object graphs out of periodic
GC scanning; that is a responsiveness measure, not removal of all memory cost.

Cancellation terminates/restarts the compute service rather than depending on
a cooperative check in every geometry loop. Selection results are task-ID
checked and highlights debounced so stale scenes do not overwrite current
ones. New tasks must handle cancellation, stale responses, error reporting
and shutdown. Windows launch paths need a guarded entry point and
`multiprocessing.freeze_support()` when appropriate.

## Templates and new settings

Every custom G-code box uses the same safe evaluator and shared variable
registry. A `Param(..., "gcode", default=...)` receives the reusable editor,
Reset, insertion menu, example preview and live check. Rendering a new kind
of event still requires wiring its template source/default and providing
correct event-specific values; merely adding a Param does not create an
emission event.

For a variable, add registry metadata (name/category/description/example/
workflows), fill it in `job_variables()` or an explicit event override, and
add tests proving availability, effective values and workflow boundaries.
Do not expose unsafe arbitrary Python as template evaluation.

For a profile/process field, define ownership first, then schema/default,
resolution, actual behaviour, persistence/migration and tests. If not yet
implemented, label it reserved/descriptive rather than implying that a field
is enforced. Update reference generation when adding a new built-in stage.

## Tests and checks

From the repository root:

```bash
python -m pip install -e ".[dev]"
python tools/generate_reference.py
python tools/generate_reference.py --check
python -m pytest -q
```

GUI tests use offscreen Qt, isolated libraries and distinct Qt settings
namespaces. They should not read/write your real library for routine tests.
OpenGL rendering on actual drivers still needs manual checks. For a new CAM
strategy, test invalid geometry, reference changes, depth bounds, tool order,
stock-contact assumptions, metadata and export warnings—not only a happy-path
G-code string. Never execute tests' output on hardware without qualification.

## Documentation contract

Keep root `README.md` a short feature list, launch example, safety/status note
and links. Put detailed instructions in `docs/`, not back into the overview.
For each new or changed feature/process:

1. Add/update its guide and link it from the documentation index and relevant
   workflow index. Prefer focused feature pages over a single growing manual.
2. State purpose, workflow, UI location, input geometry and generated output.
3. List settings with units/defaults, who owns them, how auto values resolve,
   interactions and practical examples. Link to exact schema tables.
4. Explain steps to use the feature and inspect the result, errors/warnings,
   limitations and what is **not** implemented or verified.
5. Describe persistence, migration and invalidation rules. Distinguish presets,
   profiles, model state and controller state.
6. Regenerate checked-in reference pages after schema/default/variable changes.
   Do not hand-edit generated tables. Keep developer documentation alongside
   extension/API changes.
7. Add regression tests, run link/reference tests and capture pictures as useful
   features are added/documented. Store all images in `docs/pictures/`, add an
   inventory entry in its README and link from the feature guide. Use real
   application captures; label annotations and old screenshots explicitly.
   Follow the [picture guidelines](pictures/README.md).
8. Never turn numeric examples into claims of calibrated physical safety or
   silently document reserved fields as working behaviour.

Documentation tests verify local links/anchors, generated-reference freshness,
built-in stage/operation coverage and the lightweight README boundary. They
cannot establish that prose is physically correct; review it against source
and actual behaviour before committing.
