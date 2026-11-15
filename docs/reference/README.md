[Documentation index](../README.md)

# Settings reference

These pages are generated from the live built-in schemas and variable registry:

- [Stage settings](stage-settings.md): key, label, type, units, defaults,
  bounds, choices, auto support, stage workflow and optional/core status.
- [Profile settings](profile-settings.md): FDM/CAM machine, FDM material,
  nozzle, and CAM tool fields.
- [Template variables](template-variables.md): every registered variable,
  workflow, description and example value.
- [Default start/end templates](default-templates.md): literal FDM and CAM
  defaults used by Reset and by blank boxes.

## How to use this reference

A **default** is a schema starting value, not a measured machine capability or
an effective job result. A preset/profile may override it, `auto` may resolve
from another setting, a model may supply independent state, and the FDM
emitter may cap a requested value. A numeric range describes accepted input,
not necessarily a safe range for your equipment.

A field's presence in a schema also does not guarantee that it affects output.
Read [implemented versus descriptive settings](../profiles-and-state.md#implemented-versus-descriptive-settings).
In particular, CAM tree operation settings are **not** the legacy
`cam_profile` stage parameters: use the [operation reference](../cam/operations.md).
Stock/model fields are described in [stock](../cam/stock-and-safety.md),
[depths](../cam/selection-and-depths.md), and [support](../fdm/support.md).

## Regenerate

From the repository root:

```bash
python tools/generate_reference.py
python tools/generate_reference.py --check
```

The generator does not load your profile library, run a Qt application, or
execute external plugins. It documents built-ins only. Generated files are
checked in for offline reading; tests detect when they no longer match code.
