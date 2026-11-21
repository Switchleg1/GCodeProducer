# Benchmark assumptions

- For the supplied CamBam example, both native stock boxes are unset. The
  offline replay assumes the closed outline is initially full at the target
  plane and uses a disk with the declared tool diameter. It does not infer
  the original blank, stock beyond the outline, or workholding.
- The supplied G-code uses metric absolute XYZ and incremental I/J. Target
  plane replay excludes the descent and lifts; its link classification is
  based on prior reconstructed sweeps, not a machine-clearance guarantee.
- Above-plane feed projections flag potentially entry-affected strokes as a
  group; they do not model the axial cutting edge or credit removal at depth.
- Synthetic corner and slot fixtures use a 2 mm flat cutter at one fixed
  plane with known pre-cleared stock. They compare geometry and contact,
  not cutting data, machine clearance, or physical safety. The 95° corner
  trial threshold is diagnostic only, not a production setting or a conversion
  from the legacy engagement percentage.
- The two-lobe benchmark subtracts a synthetic seed area in the left lobe.
  It does not model machining that area or an entry from above the stock.
  Stock removed east of X24 mm is a comparison metric for neckward progress,
  not evidence that the path has crossed the neck.
- The 53-cut lookahead delay is specific to the pinned fixture: it starts
  immediately before the baseline last advances its east edge (cut 54).
  It is not a production tuning rule.
- Section-bite probes assume east is neckward on this fixture. The 0.25/0.5 mm
  setbacks, 0.2 mm endpoint inset and three bow depths are trial dimensions,
  not clearance guarantees or machining defaults. The 0.25/0.5 mm retreat
  radii are likewise fixture probes and must pass the same post-cut checks.
  Live-depth probes use the first intersection of a 0.75 mm midpoint ray
  with buffered stock, plus 0.05/0.10/0.15 mm. This estimates first contact
  at one point, not immersion or peak contact along the whole bow. The
  optional west search stops at the first eligible 0.75 or 1 mm inset;
  it does not establish that farther insets lack useful cuts.
- Section following estimates contact on eastward 1.5 mm rays spaced at most
  0.125 mm apart. It supplies a chord-chain candidate, not a continuous
  curvature or contact bound. The original motion checks still apply.
  The width-fit trial scans in 1/16 mm steps beyond 1 mm, capped at 2 mm.
  Its first eligible sampled span need not be the closest continuous one.
  Entry-taper variants apply extra advance only after the first quarter,
  reaching full advance halfway through; they do not model cutting forces.
  The terminal approach probe instead stretches the entire entry blend to
  40% or 50% of the span, leaving the exit unchanged.
  The longer-ray audit uses 1.55, 1.65 and 1.8 mm as bounded fixture probes;
  it commits no cuts and does not relax any motion gate.
  The local relief probe offsets west within the failing chord Y band and
  eases back over 0.3 mm shoulders. It assumes west is away from stock for
  this fixture and still checks every resulting cut and link.
  The relief audit counts shifts of at least 0.001 mm as visible in the
  report; that threshold is not a usefulness or quantization guarantee.
  Widening probes scan 0.25–3 mm setbacks in 1/16 mm steps, with 2.75 mm
  contact rays. The gauge is fixed 0.75 mm behind the pre-cut east edge;
  a width gain there does not verify passage across the whole neck.
  A scheduled widening retry needs at least 0.01 mm gain at its pre-cut
  gauge; this diagnostic threshold is not a production machining tolerance.
  The 128-cut comparison changes only the benchmark budget; review-file
  equality compares rounded plotting coordinates, not controller motion.
  Review exports default to a separate Documents review folder by convention,
  not a production output path. The first file shows the synthetic fixture
  in XY only, not the saved Stormtrooper session or controller-ready output.
  The full-stock variant assumes no prior operation or predrilled entry.
  It cannot claim at-depth clearance at the seed until entry is modeled.
  The entry audit uses a 4 mm flat cutter, Z0 to Z−2, and a 10° angle cap.
  X≤24 restricts helix placement to the left lobe. The independent floor
  sweep uses 32 buffer segments per quadrant, finer than the entry helper;
  it gives no cutting credit for the descending helix.
  The entry slice replay credits only motion at or below each plane, samples
  at 0.025 mm XY, and uses 60° as a diagnostic cutoff, not an entry limit
  certified for the tool. Separate slice peaks need not occur together.
  The synchronized axial audit represents a flat cylinder with uniform full
  stock across Z. Eight and 16 midpoint bands estimate thickness, not a
  certified peak or flute, chip, or machine load.
  Pitch comparisons use 10°, 5°, and 2.5° caps, not requested exact pitch;
  helix lap rounding gives lower actual angles. XY distance is not time.
  The first-cut audit uses the 2.5° cap and the helper's exact credited
  floor geometry. Bow angles and advances are planar trial proposals;
  additional travel to stock top and helix qualification remain separate.
  Second-cut probes sample radial first contact from the helix center up to
  1.2 mm beyond its orbit. A hit supplies proposal geometry only.
  The bounded seed trial tests straight proposals on raw front edges of
  at least 2 mm. The fitted trial simplifies proposal stock at 0.15 and
  0.30 mm with straight ends extended 1.25 or 2 mm. None of these
  approximations is used by the live-stock checks.
  Turned-straight probes try 0.75/1.25/1.75 mm bodies with 0.4/0.65 mm
  turn radii. Endpoint membership in the clearance map is a proposal
  filter only; full-disk and sampled contact checks still govern.
  The 24-cut comparison holds the accepted-cut budget fixed, not coverage;
  distance totals include planar links and cuts but exclude the helix.
  The live focus unions the fixed neighborhood with the connected center
  region expanded by cutter radius plus 0.35 mm; this is only a search area.
  Longer-body probes are capped by the unextended fitted chord length.
  The 2.25/2.75/3.25 mm lengths are trial dimensions, not tool limits.
  Long-versus-short means pair the best ranked long candidate with the
  selected cut in each round that offers a checked long candidate. They
  are not a comparison between complete paths at equal coverage.
  The face probe preserves the stock-left direction and measures body
  removal after subtracting the preceding lead sweep with polygon buffers.
  The reported approximation is not an engagement or force estimate.
  The neighbor probe inserts the already-checked greedy second cut;
  it does not claim an optimal neighboring pass or an equal-coverage run.
  The fitted comparison exhausts the eligible neighbors for this one pose,
  then checks the return set for each and ranks the pairs by efficiency.
  It does not optimize arbitrary paths or hold removal exactly equal.
  The neck-pair fixture uses +X as the neck direction. The first body's
  stock-left unit normal must have an X component of at least 0.7;
  pair reach is ranked at six decimal places in mm.
  Repeated pairs take the last verified return body as the new reference
  and commit neither neighbor nor return if the pair cannot be checked.
  Widths use fixed X stations relative to the shared initial east edge
  and the widest contiguous Y span, not a sum of disconnected spans.
  Anchored straights reserve 0.2 mm at each end of a contiguous span,
  shift east, and require mapped endpoints plus the original motion checks.
  Moving anchors probe 0.125–0.625 mm behind the live edge; stations at
  or west of the original seed edge are excluded as in the fixed probe.
  The tapered probe keeps the original lateral offset and tests lead runs
  of 1, 1.5 and 2 times the rejected turn's axial run on identical stock.
  Clearance-fitted leads sample interior positions on verified horizontal
  intervals 0.125–1.5 mm west of the body, at four trial run lengths.
  The shoulder probe uses eligible anchor cuts as preparations and checks
  the original rejected geometry from the new pose and stock. A preparation
  is not substituted on its own if its paired retry fails. The repeated
  pair audit deliberately stops without a pair even if single cuts remain.
  Hybrid continuation prefers an eligible pair when two budget slots
  remain, otherwise a checked single. The comparison fixes total cut count.
  The handoff transfers modeled stock and the final heading, uses 0.025 mm
  XY contact sampling, and credits no synthetic clearing. A handoff review
  would show only accepted continuation motion, not the helix or seed cuts.
  The fallback searches within cutter radius plus 0.35 mm of the live
  connected component. The map filters proposals; actual checks still apply.
  The 64-cut run changes only the bare-handoff budget; accepted-cut family
  indices describe this offline selection, not elapsed or machining time.
  The wider sweep uses 2.5–4 mm anchor widths, 2.75 mm contact rays and
  0.03/0.05/0.08 mm advance probes. It prioritizes checked eastward reach;
  the width reported for the full stroke includes its retreat.
  The sweep comparison uses eight continuation cuts after the same 64;
  the sweep run therefore has one more cut than the control. Distances are
  planar feed geometry, not machine time.
- Wavefront trial: 4 mm cutter, 60° sampled contact limit, stepovers tried from 1.0 down to 0.12 mm, 3 mm roll-on and
  roll-off blends, clockwise travel with stock on the left. Spiral stepover is chosen on the first few turns and the full
  spiral is then checked once. Cut feed distance stands in for time; it ignores acceleration, rapids and helix descent.
  The thirds rule keeps the even spacing unless a spot in the same band is more than 5% wider.
