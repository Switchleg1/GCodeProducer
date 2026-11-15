[Documentation](../README.md) / [CAM](README.md)

# Geometry selection and linked depths

## What is selectable?

STL stores triangles, not CAD faces, edges or analytic circles. The application
reconstructs a limited topology after placement:

- **Face:** a connected group of coplanar triangles. Disconnected patches in
  the same plane are separate faces. A curved surface is not one analytic face.
- **Feature edge:** a boundary or a crease exceeding the current 30° threshold.
  Ordinary coplanar triangle seams are omitted.
- **Edge chain:** feature segments continue through degree-two vertices;
  branches stop chains. A cube edge stops at its corners; a faceted circular
  rim can form one closed chain.

A shallow crease below the threshold may not be selectable as a feature edge.
Very coarse meshes may not approximate a circle well enough for drilling.
This is not a replacement for exact B-rep/CAD topology.

## Selecting cutting geometry

1. Select an operation in the CAM tree. Its geometry count and settings appear.
2. Choose **Select faces** or **Select edges**.
3. Keep **Pick purpose: Apply picks to machining geometry**.
4. Click an element to add it; click it again to remove it.
5. Use **Clear geometry** to remove all cutting references from this operation.

Selected faces/edges highlight yellow. The operation owns its selections;
switching to another operation displays that operation's geometry. Merely
selecting another tree node does not copy geometry between operations.

Clicking different triangles of the same reconstructed face resolves to the
same face reference. A different segment of the same feature chain resolves
to that chain. Selected individual edges can be assembled into a closed
contour when their endpoints meet. Open branches or incomplete selections
cannot define a pocket/profile boundary.

Picking is click-on-release with a small drag tolerance. Drag to orbit rather
than accidentally accumulating selections; Shift-drag/right-drag pans. Esc
returns to navigation. Leave selection mode to drag the model in XY. Place on
face and CAM picking are separate, mutually exclusive actions.

Topology, hit evaluation and selection highlights are computed outside the UI
process. A short delay is expected after a pick or placement edit; requests
for old scenes/operations are discarded rather than applied to the current one.

## Cutting geometry versus height-only geometry

A horizontal face may define the operation boundary, while another face
provides a bottom height. To avoid cutting both faces:

1. Select the intended cutting boundary normally.
2. Change Pick purpose to **Pick height reference only**.
3. Click the depth-reference face/edge.
4. Press **Use last pick** next to Start Z or End Z.

A height-only pick updates the last-picked geometry/Z display but does not
add/remove a cutting reference. **Use last pick** uses the chosen geometry
as a live reference and resets that depth's numeric offset to zero. Set the
offset afterwards. The minimum/maximum dropdown determines which extreme is
used. A reference used for depth need not be horizontal; a vertical face can
supply either its top or bottom Z. Cutting geometry has stricter requirements.

## Start and end depth fields

Every operation has independent Start Z and End Z definitions:

| Source | Numeric field means | Evaluation |
|---|---|---|
| Model top + offset | Offset in mm | Highest placed model vertex Z + offset |
| Model bottom + offset | Offset in mm | Lowest placed model vertex Z + offset |
| Absolute Z | World/work-coordinate height | Numeric value directly |
| Selected geometry + offset | Offset in mm | Reference minimum or maximum Z + offset |

The minimum/maximum selector affects geometry references. It is irrelevant to
an absolute height or the explicit Model top/bottom sources. The resolved
start/end values are shown below the fields. A Geometry source without a
reference is an error, not an implicit zero.

**Start** is the cutting-depth reference, not the safe rapid height. Each
pass normally cuts a stepdown below Start, ending at End. End must be at or
below Start. For a 20 mm part placed from -20 to 0, Start=Model top and
End=Model top + (-3) produce depths -1, -2, -3 with a 1 mm stepdown. The final
pass is shortened when the total depth is not an exact multiple of the step.
Equal start/end currently produces one pass at that height; inspect whether
that is useful for the intended operation.

### Example: pocket ending at a picked floor

Suppose the top is Z0 and the intended floor face is Z-6:

- Select the pocket boundary as cutting geometry.
- Pick the floor in height-only mode and Use last pick for End.
- End source becomes Selected geometry, offset 0.
- Start=Model top, stepdown=1.5 mm gives -1.5, -3, -4.5, -6.
- To leave 0.2 mm of axial stock, change End's offset to **+0.2**, giving -5.8.

The operation Stock to leave field is **radial** compensation; it does not
replace the axial End offset.

## Placement and changed geometry

References store triangle/vertex indices, not frozen world coordinates.
Translation/rotation/scale re-evaluates their Z values and boundaries. Absolute
Z does not follow geometry. Model-top/bottom sources follow the entire placed
model rather than a selected feature.

Rotating a cutting face away from horizontal can invalidate a 2.5D operation,
even though its depth reference still resolves. Source-file geometry changes
invalidate saved setups through a mesh fingerprint. Never assume a reference
is still semantically correct after remeshing or replacing a model.

## Selection errors

- **Select machining geometry first:** operation has no cutting references.
- **Select closed edges or a horizontal face:** a required boundary is open.
- **Horizontal face / constant-Z edges required:** selected cutting geometry
  does not satisfy 2.5D restrictions.
- **Reference no longer exists:** geometry topology/indices no longer match;
  reselect rather than guessing another index.
- **Depth has no geometry reference:** use a real pick or choose another source.

Continue with the [operation reference](operations.md).
