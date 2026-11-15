"""Command-line interface for GCodeProducer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import defaults, plugins
from .core import workflow as wf
from .core.pipeline import SlicePipeline, parse_stage_spec
from .core.profiles import KINDS, LibrarySet
from .core.session import build_job, load_mesh, slice_job


def _libset(args) -> LibrarySet:
    root = Path(args.library) if getattr(args, "library", None) else None
    ls = LibrarySet(root).load()
    defaults.seed(ls, save=not getattr(args, "no_seed", False))
    return ls


def _pick(lib, ident, kind):
    if ident is None:
        items = lib.all()
        if not items:
            raise SystemExit(f"no {kind} profiles available")
        return items[0]
    for p in lib.all():
        if p.id == ident or p.name.lower() == ident.lower():
            return p
    raise SystemExit(f"{kind} '{ident}' not found. Have: {', '.join(p.name for p in lib.all())}")


# ---------------------------------------------------------------- commands
def cmd_workflows(args):
    for w in wf.ALL:
        print(f"{wf.short(w):4}  {wf.label(w)}   libraries: {', '.join(wf.LIBRARIES[w])}")


def cmd_stages(args):
    for cls in plugins.stages.all():
        if args.workflow and not cls.applies_to(args.workflow):
            continue
        print(f"{cls.id:16} [{cls.target_tag():7}] {cls.name} - {cls.description}")
        if args.verbose:
            for p in cls.parameters():
                print("    " + p.describe())


def cmd_libraries(args):
    ls = _libset(args)
    for kind in KINDS:
        lib = ls[kind]
        print(f"\n{kind.upper()} ({len(lib)}):")
        for p in lib.all():
            tag = f" [{p.workflow}]" if kind == "machine" else ""
            print(f"  {p.id:24}{tag}  {p.name}")


def cmd_describe(args):
    print(plugins.stages.get(args.stage).help_text())


def cmd_slice(args):
    ls = _libset(args)
    workflow = wf.normalize(args.workflow)
    machine = _pick(ls.machines, args.machine, "machine")
    if machine.workflow != workflow:
        raise SystemExit(f"machine '{machine.name}' is {machine.workflow}, not {workflow}")

    material = nozzle = None
    tools = []
    if workflow == wf.FDM:
        material = _pick(ls["material"], args.material, "material")
        nozzle = _pick(ls["nozzle"], args.nozzle, "nozzle")
        for lib, prof in (("material", material), ("nozzle", nozzle)):
            if not machine.allows(lib, prof.id):
                print(f"warning: machine does not list {lib} '{prof.name}'", file=sys.stderr)
    else:
        tools = [_pick(ls["tool"], args.tool, "tool")]

    mesh = load_mesh(args.input)
    job = build_job(workflow, machine, material=material, nozzle=nozzle, tools=tools,
                    mesh=mesh, model_path=args.input,
                    settings={"layer_height": args.layer_height} if args.layer_height else {})

    pipeline = SlicePipeline.load(args.config) if args.config else SlicePipeline.default(workflow)
    for spec in args.stage_param or []:
        step = parse_stage_spec(spec)
        for s in pipeline.steps:
            if s.stage == step.stage:
                s.params.update(step.params)
                break

    log = (lambda m: print(m, file=sys.stderr)) if not args.quiet else None
    result = slice_job(job, pipeline, log=log)
    prog = result.program
    if prog is None:
        raise SystemExit("pipeline produced no program (missing emit stage?)")

    out = args.output or str(Path(args.input).with_suffix(".gcode"))
    prog.save(out)
    print(f"wrote {out}  ({len(prog.lines)} lines, {prog.num_layers} layers)")


def build_parser():
    p = argparse.ArgumentParser(prog="gcodeproducer", description="Produce G-code from geometry.")
    p.add_argument("--version", action="version", version=f"GCodeProducer {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("workflows", help="list workflows").set_defaults(func=cmd_workflows)

    s = sub.add_parser("stages", help="list slice stages")
    s.add_argument("-w", "--workflow")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_stages)

    s = sub.add_parser("describe", help="describe a stage")
    s.add_argument("stage")
    s.set_defaults(func=cmd_describe)

    s = sub.add_parser("libraries", help="list profiles in every library")
    s.add_argument("--library"); s.add_argument("--no-seed", action="store_true")
    s.set_defaults(func=cmd_libraries)

    s = sub.add_parser("slice", help="slice a model into G-code")
    s.add_argument("input")
    s.add_argument("-w", "--workflow", default="fdm")
    s.add_argument("-o", "--output")
    s.add_argument("--machine"); s.add_argument("--material")
    s.add_argument("--nozzle"); s.add_argument("--tool")
    s.add_argument("--layer-height", type=float)
    s.add_argument("-m", "--stage-param", action="append",
                   help="stage_id:key=value,... override")
    s.add_argument("--config", help="pipeline JSON")
    s.add_argument("--library"); s.add_argument("--no-seed", action="store_true")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(func=cmd_slice)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
