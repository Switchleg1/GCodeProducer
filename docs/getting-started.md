[Documentation index](README.md)

# Installation and first jobs

## Requirements

- Python **3.10 or later**; use the same Python interpreter for installation and launching.
- PyQt6 >= 6.5, PyOpenGL >= 3.1, NumPy >= 1.24 and Shapely >= 2.0
  (installed as dependencies; Shapely supplies CAM pocket offsets).
- A desktop session and functioning OpenGL driver for the 3D GUI. The CLI
  does not need a visible Qt window.
- An STL model; one model is processed at a time. Binary and ASCII STL are supported.
- A controller-compatible machine setup. Starter machine profiles and default
  G-code templates are examples, not verified configurations for your hardware.

## Install from a checkout

Run commands from the repository root. A virtual environment is recommended:

```bash
python -m venv .venv
```

Activate it using `.venv\Scripts\activate` in Windows Command Prompt,
`.venv\Scripts\Activate.ps1` in PowerShell, or `source .venv/bin/activate`
in a POSIX shell. Then:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

Alternatively, install runtime requirements with
`python -m pip install -r requirements.txt` and launch from the checkout.
For tests, install the optional development dependencies with
`python -m pip install -e ".[dev]"`.

## Launch

```bash
python -m gcodeproducer gui
python -m gcodeproducer gui examples/cube20.stl
```

On Windows, `GCodeProducer.bat` is also a launcher. An editable installation
makes `gcodeproducer` and `gcodeproducer-gui` entry points available; the
`python -m` form avoids ambiguity about which Python installation is being used.

The first library load seeds starter profiles into empty libraries. Existing
nonempty libraries are not overwritten or reseeded wholesale. If a starter
profile mentioned in this manual is absent, use your own equivalent or create
one in Libraries. See [data locations](profiles-and-state.md#data-locations).

## First FDM job

1. Choose **FDM** and an appropriate machine. Verify bed dimensions, origin,
   limits, extrusion mode and start/end G-code in **Libraries**.
2. Choose an allowed material and nozzle. Verify filament diameter,
   temperatures, flow and nozzle diameter.
3. Import `examples/cube20.stl`, use **Center**, and confirm the bottom is at Z0.
4. Pick a process preset. For a simple demonstration use 0.2 mm layers, two
   walls, solid top/bottom shells and moderate sparse infill. Do not treat this
   as a calibrated printer profile.
5. Leave **Model → Support: None** for this cube. A support-free cube does not
   exercise support generation.
6. **Slice** (`Ctrl+R`). Review the Log for caps or template problems.
7. In Preview, inspect the first layer, walls, holes if present, solid surfaces,
   travels, temperature commands and shutdown sequence.
8. **Save G-code** only after matching the output to the intended printer.

Continue with [FDM processes](fdm/README.md) and [support](fdm/support.md).

## First CAM job

1. Read [CAM stock and safety](cam/stock-and-safety.md) first.
2. Choose **CAM** and configure the machine's work area, safe Z, available
   tools and controller-specific start/end G-code.
3. Import a simple prismatic STL. The **top defaults to Z0** and the body
   extends in negative Z; X/Y position fields describe the model centre.
4. In **Model → Material / stock** enter the material description, choose the
   **Machining material** (it selects the tool's cutting table) and set the
   density if known. Set a small margin and press **Auto — fit material to
   part**. Confirm dimensions, amber outline and stock bottom Z.
5. In **CAM setup → Tool changes & operations** choose a permitted tool and
   **Add tool change**. Select the tool node, choose **Profile**, and **Add
   operation**.
6. Select a horizontal face or a closed chain of feature edges; each pick
   becomes a row of the operation's selection list. For a first
   inspection-only example, set start to Model top and end to Model top with
   a shallow negative offset. Choose Outside. Depth per pass comes from the
   tool's table for the machining material; tick **Unlock depth of cut** to
   choose a smaller one.
7. Ensure machine safe Z is strictly above the model, stock and operation
   start heights. **Generate paths**.
8. In Preview, step or play through the program with the playback bar
   (Space plays/pauses). Inspect every depth pass, tool number, spindle/feed
   command, entry and retract. Read all warnings in the Messages dock. A lack
   of warnings is not a clearance proof.
9. Independently simulate with your actual controller, work offset, tooling
   and fixtures. Establish offsets and clearance, then air-cut before cutting.

The supplied cube is suitable for learning the interface, not a ready-to-run
machining project. An outside profile through the part needs workholding;
[holding tabs](cam/holding-tabs.md) and [lead-ins](cam/material-state-and-leads.md)
are available but are not a qualified fixturing plan. For sloped or contoured
floors, see [3-axis surface operations](cam/3d-operations.md).

## Updating or troubleshooting

Back up libraries before replacing files or changing profile schemas. Model
state is not embedded in exported process JSON or in the STL. Review
[profiles and persistence](profiles-and-state.md), especially when moving to a
new computer. If the GUI cannot start or geometry looks wrong, use
[troubleshooting](troubleshooting.md).
