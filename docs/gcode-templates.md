[Documentation index](README.md)

# Start/end G-code templates

**Where:** Libraries → Machine → G-code. Both workflows have multi-line
**Start G-code** and **End G-code** boxes. They are reusable machine settings,
not model geometry or FDM process settings.

## Editor controls

- Monospace multi-line editor with horizontal scrolling.
- **Reset to default:** replace contents with the current workflow default.
- **Insert variable:** categorized workflow-specific menu built from one
  shared variable registry; tooltips show descriptions/examples.
- **Preview:** render using **example values**, not the currently placed job.
- Live problem list: unknown names, syntax and unmatched conditional blocks.
  It updates shortly after typing stops.

Empty or whitespace-only text means **use the default**, not “output no
start/end code.” Use an explicit comment-only template if you intentionally
need no commands, and verify every action formerly performed by the default.
Reset is disabled when the text already matches its default.

Read the [literal default templates](reference/default-templates.md). Defaults
are generic, not machine/controller-qualified posts. They do not know your
probe, purge line, work offset, tool sensor, clamp layout or macro conventions.

## Substitution and formatting

```gcode
M104 S{nozzle_temp_first} T{tool}
; material {material}, layer height {layer_height:.2f}
G0 Z{safe_z}
```

The last line uses a CAM variable, while material/nozzle variables above are
FDM-specific. An unavailable workflow name is not silently substituted with
zero. See the [complete dictionary](reference/template-variables.md).

Whole-number floats normally print without `.0`, other floats with up to four
fractional digits, and booleans as 1/0. A format suffix such as `:.2f` requests
explicit precision. Use `{{` and `}}` to output literal braces. Comments remain
in output; tags inside comments are substituted too.

## Expressions

Allowed expressions include arithmetic, comparisons, boolean `and`/`or`/`not`,
a conditional expression (`a if condition else b`) and functions
`round`, `int`, `float`, `min`, `max`, `abs`, `str`:

```gcode
; example only: target plus offset = {nozzle_temp + 5}
; capped request = {min(nozzle_temp, max_nozzle_temp)}
```

This is a restricted expression evaluator, **not Python scripting**. Imports,
attribute access, comprehensions and arbitrary function calls are not allowed.
Expressions are intended for small numeric/text substitutions; do not use
large computations or assume every Python operator/format is supported.

**Safety:** variable temperatures supplied by the FDM emitter are capped to
machine limits, but arithmetic or literal commands can exceed those limits.
`{nozzle_temp + 5}` does not apply another automatic temperature cap. Template
validation is not G-code/controller safety validation.

## Conditional blocks

```gcode
{if chamber_temp > 0}M141 S{chamber_temp} ; set chamber
{endif}M140 S{bed_temp_first} ; set bed
{if chamber_temp > 0 and wait_for_chamber}M191 S{chamber_temp}
{endif}
```

Use `{if expression}`, optional `{elif expression}`/`{else}`, and `{endif}`.
Blocks can nest and span lines. Text in an inactive branch is omitted; the
remaining whitespace/newlines are otherwise preserved. The editor checks
names in **all** branches, even if example values would not execute one.

Keep complex controller logic in controller-qualified macros where possible.
The template language cannot prove the semantic correctness of a macro call.

## Dictionary and event values

The registry in `core/gcode_vars.py` drives insertion, examples and validation.
Actual values are built from the job at emission. Categories include machine,
model/date/time/version, temperatures, tool/nozzle, material, layer values,
part bounds and CAM stock. Example values in the reference are not live data.

Important distinctions:

- `nozzle_temp` / `bed_temp`: **normal** temperatures.
- `nozzle_temp_first` / `bed_temp_first`: first-layer temperatures, used at startup.
- `chamber_temp`: zero when chamber heating is unavailable/not requested.
- FDM `tool`: currently extruder 0, not a multi-extruder selection system.
- CAM `tool`, tool name/diameter/feed/RPM: first active tool at startup, last
  active tool at shutdown, not just the first allowed library entry. CAM
  `feed` is the tool's base cutting feed; per-move engagement factors and the
  machine max-feed cap can change emitted F values.
- `layer`: 1-based template value; internal preview/program indices are 0-based.
- At FDM start, current-layer values describe the first layer; at FDM end,
  they describe the last layer, including `current_layer_height`.
- CAM updates end `layer`/`layer_z` from the final depth pass. FDM-only layer
  height variables are not CAM milling-step values.
- `print_min_*` / `print_max_*`: placed model bounds, not all adhesion/support
  paths or the raw blank bounds.
- `stock_*`: CAM raw-stock description/dimensions, not remaining stock.

When migrating old custom start code, replace any old use of `nozzle_temp`
that meant the first layer with `nozzle_temp_first` (and similarly for bed).

## Rendering problems and output ownership

Runtime problems are collected in the log. Unknown/failed expression tags
can remain visibly unresolved in output rather than becoming plausible zeroes.
**Do not run code containing unresolved tags or template errors.** The live
check catches many structural mistakes but does not fully validate every
runtime arithmetic/formatting case or every forbidden expression construct.

Custom start/end templates replace the generic sequence for that box. The
FDM emitter still writes its separate extrusion-mode/E-reset handling and
optional acceleration, and changes normal temperatures after the first layer.
Chamber commands are template-owned; if a custom start omits chamber commands
while heat is requested, a warning is logged. Check shutdown commands too.
CAM tool changes between groups are emitted by the CAM emitter, not through
a configurable tool-change template yet.

The underlying editor/type is reusable for future boxes. That architecture
does not imply that layer-change/tool-change G-code boxes already exist.
See [extending templates](development.md#templates-and-new-settings).
