[Documentation index](README.md)

# Development, extensions and documentation maintenance

## Repository map

| Area | Responsibility |
|---|---|
| `gcodeproducer/core/jobs/` | Job, layer/path/condition records, model placement, session construction |
| `core/pipeline/` | Steps, results and ordered pipeline execution |
| `core/libraries/` | Profile/process records and libraries, schemas and starter specifications |
| `core/parameters/`, `core/settings/`, `core/workflows/` | Shared coercion/default rules, application preferences and workflow compatibility |
| `core/geometry/`, `core/fdm/` | Mesh/region records, STL geometry kernel, infill and model-owned support |
| `core/cam/` | Separate setup/reference/shape/operation/topology/stock classes; drawing hit tests, paths, tabs, cutting, engagement and material systems; `model_shadow.py`, `drop_surface.py` and `surface_paths.py` for the model-surface-limited operations |
| `core/gcode/` | Builder, line/program records, parsing, templates, variables, features, simulation and path arrays |
| `core/runtime/`, `core/plugins/` | Qt-free compute tasks and recursive plugin discovery/registries |
| `gui/application/` | Application startup, workflow coordination, persistence, docks and actions |
| `gui/runtime/` | Compute process service and separate queue-reader class |
| `gui/history/` | Bounded transactional history, structural widget mementos, main-window and modal domain adapters; shared Help shortcut table |
| `gui/rendering/` | Cameras, separate GL mesh classes, Prepare/Preview and plate/material rendering |
| `gui/editors/`, `gui/inspection/` | Parameter/process/CAM/stock/tab/reference/template editors (`section.py` is the one collapsible pane used by every panel); G-code table/panel and `playback_bar.py`, the Preview cursor/layer/transport controller shared by FDM and CAM |
| `gui/dialogs/`, `gui/messages/` | Libraries/Settings dialogs, message panel and pop-ups |
| `importers/`, `stages/base/`, `stages/fdm/`, `stages/cam/` | One-class importer/stage implementations and public stage API |
| `plugins/` | Repository-local optional Python extensions |
| `examples/` | Example geometry |
| `tests/` | Automated regression tests |
| `docs/`, `tools/generate_reference.py` | Handwritten manual and schema-derived reference |

Paths beginning with `core/` or `gui/` above are under `gcodeproducer/`.
Each application Python file defines at most one class. Named module constants,
schemas and dispatch/choice tables belong to the owning directory's local
`<directory>_constants.py`; for example `core/cam/cam_constants.py` and
`gui/editors/editors_constants.py`. Stage classes reference shared parameter
tables instead of embedding a second copy.

Old flat module paths remain thin compatibility exports, not implementations.
Use the subsystem modules for new internal code; existing plugin imports such
as `gcodeproducer.stages.base` continue to work. See the
[cleanup and UI audit](cleanup-and-ui-audit.md) for removed unused definitions,
default-loading changes and retained inactive/overlapping controls.

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
group and operation metadata. Wall-parallel pocket paths can carry `stay_down`
permission and an expected preceding XY endpoint. The planner validates each
straight connector against the cutter-centre region; the emitter checks the
endpoint and resets same-depth permission at every layer/operation/tool boundary.
Do not infer safe linking from proximity alone. Staying down between depth passes
is independently checked against current material before a level link and ramp.
`core/cam/engagement.py` then subtracts completed planar sweeps to choose clearing
hand (slots are neutral) and attaches per-segment/link `CutCondition` records.
Closed-loop reversal preserves the seam and therefore valid link endpoints.
The emitter applies feed factors/caps and carries engagement/notes into program
metadata. Depth-tagged planar sweeps now carry removal across operations;
identical material states reuse engagement plans. Emitted movements additionally
update a height field and per-operation display meshes in `core/cam/material.py`.
Surface-limited operations (`_surface_operation` in `core/cam/planning.py`) plan
each level against `ModelShadow.at(z)`; 3D Contour stores `(n, 3)` path points,
which the emitter writes as XYZ moves and which the planar material history
deliberately ignores. Do not document these representations as complete 3D solid simulation. The emitter marks program lines with layer and
operation information so Preview preserves execution order across tool changes.

## Editor history and versions

`EditHistory` snapshots domain records and editable widget values/selections.
Input boundaries and change signals batch a complete drag or control action;
Undo/Redo own their shortcuts even inside Qt text/spin editors. Modal editors
have independent histories. Widget addresses are structural, so rebuilt forms
can restore selections without keeping obsolete widgets alive. Child dialogs
and control internals are excluded from their parent's widget memento.
QMainWindow-owned dock tab bars are also excluded: Qt replaces these using
deferred deletion during layout restoration. Recording them can create a
phantom edit after Undo and incorrectly discard Redo. Unchanged dock layouts
are not restored again.
`WindowState` restores model-owned data, both pipelines, owned profile/process
files and preferences, then rebinds the editors. Source meshes are shared,
not copied per edit, and released when no bounded history entry uses them.
Content changes invalidate output and cancel pending compute results; view-only
restoration does not. New editor-owned state must be added to its adapter;
new ordinary Qt controls join automatically at their next input event.

`placement_face` is a compute task: a ray picks the nearest triangle normal.
The GUI composes that alignment with the existing rotation, retaining XY/scale,
then anchors the entire mesh below the CAM stock top or above the FDM bed.

Versions use **major.minor.build**. Increment the build once per user-request
turn; change minor/major only on explicit
operator instruction. Keep `pyproject.toml` and `gcodeproducer/__init__.py` in
sync; template-variable examples use `__version__`. See root `AGENTS.md`.

## Ownership invariants

- Never place translation, rotation, support mode/blocks or stock in FDM
  process parameters just to reuse a form builder.
- Process selection/editing must not change model placement/support state.
- FDM machine fields define capabilities; process requests speeds; material
  requests temperatures; nozzle supplies geometry/flow limits.
- CAM operations reference library tool IDs, mesh indices or stable drawn-shape
  IDs. Re-evaluate mesh coordinates after placement; invalidate references for
  changed source meshes. Model-owned `ReferenceShape` objects remain in fixed
  work coordinates like stock; placement must not silently transform them.
  Ray/plane construction is scalar GUI work; polygon construction, projection
  picking, highlights and toolpath computation stay in the compute process.
- Stock is independent of later placement changes unless the user requests
  Auto again. Support/material occupy one shared UI slot; CAM reference
  geometry is a separate Model-dock pane below it.
- Preview cursor and layer range belong to `PlaybackBar`; the window only
  applies its `cursorChanged` / `layersChanged` signals to the viewer, text
  panel, vertical layer slider and status line.
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
registers subclasses defined in that module. Built-in package scanning is recursive,
so stages in `stages/fdm/` and `stages/cam/` are found once; re-export modules are
not duplicate registrations. Choose unique IDs; duplicate IDs
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

For a profile/process field, define ownership first, then its local constant/schema
table, resolution, actual behaviour, persistence/migration and tests. Generated
forms use `resolve_params` / `Param.coerce`, not a separate GUI default/coercion
implementation. Keep table defaults, reset values and constructor fallbacks aligned. If not yet
implemented, label it reserved/descriptive rather than implying that a field
is enforced. Update reference generation when adding a new built-in stage.

## Panes and layout conventions

Build every panel group with `gui.editors.section.Section`, never `QGroupBox`
(a test enforces this for the main window). Pass `key="dock.pane"` to remember
the expanded state in Qt settings, `level=1` for a pane nested in another pane,
and either a ready body widget or fill `section.body`. Lists with actions put
the buttons directly under the list. Checkable viewport tools (Place blocks,
Place tabs, Draw/Move/Resize) are highlighted while active and end on Esc or a
second click.

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
