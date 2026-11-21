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
