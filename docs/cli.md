[Documentation index](README.md)

# Command-line interface

Run from an installed environment or the repository checkout:

```bash
python -m gcodeproducer --help
python -m gcodeproducer slice --help
```

Examples below use POSIX `\` line continuation; put a command on one line in
Windows shells, or use that shell's continuation syntax. Profile names with
spaces must remain quoted.

## Discovery commands

| Command | Purpose / options |
|---|---|
| `workflows` | List available workflows |
| `stages [-w fdm\|cam] [-v]` | List built-in/discovered stages, optionally with parameters |
| `describe STAGE_ID` | Describe a stage's parameters/defaults |
| `libraries [--library PATH] [--no-seed]` | List profiles from library root |
| `processes [-w WORKFLOW] [-v] [--library PATH] [--no-seed]` | List stored pipeline presets |
| `gui [MODEL.stl]` | Launch desktop UI, optionally importing a model |
| `--version` | Print application version |

Stage discovery can load external Python plugins; only use trusted plugin
paths. Generated documentation, in contrast, documents built-ins without
loading user plugins.

## Slice command and precedence

```text
python -m gcodeproducer slice INPUT.stl [options]
```

| Option | Meaning |
|---|---|
| `-w`, `--workflow` | `fdm` (default) or `cam` |
| `-o`, `--output` | Output path; supply `.nc` explicitly for CAM if desired |
| `--machine` | Profile ID/name matching the chosen workflow |
| `--material`, `--nozzle` | FDM consumables |
| `--tool` | One tool for the legacy CLI CAM profile |
| `--cam-material` | Machining category for an automatic SFM/chip-load tool (e.g. `non_iron_metal`, `steel`) |
| `--pref KEY=VALUE` | Override one [global setting](settings.md) for this run (repeatable); `gcodeproducer settings` lists keys |
| `--process` | Saved pipeline preset by ID/name |
| `--config` | Pipeline JSON; takes precedence over `--process` |
| `-m`, `--stage-param` | Repeatable `stage_id:key=value,...` override |
| `--layer-height` | Explicit job normal-layer override (FDM) |
| `--library` | Library root override |
| `--no-seed` | Do not add starter entries while loading libraries |
| `-q`, `--quiet` | Suppress ordinary slicing log output |

Without explicit profile selection, the CLI picks an available entry, which
may not be the hardware you intend. Prefer explicit IDs/names and verify
`libraries` output. Workflow mismatches are rejected. FDM allowed-consumable
mismatches are reported as warnings rather than being the GUI's selection
filter; do not assume CLI selection is fully machine-qualified.

Pipeline choice is: `--config`, else named `--process`, else workflow default.
Stage overrides then merge into existing steps and enable the overridden
stage. A `-m` option cannot add a stage absent from that pipeline; unknown
parameter names are errors. Per-job `--layer-height` wins over the normal
height resolved from the layer step. Model placement/support flags are
independent of process parameters.

The default output extension is `.gcode` even for legacy CAM unless you give
`-o`. Logs normally go to stderr. Many invalid parameter/profile cases return
an error exit status; do not treat file existence alone as a completed,
verified job. Do not suppress logs during first-time setup or diagnosis.

## FDM examples

```bash
python -m gcodeproducer slice examples/cube20.stl -w fdm -o cube.gcode \
  --machine "Generic 220 FDM" --material PLA --nozzle "0.4 mm" \
  --process "0.12 mm Fine"
```

Starter names may be absent from an older nonempty library. Substitute IDs
from `libraries`/`processes` rather than assuming a missing starter was added.

Override selected stage settings:

```bash
python -m gcodeproducer slice examples/cube20.stl -o cube.gcode \
  --machine "Generic 220 FDM" --material PLA --nozzle "0.4 mm" \
  --layer-height 0.2 \
  -m "fdm_perimeters:perimeters=3" \
  -m "fdm_top_bottom:top_layers=5,bottom_layers=4" \
  -m "fdm_infill:density=25,pattern=cubic"
```

## Placement flags

| Flag | Meaning |
|---|---|
| `--x`, `--y` | Transformed model bounding-box centre |
| `--z` | FDM bottom height; CAM **top** height, default 0 |
| `--rotate-x`, `--rotate-y`, `--rotate-z` | Degrees about world axes |
| `--scale` | Uniform percentage, default 100 |
| `--lay-flat` | Choose a largest-face-down orientation |

Without XY overrides, FDM centres on the bed; legacy CAM retains the model's
original XY centre. The GUI normally offers explicit centring/remembered
placement, so do not assume its remembered state is loaded into a CLI job.
CAM top is anchored at zero with negative body Z; FDM bottom at zero.

## Model support flags

| Flag | Default | Meaning |
|---|---|---|
| `--support` | `none` | `none`, `buildplate`, `everywhere`, `blocks` |
| `--overhang-angle` | 50° | Automatic overhang threshold from vertical |
| `--support-extend` | 1 mm | Reach beyond supported edges |
| `--fill-holes` | 0 mm² | Area threshold for filling support holes; 0 off |
| `--support-blocks` | None | JSON list (or object with `blocks`) of block bounds |

```bash
python -m gcodeproducer slice bracket.stl -o bracket.gcode \
  --rotate-x 90 --x 80 --y 100 --support everywhere \
  --overhang-angle 45 --support-extend 1.5
```

Manual blocks use world/bed coordinates after placement:

```json
[
  {"x0": 95, "y0": 95, "z0": 0, "x1": 125, "y1": 125, "z1": 20}
]
```

```bash
python -m gcodeproducer slice bracket.stl --z 3 \
  --support blocks --support-blocks blocks.json
```

Old `-m "fdm_support:placement=..."` syntax is not a model-support setting and
is rejected. Use the dedicated flags. Support density/gaps/interfaces remain
`fdm_support` stage parameters. See [support](fdm/support.md).

## Legacy CAM command

```bash
python -m gcodeproducer slice examples/cube20.stl -w cam -o part.nc \
  --machine "Generic 300 Router" --tool "6 mm flat endmill" \
  -m "cam_profile:side=outside,stepdown=1.5"
```

This profiles the part silhouette with **one tool**. `final_depth=auto` goes
to the placed model bottom; a numeric final depth is a positive distance below
its top. It is not the tree operation End Z source system.

Automatic SFM/chip-load tools require explicit `--cam-material` so the CLI
does not silently assume a machining material. RPM/feed calculation uses that
category; legacy profile stepdown parameters still control axial passes rather
than the GUI's automatic material/process depth setting.

The CLI currently has **no tree/setup/stock import flags** for GUI Pocket,
Drill, Engrave or multi-tool setups. `--config` loads a pipeline, not a
`CAMSetup` or GUI model state. Legacy CAM does not automatically allocate
stock or run the setup-dependent stock checks. Safe Z and all output still
require independent verification.

For programmatic integration, use `CAMSetup`, `build_job(..., cam_setup=...)`
and `slice_job`; these are described in [development](development.md).

## Isolated libraries

Use a throwaway root for experiments:

```bash
python -m gcodeproducer libraries --library ./scratch-library
python -m gcodeproducer processes --library ./scratch-library -v
```

This does not redirect GUI Qt settings or disable plugin discovery. See
[profiles and persistence](profiles-and-state.md) for environment variables
and backup boundaries.
