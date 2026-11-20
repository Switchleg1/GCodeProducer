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
