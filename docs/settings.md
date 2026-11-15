[Documentation](README.md)

# Global settings

**File → Settings… (Ctrl+,)** opens preferences that apply to every model,
machine and process. They are stored as `settings.json` next to the profile
libraries (`~/.gcodeproducer`, or `GCODEPRODUCER_LIBRARY`), not in QSettings
window state and not in a machine or process profile, because they change
generated output. The CLI reads the same file; `gcodeproducer settings`
lists the current values and `--pref KEY=VALUE` overrides one for a single run.

![Settings dialog](pictures/settings-dialog.png)

| Setting | Default | Effect |
|---|---|---|
| Remove air cutting | On | CAM operations start at the first depth that still holds material (estimated from earlier operations in the same setup), pocket contours lying entirely in removed material are dropped, and operations/passes with nothing left to cut are skipped. Everything skipped is logged. |
| Material grid resolution | 0.2 mm | Height-field cell size for current-material contact checks, lead entry heights and the Material display. |
| Maximum grid cells | 2,000,000 | Memory guard. If `width × depth / resolution²` exceeds it the grid is coarsened and a warning is issued. |
| Colour conflicts and collisions | On | Moves flagged by the planner/stock checks are recoloured as the **Conflict** and **Collision** features in Feature colour mode. |
| Show warning dialog after generation | On | Off keeps warnings in the log and the export confirmation; it never suppresses them. |

Changing a setting marks an existing CAM result stale; regenerate before
exporting. **Restore Defaults** resets the dialog, and OK saves it. A corrupt
or missing settings file silently falls back to defaults at start-up.

## Air-cut removal: what it knows and does not know

The estimate subtracts the planar cutter sweeps of earlier operations at each
recorded depth. It does not know material removed by a previous program, by
hand, or by a tool change outside this setup, and it ignores rapid moves and
lead ramps. An operation lowered to a later start therefore relies on the
earlier operations actually having run. A path is dropped only when its
**entire** cutter sweep meets no remaining material; partially engaged paths
are kept and their engagement classified normally. When a dropped path broke
a stay-down chain the next path re-enters from safe height.

## Material grid resolution

The previous per-machine `stock_resolution` field is ignored and hidden;
the global value replaces it. Small tools (diameter below twice the grid
cell) trigger a warning because sub-cell contacts can be missed. Finer grids
are slower and use more memory: a 300 × 300 mm blank at 0.1 mm is 9 million
cells and is coarsened by the default cell limit. Raise the limit knowingly.

## Conflict and collision colouring

- **Conflict** (yellow): cut segments inside a path that the planner could not
  keep on the requested climb/conventional hand because remaining material
  switches sides. They are cut at the measured engagement feed; the colour is
  a review aid, and the warning text still appears.
- **Collision** (magenta): moves named by a `Line N:` stock finding — rapid or
  spindle-off contact with current material, unclassified feed contact,
  motion below the blank bottom or an entry deeper than the tool's depth per
  pass. Setup-level findings (unallocated stock, safe Z, part containment)
  have no single move and are not coloured.

Colouring does not alter the G-code. A program with coloured moves must be
corrected, not exported with the warning confirmed.
