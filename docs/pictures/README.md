[Documentation index](../README.md)

# Documentation pictures

Store documentation screenshots, annotated examples and other feature images
in **`docs/pictures/`**. Link to them from the feature guide using relative
paths; do not scatter new images across the documentation root.

## Image inventory

| File | Purpose / provenance | Used by |
|---|---|---|
| [ui-controls-and-shortcuts.png](ui-controls-and-shortcuts.png) | Actual 0.1.1 Help → Controls dialog, including undo/redo and Ctrl+L; captured with isolated temporary library/settings | [GUI shortcuts](../gui.md#keyboard-and-mouse-reference) |
| [prepare.jpg](prepare.jpg) | Earlier Prepare workspace screenshot; some labels may be historical | [GUI guide](../gui.md) |
| [preview.jpg](preview.jpg) | Earlier Preview workspace screenshot | [GUI guide](../gui.md) |
| [support_panel.jpg](support_panel.jpg) | Earlier FDM support panel screenshot; ownership descriptions in the guide take precedence | [Support](../fdm/support.md) |
| [cam-pocket-bounds-example.png](cam-pocket-bounds-example.png) | User-supplied example with red annotations marking intended outer rim and boss boundary; annotations are not app selection colours | [Pocket operations](../cam/operations.md#bounds-and-automatic-removal-height) |
| [cam-pocket-floor-selected.png](cam-pocket-floor-selected.png) | Current application capture: selected annular floor yellow, raised boss blue, stock amber | [Pocket operations](../cam/operations.md#bounds-and-automatic-removal-height) |
| [cam-pocket-generated-pass.png](cam-pocket-generated-pass.png) | Contour-geometry capture before stay-down linking; green concentric cuts and amber original stock, entry/rapid motion hidden | [Toolpath strategies](../cam/toolpaths.md) |
| [cam-pocket-stay-down.png](cam-pocket-stay-down.png) | Current application capture: neighbouring closed loops joined by short green cutting-feed links, one depth pass with entry/rapids hidden | [Stay-down linking](../cam/toolpaths.md#stay-down-ordering-and-link-checks) |
| [cam-pocket-square-circle.png](cam-pocket-square-circle.png) | Actual generated paths for a constructed square pocket with circular island; straight and curved fronts transition into corner contours; linking motion hidden | [Toolpath strategies](../cam/toolpaths.md) |
| [cam-pocket-engagement-features.png](cam-pocket-engagement-features.png) | Actual feature-coloured annular pass: initial neutral slot orange, ordinary clearing green, heavier entry links separately classified; entry/rapids hidden | [Engagement and feeds](../cam/engagement-and-feeds.md#illustrated-annular-example) |
| [cam-pocket-engagement-estimate.png](cam-pocket-engagement-estimate.png) | Same generated pass coloured by estimated radial engagement; 3 mm tool, base feed 800 mm/min, Standard override 150%, Slotting 50% | [Engagement and feeds](../cam/engagement-and-feeds.md#illustrated-annular-example) |
| [cam-tool-calculation.png](cam-tool-calculation.png) | Actual Libraries → Tools pane *Cutting calculation*: calculation checkbox, RPM ceiling and lead-feed percentage; isolated illustrative 4 mm profile | [Cutting data](../cam/cutting-data.md#automatic-calculation) |
| [cam-tool-material-table.png](cam-tool-material-table.png) | Actual per-tool *Cut data: Non-iron metal* pane (marked active CAM material); illustrative values, not a calibrated recipe | [Cutting data](../cam/cutting-data.md#per-tool-per-material-table) |
| [settings-dialog.png](settings-dialog.png) | Actual File → Settings dialog with default values; groups are collapsible panes | [Global settings](../settings.md) |
| [cam-auto-depth-material-source.png](cam-auto-depth-material-source.png) | Actual Operation pane: summary naming Non-iron metal Pocket 25% D = 1 mm/pass for the illustrative 4 mm tool, unlock rows below | [Material-specific depth](../cam/cutting-data.md#which-saved-table-is-used) |
| [cam-material-table-order.png](cam-material-table-order.png) | Actual tool editor showing the Cutting calculation pane followed by *Cut data: Soft wood*, the first of the fixed material order | [Material-specific depth](../cam/cutting-data.md#which-saved-table-is-used) |
| [cam-active-material-cutting-table.png](cam-active-material-cutting-table.png) | Actual tool editor: Hard plastic, then *Non-iron metal — active CAM material*, then Steel; the active table is marked, not moved | [Material-specific depth](../cam/cutting-data.md#which-saved-table-is-used) |
| [cam-depth-of-cut-override.png](cam-depth-of-cut-override.png) | Actual Operation pane rows: depth of cut unlocked at 0.4 mm/pass and cutting direction unlocked (Climb) while RPM, feed and lead feed stay calculated; illustrative settings | [Depth override](../cam/cutting-data.md#automatic-versus-explicit-stepdown) |
| [cam-operation-label-widths.png](cam-operation-label-widths.png) | Actual 0.1.5 Operation pane using the application's dark Fusion theme: Roughing clearance and Material boundary labels stay on one line beside their fields; isolated temporary library/settings | [CAM form labels](../gui.md#cam-form-labels) |
| [cam-cutting-strategy-clearing.png](cam-cutting-strategy-clearing.png) | Actual 0.1.4 Pocket Cutting strategy popup: Wall-parallel contours, Raster lines X/Y; same choices apply to Waterfall. Isolated temporary library/settings | [Cutting strategy](../cam/operations.md#cutting-strategy) |
| [cam-cutting-strategy-contour.png](cam-cutting-strategy-contour.png) | Actual 0.1.4 Contour popup: Meander, Raster lines X/Y; Profile side row absent | [Cutting strategy](../cam/operations.md#cutting-strategy) |
| [cam-profile-side-choices.png](cam-profile-side-choices.png) | Actual 0.1.4 Profile popup: Outside/Inside only, Cutting strategy row absent | [Profile](../cam/operations.md#profile) |
| [cam-waterfall-clearing.png](cam-waterfall-clearing.png) | 0.1.3 Preview (earlier controls/status layout): full-area Waterfall clearing, depth 4 of 8 at Z−4, 3 mm tool, 1 mm depth/pass; isolated temporary library/settings | [3D operations](../cam/3d-operations.md) |
| [cam-contour-leads-engagement.png](cam-contour-leads-engagement.png) | Actual 0.1.6 Preview, dark Fusion theme: Contour with contacting lead-in/cleared lead-out and Slot/High/Cut/HSM/Air metadata. Wedge, 3 mm tool, 1 mm/pass, 30% stepover; illustrative feeds; isolated temporary library/settings | [Contour](../cam/3d-operations.md#3d-contour) |
| [cam-contour-engagement-settings.png](cam-contour-engagement-settings.png) | Actual 0.1.6 Operation pane: selected leads and enabled HSM/Cut/High/Slot feed controls for Contour; same illustrative isolated setup | [Contour](../cam/3d-operations.md#3d-contour) |
| [cam-contour-depth-passes.png](cam-contour-depth-passes.png) | 0.1.3 Preview (before XYZ leads/engagement and the current controls/status layout): final surface pass after depth-limited Contour clearing, 10 depths rather than one direct pass; same isolated wedge example | [3D operations](../cam/3d-operations.md) |
| [ui-reference-selection-fill.png](ui-reference-selection-fill.png) | 0.1.3 Prepare (earlier status layout): lime-filled editor-selected circle and magenta-filled operation-selected rectangle above model/stock; isolated wedge example | [Reference geometry](../cam/reference-geometry.md) |
| [cam-3d-rough-and-finish.png](cam-3d-rough-and-finish.png) | Historical pre-0.1.3 Preview: Pocket terraces, wall-only Waterfall and single-pass Contour; not current instructions | [3D operations](../cam/3d-operations.md) |
| [cam-3d-pocket-terraces.png](cam-3d-pocket-terraces.png) | Historical surface-limited Pocket; this behaviour is now Waterfall, and the Pocket toggle has been removed | [Pocket migration](../cam/3d-operations.md#pocket-migration) |
| [cam-3d-waterfall.png](cam-3d-waterfall.png) | Historical wall-only Waterfall at 0.5 mm levels; superseded by full-area clearing | [3D operations](../cam/3d-operations.md) |
| [cam-3d-contour.png](cam-3d-contour.png) | Historical single-pass Contour with uncleared-depth warnings; current Contour uses depth bands | [3D operations](../cam/3d-operations.md) |
| [ui-preview-playback.png](ui-preview-playback.png) | Actual Preview of `examples/wedge-pocket.stl` (FDM) part-way through layer 41 with the shared playback bar; also shows the compact Messages dock and 70/30 action buttons | [Inspecting generated paths](../gui.md#inspecting-generated-paths) |
| [cam-operation-selection-list.png](cam-operation-selection-list.png) | Actual CAM Operation pane: full-width selection list with pick mode, Remove and Clear geometry underneath | [Selecting cutting geometry](../cam/selection-and-depths.md#selecting-cutting-geometry) |
| [ui-reference-geometry-pane.png](ui-reference-geometry-pane.png) | Earlier capture: Reference geometry pane with outline-only yellow focus; current selection uses lime/magenta fill | [Reference geometry](../cam/reference-geometry.md#moving-and-resizing) |
| [ui-collapsible-panes-fdm.png](ui-collapsible-panes-fdm.png) | Actual capture: shared collapsible panes in the Model, Process (quieter nested setting groups) and View docks | [Collapsible panes](../gui.md#collapsible-panes) |
| [cam-reference-drawing.png](cam-reference-drawing.png) | Earlier layout (pane inside CAM setup, *Draw reference* / *Stop / cancel*). Actual Prepare capture with all four construction methods represented, cyan saved outlines and a magenta selected circle; isolated example cube | [Reference geometry](../cam/reference-geometry.md) |
| [cam-reference-picking.png](cam-reference-picking.png) | Actual reference-only edge selection as a machining boundary with linked constant-Z depth; no qualified cutting recipe implied | [Selecting outlines](../cam/reference-geometry.md#selecting-an-outline) |
| [cam-per-selection-purpose.png](cam-per-selection-purpose.png) | Actual Prepare capture: selection list with a checked part edge and an unchecked (height-only) material edge drawn green; isolated cube example | [Selection purpose](../cam/selection-and-depths.md#cutting-geometry-versus-height-only-geometry) |
| [cam-cutting-direction-unlock.png](cam-cutting-direction-unlock.png) | Actual window: Operation pane scrolled to the unlock rows, cutting direction unlocked directly below lead/plunge feed; Messages dock with sample entries | [Operations](../cam/operations.md) |
| [cam-mixed-boundary-selection.png](cam-mixed-boundary-selection.png) | Earlier actual mixed selection: circular part flange rim and material top edge; current per-selection controls/green highlights differ | [Mixed boundaries](../cam/selection-and-depths.md#clear-between-the-part-and-material-edges) |
| [cam-mixed-boundary-pocket.png](cam-mixed-boundary-pocket.png) | Actual Pocket clearing outside the selected flange rim up to the material envelope; yellow Conflict segments require review | [Mixed boundaries](../cam/selection-and-depths.md#clear-between-the-part-and-material-edges) |
| [cam-material-boundary-selected.png](cam-material-boundary-selected.png) | Earlier actual material top-face selection; current material fill/outline is green, not yellow | [Material boundary selection](../cam/selection-and-depths.md#selecting-material-boundaries) |
| [cam-material-boundary-pocket.png](cam-material-boundary-pocket.png) | Actual last Pocket pass from the material envelope to the flange floor, with the boss protected; yellow Conflict segments need review | [Material-boundary Pocket](../cam/selection-and-depths.md#material-boundary-pocket) |
| [cam-holding-tabs-editor.png](cam-holding-tabs-editor.png) | Actual Model dock: Holding tabs pane (list, Place / Remove / Delete selected under it, selected tab fields) with two illustrative tabs | [Holding tabs](../cam/holding-tabs.md#place-and-edit-tabs) |
| [cam-holding-tabs-prepare.png](cam-holding-tabs-prepare.png) | Actual Prepare view: two 4 × 4 mm rails to opposite stock X edges | [Holding tabs](../cam/holding-tabs.md#place-and-edit-tabs) |
| [cam-holding-tabs-output.png](cam-holding-tabs-output.png) | Actual calculated result and last profile section: stock bottom Z-32, tab tops Z-28, leads preserved; illustrative long-reach tool | [Path splitting](../cam/holding-tabs.md#how-tabs-split-operations) |
| [settings-operation-defaults.png](settings-operation-defaults.png) | Actual Settings dialog scrolled to the Default operation settings and Messages panes, including the reference-geometry deletion switch | [Default operation settings](../settings.md#default-operation-settings) |
| [messages-panel.png](messages-panel.png) | Current 0.1.4 bottom Messages dock plus shared status row: status text on the left, illustrative 65% progress and Clear on the right, all at the same height; isolated temporary library/settings | [Messages](../settings.md#messages-and-the-messages-panel) |
| [cam-overcut-material-limit.png](cam-overcut-material-limit.png) | Actual top view: flange pocket with 6 mm overcut stopped at the blank edge by material limit 0; 3 mm demonstration tool | [Overcut](../cam/operations.md#overcut-into-void-material) |
| [cam-air-cut-removed.png](cam-air-cut-removed.png) | Actual Preview: bolt-hole counterbore pocket after the flange pocket starts at Z-15, not the Z0 material surface; 3 mm demonstration tool | [Selection and depths](../cam/selection-and-depths.md#start-and-end-depth-fields) |
| [cam-material-initial.png](cam-material-initial.png) | Actual Preview initial height-field blank; Material on, toolpaths hidden | [Current material](../cam/material-state-and-leads.md#example-blank-then-pocket-output) |
| [cam-material-after-pocket.png](cam-material-after-pocket.png) | Actual calculated material after the annular Pocket; boss and unprocessed holes/corners remain; 0.5 mm checking grid, decimated display | [Current material](../cam/material-state-and-leads.md#example-blank-then-pocket-output) |
| [cam-material-lead-paths.png](cam-material-lead-paths.png) | Same result with one cutting depth and lead paths displayed; demonstration 3 mm tool/material data. Captured before short retracts / stay-down entries (entries still rise to safe Z) | [Current material](../cam/material-state-and-leads.md#example-blank-then-pocket-output) |
| [cam-pocket-raster-pass.png](cam-pocket-raster-pass.png) | Earlier raster-strategy capture for comparison, including magenta entry/retract motion | [Toolpath strategies](../cam/toolpaths.md#raster-comparison) |

The selected-floor and annular-pass captures show a part with boss top Z0,
flange floor Z-15, and base bottom Z-30. Generated removal stops at the selected
floor Z-15. The square/circle image is a constructed 90 mm square removal
region with a 25 mm-radius retained island, displayed using the actual generator
and Preview. Captures use isolated settings/library state and are cropped for
readability. They are not synthetic
renderings or evidence of safe hardware execution.

## Adding pictures for a feature

1. Capture the real implemented UI/result; use an isolated settings/library
   namespace and avoid exposing personal paths, machine credentials or unrelated
   windows. Do not modify operator projects just to stage a screenshot.
2. Use descriptive names such as `cam-pocket-floor-selected.png` rather than
   numbered temporary filenames. Prefer PNG for UI/line art and JPEG where
   photographic content or file size makes it appropriate.
3. Crop irrelevant window/background areas without changing what the feature
   actually displays. If annotated, say which marks were added externally.
4. Add alt text and a caption in the feature guide explaining the selected
   geometry, relevant values and what the image does **not** establish.
5. Add an inventory entry here and update existing pictures when changed UI
   would make them misleading. Label retained historical pictures explicitly.
6. Run documentation link tests after moving/renaming files. Application
   controls and written documentation, not an old screenshot alone, define
   current behaviour.
