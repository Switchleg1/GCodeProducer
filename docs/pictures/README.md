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
| [cam-pocket-generated-pass.png](cam-pocket-generated-pass.png) | Current application capture: one generated annular pocket depth pass; green cuts and magenta vertical entry/retract motion, original stock amber | [Pocket operations](../cam/operations.md#bounds-and-automatic-removal-height) |

The two current CAM captures show a part with boss top Z0, flange floor Z-15,
and base bottom Z-30. Generated removal stops at the selected floor Z-15.
They were captured from the application's actual views with isolated settings
and library state, then cropped for readability. They are not synthetic
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
