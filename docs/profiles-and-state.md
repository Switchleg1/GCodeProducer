[Documentation index](README.md)

# Profiles, ownership and persistent state

## Which object owns a setting?

| Owner | Settings | Reused / saved where |
|---|---|---|
| FDM machine | Build volume, limits, extrusion mode, chamber capability, start/end templates, allowed consumables | Machine JSON |
| FDM material | Filament diameter/density, requested temperatures, flow, cooling and retraction amounts | Material JSON |
| Nozzle | Diameter, default line width, volumetric limit, descriptive layer limits | Nozzle JSON |
| FDM process | Layer heights, adhesion, wall/shell/infill style, support printing style, requested speeds/travel | Process preset JSON; dirty working pipeline in Qt settings |
| Model support | Mode, angle, edge extension, hole filling, manual blocks | Per-model Qt settings, independent of presets |
| Placement | Translation, rotation, scale, Z anchor | Per-model Qt settings, separately for FDM and CAM |
| CAM machine | Work area, safe Z, rapid/feed/spindle fields, default cutting direction, allowed tools, templates | Machine JSON |
| CAM tool | T number, cutter dimensions/type, feeds/RPM, maximum depth/pass | Tool JSON |
| CAM setup | Ordered tool groups/operations, cutting selections, depth references, allocated stock | Per-model Qt settings |
| CAM stock | Material description/density, margin, position and blank dimensions | Inside CAM setup, not the FDM material library |

Selecting a FDM process must **never** move the model or change its support
mode, support configuration or blocks. A process can still change how those
supports print: line width, density, XY separation, gaps and interfaces.
CAM setup is not an FDM-style pipeline preset and its UI does not use those
Save/Revert controls.

## Data locations

Default reusable library root: `~/.gcodeproducer/` (on Windows, normally under
the current user's home folder):

```text
machines/*.json
materials/*.json
nozzles/*.json
tools/*.json
processes/*.json
plugins/*.py
```

`GCODEPRODUCER_LIBRARY` overrides the profile-library root. CLI `--library`
selects a root for commands that accept it. The plugin home search path remains
`~/.gcodeproducer/plugins`; relocating profiles is not a plugin sandbox.
Starter profiles are seeded into empty libraries. Existing nonempty libraries
are not overwritten to introduce new starter entries.

Window layout, recent models, selections, dirty working pipelines, model
placements/support, and CAM setups use **Qt QSettings**, not those JSON folders.
The organization is `GCodeProducer`; the application name defaults to
`GCodeProducer`. `GCODEPRODUCER_SETTINGS` selects another settings namespace,
which is useful for isolated experiments. The physical backing store depends
on the platform; Windows commonly uses the user registry.

Per-model keys are based on the normalized model path. Moving or renaming an
STL can therefore make it appear to have no saved model state. The state is
not written into the STL and a process export does not include it.

## Library editing

Use **Libraries** or a profile edit button. Each profile has a stable ID, name,
workflow and values. Machine profiles determine which consumables can be
selected: `*` means all, an explicit ID list is a subset, and `[]` means none.
A profile name alone is not enough to satisfy a saved CAM tool reference if
its ID has changed. Back up JSON before manually editing IDs or allowed lists.

The profile JSON shape is:

```json
{
  "kind": "nozzle",
  "id": "example-04",
  "name": "Example 0.4 mm",
  "workflow": "fdm",
  "values": {"diameter": 0.4, "line_width": 0.45, "max_flow": 12.0}
}
```

Defaults fill missing recognized fields. Obsolete profile fields are retained
in loaded data but ignored during resolution. Malformed library files may be
skipped while loading, so check syntax and workflow if an entry disappears.
See the [full profile tables](reference/profile-settings.md).

## FDM request versus limit

Requested speeds belong to the process; requested temperatures belong to the
material. Machine limits and the nozzle's volumetric limit cap them when
emitting FDM moves. Changes in effective speed/temperature are logged. A
machine profile is not a second place to tune ordinary print speeds.

Example: 60 mm/s infill requested with a 40 mm/s maximum print speed emits at
no more than 40 mm/s, and may be lower still if the bead would exceed the
hot-end/nozzle volumetric limit. Lowering material flow changes extrusion
volume and therefore the flow-limited speed calculation; it is not a substitute
for calibrating temperature or setting valid limits.

## Implemented versus descriptive settings

The schema reference lists stored fields, not a guarantee of output enforcement:

- FDM machine speed/flow/temperature limits are applied by the FDM emitter.
  Zero flow/acceleration limits generally disable that particular cap; check
  the individual field help. Do not assume zero means a physically safe value.
- Material `min_layer_time` is stored but the current emitter does **not**
  implement minimum-layer-time slowdown. Fan percentage and fan-start layer
  are used; a stored cooling target does not enforce a dwell or speed reduction.
- Nozzle minimum/maximum layer heights are stored; the layer stage does not
  automatically validate or clamp its height to those nozzle recommendations.
- CAM cutter type, flutes, cutting length and V angle are descriptive. They do
  not provide full cutter-shape/holder collision geometry, chip-load
  calculations, or automatic V-carving depth.
- CAM machine `cut_direction` defaults to Climb; Pocket/Profile inherit it
  unless overridden. Conventional reverses winding and Meander alternates
  paths; the convention assumes M3. See [toolpath directions](cam/toolpaths.md).
- CAM tool feed/plunge feed/RPM drive output; stepdown is capped at tool
  `max_doc`. Tree operation stepover currently starts at 40%, independently
  of the tool profile's stored stepover field.
- CAM `safe_z` and XY rapid feed are used. Separate `clearance_z`, `rapid_z`
  and the reserved ramp option do not currently implement extra clearance,
  explicit Z rapid feed control or ramp entry.
- CAM machine `max_feed` and spindle-range fields are **not general tool-request
  caps** in the current emitter. Verify each tool's feed and RPM yourself.
- CAM output is currently millimetres (`G21` in the default template). The
  stored machine `units` field is not an automatic inch postprocessor.
- CAM origin choices affect placement only as implemented: centre origin
  centres XY around zero; the named front-left alternatives share the same
  XY rectangle. Top-at-Z0 is the CAM model-placement convention, not automatic
  programming of a controller work offset or tool-length compensation.
- Stock density is used for volume/mass reporting only. It does not select
  cutting parameters or identify a material's machinability.

## Backups and migration

Back up both the JSON library root and platform Qt settings if you need the
complete working state. Copying just `processes/` transfers FDM recipes but
not model support, placement, tool-change trees or stock.

Older machine speed keys such as `print_speed`, `travel_speed`,
`perimeter_speed` or `acceleration` are no longer FDM requested speeds. Move
those requests into processes and review the current machine limits. Older
process-contained support placement is not a reliable model-state migration;
select the desired support mode in Model → Support. Reusable style values
remain process settings.

CAM uses a separate placement key. The first CAM placement defaults to top
Z0 instead of reusing a remembered FDM bottom height. Old CAM setups without
stock load with unallocated stock and require Auto or manual dimensions before
stock checking can run. If the source mesh fingerprint changes, saved CAM
setup references are invalidated rather than applied to unrelated geometry.
