"""Command-line interface for GCodeProducer."""
from __future__ import annotations


import argparse, sys, gcodeproducer.core.libraries.defaults as defaults, gcodeproducer.core.plugins.discovery as plugins, gcodeproducer.core.workflows.validation as wf
from pathlib import Path
from gcodeproducer import __version__
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.pipeline.engine import parse_stage_spec
from gcodeproducer.core.libraries.libraries_constants import KINDS
from gcodeproducer.core.libraries.library_set import LibrarySet
from gcodeproducer.core.jobs.session import build_job, load_mesh, slice_job


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


def cmd_processes(args):
    ls = _libset(args)
    for p in ls.processes.all(args.workflow or None):
        steps = [s["stage"] for s in p.pipeline.get("steps", []) if s.get("enabled", True)]
        print(f"{p.id:24} [{wf.short(p.workflow)}]  {p.name}")
        if args.verbose:
            print("    " + " -> ".join(steps))


def _preferences(args, root):
    import gcodeproducer.core.settings.preferences as app_settings
    prefs = app_settings.load(root)
    for item in getattr(args, "pref", []) or []:
        if "=" not in item:
            raise SystemExit(f"--pref expects KEY=VALUE, got '{item}'")
        key, value = item.split("=", 1)
        known = [p.name for p in app_settings.SCHEMA]      # GUI pop-up switches are not CLI settings
        if key not in known:
            raise SystemExit(f"Unknown setting '{key}'. Known: {', '.join(known)}")
        prefs[key] = value.lower() in ("1", "true", "yes", "on") if isinstance(app_settings.DEFAULTS[key], bool) else value
    return app_settings.validated(prefs)


def cmd_settings(args):
    import gcodeproducer.core.settings.preferences as app_settings
    from gcodeproducer.core.libraries.schemas import default_root
    prefs = app_settings.load(default_root())
    for p in app_settings.SCHEMA:
        print(f"{p.name} = {prefs[p.name]!r}  ({p.label}; default {p.default!r})")
    return 0


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

    from gcodeproducer.core.jobs.placement import Placement
    mesh = load_mesh(args.input)
    placement = Placement(x=args.x, y=args.y, z=args.z, scale=args.scale,
                          z_anchor="top" if workflow == wf.CAM else "bottom")
    for axis in ("x", "y", "z"):
        deg = getattr(args, f"rotate_{axis}")
        if deg:
            placement.rotate_by(axis, deg)
    if args.lay_flat:
        placement.lay_flat(mesh)
    blocks = []
    if args.support_blocks:
        import json
        from gcodeproducer.core.fdm.support_block import SupportBlock
        with open(args.support_blocks, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        blocks = [SupportBlock.from_dict(b) for b in (data.get("blocks", []) if isinstance(data, dict) else data)]
    from gcodeproducer.core.fdm.model_support import ModelSupport
    model_support = ModelSupport(mode=args.support, overhang_angle=args.overhang_angle,
                                 extend=args.support_extend, fill_holes=args.fill_holes)
    job = build_job(workflow, machine, material=material, nozzle=nozzle, tools=tools,
                    mesh=mesh, model_path=args.input, placement=placement, support_blocks=blocks,
                    support=model_support,
                    settings={**({"layer_height": args.layer_height} if args.layer_height else {}),
                              **({"machining_material": args.cam_material} if args.cam_material else {})},
                    preferences=_preferences(args, ls.root))

    if args.config:
        pipeline = SlicePipeline.load(args.config)
    elif args.process:
        preset = None
        for p in ls.processes.all(workflow):
            if p.id == args.process or p.name.lower() == args.process.lower():
                preset = p
                break
        if preset is None:
            raise SystemExit(f"process '{args.process}' not found for {workflow}. "
                             f"Have: {', '.join(p.name for p in ls.processes.all(workflow))}")
        pipeline = preset.slice_pipeline()
    else:
        pipeline = SlicePipeline.default(workflow)
    for spec in args.stage_param or []:
        step = parse_stage_spec(spec)
        target = pipeline.step(step.stage)
        if target is None:
            raise SystemExit(f"stage '{step.stage}' is not in this process "
                             f"(have: {', '.join(s.stage for s in pipeline.steps)})")
        merged = {**target.params, **step.params}
        plugins.stages.get(step.stage).resolve(merged, strict=True)   # report typos
        target.params = merged
        target.enabled = True            # overriding a stage switches it on (e.g. supports)

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
    from gcodeproducer.core.cam.cam_constants import MATERIALS
    s.add_argument("--cam-material",choices=[m[0] for m in MATERIALS],
                   help="machining category for automatic CAM tool SFM/chip-load calculation")
    s.add_argument("--pref", action="append", default=[], metavar="KEY=VALUE",
                   help="override a global setting (see 'settings' command) for this run only")
    s.add_argument("--layer-height", type=float)
    g = s.add_argument_group("placement")
    g.add_argument("--x", type=float, help="model centre X on the bed (default: bed centre)")
    g.add_argument("--y", type=float, help="model centre Y on the bed (default: bed centre)")
    g.add_argument("--z", type=float, default=0.0, help="FDM: bottom above bed; CAM: model top Z (default 0, body below surface)")
    g.add_argument("--rotate-x", type=float, default=0.0, metavar="DEG")
    g.add_argument("--rotate-y", type=float, default=0.0, metavar="DEG")
    g.add_argument("--rotate-z", type=float, default=0.0, metavar="DEG")
    g.add_argument("--scale", type=float, default=100.0, metavar="PCT")
    g.add_argument("--lay-flat", action="store_true", help="rest the largest flat face on the bed")
    g = s.add_argument_group("support (per model)")
    g.add_argument("--support", choices=["none", "buildplate", "everywhere", "blocks"], default="none",
                   help="where support goes (default: none)")
    g.add_argument("--overhang-angle", type=float, default=50.0, metavar="DEG",
                   help="overhangs steeper than this (from vertical) get support")
    g.add_argument("--support-extend", type=float, default=1.0, metavar="MM",
                   help="how far support reaches past the model's edges")
    g.add_argument("--fill-holes", type=float, default=0.0, metavar="MM2",
                   help="support right across holes up to this area (0 = off)")
    g.add_argument("--support-blocks", metavar="JSON",
                   help="manual support blocks (list of {x0,y0,z0,x1,y1,z1}, bed coordinates); "
                        "use with --support blocks")
    s.add_argument("-m", "--stage-param", action="append",
                   help="stage_id:key=value,... override")
    s.add_argument("--process", help="named process preset (workflow options)")
    s.add_argument("--config", help="pipeline JSON (overrides --process)")
    s.add_argument("--library"); s.add_argument("--no-seed", action="store_true")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(func=cmd_slice)

    sub.add_parser("settings", help="show global settings and their defaults").set_defaults(func=cmd_settings)
    s = sub.add_parser("processes", help="list saved process presets (workflow options)")
    s.add_argument("-w", "--workflow"); s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--library"); s.add_argument("--no-seed", action="store_true")
    s.set_defaults(func=cmd_processes)
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
