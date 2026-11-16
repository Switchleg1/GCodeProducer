"""Subsystem boundaries, compatibility exports and shared configuration sources."""
import ast
import importlib
from pathlib import Path

import pytest

from gcodeproducer.core.libraries.defaults import builtin_profiles, builtin_processes
from gcodeproducer.core.libraries.schemas import schema
from tools.generate_reference import STAGES

ROOT = Path(__file__).resolve().parents[1] / "gcodeproducer"


def test_one_class_per_python_file():
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert len(classes) <= 1, (path, [node.name for node in classes])


def test_named_module_constants_live_in_local_constants_files():
    for path in ROOT.rglob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            names = [n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)]
            if any(name.lstrip("_").isupper() for name in names):
                assert path.name == path.parent.name + "_constants.py", (path, names)


def test_schema_names_and_defaults_are_consistent():
    lists = [schema(kind, workflow) for kind, workflow in
             (("machine", "fdm"), ("machine", "cam"), ("material", "fdm"), ("nozzle", "fdm"), ("tool", "cam"))]
    lists += [stage.parameters() for stage in STAGES]
    for params in lists:
        assert len({p.name for p in params}) == len(params)
        for param in params:
            assert param.coerce(param.default) == param.default, param.name


def test_stage_parameters_use_local_configuration_tables():
    for stage in STAGES:
        workflow = stage.workflows[0]
        table = importlib.import_module(f"gcodeproducer.stages.{workflow}.{workflow}_constants")
        assert stage.params is getattr(table, stage.__name__.upper() + "_PARAMS")


def test_builtin_tables_create_independent_profiles_and_processes():
    first = builtin_profiles()
    original = first[0].values["bed_x"]
    first[0].values["bed_x"] = -1
    assert builtin_profiles()[0].values["bed_x"] == original
    processes = builtin_processes()
    processes[0].pipeline["steps"][0]["params"]["layer_height"] = 99
    assert builtin_processes()[0].pipeline["steps"][0]["params"]["layer_height"] == .2
    for profile in builtin_profiles():
        profile.resolved()


def test_legacy_public_imports_resolve_to_split_classes():
    routes = {
        "core.cam": ("Reference", "core.cam.reference"),
        "core.geometry": ("Mesh", "core.geometry.mesh"),
        "core.job": ("Job", "core.jobs.job"),
        "core.gcode": ("GCodeProgram", "core.gcode.program"),
        "core.process": ("ProcessLibrary", "core.libraries.process_library"),
        "core.pipeline": ("Step", "core.pipeline.step"),
        "core.profiles": ("Profile", "core.libraries.profile"),
    }
    for old, (name, new) in routes.items():
        assert getattr(importlib.import_module("gcodeproducer." + old), name) is getattr(importlib.import_module("gcodeproducer." + new), name)
    api = importlib.import_module("gcodeproducer.stages.base")
    assert all(hasattr(api, name) for name in api.__all__)


def test_recursive_builtin_discovery_registers_each_implementation_once(monkeypatch):
    from gcodeproducer.core.plugins import discovery
    from gcodeproducer.core.plugins.registry import Registry
    monkeypatch.setattr(discovery, "stages", Registry("stage"))
    monkeypatch.setattr(discovery, "importers", Registry("importer"))
    monkeypatch.setattr(discovery, "_loaded", False)
    monkeypatch.setattr(discovery, "_errors", [])
    monkeypatch.setattr(discovery, "plugin_dirs", lambda: [])
    discovery.ensure_loaded()
    assert not discovery.load_errors()
    assert len(discovery.stages.all()) == len(STAGES)
    for stage in STAGES:
        assert discovery.stages.get(stage.id) is stage
        assert stage.__module__.startswith("gcodeproducer.stages." + stage.workflows[0] + ".")
    assert discovery.importers.get("stl").__module__ == "gcodeproducer.importers.stl_importer"


@pytest.mark.parametrize("value, expected", [("false", False), ("true", True), (None, True)])
def test_settings_boolean_loading_uses_parameter_conversion(value, expected):
    from gcodeproducer.core.settings.preferences import validated
    prefs = validated({"skip_air_cuts": value, "messages": {"cam_warnings": value}})
    assert prefs["skip_air_cuts"] is expected
    assert prefs["messages"]["cam_warnings"] is expected


def test_settings_choices_share_coercion_and_recover_invalid_values():
    from gcodeproducer.core.settings.preferences import validated
    from gcodeproducer.core.settings.settings_constants import DEFAULTS
    assert validated({"default_area_order": "DEPTH"})["default_area_order"] == "depth"
    assert validated({"default_area_order": None})["default_area_order"] == DEFAULTS["default_area_order"]
    assert validated({"default_area_order": "unknown"})["default_area_order"] == DEFAULTS["default_area_order"]
