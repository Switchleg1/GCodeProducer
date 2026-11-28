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

## Output

Slice and export each side with that side selected. The program begins with
`Side A of 2` or `Side B of 2: stock turned over about its X axis, old top
face on the bed`, and the suggested file name ends in `_sideA` / `_sideB`.

Switching Workflow back to **CAM 3D** shows Side A only; Side B's operations
are kept in the setup and return when CAM 3D 2Sided is chosen again.

## Not there yet

- Registration: no pin holes or fence are generated. Draw the holes as
  reference circles (symmetric about the stock's centre) and cut them with an
  operation on Side A.
- The machine's Z0 is always the top of the material; a "Z0 at the bed"
  option is planned.
- Side A's remaining material is not carried to Side B (see above).
