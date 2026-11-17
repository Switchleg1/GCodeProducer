"""FDM stage: write the G-code (the *Speed & travel* settings of the process).

Walks the layers in order, printing the paths with travels, retraction,
temperatures, fan and chamber control.

Who sets what:

* **process** (this stage): the *requested* speeds per feature, travel speed,
  acceleration, retraction behaviour and seams;
* **machine**: the *limits* - max print / travel speed, max acceleration, max
  volumetric flow, max nozzle / bed / chamber temperature, heated chamber;
* **material**: temperatures (nozzle, bed, chamber), flow, cooling, retraction
  length / speed;
* **nozzle**: line width and its volumetric flow limit.

Requested values above a limit are capped and the cap is reported in the log.
"""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMEMIT_PARAMS, _FEATURE_SPEED
import math, numpy as np
from gcodeproducer.core.fdm.fdm_constants import WALL_FEATURES
from gcodeproducer.core.fdm.path_order import closed_loop, ordered_paths
from gcodeproducer.core.fdm.travel_router import TravelRouter
from gcodeproducer.core.gcode.builder import GCodeBuilder, extrusion_per_mm
from gcodeproducer.stages.base.api import FDM
from gcodeproducer.stages.base.slice_stage import SliceStage

#: feature -> process speed parameter


class FDMEmit(SliceStage):
    id = "fdm_emit"
    name = "Speed & travel"
    description = ("Requested print speeds, travel and retraction; writes the G-code. The machine's limits "
                   "(max speed, acceleration, flow, temperatures) cap these values.")
    workflows = (FDM,)
    optional = False
    category = "Output"
    params = FDMEMIT_PARAMS

    def run(self, job, params, ctx):
        rel_e = bool(job.m("relative_e", True))
        b = GCodeBuilder(relative_e=rel_e)
        fil = job.mat("filament_diameter", 1.75) or 1.75
        fil_area = math.pi * (fil / 2) ** 2
        flow = (job.mat("flow", 100.0) or 100.0) / 100.0
        lh = job.settings.get("layer_height", job.layer_height)
        flh = job.settings.get("first_layer_height", lh)

        caps: dict = {}                      # what was limited, for the log
        max_print = job.m("max_print_speed", 0) or math.inf
        max_travel = job.m("max_travel_speed", 0) or math.inf
        flow_limits = [v for v in (job.noz("max_flow", 0), job.m("max_flow", 0)) if v and v > 0]
        max_flow = min(flow_limits) if flow_limits else math.inf

        travel = params["travel_speed"]
        if travel > max_travel:
            caps["travel"] = f"travel {travel:g} \u2192 {max_travel:g} mm/s (machine max travel speed)"
            travel = max_travel
        travel_f = travel * 60.0
        detour = travel * params["travel_detour_time"] if params["avoid_open_spaces"] else 0.
        retract_len = job.mat("retract_length", 0.0) or 0.0
        retract_spd = job.mat("retract_speed", 35) or 35
        zhop = job.mat("zhop", 0.0) or 0.0

        def print_feed(feature, requested, epm):
            """Requested speed capped by the machine max speed and the volumetric flow limit (mm/min)."""
            spd = requested
            if spd > max_print:
                caps.setdefault(feature, f"{feature} {requested:g} \u2192 {max_print:g} mm/s "
                                          f"(machine max print speed)")
                spd = max_print
            if max_flow < math.inf and epm > 0:
                flow_cap = max_flow / (epm * fil_area)     # mm/s at which the bead needs max_flow mm3/s
                if spd > flow_cap:
                    caps.setdefault(feature + "/flow", f"{feature} {spd:g} \u2192 {flow_cap:.1f} mm/s "
                                                       f"(max flow {max_flow:g} mm\u00b3/s)")
                    spd = flow_cap
            return spd * 60.0

        temps = self._temperatures(job, ctx)
        self._start_gcode(b, job, temps, params, log=ctx.log)
        b.relative_e = rel_e
        b.reset_e()

        n = max(1, len(job.layers))
        detours = fallbacks = 0
        for li, layer in enumerate(job.layers):
            b.new_layer(layer.index, layer.z)
            if layer.index == 1:
                self._layer_temperatures(b, temps)
            self._cooling(b, job, layer)
            h = flh if layer.index == 0 else lh
            first = layer.index == 0
            router = TravelRouter(layer.outline, b.dx) if detour > 0 and layer.outline else None
            paths = (ordered_paths(layer.paths, lambda: (b.x, b.y))
                     if job.settings.get("optimize_mixed_infill", True) else layer.paths)
            for path in paths:
                pts = np.asarray(path.points, float)
                if len(pts) < 2:
                    continue
                width = path.width or job.line_width
                epm = extrusion_per_mm(width, h, fil, flow)
                b.set_feature(path.feature)
                if first:
                    requested = params["first_layer_speed"]
                else:
                    requested = path.speed or params[_FEATURE_SPEED.get(path.feature, "print_speed")]
                feed = print_feed("first layer" if first else path.feature, requested, epm)
                self._print_path(b, path, pts, epm, feed, travel_f, params,
                                 retract_len, retract_spd, zhop, router, detour)
            if router is not None:
                detours += router.detours
                fallbacks += router.fallbacks
            ctx.progress((li + 1) / n)

        if detour > 0:
            ctx.log(f"  avoid open spaces: {detours} detours, {fallbacks} direct fallbacks "
                    "(no same-island route found within budget)")
        self._end_gcode(b, job, temps, log=ctx.log)
        for msg in caps.values():
            ctx.log(f"  speed capped: {msg}")
        job.program = b.program(path=None)
        job.program.machine = "fdm"
        job.program.layer_z = [l.z for l in job.layers]
        moves = sum(1 for ln in job.program.lines if ln.cmd in ("G0", "G1"))
        extra = f", {len(caps)} speed cap(s)" if caps else ""
        return f"{len(job.program.lines)} lines, {moves} moves, {len(job.layers)} layers{extra}"

    def _print_path(self, b, path, pts, epm, feed, travel_f, params,
                    rlen, rspd, zhop, router=None, detour=0.):
        head = np.array([b.x, b.y])
        if path.closed:
            seam = params["seam"]
            if path.feature in WALL_FEATURES and seam != "origin":
                target = np.array([params["seam_x"], params["seam_y"]]) if seam == "xy" else head
                pts = closed_loop(pts, target)
            elif seam != "origin":
                # Do not aim skirt or support seams at the perimeter XY target.
                s = int(np.argmin(((pts - head)**2).sum(axis=1)))
                pts = np.roll(pts, -s, axis=0)
            loop = np.vstack([pts, pts[0]])
        else:
            loop = pts
            # orient so we start from the closer end
            if ((loop[-1] - head)**2).sum() < ((loop[0] - head)**2).sum():
                loop = loop[::-1]

        start = loop[0]
        route = router.route(head, start, detour) if router is not None else [start]
        dist = sum(math.dist(a, q) for a, q in zip([head, *route], route))
        do_retract = params["retract"] and rlen > 0 and dist >= params["min_travel_retract"]
        if do_retract:
            b.retract(rlen, rspd, zhop)
        for q in route:
            b.travel(float(q[0]), float(q[1]), feed=travel_f)
        if do_retract:
            b.unretract(rlen, rspd, zhop)
        for q in loop[1:]:
            b.extrude_to(float(q[0]), float(q[1]), epm, feed=feed)

    # ------------------------------------------------------------------ temperatures
    @staticmethod
    def _temperatures(job, ctx) -> dict:
        """Material temperatures capped at the machine's limits (with log messages)."""
        def cap(name, value, limit_key, default_limit):
            limit = job.m(limit_key, default_limit)
            if limit and value > limit:
                ctx.log(f"  temperature capped: {name} {value:g} \u2192 {limit:g} \u00b0C (machine {limit_key})")
                return float(limit)
            return float(value)

        tn = job.mat("temp_nozzle", 200) or 0
        tnf = job.mat("temp_nozzle_first", tn) or tn
        tb = job.mat("temp_bed", 60) or 0
        tbf = job.mat("temp_bed_first", tb) or tb
        t = {"nozzle": cap("nozzle", tn, "max_nozzle_temp", 0),
             "nozzle_first": cap("first layer nozzle", tnf, "max_nozzle_temp", 0),
             "bed": cap("bed", tb, "max_bed_temp", 0),
             "bed_first": cap("first layer bed", tbf, "max_bed_temp", 0),
             "chamber": 0.0, "wait_chamber": False}
        tc = job.mat("temp_chamber", 0) or 0
        if tc > 0:
            if job.m("heated_chamber", False):
                t["chamber"] = cap("chamber", tc, "max_chamber_temp", 0)
                t["wait_chamber"] = bool(job.m("wait_for_chamber", False))
            else:
                ctx.log(f"  material wants a {tc:g} \u00b0C chamber but the machine has no heated chamber "
                        f"- ignored")
        return t

    @staticmethod
    def _layer_temperatures(b, t):
        """After the first layer: switch to the normal temperatures (no waiting)."""
        if t["nozzle"] != t["nozzle_first"]:
            b.command(f"M104 S{_i(t['nozzle'])}", "nozzle temperature")
        if t["bed"] != t["bed_first"]:
            b.command(f"M140 S{_i(t['bed'])}", "bed temperature")

    def _cooling(self, b, job, layer):
        fan_off = job.mat("fan_first_layers", 1) or 0
        fan = job.mat("fan_speed", 100.0) or 0.0
        if layer.index == fan_off:
            b.command(f"M106 S{int(round(255 * fan / 100.0))}", "fan on")

    def _start_gcode(self, b, job, t, params, log=None):
        """The machine's start G-code template (or the default), filled from the job's variables."""
        from gcodeproducer.core.gcode.variables import render_box
        b.comment(f"GCodeProducer FDM - {job.machine.name}")
        text = render_box(job, "start_gcode", temps=t, log=log)
        if t["chamber"] > 0 and not any(k in text.upper() for k in ("M141", "M191")) and log:
            log("  start G-code does not set the chamber (M141) although the material asks for "
                f"{t['chamber']:g} \u00b0C - use {{chamber_temp}} in the machine's start G-code")
        b.raw(text.rstrip("\n"))
        accel = params.get("acceleration", 0) or 0
        if accel > 0:
            max_acc = job.m("max_acceleration", 0) or 0
            if max_acc and accel > max_acc:
                accel = max_acc
            if accel > 0:
                b.command(f"M204 S{_i(accel)}", "acceleration")
        b.command("M83" if job.m("relative_e", True) else "M82")

    def _end_gcode(self, b, job, t, log=None):
        from gcodeproducer.core.gcode.variables import render_box
        b.set_feature("end", comment=False)
        last = job.layers[-1] if job.layers else None
        extra = {"layer": len(job.layers), "layer_z": float(last.z), "current_layer_height": float(last.height)} \
            if last is not None else None
        b.raw(render_box(job, "end_gcode", temps=t, extra=extra, log=log).rstrip("\n"))


def _i(v) -> int:
    try:
        return int(round(float(v)))
    except Exception:
        return 0
