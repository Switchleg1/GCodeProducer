"""CAM stage: emit G-code from the milling toolpaths.

Rapids at safe Z, plunges at the tool plunge feed, cuts at the tool feed, with
spindle control.  Feeds and speeds come from the tool; clearances and rapids
from the machine profile.
"""
from __future__ import annotations

import math

import numpy as np

from ..core.builder import GCodeBuilder
from ..core.gcode import format_number
from .base import CAM, Param, SliceStage


class CAMEmit(SliceStage):
    id = "cam_emit"
    name = "Output"
    description = "Turn the milling toolpaths into G-code with rapids, plunges and spindle control."
    workflows = (CAM,)
    optional = False
    category = "Output"
    params = [
        Param("ramp", "bool", False, label="Ramp entry (reserved)", group="Entry",
              help="Reserved: ramp into cuts instead of a straight plunge."),
    ]

    def run(self, job, params, ctx):
        b = GCodeBuilder(relative_e=False)
        b.e = 0.0
        tool = job.tools[0] if job.tools else None
        safe_z = job.m("safe_z", 15.0)
        feed = tool.get("feed", 800) if tool else job.m("max_feed", 800)
        plunge = tool.get("plunge_feed", 300) if tool else 300
        rpm = tool.get("spindle_rpm", 18000) if tool else job.m("spindle_max", 18000)
        rapid_xy = job.m("rapid_xy", 3000)

        self._start(b, job, tool, rpm, safe_z)
        b.set_feature("rapid", comment=False)

        n = max(1, len(job.layers))
        for li, layer in enumerate(job.layers):
            for path in layer.paths:
                pts = np.asarray(path.points, float)
                if len(pts) < 2:
                    continue
                loop = np.vstack([pts, pts[0]]) if path.closed else pts
                start = loop[0]
                b.set_feature("rapid", comment=False)
                b.command(f"G0 Z{format_number(safe_z,3)}")
                b.command(f"G0 X{format_number(start[0],3)} Y{format_number(start[1],3)} "
                          f"F{format_number(rapid_xy,1)}")
                b.set_feature("plunge", comment=False)
                b.command(f"G1 Z{format_number(layer.z,3)} F{format_number(plunge,1)}")
                b.set_feature("cut", comment=False)
                first = True
                for q in loop[1:]:
                    f = f" F{format_number(feed,1)}" if first else ""
                    b.command(f"G1 X{format_number(q[0],3)} Y{format_number(q[1],3)}{f}")
                    first = False
            ctx.progress((li + 1) / n)

        self._end(b, job, safe_z)
        prog = b.program()
        prog.machine = "cam"
        prog.layer_z = [l.z for l in job.layers]
        job.program = prog
        moves = sum(1 for ln in prog.lines if ln.cmd in ("G0", "G1"))
        return f"{len(prog.lines)} lines, {moves} moves, {len(job.layers)} depth passes"

    def _start(self, b, job, tool, rpm, safe_z):
        raw = (job.m("start_gcode") or "").strip()
        b.comment(f"GCodeProducer CAM - {job.machine.name}")
        if tool:
            b.comment(f"tool T{tool.get('tool_number',1)} {tool.get('type','')} "
                      f"D{tool.get('diameter','?')}")
        if raw:
            b.raw(raw)
        else:
            b.command("G21")
            b.command("G90")
            if tool:
                b.command(f"T{int(tool.get('tool_number',1))} M6", "tool change")
            b.command(f"M3 S{int(round(rpm))}", "spindle on")
            b.command(f"G0 Z{format_number(safe_z,3)}")

    def _end(self, b, job, safe_z):
        raw = (job.m("end_gcode") or "").strip()
        b.set_feature("retract", comment=False)
        if raw:
            b.raw(raw)
        else:
            b.command(f"G0 Z{format_number(safe_z,3)}")
            b.command("M5", "spindle off")
            b.command("G0 X0 Y0")
            b.command("M30", "end")
