# Repository instructions

## Versioning

The operator uses `major.minor.build`. Increment the build
component once on each subsequent user-request turn in this project, keeping `pyproject.toml` and `gcodeproducer/__init__.py` in sync. Change minor or
major only when the operator explicitly requests it. Regenerate documentation
with `python tools/generate_reference.py` after a version change.

## Architecture and validation

- Keep one class per Python file and subsystem tables/constants in the local
  `<directory>_constants.py`. Preserve compatibility facades.
- Model placement, support, CAM setup/stock/tabs/references are model-owned;
  process presets must not change them.
- Keep expensive geometry/picking in the spawned compute process.
- Isolate `GCODEPRODUCER_LIBRARY` and `GCODEPRODUCER_SETTINGS` in tests/captures;
  never alter the operator's actual library or settings.
- Update relevant offline guides for user-visible changes. Run generated-reference
  checks, pytest and `git diff --check` before finishing.
