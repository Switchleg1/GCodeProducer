[Documentation](../README.md) / [CAM](README.md) / [Clearing toolpaths](toolpaths.md)

# Wavefront clearing

> **Adaptive clearing in the application uses this planner** for Pocket and
> 3D Waterfall (see [Adaptive clearing](toolpaths.md#adaptive-clearing)).
> The command line tool `tools/hsm_wavefront.py` also writes XY previews and
> XYZ programs for a viewer; those are marked incomplete and are **never to
> be run on a machine**.

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
   **Several starts round a boss** (the square with a boss has one in each
   corner): the channel is cut across at every start, from the boss to the
   start and on to the outer wall square to the way forward. Every spiral is
   cut first, in order round the channel. Then each start sends one front
   forward across its own stretch and straight on through the next spiral,
   as in the ring; the last spiral cut works first, and each front ends where
   the next begins, so no lift is added. An outer corner beside a start falls
   to the stretch arriving there, whose front runs straight on into it.
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
   Nothing over the limit is kept. A refused front is retried lighter
   before any other front is tried: trying the others at the same heavier
   stepover first refused them too, and the lighter retry then cut one front
   in each arm in turn, crossing the pocket between arms on every pass. Below 0.5 mm the steps are 0.05 mm apart,
   so a cut that just misses at one step loses little at the next; with
   0.1 mm steps the slot and ring jumped between 0.4 and 0.2 mm passes.
   At 0.35 mm or below a cut may also roll off before the wall instead of
   sweeping it. Beside a spiral that only touches the wall there is no clean
   wall to run back onto, and without this the first fronts fell to 0.12 mm.
8. **Links.** Cuts are joined by stay-down feed moves through space already
   cleared, routed along the edge of the cleared region and pulled taut. Every
   link is checked to keep the whole cutter clear of the live stock. The
   route is then made into a chain of curves through its corners, leaving
   the cut before along its heading and arriving along the heading of the
   cut after, so the machine need not stop at either end or at a corner.
   The curves are checked the same way; shorter handles are tried before
   the straight route is kept as it was. Sharp turns (over 45° between
   0.5 mm steps) in links fell from 134 to 40 on the rectangle, 285 to 64
   on the L-shape, 302 to 149 on the cross and 461 to 18 on the ring; the
   links grew by 5–17 % (ring 2,323 → 2,728 mm), since curves are longer
   than corners. The
   preview shows a lift (G0) only where no such route exists: the first cut,
   and moving from one island to the next.
9. **Corners.** The fronts swallow a corner once it is within a stepover,
   so the cutter centre never reaches it, and 1–3 mm² were left in every
   square corner. After the fronts, the cutter creeps into each corner along
   one wall and then the other: each move runs in from clean wall to a point
   nearer the corner and backs out along its own track, and goes no deeper
   than 0.3 mm into stock. These moves are judged by depth, not contact
   angle: deep in a corner the stock left is a crescent hugging the cutter,
   which reads 90–115° of contact however thin it is. A corner is any place
   where the wall turns by more than 30° within 2 mm, so chamfered or
   polygon-rounded corners count. Corner moves that would need a lift are
   skipped.
10. **Finish on leftovers.** Last, the cutter follows the pocket wall only
   where stock thicker than 0.02 mm is still on it, first 0.3 mm off the wall
   and then on it, each stretch checked against the contact limit. This takes
   the skin the last front of a channel leaves because no later front sweeps
   back over it. Clean wall is not passed again. `--no-wall-finish` skips it.

## Levels and Z

`clear_depths()` clears a pocket in equal levels from the top down to a
bottom Z, none deeper than the step-down. Each level starts from intact
stock at its own depth; its helices start from the floor of the level
above. Given one outline (a 2.5D pocket) the plan is the same at every
level, so it is worked out once and moved down, with only the helices
changed; given a function of Z (the slices of a 3D waterfall) every level
is planned from its own outline.

`write_program()` writes all levels as one XYZ program for a viewer or
simulator, marked incomplete and never run on a machine: cuts and links at
the level's depth at their feeds, a helix into every start, and wherever a
cut does not start where the last ended, a rise to 2 mm above the top, a
rapid across and a rapid down to just above the level above before the
plunge feed. No tool change, spindle, coolant, tabs or allowance. The
program parses with the application's G-code reader; its time estimate
agrees with `machine_time` to within a few per cent (square with a boss,
three levels to Z-5: 964 s against 956 s).

```bash
python tools/hsm_wavefront.py --pocket-wkt examples/hsm-shapes/boss.wkt \
    --bottom -5 --step-down 2 --program boss-levels-INCOMPLETE-program.nc
```

| Pocket, three levels to Z-5 | Machine time | Compute |
|---|---|---|
| Two-lobe neck fixture | 1,377 s | 20 s |
| Square with a 16 mm boss | 956 s | 13 s |
| Ring | 685 s | 21 s |

## Machine time

The report's `machine_time` estimates one depth with a controller-like
motion planner: each move speeds up and slows down at the set acceleration,
corners are taken at the speed the junction deviation allows, and a forward
and a backward pass keep every speed reachable (the same model as the FDM
time estimate). Cuts, corner moves and links run as one chain without
stopping wherever each starts where the last ended; a lift stops the
machine, rises to 2 mm above the top, crosses at rapid and comes down
again. Helices run at the plunge feed. It is an estimate for comparing
paths, not a machine measurement.

Defaults (`MACHINE_DEFAULTS`): cutting 1,500 mm/min, links 3,000 mm/min,
plunge 500 mm/min, rapid 5,000 mm/min, 500 mm/s², junction deviation
0.02 mm. One depth with these:

| Pocket | Cutting | Links | Helices | Rapids | Total |
|---|---|---|---|---|---|
| Two-lobe neck fixture | 354 s | 89 s | 17 s | 2 s | 462 s |
| Circle, 44 mm | 106 s | 0 | 8 s | 0 | 114 s |
| Rectangle 60×30 | 150 s | 39 s | 17 s | 1 s | 206 s |
| L-shape | 157 s | 60 s | 8 s | 0 | 225 s |
| Cross | 160 s | 53 s | 8 s | 0 | 221 s |
| Slot 80×12 | 103 s | 38 s | 17 s | 1 s | 158 s |
| Square with a 16 mm boss | 207 s | 81 s | 33 s | 3 s | 324 s |
| Ring | 158 s | 64 s | 8 s | 0 | 230 s |

The curved links of 0.2.14 are 5–17 % longer than the straight routes but
save 1–4 % of the total: the cuts and links before and after them no longer
stop at the joins (ring 238.7 → 229.8 s, boss 329.0 → 322.7 s, L-shape
230.2 → 225.3 s).

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
| `machine_time` | Estimated seconds for one depth: `cutting_s`, `links_s`, `helix_s`, `rapids_s`, `total_s`, and the `machine` settings used (see Machine time). |
| `corners`, `wall_profile` | Corner moves (count, feed, contact) and the finish along wall with stock left on it. |
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

4 mm cutter, 60° limit, no wall pass. Each row is one run of version 0.2.14; the last column is the compute time for one depth
(measured while another slicing job shared the machine, so about half again slower than 0.2.9's).

| Pocket | Front arcs | Of which ≤ 0.2 mm | Stock left | Cutting | Corner moves | Links | Lifts | Time |
|---|---|---|---|---|---|---|---|---|
| Two-lobe neck fixture | 184 | 0 | 0.0 mm² | 8,766 mm | 12, 44 mm | 4,040 mm | 2 | 19.0 s |
| Circle, 44 mm | 0 (spiral only) | 0 | 0.7 mm² (a film under 0.01 mm) | 2,640 mm | 0 | 0 | 1 | 0.6 s |
| Rectangle 60×30 | 86 | 0 | 0.0 mm² | 3,598 mm | 25, 86 mm | 1,685 mm | 2 | 4.8 s |
| L-shape | 143 | 10 | 0.0 mm² | 3,783 mm | 25, 84 mm | 2,607 mm | 1 | 7.7 s |
| Cross | 208 | 23 | 0.0 mm² | 3,786 mm | 32, 106 mm | 2,049 mm | 1 | 12.3 s |
| Slot 80×12 | 173 | 4 | 0.3 mm² | 2,474 mm | 18, 49 mm | 1,577 mm | 2 | 5.4 s |
| Square with a 16 mm boss (4 starts, one way round) | 283 | 7 | 0.0 mm² | 5,059 mm | 17, 55 mm | 3,313 mm | 4 | 13.7 s |
| Ring, 48 mm across with a 20 mm boss (one way round) | 243 | 0 | 0.0 mm² | 3,919 mm | 0 | 2,728 mm | 1 | 21.6 s |

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
- **Several starts one way round** cost the square with a boss 7 arcs at
  0.2 mm or less (0 before), at the turns from a side into a corner. Only one
  channel round one boss is handled; pockets with several bosses still let
  fronts meet.
- **Small arcs in corners** (the cross has 25) are fronts squeezing into a
  corner, where contact rises. Leaving such arcs to the corner creep took
  them to none but left the creep with 2.5 times the moves and up to 150°
  of contact; not adopted.
- **Channels**: the first few bows after a spiral, the end of a channel, and
  the join between two islands still drop to small stepovers.
- **Hooks on wide straight walls** swing between about 47° and 66° from pass to
  pass instead of holding steady; the contact check refuses the heavy passes.
- **Link travel** is now mostly the way back across a channel after each
  bow: a bow always starts on the same wall to keep climb milling, so the
  L-shape's 16 mm-wide arm costs a 16 mm link per pass, now a loop rather
  than a reversal. Corner moves still reverse at the tip. The machine time
  uses one cutting feed everywhere; it does not yet slow for heavier
  contact or speed up for light peels.
- **Corner moves** back out along their own track: a full reversal at the
  tip, tiny but abrupt. They are judged by depth only, and their contact
  angle (up to 115°) is reported separately in `corners`, not in
  `peak_contact_deg`. Links grew by 100–300 mm on the square-cornered shapes
  to reach them.
- **Not built:** tabs, the conventional direction and replay of rounded
  output coordinates. In the application, stock to leave is kept from every
  wall and each Waterfall depth starts from the stock earlier passes left.
- **Slower than wall-parallel contours at the same feed.** On the saved
  Stormtrooper setup (3D Waterfall, 4 mm endmill, two depths to Z-2.5, soft
  wood, cutting at 2,000 mm/min) the application estimates 1,553 s against
  236 s for wall-parallel contours at 40 % stepover and 495 s for raster
  lines; all three complete with no safety findings. Per depth the wavefront
  cuts about 15.5 m (10.3 m of it spirals at three starts) and links about
  9.4 m, against 3.4 m of contours: at the 18 % limit (about 50°) its
  average stepover is 0.35–0.4 mm against 1.6 mm. Adaptive clearing pays
  off with a deeper cut and a feed raised for the thin chip; neither is
  applied yet. Compute: 151 s against 5 s.
- The 60° limit and the shape constants (hook radius, overlap, neck ratio) are
  trial values tuned on these shapes only.

The regression cases behind each rule are in `tests/test_hsm_wavefront.py`.
How the approach was reached is summarised in the
[research notes](adaptive-research-notes.md#wavefront-trial).
