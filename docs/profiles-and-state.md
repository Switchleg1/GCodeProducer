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
| CAM tool | T number, cutter dimensions/type, fixed feeds/RPM, SFM calculation settings, per-machining-material SFM/chip-load/axial tables, maximum depth/pass | Tool JSON |
| CAM setup | Ordered tool groups/operations (including 3D Waterfall / 3D Contour), per-operation selection lists with machining or height-only purpose, linked depth references, allocated stock | Per-model Qt settings |
| CAM stock | Material description/density, margin, position and blank dimensions | Inside CAM setup, not the FDM material library |
| CAM holding tabs | Triangle/barycentric side anchors, width, height above stock bottom, XY edge direction, enabled | Inside model CAM setup; shared protection across all operations, not tool/process settings |
| CAM reference geometry | Circle/rectangle method, two construction points, Z and stable ID | Inside model CAM setup; fixed work coordinates, independent of tool/process and later placement changes |

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

Window layout, collapsed/expanded panes, recent models, selections, dirty
working pipelines, model placements/support, and CAM setups use **Qt
QSettings**, not those JSON folders. Global preferences (Settings dialog,
message switches) are `settings.json` in the library root; see
[global settings](settings.md).
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

**Save** commits the number/text currently being typed, even if focus has
not left that field. Switching profiles or library tabs commits pending input
to the corresponding in-memory profile first; Save then writes those edits
to disk. Cancel still discards library edits. This includes every machining
material's Pocket/Slot/Profile axial percentage in Tools.

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
- Flute count now participates in SFM/chip-load feed calculation. Cutter type,
  cutting length and V angle still do not provide full cutter-shape/holder
  collision geometry or automatic V-carving depth. Per-material cutting tables
  need calibration; see [cutting data](cam/cutting-data.md).
- CAM machine `cut_direction` defaults to Climb; Pocket/Profile/3D Waterfall
  inherit it unless **Unlock cutting direction** is ticked on the operation. Operation-driven paths now choose the hand from estimated
  remaining material, not a neutral first slot. Meander alternates one-sided
  passes; the convention assumes M3. See [direction and engagement](cam/engagement-and-feeds.md).
- CAM rates come from the tool: fixed feed/plunge feed/RPM, or (with
  calculation on) SFM and chip load of the stock's machining material; each
  can be unlocked per operation. Depth per pass comes from the material's
  Slot/Pocket/Profile axial percentage or the operation's depth unlock, and is
  always capped at tool `max_doc`. Tree operation stepover currently starts at
  40%, independently of the tool profile's stored stepover field.
- CAM `safe_z` and XY rapid feed are used. Lead-in start height and short
  retract height come from the [global settings](settings.md); the machine's
  stored `clearance_z` is **not** used by the current emitter, and `rapid_z`
  does not provide explicit Z rapid feed control. The old
  reserved pipeline ramp flag was removed; actual lead-in/out settings belong
  to operations. See [material state/leads](cam/material-state-and-leads.md).
- A positive CAM machine `max_feed` caps cutting/link and plunge feed requests,
  including engagement-factor increases. Tool and machine RPM ceilings are
  enforced, and below-minimum requests fail rather than overspeeding an SFM
  target. Verify the configured ceilings and cutter/material suitability.
- The machine `stock_resolution` field is ignored; the material grid is a
  [global setting](settings.md) together with air-cut removal and colouring.
- Current types are HSM, Cut, High engagement and Slot. Machine thresholds
  default to 40/80/95%; High is above 80%. HSM/Cut inherit tool factors,
  High/Slot inherit machine factors. Operation overrides accept 1–300%; 0
  inherits. Prior depth-tagged removal now carries across operations; the
  height-field display/checks remain approximate, not a full solid simulator.
  3D Contour passes update the height field but not the planar removal history.
- CAM output is currently millimetres (`G21` in the default template). The
  stored machine `units` field is not an automatic inch postprocessor.
- CAM origin choices affect placement only as implemented: centre origin
  centres XY around zero; the named front-left alternatives share the same
  XY rectangle. Top-at-Z0 is the CAM model-placement convention, not automatic
  programming of a controller work offset or tool-length compensation.
- Stock density is for volume/mass reporting. Its separate machining category
  selects the tool's SFM/chip-load/axial table, independently of FDM filament.
  Material grade/machinability still need operator-qualified data.

The [UI-options audit](cleanup-and-ui-audit.md#ui-audit--findings-only-controls-retained)
collects inactive/descriptive fields and intentional overlaps. Those controls
were not removed by the structural cleanup. Material cutting tables now remain
in fixed wood → plastic → non-iron metal → steel order; the active table is
marked without being moved.

Generated library/process/settings forms share backend parameter coercion and
defaults. Missing/null fields use declared defaults; valid saved strings are
converted before display rather than showing a different value from the one
used for generation. See [default loading](cleanup-and-ui-audit.md#material-order-and-default-loading).

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
