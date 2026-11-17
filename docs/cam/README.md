[Documentation index](../README.md)

# CAM workflow

CAM is organized by **ordered tool changes**, not by one global FDM-style
process preset. A setup belongs to a model and contains tool groups, operations,
geometry/depth references, drawn reference outlines and allocated stock.

```text
T1 — large endmill
  Pocket: rough recess
  Profile: outside boundary
T2 — small endmill
  Profile: finish boundary
  Engrave: marking
T3 — drill
  Drill: selected hole rims
```

Pocket clearing defaults to **wall-parallel contours**. Offset fronts adapt to
both walls and islands, including square/circle transitions. The CAM machine
stores a default cutting direction—**Climb**, Conventional or Meander—with
Climb as the default. Pocket/Profile operations may override it.

The tree is the execution order. A repeated tool in a later group remains a
separate tool-change group; groups are not automatically sorted by T number.

## Coordinates and stock

CAM auto-placement puts the model **top at Z0**, extending the body downward.
For a 20 mm-tall part, default model bounds in Z are -20 to 0. The Z position
field edits the top, not the bottom; **Top to Z0** restores the surface anchor.
Changing scale/rotation preserves that anchor during placement. FDM remembers
its own independent bottom-referenced placement.

X/Y position is the transformed model's bounding-box centre. Machine origin
settings affect XY positioning/work-area framing, not actual controller work
offsets. The model surface convention is not a command to set G54, G92 or a
tool-length offset. Establish those correctly on the machine yourself.

The **Material / stock** panel takes the place of FDM Support in the same
movable UI slot. Allocate a blank with Auto or enter its dimensions manually
before generation. The amber outline is the original stock in both views.
Read [stock allocation and safety](stock-and-safety.md) before relying on it.

## Creating a setup

1. Choose a CAM machine and import the part. Verify negative-Z placement,
   work area and orientation. Pick a face for orientation separately from
   selecting machining geometry.
2. Configure stock and set **safe Z strictly above** the stock surface, model
   maximum Z and every operation start Z.
3. Choose an allowed tool and **Add tool change**. A group references the tool
   library ID. Check its T number, diameter, feed, plunge feed, RPM and max DOC.
4. Select the group, choose the operation kind (Pocket, Profile, Drill, Engrave,
   Slot, 3D Waterfall or 3D Contour), then **Add operation**.
5. Select machining faces/edges (part, material blank or
   [drawn reference geometry](reference-geometry.md)) and define start/end
   heights. Uncheck a row's **Use for machining** when it should supply depth
   but not cutting paths; **Remove** drops a row.
6. Set operation options. Rename operations so logs and output are identifiable.
7. Use the up/down arrows to move an operation within its group or a whole
   group in the setup. Delete removes the selected operation or entire group.
8. Generate paths and inspect every operation/depth pass. Handle all warnings
   and independently verify controller behaviour before exporting or cutting.

Operations can be disabled individually. Disabled operations generate no paths;
they do not imply previous operations have removed stock. Empty setups or
setups without enabled operations fail generation.

## Output order

`cam_profile` generates the ordered paths for a setup, and `cam_emit` emits
motion. The first entry after start-up or a tool change comes from safe Z.
Later entries stay at depth across cleared material when that is verified,
or use a short retract above the current material, then a rapid to just above
the material and a ≤10° lead-in ramp (or a plunge at lead/plunge feed when
lead-in is off); see [material state and leads](material-state-and-leads.md).
Wall-parallel pockets can then follow nearby contours
using clearance-checked same-depth feed links. Blocked/disconnected links and
other path strategies retain retract/position/plunge handling. Cuts and links
use tool cutting feed adjusted by estimated engagement (including heavier
entry links), capped by a positive machine max feed. The first full-width
slot is neutral; later pass direction follows remaining material. Enabled
contour-constrained leads ramp into the path and exit through calculated
cleared material; no controller helix is implied. 3D Contour paths are written
as XYZ feed moves; see [3-axis surface operations](3d-operations.md).

Between tool groups, output retracts to safe Z, stops the spindle (`M5`),
issues `T… M6`, and restarts the spindle (`M3 S…`). A real controller may need
additional tool-change macros, manual handling or offsets. The machine's
start/end templates see the first and last active tool respectively. Generic
startup/shutdown templates must be qualified for the machine.

Each depth pass receives preview layer metadata, with operation labels and
cut/plunge/rapid features. These layer indices describe execution order, not
necessarily monotonically decreasing Z across the entire setup: a later
operation may restart near the top.

## Persistence and invalidation

Setup state is automatically saved per model path in Qt settings. FDM process
Save/Revert/Import/Export controls are not the CAM setup storage mechanism.
Reopening the same model restores its stock and tree. Tool references remain
IDs, not copied tool definitions; editing a tool library changes the tool
values used on subsequent generation.

Changing the source mesh fingerprint resets the saved CAM setup, including
tool groups, selections, stock, holding tabs and reference geometry, instead of applying references to unrelated
triangles. This is logged when reopening the changed source. Moving the file to another path may
start with a fresh setup. See [persistent state](../profiles-and-state.md).
Stock does not silently move or resize when the part is moved—use Auto again
if the current blank is no longer suitable.

## Scope and next topics

Implemented machining is 2.5D from STL-derived topology, plus three 3-axis
operations limited by the model surface:

- [3D Waterfall clearing and depth-limited 3D Contour](3d-operations.md)

- [Geometry selection and linked depths](selection-and-depths.md)
- [Draw circles and rectangles as reference geometry](reference-geometry.md)
- [SFM, chip load, machining materials and axial defaults](cutting-data.md)
- [Current material, process outputs and lead-in/out](material-state-and-leads.md)
- [Holding tabs: click side walls to retain rails to stock XY edges](holding-tabs.md)
- [Engagement-aware direction and feed factors](engagement-and-feeds.md)
- [Wall-following strategies and cutting direction](toolpaths.md)
- [Operation-by-operation settings and restrictions](operations.md)
- [Stock, warnings and verification checklist](stock-and-safety.md)
- [Pipeline architecture and the proposed motion planner](architecture.md)

Model-owned rectangular holding tabs are implemented, including radius-aware
path splits and protected-tab travel checks. 3D work is limited to flat-cutter
full-area level roughing and depth-limited parallel surface-following passes: no
rest machining, ball/bull-nose compensation, scallop/spiral/adaptive strategies,
CAD/STEP topology, cutter-holder or fixture simulation is provided. Segmented contour lead ramps and progressive 2.5D
material outputs/checks are implemented, not a general solid-removal solver. Tool type labels do not implement V-carving
or ballnose surface compensation. The legacy CLI silhouette profile is a
separate, narrower workflow; see [CLI scope](../cli.md#legacy-cam-command).
