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
   **One way round a boss:** where a single spiral fills the channel between
   the outer wall and a boss, its two sides would each send a front round, to
   meet head-on on the far side in a narrowing pinch. Instead the half of the
   spiral behind is treated as still uncut and one front is followed all the
   way round; its last passes go straight through the spiral, cutting only
   the two corners beside it. Elsewhere the front nearest the cutter goes next.
6. **Ends at the wall.** A front that reaches the wall does not stop square
   against it. Depending on where it is and the angle at which it arrives, it
   does one of four things:
   - **Crosses as one bow** in a narrow channel whose walls are within 8° of
     parallel and up to about 15 mm apart (for a 4 mm cutter): the cut comes
     in along one wall, curves out across the channel at right angles to the
     walls (square to both walls it spans, not along the slant of the front,
     so curved channels and boss corners do not drift), curves onto the other wall tangentially and runs back along it.
     Every pass is the last one moved on by a stepover. Two separate hooks
     would be tight corners on so short an arc. Behind a front still curved
     from the spiral the straight crossing is set back until it is nowhere
     further from cleared ground than the front: it takes the two flanks,
     passes through air in the middle, and the front is straight after a few
     passes. Where the bow is still too heavy, separate hooks are tried
     instead.
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
   1.0, 0.8, 0.65, 0.5, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15 and 0.12 mm.
   Nothing over the limit is kept. Below 0.5 mm the steps are 0.05 mm apart,
   so a cut that just misses at one step loses little at the next; with
   0.1 mm steps the slot and ring jumped between 0.4 and 0.2 mm passes.
   At 0.35 mm or below a cut may also roll off before the wall instead of
   sweeping it. Beside a spiral that only touches the wall there is no clean
   wall to run back onto, and without this the first fronts fell to 0.12 mm.
8. **Links.** Cuts are joined by stay-down feed moves through space already
   cleared, routed along the edge of the cleared region and pulled taut. Every
   link is checked to keep the whole cutter clear of the live stock. The
   preview shows a lift (G0) only where no such route exists: the first cut,
   and moving from one island to the next.
9. **Finish on leftovers.** Last, the cutter follows the pocket wall only
   where stock thicker than 0.02 mm is still on it, first 0.3 mm off the wall
   and then on it, each stretch checked against the contact limit. This takes
   the skin the last front of a channel leaves because no later front sweeps
   back over it. Clean wall is not passed again. `--no-wall-finish` skips it.

## Speed

One depth of the two-lobe fixture takes about 10 s (145 s before 0.2.9), the
ring 12 s (124 s) and the other shapes 0.4–9 s. What made the difference:

- **Contact is measured without replaying the cut.** The cutter has swept
  everything behind it, so only the half of its edge facing forward can touch
  material. That half is measured against the stock from before the stretch,
  for all samples of a stretch at once. The earlier measure subtracted the
  sweep after every 0.1 mm sample. Both give the same angles to about 0.7°
  (the old one read that much high from its polygon sweeps); a test holds
  them together.
- **A refused cut stops being measured** at the first sample over the limit.
- **The cleared region is updated near each cut** instead of being recomputed
  for the whole pocket.
- **Films of stock under 2 µm thick are dropped.** They are leftovers of
  polygon arithmetic, and each one put a scallop in the cleared region's
  outline, which grew to many thousands of points.
- **A larger stepover is retried only now and then** once a front has settled
  at 0.4 mm or more, not on every pass.

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
| `--no-wall-finish` | Skip the finish along wall that still has stock on it. |
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

4 mm cutter, 60° limit, no wall pass. Each row is one run of version 0.2.9; the last column is the compute time for one depth.

| Pocket | Front arcs | Of which ≤ 0.2 mm | Stock left | Cutting | Links | Lifts | Time |
|---|---|---|---|---|---|---|---|
| Two-lobe neck fixture | 187 | 0 | 2.8 mm² | 8,739 mm | 4,229 mm | 2 | 9.6 s |
| Circle, 44 mm | 0 (spiral only) | 0 | 0.7 mm² | 2,640 mm | 0 | 1 | 0.4 s |
| Rectangle 60×30 | 86 | 0 | 10.4 mm² | 3,587 mm | 1,705 mm | 2 | 3.3 s |
| L-shape | 142 | 4 | 7.4 mm² | 3,765 mm | 2,959 mm | 1 | 5.1 s |
| Cross | 202 | 25 | 9.7 mm² | 3,660 mm | 3,111 mm | 1 | 7.7 s |
| Slot 80×12 | 178 | 8 | 5.6 mm² | 2,457 mm | 1,606 mm | 2 | 4.6 s |
| Square with a 16 mm boss (4 starts) | 288 | 0 | 9.0 mm² | 5,114 mm | 3,199 mm | 4 | 9.2 s |
| Ring, 48 mm across with a 20 mm boss (one way round) | 243 | 0 | 0.0 mm² | 3,919 mm | 2,323 mm | 1 | 11.7 s |

The shapes are in `examples/hsm-shapes/`. On the two-lobe fixture the average
contact is 41.1° and almost every front uses a 0.45–0.65 mm stepover. In the
slot 125 of 178 bows run at 0.45 mm; in the ring 223 of 243 run at 0.5 mm.
Figures moved a little against 0.2.8 because the contact measure reads about
0.7° lower: the cross has more small arcs (11 → 25), the rectangle and the
square with a boss none. The finer steps cut every shape's cutting
distance by 3–11 % against 0.2.4, and halved the ring's small arcs (194 → 102);
the two-lobe fixture now takes 103 s a depth instead of 221 s. The square
with a boss went from one start (162 of 351 arcs at 0.2 mm or less, 7,433 mm
cutting, 10,908 mm links) to four; crossing square to the walls then took
its last small arcs away (14 → 0) and cut links to 2,551 mm. In the ring,
going one way round took the arcs at 0.2 mm or less from 102 of 411 to none:
213 of 243 fronts run at 0.5 mm, cutting fell from 5,308 to 3,982 mm and links
from 9,663 to 2,272 mm. The set-back bows and roll-offs of 0.2.8 cost the
square with a boss 38 more arcs and about 300 mm more cutting. The L-shape and
cross still spend most of their cutting distance again on links.

## Known gaps

- **Arriving back at the spiral** in a ring: the fronts inside the spiral's
  space are shaped by stock that is only assumed there, and the two corners
  beside the spiral are finished by the wall finish (29 mm of cutting, nothing
  left) rather than by the fronts themselves.
- **One way round is only used with a single start.** A square with a boss
  has four starts, and their fronts still set off both ways and meet between
  the corners.
- **Channels**: the first few bows after a spiral, the end of a channel, and
  the join between two islands still drop to small stepovers.
- **Hooks on wide straight walls** swing between about 47° and 66° from pass to
  pass instead of holding steady; the contact check refuses the heavy passes.
- **Link travel** is long on the L-shape and cross. Link corners are not
  rounded and links have no feed rate yet.
- **Leftover stock** of 5–10 mm² on shapes with square corners sits in those
  corners; the fronts and the wall finish are both refused there at every
  stepover. It needs a corner move of its own.
- **Not built:** Z motion and helix output, depth steps, allowance, tabs and
  protected geometry, replay of rounded output coordinates, and the application
  interface.
- The 60° limit and the shape constants (hook radius, overlap, neck ratio) are
  trial values tuned on these shapes only.

The regression cases behind each rule are in `tests/test_hsm_wavefront.py`.
How the approach was reached is summarised in the
[research notes](adaptive-research-notes.md#wavefront-trial).
