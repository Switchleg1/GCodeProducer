"""Plugin discovery for slice stages and geometry importers.

Built-ins live in ``gcodeproducer.stages`` and ``gcodeproducer.importers``.
Extra plugins are ``.py`` files in ``<repo>/plugins``, ``~/.gcodeproducer/plugins``
or any directory in the ``GCODEPRODUCER_PLUGINS`` env var.  Any ``SliceStage`` /
``Importer`` subclass with a non-empty ``id`` is registered automatically.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import pkgutil
import sys
import traceback
from pathlib import Path

_loaded = False
_errors: list = []


class Registry:
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict = {}

    def register(self, cls):
        if not getattr(cls, "id", ""):
            raise ValueError(f"{cls!r} has no id")
        self._validate(cls)
        self._items[cls.id] = cls
        return cls

    def _validate(self, cls):
        if self.kind == "stage":
            from . import workflow as wf
            wfs = getattr(cls, "workflows", ()) or ()
            if not wfs:
                raise ValueError(f"stage '{cls.id}' must declare workflows, e.g. workflows=(FDM,)")
            cls.workflows = wf.normalize_all(wfs)

    def get(self, id_: str):
        ensure_loaded()
        try:
            return self._items[id_]
        except KeyError:
            raise KeyError(f"unknown {self.kind} '{id_}'. Available: {', '.join(sorted(self._items))}") from None

    def all(self) -> list:
        ensure_loaded()
        return list(self._items.values())

    def ids(self) -> list:
        return [c.id for c in self.all()]


stages = Registry("stage")
importers = Registry("importer")


def _scan(mod) -> None:
    from ..stages.base import SliceStage
    from ..importers.base import Importer
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
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        try:
            _scan(importlib.import_module(f"{pkg_name}.{info.name}"))
        except Exception:
            _errors.append(f"{pkg_name}.{info.name}: {traceback.format_exc()}")


def plugin_dirs() -> list:
    dirs = [Path(__file__).resolve().parents[2] / "plugins", Path.home() / ".gcodeproducer" / "plugins"]
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
