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
        tool_map = {t.id: t for t in job.tools}
        first_id = getattr(job.layers[0], "cam_tool_id", None) if job.layers else None
        tool = tool_map.get(first_id) or (job.tools[0] if job.tools else None)
        safe_z = job.m("safe_z", 15.0)
        feed = tool.get("feed", 800) if tool else job.m("max_feed", 800)
        plunge = tool.get("plunge_feed", 300) if tool else 300
        rpm = tool.get("spindle_rpm", 18000) if tool else job.m("spindle_max", 18000)
        rapid_xy = job.m("rapid_xy", 3000)
        max_feed = float(job.m("max_feed", 0) or 0)
        if not math.isfinite(max_feed) or max_feed < 0:
            raise ValueError("Machine max feed must be nonnegative and finite")
        capped = set()
        last_feed = None
        last_condition = None

        def limited(value):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("CAM cutting/plunge feeds must be positive and finite")
            if max_feed > 0 and value > max_feed:
                capped.add((value, max_feed))
                return max_feed
            return value

        def cut_move(point, condition=None, comment=None, force=False):
            nonlocal last_feed, last_condition
            factor = condition.feed_factor if condition is not None else 1.0
            requested = limited(float(feed)*factor)
            feature = ({"slot": "slot", "high": "high_engagement", "air": "air"}.get(condition.regime, "cut")
                       if condition is not None else "cut")
            b.set_feature(feature)
            note = None
            if condition is not None:
                note = f"{condition.regime} {condition.engagement*100:.0f}% engagement; {condition.hand}"
                key = (condition.regime, condition.hand)
                if key != last_condition and comment is None:
                    comment = note
                last_condition = key
            f = f" F{format_number(requested,1)}" if force or last_feed != requested else ""
            line = b.command(f"G1 X{format_number(point[0],3)} Y{format_number(point[1],3)}{f}", comment)
            if condition is not None:
                line.engagement = condition.engagement
                line.note = note
            last_feed = requested

        self._start(b, job, tool, rpm, safe_z, log=ctx.log)
        b.set_feature("rapid", comment=False)

        n = max(1, len(job.layers))
        previous_group = getattr(job.layers[0], "cam_group", None) if job.layers else None
        for li, layer in enumerate(job.layers):
            b.layer = li
            b.op = getattr(layer, "cam_operation", None)
            b.comment(f"LAYER:{li}")
            group = getattr(layer, "cam_group", None)
            next_tool = tool_map.get(getattr(layer, "cam_tool_id", None), tool)
            if group != previous_group:
                b.set_feature("rapid", comment=False)
                b.command(f"G0 Z{format_number(safe_z,3)}")
                b.command("M5", "spindle off before tool change")
                b.command(f"T{int(next_tool.get('tool_number', 1))} M6")
                b.command(f"M3 S{format_number(next_tool.get('spindle_rpm', 18000),0)}")
                previous_group = group
            tool = next_tool
            feed = tool.get("feed", 800) if tool else feed
            plunge = tool.get("plunge_feed", 300) if tool else plunge
            if hasattr(layer, "cam_operation"):
                b.comment(f"Operation: {layer.cam_operation}")
            previous_end = None   # never carry stay-down permission across depth/operation/tool boundaries
            for path in layer.paths:
                pts = np.asarray(path.points, float)
                if len(pts) < (1 if path.feature == "drill" else 2):
                    continue
                loop = np.vstack([pts, pts[0]]) if path.closed else pts
                start = loop[0]
                linked = (path.stay_down and previous_end is not None and path.stay_down_from is not None
                          and np.allclose(previous_end, path.stay_down_from, atol=1e-7, rtol=0))
                if linked:
                    cut_move(start, path.link_condition, "stay-down link", force=True)
                else:
                    b.set_feature("rapid", comment=False)
                    b.command(f"G0 Z{format_number(safe_z,3)}")
                    b.command(f"G0 X{format_number(start[0],3)} Y{format_number(start[1],3)} "
                              f"F{format_number(rapid_xy,1)}")
                    b.set_feature("plunge", comment=False)
                    b.command(f"G1 Z{format_number(layer.z,3)} F{format_number(limited(float(plunge)),1)}")
                    last_feed = None
                for i, q in enumerate(loop[1:]):
                    condition = path.cut_conditions[i] if i < len(path.cut_conditions) else None
                    cut_move(q, condition, force=i == 0)
                previous_end = loop[-1][:2]
            ctx.progress((li + 1) / n)

        self._end(b, job, safe_z, tool=tool, log=ctx.log)
        prog = b.program()
        prog.machine = "cam"
        prog.layer_z = [l.z for l in job.layers]
        job.program = prog
        if job.cam_setup is not None:
            from ..core.stock import check_stock
            stock_warnings = check_stock(job, prog)
            job.warnings = list(job.warnings) + stock_warnings
            for warning in stock_warnings:
                ctx.log(f"STOCK WARNING: {warning}")
        for request, cap in sorted(capped):
            ctx.log(f"  CAM feed capped: {request:g} -> {cap:g} mm/min (machine max_feed)")
        moves = sum(1 for ln in prog.lines if ln.cmd in ("G0", "G1"))
        return f"{len(prog.lines)} lines, {moves} moves, {len(job.layers)} depth passes"

    def _start(self, b, job, tool, rpm, safe_z, log=None):
        from ..core.gcode_vars import render_box
        b.comment(f"GCodeProducer CAM - {job.machine.name}")
        b.raw(render_box(job, "start_gcode", extra=_tool_variables(tool), log=log).rstrip("\n"))

    def _end(self, b, job, safe_z, tool=None, log=None):
        from ..core.gcode_vars import render_box
        b.set_feature("retract", comment=False)
        last = job.layers[-1] if job.layers else None
        extra = _tool_variables(tool)
        if last is not None:
            extra.update(layer=len(job.layers), layer_z=last.z)
        b.raw(render_box(job, "end_gcode", extra=extra, log=log).rstrip("\n"))


def _tool_variables(tool):
    if tool is None:
        return {}
    return {"tool": int(tool.get("tool_number", 1)), "tool_name": tool.name,
            "tool_diameter": tool.get("diameter", 0), "spindle_rpm": tool.get("spindle_rpm", 18000),
            "feed": tool.get("feed", 800), "plunge_feed": tool.get("plunge_feed", 300)}
