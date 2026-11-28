[Documentation](../README.md) / [CAM](README.md)

# Two-sided machining (CAM 3D 2Sided)

Machine a part from the top, turn the stock over, and machine it from the
other side. Choose **Workflow: CAM 3D 2Sided** in the Setup pane. (The
Workflow box offers **FDM**, **CAM 3D** and **CAM 3D 2Sided**; the last two
are the same CAM workflow, with a one- or a two-sided setup.)

This is geometry and planning only. It does not model fixtures, and it has
not been qualified on a machine: check both programs before running them.

## Sides

One setup holds both sides. Two rows appear under Workflow:

- **Side**: *Side A (top)* or *Side B (turned over)*. Everything shown,
  planned, sliced and exported is the side selected. Each side has its own
  tool groups and operations; switching sides switches the operation list.
- **Turn the stock about**: its **X axis** (the front edge stays at the
  front, the back at the back) or its **Y axis** (left stays left).

The stock, the holding tabs and the reference shapes belong to the setup and
are the same on both sides.

## What turning over means

For Side B the stock is turned over about the chosen axis through its centre
and put back **in the same place on the table**: it occupies the same box,
its old top face lies on the bed, and its old underside is the new top. The
stock's top is therefore at the same height as before.

The model keeps its place inside the material, so it is shown and planned
rotated half a turn about the centre of the stock's box. With an automatic
stock (top at the model's top, a margin underneath), the model's old
underside is that margin below the top on Side B.

- Operations pick faces and edges of the model; on each side they are
  planned on the model as it lies for that side. Pick Side B's geometry with
  Side B selected.
- **Reference shapes** are positions on the table, not on the model: a shape
  is in the same place on both sides. Shapes placed symmetrically about the
  stock's centre (registration holes, for example) therefore coincide after
  the turn.
- **Auto — fit material to part** always fits the stock to the model as it
  lies for Side A, whichever side is shown.
- Without allocated stock the model turns about the centre of its own bounds.

## Material on Side B

Side B is planned against a full, uncut block. What Side A removed is not
carried over. That is on the safe side for loads and collisions (Side A's
cuts can only make Side B's lighter), but Side B may cut air where Side A
already cleared, and the material Preview of Side B starts from a full block.

## Work Z origin

For either side, **Libraries → Machines → Work area → Z0 at bed** places work Z0 at the underside of the allocated stock. With 20 mm stock and Safe Z set to 5 mm, the top is Z20, a 2 mm pocket floor is Z18, and the safe retract is Z25. With Clearance Z set to 2 mm, the entry rapid stops at or above Z22 and the remaining descent is fed. `{safe_z}` and `{clearance_z}` both resolve to these work coordinates in CAM templates. Set the controller’s **work offset** accordingly; the checkbox does not home the machine or set its offset. Stock thickness must be known and the safe retract must fit within machine Z travel.

Prepare retains the saved setup coordinates, including absolute depths and drawing planes. During slicing the placed part, references and depths are translated together. Preview and NC show the resulting work coordinates. Unchecked (default) retains the existing CAM coordinates. In custom start/end G-code, use `{safe_z}` rather than a literal retract Z: literal machine commands are not rewritten.

## Output

Slice and export each side with that side selected. The program begins with
`Side A of 2` or `Side B of 2: stock turned over about its X axis, old top
face on the bed`, and the suggested file name ends in `_sideA` / `_sideB`.

Switching Workflow back to **CAM 3D** shows Side A only; Side B's operations
are kept in the setup and return when CAM 3D 2Sided is chosen again.

## Registration pins

Pins in the table, through holes in the stock, locate it on both sides. The
holes are drawn as **reference geometry** (0.2.79) and cut by an operation
you set up yourself (drill them, or pocket or profile them, to the depth you
choose, normally through the stock and into the spoilboard, on Side A).

In the Reference geometry pane choose **New shape: Registration pins — box
about the stock centre, then pin size**, then **Draw**:

1. Move the mouse: a box is previewed, centred on the stock and reaching the
   mouse, with its width and height. Click to set it.
2. Move out from a corner: four circles are previewed at the corners of that
   box, with their diameter (the distance from the mouse to the nearest
   corner is the radius). Click to add them.

Each set appears as one **Pins** row. Select it to highlight all four holes.
**Pin spacing X/Y** is the full centre-to-centre distance across the box in
each direction, not the coordinates of one hole. Diameter and Z apply to all
four. The individual circles remain pickable for machining:

- the box is always centred on the stock, so turned over about either axis
  every hole lands exactly on a hole;
- editing one pin edits all four: change its diameter or Z in the form, or
  move it (form, Move or Resize tools), and the set stays a centred box (a pin
  cannot be put on the stock's centre line);
- when the stock is moved, resized or refitted, the pins move with its centre
  and keep their box;
- deleting one pin deletes its set (refused while an operation on either side
  uses any of them).

The stock must be allocated first. Pins may lie outside the stock.

## Not there yet

- Registration against a fence along one edge: nothing is generated or
  checked for it (the turn itself is the same).
- Side A's remaining material is not carried to Side B (see above).
