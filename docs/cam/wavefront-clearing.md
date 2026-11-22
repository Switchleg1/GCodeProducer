[Documentation](../README.md) / [CAM](README.md) / [Clearing toolpaths](toolpaths.md)

# Wavefront clearing (offline trial)

> **Not in the application.** Choosing **Adaptive clearing** in GCodeProducer
> still runs the generator described under
> [Adaptive clearing](toolpaths.md#adaptive-clearing). The wavefront is an
> offline test tool, `tools/hsm_wavefront.py`. It plans one flat depth of one
> pocket outline and writes XY-only previews. It has no Z moves, entries,
> feeds or tool changes. **Never run its output on a machine.**

The wavefront replaces candidate-by-candidate peel picking with one rule:
grow the area the cutter has already cleared by one stepover, then cut the
new edge. The cuts form concentric fronts that spread from each start point
into every corner. The aim is a peel of even thickness, round motion that
lets the machine hold its feed rate, and as little travel as possible outside
the cut.

## How a pocket is planned

1. **Cutter-centre region.** The pocket is shrunk by the cutter radius. A
   cutter centre anywhere inside that region keeps the cutter inside the
   pocket.
2. **Start islands.** The region is split into lobes wherever a neck is at
   least twice as narrow as the areas it joins. Each lobe gets one start at its
   widest spot. Round a boss a milder narrowing counts (1.15 times): fronts from
   a single start would have to wrap round the boss both ways and fan out at its
   corners, so a square pocket with a boss gets a start in each corner. A pocket with a single lobe gets two starts a third of the way
   in from each end if it is at least twice as long as it is wide, otherwise
   one start. `--islands` and `--placement` override this choice.
3. **Entry.** Each start is entered with a helix. The helix is modelled
   (its floor sweep is removed from the stock), not written to the preview.
4. **Spiral.** From the helix floor, the cutter spirals out in one continuous,
   clockwise cut until the circle touches the nearest wall, then rolls off
   inward.
5. **Fronts.** The cleared region is grown by one stepover and clipped to the
   pocket; the new edge is the next cut. Each island grows as if it were alone,
   so its fronts stay concentric where two islands meet. Where two islands can
   reach the same ground, the island whose spiral edge is nearer takes it. The
   last island cuts through into space the earlier ones opened.
6. **Ends at the wall.** A front that reaches the wall does not stop square
   against it. Depending on where it is and the angle at which it arrives, it
   does one of four things:
   - **Crosses as one bow** in a narrow channel whose walls are within 8° of
     parallel and up to about 15 mm apart (for a 4 mm cutter): the cut comes
     in along one wall, curves out across the channel at right angles to the
     walls, curves onto the other wall tangentially and runs back along it.
     Every pass is the last one moved on by a stepover. Two separate hooks
     would be tight corners on so short an arc. Where the bow is too heavy,
     as at the mouth of an arm while the front is still curved from the
     spiral, separate hooks are tried instead.
   - **Runs on along the wall** if it arrives at a shallow angle, as beside a
     spiral.
   - **Hooks round** onto the wall if it arrives steeply: it continues its own
     curve, meets the wall tangentially heading back toward cleared ground, runs
     along it, and turns off into the pocket. The hook radius is up to twice the
     cutter radius. Successive hooks nest one stepover apart.
   - **Rolls back** onto the previous front when neither shape is possible.

   Either way, the end follows the wall back until it reaches wall that earlier
   cuts already cleaned, plus 0.75 mm of overlap. Every stretch of wall is
   therefore passed along at least once and no wall pass is needed afterwards.
   The wall is not followed where the cleared area falls away from it, nor
   round a corner onto another wall (more than 40° of turn within 2 mm),
   which often leads into an arm still full of stock. The start of each cut
   mirrors its end.
7. **Stepover.** Each cut is replayed against the live stock and its contact
   angle is sampled every 0.1 mm. A cut over the contact limit (60° by default)
   is refused and retried at the next smaller stepover, near the failure only:
   1.0, 0.8, 0.65, 0.5, 0.4, 0.3, 0.2 and 0.12 mm. Nothing over the limit is
   kept.
8. **Links.** Cuts are joined by stay-down feed moves through space already
   cleared, routed along the edge of the cleared region and pulled taut. Every
   link is checked to keep the whole cutter clear of the live stock. The
   preview shows a lift (G0) only where no such route exists: the first cut,
   and moving from one island to the next.
9. **Wall pass (optional).** `--wall-profile` adds a pass along the pocket
   wall at the end. It is off by default because the wall ends above leave
   almost nothing for it.

## Running it

```bash
python tools/hsm_wavefront.py --review-gcode C:/path/new-review.nc
python tools/hsm_wavefront.py --pocket-wkt examples/hsm-shapes/slot.wkt --review-gcode C:/path/slot.nc
```

| Option | Meaning |
|---|---|
| `--pocket-wkt FILE` | Pocket outline as a WKT polygon, in mm. Without it the two-lobe neck fixture (`examples/adaptive-neck-pocket.wkt`) is used. |
| `--review-gcode FILE` | Write a debug-only XY `.nc` and a matching `.svg` overlay. Existing files are never overwritten. |
| `--islands N` | Number of start islands, overriding the shape-based choice. |
| `--placement lobes\|thirds\|widest` | One start per lobe (default), spread along the long axis, or the widest remaining spots. |
| `--no-wall-pull-back` | Roll cuts off before the wall instead of following it back. Kept for comparison. |
| `--wall-profile` | Finish with a pass along the pocket wall. |
| `--time-budget SECONDS` | Stop adding fronts after this long; the report then says `time_budget`. |
| `--sample-step MM` | Contact sampling distance (default 0.1 mm). |

The command line uses a 4 mm flat cutter and a 60° contact limit;
`clear_pocket()` takes others. In the `.svg`, blue lines are cuts, grey lines
are stay-down links and orange shows reachable stock left. The `.nc` marks
each cut, its stepover and its sampled peak contact in comments.

## Reading the report

| Field | Meaning |
|---|---|
| `stop` | `front_exhausted`: nothing left that a front can reach. `blocked`: some cuts were refused at every stepover. `time_budget`: stopped early. |
| `reachable_residual_mm2`, `cleared_fraction` | Stock the cutter could reach but did not remove. Corners tighter than the cutter radius are not counted. |
| `peak_contact_deg` | Largest sampled contact angle on any kept cut. The refusal rule keeps it at or below the limit. |
| `mean_contact_deg`, `mean_contact_while_cutting_deg` | Distance-weighted average contact over all cutting moves, and over the moves touching stock. |
| `cut_feed_mm`, `link_feed_mm`, `spiral_feed_mm` | Planar distance cutting, linking through cleared space, and the spiral part of the cutting. |
| `stay_down_links`, `retract_rapids`, `retract_reasons` | How cuts were joined, and why each lift was needed. |
| `front_arcs`, `front_stepover_histogram`, `arcs_at_0.2_mm_or_less` | How many front cuts used each stepover. Many small stepovers mean an uneven peel. |

**Contact angle** is the arc of the cutter's circumference that touches stock,
measured on a flat 2D model. As a straight side cut, 37.5° is about 10% of the
cutter diameter and 60° is 25%. These are geometry figures: they say nothing
about cutting force, chip load, deflection, the helix entries, or the
cutter's flutes. Distance stands in for time here; acceleration and real feed
rates are not modelled.

## Current results

4 mm cutter, 60° limit, no wall pass. Each row is one run of version 0.2.2 or later.

| Pocket | Front arcs | Of which ≤ 0.2 mm | Stock left | Cutting | Links | Lifts |
|---|---|---|---|---|---|---|
| Two-lobe neck fixture | 187 | 0 | 2.6 mm² | 9,912 mm | 3,884 mm | 2 |
| Circle, 44 mm | 0 (spiral only) | 0 | 0.7 mm² | 3,268 mm | 0 | 1 |
| Rectangle 60×30 | 85 | 1 | 11.8 mm² | 4,124 mm | 1,709 mm | 2 |
| L-shape | 143 | 10 | 8.3 mm² | 3,989 mm | 3,195 mm | 1 |
| Cross | 177 | 7 | 15.5 mm² | 3,671 mm | 2,667 mm | 1 |
| Slot 80×12 | 187 | 11 | 9.5 mm² | 2,771 mm | 1,497 mm | 2 |
| Square with a 16 mm boss (4 starts) | 249 | 14 | 5.1 mm² | 5,110 mm | 3,312 mm | 5 |
| Ring, 48 mm across with a 20 mm boss | 430 | 193 | 1.1 mm² | 5,604 mm | 10,710 mm | 1 |

The shapes are in `examples/hsm-shapes/`. On the two-lobe fixture the average
contact is 39.6° and almost every front uses a 0.4–0.65 mm stepover. In the
slot the bows settle at a 0.4 mm stepover with a steady 56° peak. The square
with a boss went from one start (162 of 351 arcs at 0.2 mm or less, 7,433 mm
cutting, 10,908 mm links) to four. All shapes except the ring now hold an
even peel; the L-shape and cross still spend most of their cutting distance
again on links.

## Known gaps

- **Curved channels** (the ring): uneven peel and twice as much link travel as
  cutting. The bow assumes straight walls.
- **Channels**: the first few bows after a spiral, the end of a channel, and
  the join between two islands still drop to small stepovers.
- **Hooks on wide straight walls** swing between about 47° and 66° from pass to
  pass instead of holding steady; the contact check refuses the heavy passes.
- **Link travel** is long on the L-shape and cross. Link corners are not
  rounded and links have no feed rate yet.
- **Leftover stock** of a few square millimetres on most shapes is not yet
  located.
- **Not built:** Z motion and helix output, depth steps, allowance, tabs and
  protected geometry, replay of rounded output coordinates, and the application
  interface. One depth of the two-lobe fixture takes about three and a half minutes.
- The 60° limit and the shape constants (hook radius, overlap, neck ratio) are
  trial values tuned on these shapes only.

The regression cases behind each rule are in `tests/test_hsm_wavefront.py`.
How the approach was reached is summarised in the
[research notes](adaptive-research-notes.md#wavefront-trial).
