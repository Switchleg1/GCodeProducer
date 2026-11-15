[Documentation index](../README.md)

# Documentation pictures

Store documentation screenshots, annotated examples and other feature images
in **`docs/pictures/`**. Link to them from the feature guide using relative
paths; do not scatter new images across the documentation root.

## Image inventory

| File | Purpose / provenance | Used by |
|---|---|---|
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
| [cam-tool-calculation.png](cam-tool-calculation.png) | Actual tool editor calculation checkbox, RPM ceiling and lead-feed percentage; isolated example profile | [Cutting data](../cam/cutting-data.md#automatic-calculation) |
| [cam-tool-material-table.png](cam-tool-material-table.png) | Actual per-tool Non-iron metal SFM/chip-load/axial table; illustrative values, not a calibrated recipe | [Cutting data](../cam/cutting-data.md#per-tool-per-material-table) |
| [cam-material-initial.png](cam-material-initial.png) | Actual Preview initial height-field blank; Material on, toolpaths hidden | [Current material](../cam/material-state-and-leads.md#example-blank-then-pocket-output) |
| [cam-material-after-pocket.png](cam-material-after-pocket.png) | Actual calculated material after the annular Pocket; boss and unprocessed holes/corners remain; 0.5 mm checking grid, decimated display | [Current material](../cam/material-state-and-leads.md#example-blank-then-pocket-output) |
| [cam-material-lead-paths.png](cam-material-lead-paths.png) | Same result with one cutting depth and lead paths displayed; demonstration 3 mm tool/material data | [Current material](../cam/material-state-and-leads.md#example-blank-then-pocket-output) |
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
