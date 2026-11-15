# GCodeProducer

Python/PyQt6 application that produces **FDM and 2.5D CAM G-code from STL models**,
with a desktop interface and command-line tools. Based on shared components from
[GCodeTools](../GCodeTools).

**Early software:** the geometry kernel is minimal. CAM checks are advisory,
not a full stock-removal, holder, or fixture simulation. Independently verify
output before operating a machine.

## Features

- **Prepare and Preview:** shared camera and machine dimensions, model placement,
  rotation/scaling, layer inspection, feature colours, and linked G-code selection.
- **FDM:** walls, top/bottom shells, sparse infill, skirt/brim, automatic support,
  editable support blocks, and reusable process presets.
- **CAM:** ordered tool-change trees with Pocket, Profile, Drill, and Engrave
  operations; face/edge selection and geometry-linked depths.
- **CAM stock:** editable material/blank properties, margin-based Auto allocation,
  top-at-Z0 placement, and conservative stock-contact warnings.
- **Libraries:** separate machines, FDM materials/nozzles, and CAM tools.
- **Custom G-code:** multi-line start/end templates, reset, variable insertion,
  expressions, conditionals, validation, and example preview.
- **Background computation:** slicing, CAM selection/path generation, and support
  auto-generation run outside the UI process.
- **Extensible:** declarative settings, workflow-specific stages, importer plugins,
  and a CLI.

## Run

Requires **Python 3.10+** and an OpenGL-capable desktop for the GUI.

```bash
python -m pip install -e .
python -m gcodeproducer gui
```

On Windows, you can also launch `GCodeProducer.bat`.
For setup and first-job instructions, see [Getting started](docs/getting-started.md).

## Documentation

**[Open the documentation index →](docs/README.md)**

All detailed instructions live in the **`docs/` folder**. Follow the links on
GitHub, or open `docs/README.md` in a Markdown viewer/editor locally. No website
build or network connection is required to read the local files.

| Topic | Guide |
|---|---|
| Interface, placement, preview, shortcuts | [Using the GUI](docs/gui.md) |
| Libraries, settings ownership, saved state | [Profiles and persistence](docs/profiles-and-state.md) |
| FDM processes and settings | [FDM guide](docs/fdm/README.md) |
| CAM tools, operations, selections, depths | [CAM guide](docs/cam/README.md) |
| Stock allocation and collision-check limits | [Stock and safety](docs/cam/stock-and-safety.md) |
| Start/end G-code and variables | [Templates](docs/gcode-templates.md) |
| Commands and examples | [CLI](docs/cli.md) |
| Exact defaults, ranges, and choices | [Settings reference](docs/reference/README.md) |
| Problems and current limitations | [Troubleshooting](docs/troubleshooting.md) |
| Architecture, plugins, documentation maintenance | [Development](docs/development.md) |

## License

[GPL-3.0-or-later](LICENSE). Uses PyQt6 (GPL v3).
