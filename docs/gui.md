[Documentation index](README.md)

# Interface, placement and preview

## Workspace and docks

The toolbar provides import, workflow actions, Prepare/Preview switching,
Libraries and a **Camera views** menu for Iso, Top, Front, Right and Fit.
The **Model** dock contains the **Setup**, **Model**
(import and placement) panes and one workflow-specific options slot. That slot
displays **Support** for FDM, or **Material / stock** and **Holding tabs** for
CAM, followed in CAM by **Reference geometry**; moving the dock keeps them
together. The second left dock contains the FDM **Process** pane or the **CAM
setup** (**Tool changes & operations** and **Operation** panes), with the
**Slice** / **Generate paths** and **Save G-code** buttons. Right-hand docks
expose view options, G-code, statistics and the log. Every pane collapses from
its header; see [collapsible panes](#collapsible-panes).

The **Messages** dock at the bottom shows counts in its title
(*Messages — 0 errors, 1 warnings*). Status text, generation progress and
**Clear** share the existing bottom status-bar row: text on the left, progress
immediately left of Clear on the right. There is no second action row above it.

Move, float or close docks using their title bars. Restore hidden docks through
**View**. Layout and window geometry are remembered using Qt settings. A
missing dock is not evidence that its feature is disabled.

![Prepare workspace](pictures/prepare.jpg)

Screenshots may precede current labels; the workflow-specific guides describe
the current controls.

## Setup and import

The **Messages** dock along the bottom lists every warning and error with
time and level; hide it from the **View** menu. Pop-ups offer *Don't show
this again*, switchable back in Settings → Messages; see
[messages](settings.md#messages-and-the-messages-panel).

**File → Settings… (Ctrl+,)** holds [global preferences](settings.md) that
affect generated output for every model: air-cut removal, short retracts and
lead clearances, material grid resolution and cell limit, conflict colouring,
default operation settings and which message pop-ups appear.

Choose the workflow before configuring a machine. FDM offers allowed material
and nozzle profiles. CAM tools are added in the tool-change tree rather than
selected as a single global tool. Profile edit buttons open Libraries on the
relevant entry. Changing machines refreshes the permitted consumables; a saved
CAM tool that is no longer available causes generation to fail instead of
silently substituting another cutter.

In FDM or CAM, use **Model → Add…** (`Ctrl+O`), drop STL files on the window,
or use **File → Recent models** to add to the plate. Select an instance in
the list or click it in Prepare to edit its placement and supports. **Copy**
(`Ctrl+D` in Prepare) duplicates the selected instance in a free spot, with
independent placement and supports. **Delete** removes only that instance from
the plate, not its source file. Add and Copy use bounding boxes for initial
spacing; move or remove a model if the app cannot find room.

**Slice** prints the whole FDM plate layer by layer in one program, not one
object at a time. Keep models separate; intersecting meshes are not merged.
CAM generates one program against the combined placed geometry. **Auto material**
fits a single blank around every loaded CAM model, with the configured margin.
CAM selections can refer to any model; a model used by a selection, linked
height, or holding tab cannot be deleted until those references are removed.
Use normal navigation to select a model on the bed, or use the list while in
CAM picking mode. Both workflows share the same model list and selection.

![FDM model list with an original, a selected copy, and a second STL on the bed](pictures/fdm-model-plate.png)

Binary and ASCII STL are welded to shared vertices; STL units are not
self-describing, so verify displayed dimensions in millimetres.

## Work sessions

**File → Export work session…** saves a `.gcpsession` file. **File → Import
work session…** replaces the current workspace with that file. It restores
loaded model instances and their placement and support settings, the active CAM
setup, the workflow, the process name and working settings, and the window,
dock and camera layout. Import does not add or overwrite library presets.

Closing the app saves the same information as the default session in its
settings. A normal launch restores it; launching with a model path starts a
workspace for that model instead. Session files reference the source STLs, so
keep those accessible. Manual import reports missing files without replacing
the workspace; automatic startup skips missing models and logs them. Generated
G-code is not saved in the session: regenerate it to return to Preview.

## Position and orientation

| Control | Meaning and behaviour |
|---|---|
| X / Y | Centre of the transformed model's bounding box, not its minimum corner or a machine work offset |
| Center | Places the XY centre at the machine work-area centre, respecting centre-origin settings |
| Z, FDM | Bottom of model above bed; nonnegative. Zero rests on the bed |
| Z, CAM | Top of model; normally zero. Negative values recess the whole part below the surface |
| Drop to bed / Top to Z0 | Restores the workflow's Z anchor to zero without resetting rotation or XY |
| Rotate X/Y/Z | Euler angles; buttons rotate ±90° about world axes |
| Scale | Uniform percentage; displayed size updates from the transformed mesh |
| Lay flat | Uses the largest grouped planar area to choose a downward orientation |
| Place on face (Ctrl+L) | Click a face: point it down onto the FDM bed, or up toward the CAM cutting surface. Rotation and Z placement are applied together; Esc cancels |
| Reset | Restores rotation, scale and Z, then centres XY using the active workflow convention |

Placement is model state, not process state. Switching workflows keeps XY,
rotation, scale and relative Z spacing. The entire group shifts in Z so its
lowest point rests on the FDM bed or its highest point is at CAM Z0. CAM stock
and drawn references stay in work coordinates. Older sessions with separate
model lists reopen the list for their saved workflow.
Changing presets must not move a model or alter its
support blocks. Moving FDM models moves their support blocks; rotation or
scaling invalidates those blocks and removes them. CAM references use mesh
indices and are re-evaluated after placement; an operation may become invalid
if its selected cutting geometry is no longer horizontal.

**Ctrl+left drag** on a model in ordinary Prepare mode changes its XY. A plain
left drag always orbits, wherever it starts; a plain click on a model still
selects it. Selecting a CAM operation automatically activates face picking. Switch to
Select edges to pick rims; a reopened setup selects its first operation so
picking is immediately usable. During CAM selection, dragging over the model
orbits instead of moving it; leave selection mode before Ctrl+dragging the part. Model placements outside
the work volume are orange and show a warning. The CAM volume extends below
Z0; the FDM volume extends above it. Stock and extra adhesion paths are not
made safe merely because the model itself fits.

### Placing a chosen face flat

Press **Ctrl+L** (or **Edit → Place on face** / the Model button), then click a
visible model face in Prepare. This is available in both workflows. FDM aligns
the clicked triangle's normal downward and puts the lowest model point on Z0.
CAM aligns it upward and puts the highest point at the allocated stock's top
(or Z0 without stock). XY centre and scale are retained. Picking runs in the
background compute process; a miss leaves the tool active, and Esc cancels.

STL faces are triangles: on a curved surface this aligns the clicked facet,
not an analytic CAD surface. A recessed/concave face may not touch the plane;
the whole part is anchored by its extreme so it does not cross the bed/cutting
surface. Check the result, workholding and CAM geometry/depths after rotating.
Stock and drawn reference outlines do not move with the part. Undo restores
the prior placement and any support blocks invalidated by the rotation;
Redo reapplies the face placement. Queued dock redraws do not create edits or
consume this redo history.

## Undo and redo

Use **Edit → Undo / Redo**, **Ctrl+Z**, **Ctrl+Shift+Z** or **Ctrl+Y**. The shared
history covers FDM and CAM model edits, process/operation settings, picking,
stock/tabs/references, and control values and selections—including spinners,
dropdowns, lists, checkboxes, text, collapsible panes and view controls. A drag
is one edit. A new edit after Undo discards the redo branch.

Libraries, Settings and the pipeline dialog have local undo/redo shortcuts;
**Cancel** still discards the dialog as usual. Accepted changes join the main
history, including saved profile/process changes. History is bounded to 100
transactions and lasts for this application session, not across restarts.

Undoing a machining/printing input marks generated output out of date;
regenerate to export G-code that reflects the restored setup. View-only undo
does not make paths stale. Undo also ignores
late results computed from an undone setup. History restores editor state,
not exported files or a physical machine: exporting G-code, running/cancelling
computation, and quitting are not reversible execution commands. Automatic
playback ticks are not individual history entries.

## Prepare and Preview

Both views use the **same camera**, machine rectangle, grid, origin and
work-volume dimensions. Slicing does not automatically re-fit the camera.
Switching views therefore should not change scale or framing. Use **Fit**
when you deliberately want a different framing.

Prepare displays geometry, support block overlays and CAM selections. FDM
can tint overhangs red. The FDM plate becomes translucent from below. CAM has
no opaque surface hiding the negative-Z part; the stock outline is amber.
Preview displays generated moves and, in CAM, the selected calculated material
output. The outline remains the original blank; translucent surfaces show the
height-field result after the chosen operation. **Show → Material** defaults
on and **Calculated operation output** selects Initial material or each
completed process. These are approximate 2.5D results, not physical simulation.
See [material state and leads](cam/material-state-and-leads.md).

![Toolpath preview](pictures/preview.jpg)

Edits to placement, machine, process, consumables or CAM stock/setup make the
preview **out of date**. **Save G-code** can still write the previous program
unchanged after a warning. Regenerate to apply or check the new setup. CAM
warnings on the generated program have a separate export prompt. Both prompts
can be turned off or restored in **Settings → Messages**.

## Material boundary selection

CAM operations default to **Pick from → Part + material + references** alongside
Select faces/edges. Select a part rim and a material edge in one Pocket to
clear the space between them, without switching selection types. One horizontal
material edge identifies the blank rim; selected part loops are retained inner
boundaries. *Part only* / *Material only* remain optional pick filters. Side
faces and vertical edges can supply linked height references; references
follow blank edits. See
[material boundaries](cam/selection-and-depths.md#selecting-material-boundaries)
for stock-envelope Pocket behaviour and 2.5D limits.

## Draw reference geometry

In the **Reference geometry** pane at the bottom of the Model dock (CAM), draw
circles by center/rim or diameter endpoints and rectangles by center/corner or
opposite corners on a chosen Z plane, then move or resize the selected shape by
typing its center/size or with the **Move** / **Resize** click tools. **Draw**,
Move and Resize are highlighted while active; click again or press Esc to stop.
While one of them is active, moving the mouse shows what a click would make
(0.2.77): the outline in the view, and above the tool hint its position and
size. Before the first click of a new shape that is the cursor position on the
drawing plane; after it, the centre and the diameter (circle) or width and
height (rectangle). The pane's own status line is unchanged.
Saved outlines are cyan. The pane-selected shape has a bright lime outline
and translucent fill; operation-picked shapes have magenta outlines and fill.
Material selection remains green. They are selectable boundaries or per-selection height-only
references. Use **Reference geometry only** to pick through overlaps. Outlines
stay fixed in CAM work coordinates when the model is moved. See
[reference geometry](cam/reference-geometry.md) for construction, persistence,
operation rules and limitations.

## CAM form labels

Short CAM labels such as **Roughing clearance (mm)** and **Material boundary
(mm)** stay on one line when space is available. In a genuinely narrow dock,
the form moves the field below the label instead of splitting these labels
inside an unnecessarily narrow column.

![Single-line CAM clearance and material labels](pictures/cam-operation-label-widths.png)

## Values shown in orange

A number shown in **orange** is valid but will not be used as entered. Its
tooltip starts with the reason, above the field's usual help. The value
itself is never changed: fix the limit (or the value) to clear it.

| Where | Field | Why |
|---|---|---|
| CAM operation | Depth per pass | Above the tool's **Max depth/pass**: passes use the tool's value |
| CAM operation | Spindle RPM | Above the machine's **Spindle max** or the tool's **Max spindle RPM** |
| CAM operation | Cut, lead-in and plunge base feeds; engagement feed % | Above the machine's **Max feed** (for a %, the cut feed times it) |
| CAM operation | Lead-in / plunge feed % | Not used: that base feed is unlocked |
| CAM operation | Stepover | Wall-parallel contours over 50 %: used as 50 % |
| Process (FDM output) | Speeds, acceleration | Above the machine's **Max print / travel speed** or **Max acceleration** |
| Library: material | Nozzle, bed, chamber temperatures | Above the machine's limits; a chamber temperature on a machine without a heated chamber is ignored |
| Library: tool | Fixed spindle RPM, cut and lead-in feeds | Above the active machine's **Spindle max** / **Max feed** or the tool's own **Max spindle RPM** |

Library values are judged against the machine selected in the main window.
Not shown here: caps that depend on the geometry or the path, such as the
volumetric flow cap on each FDM path (see the slicing log), the overcut kept
inside the material boundary, or the material and surface grids coarsened by
the cell limit (job warnings).

## Collapsible panes

Every panel is built from the same collapsible pane as the FDM process sections
(Layers, Skirt / brim, Walls, …): Setup, Model, Support, Material / stock,
Holding tabs, Reference geometry, Process, CAM tool changes and Operation, the
View dock's Show / Features / Camera, Settings → Messages and the groups of
every generated form (library profiles, global settings). Click a header to
collapse or expand it; the arrow shows the state. Panes nested inside another
pane (setting groups within a process section, Engagement feeds within an
Operation) use a quieter header. Collapsed/expanded state of the named panes
is remembered with the window layout.

![Collapsible panes in the Model, Process and View docks](pictures/ui-collapsible-panes-fdm.png)

Lists with actions are laid out the same way everywhere: the list first, its
buttons directly underneath, then the fields of the selected entry (support
blocks, holding tabs, reference geometry).

## CAM holding tabs

In the **Holding tabs** pane (Model dock, CAM), choose **Place tabs** and
click side walls to retain rectangular rails to the stock's X/Y edges.
**Remove tabs** repeatedly removes clicked rails; selecting a row edits its
width, height or direction. Esc returns to navigation. No operation needs to
be selected. Purple volumes appear in both views with Show → Material. Tabs
are saved with the model and split paths according to Area order, preserving
leads; see [holding tabs](cam/holding-tabs.md) for setup and safety limits.

## Inspecting generated paths

The playback bar under Preview is shared by FDM and CAM. The tool marker
moves along the path at the selected preview speed; the drawing and G-code
cursor advance as each line completes. Playback skips dwell and other
non-motion delays and does not use the programmed feed rates.

![Preview playback bar](pictures/ui-preview-playback.png)

| Control | Action |
|---|---|
| ⏮ / ⏭ | Jump to the start; End shows the whole program |
| ⏪ / ⏩ | Previous / next layer (FDM layer or CAM depth pass); the cursor goes to the end of that layer |
| ◀ / ▶\| | Previous / next move (comments and blank lines are skipped) |
| ▶ / ⏸ | Play / pause (Space). Playing at the end restarts from the start |
| Speed | About 1 to 50,000 mm/s along the toolpath, logarithmic |
| Line slider and *line* box | Position in the whole program |
| In layer | Position within the top visible layer |
| Layers *from* / *to* | Lowest and highest visible layer |
| Single layer | Show only the top visible layer |
| Follow | While scrubbing or playing, the top visible layer follows the cursor |

- The vertical slider beside the view is the same *to* layer (PgUp / PgDn).
- Double-clicking a G-code line moves the cursor there; the view, the G-code
  list and the status line always show the cursor's line.
- Playback stops when leaving Preview or regenerating. Layer and playback
  controls are disabled in Prepare but stay outside the viewport so their
  labels do not resize the 3D area when changing views.
- Colour by feature, movement kind, speed or layer. Feature checkboxes hide or
  show categories; hover a CAM entry such as *HSM*, *Conflict* or *Collision*
  for its meaning. Hidden paths still exist in exported G-code.
- CAM moves flagged by the planner or the stock checks are recoloured
  **Conflict** (yellow) or **Collision** (magenta) when the global setting
  allows it; see [global settings](settings.md#conflict-and-collision-colouring).
- Double-click a move to select its G-code line; double-click a line to locate
  the corresponding move in 3D.
- Statistics summarize lines, layers, motion bounds and time. FDM also reports
  filament length and an estimated mass using material density.

FDM time comes from a firmware-like trapezoidal planner: every move
accelerates and brakes at the machine's firmware print/travel acceleration
(or the `M204` values in the file), corners are slowed by the junction
deviation, and retract/unretract moves count. Set **Machine → Motion**
(firmware print acceleration, travel acceleration, junction deviation) to your
firmware's values; a saved file carries them in a `;MOTION` header so the
estimate matches after reopening. It is still an estimate: firmware buffers,
input shaping and extruder limits are not modelled. CAM time remains
feed-based, without acceleration. Toolpaths are not proof of extrusion quality, dimensional accuracy,
cutter clearance or successful workholding.

## Keyboard and mouse reference

| Input | Action |
|---|---|
| Ctrl+Z | Undo, including edits in text/spin fields |
| Ctrl+Shift+Z / Ctrl+Y | Redo |
| Ctrl+L | Activate Place on face; then click the face |
| Ctrl+, | Settings |
| Ctrl+Q | Quit |
| Ctrl+O | Add models |
| Ctrl+D | Copy selected model in Prepare |
| Ctrl+R | Slice / generate paths |
| Ctrl+S | Save generated G-code (subject to CAM checks) |
| Ctrl+1 / Ctrl+2 | Prepare / Preview |
| Left drag | Orbit (anywhere, including over a model) |
| Ctrl+left drag on a model | Move the model in XY (ordinary Prepare mode) |
| Right / middle drag | Pan |
| Shift+left drag | Pan, including CAM picking mode |
| Wheel | Zoom |
| F | Fit view |
| 1 / 2 / 3 / 4 in viewer | Isometric / top / front / right |
| PgUp / PgDn | Next / previous layer index |
| Space (Preview) | Play / pause playback |
| Left / Right (Preview) | Previous / next move |
| Home / End | First / last layer index |
| Esc | Exit the active picking, placement or reference Draw / Move / Resize tool |
| Delete / Backspace | Delete selected manual support block in its editing context |

The same shortcut list is available offline under **Help → Controls**, with
context notes for viewport-only and Preview-only keys.

![Help Controls with the full shortcut list](pictures/ui-controls-and-shortcuts.png)

## Generation, progress and cancellation

The action reads **Slice** for FDM and **Generate paths** for CAM. It shares
its height with **Save G-code…** and takes about 70 % of the row. While a job
is running, it becomes **Cancel**. Heavy geometry work and toolpath preparation
run in a persistent spawned compute process, which spreads the per-layer work
of FDM slicing over a pool of worker processes (one less than the CPU cores,
at most 16; environment variable `GCODEPRODUCER_WORKERS` overrides, 0 or 1 =
no pool). The first slice after start-up also starts that pool. The GUI receives progress/log
signals and chunked program results. Cancelling stops the compute process;
a later task starts it again. Cancellation does not undo settings edits.

Read the Messages dock and the Log after each generation. Caps, ignored settings, template problems,
unsupported geometry and stock warnings are explained there. For failure
recovery see [troubleshooting](troubleshooting.md).
