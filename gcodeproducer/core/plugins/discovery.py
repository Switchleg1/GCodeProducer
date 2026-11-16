"""Plugin discovery for slice stages and geometry importers.

Built-ins live in ``gcodeproducer.stages`` and ``gcodeproducer.importers``.
Extra plugins are ``.py`` files in ``<repo>/plugins``, ``~/.gcodeproducer/plugins``
or any directory in the ``GCODEPRODUCER_PLUGINS`` env var.  Any ``SliceStage`` /
``Importer`` subclass with a non-empty ``id`` is registered automatically.
"""
from __future__ import annotations

from gcodeproducer.core.plugins.registry import Registry
import importlib, importlib.util, inspect, os, pkgutil, sys, traceback
from pathlib import Path

_loaded = False
_errors: list = []


stages = Registry("stage")
importers = Registry("importer")


def _scan(mod) -> None:
    from gcodeproducer.stages.base.slice_stage import SliceStage
    from gcodeproducer.importers.importer import Importer
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if obj.__module__ != mod.__name__:
            continue
        try:
            if issubclass(obj, SliceStage) and obj is not SliceStage and getattr(obj, "id", ""):
                stages.register(obj)
            elif issubclass(obj, Importer) and obj is not Importer and getattr(obj, "id", ""):
                importers.register(obj)
        except ValueError as exc:
            _errors.append(f"{mod.__name__}: {exc}")


def _load_package(pkg_name: str) -> None:
    pkg = importlib.import_module(pkg_name)
    for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg_name+"."):
        if info.name.rsplit(".",1)[-1].startswith("_"):
            continue
        try:
            _scan(importlib.import_module(info.name))
        except Exception:
            _errors.append(f"{info.name}: {traceback.format_exc()}")


def plugin_dirs() -> list:
    dirs = [Path(__file__).resolve().parents[3] / "plugins", Path.home() / ".gcodeproducer" / "plugins"]
    env = os.environ.get("GCODEPRODUCER_PLUGINS")
    if env:
        dirs += [Path(p) for p in env.split(os.pathsep) if p]
    return dirs


def _load_file(path: Path) -> None:
    name = f"gcodeproducer_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _scan(mod)
    except Exception:
        _errors.append(f"{path}: {traceback.format_exc()}")


def ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    _load_package("gcodeproducer.importers")
    _load_package("gcodeproducer.stages")
    for d in plugin_dirs():
        if d.is_dir():
            for f in sorted(d.glob("*.py")):
                if not f.name.startswith("_"):
                    _load_file(f)


def load_errors() -> list:
    ensure_loaded()
    return list(_errors)
