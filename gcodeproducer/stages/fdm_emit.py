"""FDM stage 4: emit G-code from the generated toolpaths.

Walks the layers in order, printing perimeters then infill, inserting travels,
retraction, temperatures, fan and layer-time cooling.  Speeds come from the
*machine* profile; temperatures, flow, cooling and retraction from the
*material*; line width and flow limits from the *nozzle*.
"""
from __future__ import annotations

import math

import numpy as np

from ..core.builder import GCodeBuilder, extrusion_per_mm
from .base import FDM, Param, SliceStage

_FEATURE_SPEED = {
    "outer_perimeter": "outer_perimeter_speed",
    "inner_perimeter": "perimeter_speed",
    "infill": "infill_speed",
}


class FDMEmit(SliceStage):
    id = "fdm_emit"
    name = "Emit G-code"
    description = "Turn the toolpaths into G-code with travels, retraction, temperatures and cooling."
    workflows = (FDM,)
    optional = False
    category = "Output"
    params = [
        Param("retract", "bool", True, help="Retract on travels between features."),
        Param("min_travel_retract", "float", 1.5, unit="mm",
              help="Shortest travel that triggers a retraction."),
        Param("seam", "choice", "nearest", choices=["nearest", "origin"],
              help="Where closed loops start."),
    ]

    def run(self, job, params, ctx):
        rel_e = bool(job.m("relative_e", True))
        b = GCodeBuilder(relative_e=rel_e)
        fil = job.mat("filament_diameter", 1.75) or 1.75
        flow = (job.mat("flow", 100.0) or 100.0) / 100.0
        lh = job.settings.get("layer_height", job.layer_height)
        flh = job.settings.get("first_layer_height", lh)

        travel_f = (job.m("travel_speed", 150) or 150) * 60.0
        first_f = (job.m("first_layer_speed", 20) or 20)
        retract_len = job.mat("retract_length", 0.0) or 0.0
        retract_spd = job.mat("retract_speed", 35) or 35
        zhop = job.mat("zhop", 0.0) or 0.0

        self._start_gcode(b, job)
        b.relative_e = rel_e
        b.reset_e()

        n = max(1, len(job.layers))
        for li, layer in enumerate(job.layers):
            b.new_layer(layer.index, layer.z)
            self._cooling(b, job, layer)
            h = flh if layer.index == 0 else lh
            first = layer.index == 0
            for path in layer.paths:
                pts = np.asarray(path.points, float)
                if len(pts) < 2:
                    continue
                width = path.width or job.line_width
                epm = extrusion_per_mm(width, h, fil, flow)
                base = _FEATURE_SPEED.get(path.feature, "print_speed")
                spd = first_f if first else (path.speed or job.m(base, 60))
                feed = spd * 60.0
                self._print_path(b, path, pts, epm, feed, travel_f, params,
                                 retract_len, retract_spd, zhop)
            ctx.progress((li + 1) / n)

        self._end_gcode(b, job)
        job.program = b.program(path=None)
        job.program.machine = "fdm"
        job.program.layer_z = [l.z for l in job.layers]
        moves = sum(1 for ln in job.program.lines if ln.cmd in ("G0", "G1"))
        return f"{len(job.program.lines)} lines, {moves} moves, {len(job.layers)} layers"

    # ------------------------------------------------------------------
    def _print_path(self, b, path, pts, epm, feed, travel_f, params,
                    rlen, rspd, zhop):
        if path.closed:
            # choose a seam point nearest the current head position
            if params["seam"] == "nearest":
                d = ((pts - np.array([b.x, b.y])) ** 2).sum(axis=1)
                s = int(np.argmin(d))
                pts = np.roll(pts, -s, axis=0)
            loop = np.vstack([pts, pts[0]])
        else:
            loop = pts
            # orient so we start from the closer end
            if ((loop[-1] - [b.x, b.y]) ** 2).sum() < ((loop[0] - [b.x, b.y]) ** 2).sum():
                loop = loop[::-1]

        start = loop[0]
        dist = math.hypot(start[0] - b.x, start[1] - b.y)
        do_retract = params["retract"] and rlen > 0 and dist >= params["min_travel_retract"]
        if do_retract:
            b.retract(rlen, rspd, zhop)
        b.travel(float(start[0]), float(start[1]), feed=travel_f)
        if do_retract:
            b.unretract(rlen, rspd, zhop)
        for q in loop[1:]:
            b.extrude_to(float(q[0]), float(q[1]), epm, feed=feed)

    # ------------------------------------------------------------------
    def _cooling(self, b, job, layer):
        fan_off = job.mat("fan_first_layers", 1) or 0
        fan = job.mat("fan_speed", 100.0) or 0.0
        if layer.index == fan_off:
            b.command(f"M106 S{int(round(255 * fan / 100.0))}", "fan on")

    def _start_gcode(self, b, job):
        tn = job.mat("temp_nozzle", 200)
        tnf = job.mat("temp_nozzle_first", tn) or tn
        tb = job.mat("temp_bed", 60)
        tbf = job.mat("temp_bed_first", tb) or tb
        raw = (job.m("start_gcode") or "").strip()
        subs = {"nozzle_temp": tnf, "bed_temp": tbf, "nozzle_temp_layer": tn, "bed_temp_layer": tb,
                "material": (job.material.name if job.material else ""),
                "machine": job.machine.name}
        b.comment(f"GCodeProducer FDM - {job.machine.name}")
        if job.material:
            b.comment(f"material: {job.material.name}  nozzle: {job.nozzle.name if job.nozzle else '?'}")
        if raw:
            try:
                raw = raw.format(**subs)
            except Exception:
                pass
            b.raw(raw)
        else:
            b.command(f"M140 S{_i(tbf)}", "set bed")
            b.command(f"M104 S{_i(tnf)}", "set nozzle")
            b.command(f"M190 S{_i(tbf)}", "wait bed")
            b.command(f"M109 S{_i(tnf)}", "wait nozzle")
            b.command("G28", "home")
            b.command("G21")
            b.command("G90")
        b.command("M83" if job.m("relative_e", True) else "M82")

    def _end_gcode(self, b, job):
        raw = (job.m("end_gcode") or "").strip()
        b.set_feature("end", comment=False)
        if raw:
            b.raw(raw)
        else:
            b.command("M104 S0", "nozzle off")
            b.command("M140 S0", "bed off")
            b.command("M107", "fan off")
            b.command("G91")
            b.command("G1 Z10 F600", "lift")
            b.command("G90")
            b.command("M84", "motors off")


def _i(v) -> int:
    try:
        return int(round(float(v)))
    except Exception:
        return 0
