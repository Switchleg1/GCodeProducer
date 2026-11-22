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
from gcodeproducer.core.fdm.layer_order import order_layer
from gcodeproducer.core.fdm.path_order import closed_loop, ordered_paths
from gcodeproducer.core.fdm.wall_regions import slice_region
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.fdm.travel_router import TravelRouter
from gcodeproducer.core.geometry.decimate import decimate
from gcodeproducer.core.gcode.gcode_constants import MOTION_DEFAULTS
from gcodeproducer.core.gcode.time_estimate import motion_comment
from gcodeproducer.core.settings.preferences import pref
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

    @classmethod
    def resolve(cls, values, strict=False):
        from gcodeproducer.core.parameters.type_conversion import coerce_bool

        values = dict(values or {})
        legacy = {key: values.pop(key) for key in ('retract', 'retract_open_only', 'force_travel_retract')
                  if key in values}
        if legacy and values.get('retraction_mode') is None:
            def flag(key, default):
                value = legacy.get(key)
                return default if value is None else coerce_bool(value)

            if not flag('retract', True):
                values['retraction_mode'] = 'off'
            elif not flag('retract_open_only', False):
                values['retraction_mode'] = 'all'
            else:
                values['retraction_mode'] = 'separate' if flag('force_travel_retract', True) else 'open'
        if 'avoid_open_spaces' in values:
            enabled = coerce_bool(values.pop('avoid_open_spaces'))
            if not enabled:
                values['travel_detour_time'] = 0.
            elif values.get('travel_detour_time') is None:
                values['travel_detour_time'] = 0.1  # default budget before the controls were combined
        return super().resolve(values, strict=strict)

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
        detour = travel * params["travel_detour_time"]
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
        motion = {"print_acceleration": job.m("print_acceleration", MOTION_DEFAULTS["print_acceleration"]),
                  "travel_acceleration": job.m("travel_acceleration", 0.),
                  "junction_deviation": job.m("junction_deviation", MOTION_DEFAULTS["junction_deviation"])}
        self._start_gcode(b, job, temps, params, log=ctx.log)
        b.comment(motion_comment(motion))      # read back by the time estimate
        b.relative_e = rel_e
        b.reset_e()
        bridge = job.material.resolved() if job.material is not None else {}
        bridge_speed = (bridge.get('bridge_speed', 25.) if bridge.get('bridge_speed_mode') != 'modifier'
                        else params['solid_infill_speed'] * bridge['bridge_speed_modifier']/100.)
        configured_fan = job.mat('fan_speed', 100.) or 0.
        bridge_fan = (bridge.get('bridge_cooling', 100.) if bridge.get('bridge_cooling_mode') != 'modifier'
                      else configured_fan * bridge['bridge_cooling_modifier']/100.)
        bridge_pwm = round(255 * min(100., max(0., bridge_fan))/100.)
        normal_pwm = 0
        for line in b.lines:
            if line.cmd == 'M106':
                normal_pwm = line.params.get('S', 255)
            elif line.cmd == 'M107':
                normal_pwm = 0

        n = max(1, len(job.layers))
        detours = fallbacks = outside = bridges = 0
        route_or_classify = detour > 0 or (params['retraction_mode'] in ('open', 'separate') and retract_len > 0)
        simplification = pref(job, 'fdm_travel_simplification')
        min_segment = pref(job, 'fdm_min_segment_length')
        deviation = pref(job, 'fdm_max_deviation')
        for li, layer in enumerate(job.layers):
            b.new_layer(layer.index, layer.z)
            if layer.index == 1:
                self._layer_temperatures(b, temps)
            cooling = self._cooling(b, job, layer)
            if cooling is not None:
                normal_pwm = cooling
            active_pwm = normal_pwm
            h = flh if layer.index == 0 else lh
            first = layer.index == 0
            router = (TravelRouter(layer.outline, b.dx, simplification=simplification)
                      if route_or_classify else None)
            mixed = job.settings.get("optimize_mixed_infill", True)
            if params["travel_order"]:
                islands = router.islands if router is not None else list(polygons(slice_region(layer.outline)))
                paths = order_layer(layer.paths, (b.x, b.y), islands, params["seam"],
                                    (params["seam_x"], params["seam_y"]), mixed)
            else:
                paths = ordered_paths(layer.paths, lambda: (b.x, b.y)) if mixed else layer.paths
            for path in paths:
                pts, widths = decimate(np.asarray(path.points, float), path.closed, min_segment, deviation,
                                       path.widths)
                if len(pts) < 2:
                    continue
                width = path.width or job.line_width
                epm = extrusion_per_mm(width, h, fil, flow)
                if widths is not None:
                    # Per-segment flow relative to the nominal bead; feed caps use the widest bead.
                    widths = np.asarray(widths, float)
                    scale = np.array([extrusion_per_mm(float(w), h, fil, flow) for w in widths]) / epm
                    epm *= float(scale.max())
                    scale /= scale.max()
                else:
                    scale = None
                b.set_feature(path.feature)
                is_bridge = path.feature == 'bridge'
                target_pwm = bridge_pwm if is_bridge else normal_pwm
                if target_pwm != active_pwm:
                    self._fan(b, target_pwm)
                    active_pwm = target_pwm
                if is_bridge:
                    requested = bridge_speed
                    epm *= bridge.get('bridge_flow', 100.)/100.
                elif first:
                    requested = params["first_layer_speed"]
                else:
                    requested = path.speed or params[_FEATURE_SPEED.get(path.feature, "print_speed")]
                feed = print_feed("first layer" if first else path.feature, requested, epm)
                self._print_path(b, path, pts, epm, feed, travel_f, params,
                                 retract_len, retract_spd, zhop, router, detour, scale)
            if active_pwm != normal_pwm:
                self._fan(b, normal_pwm)
            if router is not None:
                detours += router.detours
                fallbacks += router.fallbacks
                outside += router.outside
                bridges += router.bridges
            ctx.progress((li + 1) / n)

        if detour > 0:
            ctx.log(f"  avoid open spaces: {detours} same-island detours, {bridges} shortened island crossings, "
                    f"{fallbacks} unresolved same-island crossings, {outside} other open transitions")
        self._end_gcode(b, job, temps, log=ctx.log)
        for msg in caps.values():
            ctx.log(f"  speed capped: {msg}")
        job.program = b.program(path=None)
        job.program.machine = "fdm"
        job.program.motion = motion
        job.program.layer_z = [l.z for l in job.layers]
        moves = sum(1 for ln in job.program.lines if ln.cmd in ("G0", "G1"))
        extra = f", {len(caps)} speed cap(s)" if caps else ""
        return f"{len(job.program.lines)} lines, {moves} moves, {len(job.layers)} layers{extra}"

    def _print_path(self, b, path, pts, epm, feed, travel_f, params,
                    rlen, rspd, zhop, router=None, detour=0., scale=None):
        """Print one path; ``scale`` optionally holds per-vertex flow factors (variable width)."""
        head = np.array([b.x, b.y])
        if path.closed:
            seam = params["seam"]
            if path.feature in WALL_FEATURES and seam != "origin":
                target = np.array([params["seam_x"], params["seam_y"]]) if seam == "xy" else head
                if scale is None:
                    pts = closed_loop(pts, target)
                else:
                    pts, scale = closed_loop(pts, target, scale)
            elif seam != "origin":
                # Do not aim skirt or support seams at the perimeter XY target.
                s = int(np.argmin(((pts - head)**2).sum(axis=1)))
                pts = np.roll(pts, -s, axis=0)
                if scale is not None:
                    scale = np.roll(scale, -s)
            loop = np.vstack([pts, pts[0]])
            if scale is not None:
                scale = np.append(scale, scale[0])
        else:
            loop = pts
            # orient so we start from the closer end
            if ((loop[-1] - head)**2).sum() < ((loop[0] - head)**2).sum():
                loop = loop[::-1]
                if scale is not None:
                    scale = scale[::-1]
        # flow of each segment (k -> k+1)
        seg_epm = [epm]*(len(loop)-1) if scale is None else (epm*(scale[:-1]+scale[1:])/2).tolist()

        start = loop[0]
        route = router.route(head, start, detour) if router is not None else [start]
        dist = sum(math.dist(a, q) for a, q in zip([head, *route], route))
        do_retract = False
        mode = params['retraction_mode']
        if mode != 'off' and rlen > 0 and dist > 1e-9:
            inside = mode in ('open', 'separate') and router is not None and not router.crosses_open(head, route)
            if inside:
                do_retract = mode == 'separate' and dist >= params['inside_travel_retract']
            else:
                do_retract = dist >= params['min_travel_retract']
        if do_retract:
            b.retract(rlen, rspd, zhop)
        for q in route:
            # Even a one-unit change in the last decimal can matter at a wall.
            b.travel(float(q[0]), float(q[1]), feed=travel_f, force_xy=len(route) > 1)
        if do_retract:
            b.unretract(rlen, rspd, zhop)
        coast = 0. if path.feature == 'bridge' else params.get('coast_length', 0.)
        if coast > 0:
            lengths = np.linalg.norm(np.diff(loop, axis=0), axis=1)
            tail = np.cumsum(lengths[::-1])
            # Leave at least one position increment of extrusion. Very short
            # paths keep their normal extrusion instead of coasting entirely.
            if tail[-1] - coast > 10**-b.dx and coast >= 10**-b.dx:
                reverse_index = int(tail.searchsorted(coast))
                i = len(lengths) - 1 - reverse_index
                remaining = coast - (tail[reverse_index-1] if reverse_index else 0.)
                split = loop[i+1] + (remaining/lengths[i])*(loop[i]-loop[i+1])
                for k, q in enumerate(loop[1:i+1]):
                    b.extrude_to(float(q[0]), float(q[1]), seg_epm[k], feed=feed)
                if math.dist(split, loop[i]) > 1e-9:
                    b.extrude_to(float(split[0]), float(split[1]), seg_epm[i], feed=feed)
                for q in loop[i+1:]:
                    b.coast_to(float(q[0]), float(q[1]), feed=feed)
                return
        for k, q in enumerate(loop[1:]):
            b.extrude_to(float(q[0]), float(q[1]), seg_epm[k], feed=feed)

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
            pwm = round(255 * fan / 100.)
            b.command(f"M106 S{pwm}", "fan on")
            return pwm
        return None

    @staticmethod
    def _fan(b, pwm):
        b.command(f'M106 S{pwm:g}' if pwm else 'M107', 'bridge cooling transition')

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
